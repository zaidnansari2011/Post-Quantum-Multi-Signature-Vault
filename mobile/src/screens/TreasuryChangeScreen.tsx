// A change to a vault's treasury signers (phone-ux §6.15): its own route, because it is not a
// decision. It has no raiser, no signed text and no reject path on the server, so the page is the
// decision's frame cut to what a change has: the status line, what the change does, its approvals,
// "Checked on this phone", and one button, "Approve change". There is no Reject (owner Q8).
//
// The order is the decision's (I-1): this phone derives the change's digest from its signed inputs
// and refuses to show it as genuine when the server's differs (`checkTreasuryChange`); "Approve
// change" opens a sheet over a frozen copy, only when that copy came from the network in this process
// under a minute ago (I-7); and `approveTreasuryChange` checks everything again before the prompt.
// No decision code: the web's treasury-change view does not show one yet (§5.11, A17).

import { useRef, useState } from 'react';
import { Linking, Platform, Share, View } from 'react-native';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import Constants from 'expo-constants';

import {
  ActionBar,
  Banner,
  Button,
  ColdStartHint,
  DisclosureRow,
  EmptyState,
  Icon,
  Identifier,
  InlineMessage,
  List,
  NavBar,
  Screen,
  Scroll,
  Seal,
  Sheet,
  SignedOverlay,
  Skeleton,
  StatusLine,
  Text,
  TextLink,
  feedback,
} from '../ui/index.tsx';
import { makeStyles, useTheme } from '../theme/index.ts';
import { useEnrolledSession } from '../session.tsx';
import { ApiError, TransportError } from '../api/client.ts';
import { getApiBaseUrl } from '../config.ts';
import type { ReconfigurationView } from '../api/schemas.ts';
import {
  NoScreenLockError,
  NotThisPhonesSeatError,
  PayloadMismatchError,
  SelfVerificationError,
  approveTreasuryChange,
} from '../flows.ts';
import { OfflineNotice, useColdStart, useOffline, useRefreshOnFocus } from '../freshness.tsx';
import { devicesQuery, keys, networkFetches, treasuryQuery, vaultsQuery } from '../queries.ts';
import { fetchKey, OFFLINE_SIGNING } from '../logic/freshness.ts';
import { methodButton } from '../logic/methodLabel.ts';
import {
  changeConsequence,
  changeSummary,
  checkTreasuryChange,
  requestedLine,
  treasuryChangeStatus,
} from '../logic/treasuryChange.ts';
import { dueWhen } from '../logic/words.ts';
import { useSigningMethod } from '../signingMethod.ts';
import { MoreSheet, type MoreItem } from './decision/parts.tsx';

type Problem = { tone: 'neutral' | 'warning' | 'critical'; text: string };

const DAY = 24 * 60 * 60 * 1000;

export default function TreasuryChangeScreen({
  vaultId,
  changeId,
  opened,
  onBack,
  onOpenTreasuryApprovals,
}: {
  vaultId: number;
  changeId: number;
  opened?: 'queue';
  onBack: () => void;
  onOpenTreasuryApprovals: () => void;
}) {
  const s = useStyles();
  const t = useTheme();
  const { token, identity, custody } = useEnrolledSession();
  const queryClient = useQueryClient();
  const method = useSigningMethod();
  const offline = useOffline();

  const [snapshot, setSnapshot] = useState<{ change: ReconfigurationView; address: string } | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [checking, setChecking] = useState(false);
  const [more, setMore] = useState(false);
  const [evidence, setEvidence] = useState(false);
  const [ack, setAck] = useState<{ approvals: number; needed: number } | null>(null);

  const query = useQuery(treasuryQuery(token, vaultId));
  // Nothing refetches it under an open sheet (I-6).
  useRefreshOnFocus([keys.treasury(vaultId)], !sheetOpen && !busy);
  const vaults = useQuery(vaultsQuery(token));
  const devices = useQuery(devicesQuery(token));
  const coldStart = useColdStart(!query.data && query.isFetching);
  const vaultName = vaults.data?.vaults.find((v) => v.vault_id === vaultId)?.name ?? 'this vault';
  const webUrl = `${getApiBaseUrl()}/vaults/${vaultId}?tab=treasury`;
  const openWeb = () => void Linking.openURL(webUrl).catch(() => {});

  const data = query.data;
  const fetchedKey = fetchKey(keys.treasury(vaultId));
  const treasury = data?.treasury ?? null;
  const live = data?.change?.reconfiguration ?? null;
  const change = live && live.id === changeId ? live : null;

  // Row 11: the state this screen first saw. Opened from the queue, where it waited on you, and
  // moved on by the time it loaded: the line says so first.
  const firstState = useRef<string | null>(null);
  if (change && firstState.current === null) firstState.current = change.state;


  if (!data || (!change && !query.isFetching && data)) {
    const gone = query.error instanceof ApiError && (query.error.status === 404 || query.error.status === 403);
    return (
      <Screen>
        <NavBar onBack={onBack} title="Treasury change" />
        <OfflineNotice at={query.dataUpdatedAt} />
        <Scroll refreshing={false} onRefresh={() => void query.refetch()}>
          <ColdStartHint stage={coldStart} onRetry={() => void query.refetch()} />
          {data && !change ? (
            <EmptyState
              title="You can't open this change."
              detail={
                treasury
                  ? "It may have been replaced by a newer change. The vault's treasury shows the current one."
                  : `This treasury is no longer linked to ${vaultName}.`
              }
              action={<Button label="Go back" onPress={onBack} />}
            />
          ) : gone ? (
            <EmptyState
              title="You can't open this change."
              detail="You may no longer be in its vault."
              action={<Button label="Go back" onPress={onBack} />}
            />
          ) : query.error ? (
            <Banner
              tone="warning"
              title="Can't load this change"
              detail="Check your connection and try again."
              actions={[{ label: 'Try again', onPress: () => void query.refetch() }]}
            />
          ) : (
            <View style={s.skeleton}>
              <Skeleton width={150} height={24} radius={4} />
              <Skeleton width="80%" height={18} />
              <Skeleton width="95%" height={16} />
              <Skeleton width="70%" height={16} />
            </View>
          )}
        </Scroll>
      </Screen>
    );
  }
  if (!change) return null;

  const now = Date.now();
  const address = treasury?.address ?? '';
  const integrity = treasury ? checkTreasuryChange(change, address) : { ok: true as const };
  const otherDevice = devices.data?.devices.find(
    (d) => !d.is_current && d.fingerprint !== null && d.fingerprint === change.seat_fingerprint,
  );
  const status = treasuryChangeStatus({
    change,
    fingerprint: identity.fingerprint,
    integrity,
    linked: treasury !== null,
    vaultName,
    otherDeviceName: otherDevice && !otherDevice.revoked_at ? otherDevice.name : null,
    closedBefore: opened === 'queue' && firstState.current !== 'collecting_approvals',
    now,
  });
  const collecting = change.state === 'collecting_approvals';
  const until = Date.parse(change.valid_until);
  const soon = collecting && !Number.isNaN(until) && until - now < DAY && until > now;
  const summary = changeSummary(change, treasury?.signer_count ?? null);

  function open() {
    const current = queryClient.getQueryData<typeof data>(keys.treasury(vaultId));
    const c = current?.change?.reconfiguration;
    const addr = current?.treasury?.address;
    if (!c || c.id !== changeId || !addr || !networkFetches.signable(fetchedKey, current, Date.now())) {
      setProblem({ tone: 'warning', text: "Couldn't check this change with Q-Vault, so it can't be approved yet. Try again." });
      return;
    }
    // Moved on, already approved, or not this phone's seat since the page was drawn: the page now
    // says so, and no sheet opens over it.
    if (!checkTreasuryChange(c, addr).ok) return;
    if (c.state !== 'collecting_approvals' || c.approved_by_me || c.seat_fingerprint !== identity.fingerprint) return;
    setSnapshot({ change: c, address: addr });
    setProblem(null);
    setSheetOpen(true);
  }

  const requestApprove = () => {
    if (inFlight.current || sheetOpen || checking || offline) return;
    if (data && networkFetches.signable(fetchedKey, data, Date.now())) {
      open();
      return;
    }
    // Fresh data before signing (I-7): fetch it again, then open over that answer, read from the
    // cache by `open`, which checks it came from this very fetch.
    setChecking(true);
    void query.refetch({ cancelRefetch: true }).then((result) => {
      setChecking(false);
      if (result.isSuccess) open();
      else setProblem({ tone: 'warning', text: "Couldn't check this change with Q-Vault, so it can't be approved yet. Try again." });
    });
  };

  const close = () => {
    if (inFlight.current) return;
    setSheetOpen(false);
    setProblem(null);
  };

  const confirm = async () => {
    if (inFlight.current || !snapshot) return;
    inFlight.current = true;
    setBusy(true);
    setProblem(null);
    try {
      await new Promise<void>((resolve) => requestAnimationFrame(() => setTimeout(resolve, 0)));
      const result = await approveTreasuryChange({
        custody,
        token,
        identity,
        vaultId,
        treasuryAddress: snapshot.address,
        change: snapshot.change,
      });
      setSheetOpen(false);
      setAck({ approvals: result.approvals, needed: result.needed });
      void queryClient.invalidateQueries({ queryKey: keys.treasury(vaultId) });
    } catch (err) {
      const p = describe(err, method?.name ?? null);
      if (p === 'recheck') {
        // The approval may have reached Q-Vault with no answer the phone could read: ask again.
        const after = await query.refetch({ cancelRefetch: true });
        const c = after.data?.change?.reconfiguration;
        if (c && c.id === changeId && c.approved_by_me) {
          setSheetOpen(false);
          setAck({ approvals: c.approvals, needed: c.needed });
        } else {
          setProblem({
            tone: 'warning',
            text: "This phone couldn't confirm Q-Vault received your approval. Trying again won't count it twice.",
          });
        }
      } else if (p === 'already') {
        setSheetOpen(false);
        void query.refetch();
      } else {
        setProblem(p);
        if (p.tone !== 'neutral') feedback.refused();
      }
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  const report = () => {
    const text = [
      'Q-Vault treasury change report',
      `Vault: ${vaultName} (${vaultId})`,
      `Change: ${change.id}, ${change.state}`,
      `Check: ${integrity.ok ? 'passed' : `failed (${integrity.why})`}`,
      `Stated digest: ${change.digest ?? 'none'}`,
      `Treasury: ${address}`,
      `App: ${Constants.expoConfig?.version ?? 'unknown'}`,
      `At: ${new Date().toISOString()}`,
    ].join('\n');
    void Share.share({ message: text }).catch(() => {});
  };
  const items: MoreItem[] = [
    { key: 'web', title: 'Open on the web', icon: 'external', onPress: openWeb },
    { key: 'report', title: 'Copy a report', icon: 'alert', onPress: report },
  ];

  const action = status.action;
  const bar =
    offline && action.kind === 'approve' ? (
      <ActionBar message={problem && !sheetOpen ? problem : null} line={OFFLINE_SIGNING} />
    ) : action.kind === 'approve' ? (
      <ActionBar
        message={problem && !sheetOpen ? problem : null}
        primary={{ label: checking ? 'Checking…' : 'Approve change', onPress: requestApprove, busy: checking, disabled: busy }}
      />
    ) : action.kind === 'web' && action.fix ? (
      <ActionBar primary={{ label: 'Open on the web', variant: 'secondary', onPress: openWeb }} />
    ) : action.kind === 'report' ? (
      <ActionBar
        stack
        primary={{ label: 'Copy a report', variant: 'secondary', onPress: report }}
        secondary={{ label: 'Open on the web', variant: 'quiet', onPress: openWeb }}
      />
    ) : null;

  return (
    <Screen edges={['top']}>
      <NavBar
        onBack={onBack}
        title={vaultName}
        actions={[{ icon: Platform.OS === 'android' ? 'more-vertical' : 'more', label: 'More options', onPress: () => setMore(true) }]}
      />
      <OfflineNotice at={query.dataUpdatedAt} />
      <Scroll refreshing={query.isRefetching} onRefresh={() => void query.refetch()}>
        <View style={s.stack}>
          {!integrity.ok ? (
            <Banner
              tone="critical"
              title="Don't approve this change"
              detail="The keys shown aren't the ones that would be signed. Nothing has been signed, and this phone won't sign it."
            />
          ) : (
            <View style={s.labelled}>
              <StatusLine
                badge={status.badge}
                when={collecting && !Number.isNaN(until) ? `Until ${dueWhen(change.valid_until, now)}` : null}
                soon={soon}
                line={status.line}
              />
              {action.kind === 'web' && action.fix ? (
                <TextLink label="Approve treasury payments on this phone" onPress={onOpenTreasuryApprovals} />
              ) : null}
            </View>
          )}

          <View style={s.titleBlock}>
            <Text role="titleSm" accessibilityRole="header">
              {`Treasury change in ${vaultName}`}
            </Text>
            <Text role="caption" tone="muted">
              {requestedLine(change, now)}
            </Text>
          </View>

          {/* A summary of signed identities, not signed prose: sans (§6.15). */}
          <Text role="body">{summary}</Text>

          {integrity.ok ? (
            <View style={s.quorum}>
              <Seal filled={change.approvals} required={change.needed} size={14} />
              {collecting ? (
                <Text role="body" tone="muted">
                  {changeConsequence(change)}
                </Text>
              ) : null}
            </View>
          ) : null}

          <List>
            <DisclosureRow
              leading={
                <Icon
                  name={integrity.ok ? 'check-circle' : 'alert'}
                  size={20}
                  color={integrity.ok ? t.color.status.success.fg : t.color.status.critical.fg}
                />
              }
              title={integrity.ok ? 'Checked on this phone' : 'What failed'}
              onPress={() => setEvidence(true)}
            />
          </List>
        </View>
      </Scroll>

      {bar}

      <Sheet
        visible={sheetOpen}
        onClose={close}
        dismissible={!busy}
        title="Approve this treasury change"
        footer={
          <>
            {problem ? <InlineMessage tone={problem.tone} text={problem.text} /> : null}
            <Button
              label={methodButton('Approve', method)}
              onPress={() => void confirm()}
              busy={busy}
              full
            />
            <Button label="Cancel" variant="quiet" onPress={close} disabled={busy} full />
          </>
        }
      >
        {snapshot ? (
          <View style={s.stack16}>
            <Text role="body">{changeSummary(snapshot.change, treasury?.signer_count ?? null)}</Text>
            <Text role="body" tone="muted">
              {`${changeConsequence(snapshot.change)} An approval can't be withdrawn.`}
            </Text>
          </View>
        ) : null}
      </Sheet>

      <Sheet visible={evidence} onClose={() => setEvidence(false)} title={integrity.ok ? 'Checked on this phone' : 'What failed'}>
        <View style={s.stack16}>
          {integrity.ok ? (
            <>
              <Check ok text="The keys shown are the ones an approval signs: this phone worked out the change's digest itself." />
              <Check ok text={`It is a change to ${vaultName}'s treasury.`} />
              <Check text="Checked again, with your seat on the treasury, when you approve." />
            </>
          ) : (
            <Check ok={false} text="The digest this phone worked out doesn't match the one Q-Vault sent, so the keys shown may not be the ones signed." />
          )}
          <Text role="body" tone="muted">
            {"Don't approve a change you don't recognise; ask the person who requested it."}
          </Text>
          {change.digest ? <Identifier label="Change digest" value={change.digest} /> : null}
          {address ? <Identifier label="Treasury" value={address} /> : null}
          {(change.people?.add ?? []).map((p, i) =>
            p.key_fingerprint ? <Identifier key={`a${i}`} label={`Joins: ${p.name ?? 'someone'}`} value={p.key_fingerprint} /> : null,
          )}
          {(change.people?.remove ?? []).map((p, i) =>
            p.key_fingerprint ? <Identifier key={`r${i}`} label={`Leaves: ${p.name ?? 'someone'}`} value={p.key_fingerprint} /> : null,
          )}
        </View>
      </Sheet>

      <MoreSheet visible={more} onClose={() => setMore(false)} items={items} title="This change" />

      {ack ? (
        <SignedOverlay
          visible
          mark="tick"
          sealed={ack.approvals >= ack.needed}
          headline={ack.approvals >= ack.needed ? 'Change approved' : 'Approval signed'}
          line={
            ack.approvals >= ack.needed
              ? 'Yours was the approval that met the rule. The treasury applies the change at its next check.'
              : ack.needed - ack.approvals === 1
                ? 'One more approval is needed.'
                : `${ack.needed - ack.approvals} more approvals are needed.`
          }
          filled={ack.approvals}
          required={ack.needed}
          onDone={() => setAck(null)}
        />
      ) : null}
    </Screen>
  );
}

function Check({ ok, text }: { ok?: boolean; text: string }) {
  const t = useTheme();
  const s = useStyles();
  const color = ok === undefined ? t.color.textMuted : ok ? t.color.status.success.fg : t.color.status.critical.fg;
  return (
    <View style={s.check} accessible accessibilityLabel={text}>
      <Icon name={ok === undefined ? 'info' : ok ? 'check-circle' : 'alert'} size={20} color={color} />
      <Text role="body" style={s.flex}>
        {text}
      </Text>
    </View>
  );
}

/** What the sheet says when an approval fails (§6.6's table, for a change). Never a raw message. */
function describe(err: unknown, method: string | null): Problem | 'recheck' | 'already' {
  if (err instanceof PayloadMismatchError) {
    return { tone: 'critical', text: "Refused to sign: this change doesn't match what Q-Vault says it is. Nothing was signed." };
  }
  if (err instanceof NotThisPhonesSeatError) {
    return { tone: 'warning', text: "The treasury doesn't hold this phone's key for you, so nothing was signed." };
  }
  if (err instanceof NoScreenLockError) return { tone: 'critical', text: 'Set a screen lock to sign with this phone.' };
  if (err instanceof SelfVerificationError) {
    return { tone: 'critical', text: "This phone's key can't sign any more. Nothing was signed." };
  }
  if (err instanceof Error && err.name === 'AuthenticationCancelled') {
    return { tone: 'neutral', text: `${method ?? 'The check'} was cancelled. Nothing was signed.` };
  }
  if (err instanceof ApiError) {
    if (err.code === 'already_approved') return 'already';
    if (err.code === 'chain_unavailable') {
      return { tone: 'warning', text: "Sepolia didn't answer, so your approval wasn't counted. Try again in a minute." };
    }
    return { tone: 'warning', text: 'Something went wrong, so nothing was signed. Try again.' };
  }
  if (err instanceof TransportError) return 'recheck';
  if (err instanceof Error && /deadline|registered|already approved/i.test(err.message)) {
    return { tone: 'warning', text: "This change can't be approved now. Nothing was signed." };
  }
  return { tone: 'warning', text: 'Something went wrong, so nothing was signed. Try again.' };
}

const useStyles = makeStyles((t) => ({
  flex: { flex: 1 },
  skeleton: { gap: t.space[12], paddingTop: t.space[8] },
  stack: { gap: t.space[24], paddingTop: t.space[8] },
  stack16: { gap: t.space[16] },
  labelled: { gap: t.space[8] },
  titleBlock: { gap: t.space[4] },
  quorum: { gap: t.space[8] },
  check: { flexDirection: 'row', gap: t.space[12], alignItems: 'flex-start' },
}));
