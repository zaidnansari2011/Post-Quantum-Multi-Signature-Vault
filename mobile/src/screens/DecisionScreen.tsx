// A single decision, and the only screen in the app that can produce a signature.
//
// The order of operations is load-bearing and is unchanged from the previous version:
//
//   1. Fetch the proposal, including the complete `signing_inputs`.
//   2. Recompute `payload_hash` from those inputs, locally, and compare.
//   3. Only if they agree, offer Approve and Reject at all.
//   4. On tap, restate what is about to be signed, take an explicit confirmation, prompt for the
//      handset lock, sign the hash WE derived, verify our own signature, then submit.
//
// Step 2 is what makes device custody more than decoration: if this screen signed the hash the
// server sent, a compromised server could show one action and collect consent for another, and
// keeping the private key off that server would prove nothing at all.
//
// Step 4 is new. The old screen went from tap to biometric prompt with nothing in between, which
// meant the last thing a person read before committing was an OS dialog that says "Q-Vault wants
// to authenticate you" -- a sentence about identity, not about the decision. The sheet restates
// the action in the words it will be recorded in, so the thing being confirmed is the thing.
//
// WHAT MOVED, presentationally. The decision used to be one paragraph in a panel called "Action",
// with a six-row "Payload" panel of equal weight beneath it. Now the decision is the largest thing
// on the screen and the cryptography is a single line that opens on demand -- see Assurance.tsx
// for the full argument. No check was weakened to do this; `verifyProposalIntegrity` runs on every
// render exactly as before, and its failure still takes over the screen and withdraws the buttons.

import { useMemo, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  ActionBar,
  Banner,
  Button,
  Card,
  Chip,
  Divider,
  Hash,
  KeyValue,
  Loading,
  NavBar,
  Row,
  Screen,
  Scroll,
  Seal,
  Section,
  feedback,
} from '../ui/index.tsx';
import { Assurance } from '../ui/Assurance.tsx';
import { Sheet } from '../ui/Sheet.tsx';
import { SignedOverlay } from '../ui/SignedOverlay.tsx';
import { color, space, statusTone, type } from '../theme.ts';
import { expiryPhrase, exactly, urgencyOf, whenPhrase } from '../time.ts';
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

export default function DecisionScreen({ uuid, onBack }: { uuid: string; onBack: () => void }) {
  const { token, identity, custody } = useEnrolledSession();
  const queryClient = useQueryClient();

  const [pending, setPending] = useState<Decision | null>(null);
  const [outcome, setOutcome] = useState<VoteOutcome | null>(null);
  // What THIS person just did, kept separately from the proposal's resulting status. Deriving the
  // acknowledgement from `outcome.status` would be wrong: a rejection does not necessarily close a
  // proposal -- with a 3-of-4 policy it takes two refusals before approval is arithmetically out of
  // reach -- so the first rejection leaves the status "open" and the overlay would answer a refusal
  // with a green tick.
  const [voted, setVoted] = useState<Decision | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<{ title: string; detail?: string } | null>(null);

  const query = useQuery({
    queryKey: ['proposal', uuid],
    queryFn: ({ signal }) => api.fetchProposal(token, uuid, signal),
  });
  const detail = query.data?.proposal;

  // Recomputed on every render of a loaded proposal, not once on mount: the value shown beside the
  // hash must describe the data currently on screen, including after a refetch.
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
    onSuccess: (result, decision) => {
      setOutcome(result);
      setVoted(decision);
      setError(null);
      setPending(null);
      // The confirmation owns the haptic, not this handler. It fires as the tick finishes drawing
      // rather than as the response arrives, so what the hand feels and what the eye sees are the
      // same event. Firing here as well would buzz twice for one signature.
      setConfirming(true);
      void queryClient.invalidateQueries({ queryKey: ['proposals'] });
      void queryClient.invalidateQueries({ queryKey: ['proposal', uuid] });
    },
    onError: (err) => {
      setError(describe(err));
      setPending(null);
      feedback.refused();
    },
  });

  if (query.isLoading || !detail) {
    return (
      <Screen>
        <NavBar onBack={onBack} />
        <Scroll>
          {query.error ? (
            <Banner
              tone="broken"
              title="Could not load this decision."
              detail={query.error instanceof Error ? query.error.message : undefined}
            />
          ) : (
            <Loading label="Loading decision" />
          )}
        </Scroll>
      </Screen>
    );
  }

  const tampered = integrity !== null && !integrity.ok;
  const alreadySigned = detail.signed_by_me || outcome !== null;
  const closed = detail.status !== 'open';
  const canSign = !tampered && !alreadySigned && !closed && detail.can_sign;

  // Counts after this device's own vote, so the marks reflect what just happened without waiting
  // for the refetch to land.
  const approvals = outcome?.approvals ?? detail.approvals;
  const status = outcome?.status ?? detail.status;
  const expiry = expiryPhrase(detail.expires_at);
  const urgency = urgencyOf(detail.expires_at);

  return (
    <Screen edges={['top']}>
      <NavBar onBack={onBack} title={detail.vault_name ?? `Vault ${detail.vault_id}`} />

      <Scroll footerSpace={canSign ? 128 : 0}>
        {tampered ? (
          <View style={{ marginBottom: space.lg }}>
            <Banner
              tone="broken"
              title="This decision does not match its own signature payload."
              detail="Nothing has been signed. Report this before acting on it."
            />
          </View>
        ) : null}

        {error ? (
          <View style={{ marginBottom: space.lg }}>
            <Banner tone="broken" title={error.title} detail={error.detail} />
          </View>
        ) : null}

        {/* The decision. The only serif on the screen, and sized to its own length.
            A real decision in this system is not the one-line sentence the first draft assumed --
            it is a structured authorisation with a beneficiary, an instrument, a window and a
            scope note, running to several paragraphs. At the display size that suits "Release the
            escrow payment", that content fills the screen twice over and pushes the quorum, the
            deadline and the buttons below the fold, so the reader has to scroll to find out what
            they are even being asked. Long decisions step down to a reading size and hand the
            screen's moment of scale to the quorum instead, which is where it belongs once the text
            is a document rather than a sentence. */}
        <Text style={detail.action_text.length > LONG_DECISION ? s.decisionLong : s.decision}>
          {detail.action_text}
        </Text>

        {/* The quorum, immediately under it. `celebrate` is true only when this person's own
            signature is what completed it -- animating a decision that was already complete when
            they arrived would claim it happened in front of them. */}
        <View style={s.quorum}>
          <Seal
            filled={approvals}
            required={detail.required_m}
            size={13}
            celebrate={outcome !== null && approvals >= detail.required_m}
          />
          <Text style={s.quorumText}>{quorumPhrase(approvals, detail.required_m, status)}</Text>
        </View>

        <Row gap={space.md} style={{ marginTop: space.sm, flexWrap: 'wrap' }}>
          {expiry && status === 'open' ? (
            <Text style={[s.timing, urgency === 'critical' || urgency === 'expired' ? { color: color.broken } : null]}>
              {expiry}
            </Text>
          ) : null}
          <Text style={s.timing}>Raised {whenPhrase(detail.signing_inputs.created_at)}</Text>
        </Row>

        {outcome ? (
          <View style={{ marginTop: space.lg }}>
            <Banner
              tone={outcome.status === 'rejected' ? 'broken' : 'sealed'}
              title={
                outcome.status === 'rejected'
                  ? 'You rejected this decision.'
                  : approvals >= detail.required_m
                    ? 'Signed. The threshold is met.'
                    : 'Signed on this device.'
              }
              detail={`Signature ${outcome.signatureSha256.slice(0, 16)}`}
            />
          </View>
        ) : null}

        {/* The cryptography: one line when it holds, the whole screen when it does not. */}
        <View style={{ marginTop: space.xl }}>
          <Assurance ok={!!integrity?.ok}>
            <KeyValue label="Payload hash" mono value={integrity?.ok ? integrity.hash : detail.payload_hash} />
            {!integrity?.ok && integrity ? (
              <KeyValue label="Server stated" mono value={integrity.expected} />
            ) : null}
            <KeyValue label="Nonce" mono value={detail.signing_inputs.nonce} />
            <KeyValue
              label="Attached file"
              mono={detail.signing_inputs.file_sha256 !== null}
              value={detail.signing_inputs.file_sha256 ?? 'No attachment'}
            />
            <KeyValue label="Signing key" value={identity.algId} />
            <KeyValue label="This device" mono value={identity.fingerprint} />
            <KeyValue
              label="Policy"
              value={`${detail.required_m} of ${detail.required_n} authorised signers`}
            />
            <KeyValue label="Raised" value={exactly(detail.signing_inputs.created_at)} />
          </Assurance>
        </View>

        <Section title={detail.votes.length === 1 ? 'One signature' : `${detail.votes.length} signatures`}>
          {detail.votes.length === 0 ? (
            <Text style={s.none}>No one has signed this yet.</Text>
          ) : (
            <Card>
              {detail.votes.map((v, i) => (
                <View key={`${v.signer_id}-${i}`}>
                  {i > 0 ? <Divider /> : null}
                  <VoteRow vote={v} />
                </View>
              ))}
            </Card>
          )}
        </Section>

        {!canSign && !tampered ? (
          <View style={{ marginTop: space.lg, alignItems: 'flex-start' }}>
            <Chip
              label={standingLabel({ alreadySigned, closed, status, canSignPolicy: detail.can_sign })}
              tone={alreadySigned ? 'sealed' : statusTone(status)}
            />
          </View>
        ) : null}
      </Scroll>

      {canSign ? (
        <ActionBar>
          <Button label="Approve" onPress={() => setPending('approve')} disabled={vote.isPending} />
          <Button
            label="Reject"
            variant="danger"
            onPress={() => setPending('reject')}
            disabled={vote.isPending}
          />
        </ActionBar>
      ) : null}

      <ConfirmSheet
        decision={pending}
        detail={detail}
        busy={vote.isPending}
        onCancel={() => setPending(null)}
        onConfirm={() => pending && vote.mutate(pending)}
      />

      {/* The acknowledgement. Stays until dismissed rather than timing out: someone who signed and
          immediately put the phone down should still be told what happened when they look at it
          again. The banner left behind on the page underneath is the durable record of it. */}
      <SignedOverlay
        visible={confirming && outcome !== null}
        approved={voted === 'approve'}
        filled={approvals}
        required={detail.required_m}
        onDone={() => setConfirming(false)}
      />
    </Screen>
  );
}

/**
 * The restatement.
 *
 * It repeats the action text verbatim rather than summarising it. A summary would be a second,
 * unsigned description of the decision sitting next to the signed one, and the moment those two
 * disagree -- through a truncation, a rewording, anything -- the confirmation is confirming the
 * wrong sentence.
 */
function ConfirmSheet({
  decision,
  detail,
  busy,
  onCancel,
  onConfirm,
}: {
  decision: Decision | null;
  detail: ProposalDetail;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const approving = decision === 'approve';
  const completes = approving && detail.approvals + 1 >= detail.required_m;

  return (
    <Sheet
      visible={decision !== null}
      onClose={onCancel}
      dismissible={!busy}
      title={approving ? 'Approve this decision' : 'Reject this decision'}
    >
      <Text style={s.confirmAction}>{detail.action_text}</Text>

      <Text style={s.confirmNote}>
        {approving
          ? completes
            ? 'Yours is the signature that meets the threshold. Once it is recorded the decision is approved and cannot be withdrawn.'
            : 'Your signature is recorded against this decision and cannot be withdrawn.'
          : 'Your rejection is recorded against this decision and cannot be withdrawn.'}
      </Text>

      <View style={{ gap: space.sm, marginTop: space.xs }}>
        <Button
          label={approving ? 'Sign approval' : 'Sign rejection'}
          variant={approving ? 'primary' : 'danger'}
          onPress={onConfirm}
          busy={busy}
        />
        <Button label="Cancel" variant="quiet" onPress={onCancel} disabled={busy} />
      </View>
    </Sheet>
  );
}

function VoteRow({ vote }: { vote: VoteRecord }) {
  const approved = vote.decision === 'approve';
  return (
    <View style={s.vote}>
      <View style={{ flex: 1, gap: 2 }}>
        <Text style={s.voteName} numberOfLines={1}>
          {vote.signer_name ?? `Signer ${vote.signer_id}`}
        </Text>
        {/* Both custody models are named, not just the device one. OWNER-ACTIONS §3.3 turns on
            this line: the demo has one person approve from the app and another from the web UI, so
            that a single record shows a device-held key and a server-held key side by side. If
            only `device` were labelled, the server case would read as missing data rather than as
            the other half of the comparison. */}
        <Text style={s.voteMeta} numberOfLines={1}>
          {whenPhrase(vote.signed_at)}
          {vote.custody === 'device' ? ', key held on their device' : ', key held on the server'}
        </Text>
      </View>
      <Text style={[s.voteDecision, { color: approved ? color.sealed : color.broken }]}>
        {approved ? 'Approved' : 'Rejected'}
      </Text>
    </View>
  );
}

function quorumPhrase(filled: number, required: number, status: string): string {
  if (status === 'approved' || filled >= required) return 'Threshold met';
  if (status === 'rejected') return 'Rejected';
  if (status === 'expired') return 'Expired before the threshold was met';
  const left = required - filled;
  return left === 1 ? 'One more signature needed' : `${left} more signatures needed`;
}

function standingLabel({
  alreadySigned,
  closed,
  status,
  canSignPolicy,
}: {
  alreadySigned: boolean;
  closed: boolean;
  status: string;
  canSignPolicy: boolean;
}): string {
  if (alreadySigned) return 'You have signed this';
  if (closed) return status === 'approved' ? 'Approved' : status === 'rejected' ? 'Rejected' : 'Expired';
  if (!canSignPolicy) return 'You are not an authorised signer';
  return 'No action available';
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
  // Deliberately NOT folded into the line above: a device that cannot ask is a different problem
  // from a person who declined, and telling someone "nothing was signed" when their sensor is
  // locked out sends them round the same loop forever.
  if (err instanceof Error && err.name === 'AuthenticationUnavailable') {
    const reason = (err as { reason?: string }).reason;
    return {
      title: 'This device could not verify you.',
      detail:
        reason === 'lockout' || reason === 'not_enrolled'
          ? 'Unlock your phone with your PIN, then try again.'
          : 'Check that a screen lock or biometric is set up on this phone.',
    };
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
        return { title: 'This device key is no longer active.', detail: 'Enrol this device again.' };
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

/**
 * Where a decision stops being a sentence and starts being a document.
 *
 * ~180 characters is about three lines at the display size on a narrow handset. Past that, the
 * large setting stops feeling emphatic and starts feeling like a wall.
 */
const LONG_DECISION = 180;

const s = StyleSheet.create({
  decision: { ...type.decision, marginTop: space.sm },
  decisionLong: { ...type.decisionSm, fontSize: 16.5, lineHeight: 26, marginTop: space.sm },
  quorum: { flexDirection: 'row', alignItems: 'center', gap: space.md, marginTop: space.xl },
  quorumText: { ...type.body, color: color.ink2 },
  timing: { ...type.meta },
  none: { ...type.meta },

  vote: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: space.md,
    paddingVertical: space.md,
  },
  voteName: { ...type.body },
  voteMeta: { ...type.micro },
  voteDecision: { ...type.micro, fontSize: 12.5 },

  confirmAction: { ...type.decisionSm, fontSize: 18, lineHeight: 27 },
  confirmNote: { ...type.meta, lineHeight: 19 },
});
