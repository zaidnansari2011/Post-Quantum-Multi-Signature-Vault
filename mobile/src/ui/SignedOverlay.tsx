// The moment the signature lands: the one orchestrated animation in the product (phone-ux §6.11).
//
//   1. The ground dims.                                   the page is still there, underneath
//   2. The disc springs in and a ring expands off it.     something has been pressed onto the page
//   3. The tick draws, short arm then long arm.           it is being written, not switched on
//   4. The haptic fires as the tick completes.            the physical world agrees
//   5. The words fade up.                                 read after the event, not during it
//
// Rejection gets the same ceremony in the critical tone, with a cross: rejecting is as deliberate
// and as irreversible, and celebrating only approval would lean on a decision the product has no
// business influencing. Reduced motion jumps to the end state, and the haptic still fires.
//
// The tick and cross are two bars each, scaled rather than resized (a scale is composited off the
// JS thread; animating width re-runs layout every frame), so no SVG module is needed.

import { useEffect } from 'react';
import { Modal, View } from 'react-native';
import Animated, {
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withDelay,
  withSpring,
  withTiming,
} from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { makeStyles, useTheme } from '../theme/index.ts';
import { Button } from './Button.tsx';
import { feedback } from './feedback.ts';
import { Seal } from './Seal.tsx';
import { Text } from './Text.tsx';
import { Touchable } from './Touchable.tsx';

const DISC = 72;
const STROKE = 4;
// A tick is an ASYMMETRIC V: a short arm into the corner, a long one sweeping out of it.
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
  /** False for a rejection: the hue, the glyph and the words change, not the ceremony. */
  approved: boolean;
  filled: number;
  required: number;
  onDone: () => void;
}) {
  const t = useTheme();
  const s = useStyles();
  const reduced = useReducedMotion();
  const insets = useSafeAreaInsets();

  const dim = useSharedValue(0);
  const disc = useSharedValue(0);
  const ring = useSharedValue(0);
  const armA = useSharedValue(0);
  const armB = useSharedValue(0);
  const words = useSharedValue(0);

  const complete = approved && filled >= required;
  const tone = approved ? t.color.status.success : t.color.status.critical;

  useEffect(() => {
    if (!visible) {
      [dim, disc, ring, armA, armB, words].forEach((v) => (v.value = 0));
      return;
    }
    if (reduced) {
      [dim, disc, armA, armB, words].forEach((v) => (v.value = 1));
      complete ? feedback.sealed() : feedback.signed();
      return;
    }
    dim.value = withTiming(1, { duration: t.motion.popover });
    disc.value = withDelay(60, withSpring(1, t.motion.emphatic));
    ring.value = withDelay(120, withTiming(1, { duration: t.motion.seal }));
    armA.value = withDelay(260, withTiming(1, { duration: 130 }));
    armB.value = withDelay(390, withTiming(1, { duration: 190 }));
    words.value = withDelay(560, withTiming(1, { duration: t.motion.dialog }));
    // Timed to the tick finishing, so what the hand feels and what the eye sees are one event.
    const at = setTimeout(() => (complete ? feedback.sealed() : feedback.signed()), 580);
    return () => clearTimeout(at);
  }, [visible, reduced, complete, dim, disc, ring, armA, armB, words, t.motion]);

  const dimStyle = useAnimatedStyle(() => ({ opacity: dim.value }));
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
  const armAStyle = useAnimatedStyle(() => ({ transform: [{ scaleX: armA.value }] }));
  const armBStyle = useAnimatedStyle(() => ({ transform: [{ scaleY: armB.value }] }));
  const crossAStyle = useAnimatedStyle(() => ({ transform: [{ rotate: '45deg' }, { scaleX: armA.value }] }));
  const crossBStyle = useAnimatedStyle(() => ({ transform: [{ rotate: '-45deg' }, { scaleX: armB.value }] }));

  const head = headline(approved, complete);
  const body = detail(approved, complete, filled, required);
  // The glyph is drawn in the tone's own tint: white on the light-green disc of the dark theme
  // would be about 1.6:1.
  const glyph = { backgroundColor: tone.bg };

  return (
    <Modal visible={visible} transparent animationType="none" onRequestClose={onDone} statusBarTranslucent hardwareAccelerated>
      <View style={s.root}>
        <Animated.View style={[s.dim, dimStyle]} pointerEvents="none" />
        <Touchable style={s.dismissArea} accessibilityRole="button" accessibilityLabel="Dismiss" onPress={onDone} />
        <Animated.View
          style={[s.card, t.elevation.sheet, { paddingBottom: t.space[16] + insets.bottom }, cardStyle]}
          accessibilityViewIsModal
          accessibilityLiveRegion="assertive"
          accessibilityLabel={`${head}. ${body}`}
        >
          <View style={s.discWrap}>
            <Animated.View pointerEvents="none" style={[s.ring, { borderColor: tone.fg }, ringStyle]} />
            <Animated.View style={[s.disc, { backgroundColor: tone.fg }, discStyle]}>
              {approved ? (
                <View style={s.tickBox}>
                  <Animated.View style={[s.armShort, glyph, armAStyle]} />
                  <Animated.View style={[s.armLong, glyph, armBStyle]} />
                </View>
              ) : (
                <View style={s.crossBox}>
                  <Animated.View style={[s.crossBar, glyph, crossAStyle]} />
                  <Animated.View style={[s.crossBar, glyph, crossBStyle]} />
                </View>
              )}
            </Animated.View>
          </View>

          <Animated.View style={[s.words, wordsStyle]}>
            <Text role="title" align="center" accessibilityRole="header">
              {head}
            </Text>
            <Text role="body" tone="muted" align="center" style={s.detail}>
              {body}
            </Text>
            {approved ? (
              <View style={s.sealRow}>
                <Seal filled={filled} required={required} size={20} />
              </View>
            ) : null}
          </Animated.View>

          <Button label="Done" onPress={onDone} variant="secondary" full />
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

const useStyles = makeStyles((t) => ({
  root: { flex: 1, justifyContent: 'flex-end' },
  dim: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: t.color.backdrop },
  dismissArea: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 },
  card: {
    width: '100%',
    maxWidth: t.layout.maxContent,
    alignSelf: 'center',
    backgroundColor: t.color.surfaceRaised,
    borderTopLeftRadius: t.radius.sheet,
    borderTopRightRadius: t.radius.sheet,
    borderTopWidth: t.scheme === 'dark' ? 1 : 0,
    borderColor: t.color.border,
    paddingHorizontal: t.layout.gutter,
    paddingTop: t.space[24],
    alignItems: 'center',
    gap: t.space[16],
  },
  discWrap: { width: DISC, height: DISC, alignItems: 'center', justifyContent: 'center' },
  ring: { position: 'absolute', width: DISC, height: DISC, borderRadius: DISC / 2, borderWidth: 2 },
  disc: { width: DISC, height: DISC, borderRadius: DISC / 2, alignItems: 'center', justifyContent: 'center' },
  // An L sharing its bottom-right corner, turned 45 degrees: short arm up-left, long arm up-right.
  tickBox: { width: TICK_SHORT, height: TICK_LONG, transform: [{ rotate: '45deg' }], marginLeft: -3 },
  armShort: {
    position: 'absolute',
    right: 0,
    bottom: 0,
    width: TICK_SHORT,
    height: STROKE,
    borderRadius: STROKE / 2,
    transformOrigin: 'right center',
  },
  armLong: {
    position: 'absolute',
    right: 0,
    bottom: 0,
    width: STROKE,
    height: TICK_LONG,
    borderRadius: STROKE / 2,
    transformOrigin: 'center bottom',
  },
  crossBox: { width: 30, height: 30, alignItems: 'center', justifyContent: 'center' },
  crossBar: { position: 'absolute', width: 28, height: STROKE, borderRadius: STROKE / 2 },
  words: { alignItems: 'center', gap: t.space[4], alignSelf: 'stretch' },
  detail: { maxWidth: 320 },
  sealRow: { marginTop: t.space[8] },
}));
