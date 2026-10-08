// The on-device check, as quiet assurance (phone-ux §1.3, §6.5 item 9).
//
// The handset recomputes the payload hash from the server's own stated inputs and refuses to sign
// if they disagree, so a compromised server cannot show one action and collect consent for another.
// That has to be visible, but an approver has no nonce-shaped question. So assurance is quiet when
// it holds and loud when it does not:
//
//   HOLDS   one row: a success mark, the words, and a way in to the detail.
//   FAILS   the whole thing opens in the critical tone, cannot be collapsed, and the screen around
//           it withdraws the signing controls.
//
// `verifyProposalIntegrity` runs on every render of a loaded decision; only its presentation is here.
// (P2 replaces the drawer with the "Checked on this phone" evidence sheet, §6.7.)

import { useState, type ReactNode } from 'react';
import { View } from 'react-native';
import Animated, { FadeIn, FadeOut, useReducedMotion } from 'react-native-reanimated';

import { makeStyles, useTheme } from '../theme/index.ts';
import { Icon } from './Icon.tsx';
import { Text } from './Text.tsx';
import { Touchable } from './Touchable.tsx';

export function Assurance({
  ok,
  children,
  failureTitle = 'This decision does not match its own signature payload.',
  failureDetail = 'Nothing has been signed. Report this before acting on it.',
}: {
  ok: boolean;
  /** The detail rows: shown when opened, and always when the check has failed. */
  children: ReactNode;
  failureTitle?: string;
  failureDetail?: string;
}) {
  const t = useTheme();
  const s = useStyles();
  const reduced = useReducedMotion();
  const [open, setOpen] = useState(false);
  // A failed check is never collapsible: tidying it away by accident must not be possible.
  const expanded = !ok || open;
  const palette = t.color.status.critical;

  return (
    <View style={[s.wrap, ok ? s.wrapOk : { backgroundColor: palette.bg, borderColor: palette.border }]}>
      {ok ? (
        <Touchable
          onPress={() => setOpen((v) => !v)}
          accessibilityRole="button"
          accessibilityState={{ expanded }}
          accessibilityLabel="Verified on this device. Show the signing detail."
          ringRadius={t.radius.card}
          style={({ pressed }) => [s.head, pressed && s.pressed]}
        >
          <Icon name="check-circle" size={20} color={t.color.status.success.fg} />
          <Text role="body" style={s.flex}>
            Verified on this device
          </Text>
          <Icon name={open ? 'chevron-down' : 'chevron-right'} size={16} color={t.color.textMuted} />
        </Touchable>
      ) : (
        <View style={s.head} accessibilityRole="alert" accessible accessibilityLabel={`${failureTitle} ${failureDetail}`}>
          <Icon name="alert" size={20} color={palette.fg} style={s.alertIcon} />
          <View style={s.flex}>
            <Text role="bodyStrong" color={palette.fg}>
              {failureTitle}
            </Text>
            <Text role="body">{failureDetail}</Text>
          </View>
        </View>
      )}
      {expanded ? (
        <Animated.View
          entering={reduced ? undefined : FadeIn.duration(t.motion.popover)}
          exiting={reduced ? undefined : FadeOut.duration(t.motion.press)}
          style={[s.body, !ok && { borderTopColor: palette.border }]}
        >
          {children}
        </Animated.View>
      ) : null}
    </View>
  );
}

const useStyles = makeStyles((t) => ({
  flex: { flex: 1 },
  wrap: { borderWidth: 1, borderRadius: t.radius.card, overflow: 'hidden' },
  wrapOk: { backgroundColor: t.color.surface, borderColor: t.color.border },
  head: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: t.space[12],
    minHeight: 56,
    paddingHorizontal: t.layout.gutter,
    paddingVertical: t.space[12],
  },
  alertIcon: { alignSelf: 'flex-start', marginTop: 2 },
  pressed: { backgroundColor: t.color.fill },
  body: {
    paddingHorizontal: t.layout.gutter,
    paddingTop: t.space[8],
    paddingBottom: t.space[12],
    gap: t.space[4],
    borderTopWidth: 1,
    borderTopColor: t.color.border,
  },
}));
