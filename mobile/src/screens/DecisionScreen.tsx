// A single decision, and the only screen in the app that can produce a signature (phone-ux §6.5).
//
// The order of operations is load-bearing:
//
//   1. Fetch the decision, including the complete `signing_inputs`.
//   2. Recompute `payload_hash` from those inputs, here, and run every other check (checks.ts),
//      including that the signed content has not changed since an earlier fetch in this run (I-16).
//   3. Only if they all hold, offer Approve and Reject at all. A decision that fails offers no
//      signing whatsoever, not even Reject (D7): the phone signs over a hash it derived itself, and
//      when that disagrees with the server's there is nothing verified to sign.
//   4. On tap, open the approve or reject sheet over a FROZEN copy of the decision, checked again as
//      it opens (I-6, src/signingSheet.ts). On confirm, check the copy once more and compare it with
//      the page's latest fetch; only then prompt for the handset lock, sign the hash WE derived,
//      verify our own signature, and submit (flows.ts, which checks again before the prompt). One
//      signature at a time: a second tap while one is in flight does nothing.
//
// Fresh data before signing (§2.6, I-7): Approve and Reject open their sheet only when the decision
// on the page is the answer of a network fetch made in this process under a minute ago
// (`networkFetches`, src/queries.ts). Otherwise the button reads "Checking…", the decision is fetched
// again, and the sheet opens over that answer. The page polls every 20 s while it is open, not while
// a sheet is; offline, the action bar says signing needs a connection. Opened without its detail (a
// restart, offline), the page shows the list's summary until the network copy arrives (D5).
//
// What the page says and allows comes from one place, `personalStatus()` (§6.6), never from flags
// worked out here: the action bar shows Approve only when it returns `sign`. A status this app does
// not know reads "Unknown" and offers nothing.
//
// Top to bottom: the status line (badge, due time, one personal sentence); the title, small and in
// sans because it is not signed (S19); what you sign, in the serif, or a payment's amount and
// recipient; the quorum and its sentence; who decided; "Checked on this phone" with the code; and
// Details. Everything else is one tap away in the evidence sheet.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Linking, Platform, Share, View, type LayoutChangeEvent } from 'react-native';
import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { useIsFocused } from '@react-navigation/native';
import Constants from 'expo-constants';

import {
  ActionBar,
  Banner,
  Button,
  ColdStartHint,
  DisclosureRow,
  EmptyState,
  Icon,
  InlineMessage,
  List,
  ListRow,
  NavBar,
  PaymentCard,
  Screen,
  Scroll,
  Seal,
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
import { ApiError } from '../api/client.ts';
import { getApiBaseUrl } from '../config.ts';
import { useApprovals } from '../approvals.ts';
import { OfflineNotice, useColdStart, useOffline, useRefreshOnFocus } from '../freshness.tsx';
import { devicesQuery, holdDecision, keys, networkFetches, proposalQuery } from '../queries.ts';
import { fetchKey, OFFLINE_DECISION, OFFLINE_SIGNING, POLL_MS } from '../logic/freshness.ts';
import { checkInRun, type Checked } from '../checks.ts';
import { voteOnProposal, type VoteOutcome } from '../flows.ts';
import { type Decision } from '../crypto/signing.ts';
import type { ProposalDetail, ProposalSummary, VaultDetail } from '../api/schemas.ts';
import { reportSigning } from '../links.ts';
import { useSigningMethod } from '../signingMethod.ts';
import {
  confirmSigning,
  openSigningSheet,
  signingProblem,
  type OpenRefusal,
  type SheetKind,
  type SigningProblem,
  type Snapshot,
} from '../signingSheet.ts';
import { acknowledgement, nextCaption } from '../logic/consequence.ts';
import { decisionCode, spokenCode } from '../logic/decisionCode.ts';
import { problemReport } from '../logic/evidence.ts';
import { personalStatus, type DecisionFacts, type Seat, type SessionVote } from '../logic/personalStatus.ts';
import { classifySeat } from '../logic/queue.ts';
import { quorumSentence } from '../logic/quorum.ts';
import { dayMonth, dueWhen } from '../logic/words.ts';
import { EvidenceSheet, type EvidenceTab } from './decision/EvidenceSheet.tsx';
import { DetailsSheet, MoreSheet, TamperPanel, WhoDecided, type MoreItem } from './decision/parts.tsx';
import { SigningSheet } from './decision/SigningSheet.tsx';

const DAY = 24 * 60 * 60 * 1000;
const SEPOLIA = 11155111;
const TX_HASH = /^0x[0-9a-fA-F]{64}$/;

type OpenSheet = 'evidence' | 'details' | 'more' | null;
type Message = { tone: 'neutral' | 'warning' | 'critical'; text: string };

/** Paint the busy state before the ML-DSA work holds the JS thread (§6.10). */
const nextFrame = () =>
  new Promise<void>((resolve) => requestAnimationFrame(() => setTimeout(resolve, 0)));

/** The refetch before a sheet could not get an answer (I-7): nothing opens. */
const NOT_CHECKED: Message = {
  tone: 'warning',
  text: "Couldn't check this decision with Q-Vault, so it can't be signed yet. Try again.",
};

/** What the bar says when a sheet refuses to open. Tampered says nothing: the page already does. */
function refusalMessage(refusal: OpenRefusal): Message | null {
  switch (refusal) {
    case 'seat':
      return { tone: 'warning', text: "The treasury doesn't hold this phone's key for you, so this phone can't approve it." };
    case 'digest':
      return {
        tone: 'critical',
        text: "Refused to sign: the treasury's payment doesn't match this decision. Nothing was signed.",
      };
    case 'not_offered':
      return { tone: 'neutral', text: "This can't be signed from here." };
    default:
      return null;
  }
}

export default function DecisionScreen({
  uuid,
  via,
  opened,
  onBack,
  onNext,
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
  /** "Next decision" from the acknowledgement: replaces this route (§6.11, §2.3). */
  onNext: (uuid: string) => void;
  onOpenTreasuryApprovals: () => void;
  onRaiseIn: (vaultId: number, vaultName: string) => void;
}) {
  const s = useStyles();
  const t = useTheme();
  const { token, identity, custody, markKeyUnusable } = useEnrolledSession();
  const queryClient = useQueryClient();
  const method = useSigningMethod();
  const focused = useIsFocused();
  const offline = useOffline();

  // The signing sheet: its frozen snapshot (kept while it animates out), whether it is open, and
  // whether a signature is in flight. `inFlight` guards against a second tap in the same frame,
  // before React has re-rendered the button as busy.
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [signingOpen, setSigningOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const [problem, setProblem] = useState<SigningProblem | null>(null);
  const [reasonMissing, setReasonMissing] = useState(false);
  const [barMessage, setBarMessage] = useState<Message | null>(null);
  const [keyBanner, setKeyBanner] = useState<{ text: string; cause: 'key_missing' | 'key_unusable' } | null>(
    null,
  );
  const [closedBeforeSigned, setClosedBeforeSigned] = useState(false);
  // "Checking…": the decision is being fetched again before its sheet may open (I-7), and which
  // sheet will open once it is back.
  const [checking, setChecking] = useState<SheetKind | null>(null);
  const [readyToOpen, setReadyToOpen] = useState<SheetKind | null>(null);
  // While a sheet is open, a signature is in flight or the pre-sheet check runs, nothing refetches
  // this decision on its own: no polling, no focus refetch (§2.6, I-6).
  const held = signingOpen || busy || checking !== null;
  useEffect(() => (held ? holdDecision(uuid) : undefined), [held, uuid]);
  const queue = useApprovals();

  const [outcome, setOutcome] = useState<(VoteOutcome & { decision: Decision; at: string }) | null>(null);
  const [acknowledging, setAcknowledging] = useState(false);
  const [sheet, setSheet] = useState<OpenSheet>(null);
  const [evidenceTab, setEvidenceTab] = useState<EvidenceTab>('checks');
  const [titleBottom, setTitleBottom] = useState<number | null>(null);
  const [scrolledPastTitle, setScrolledPastTitle] = useState(false);

  const query = useQuery({
    ...proposalQuery(token, uuid),
    refetchInterval: focused && !held ? POLL_MS.decision : false,
  });
  useRefreshOnFocus([keys.proposal(uuid)], !held);
  const devices = useQuery(devicesQuery(token));
  const detail = query.data?.proposal;
  const action = detail?.signing_inputs.action;
  const treasury = useQuery({
    queryKey: ['treasury', detail?.vault_id],
    queryFn: ({ signal }) => api.fetchTreasury(token, detail!.vault_id, signal),
    enabled: !!action && detail?.status === 'open',
  });
  const coldStart = useColdStart(!detail && query.isFetching);

  // Every check, on every fetch of the decision: what is shown beside the code must describe the
  // data on screen now, including after a refetch, and signed content that changed between two
  // fetches in this run fails as `changed` (I-16).
  const checked = useMemo<Checked | null>(() => (detail ? checkInRun(detail) : null), [detail]);

  const closeSigning = useCallback(() => {
    if (inFlight.current) return;
    setSigningOpen(false);
    setProblem(null);
    setReasonMissing(false);
  }, []);

  // A fetch that changed the signed content, or failed a check, closes an idle sheet before any
  // prompt, and the page shows why (§6.6, I-16). A signature already in flight is over the frozen
  // snapshot and cannot be recalled; the page shows the change once it settles.
  useEffect(() => {
    if (!signingOpen || busy || !snapshot || !checked) return;
    if (!checked.ok || checked.hash !== snapshot.hash) closeSigning();
  }, [signingOpen, busy, snapshot, checked, closeSigning]);

  // Tell the link router what is happening, so a link never interrupts a signature (§2.4 rule 2).
  useEffect(() => {
    reportSigning({
      sheet: signingOpen ? (busy ? 'busy' : 'idle') : 'none',
      acknowledging,
      closeSheet: closeSigning,
    });
  }, [signingOpen, busy, acknowledging, closeSigning]);
  useEffect(() => () => reportSigning({ sheet: 'none', acknowledging: false, closeSheet: null }), []);

  // The pre-sheet check is back with a fresh answer: open the sheet over it, from this render's copy
  // of the page (the refetched decision), through the same gate as a direct tap.
  const openAfterCheck = useRef<((kind: SheetKind) => void) | null>(null);
  useEffect(() => {
    if (readyToOpen === null) return;
    const kind = readyToOpen;
    setReadyToOpen(null);
    setChecking(null);
    openAfterCheck.current?.(kind);
  }, [readyToOpen]);
  const mounted = useRef(true);
  useEffect(
    () => () => {
      mounted.current = false;
    },
    [],
  );

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

  // A 401 is handled once, by the session (the API client reports it): Session ended (§6.20).
  const unauthorised = query.error instanceof ApiError && query.error.status === 401;

  const webUrl = detail ? `${getApiBaseUrl()}/vaults/${detail.vault_id}/proposals/${uuid}` : null;
  const openWeb = () => {
    if (webUrl) void Linking.openURL(webUrl).catch(() => {});
  };

  // -- the states before there is a decision to show -------------------------------------------

  if (!detail || !checked) {
    const gone = query.error instanceof ApiError && (query.error.status === 404 || query.error.status === 403);
    // Its list summary, if a list has it (D5): title, vault and due time, all unsigned and display
    // only. Nothing here can be signed; the page proper waits for the network copy.
    const listed = gone ? null : findSummary(queryClient, uuid);
    const failed = !!query.error && !unauthorised && !gone;
    return (
      <Screen>
        <NavBar onBack={onBack} title={listed?.summary.vault_name ?? undefined} />
        <OfflineNotice at={listed?.at} />
        <Scroll refreshing={false} onRefresh={() => void query.refetch()}>
          {gone ? (
            <EmptyState
              title="You can't open this decision."
              detail="It may have been deleted, or you're no longer in its vault."
              action={<Button label="Go to Approvals" onPress={onBack} />}
            />
          ) : listed ? (
            <View style={s.stack}>
              <View style={s.titleBlock}>
                <Text role="titleSm" accessibilityRole="header" numberOfLines={3}>
                  {listed.summary.title}
                </Text>
                {listed.due ? (
                  <Text role="caption" tone="muted">
                    {`Due ${listed.due.replace(/^(Today|Tomorrow)/, (w) => w.toLowerCase())}`}
                  </Text>
                ) : null}
              </View>
              {offline ? (
                <InlineMessage tone="neutral" text={OFFLINE_DECISION} />
              ) : failed ? (
                <Banner
                  tone="warning"
                  title="Can't load this decision."
                  detail="Check your connection."
                  actions={[{ label: 'Try again', onPress: () => void query.refetch() }]}
                />
              ) : (
                <View style={s.labelled}>
                  <ColdStartHint stage={coldStart} onRetry={() => void query.refetch()} />
                  <TextSkeleton />
                </View>
              )}
            </View>
          ) : failed ? (
            <View style={s.top}>
              <Banner
                tone="warning"
                title="Can't load this decision."
                detail={offline ? OFFLINE_DECISION : 'Check your connection.'}
                actions={[{ label: 'Try again', onPress: () => void query.refetch() }]}
              />
            </View>
          ) : (
            <View>
              <ColdStartHint stage={coldStart} onRetry={() => void query.refetch()} />
              <DecisionSkeleton />
            </View>
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
    closedBefore:
      opened === 'queue' && firstStatus.current !== 'open' ? 'opened' : closedBeforeSigned ? 'signed' : null,
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

  // Who can still approve, by A3's names, for the quorum sentence and the acknowledgement.
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

  // -- signing ---------------------------------------------------------------------------------

  const proposalKey = fetchKey(keys.proposal(uuid));

  // Open a sheet over the page's decision, only if a network fetch in this process returned this
  // very copy under a minute ago (I-7). `afterCheck`: straight after the pre-sheet refetch, when a
  // decision that has closed meanwhile simply shows its new state, with no extra message.
  const startSigning = (kind: SheetKind, afterCheck = false) => {
    if (inFlight.current || signingOpen) return;
    setBarMessage(null);
    if (!networkFetches.signable(proposalKey, query.data, Date.now())) {
      setBarMessage(NOT_CHECKED);
      return;
    }
    const attempt = openSigningSheet({ detail, kind, actions, identity, method, via });
    if (!attempt.ok) {
      const message = afterCheck && attempt.refusal === 'not_offered' ? null : refusalMessage(attempt.refusal);
      if (message) {
        setBarMessage(message);
        feedback.refused();
      }
      return;
    }
    setSnapshot(attempt.snapshot);
    setProblem(null);
    setReasonMissing(false);
    setSigningOpen(true);
  };
  openAfterCheck.current = (kind) => startSigning(kind, true);

  /** Approve or Reject tapped: open at once if the copy is fresh, otherwise check first (I-7). */
  const requestSigning = (kind: SheetKind) => {
    if (inFlight.current || signingOpen || checking !== null || offline) return;
    if (networkFetches.signable(proposalKey, query.data, Date.now())) {
      startSigning(kind);
      return;
    }
    setBarMessage(null);
    setChecking(kind);
    // Cancels any fetch in flight and asks again: only an answer to a request made now counts.
    void query.refetch({ cancelRefetch: true }).then((result) => {
      if (!mounted.current) return;
      if (result.isSuccess && networkFetches.signable(proposalKey, result.data, Date.now())) {
        setReadyToOpen(kind);
        return;
      }
      setChecking(null);
      if (!(result.error instanceof ApiError && result.error.status === 401)) setBarMessage(NOT_CHECKED);
    });
  };

  const confirm = async (reason: string) => {
    if (inFlight.current || !snapshot || !signingOpen) return;
    // The frozen snapshot, checked again and compared with the page's latest fetch, before any
    // prompt (I-1, I-6, I-16). The live copy is read from the cache, not from this render.
    const live = queryClient.getQueryData<{ proposal: ProposalDetail }>(['proposal', uuid])?.proposal;
    // The page as it stands now must still offer this signature: a decision that closed, or that
    // this person can no longer sign, while the sheet was open is not signed (no prompt).
    const offered =
      snapshot.kind === 'approve' ? actions.kind === 'sign' : actions.kind === 'sign' || actions.kind === 'web';
    if (!offered) {
      closeSigning();
      setBarMessage({ tone: 'neutral', text: 'This changed while you were reading it, so nothing was signed.' });
      return;
    }
    const ready = confirmSigning(snapshot, live, reason);
    if (!ready.ok) {
      if (ready.refusal === 'reason_missing' || ready.refusal === 'reason_too_long') {
        setReasonMissing(true);
        return;
      }
      // Changed or failed: close before any prompt; the page shows the failure.
      closeSigning();
      feedback.refused();
      return;
    }
    inFlight.current = true;
    setBusy(true);
    setProblem(null);
    try {
      await nextFrame();
      const result = await voteOnProposal({
        custody,
        token,
        identity,
        detail: ready.detail,
        decision: snapshot.kind,
        reason: ready.reason,
      });
      setOutcome({ ...result, decision: snapshot.kind, at: new Date().toISOString() });
      setBarMessage(null);
      setSigningOpen(false);
      // The acknowledgement owns the haptic, timed to its tick: firing here too would buzz twice.
      setAcknowledging(true);
      void queryClient.invalidateQueries({ queryKey: ['proposals'] });
      void queryClient.invalidateQueries({ queryKey: ['proposal', uuid] });
    } catch (err) {
      const p = signingProblem(err, method);
      if (p.closeSheet) {
        setSigningOpen(false);
        setReasonMissing(false);
      }
      if (p.place === 'sheet') setProblem(p);
      if (p.place === 'bar' && p.text) setBarMessage({ tone: p.tone, text: p.text });
      if (p.place === 'banner' && p.text) setKeyBanner({ text: p.text, cause: p.setupCause ?? 'key_unusable' });
      if (p.closedBeforeSigned) setClosedBeforeSigned(true);
      if (p.refetch) void query.refetch();
      // A cancelled prompt gets nothing: the person chose it (§7.2).
      if (p.tone !== 'neutral') feedback.refused();
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  // The acknowledgement (§6.11): its words from the signed rule and the counts the server returned.
  const ack = outcome
    ? acknowledgement({
        decision: outcome.decision,
        M: policy.M,
        N: policy.N,
        approvals: outcome.approvals,
        rejections: outcome.rejections,
        isPayment,
        stillToApprove,
        pastPayBy: !Number.isNaN(payBy) && payBy <= now,
      })
    : null;
  // Next decision: the queue's own "Needs your signature" group, less this one, soonest first; the
  // same number as the badge (§2.5), and never an "Approve on the web" item.
  const nextUp = queue.groups.needsYou.filter((p) => p.proposal_uuid !== uuid);

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
  // At large text the action bar keeps only its buttons (§6.6 row 7): the line repeats the personal
  // line, so it goes, and the one-time switch moves onto the page under the status line.
  const compactBar = t.stacked;

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
      <OfflineNotice at={query.dataUpdatedAt} />

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
          {compactBar && actions.kind === 'web' && actions.fix ? (
            <TextLink label="Approve treasury payments on this phone" onPress={onOpenTreasuryApprovals} />
          ) : null}

          {keyBanner ? (
            <Banner
              tone="critical"
              title={keyBanner.text}
              actions={[{ label: 'Set up this phone again', onPress: () => markKeyUnusable(keyBanner.cause) }]}
            />
          ) : null}

          {/* The title: the name it goes by in every list. Unsigned, so small and in sans. */}
          <View style={s.titleBlock} onLayout={onTitleLayout}>
            <Text role="titleSm" accessibilityRole="header" numberOfLines={3}>
              {detail.title}
            </Text>
            <Text role="caption" tone="muted">
              {raisedLine(detail, identity.userId, now)}
            </Text>
          </View>

          {tampered && checked.reason === 'changed' ? (
            // I-16: the later text is never shown in place of the one the person was reading.
            <Text role="caption" tone="critical">
              {'Q-Vault sent different text for this decision after you opened it, so neither version is shown here.'}
            </Text>
          ) : tampered ? (
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
        busy={busy}
        checking={checking}
        offline={offline}
        compact={compactBar}
        message={barMessage}
        onApprove={() => requestSigning('approve')}
        onReject={() => requestSigning('reject')}
        onReport={report}
        onOpenWeb={openWeb}
        onFix={onOpenTreasuryApprovals}
        onRaiseAgain={() => onRaiseIn(detail.vault_id, detail.vault_name ?? '')}
      />

      <SigningSheet
        snapshot={snapshot}
        visible={signingOpen}
        busy={busy}
        problem={problem}
        reasonMissing={reasonMissing}
        onConfirm={(reason) => void confirm(reason)}
        onCancel={closeSigning}
        onReasonChange={() => setReasonMissing(false)}
        onOpenWeb={openWeb}
        balanceWei={treasury.data?.status?.balance_wei ?? null}
        balanceText={treasury.data?.status?.balance ?? null}
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
      {ack ? (
        <SignedOverlay
          visible={acknowledging}
          mark={ack.mark}
          sealed={ack.sealed}
          headline={ack.headline}
          line={ack.line}
          filled={approvals}
          required={policy.M}
          next={
            nextUp.length > 0
              ? {
                  caption: nextCaption(nextUp.length),
                  onPress: () => {
                    setAcknowledging(false);
                    onNext(nextUp[0]!.proposal_uuid);
                  },
                }
              : null
          }
          onDone={() => setAcknowledging(false)}
        />
      ) : null}
    </Screen>
  );
}

/** The action bar, from `personalStatus`'s actions only (§5.3, §6.6). */
function Bar({
  actions,
  busy,
  checking,
  offline,
  compact,
  message,
  onApprove,
  onReject,
  onReport,
  onOpenWeb,
  onFix,
  onRaiseAgain,
}: {
  actions: ReturnType<typeof personalStatus>['actions'];
  busy: boolean;
  /** Which button is fetching the decision again before its sheet may open (I-7). */
  checking: SheetKind | null;
  /** No connection: signing is not offered, and the bar says why (§2.6). */
  offline: boolean;
  /** Large text: buttons only (the line is the personal line again, and the link is on the page). */
  compact: boolean;
  /** An action's error after its sheet closed. */
  message: Message | null;
  onApprove: () => void;
  onReject: () => void;
  onReport: () => void;
  onOpenWeb: () => void;
  onFix: () => void;
  onRaiseAgain: () => void;
}) {
  if (offline && (actions.kind === 'sign' || actions.kind === 'web')) {
    // The phone checks a decision against the network before any sheet (I-7): none offline.
    return <ActionBar message={message} line={OFFLINE_SIGNING} />;
  }
  const held = busy || checking !== null;
  const reject = {
    label: checking === 'reject' ? 'Checking…' : 'Reject',
    variant: 'dangerSecondary' as const,
    onPress: onReject,
    busy: checking === 'reject',
    disabled: held && checking !== 'reject',
  };
  switch (actions.kind) {
    case 'sign':
      return (
        <ActionBar
          message={message}
          secondary={reject}
          primary={{
            label: checking === 'approve' ? 'Checking…' : 'Approve',
            onPress: onApprove,
            busy: checking === 'approve',
            disabled: held && checking !== 'approve',
          }}
        />
      );
    case 'web':
      // A rejection carries no treasury signature, so Reject stays (§6.6 row 7).
      return (
        <ActionBar
          message={message}
          line={compact ? null : actions.line}
          secondary={reject}
        >
          {actions.fix && !compact ? <TextLink label="Approve treasury payments on this phone" onPress={onFix} /> : null}
        </ActionBar>
      );
    case 'report':
      // No signing at all (D7): neither Approve nor Reject.
      return (
        <ActionBar
          stack
          message={message}
          primary={{ label: 'Copy a report', variant: 'secondary', onPress: onReport }}
          secondary={{ label: 'Open on the web', variant: 'quiet', onPress: onOpenWeb }}
        />
      );
    case 'remind':
      return <ActionBar message={message} line="You raised this, so you can't approve it." />;
    case 'raiseAgain':
      return actions.placement === 'bar' ? (
        <ActionBar message={message} primary={{ label: 'Raise again', variant: 'secondary', onPress: onRaiseAgain }} />
      ) : message ? (
        <ActionBar message={message} />
      ) : null;
    default:
      return message ? <ActionBar message={message} /> : null;
  }
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

/**
 * A decision's summary from a list in the cache, and when that list was fetched: the queue, the
 * record, or a vault's page. Display only (D5).
 */
function findSummary(
  client: QueryClient,
  uuid: string,
): { summary: ProposalSummary; at: number | undefined; due: string | null } | null {
  for (const queryKey of [keys.awaiting, keys.all]) {
    const state = client.getQueryState<{ proposals: ProposalSummary[] }>(queryKey);
    const found = state?.data?.proposals.find((p) => p.proposal_uuid === uuid);
    if (found) return { summary: found, at: state!.dataUpdatedAt, due: dueWhen(found.expires_at, Date.now()) };
  }
  for (const [queryKey, data] of client.getQueriesData<{ vault: VaultDetail }>({ queryKey: ['vault'] })) {
    const found = data?.vault.proposals.find((p) => p.proposal_uuid === uuid);
    if (found) {
      const at = client.getQueryState(queryKey)?.dataUpdatedAt;
      return { summary: found, at, due: dueWhen(found.expires_at, Date.now()) };
    }
  }
  return null;
}

/** The signed text's place while it loads under a summary. */
function TextSkeleton() {
  const s = useStyles();
  return (
    <View style={s.textSkeleton}>
      <Skeleton width="95%" height={22} />
      <Skeleton width="90%" height={22} />
      <Skeleton width="70%" height={22} />
    </View>
  );
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

const useStyles = makeStyles((t) => ({
  top: { paddingTop: t.space[8] },
  stack: { gap: t.space[24], paddingTop: t.space[8] },
  titleBlock: { gap: t.space[4] },
  labelled: { gap: t.space[8] },
  quorum: { gap: t.space[8] },
  textSkeleton: { gap: t.space[12] },
}));
