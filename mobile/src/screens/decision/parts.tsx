// The decision screen's smaller pieces (phone-ux §6.5, §6.6): who decided, the tampered panel, the
// Details sheet and the overflow menu. Each is display only; nothing here signs.

import { useState } from 'react';
import { View } from 'react-native';

import {
  Avatar,
  Identifier,
  Icon,
  KeyValue,
  List,
  ListRow,
  Sheet,
  Text,
  TextLink,
  Touchable,
} from '../../ui/index.tsx';
import { makeStyles, useTheme } from '../../theme/index.ts';
import type { ProposalDetail } from '../../api/schemas.ts';
import { decidedLines, ruleWhenRaised, type VoteFacts } from '../../logic/quorum.ts';
import { tamperReason } from '../../logic/evidence.ts';
import { exactly } from '../../time.ts';

/** Who decided (§6.5 item 8): a compact list, no card. More than four collapse to three. */
export function WhoDecided({ votes, viewerId, now }: { votes: VoteFacts[]; viewerId: number; now: number }) {
  const s = useStyles();
  const [all, setAll] = useState(false);
  const lines = decidedLines(votes, viewerId, now);
  if (lines.length === 0) return null;
  const shown = all || lines.length <= 4 ? lines : lines.slice(0, 3);
  return (
    <View style={s.decided}>
      <Text role="titleSm" accessibilityRole="header">
        Who decided
      </Text>
      {shown.map((line) => (
        <DecidedRow key={line.key} line={line} />
      ))}
      {shown.length < lines.length ? (
        <TextLink label={`See all ${lines.length}`} onPress={() => setAll(true)} />
      ) : null}
    </View>
  );
}

function DecidedRow({ line }: { line: ReturnType<typeof decidedLines>[number] }) {
  const t = useTheme();
  const s = useStyles();
  const [whole, setWhole] = useState(false);
  return (
    <View style={s.decidedRow}>
      <View style={s.decidedHead} accessible accessibilityLabel={[line.text, line.when].filter(Boolean).join(', ')}>
        <Avatar name={line.name} />
        <Text role="body" style={s.flex}>
          {line.text}
        </Text>
        {line.when ? (
          <Text role="caption" tone="muted" tabular>
            {line.when}
          </Text>
        ) : null}
      </View>
      {line.reason ? (
        // The reason is unsigned and in the sans (I-15): never mistaken for what was signed.
        <Touchable
          onPress={() => setWhole((v) => !v)}
          accessibilityRole="button"
          accessibilityLabel={`Reason: ${line.reason}`}
          accessibilityHint={whole ? 'Shows less' : 'Shows the whole reason'}
          ringRadius={8}
          style={({ pressed }) => [s.reason, pressed && { backgroundColor: t.color.fill }]}
        >
          <Text role="body" tone="muted" numberOfLines={whole ? undefined : 2}>
            {`“${line.reason}”`}
          </Text>
        </Touchable>
      ) : null}
    </View>
  );
}

/**
 * The failed check, said once, at the top (§6.6 Tampered): the title, the reason first, then that
 * nothing was signed. Not collapsible. The page withdraws every signing control around it.
 */
export function TamperPanel({ reason }: { reason: string }) {
  const t = useTheme();
  const s = useStyles();
  const palette = t.color.status.critical;
  const why = tamperReason(reason);
  return (
    <View
      style={[s.panel, { backgroundColor: palette.bg, borderColor: palette.border }]}
      accessible
      accessibilityRole="alert"
      accessibilityLabel={`Don't act on this decision. ${why} Nothing has been signed, and this phone won't sign it.`}
    >
      <View style={s.panelHead}>
        <Icon name="alert" size={20} color={palette.fg} style={s.panelIcon} />
        <View style={s.flex}>
          <Text role="bodyStrong" color={palette.fg}>
            {"Don't act on this decision"}
          </Text>
          <Text role="body">{why}</Text>
          <Text role="body">{"Nothing has been signed, and this phone won't sign it."}</Text>
        </View>
      </View>
    </View>
  );
}

/** "Details" (§6.5 item 10): what the decision is, outside the text that is signed. */
export function DetailsSheet({
  visible,
  onClose,
  detail,
}: {
  visible: boolean;
  onClose: () => void;
  detail: ProposalDetail;
}) {
  const s = useStyles();
  const inputs = detail.signing_inputs;
  const action = inputs.action;
  const names = detail.signers
    ? inputs.policy.signers.map((id) => detail.signers!.find((p) => p.user_id === id)?.name ?? null)
    : null;
  const known = names && names.every((n): n is string => n !== null) ? names : null;
  return (
    <Sheet visible={visible} onClose={onClose} title="Details">
      <View style={s.details}>
        <KeyValue label="Vault" value={detail.vault_name ?? `Vault ${detail.vault_id}`} />
        <KeyValue label="Type" value={action ? 'Payment' : 'Decision'} />
        <KeyValue
          label="Rule when raised"
          value={ruleWhenRaised(inputs.policy.M, inputs.policy.N, known)}
        />
        <KeyValue
          label="Raised"
          value={`${exactly(inputs.created_at)}${detail.raised_by?.name ? `, by ${detail.raised_by.name}` : ''}`}
        />
        <KeyValue label="Due" value={detail.expires_at ? exactly(detail.expires_at) : 'No deadline'} />
        {action ? (
          <View>
            <KeyValue
              label="Approvals valid until"
              value={exactly(new Date(action.valid_until * 1000).toISOString())}
            />
            <Text role="caption" tone="muted">
              After this the treasury refuses the payment, even if it is approved.
            </Text>
          </View>
        ) : null}
        <Identifier label="Decision ID" value={detail.proposal_uuid} />
      </View>
    </Sheet>
  );
}

export type MoreItem = { key: string; title: string; icon: Parameters<typeof Icon>[0]['name']; onPress: () => void };

/** The overflow menu, as a sheet (§6.5 item 1). */
export function MoreSheet({ visible, onClose, items }: { visible: boolean; onClose: () => void; items: MoreItem[] }) {
  return (
    <Sheet visible={visible} onClose={onClose} title="This decision">
      <List>
        {items.map((item) => (
          <ListRow
            key={item.key}
            icon={item.icon}
            title={item.title}
            onPress={() => {
              onClose();
              item.onPress();
            }}
          />
        ))}
      </List>
    </Sheet>
  );
}

const useStyles = makeStyles((t) => ({
  flex: { flex: 1 },
  decided: { gap: t.space[12] },
  decidedRow: { gap: t.space[4] },
  decidedHead: { flexDirection: 'row', alignItems: 'center', gap: t.space[12], minHeight: 32 },
  reason: { marginLeft: 36, borderRadius: 8, paddingVertical: t.space[4], minHeight: 32, justifyContent: 'center' },
  panel: { borderWidth: 1, borderRadius: t.radius.card, padding: t.space[16] },
  panelHead: { flexDirection: 'row', gap: t.space[12], alignItems: 'flex-start' },
  panelIcon: { marginTop: 2 },
  details: { gap: t.space[12] },
}));
