// The cryptography, as quiet assurance.
//
// This component is the whole argument of the redesign in one place.
//
// The old decision screen gave a panel titled "Payload" equal billing with the decision itself,
// and filled it with six rows: a verification state, a payload hash, a nonce, a file digest, a
// creation timestamp and a signer count. An executive has no nonce-shaped question. Showing it to
// them does not make the system more trustworthy -- it makes the screen harder to read, which
// makes the decision harder to take, which is the opposite of what the security is for.
//
// But deleting it would be worse. The on-device payload check is the project's actual thesis: the
// handset recomputes the hash from the server's own stated inputs and refuses to sign if they
// disagree, so a compromised server cannot show one action and collect consent for another. That
// has to be visible, or the guarantee is indistinguishable from a claim.
//
// The resolution is that assurance is quiet when it holds and loud when it does not:
//
//   HOLDS   -- one line. A mark, four words, and a way in. The detail is one tap away for the
//              person who wants it, and absent for the person who does not.
//   FAILS   -- the whole thing opens, turns `broken`, cannot be collapsed, and the screen that
//              contains it withdraws the signing controls.
//
// The check itself is unchanged: `verifyProposalIntegrity` runs on every render of a loaded
// decision exactly as before. Only its presentation is different.

import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import Animated, {
  FadeIn,
  FadeOut,
  LinearTransition,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withTiming,
} from 'react-native-reanimated';

import { color, motion, radius, space, tone, type } from '../theme.ts';

// Reanimated layout animations rather than RN's `LayoutAnimation`. This app runs on the New
// Architecture (`newArchEnabled=true`, RN 0.86), where `LayoutAnimation` is not supported and
// `UIManager.setLayoutAnimationEnabledExperimental` does not exist -- so the first version of this
// component would have degraded to an unannounced jump at best. Reanimated drives layout off the
// UI thread and works identically on Fabric.

export function Assurance({
  ok,
  children,
  failureTitle = 'This decision does not match its own signature payload.',
  failureDetail = 'Nothing has been signed. Report this before acting on it.',
}: {
  ok: boolean;
  /** The detail rows. Rendered only when expanded, or always when the check has failed. */
  children: React.ReactNode;
  failureTitle?: string;
  failureDetail?: string;
}) {
  const reduced = useReducedMotion();
  const [open, setOpen] = useState(false);
  const spin = useSharedValue(0);

  // A failed check is never collapsible. Letting someone tidy away an integrity failure would make
  // the loudest state in the product dismissible by accident.
  const expanded = !ok || open;

  const chevronStyle = useAnimatedStyle(() => ({
    transform: [{ rotate: `${spin.value * 90}deg` }],
  }));

  function toggle() {
    if (!ok) return;
    const next = !open;
    setOpen(next);
    spin.value = withTiming(next ? 1 : 0, { duration: motion.quick });
  }

  const palette = ok ? tone.sealed : tone.broken;

  return (
    <Animated.View
      layout={reduced ? undefined : LinearTransition.duration(motion.settle)}
      style={[
        s.wrap,
        { borderColor: ok ? color.rule : palette.border, backgroundColor: ok ? color.surface : palette.bg },
      ]}
    >
      <Pressable
        onPress={toggle}
        disabled={!ok}
        accessibilityRole={ok ? 'button' : 'summary'}
        accessibilityState={{ expanded }}
        accessibilityLabel={
          ok ? 'Verified on this device. Show the signing detail.' : failureTitle
        }
        style={({ pressed }) => [s.head, pressed && ok && { opacity: 0.6 }]}
      >
        <View style={[s.mark, { borderColor: palette.fg }]}>
          <Text style={[s.markGlyph, { color: palette.fg }]}>{ok ? '✓' : '!'}</Text>
        </View>

        <View style={{ flex: 1 }}>
          <Text style={[s.title, { color: ok ? color.ink : palette.fg }]}>
            {ok ? 'Verified on this device' : failureTitle}
          </Text>
          {!ok ? <Text style={[s.detail, { color: palette.fg }]}>{failureDetail}</Text> : null}
        </View>

        {ok ? (
          <Animated.Text style={[s.chevron, chevronStyle]}>›</Animated.Text>
        ) : null}
      </Pressable>

      {expanded ? (
        <Animated.View
          entering={reduced ? undefined : FadeIn.duration(motion.quick)}
          exiting={reduced ? undefined : FadeOut.duration(motion.instant)}
          style={s.body}
        >
          {children}
        </Animated.View>
      ) : null}
    </Animated.View>
  );
}

const s = StyleSheet.create({
  wrap: {
    borderWidth: 1,
    borderRadius: radius.card,
    overflow: 'hidden',
  },
  head: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    padding: space.md,
  },
  mark: {
    width: 20,
    height: 20,
    borderRadius: 10,
    borderWidth: 1.5,
    alignItems: 'center',
    justifyContent: 'center',
  },
  markGlyph: { fontSize: 12, lineHeight: 15, fontWeight: '700' },
  title: { ...type.body, fontSize: 14.5 },
  detail: { ...type.meta, marginTop: 2 },
  chevron: { fontSize: 22, lineHeight: 24, color: color.ink4, width: 14, textAlign: 'center' },
  body: {
    paddingHorizontal: space.md,
    paddingBottom: space.md,
    paddingTop: space.xs,
    gap: space.xs,
    borderTopWidth: 1,
    borderTopColor: color.rule2,
  },
});
