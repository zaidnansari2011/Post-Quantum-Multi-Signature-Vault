// The vault page's two sheets (phone-ux §6.14, §6.15): who is on the vault, and its treasury.
//
// Both are glances. Changing members, creating a treasury and asking for a treasury update are web
// jobs (§1.1, owner Q5): the phone states the fact and says where to do it. A change to the
// treasury's signers that is waiting on approvals is a row at the top of the treasury sheet, which
// opens its own screen, where it is checked and approved (§6.15).

import { useState } from 'react';
import { Linking, View } from 'react-native';

import {
  Avatar,
  Button,
  Identifier,
  KeyValue,
  List,
  ListRow,
  Sheet,
  Text,
  TextLink,
} from '../../ui/index.tsx';
import { makeStyles } from '../../theme/index.ts';
import type { TreasuryResponse, VaultMember } from '../../api/schemas.ts';
import { changeSummary, treasuryChangeStatus } from '../../logic/treasuryChange.ts';
import { ruleSentence } from '../../logic/workspace.ts';

const ROLE_WORDS: Record<string, string> = { owner: 'Owner', signer: 'Approver', viewer: 'Viewer' };

export function MembersSheet({
  visible,
  onClose,
  members,
  onWeb,
}: {
  visible: boolean;
  onClose: () => void;
  members: VaultMember[];
  onWeb: () => void;
}) {
  const [shown, setShown] = useState<number | null>(null);
  // Approvers first, then viewers; you among them, by name.
  const order = (m: VaultMember) => (m.role === 'viewer' ? 1 : 0);
  const sorted = [...members].sort((a, b) => order(a) - order(b) || (a.name ?? '').localeCompare(b.name ?? ''));
  return (
    <Sheet
      visible={visible}
      onClose={onClose}
      title={members.length === 1 ? 'One member' : `${members.length} members`}
      footer={<Button label="Change members on the web" variant="quiet" onPress={onWeb} full />}
    >
      <List>
        {sorted.map((m) => {
          const name = m.name ?? 'Someone';
          const role = ROLE_WORDS[m.role] ?? 'Member';
          const noKey = m.role !== 'viewer' && m.has_key === false;
          const caption = [
            noKey ? "No key yet, can't approve yet" : null,
            shown === m.user_id ? m.email : null,
          ]
            .filter(Boolean)
            .join('\n');
          return (
            <ListRow
              key={m.user_id}
              leading={<Avatar name={name} size={32} />}
              title={m.is_me ? `${name} (you)` : name}
              caption={caption || null}
              captionTone={noKey ? 'warning' : 'muted'}
              value={role}
              onPress={m.email ? () => setShown(shown === m.user_id ? null : m.user_id) : undefined}
              chevron={false}
              accessibilityHint={m.email ? (shown === m.user_id ? 'Hides their email' : 'Shows their email') : undefined}
            />
          );
        })}
      </List>
    </Sheet>
  );
}

export function TreasurySheet({
  visible,
  onClose,
  vaultName,
  vaultRule,
  viewerId,
  data,
  fingerprint,
  onOpenChange,
  onWeb,
}: {
  visible: boolean;
  onClose: () => void;
  vaultName: string;
  vaultRule: { m: number | null; n: number };
  viewerId: number;
  data: TreasuryResponse;
  fingerprint: string;
  onOpenChange: (changeId: number) => void;
  onWeb: () => void;
}) {
  const s = useStyles();
  const treasury = data.treasury;
  if (!treasury) return null;
  const status = data.status ?? null;
  const change = data.change?.reconfiguration ?? null;
  const pending = data.change?.pending_change ?? null;
  const seat = treasury.signers.find((x) => x.user_id === viewerId);
  const sameRule = vaultRule.m === treasury.threshold_m && vaultRule.n === treasury.signer_count;
  const rule = ruleSentence(treasury.threshold_m, treasury.signer_count).replace(/\.$/, '');
  const changeStatus = change
    ? treasuryChangeStatus({
        change,
        fingerprint,
        integrity: { ok: true },
        linked: true,
        vaultName,
        now: Date.now(),
      })
    : null;
  const changeOpen = changeStatus !== null && [2, 3, 4, 5, 6, 7, 8].includes(changeStatus.row) && change!.state !== 'done';
  const etherscan = treasury.chain_id === 11155111 ? `https://sepolia.etherscan.io/address/${treasury.address}` : null;

  return (
    <Sheet visible={visible} onClose={onClose} title="Treasury">
      <View style={s.stack}>
        {changeOpen && change ? (
          <List>
            <ListRow
              icon="key"
              title="Treasury change"
              caption={`${changeStatus!.badge?.word ?? ''}. ${changeSummary(change, treasury.signer_count)}`}
              captionLines={3}
              onPress={() => {
                onClose();
                onOpenChange(change.id);
              }}
              accessibilityHint="Opens the change"
            />
          </List>
        ) : null}

        {status?.balance ? (
          <View style={s.lead} accessible accessibilityLabel={`Balance, ${status.balance.replace(/ETH$/, 'ether')}`}>
            <Text role="figure" tabular>
              {status.balance}
            </Text>
            <Text role="caption" tone="muted">
              {`In the treasury of ${vaultName}, on Sepolia`}
            </Text>
          </View>
        ) : (
          <Text role="body" tone="muted">
            {`The treasury of ${vaultName} is on Sepolia. Sepolia didn't answer, so its balance isn't known right now.`}
          </Text>
        )}

        <View>
          <Identifier label="Address" value={treasury.address} />
          {etherscan ? (
            <TextLink label="View on Etherscan" onPress={() => void Linking.openURL(etherscan).catch(() => {})} />
          ) : null}
        </View>
        <KeyValue
          label="Approvals needed"
          value={sameRule ? `${rule}, the same as the vault` : `${rule}. The vault's rule has changed since; an owner can update the treasury on the web.`}
        />
        {status ? (
          <KeyValue label="Payouts today" value={`${status.payouts_left_today} of ${status.payouts_per_day} left`} />
        ) : null}
        <KeyValue
          label="Your key here"
          value={
            !seat
              ? "None: you don't approve its payments"
              : seat.custody === 'password'
                ? 'Your password key'
                : seat.key_active
                  ? 'A phone key of yours'
                  : 'A phone key of yours that was removed'
          }
        />

        {pending && !changeOpen ? (
          <View style={s.stack8}>
            <Text role="body" tone="muted">
              {`This treasury needs updating: ${pendingSentence(pending)}. An owner can update it on the web.`}
            </Text>
            <Button label="Open on the web" variant="secondary" onPress={onWeb} />
          </View>
        ) : null}
      </View>
    </Sheet>
  );
}

/** "Brij's new key isn't registered" in the web's words, from the vault-treasury difference. */
function pendingSentence(c: NonNullable<NonNullable<TreasuryResponse['change']>['pending_change']>): string {
  const name = (p: { name: string | null }) => p.name ?? 'someone';
  const parts: string[] = [];
  if (c.added.length) parts.push(`${c.added.map(name).join(', ')} ${c.added.length === 1 ? "isn't" : "aren't"} on it yet`);
  if (c.removed.length) parts.push(`${c.removed.map(name).join(', ')} ${c.removed.length === 1 ? 'is' : 'are'} still on it`);
  if (c.rotated.length) parts.push(`${c.rotated.map((p) => `${name(p)}'s new key`).join(', ')} isn't registered`);
  if (c.threshold_from !== c.threshold_to) parts.push(`it needs ${c.threshold_from} approvals, not ${c.threshold_to}`);
  return parts.join('; ') || 'its signers differ from the vault';
}

const useStyles = makeStyles((t) => ({
  stack: { gap: t.space[16] },
  stack8: { gap: t.space[8] },
  lead: { gap: t.space[4] },
}));
