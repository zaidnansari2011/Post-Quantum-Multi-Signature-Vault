// The moment the signature lands.
//
// This is the single orchestrated animation in the product, and it earns that status: it marks the
// only irreversible thing a person can do here. Everything else in the app either answers a tap or
// stays still.
//
// The first version of this screen reported a successful signature with an inline banner and a
// quorum mark quietly filling in. That was wrong, and the author said so: after a biometric prompt
// the person has physically committed something, and the interface answering with a line of text
// makes the act feel unacknowledged. A signature is not a form submission.
//
// The sequence, ~1.2s end to end:
//
//   1. The ground dims.                                   the page is still there, underneath
//   2. The disc springs in and a ring expands off it.     something has been pressed onto the page
//   3. The tick draws, short arm then long arm.           it is being written, not switched on
//   4. Haptic fires as the tick completes.                the physical world agrees
//   5. The words fade up.                                 read after the event, not during it
//
// The tick is drawn from two bars rather than an SVG path: `react-native-svg` is a native module,
// and adding one would mean this change could not ship over the air. Two bars anchored at a shared
// corner inside a 45-degree rotation give the same read for no native surface at all.
//
// REJECTION GETS THE SAME CEREMONY, in `broken` rather than `sealed`, with a cross instead of a
// tick. Rejecting is equally irreversible and equally deliberate, and celebrating only approval
// would put a thumb on the scale of a decision the product has no business influencing.

import { useEffect } from 'react';
import { Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import Animated, {
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withDelay,
  withSequence,
  withSpring,
  withTiming,
} from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Seal } from './Seal.tsx';
import { feedback } from './feedback.ts';
import { color, motion, radius, space, type } from '../theme.ts';

const DISC = 72;
const STROKE = 4;
// A tick is an ASYMMETRIC V: a short arm down into the corner, a long one sweeping up out of it.
// Equal arms give a chevron, which is what the first version drew.
const TICK_SHORT = 13;
const TICK_LONG = 27;

export function SignedOverlay({
  visible,
  approved,
  filled,
  required,
  onDone,
}: {
  visible: boolean;
  /** False for a rejection. Changes the hue, the glyph and the words -- not the ceremony. */
  approved: boolean;
  filled: number;
  required: number;
  onDone: () => void;
}) {
  const reduced = useReducedMotion();

  const dim = useSharedValue(0);
  const disc = useSharedValue(0);
  const ring = useSharedValue(0);
  const armA = useSharedValue(0);
  const armB = useSharedValue(0);
  const words = useSharedValue(0);

  const complete = approved && filled >= required;
  const hue = approved ? color.sealed : color.broken;

  useEffect(() => {
    if (!visible) {
      [dim, disc, ring, armA, armB, words].forEach((v) => (v.value = 0));
      return;
    }

    if (reduced) {
      // Reduced motion gets the destination, not a faster journey. The haptic still fires: it is
      // confirmation, not decoration, and someone who suppresses animation has not asked to be
      // told less.
      [dim, disc, armA, armB, words].forEach((v) => (v.value = 1));
      complete ? feedback.sealed() : feedback.signed();
      return;
    }

    dim.value = withTiming(1, { duration: motion.quick });
    disc.value = withDelay(60, withSpring(1, motion.emphatic));
    ring.value = withDelay(120, withTiming(1, { duration: motion.seal }));
    armA.value = withDelay(260, withTiming(1, { duration: 130 }));
    armB.value = withDelay(390, withTiming(1, { duration: 190 }));
    words.value = withDelay(560, withTiming(1, { duration: motion.settle }));

    // Timed to the tick finishing rather than to the request returning. The signature was accepted
    // a moment ago; this is the instant the person is told, and the two should agree.
    const at = setTimeout(() => (complete ? feedback.sealed() : feedback.signed()), 580);
    return () => clearTimeout(at);
  }, [visible, reduced, complete, dim, disc, ring, armA, armB, words]);

  const dimStyle = useAnimatedStyle(() => ({ opacity: dim.value * 0.5 }));
  const cardStyle = useAnimatedStyle(() => ({
    opacity: dim.value,
    transform: [{ translateY: (1 - dim.value) * 24 }],
  }));
  const discStyle = useAnimatedStyle(() => ({ transform: [{ scale: disc.value }] }));
  const ringStyle = useAnimatedStyle(() => ({
    opacity: (1 - ring.value) * 0.85,
    transform: [{ scale: 1 + ring.value * 1.5 }],
  }));
  const wordsStyle = useAnimatedStyle(() => ({
    opacity: words.value,
    transform: [{ translateY: (1 - words.value) * 8 }],
  }));

  // SCALE, NEVER WIDTH OR HEIGHT. The first version animated the arms' extents, which makes React
  // Native re-run layout on every frame of a 300ms draw -- that was the jank. A scale is composited
  // on the UI thread and touches no layout at all. `transformOrigin` pins each arm to the corner
  // the two share, so scaling grows it along its own length instead of out from its middle.
  const armAStyle = useAnimatedStyle(() => ({ transform: [{ scaleX: armA.value }] }));
  const armBStyle = useAnimatedStyle(() => ({ transform: [{ scaleY: armB.value }] }));

  const crossAStyle = useAnimatedStyle(() => ({
    transform: [{ rotate: '45deg' }, { scaleX: armA.value }],
  }));
  const crossBStyle = useAnimatedStyle(() => ({
    transform: [{ rotate: '-45deg' }, { scaleX: armB.value }],
  }));

  const insets = useSafeAreaInsets();

  return (
    // hardwareAccelerated: an Android modal window is composited in software unless asked
    // otherwise, so every frame of the draw goes through the CPU. It costs nothing to ask.
    <Modal
      visible={visible}
      transparent
      animationType="none"
      onRequestClose={onDone}
      statusBarTranslucent
      hardwareAccelerated
    >
      <View style={s.root}>
        <Animated.View style={[s.dim, dimStyle]} />
        <Pressable style={s.dismissArea} accessibilityRole="button" accessibilityLabel="Dismiss" onPress={onDone} />

        <Animated.View
          style={[s.card, { marginBottom: insets.bottom }, cardStyle]}
          accessibilityLiveRegion="assertive"
          accessibilityLabel={`${headline(approved, complete)}. ${detail(approved, complete, filled, required)}`}
        >
          <View style={s.discWrap}>
            <Animated.View
              pointerEvents="none"
              style={[s.ring, { borderColor: hue }, ringStyle]}
            />
            <Animated.View style={[s.disc, { backgroundColor: hue }, discStyle]}>
              {approved ? (
                <View style={s.tickBox}>
                  <Animated.View style={[s.armShort, armAStyle]} />
                  <Animated.View style={[s.armLong, armBStyle]} />
                </View>
              ) : (
                <View style={s.crossBox}>
                  <Animated.View style={[s.crossBar, crossAStyle]} />
                  <Animated.View style={[s.crossBar, crossBStyle]} />
                </View>
              )}
            </Animated.View>
          </View>

          <Animated.View style={[s.words, wordsStyle]}>
            <Text style={s.headline}>{headline(approved, complete)}</Text>
            <Text style={s.detail}>{detail(approved, complete, filled, required)}</Text>

            {approved ? (
              <View style={s.sealRow}>
                <Seal filled={filled} required={required} size={12} />
              </View>
            ) : null}
          </Animated.View>

          <Pressable
            onPress={onDone}
            accessibilityRole="button"
            style={({ pressed }) => [s.done, pressed && { opacity: 0.6 }]}
          >
            <Text style={s.doneText}>Done</Text>
          </Pressable>
        </Animated.View>
      </View>
    </Modal>
  );
}

function headline(approved: boolean, complete: boolean): string {
  if (!approved) return 'Decision rejected';
  return complete ? 'Decision approved' : 'Approval signed';
}

function detail(approved: boolean, complete: boolean, filled: number, required: number): string {
  if (!approved) return 'Your rejection is recorded against this decision.';
  if (complete) return 'Yours was the signature that met the threshold.';
  const left = required - filled;
  return left === 1
    ? 'One more signature is needed before this is approved.'
    : `${left} more signatures are needed before this is approved.`;
}

const s = StyleSheet.create({
  root: { flex: 1, justifyContent: 'flex-end' },
  dim: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: '#0E1729' },
  dismissArea: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 },

  card: {
    backgroundColor: color.surface,
    borderTopLeftRadius: radius.sheet,
    borderTopRightRadius: radius.sheet,
    paddingHorizontal: space.xl,
    paddingTop: space.xl,
    paddingBottom: space.lg,
    alignItems: 'center',
    gap: space.lg,
  },

  discWrap: { width: DISC, height: DISC, alignItems: 'center', justifyContent: 'center' },
  ring: {
    position: 'absolute',
    width: DISC,
    height: DISC,
    borderRadius: DISC / 2,
    borderWidth: 2,
  },
  disc: {
    width: DISC,
    height: DISC,
    borderRadius: DISC / 2,
    alignItems: 'center',
    justifyContent: 'center',
  },

  // An L sharing a BOTTOM-RIGHT corner, turned 45 degrees clockwise. That lands the short arm
  // pointing up-left and the long arm sweeping up-right, which is a tick. The first version put
  // the corner bottom-left and turned it the other way, which mirrors the glyph: short arm to the
  // right, long arm to the left, and the whole thing reads as a chevron.
  tickBox: {
    width: TICK_SHORT,
    height: TICK_LONG,
    transform: [{ rotate: '45deg' }],
    marginLeft: -3,
  },
  armShort: {
    position: 'absolute',
    right: 0,
    bottom: 0,
    width: TICK_SHORT,
    height: STROKE,
    borderRadius: STROKE / 2,
    backgroundColor: '#FFFFFF',
    transformOrigin: 'right center',
  },
  armLong: {
    position: 'absolute',
    right: 0,
    bottom: 0,
    width: STROKE,
    height: TICK_LONG,
    borderRadius: STROKE / 2,
    backgroundColor: '#FFFFFF',
    transformOrigin: 'center bottom',
  },

  crossBox: { width: 30, height: 30, alignItems: 'center', justifyContent: 'center' },
  crossBar: {
    position: 'absolute',
    width: 28,
    height: STROKE,
    borderRadius: STROKE / 2,
    backgroundColor: '#FFFFFF',
  },

  words: { alignItems: 'center', gap: space.xs },
  headline: { ...type.title, fontSize: 21, textAlign: 'center' },
  detail: { ...type.bodyMuted, textAlign: 'center', maxWidth: 300 },
  sealRow: { marginTop: space.md },

  done: {
    alignSelf: 'stretch',
    minHeight: 50,
    borderRadius: radius.control,
    borderWidth: 1,
    borderColor: color.rule,
    alignItems: 'center',
    justifyContent: 'center',
  },
  doneText: { ...type.action },
});
