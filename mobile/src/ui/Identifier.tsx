// A hash, key or address (phone-ux §5.7, §1.4 rule 8).
//
// Middle-truncated in mono ("0x41Ed…8A19", R7's `middleOut`), with Copy and "Show full". Expanded,
// it is grouped in fours after any "0x", with the first and last 8 hex characters in `text` at
// weight 500 and the middle in `textMuted` (the address-poisoning defence: a 4+4 match can be
// ground in minutes, so the ends a person checks are the strong ones and the rest still shows).
//
// `expanded="always"` renders the expanded form with no way to collapse it. The signing sheets use
// it for a payment's recipient: at the moment of signing the whole address is in front of the
// person, never a shortened one.
//
// Copy goes through React Native's Share sheet (which offers Copy) until a clipboard module is in the
// rework APK (N11): Share is part of React Native, so it adds no native module.

import { useState } from 'react';
import { AccessibilityInfo, Share, View } from 'react-native';

import { middleOut } from '../format.ts';
import { fontFamily, makeStyles, useTheme } from '../theme/index.ts';
import { IconButton, TextLink } from './Button.tsx';
import { Text } from './Text.tsx';

/** "0x 41Ed 8A19 …": the value split into its prefix and groups of four. */
export function groupsOfFour(value: string): { prefix: string; groups: string[] } {
  const prefix = value.startsWith('0x') ? '0x' : '';
  const body = value.slice(prefix.length);
  const groups: string[] = [];
  for (let i = 0; i < body.length; i += 4) groups.push(body.slice(i, i + 4));
  return { prefix, groups };
}

/** "Address 0x 41Ed, ending 8A19": what a screen reader says instead of 42 characters. */
export function spokenIdentifier(label: string, value: string): string {
  const { prefix, groups } = groupsOfFour(value);
  if (groups.length < 3) return `${label} ${value}`;
  const head = `${prefix ? '0x ' : ''}${groups[0]}`;
  return `${label} ${head}, ending ${groups[groups.length - 1]}`;
}

/** The grouped form, ends emphasised. Used by Identifier and by addresses inside signed text. */
export function GroupedValue({ value, emphasiseEnds = true }: { value: string; emphasiseEnds?: boolean }) {
  const t = useTheme();
  const { prefix, groups } = groupsOfFour(value);
  const hex = groups.join('');
  const strongHead = emphasiseEnds && hex.length > 16 ? 8 : hex.length;
  const strongTail = emphasiseEnds && hex.length > 16 ? 8 : 0;
  let seen = 0;
  const pieces = groups.map((g, i) => {
    const chars = g.split('').map((ch, j) => {
      const at = seen + j;
      const strong = at < strongHead || at >= hex.length - strongTail;
      return (
        <Text
          key={j}
          role="code"
          color={strong ? t.color.text : t.color.textMuted}
          style={strong ? { fontFamily: fontFamily.monoMedium } : null}
        >
          {ch}
        </Text>
      );
    });
    seen += g.length;
    return (
      <Text key={i} role="code">
        {chars}
        {i < groups.length - 1 ? ' ' : ''}
      </Text>
    );
  });
  return (
    <Text role="code" selectable>
      {prefix ? (
        <Text role="code" tone="muted">
          {`${prefix} `}
        </Text>
      ) : null}
      {pieces}
    </Text>
  );
}

export function Identifier({
  label,
  value,
  expanded = 'toggle',
  showLabel = true,
}: {
  /** "Address", "Payload hash": spoken, and drawn above the value when `showLabel`. */
  label: string;
  value: string;
  /** 'always' for a payment's recipient in a signing sheet (§1.4 rule 8). */
  expanded?: 'toggle' | 'always';
  showLabel?: boolean;
}) {
  const s = useStyles();
  const [whole, setWhole] = useState(false);
  const short = middleOut(value);
  const canShorten = short !== value;
  const full = expanded === 'always' || whole || !canShorten;

  const share = async () => {
    try {
      await Share.share({ message: value });
    } catch {
      setWhole(true);
    }
  };

  return (
    <View style={s.wrap}>
      {showLabel ? (
        <Text role="caption" tone="muted">
          {label}
        </Text>
      ) : null}
      <View style={s.row}>
        {/* Always the grouped, short reading (§8.2): the whole value is read only when asked. */}
        <View
          style={s.value}
          accessible
          accessibilityLabel={spokenIdentifier(label, value)}
          accessibilityHint="Double tap to hear in full"
          accessibilityActions={[{ name: 'activate' }]}
          onAccessibilityAction={() => {
            const { prefix, groups } = groupsOfFour(value);
            AccessibilityInfo.announceForAccessibility(
              `${label} ${prefix ? '0x ' : ''}${groups.map((g) => g.split('').join(' ')).join(', ')}`,
            );
          }}
        >
          {full ? (
            <GroupedValue value={value} />
          ) : (
            <Text role="code" numberOfLines={1}>
              {short}
            </Text>
          )}
        </View>
        {/* On the value's own row, so an identifier costs one line, not two. */}
        {expanded === 'toggle' && canShorten ? (
          <TextLink
            label={whole ? 'Show less' : 'Show full'}
            accessibilityLabel={whole ? `Shorten the ${label.toLowerCase()}` : `Show the full ${label.toLowerCase()}`}
            onPress={() => setWhole((w) => !w)}
            role="caption"
            compact
          />
        ) : null}
        <IconButton
          icon="copy"
          label={`Copy the ${label.toLowerCase()}`}
          onPress={() => void share()}
          size={18}
          compact
        />
      </View>
    </View>
  );
}

const useStyles = makeStyles((t) => ({
  wrap: { gap: t.space[2] },
  row: { flexDirection: 'row', alignItems: 'flex-start', gap: t.space[4] },
  // The controls are 32pt, so the value's first line is centred on them and the row costs 32.
  value: { flex: 1, minHeight: 32, justifyContent: 'center', paddingVertical: 6 },
}));
