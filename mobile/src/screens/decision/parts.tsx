// The decision screen's smaller pieces (phone-ux §6.5, §6.6): who decided, the tampered panel, the
// Details sheet and the overflow menu. Each is display only; nothing here signs.

import { useState } from 'react';
import { View } from 'react-native';

import {
  Avatar,
  Identifier,
  SignedText,
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
import { TYPE_LABELS, type DecisionType, type FieldRow } from '../../logic/decisionTypes.ts';

/** Who decided (§6.5 item 8): a compact list, no card. More than four collapse to three. */
export function WhoDecided({
  votes,
  viewerId,
  viewerName,
  now,
}: {
  votes: VoteFacts[];
  viewerId: number;
  /** For the viewer's own avatar: their initials, not "Y". */
  viewerName: string | null;
  now: number;
}) {
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
        <DecidedRow key={line.key} line={line} avatar={line.you && viewerName ? viewerName : line.name} />
      ))}
      {shown.length < lines.length ? (
        <TextLink label={`See all ${lines.length}`} onPress={() => setAll(true)} />
      ) : null}
    </View>
  );
}

function DecidedRow({ line, avatar }: { line: ReturnType<typeof decidedLines>[number]; avatar: string }) {
  const t = useTheme();
  const s = useStyles();
  const [whole, setWhole] = useState(false);
  return (
    <View style={s.decidedRow}>
      <View style={s.decidedHead} accessible accessibilityLabel={[line.text, line.when].filter(Boolean).join(', ')}>
        <Avatar name={avatar} />
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

/**
 * A typed decision's card (S13, §6.21): its fields as rows, in sans, then the signed text one tap
 * away. Drawn only from `rows`, which the phone's own check returned because those fields write the
 * signed text byte for byte: each row IS a line of what everyone signs, so nothing signed is hidden
 * and nothing unsigned is shown (the payment card's rule, D8).
 */
export function TypedCard({ type, rows, text }: { type: DecisionType; rows: FieldRow[]; text: string }) {
  const t = useTheme();
  const s = useStyles();
  const [open, setOpen] = useState(false);
  return (
    <View style={s.card}>
      <Text role="caption" tone="muted">
        {TYPE_LABELS[type]}
      </Text>
      {rows.map((row) => (
        <View
          key={row.label}
          style={[s.field, t.stacked && s.fieldStacked]}
          accessible
          accessibilityLabel={`${row.label}, ${row.value}`}
        >
          <Text role="body" tone="muted" style={t.stacked ? null : s.fieldLabel}>
            {row.label}
          </Text>
          <Text role="body" style={s.fieldValue}>
            {row.value}
          </Text>
        </View>
      ))}
      <Touchable
        onPress={() => setOpen((v) => !v)}
        accessibilityRole="button"
        accessibilityState={{ expanded: open }}
        accessibilityLabel={open ? 'Hide the signed text' : 'Show the signed text'}
        ringRadius={8}
        style={({ pressed }) => [s.disclosure, pressed && s.pressed]}
      >
        <Text role="body" tone="link" style={s.flex}>
          {open ? 'Hide the signed text' : 'Show the signed text'}
        </Text>
        <Icon name={open ? 'chevron-down' : 'chevron-right'} size={16} color={t.color.link} />
      </Touchable>
      {open ? <SignedText text={text} size="decision" /> : null}
    </View>
  );
}

/** "Details" (§6.5 item 10): what the decision is, outside the text that is signed. */
export function DetailsSheet({
  visible,
  onClose,
  detail,
  type,
}: {
  visible: boolean;
  onClose: () => void;
  detail: ProposalDetail;
  /** The type the signed text bears out (the phone's own check); null when it is not one it knows. */
  type?: DecisionType | null;
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
        <KeyValue label="Type" value={action ? 'Payment' : type ? TYPE_LABELS[type] : 'General'} />
        {detail.raised_again_from ? <KeyValue label="Raised again from" value={detail.raised_again_from.title} /> : null}
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
export function MoreSheet({
  visible,
  onClose,
  items,
  title = 'This decision',
}: {
  visible: boolean;
  onClose: () => void;
  items: MoreItem[];
  title?: string;
}) {
  return (
    <Sheet visible={visible} onClose={onClose} title={title}>
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
  card: {
    backgroundColor: t.color.surface,
    borderWidth: 1,
    borderColor: t.color.border,
    borderRadius: t.radius.card,
    padding: t.space[16],
    gap: t.space[8],
  },
  field: { flexDirection: 'row', gap: t.space[12], alignItems: 'flex-start' },
  fieldLabel: { width: 96 },
  fieldStacked: { flexDirection: 'column', gap: t.space[2] },
  fieldValue: { flex: 1 },
  disclosure: {
    minHeight: 44,
    flexDirection: 'row',
    alignItems: 'center',
    gap: t.space[8],
    borderRadius: 8,
    marginTop: t.space[4],
  },
  pressed: { backgroundColor: t.color.fill },
}));
