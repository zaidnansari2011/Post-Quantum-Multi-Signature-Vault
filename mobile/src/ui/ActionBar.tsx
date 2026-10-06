// The bar pinned to the bottom of a decision (phone-ux §5.3).
//
// Reject on the left and Approve on the right, side by side at 2:3, 12 apart: about 72pt plus the
// inset against 128 for the stacked pair it replaces, which is what keeps a payment's quorum
// sentence above the fold (D2). Reject only opens a sheet, so a mis-tap costs one Cancel. At large
// text (1.6x) or on a window under 340pt they stack, Approve first.
//
// The message slot holds one line for an action's error after its sheet has closed. When there is
// nothing to sign, a centred line replaces the buttons; when nothing applies, there is no bar.

import { type ReactNode } from 'react';
import { useWindowDimensions, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { makeStyles, useTheme, type Tone } from '../theme/index.ts';
import { Button, type ButtonProps } from './Button.tsx';
import { InlineMessage } from './messages.tsx';
import { Text } from './Text.tsx';

export function ActionBar({
  primary,
  secondary,
  message,
  line,
  caption,
  children,
}: {
  /** The one primary action, on the right. */
  primary?: ButtonProps;
  /** Reject (dangerSecondary), on the left at 2:3. */
  secondary?: ButtonProps;
  /** An action's error after its sheet closed: tone, icon and one line, announced. */
  message?: { tone: Tone; text: string } | null;
  /** In place of the buttons, when this person can't act: "You raised this, so you can't approve it." */
  line?: string | null;
  /** A line above a single button: "Once raised, the text can't be changed." */
  caption?: string | null;
  /** Anything else under the buttons (the quiet link of §6.6 state 7). */
  children?: ReactNode;
}) {
  const t = useTheme();
  const s = useStyles();
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const stacked = t.stacked || width < t.breakpoints.narrowWidth;

  return (
    <View style={[s.bar, t.elevation.bar, { paddingBottom: t.space[12] + insets.bottom }]}>
      {message ? <InlineMessage tone={message.tone} text={message.text} /> : null}
      {caption ? (
        <Text role="caption" tone="muted">
          {caption}
        </Text>
      ) : null}
      {line ? (
        <Text role="body" tone="muted" align="center" style={s.line}>
          {line}
        </Text>
      ) : null}
      {primary || secondary ? (
        stacked ? (
          <View style={s.stack}>
            {primary ? <Button {...primary} full /> : null}
            {secondary ? <Button {...secondary} full /> : null}
          </View>
        ) : (
          <View style={s.row}>
            {secondary ? (
              <View style={s.two}>
                <Button {...secondary} full />
              </View>
            ) : null}
            {primary ? (
              <View style={s.three}>
                <Button {...primary} full />
              </View>
            ) : null}
          </View>
        )
      ) : null}
      {children}
    </View>
  );
}

const useStyles = makeStyles((t) => ({
  bar: {
    backgroundColor: t.color.surfaceRaised,
    borderTopWidth: 1,
    borderTopColor: t.color.border,
    paddingTop: t.space[12],
    paddingHorizontal: t.layout.gutter,
    gap: t.space[12],
  },
  row: { flexDirection: 'row', gap: t.space[12] },
  two: { flex: 2 },
  three: { flex: 3 },
  stack: { gap: t.space[8] },
  line: { paddingVertical: t.space[4] },
}));
