// The quorum, drawn as marks rather than written as a fraction.
//
// An m-of-n vault is a document that is not valid until enough people have sealed it. That is the
// literal mechanism, and it is worth showing literally: `2/3 approved` is a number someone has to
// read and convert, while three marks with two of them filled is a state someone takes in without
// reading anything. It also gives the product one honest place to spend motion -- when a signature
// completes the quorum, the last mark closes, and that is the moment the decision became
// irreversible.
//
// Deliberately NOT a progress bar. A bar implies a continuous quantity filling up, and a quorum is
// none of those things: it is a small number of discrete, individually-attributable consents. The
// marks are countable for the same reason the underlying policy is.

import { useEffect } from 'react';
import { StyleSheet, View } from 'react-native';
import Animated, {
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withDelay,
  withSequence,
  withSpring,
  withTiming,
} from 'react-native-reanimated';

import { color, motion, space } from '../theme.ts';

/** Above this many marks the row stops being countable at a glance and we show a figure instead. */
const MAX_MARKS = 8;

export type SealProps = {
  /** Signatures gathered so far. */
  filled: number;
  /** Signatures the policy requires -- the `m` of m-of-n. */
  required: number;
  /**
   * Play the closing animation once, now. Set this only on the screen where the person has just
   * signed: a decision that was already complete when they opened it did not happen in front of
   * them, and animating it would claim it did.
   */
  celebrate?: boolean;
  size?: number;
};

export function Seal({ filled, required, celebrate = false, size = 11 }: SealProps) {
  const complete = filled >= required && required > 0;

  if (required > MAX_MARKS) {
    return <SealFigure filled={filled} required={required} complete={complete} />;
  }

  return (
    <View style={[s.row, { gap: Math.max(5, size * 0.55) }]} accessibilityRole="progressbar"
      accessibilityLabel={`${filled} of ${required} signatures gathered`}>
      {Array.from({ length: required }, (_, i) => (
        <Mark
          key={i}
          index={i}
          on={i < filled}
          size={size}
          // Only the mark that completes the quorum gets the closing animation, and only when this
          // person is the one who completed it.
          closes={celebrate && complete && i === required - 1}
        />
      ))}
    </View>
  );
}

function Mark({
  index,
  on,
  size,
  closes,
}: {
  index: number;
  on: boolean;
  size: number;
  closes: boolean;
}) {
  const reduced = useReducedMotion();
  const scale = useSharedValue(1);
  const ring = useSharedValue(0);

  useEffect(() => {
    if (!closes || reduced) return;
    // A press inward before the expansion outward. A seal is pushed down onto the page; going
    // straight to a bloom would read as a notification badge rather than as something set.
    scale.value = withSequence(
      withTiming(0.82, { duration: motion.instant }),
      withSpring(1, motion.emphatic),
    );
    ring.value = withDelay(motion.instant, withTiming(1, { duration: motion.seal }));
  }, [closes, reduced, scale, ring]);

  const markStyle = useAnimatedStyle(() => ({ transform: [{ scale: scale.value }] }));

  // The ring is a single expanding outline that fades as it grows -- the visual of something
  // pressed into paper displacing outward. It is drawn outside the mark and never moves layout.
  const ringStyle = useAnimatedStyle(() => ({
    opacity: (1 - ring.value) * 0.9,
    transform: [{ scale: 1 + ring.value * 2.6 }],
  }));

  return (
    <View style={{ width: size, height: size }}>
      {closes ? (
        <Animated.View
          pointerEvents="none"
          style={[
            s.ring,
            { width: size, height: size, borderRadius: size / 2, borderColor: color.sealed },
            ringStyle,
          ]}
        />
      ) : null}
      <Animated.View
        style={[
          {
            width: size,
            height: size,
            borderRadius: size / 2,
            borderWidth: on ? 0 : 1.5,
            borderColor: color.rule,
            backgroundColor: on ? color.sealed : 'transparent',
          },
          markStyle,
        ]}
      />
    </View>
  );
}

/**
 * The fallback for an unusually large quorum. Still not a bar: a bar would invite reading the
 * remaining distance as an amount, when what matters is how many named people are still to sign.
 */
function SealFigure({
  filled,
  required,
  complete,
}: {
  filled: number;
  required: number;
  complete: boolean;
}) {
  return (
    <View style={[s.row, { gap: space.xs }]}>
      <View
        style={[
          s.figureDot,
          { backgroundColor: complete ? color.sealed : color.waiting },
        ]}
      />
      <Animated.Text style={s.figureText}>
        {filled} of {required} signed
      </Animated.Text>
    </View>
  );
}

const s = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center' },
  ring: { position: 'absolute', borderWidth: 1.5 },
  figureDot: { width: 8, height: 8, borderRadius: 4 },
  figureText: { fontSize: 13, color: color.ink2 },
});
