// A single decision, and the only screen in the app that can produce a signature.
//
// The order of operations is load-bearing and unchanged:
//
//   1. Fetch the proposal, including the complete `signing_inputs`.
//   2. Recompute `payload_hash` from those inputs, locally, and compare.
//   3. Only if they agree, offer Approve and Reject at all.
//   4. On tap, restate what is about to be signed, take an explicit confirmation, prompt for the
//      handset lock, sign the hash WE derived, verify our own signature, then submit.
//
// Step 2 is what makes device custody more than decoration: if this screen signed the hash the
// server sent, a compromised server could show one action and collect consent for another.
// Step 4's sheet restates the action in the words it will be recorded in, so the thing being
// confirmed is the thing, not the OS prompt's "Q-Vault wants to authenticate you".
//
// The signed text is the largest thing on the screen and the only serif; the title above it is a
// label, set small in sans, because it is not under the hash (S19). The cryptography is one quiet
// row that opens on demand, and its failure takes the screen and withdraws the buttons.
// (P2 rebuilds this frame per phone-ux §6.5: status line first, the evidence sheet, the quorum
// sentence. P1 keeps its content and moves it onto the new components.)

import { useMemo, useRef, useState } from 'react';
import { View } from 'react-native';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  ActionBar,
  Assurance,
  Banner,
  Button,
  Identifier,
  InlineMessage,
  KeyValue,
  List,
  ListRow,
  NavBar,
  PaymentCard,
  Screen,
  Scroll,
  Seal,
  Section,
  Sheet,
  SignedOverlay,
  SignedText,
  Skeleton,
  Text,
  feedback,
} from '../ui/index.tsx';
import { makeStyles } from '../theme/index.ts';
import { decisionStatus } from '../status.ts';
import { expiryPhrase, exactly, urgencyOf, whenAfter, whenPhrase } from '../time.ts';
import { useEnrolledSession } from '../session.tsx';
import * as api from '../api/endpoints.ts';
import { ApiError, TransportError } from '../api/client.ts';
import {
  NoScreenLockError,
  NotThisPhonesSeatError,
  PayloadMismatchError,
  SelfVerificationError,
  verifyProposalIntegrity,
  voteOnProposal,
  type VoteOutcome,
} from '../flows.ts';
import { type Decision, type PaymentAction } from '../crypto/signing.ts';
import type { PayoutView, ProposalDetail, VoteRecord } from '../api/schemas.ts';
import type { Tone } from '../theme/index.ts';

export default function DecisionScreen({ uuid, onBack }: { uuid: string; onBack: () => void }) {
  const s = useStyles();
  const { token, identity, custody } = useEnrolledSession();
  const queryClient = useQueryClient();

  const [pending, setPending] = useState<Decision | null>(null);
  const [outcome, setOutcome] = useState<VoteOutcome | null>(null);
  // What THIS person just did, kept apart from the resulting status: a rejection does not
  // necessarily close a proposal (3 of 4 takes two refusals), so deriving the acknowledgement from
  // `outcome.status` would answer a first refusal with a green tick.
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
        return { ok: false as const, expected: err.expected, actual: err.actual, reason: err.reason };
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
      // The acknowledgement owns the haptic, timed to its tick: firing here too would buzz twice.
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
              tone="warning"
              title="Could not load this decision."
              detail={query.error instanceof Error ? query.error.message : undefined}
            />
          ) : (
            <DecisionSkeleton />
          )}
        </Scroll>
      </Screen>
    );
  }

  // The threshold as signed. The top-level copy is not under the hash (verifyProposalIntegrity
  // refuses a response whose two copies differ), so nothing on this screen reads it.
  const { M: requiredM, N: requiredN } = detail.signing_inputs.policy;

  // The state every other screen shows (`status.ts`): the server's, unless it still says open past
  // the deadline, which happens when this page has been open a while.
  const settled = decisionStatus({ ...detail, required_m: requiredM, required_n: requiredN });
  const tampered = integrity !== null && !integrity.ok;
  const alreadySigned = detail.signed_by_me || outcome !== null;
  const closed = settled !== 'open';
  const canSign = !tampered && !alreadySigned && !closed && detail.can_sign;

  // Counts after this device's own vote, so the marks reflect it before the refetch lands.
  const approvals = outcome?.approvals ?? detail.approvals;
  const status = outcome?.status ?? settled;
  const expiry = expiryPhrase(detail.expires_at);
  const urgency = urgencyOf(detail.expires_at);
  const payment = detail.signing_inputs.action;

  return (
    <Screen edges={['top']}>
      <NavBar onBack={onBack} title={detail.vault_name ?? `Vault ${detail.vault_id}`} />

      <Scroll footerSpace={canSign ? 72 : 0}>
        <View style={s.stack}>
          {tampered ? (
            <Banner
              tone="critical"
              title="This decision does not match its own signature payload."
              detail="Nothing has been signed. Report this before acting on it."
            />
          ) : null}

          {error ? <Banner tone="critical" title={error.title} detail={error.detail} /> : null}

          {/* The title: the name it goes by in every list. Unsigned, so small and in sans; the
              signed text beneath it is the largest thing here and the only words the sheet and the
              prompt repeat (S19). */}
          <Text role="titleSm" tone="muted" accessibilityRole="header">
            {detail.title}
          </Text>
          {/* Always the signed copy: verifyProposalIntegrity refuses a response whose two copies of
              the text disagree. */}
          <SignedText text={detail.signing_inputs.action_text} />
          {payment ? <PaymentCard action={payment} /> : null}
          {payment ? <PaymentFacts action={payment} /> : null}
          {detail.payout ? <Payout payout={detail.payout} /> : null}

          {/* The quorum, under it. `celebrate` only when this person's own signature completed it. */}
          <View style={s.quorum}>
            <Seal
              filled={approvals}
              required={requiredM}
              size={14}
              showCount={false}
              celebrate={outcome !== null && approvals >= requiredM}
            />
            <Text role="body" tone="muted" style={s.flex}>
              {quorumPhrase(approvals, requiredM, status)}
            </Text>
          </View>

          <View style={s.timing}>
            {expiry && status === 'open' ? (
              <Text
                role="caption"
                tone={urgency === 'critical' || urgency === 'expired' ? 'critical' : 'muted'}
              >
                {expiry}
              </Text>
            ) : null}
            <Text role="caption" tone="muted">
              {whenAfter('Raised', detail.signing_inputs.created_at)}
            </Text>
          </View>

          {outcome ? (
            <Banner
              tone={outcome.status === 'rejected' ? 'critical' : 'success'}
              title={
                outcome.status === 'rejected'
                  ? 'You rejected this decision.'
                  : approvals >= requiredM
                    ? 'Signed. The threshold is met.'
                    : 'Signed on this device.'
              }
              detail={`Signature ${outcome.signatureSha256.slice(0, 16)}`}
            />
          ) : null}

          {/* The cryptography: one row when it holds, the whole screen when it does not. */}
          <Assurance ok={!!integrity?.ok}>
            {integrity && !integrity.ok ? (
              <>
                {/* What this phone derived, then what the server claimed. */}
                <KeyValue label="Derived on this phone" mono value={integrity.actual} />
                <KeyValue label="Server stated" mono value={integrity.expected} />
                <KeyValue label="Failed check" value={MISMATCH_REASON[integrity.reason]} />
              </>
            ) : (
              <KeyValue
                label="Payload hash"
                mono
                value={integrity?.ok ? integrity.hash : detail.payload_hash}
              />
            )}
            <KeyValue label="Nonce" mono value={detail.signing_inputs.nonce} />
            <KeyValue
              label="Attached file"
              mono={detail.signing_inputs.file_sha256 !== null}
              value={detail.signing_inputs.file_sha256 ?? 'No attachment'}
            />
            <KeyValue label="Signing key" value={identity.algId} />
            <KeyValue label="This device" mono value={identity.fingerprint} />
            <KeyValue label="Policy" value={`${requiredM} of ${requiredN} authorised signers`} />
            <KeyValue label="Raised" value={exactly(detail.signing_inputs.created_at)} />
          </Assurance>
        </View>

        <Section title={detail.votes.length === 1 ? 'One signature' : `${detail.votes.length} signatures`}>
          {detail.votes.length === 0 ? (
            <Text role="body" tone="muted">
              No one has signed this yet.
            </Text>
          ) : (
            <List>
              {detail.votes.map((v, i) => (
                <VoteRow key={`${v.signer_id}-${i}`} vote={v} />
              ))}
            </List>
          )}
        </Section>

        {!canSign && !tampered ? (
          <View style={s.standing}>
            <InlineMessage
              tone={standingTone(alreadySigned, status)}
              text={standingLabel({ alreadySigned, closed, status, canSignPolicy: detail.can_sign })}
            />
          </View>
        ) : null}
      </Scroll>

      {canSign ? (
        <ActionBar
          secondary={{
            label: 'Reject',
            variant: 'dangerSecondary',
            onPress: () => setPending('reject'),
            disabled: vote.isPending,
          }}
          primary={{ label: 'Approve', onPress: () => setPending('approve'), disabled: vote.isPending }}
        />
      ) : null}

      <ConfirmSheet
        decision={pending}
        detail={detail}
        busy={vote.isPending}
        onCancel={() => setPending(null)}
        onConfirm={() => pending && vote.mutate(pending)}
      />

      {/* The acknowledgement. Stays until dismissed: someone who signed and put the phone down
          should still be told what happened when they look at it again. */}
      <SignedOverlay
        visible={confirming && outcome !== null}
        approved={voted === 'approve'}
        filled={approvals}
        required={requiredM}
        onDone={() => setConfirming(false)}
      />
    </Screen>
  );
}

/**
 * The restatement: the action text verbatim, never a summary. A summary would be a second,
 * unsigned description sitting beside the signed one, and the moment the two disagree the
 * confirmation is confirming the wrong sentence.
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
  const completes = approving && detail.approvals + 1 >= detail.signing_inputs.policy.M;
  const payment = detail.signing_inputs.action;
  // Kept while the sheet animates out, so it does not flash to the other title on its way down.
  const last = useRef<Decision>('approve');
  if (decision) last.current = decision;
  const showing = decision ?? last.current;
  const isApprove = showing === 'approve';

  return (
    <Sheet
      visible={decision !== null}
      onClose={onCancel}
      dismissible={!busy}
      title={isApprove ? 'Approve this decision' : 'Reject this decision'}
      footer={
        <>
          <Text role="caption" tone="muted">
            {isApprove && payment
              ? 'Your approval also signs the payment exactly as shown, which the treasury checks on chain before it pays. It cannot be withdrawn.'
              : isApprove
                ? completes
                  ? 'Yours is the signature that meets the threshold. Once it is recorded the decision is approved and cannot be withdrawn.'
                  : 'Your signature is recorded against this decision and cannot be withdrawn.'
                : 'Your rejection is recorded against this decision and cannot be withdrawn.'}
          </Text>
          <Button
            label={isApprove ? 'Sign approval' : 'Sign rejection'}
            variant={isApprove ? 'primary' : 'danger'}
            onPress={onConfirm}
            busy={busy}
            full
          />
          <Button label="Cancel" variant="quiet" onPress={onCancel} disabled={busy} full />
        </>
      }
    >
      <SignedText text={detail.signing_inputs.action_text} size="decision" />
      {payment ? <PaymentCard action={payment} place="sheet" /> : null}
      {payment ? <PaymentFacts action={payment} /> : null}
    </Sheet>
  );
}

/**
 * The payment's other signed fields, read from `signing_inputs.action`, never the server's display
 * copy. (P2 moves the treasury and the time limit into the evidence sheet, §5.12.)
 */
function PaymentFacts({ action }: { action: PaymentAction }) {
  const s = useStyles();
  return (
    <View style={s.facts}>
      <Identifier label="From treasury" value={action.treasury} />
      <KeyValue label="Approvals valid until" value={exactly(new Date(action.valid_until * 1000).toISOString())} />
    </View>
  );
}

const PAYOUT_LABEL: Record<string, [string, Tone]> = {
  awaiting_approvals: ['Paid once approved', 'neutral'],
  queued: ['Payout queued', 'info'],
  submitting: ['Payout being sent', 'info'],
  confirmed: ['Paid', 'success'],
  expired: ['Not paid: its approvals expired', 'critical'],
  voided: ['Not paid: the treasury changed', 'critical'],
  failed: ['Payout failed', 'critical'],
  not_paid: ['Not paid', 'neutral'],
};

/** How the payout stands (plan Phase 8): the server's account, shown and never signed. */
function Payout({ payout }: { payout: PayoutView }) {
  const s = useStyles();
  const [label, tone] = PAYOUT_LABEL[payout.state] ?? ['Payout state unknown', 'neutral'];
  return (
    <View style={s.facts}>
      <InlineMessage tone={tone} text={label} />
      {payout.state !== 'confirmed' && payout.reason ? (
        <Text role="caption" tone="muted">
          {payout.reason}
        </Text>
      ) : null}
      <KeyValue label="Payment authorisations" value={`${payout.execution_signatures} of ${payout.needed}`} />
      {payout.tx_hash ? <Identifier label="Transaction" value={payout.tx_hash} /> : null}
      {payout.block_number !== null ? (
        <KeyValue label="Block" value={payout.block_number.toLocaleString('en-GB')} />
      ) : null}
      {payout.gas_used !== null ? <KeyValue label="Gas" value={payout.gas_used.toLocaleString('en-GB')} /> : null}
    </View>
  );
}

function VoteRow({ vote }: { vote: VoteRecord }) {
  const approved = vote.decision === 'approve';
  // Both custody models are named: OWNER-ACTIONS §3.3 has one person approve from the app and one
  // from the web, so a single record shows a device-held key and a server-held key side by side.
  return (
    <ListRow
      title={vote.signer_name ?? `Signer ${vote.signer_id}`}
      caption={`${whenPhrase(vote.signed_at)}, ${vote.custody === 'device' ? 'key held on their device' : 'key held on the server'}`}
      value={approved ? 'Approved' : 'Rejected'}
      valueTone={approved ? 'success' : 'critical'}
    />
  );
}

/** The decision's shape while it loads: a title, five lines of text, the quorum (§6.6). */
function DecisionSkeleton() {
  const s = useStyles();
  return (
    <View style={s.stack}>
      <Skeleton width="45%" height={16} />
      <Skeleton width="95%" height={22} />
      <Skeleton width="90%" height={22} />
      <Skeleton width="70%" height={22} />
      <Skeleton width={140} height={14} />
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

function standingTone(alreadySigned: boolean, status: string): Tone {
  if (alreadySigned) return 'success';
  if (status === 'approved') return 'success';
  if (status === 'rejected') return 'critical';
  return 'neutral';
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
    return { title: 'Refused to sign.', detail: 'This decision does not match its own signature payload.' };
  }
  if (err instanceof SelfVerificationError) {
    return { title: err.message, detail: 'Enrol this device again to replace the key.' };
  }
  if (err instanceof NotThisPhonesSeatError) {
    return { title: 'Not signed on this phone.', detail: err.message };
  }
  if (err instanceof NoScreenLockError) {
    return { title: err.message, detail: 'Q-Vault asks for it before every signature. Nothing was signed.' };
  }
  if (err instanceof Error && err.name === 'AuthenticationCancelled') {
    return { title: 'Nothing was signed.' };
  }
  // Not folded into the line above: a device that cannot ask is a different problem from a person
  // who declined, and "nothing was signed" to a locked-out sensor sends them round the same loop.
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
      case 'chain_unavailable':
        // D43: a retry, not a failure. Nothing was stored.
        return { title: 'Ethereum did not answer. Nothing was signed.', detail: 'Try again in a moment.' };
      case 'proposal_closed':
        return { title: 'This decision is closed.', detail: 'It takes no further votes.' };
      case 'not_a_signer':
        return { title: 'You are not an authorised signer on this decision.' };
      case 'device_key_not_active':
        return { title: 'This device key is no longer active.', detail: 'Enrol this device again.' };
      case 'signature_invalid':
        return { title: 'The server rejected the signature.', detail: 'Enrol this device again if this keeps happening.' };
      default:
        return { title: err.message };
    }
  }
  if (err instanceof TransportError) return { title: err.message };
  return { title: err instanceof Error ? err.message : 'Something went wrong.' };
}

/** Which integrity check refused the decision, in the words the Assurance drawer shows. */
const MISMATCH_REASON: Record<PayloadMismatchError['reason'], string> = {
  hash: 'The contents do not hash to the stated payload hash',
  payment_text: 'The text describes a different payment from the one signed',
  display_text: 'The text sent for display is not the text that would be signed',
  display_policy: 'The approval threshold sent for display is not the one that would be signed',
};

const useStyles = makeStyles((t) => ({
  flex: { flex: 1 },
  stack: { gap: t.space[16], paddingTop: t.space[8] },
  quorum: { flexDirection: 'row', alignItems: 'center', gap: t.space[12], marginTop: t.space[8] },
  timing: { flexDirection: 'row', flexWrap: 'wrap', columnGap: t.space[16], marginTop: -t.space[8] },
  facts: { gap: t.space[4] },
  standing: { marginTop: t.space[24] },
}));
