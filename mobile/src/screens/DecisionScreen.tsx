// A single decision, and the only screen in the app that can produce a signature (phone-ux §6.5).
//
// The order of operations is load-bearing and unchanged:
//
//   1. Fetch the decision, including the complete `signing_inputs`.
//   2. Recompute `payload_hash` from those inputs, here, and run every other check (checks.ts).
//   3. Only if they all hold, offer Approve and Reject at all. A decision that fails offers no
//      signing whatsoever, not even Reject (D7): the phone signs over a hash it derived itself, and
//      when that disagrees with the server's there is nothing verified to sign.
//   4. On tap, restate what is about to be signed, prompt for the handset lock, sign the hash WE
//      derived, verify our own signature, then submit (flows.ts, which checks again first).
//
// What the page says and allows comes from one place, `personalStatus()` (§6.6), never from flags
// worked out here: the action bar shows Approve only when it returns `sign`. A status this app does
// not know reads "Unknown" and offers nothing.
//
// Top to bottom: the status line (badge, due time, one personal sentence); the title, small and in
// sans because it is not signed (S19); what you sign, in the serif, or a payment's amount and
// recipient; the quorum and its sentence; who decided; "Checked on this phone" with the code; and
// Details. Everything else is one tap away in the evidence sheet.

import { useEffect, useMemo, useRef, useState } from 'react';
import { Linking, Platform, Share, View, type LayoutChangeEvent } from 'react-native';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import Constants from 'expo-constants';

import {
  ActionBar,
  Banner,
  Button,
  DisclosureRow,
  EmptyState,
  Field,
  Icon,
  InlineMessage,
  List,
  ListRow,
  NavBar,
  PaymentCard,
  Screen,
  Scroll,
  Seal,
  Sheet,
  SignedOverlay,
  SignedText,
  Skeleton,
  StatusLine,
  Text,
  TextLink,
  feedback,
} from '../ui/index.tsx';
import { makeStyles, useTheme } from '../theme/index.ts';
import { decisionStatus } from '../status.ts';
import { parseInstant, whenAfter } from '../time.ts';
import { useEnrolledSession } from '../session.tsx';
import * as api from '../api/endpoints.ts';
import { ApiError, TransportError } from '../api/client.ts';
import { getApiBaseUrl } from '../config.ts';
import { retryTransport } from '../approvals.ts';
import { checkDecision, type Checked } from '../checks.ts';
import {
  NoScreenLockError,
  NotThisPhonesSeatError,
  PayloadMismatchError,
  SelfVerificationError,
  voteOnProposal,
  type VoteOutcome,
} from '../flows.ts';
import { type Decision } from '../crypto/signing.ts';
import type { ProposalDetail } from '../api/schemas.ts';
import { decisionCode, spokenCode } from '../logic/decisionCode.ts';
import { problemReport } from '../logic/evidence.ts';
import { personalStatus, type DecisionFacts, type Seat, type SessionVote } from '../logic/personalStatus.ts';
import { classifySeat } from '../logic/queue.ts';
import { quorumSentence } from '../logic/quorum.ts';
import { dayMonth, dueWhen } from '../logic/words.ts';
import { EvidenceSheet, type EvidenceTab } from './decision/EvidenceSheet.tsx';
import { DetailsSheet, MoreSheet, TamperPanel, WhoDecided, type MoreItem } from './decision/parts.tsx';

const DAY = 24 * 60 * 60 * 1000;
const SEPOLIA = 11155111;
const TX_HASH = /^0x[0-9a-fA-F]{64}$/;

type OpenSheet = 'evidence' | 'details' | 'more' | null;

export default function DecisionScreen({
  uuid,
  opened,
  onBack,
  onOpenTreasuryApprovals,
  onRaiseIn,
}: {
  uuid: string;
  /** 'web': opened from the web's "Approve on your phone" handoff; the approve sheet (the signing
   * step) shows the full code comparison for it (§5.11). */
  via?: 'web';
  /** 'queue': opened from a list that showed it open, so a closed answer says "before you opened this". */
  opened?: 'queue';
  onBack: () => void;
  onOpenTreasuryApprovals: () => void;
  onRaiseIn: (vaultId: number, vaultName: string) => void;
}) {
  const s = useStyles();
  const t = useTheme();
  const { token, identity, custody, handleUnauthorized } = useEnrolledSession();
  const queryClient = useQueryClient();

  const [pending, setPending] = useState<Decision | null>(null);
  const [outcome, setOutcome] = useState<(VoteOutcome & { decision: Decision; at: string }) | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<{ title: string; detail?: string } | null>(null);
  const [sheet, setSheet] = useState<OpenSheet>(null);
  const [evidenceTab, setEvidenceTab] = useState<EvidenceTab>('checks');
  const [titleBottom, setTitleBottom] = useState<number | null>(null);
  const [scrolledPastTitle, setScrolledPastTitle] = useState(false);

  const query = useQuery({
    queryKey: ['proposal', uuid],
    queryFn: ({ signal }) => api.fetchProposal(token, uuid, signal),
    retry: retryTransport,
  });
  const devices = useQuery({
    queryKey: ['devices'],
    queryFn: ({ signal }) => api.fetchDevices(token, signal),
    retry: retryTransport,
  });
  const detail = query.data?.proposal;
  const action = detail?.signing_inputs.action;
  const treasury = useQuery({
    queryKey: ['treasury', detail?.vault_id],
    queryFn: ({ signal }) => api.fetchTreasury(token, detail!.vault_id, signal),
    enabled: !!action && detail?.status === 'open',
    retry: retryTransport,
  });

  // Every check, on every render of a loaded decision: what is shown beside the code must describe
  // the data on screen now, including after a refetch.
  const checked = useMemo<Checked | null>(() => (detail ? checkDecision(detail) : null), [detail]);

  // Row 16: the state this screen first saw. Opened from a list that showed it open, and closed by
  // the time it loaded, the first line says it closed before you opened it.
  const firstStatus = useRef<string | null>(null);
  if (detail && firstStatus.current === null) {
    firstStatus.current = decisionStatus({
      ...detail,
      required_m: detail.signing_inputs.policy.M,
      required_n: detail.signing_inputs.policy.N,
    });
  }

  const unauthorised = query.error instanceof ApiError && query.error.status === 401;
  useEffect(() => {
    if (unauthorised) void handleUnauthorized();
  }, [unauthorised, handleUnauthorized]);

  const vote = useMutation({
    mutationFn: async ({ decision, reason }: { decision: Decision; reason: string | null }) => {
      if (!detail) throw new Error('Proposal is still loading.');
      return voteOnProposal({ custody, token, identity, detail, decision, reason });
    },
    onSuccess: (result, { decision }) => {
      setOutcome({ ...result, decision, at: new Date().toISOString() });
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

  const webUrl = detail ? `${getApiBaseUrl()}/vaults/${detail.vault_id}/proposals/${uuid}` : null;
  const openWeb = () => {
    if (webUrl) void Linking.openURL(webUrl).catch(() => {});
  };

  // -- the states before there is a decision to show -------------------------------------------

  if (!detail || !checked) {
    const gone = query.error instanceof ApiError && (query.error.status === 404 || query.error.status === 403);
    return (
      <Screen>
        <NavBar onBack={onBack} />
        <Scroll refreshing={false} onRefresh={() => void query.refetch()}>
          {gone ? (
            <EmptyState
              title="You can't open this decision."
              detail="It may have been deleted, or you're no longer in its vault."
              action={<Button label="Go to Approvals" onPress={onBack} />}
            />
          ) : query.error && !unauthorised ? (
            <View style={s.top}>
              <Banner
                tone="warning"
                title="Can't load this decision."
                detail="Check your connection."
                actions={[{ label: 'Try again', onPress: () => void query.refetch() }]}
              />
            </View>
          ) : (
            <DecisionSkeleton />
          )}
        </Scroll>
      </Screen>
    );
  }

  // -- what the page says, and allows ----------------------------------------------------------

  const now = Date.now();
  const policy = detail.signing_inputs.policy;
  const isPayment = action !== undefined;
  const others = devices.data?.devices
    .filter((d) => !d.is_current)
    .map((d) => ({ name: d.name, fingerprint: d.fingerprint, revoked: d.revoked_at !== null }));
  let seat: Seat | null = null;
  if (isPayment && detail.execution) {
    const found = classifySeat(detail.execution.seat_fingerprint, identity.fingerprint, others ?? []);
    // Without the device list, another phone's key would read as the password key: say nothing yet.
    seat = found.kind === 'password' && others === undefined ? null : found;
  }
  const sessionVote: SessionVote | null = outcome
    ? {
        decision: outcome.decision,
        status: outcome.status,
        approvals: outcome.approvals,
        rejections: outcome.rejections,
        at: outcome.at,
      }
    : null;
  const facts: DecisionFacts = {
    status: detail.status,
    expires_at: detail.expires_at,
    approvals: detail.approvals,
    rejections: detail.rejections,
    can_sign: detail.can_sign,
    signed_by_me: detail.signed_by_me,
    policy,
    votes: detail.votes,
    is_payment: isPayment,
    payout: detail.payout ?? null,
    raised_by: detail.raised_by ?? null,
    separation_of_duties: detail.separation_of_duties,
    withdrawn_by: detail.withdrawn_by ?? null,
    withdrawn_at: detail.withdrawn_at ?? null,
    decided_at: detail.decided_at ?? null,
    signers: detail.signers,
  };
  const personal = personalStatus({
    decision: facts,
    viewerId: identity.userId,
    integrity: checked.ok ? { ok: true } : { ok: false, reason: checked.reason },
    vote: sessionVote,
    seat,
    closedBefore: opened === 'queue' && firstStatus.current !== 'open' ? 'opened' : null,
    now,
  });
  const actions = personal.actions;
  const tampered = !checked.ok;
  const code = checked.ok ? decisionCode(checked.hash) : null;
  const effective = decisionStatus(
    {
      status: outcome?.status ?? detail.status,
      expires_at: detail.expires_at,
      approvals: outcome?.approvals ?? detail.approvals,
      rejections: outcome?.rejections ?? detail.rejections,
      required_m: policy.M,
      required_n: policy.N,
    },
    now,
  );
  const open = effective === 'open';
  const approvals = outcome?.approvals ?? detail.approvals;
  const rejections = outcome?.rejections ?? detail.rejections;

  // The due time on the right of the status line, only while open; "Pay by" when the treasury's
  // limit comes first (§5.12).
  const deadline = parseInstant(detail.expires_at);
  const payBy = action ? action.valid_until * 1000 : Number.NaN;
  const payByFirst = open && !Number.isNaN(payBy) && (Number.isNaN(deadline) || payBy < deadline);
  const whenAt = payByFirst ? payBy : deadline;
  const whenText = !open
    ? null
    : payByFirst
      ? `Pay by ${dueWhen(new Date(payBy).toISOString(), now)}`
      : dueWhen(detail.expires_at, now);
  // Within a day, or already past (a payment's limit can pass while it is still open): the warning
  // tone and the clock, never colour alone.
  const soon = open && !Number.isNaN(whenAt) && whenAt - now < DAY;

  // Who can still approve, by A3's names, for the quorum sentence.
  const voted = new Set(detail.votes.map((v) => v.signer_id));
  const remaining = detail.signers
    ? policy.signers
        .filter((id) => !voted.has(id) && id !== identity.userId)
        .map((id) => detail.signers!.find((p) => p.user_id === id)?.name ?? null)
    : null;
  const stillToApprove = remaining && remaining.every((n): n is string => n !== null) ? remaining : null;
  const quorum = open
    ? quorumSentence({
        M: policy.M,
        N: policy.N,
        approvals,
        rejections,
        isPayment,
        viewerCanApprove: actions.kind === 'sign',
        stillToApprove,
        mentionRejections: personal.row !== 5,
      })
    : null;

  const payoutFailed = !!detail.payout && ['failed', 'voided', 'expired'].includes(detail.payout.state);
  const txHash = detail.payout?.state === 'confirmed' ? detail.payout.tx_hash : null;
  const etherscan =
    txHash && TX_HASH.test(txHash) && action?.chain_id === SEPOLIA
      ? `https://sepolia.etherscan.io/tx/${txHash}`
      : null;

  const report = () => {
    const text = problemReport({
      uuid,
      title: detail.title,
      reason: checked.ok ? null : checked.reason,
      derived: checked.ok ? checked.hash : checked.actual,
      stated: detail.payload_hash,
      appVersion: Constants.expoConfig?.version ?? 'unknown',
      at: new Date().toISOString(),
    });
    void Share.share({ message: text }).catch(() => {});
  };
  const openEvidence = (tab: EvidenceTab) => {
    setEvidenceTab(tab);
    setSheet('evidence');
  };

  const more: MoreItem[] = [
    { key: 'share', title: 'Share link', icon: 'share', onPress: () => webUrl && void Share.share({ message: webUrl }).catch(() => {}) },
    { key: 'web', title: 'Open on the web', icon: 'external', onPress: openWeb },
    { key: 'technical', title: 'Technical details', icon: 'shield', onPress: () => openEvidence('hashes') },
    ...(actions.kind === 'raiseAgain' && actions.placement === 'overflow'
      ? [{ key: 'again', title: 'Raise again', icon: 'plus' as const, onPress: () => onRaiseIn(detail.vault_id, detail.vault_name ?? '') }]
      : []),
    { key: 'report', title: 'Report a problem', icon: 'alert', onPress: report },
  ];

  const onScroll = (e: { nativeEvent: { contentOffset: { y: number } } }) => {
    if (titleBottom === null) return;
    const past = e.nativeEvent.contentOffset.y > titleBottom;
    if (past !== scrolledPastTitle) setScrolledPastTitle(past);
  };
  const onTitleLayout = (e: LayoutChangeEvent) => {
    const { y, height } = e.nativeEvent.layout;
    setTitleBottom(y + height);
  };

  const navTitle = scrolledPastTitle ? detail.title : (detail.vault_name ?? `Vault ${detail.vault_id}`);

  return (
    <Screen edges={['top']}>
      <NavBar
        onBack={onBack}
        title={navTitle}
        actions={[
          {
            icon: Platform.OS === 'android' ? 'more-vertical' : 'more',
            label: 'More options',
            onPress: () => setSheet('more'),
          },
        ]}
      />

      <Scroll onScroll={onScroll} scrollEventThrottle={16} refreshing={query.isRefetching} onRefresh={() => void query.refetch()}>
        <View style={s.stack}>
          {tampered ? (
            <TamperPanel reason={checked.reason} />
          ) : (
            <StatusLine
              badge={personal.badge}
              when={whenText}
              soon={soon}
              line={personal.line}
            />
          )}
          {!tampered && personal.row === 0 ? (
            // A state this app does not know: said plainly, never shown as one it does.
            <InlineMessage
              tone="neutral"
              text="This phone doesn't recognise this decision's state, so it offers nothing to sign. Open it on the web to see more."
            />
          ) : null}

          {error ? <Banner tone="critical" title={error.title} detail={error.detail} /> : null}

          {/* The title: the name it goes by in every list. Unsigned, so small and in sans. */}
          <View style={s.titleBlock} onLayout={onTitleLayout}>
            <Text role="titleSm" accessibilityRole="header" numberOfLines={3}>
              {detail.title}
            </Text>
            <Text role="caption" tone="muted">
              {raisedLine(detail, identity.userId, now)}
            </Text>
          </View>

          {tampered ? (
            <View style={s.labelled}>
              <Text role="caption" tone="critical">
                {"This is the text the server sent. It doesn't match what would be signed."}
              </Text>
              {/* The copy that failed: for display_text that is the text sent to be shown; otherwise
                  the text the hash or the payment did not match. */}
              <SignedText
                text={checked.reason === 'display_text' ? detail.action_text : detail.signing_inputs.action_text}
                size="decision"
              />
            </View>
          ) : action ? (
            // A payment leads with its amount and recipient, read from the signed action, which the
            // integrity check has matched to the signed sentence; the sentence is one tap away.
            <PaymentCard
              action={action}
              sentence={detail.signing_inputs.action_text}
              balanceWei={open ? (treasury.data?.status?.balance_wei ?? null) : null}
              balanceText={open ? (treasury.data?.status?.balance ?? null) : null}
            />
          ) : (
            <SignedText text={detail.signing_inputs.action_text} />
          )}

          {detail.signing_inputs.file_sha256 && !tampered ? (
            <List>
              <ListRow
                icon="document"
                title="Attached file"
                caption={
                  actions.kind === 'sign'
                    ? 'Bound into the signature. Read the attached file on the web before approving.'
                    : 'Bound into the signature. Open it on the web.'
                }
                captionLines={6}
                onPress={openWeb}
                accessibilityHint="Opens the decision on the web"
              />
            </List>
          ) : null}

          {tampered ? null : (
            <View style={s.quorum}>
              <Seal
                filled={approvals}
                required={policy.M}
                size={14}
                // Said once: in the sentence while it is open, as the seal's caption once decided.
                rejections={quorum ? 0 : rejections}
                celebrate={outcome !== null && approvals >= policy.M}
              />
              {quorum ? (
                <Text role="body" tone="muted">
                  {quorum}
                </Text>
              ) : null}
            </View>
          )}

          <WhoDecided votes={detail.votes} viewerId={identity.userId} now={now} />

          <List>
            {tampered ? null : (
              <DisclosureRow
                leading={<Icon name="check-circle" size={20} color={t.color.status.success.fg} />}
                title={payoutFailed ? 'This phone checked the signed text' : 'Checked on this phone'}
                code={code ? `Code ${code}` : null}
                accessibilityLabel={`${payoutFailed ? 'This phone checked the signed text' : 'Checked on this phone'}${code ? `. Decision code: ${spokenCode(code)}` : ''}`}
                onPress={() => openEvidence('checks')}
              />
            )}
            <DisclosureRow title="Details" onPress={() => setSheet('details')} />
            {etherscan ? (
              <ListRow
                icon="external"
                title="View on Etherscan"
                onPress={() => void Linking.openURL(etherscan).catch(() => {})}
                accessibilityHint="Opens the payment on Sepolia Etherscan"
              />
            ) : null}
          </List>
        </View>
      </Scroll>

      <Bar
        actions={actions}
        busy={vote.isPending}
        onApprove={() => setPending('approve')}
        onReject={() => setPending('reject')}
        onReport={report}
        onOpenWeb={openWeb}
        onFix={onOpenTreasuryApprovals}
        onRaiseAgain={() => onRaiseIn(detail.vault_id, detail.vault_name ?? '')}
      />

      <ConfirmSheet
        decision={pending}
        detail={detail}
        busy={vote.isPending}
        onCancel={() => setPending(null)}
        onConfirm={(reason) => {
          if (!pending) return;
          // Checked again at the moment of signing (I-1): a refetch since the sheet opened could
          // have brought a decision that no longer holds. flows.ts checks once more before the prompt.
          if (!checkDecision(detail).ok) {
            setPending(null);
            return;
          }
          vote.mutate({ decision: pending, reason });
        }}
      />

      <EvidenceSheet
        visible={sheet === 'evidence'}
        onClose={() => setSheet(null)}
        tab={evidenceTab}
        onTab={setEvidenceTab}
        detail={detail}
        checked={checked}
        code={code}
        identity={identity}
        seat={seat}
        open={open}
        onReport={report}
      />
      <DetailsSheet visible={sheet === 'details'} onClose={() => setSheet(null)} detail={detail} />
      <MoreSheet visible={sheet === 'more'} onClose={() => setSheet(null)} items={more} />

      {/* The acknowledgement. Stays until dismissed: someone who signed and put the phone down
          should still be told what happened when they look at it again. */}
      <SignedOverlay
        visible={confirming && outcome !== null}
        approved={outcome?.decision === 'approve'}
        filled={approvals}
        required={policy.M}
        onDone={() => setConfirming(false)}
      />
    </Screen>
  );
}

/** The action bar, from `personalStatus`'s actions only (§5.3, §6.6). */
function Bar({
  actions,
  busy,
  onApprove,
  onReject,
  onReport,
  onOpenWeb,
  onFix,
  onRaiseAgain,
}: {
  actions: ReturnType<typeof personalStatus>['actions'];
  busy: boolean;
  onApprove: () => void;
  onReject: () => void;
  onReport: () => void;
  onOpenWeb: () => void;
  onFix: () => void;
  onRaiseAgain: () => void;
}) {
  switch (actions.kind) {
    case 'sign':
      return (
        <ActionBar
          secondary={{ label: 'Reject', variant: 'dangerSecondary', onPress: onReject, disabled: busy }}
          primary={{ label: 'Approve', onPress: onApprove, disabled: busy }}
        />
      );
    case 'web':
      // A rejection carries no treasury signature, so Reject stays (§6.6 row 7).
      return (
        <ActionBar
          line={actions.line}
          secondary={{ label: 'Reject', variant: 'dangerSecondary', onPress: onReject, disabled: busy }}
        >
          {actions.fix ? <TextLink label="Approve treasury payments on this phone" onPress={onFix} /> : null}
        </ActionBar>
      );
    case 'report':
      // No signing at all (D7): neither Approve nor Reject.
      return (
        <ActionBar
          stack
          primary={{ label: 'Copy a report', variant: 'secondary', onPress: onReport }}
          secondary={{ label: 'Open on the web', variant: 'quiet', onPress: onOpenWeb }}
        />
      );
    case 'remind':
      return <ActionBar line="You raised this, so you can't approve it." />;
    case 'raiseAgain':
      return actions.placement === 'bar' ? (
        <ActionBar primary={{ label: 'Raise again', variant: 'secondary', onPress: onRaiseAgain }} />
      ) : null;
    default:
      return null;
  }
}

/**
 * The restatement: the action text verbatim, never a summary. (The signing step rebuilds this as
 * the approve and reject sheets of §6.8 and §6.9; a rejection already needs its reason, S16.)
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
  onConfirm: (reason: string | null) => void;
}) {
  const payment = detail.signing_inputs.action;
  const completes = detail.approvals + 1 >= detail.signing_inputs.policy.M;
  const [reason, setReason] = useState('');
  const [missing, setMissing] = useState(false);
  // Kept while the sheet animates out, so it does not flash to the other title on its way down.
  const last = useRef<Decision>('approve');
  if (decision) last.current = decision;
  const isApprove = (decision ?? last.current) === 'approve';
  const noun = payment ? 'payment' : 'decision';

  useEffect(() => {
    if (decision === null) {
      setReason('');
      setMissing(false);
    }
  }, [decision]);

  const confirm = () => {
    if (isApprove) return onConfirm(null);
    const text = reason.trim();
    if (!text) {
      // Shown inline, before any prompt: a rejection without its reason is never signed (S16).
      setMissing(true);
      return;
    }
    onConfirm(text);
  };

  return (
    <Sheet
      visible={decision !== null}
      onClose={onCancel}
      dismissible={!busy}
      title={isApprove ? `Approve this ${noun}` : `Reject this ${noun}`}
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
            onPress={confirm}
            busy={busy}
            full
          />
          <Button label="Cancel" variant="quiet" onPress={onCancel} disabled={busy} full />
        </>
      }
    >
      {isApprove ? null : (
        <Field
          label="Reason"
          caption={`Everyone in ${detail.vault_name ?? 'this vault'} sees this next to your rejection. It isn't part of what you sign.`}
          error={missing ? 'Add a reason so they know what to change.' : null}
          value={reason}
          onChangeText={(v: string) => {
            setReason(v);
            if (v.trim()) setMissing(false);
          }}
          maxLength={255}
          multiline
        />
      )}
      {payment ? (
        <PaymentCard action={payment} place="sheet" sentence={detail.signing_inputs.action_text} />
      ) : (
        <SignedText text={detail.signing_inputs.action_text} size="decision" />
      )}
    </Sheet>
  );
}

/**
 * "From Gracian, 38 minutes ago" once the server says who raised it (A1); until then "Raised 38
 * minutes ago". Older than a week, the date as the rest of the app writes it ("31 Aug").
 */
function raisedLine(detail: ProposalDetail, viewerId: number, now: number): string {
  const created = detail.signing_inputs.created_at;
  const age = now - parseInstant(created);
  const when = age >= 7 * DAY ? (dayMonth(created, now) ?? '') : whenAfter('', created, now).trim();
  const by = detail.raised_by;
  if (by?.name) return `From ${by.id === viewerId ? 'you' : by.name}, ${when}`;
  return `Raised ${when}`;
}

/** The decision's shape while it loads (§6.6): status line, two title lines, five text lines, quorum. */
function DecisionSkeleton() {
  const s = useStyles();
  return (
    <View style={[s.stack, s.top]}>
      <Skeleton width={150} height={24} radius={4} />
      <Skeleton width="80%" height={18} />
      <Skeleton width="45%" height={14} />
      <Skeleton width="95%" height={22} />
      <Skeleton width="92%" height={22} />
      <Skeleton width="88%" height={22} />
      <Skeleton width="94%" height={22} />
      <Skeleton width="60%" height={22} />
      <Skeleton width={140} height={14} />
    </View>
  );
}

function describe(err: unknown): { title: string; detail?: string } {
  if (err instanceof PayloadMismatchError) {
    return { title: 'Refused to sign.', detail: "This decision doesn't match what would be signed. Nothing was signed." };
  }
  if (err instanceof SelfVerificationError) {
    return { title: "This phone's key can't sign any more. Nothing was signed." };
  }
  if (err instanceof NotThisPhonesSeatError) {
    return { title: 'Not signed on this phone.', detail: err.message };
  }
  if (err instanceof NoScreenLockError) {
    return { title: 'Set a screen lock to sign with this phone.', detail: 'Nothing was signed.' };
  }
  if (err instanceof Error && err.name === 'AuthenticationCancelled') {
    return { title: 'Nothing was signed.' };
  }
  // Not folded into the line above: a device that cannot ask is a different problem from a person
  // who declined, and "nothing was signed" to a locked-out sensor sends them round the same loop.
  if (err instanceof Error && err.name === 'AuthenticationUnavailable') {
    const reason = (err as { reason?: string }).reason;
    return {
      title: 'This phone could not check it was you. Nothing was signed.',
      detail:
        reason === 'lockout' || reason === 'not_enrolled'
          ? 'Unlock your phone with its PIN, then try again.'
          : 'Check that a screen lock is set up on this phone.',
    };
  }
  if (err instanceof ApiError) {
    switch (err.code) {
      case 'already_voted':
        return { title: 'You have already signed this decision.' };
      case 'chain_unavailable':
        return { title: "Sepolia didn't answer, so nothing was signed.", detail: 'Try again in a minute.' };
      case 'proposal_closed':
        return { title: 'This was decided before your signature arrived. Nothing was signed.' };
      case 'not_a_signer':
        return { title: "You're not an approver on this decision." };
      case 'device_key_not_active':
      case 'signature_invalid':
        return { title: "This phone's key can't sign any more. Nothing was signed." };
      default:
        // The server's own wording is never shown (§6.6).
        return { title: 'Something went wrong, so nothing was signed.' };
    }
  }
  if (err instanceof TransportError) {
    return { title: "Not signed. Q-Vault didn't receive your signature, so nothing changed." };
  }
  return { title: 'Something went wrong, so nothing was signed.' };
}

const useStyles = makeStyles((t) => ({
  top: { paddingTop: t.space[8] },
  stack: { gap: t.space[24], paddingTop: t.space[8] },
  titleBlock: { gap: t.space[4] },
  labelled: { gap: t.space[8] },
  quorum: { gap: t.space[8] },
}));
