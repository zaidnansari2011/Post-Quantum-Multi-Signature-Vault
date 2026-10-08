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

import { View } from 'react-native';

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
  /** The outcome variant's line 3: "Approved", with its date. */
  outcome?: { word: string; tone: TextTone; when?: string | null };
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
  outcome,
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
    variant === 'outcome' && outcome ? (
      <Text role="caption" tone={outcome.tone} tabular>
        {outcome.when ? `${outcome.word} ${outcome.when}` : outcome.word}
      </Text>
    ) : variant === 'web' ? (
      <Text role="caption" tone="muted">
        Approve on the web
      </Text>
    ) : due ? (
      <View style={s.due}>
        {soon ? <Icon name="clock" size={14} color={t.color.status.warning.fg} /> : null}
        <Text role="caption" tone={soon ? 'warning' : 'muted'} tabular>
          {due}
        </Text>
      </View>
    ) : null;

  const left =
    variant === 'waiting' ? (
      <View style={s.marks}>
        <Seal filled={approvals} required={required} size={10} showCount={false} />
        <Text role="caption" tone="muted" tabular>
          {`Waiting on ${Math.max(1, required - approvals)}`}
        </Text>
      </View>
    ) : (
      <Seal filled={approvals} required={required} size={10} />
    );

  const label = [
    title,
    amount ? `Payment of ${amount.replace(/ETH$/, 'ether')}` : null,
    line2,
    `${approvals} of ${required} approvals`,
    variant === 'outcome' && outcome
      ? `${outcome.word}${outcome.when ? ` ${outcome.when}` : ''}`
      : variant === 'web'
        ? `Approve on the web${due ? `. Due ${due}` : ''}`
        : due
          ? `Due ${due}`
          : null,
  ]
    .filter(Boolean)
    .join('. ');

  return (
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
          <Text role="caption" tone={soon ? 'warning' : 'muted'} tabular>
            {due}
          </Text>
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
    </Touchable>
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
  marks: { flexDirection: 'row', alignItems: 'center', gap: t.space[8] },
  due: { flexDirection: 'row', alignItems: 'center', gap: t.space[4] },
}));
