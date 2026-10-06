// The quorum, drawn as marks rather than a bar (phone-ux §5.5).
//
// An m-of-n vault is a document that is not valid until enough people have sealed it, so the marks
// are discrete and countable. Filled and empty differ in SHAPE as well as colour (a disc against a
// 1.5pt ring in the strong border colour, 3:1 or better), and the marks are always followed by
// "1 of 2", so 2 of 3 and 2 of 5 no longer look alike. Rejections are a caption, never marks.
//
// The closing animation plays only when this person's own signature completed the quorum: a
// decision that was already complete when they opened it did not happen in front of them.

import { useEffect } from 'react';
import { View } from 'react-native';
import Animated, {
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withDelay,
  withSequence,
  withSpring,
  withTiming,
} from 'react-native-reanimated';

import { makeStyles, useTheme } from '../theme/index.ts';
import { Text } from './Text.tsx';

/** Above this many marks the row stops being countable at a glance; the words carry it alone. */
const MAX_MARKS = 8;

export type SealSize = 10 | 14 | 20;

export function Seal({
  filled,
  required,
  size = 14,
  celebrate = false,
  showCount = true,
  rejections = 0,
}: {
  filled: number;
  required: number;
  size?: SealSize;
  /** Play the closing once, now: only where this person has just completed the quorum. */
  celebrate?: boolean;
  /** "1 of 2" after the marks. */
  showCount?: boolean;
  /** Shown as a caption, "1 rejection", never as marks. */
  rejections?: number;
}) {
  const s = useStyles();
  const complete = required > 0 && filled >= required;
  const label = `${filled} of ${required} ${required === 1 ? 'approval' : 'approvals'}${
    rejections > 0 ? `, ${rejections} ${rejections === 1 ? 'rejection' : 'rejections'}` : ''
  }`;
  return (
    <View style={s.row} accessible accessibilityRole="text" accessibilityLabel={label}>
      {required <= MAX_MARKS ? (
        <View style={[s.marks, { gap: Math.max(4, Math.round(size * 0.45)) }]}>
          {Array.from({ length: required }, (_, i) => (
            <Mark
              key={i}
              on={i < filled}
              size={size}
              closes={celebrate && complete && i === required - 1}
            />
          ))}
        </View>
      ) : null}
      {showCount || required > MAX_MARKS ? (
        <Text role="caption" tone="muted" tabular>
          {`${filled} of ${required}`}
        </Text>
      ) : null}
      {rejections > 0 ? (
        <Text role="caption" tone="critical" tabular>
          {rejections === 1 ? '1 rejection' : `${rejections} rejections`}
        </Text>
      ) : null}
    </View>
  );
}

function Mark({ on, size, closes }: { on: boolean; size: number; closes: boolean }) {
  const t = useTheme();
  const reduced = useReducedMotion();
  const scale = useSharedValue(1);
  const ring = useSharedValue(0);

  useEffect(() => {
    if (!closes || reduced) return;
    // Pressed inward before it settles: a seal is pushed onto the page, not bloomed.
    scale.value = withSequence(withTiming(0.82, { duration: t.motion.press }), withSpring(1, t.motion.emphatic));
    ring.value = withDelay(t.motion.press, withTiming(1, { duration: t.motion.seal }));
  }, [closes, reduced, scale, ring, t.motion]);

  const markStyle = useAnimatedStyle(() => ({ transform: [{ scale: scale.value }] }));
  const ringStyle = useAnimatedStyle(() => ({
    opacity: (1 - ring.value) * 0.9,
    transform: [{ scale: 1 + ring.value * 2.6 }],
  }));

  const round = { width: size, height: size, borderRadius: size / 2 };
  return (
    <View style={round}>
      {closes ? (
        <Animated.View
          pointerEvents="none"
          style={[round, { position: 'absolute', borderWidth: 1.5, borderColor: t.color.markFilled }, ringStyle]}
        />
      ) : null}
      <Animated.View
        style={[
          round,
          on
            ? { backgroundColor: t.color.markFilled }
            : { borderWidth: 1.5, borderColor: t.color.markEmpty },
          markStyle,
        ]}
      />
    </View>
  );
}

const useStyles = makeStyles((t) => ({
  row: { flexDirection: 'row', alignItems: 'center', gap: t.space[8], flexWrap: 'wrap' },
  marks: { flexDirection: 'row', alignItems: 'center' },
}));
