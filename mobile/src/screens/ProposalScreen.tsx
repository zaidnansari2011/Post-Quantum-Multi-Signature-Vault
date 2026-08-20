// A single decision, and the only screen that can produce a signature.
//
// The order of operations here is load-bearing:
//
//   1. Fetch the proposal, including the complete `signing_inputs`.
//   2. Recompute `payload_hash` from those inputs, locally, and compare.
//   3. Only if they agree, offer Approve and Reject at all.
//   4. On tap, prompt for the handset lock, sign the hash WE derived, verify our own signature,
//      then submit.
//
// Step 2 is what makes device custody more than decoration. If this screen signed the hash the
// server sent, a compromised server could show one action and collect consent for another, and
// keeping the private key off that server would prove nothing at all.

import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { StyleSheet, Text, View } from 'react-native';

import {
  Banner,
  Body,
  Button,
  Chip,
  Hash,
  Header,
  Loading,
  Meta,
  Panel,
  Row,
  Screen,
} from '../ui/index.tsx';
import { color, space, statusTone, type } from '../theme.ts';
import { useEnrolledSession } from '../session.tsx';
import * as api from '../api/endpoints.ts';
import { ApiError, TransportError } from '../api/client.ts';
import {
  PayloadMismatchError,
  SelfVerificationError,
  verifyProposalIntegrity,
  voteOnProposal,
  type VoteOutcome,
} from '../flows.ts';
import type { Decision } from '../crypto/signing.ts';
import type { ProposalDetail, VoteRecord } from '../api/schemas.ts';

export default function ProposalScreen({ uuid, onBack }: { uuid: string; onBack: () => void }) {
  const { token, identity, custody } = useEnrolledSession();
  const queryClient = useQueryClient();
  const [outcome, setOutcome] = useState<VoteOutcome | null>(null);
  const [error, setError] = useState<{ title: string; detail?: string } | null>(null);

  const query = useQuery({
    queryKey: ['proposal', uuid],
    queryFn: ({ signal }) => api.fetchProposal(token, uuid, signal),
  });
  const detail = query.data?.proposal;

  // Recomputed on every render of a loaded proposal, not once on mount: the value shown next to
  // the hash must describe the data currently on screen, including after a refetch.
  const integrity = useMemo(() => {
    if (!detail) return null;
    try {
      return { ok: true as const, hash: verifyProposalIntegrity(detail) };
    } catch (err) {
      if (err instanceof PayloadMismatchError) {
        return { ok: false as const, expected: err.expected, actual: err.actual };
      }
      throw err;
    }
  }, [detail]);

  const vote = useMutation({
    mutationFn: async (decision: Decision) => {
      if (!detail) throw new Error('Proposal is still loading.');
      return voteOnProposal({ custody, token, identity, detail, decision });
    },
    onSuccess: (result) => {
      setOutcome(result);
      setError(null);
      void queryClient.invalidateQueries({ queryKey: ['proposals'] });
      void queryClient.invalidateQueries({ queryKey: ['proposal', uuid] });
    },
    onError: (err) => setError(describe(err)),
  });

  if (query.isLoading || !detail) {
    return (
      <Screen>
        <Header title="Decision" onBack={onBack} />
        <Body>
          {query.error ? (
            <Banner
              tone="broken"
              title="Could not load this decision."
              detail={query.error instanceof Error ? query.error.message : undefined}
            />
          ) : (
            <Loading label="Loading decision" />
          )}
        </Body>
      </Screen>
    );
  }

  const tampered = integrity !== null && !integrity.ok;
  const alreadySigned = detail.signed_by_me;
  const closed = detail.status !== 'open';
  const canSign = !tampered && !alreadySigned && !closed && detail.can_sign;

  return (
    <Screen>
      <Header
        title={detail.title}
        subtitle={detail.vault_name ?? `Vault ${detail.vault_id}`}
        onBack={onBack}
        figure={`${detail.approvals}/${detail.required_m}`}
        figureLabel={`approved · ${detail.required_m}-of-${detail.required_n} required`}
      />
      <Body>
        {tampered && integrity ? (
          <Banner
            tone="broken"
            title="This decision does not match its own signature payload."
            detail="Nothing has been signed. Report this before acting on it."
          />
        ) : null}

        {error ? <Banner tone="broken" title={error.title} detail={error.detail} /> : null}

        {outcome ? (
          <Banner
            tone={outcome.status === 'rejected' ? 'broken' : 'sealed'}
            title={`Signed on this device · ${outcome.approvals} of ${detail.required_m} approved`}
            detail={`${outcome.algId ?? identity.algId} · signature ${outcome.signatureSha256.slice(0, 16)}`}
          />
        ) : null}

        <Panel title="Action">
          <Text style={s.action}>{detail.action_text}</Text>
        </Panel>

        <Panel title="Payload">
          <Meta label="Verified">
            {integrity?.ok ? (
              <Chip label="Recomputed on this device" tone="sealed" />
            ) : (
              <Chip label="Does not match" tone="broken" />
            )}
          </Meta>
          <Meta label="Payload hash">
            <Hash value={integrity?.ok ? integrity.hash : detail.payload_hash} />
          </Meta>
          <Meta label="Nonce" value={detail.signing_inputs.nonce} mono />
          <Meta
            label="File"
            value={detail.signing_inputs.file_sha256 ?? 'No attachment'}
            mono={detail.signing_inputs.file_sha256 !== null}
          />
          <Meta label="Created" value={formatWhen(detail.signing_inputs.created_at)} />
          <Meta label="Signers" value={`${detail.signing_inputs.policy.signers.length} authorised`} />
        </Panel>

        <Panel title={`Votes (${detail.votes.length})`}>
          {detail.votes.length === 0 ? (
            <Text style={s.none}>No signatures yet.</Text>
          ) : (
            detail.votes.map((v, i) => <VoteRow key={`${v.signer_id}-${i}`} vote={v} />)
          )}
        </Panel>

        {canSign ? (
          <View style={s.actions}>
            <Button
              label="Approve"
              onPress={() => vote.mutate('approve')}
              busy={vote.isPending}
              disabled={vote.isPending}
            />
            <Button
              label="Reject"
              variant="danger"
              onPress={() => vote.mutate('reject')}
              busy={vote.isPending}
              disabled={vote.isPending}
            />
          </View>
        ) : (
          <View style={s.actions}>
            <Chip
              label={
                tampered
                  ? 'Signing blocked'
                  : alreadySigned
                    ? 'You have signed this'
                    : closed
                      ? `Closed · ${detail.status}`
                      : 'You are not an authorised signer'
              }
              tone={tampered ? 'broken' : alreadySigned ? 'sealed' : 'neutral'}
            />
          </View>
        )}
      </Body>
    </Screen>
  );
}

function VoteRow({ vote }: { vote: VoteRecord }) {
  return (
    <View style={s.vote}>
      <View style={s.voteMain}>
        <Text style={s.voteName} numberOfLines={1}>
          {vote.signer_name ?? `Signer ${vote.signer_id}`}
        </Text>
        <Text style={s.voteMeta} numberOfLines={1}>
          {vote.alg_id ?? 'unknown'} · {formatWhen(vote.signed_at)}
        </Text>
      </View>
      <Row gap={6}>
        {/* Custody is the fact this whole project is about, so it reads as ordinary metadata. */}
        <Chip label={vote.custody === 'device' ? 'device key' : 'server key'} />
        <Chip
          label={vote.decision}
          tone={vote.decision === 'approve' ? 'sealed' : 'broken'}
        />
      </Row>
    </View>
  );
}

function formatWhen(iso: string | null): string {
  if (!iso) return '—';
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  return at.toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function describe(err: unknown): { title: string; detail?: string } {
  if (err instanceof PayloadMismatchError) {
    return {
      title: 'Refused to sign.',
      detail: 'This decision does not match its own signature payload.',
    };
  }
  if (err instanceof SelfVerificationError) {
    return { title: err.message, detail: 'Enrol this device again to replace the key.' };
  }
  if (err instanceof Error && err.name === 'AuthenticationCancelled') {
    return { title: 'Nothing was signed.' };
  }
  if (err instanceof ApiError) {
    switch (err.code) {
      case 'already_voted':
        return { title: 'You have already signed this decision.' };
      case 'proposal_closed':
        return { title: 'This decision is closed.', detail: 'It takes no further votes.' };
      case 'not_a_signer':
        return { title: 'You are not an authorised signer on this decision.' };
      case 'device_key_not_active':
        return {
          title: 'This device key is no longer active.',
          detail: 'Enrol this device again.',
        };
      case 'signature_invalid':
        return {
          title: 'The server rejected the signature.',
          detail: 'Enrol this device again if this keeps happening.',
        };
      default:
        return { title: err.message };
    }
  }
  if (err instanceof TransportError) return { title: err.message };
  return { title: err instanceof Error ? err.message : 'Something went wrong.' };
}

const s = StyleSheet.create({
  action: { ...type.body, fontSize: 15, lineHeight: 22 },
  none: { ...type.meta },
  actions: { gap: space.sm, marginTop: space.xs },
  vote: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: space.sm,
    paddingVertical: space.sm,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: color.rule2,
  },
  voteMain: { flex: 1 },
  voteName: { ...type.body },
  voteMeta: { ...type.meta, fontSize: 11.5 },
});
