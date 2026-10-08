// The status badge and the status line (phone-ux §5.4).
//
// The badge words are S6's closed vocabulary, computed by `personalStatus()`; the word is always
// there, so colour is never the only signal. The status line sits at the top of every decision: the
// badge on the left, the due time or outcome date on the right, and one personal sentence under it.

import { View } from 'react-native';

import { makeStyles, scaleCap, useTheme, type Tone } from '../theme/index.ts';
import { Icon } from './Icon.tsx';
import { Text } from './Text.tsx';

export function StatusBadge({ word, tone }: { word: string; tone: Tone }) {
  const t = useTheme();
  const s = useStyles();
  const palette = t.color.status[tone];
  return (
    <View
      style={[s.badge, { backgroundColor: palette.bg, borderColor: palette.border }]}
      accessibilityRole="text"
      accessibilityLabel={word}
    >
      <Text role="label" color={palette.fg} maxScale={scaleCap.badge} numberOfLines={1}>
        {word}
      </Text>
    </View>
  );
}

export function StatusLine({
  badge,
  when,
  soon = false,
  passed = false,
  line,
}: {
  badge: { word: string; tone: Tone } | null;
  /** "Today, 18:00", "Approved 4 Oct". */
  when?: string | null;
  /** Due within 24 hours: the warning tone and a clock, so it is never colour alone (§8.5). */
  soon?: boolean;
  /**
   * `when` is a limit that has already passed ("Treasury limit passed 7 Oct"): the warning tone with
   * the alert mark instead of the clock, and read without "Due".
   */
  passed?: boolean;
  line?: string | null;
}) {
  const t = useTheme();
  const s = useStyles();
  const warn = soon || passed;
  const label = [badge?.word, when ? `${soon && !passed ? 'Due ' : ''}${when}` : null, line]
    .filter(Boolean)
    .join('. ');
  return (
    <View style={s.statusLine} accessible accessibilityLabel={label}>
      <View style={[s.statusTop, t.stacked && s.statusTopStacked]}>
        {badge ? <StatusBadge word={badge.word} tone={badge.tone} /> : null}
        {when ? (
          <View style={s.when}>
            {warn ? <Icon name={passed ? 'alert' : 'clock'} size={16} color={t.color.status.warning.fg} /> : null}
            <Text role="caption" tone={warn ? 'warning' : 'muted'} tabular>
              {when}
            </Text>
          </View>
        ) : null}
      </View>
      {line ? (
        <Text role="body" tone="muted">
          {line}
        </Text>
      ) : null}
    </View>
  );
}

const useStyles = makeStyles((t) => ({
  badge: {
    minHeight: 24,
    borderRadius: t.radius.badge,
    borderWidth: 1,
    paddingHorizontal: t.space[8],
    justifyContent: 'center',
    alignSelf: 'flex-start',
  },
  statusLine: { gap: t.space[8] },
  statusTop: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: t.space[12],
    flexWrap: 'wrap',
  },
  statusTopStacked: { flexDirection: 'column', alignItems: 'flex-start', gap: t.space[4] },
  when: { flexDirection: 'row', alignItems: 'center', gap: t.space[4] },
}));
