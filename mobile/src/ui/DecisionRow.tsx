// A decision in a list (phone-ux §5.6). Replaces DecisionCard.
//
//   Top up the release deployer wallet            0.25 ETH
//   Operations, from Gracian
//   (o)(o) 1 of 2                       Tue 6 Oct, 17:00
//
// A row, not a card: no border, no radius, 12/16 padding, about 88pt, so six fit on a 390 x 844
// screen. The title is sans because it is unsigned. No badge in the Approvals list (the headline
// says it), and no Approve or Reject: nothing signs from a list (§1.4 rule 5).
//
// One accessibility element with a composed label, so a screen reader hears the decision once.

import type { ReactNode } from 'react';
import { View } from 'react-native';

import { waitingBadge } from '../logic/personalStatus.ts';
import { dueWhen } from '../logic/words.ts';
import { makeStyles, useTheme } from '../theme/index.ts';
import { parseInstant } from '../time.ts';
import { Icon } from './Icon.tsx';
import { Seal } from './Seal.tsx';
import { Skeleton } from './messages.tsx';
import { Text, type TextTone } from './Text.tsx';
import { Touchable } from './Touchable.tsx';

const DAY = 24 * 60 * 60 * 1000;

export type DecisionRowProps = {
  title: string;
  vault: string;
  /** A1: "from Gracian", or "raised by you". Unsigned display. */
  from?: string | null;
  /** A2: the display amount for a payment, "0.25 ETH". */
  amount?: string | null;
  approvals: number;
  required: number;
  expiresAt: string | null;
  /** `waiting`: "Waiting on 1" leads line 3. `web`: line 3's right says so. `outcome`: history. */
  variant?: 'queue' | 'waiting' | 'web' | 'outcome';
  /** The web variant's note on line 3 (default "Approve on the web"): where it can be approved. */
  note?: string;
  /** The outcome variant's line 3: "Approved", with its date. */
  outcome?: { word: string; tone: TextTone; when?: string | null };
  /** The outcome variant's right side: this person's part ("You approved"). */
  part?: string | null;
  /** Waiting: whether it can still pass (R5); false reads "Can't pass" in place of "Waiting on N". */
  canStillPass?: boolean;
  /** One caption under line 3: who can still act, or why it can't pass. */
  note2?: string | null;
  note2Tone?: TextTone;
  /** A sibling control on the right, never inside the row's own target (§4.6): Remind. */
  trailing?: ReactNode;
  onPress: () => void;
  now?: number;
};

export function DecisionRow({
  title,
  vault,
  from,
  amount,
  approvals,
  required,
  expiresAt,
  variant = 'queue',
  note = 'Approve on the web',
  outcome,
  part,
  canStillPass,
  note2,
  note2Tone = 'muted',
  trailing,
  onPress,
  now = Date.now(),
}: DecisionRowProps) {
  const t = useTheme();
  const s = useStyles();
  const deadline = parseInstant(expiresAt);
  const due = dueWhen(expiresAt, now);
  const soon = !Number.isNaN(deadline) && deadline > now && deadline - now < DAY;
  const line2 = from ? `${vault}, ${from}` : vault;
  const stacked = t.stacked;

  const right =
    variant === 'outcome' && part ? (
      <Text role="caption" tone="muted" numberOfLines={1} style={s.note}>
        {part}
      </Text>
    ) : variant === 'outcome' && outcome ? (
      <Text role="caption" tone={outcome.tone} tabular>
        {outcome.when ? `${outcome.word} ${outcome.when}` : outcome.word}
      </Text>
    ) : variant === 'web' ? (
      <Text role="caption" tone="muted" numberOfLines={1} style={s.note}>
        {note}
      </Text>
    ) : due ? (
      <View style={s.due}>
        {soon ? <Icon name="clock" size={14} color={t.color.status.warning.fg} /> : null}
        <Text role="caption" tone={soon ? 'warning' : 'muted'} tabular>
          {due}
        </Text>
      </View>
    ) : null;

  // "Waiting on N", or "Can't pass" when the server says too few can still approve it (R5): the
  // same derived word as the decision's own status line (`waitingBadge`).
  const waitingWord = waitingBadge(approvals, required, canStillPass);
  const left =
    variant === 'waiting' ? (
      <View style={s.marks}>
        <Seal filled={approvals} required={required} size={10} showCount={false} />
        <Text role="caption" tone={waitingWord.tone === 'warning' ? 'warning' : 'muted'} tabular>
          {waitingWord.word}
        </Text>
      </View>
    ) : variant === 'outcome' && part && outcome ? (
      <Text role="caption" tone={outcome.tone} tabular>
        {outcome.when ? `${outcome.word} ${outcome.when}` : outcome.word}
      </Text>
    ) : (
      <Seal filled={approvals} required={required} size={10} />
    );

  const label = [
    title,
    amount ? `Payment of ${amount.replace(/ETH$/, 'ether')}` : null,
    line2,
    variant === 'waiting' ? waitingWord.word : variant === 'outcome' && part ? null : `${approvals} of ${required} approvals`,
    variant === 'outcome' && outcome
      ? `${outcome.word}${outcome.when ? ` ${outcome.when}` : ''}${part ? `. ${part}` : ''}`
      : variant === 'web'
        ? `${note}${due ? `. Due ${due}` : ''}`
        : due
          ? `Due ${due}`
          : null,
    note2 ?? null,
  ]
    .filter(Boolean)
    .join('. ');

  const row = (
    <Touchable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityHint="Opens the decision"
      ringRadius={0}
      style={({ pressed }) => [s.row, pressed && s.pressed]}
    >
      <View style={[s.line, stacked && s.lineStacked]}>
        <Text role="bodyStrong" numberOfLines={2} style={stacked ? null : s.title}>
          {title}
        </Text>
        {amount ? (
          <Text role="bodyStrong" tabular numberOfLines={1} style={s.amount}>
            {amount}
          </Text>
        ) : null}
      </View>
      {variant === 'web' && due ? (
        // The "Approve on the web" variant: line 3 says where, so the due time moves here (§5.6).
        <View style={[s.line, stacked && s.lineStacked]}>
          <Text role="caption" tone="muted" numberOfLines={1} style={stacked ? null : s.title}>
            {line2}
          </Text>
          {/* Due soon carries the clock as well as the tone, never colour alone (§8.5). */}
          <View style={s.due}>
            {soon ? <Icon name="clock" size={14} color={t.color.status.warning.fg} /> : null}
            <Text role="caption" tone={soon ? 'warning' : 'muted'} tabular>
              {due}
            </Text>
          </View>
        </View>
      ) : (
        <Text role="caption" tone="muted" numberOfLines={1}>
          {line2}
        </Text>
      )}
      <View style={[s.line, s.line3, stacked && s.lineStacked]}>
        {left}
        {right}
      </View>
      {note2 ? (
        <Text role="caption" tone={note2Tone} numberOfLines={2}>
          {note2}
        </Text>
      ) : null}
    </Touchable>
  );
  if (!trailing) return row;
  // The row and its second action are siblings, so a screen reader reaches both (§6.4).
  return (
    <View style={s.withTrailing}>
      <View style={s.flex}>{row}</View>
      <View style={s.trailing}>{trailing}</View>
    </View>
  );
}

/** The shape of a row while it loads (§5.10): skeletons match rows, not cards. */
export function DecisionRowSkeleton() {
  const s = useStyles();
  return (
    <View style={s.row} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      <Skeleton width="72%" height={16} />
      <Skeleton width="40%" height={12} />
      <View style={[s.line, s.line3]}>
        <Skeleton width={72} height={12} />
        <Skeleton width={96} height={12} />
      </View>
    </View>
  );
}

const useStyles = makeStyles((t) => ({
  row: {
    paddingHorizontal: t.layout.gutter,
    paddingVertical: t.space[12],
    gap: t.space[4],
    backgroundColor: t.color.surface,
  },
  pressed: { backgroundColor: t.color.fill },
  line: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: t.space[12] },
  lineStacked: { flexDirection: 'column', alignItems: 'flex-start', gap: t.space[4] },
  line3: { alignItems: 'center', marginTop: t.space[2] },
  title: { flex: 1 },
  amount: { flexShrink: 0 },
  note: { flexShrink: 1, textAlign: 'right' },
  marks: { flexDirection: 'row', alignItems: 'center', gap: t.space[8] },
  withTrailing: { flexDirection: 'row', alignItems: 'stretch', backgroundColor: t.color.surface },
  flex: { flex: 1 },
  trailing: { justifyContent: 'center', paddingRight: t.space[8] },
  due: { flexDirection: 'row', alignItems: 'center', gap: t.space[4] },
}));
