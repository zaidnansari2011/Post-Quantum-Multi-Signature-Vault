// A vault's treasury on the phone (docs/plans/onchain-execution.md, D40, Phases 7b and 8): where it
// is, what it holds, what it may still pay today, and any change to its signers, with the approval
// when the treasury holds this phone's key for this person.
//
// What a change adds, removes and requires is read from its signed inputs, the fields this phone
// hashes itself before it approves; the names beside them are the server's description.
// (Phone-ux §6.15 moves creating and updating a treasury to the web in P3, with the native alert.)

import { useState } from 'react';
import { Alert, View } from 'react-native';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { makeStyles } from '../theme/index.ts';
import { Button } from './Button.tsx';
import { feedback } from './feedback.ts';
import { Identifier } from './Identifier.tsx';
import { KeyValue } from './List.tsx';
import { Banner, InlineMessage } from './messages.tsx';
import { Section } from './structure.tsx';
import { Text } from './Text.tsx';
import { useEnrolledSession } from '../session.tsx';
import * as api from '../api/endpoints.ts';
import { ApiError, TransportError } from '../api/client.ts';
import type { ReconfigurationView, TreasuryChange } from '../api/schemas.ts';
import {
  NoScreenLockError,
  NotThisPhonesSeatError,
  PayloadMismatchError,
  SelfVerificationError,
  approveTreasuryChange,
} from '../flows.ts';

const OPEN = ['queued', 'registering_keys', 'collecting_approvals', 'submitting', 'finalizing'];

export function TreasuryCard({ vaultId }: { vaultId: number }) {
  const s = useStyles();
  const { token, identity, custody } = useEnrolledSession();
  const queryClient = useQueryClient();
  const [error, setError] = useState<{ title: string; detail?: string } | null>(null);

  const query = useQuery({
    queryKey: ['treasury', vaultId],
    queryFn: ({ signal }) => api.fetchTreasury(token, vaultId, signal),
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ['treasury', vaultId] });

  const create = useMutation({
    mutationFn: () => api.createTreasury({ token, vaultId }),
    onSuccess: () => {
      setError(null);
      refresh();
    },
    onError: (err) => {
      setError(describe(err));
      feedback.refused();
    },
  });

  const ask = useMutation({
    mutationFn: (confirm: string | null) => api.requestReconfiguration({ token, vaultId, confirm }),
    onSuccess: () => {
      setError(null);
      refresh();
    },
    onError: (err) => {
      setError(describe(err));
      feedback.refused();
    },
  });

  const approve = useMutation({
    mutationFn: (change: ReconfigurationView) =>
      approveTreasuryChange({
        custody,
        token,
        identity,
        vaultId,
        treasuryAddress: query.data!.treasury!.address,
        change,
      }),
    onSuccess: () => {
      setError(null);
      feedback.signed();
      refresh();
    },
    onError: (err) => {
      if (err instanceof TransportError) {
        // The approval was signed and sent. No answer the phone could read says nothing about
        // whether Q-Vault recorded it (phone-ux §6.6), so it says so and asks again.
        setError({
          title: 'Q-Vault may have received your approval.',
          detail: 'Checking the change again now. If it shows your approval, it counted.',
        });
        refresh();
      } else {
        setError(describe(err));
      }
      feedback.refused();
    },
  });

  const data = query.data;
  if (!data) return null;
  const { treasury, job, status } = data;
  const change: TreasuryChange | null = data.change ?? null;
  const jobOpen = job !== null && !['done', 'failed', 'cancelled'].includes(job.state);
  if (!treasury && !jobOpen && !data.may_create) return null;

  const r = change?.reconfiguration ?? null;
  const rOpen = r !== null && OPEN.includes(r.state);

  const requestChange = () => {
    const warnings = change?.warnings ?? [];
    if (warnings.length === 0) {
      ask.mutate(null);
      return;
    }
    Alert.alert(
      'Update the treasury?',
      warnings.map((w) => w[0].toUpperCase() + w.slice(1) + '.').join('\n'),
      [
        { text: 'Cancel', style: 'cancel' },
        // Confirms exactly the warnings shown: the server asks again if they have changed.
        { text: 'Update', style: 'destructive', onPress: () => ask.mutate(change?.warnings_digest ?? null) },
      ],
    );
  };

  return (
    <Section title="Treasury">
      <View style={s.card}>
        {error ? <Banner tone="critical" title={error.title} detail={error.detail} /> : null}
        {treasury ? (
          <View style={s.facts}>
            <Identifier label="Address" value={treasury.address} />
            {/* Short values sit on their label's line, as everywhere else in the app. */}
            <InlineFact label="Network" value="Sepolia" />
            <InlineFact label="Balance" value={status?.balance ?? 'Unavailable'} />
            <InlineFact label="Approvals" value={`${treasury.threshold_m} of ${treasury.signer_count}`} />
            {status ? (
              <InlineFact
                label="Payouts today"
                value={`${status.payouts_left_today} of ${status.payouts_per_day} left`}
              />
            ) : null}
          </View>
        ) : jobOpen ? (
          <InlineMessage tone="warning" text={job!.reason ?? 'Creating the treasury'} />
        ) : (
          <View style={s.facts}>
            {job?.state === 'failed' ? (
              <Text role="caption" tone="muted">{`The last attempt stopped: ${job.reason}`}</Text>
            ) : null}
            <Button label="Create treasury" variant="secondary" busy={create.isPending} onPress={() => create.mutate()} />
          </View>
        )}

        {rOpen ? (
          <ChangeInProgress
            change={r!}
            busy={approve.isPending}
            onApprove={() => {
              setError(null);
              approve.mutate(r!);
            }}
          />
        ) : change?.pending_change ? (
          <View style={s.change}>
            <InlineMessage tone="warning" text="Out of date with the vault" />
            <Text role="caption" tone="muted">
              {summary(change)}
            </Text>
            {(change.problems ?? []).map((p) => (
              <Text key={p} role="caption" tone="muted">
                {`${p[0].toUpperCase()}${p.slice(1)}.`}
              </Text>
            ))}
            {change.may_request ? (
              <Button label="Update treasury" variant="secondary" busy={ask.isPending} onPress={requestChange} />
            ) : null}
          </View>
        ) : null}
      </View>
    </Section>
  );
}

/** A label and a short value on one line: one accessibility element, "Network, Sepolia". */
function InlineFact({ label, value }: { label: string; value: string }) {
  const s = useStyles();
  return (
    <View style={s.inline} accessible accessibilityLabel={`${label}, ${value}`}>
      <Text role="body" tone="muted">
        {label}
      </Text>
      <Text role="body" tabular style={s.inlineValue}>
        {value}
      </Text>
    </View>
  );
}

function ChangeInProgress({
  change,
  busy,
  onApprove,
}: {
  change: ReconfigurationView;
  busy: boolean;
  onApprove: () => void;
}) {
  const s = useStyles();
  const inputs = change.signing_inputs;
  const canApproveHere =
    change.state === 'collecting_approvals' &&
    change.my_custody === 'device' &&
    !change.approved_by_me &&
    change.approval_problem === null;
  return (
    <View style={s.change}>
      <InlineMessage
        tone="warning"
        text={change.state === 'collecting_approvals' ? 'Change awaiting approval' : 'Change in progress'}
      />
      {inputs ? (
        // The signed fields: what an approval here authorises.
        <Text role="caption" tone="muted">
          {`Adds ${inputs.add.length} ${inputs.add.length === 1 ? 'key' : 'keys'}, removes ${inputs.remove.length}, then needs ${inputs.threshold} ${inputs.threshold === 1 ? 'approval' : 'approvals'}.`}
        </Text>
      ) : null}
      {change.people
        ? [
            ...change.people.add.map((p, i) => ({ p, verb: 'Joins', i })),
            ...change.people.remove.map((p, i) => ({ p, verb: 'Leaves', i })),
          ].map(({ p, verb, i }) => (
            <KeyValue
              key={`${verb}-${i}`}
              label={`${verb}: ${p.name ?? (p.user_id !== null ? `User ${p.user_id}` : 'unknown')}`}
              mono
              value={p.key_fingerprint ?? 'unknown key'}
            />
          ))
        : null}
      <KeyValue label="Approvals" value={`${change.approvals} of ${change.needed}`} />
      {change.reason ? (
        <Text role="caption" tone="muted">
          {change.reason}
        </Text>
      ) : null}
      {change.approved_by_me ? (
        <InlineMessage tone="success" text="You approved" />
      ) : canApproveHere ? (
        <Button label="Approve change" busy={busy} onPress={onApprove} full />
      ) : change.state === 'collecting_approvals' && change.my_custody === 'password' ? (
        <Text role="caption" tone="muted">
          Approve this on the web with your password.
        </Text>
      ) : null}
    </View>
  );
}

function summary(change: TreasuryChange): string {
  const c = change.pending_change!;
  const names = (people: Array<{ name: string | null; user_id: number }>) =>
    people.map((p) => p.name ?? `User ${p.user_id}`).join(', ');
  const parts: string[] = [];
  if (c.added.length) parts.push(`joining: ${names(c.added)}`);
  if (c.removed.length) parts.push(`leaving: ${names(c.removed)}`);
  if (c.rotated.length) parts.push(`new key: ${names(c.rotated)}`);
  if (c.threshold_from !== c.threshold_to) parts.push(`approvals ${c.threshold_from} → ${c.threshold_to}`);
  return parts.join('; ');
}

function describe(err: unknown): { title: string; detail?: string } {
  if (err instanceof PayloadMismatchError) {
    return { title: 'Refused to sign.', detail: 'This change does not match what the server says it is.' };
  }
  if (err instanceof NotThisPhonesSeatError) return { title: 'Not signed on this phone.', detail: err.message };
  if (err instanceof NoScreenLockError) return { title: err.message, detail: 'Nothing was signed.' };
  if (err instanceof SelfVerificationError) {
    return { title: err.message, detail: 'Enrol this device again to replace the key.' };
  }
  if (err instanceof Error && err.name === 'AuthenticationCancelled') return { title: 'Nothing was signed.' };
  if (err instanceof ApiError) {
    switch (err.code) {
      case 'chain_unavailable':
        return { title: 'Ethereum did not answer. Nothing was signed.', detail: 'Try again in a moment.' };
      case 'already_approved':
        return { title: 'You have already approved this change.' };
      default:
        return { title: err.message };
    }
  }
  if (err instanceof TransportError) return { title: err.message };
  return { title: err instanceof Error ? err.message : 'Something went wrong.' };
}

const useStyles = makeStyles((t) => ({
  card: {
    backgroundColor: t.color.surface,
    borderWidth: 1,
    borderColor: t.color.border,
    borderRadius: t.radius.card,
    padding: t.space[16],
    gap: t.space[12],
  },
  facts: { gap: t.space[4] },
  inline: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: t.space[12],
    minHeight: 32,
    alignItems: 'center',
  },
  inlineValue: { flexShrink: 1, textAlign: 'right' },
  change: {
    gap: t.space[8],
    paddingTop: t.space[12],
    borderTopWidth: 1,
    borderTopColor: t.color.border,
  },
}));
