// The confirm sheet.
//
// The old app approved on a single tap: press Approve, satisfy the biometric prompt, done. That is
// the correct number of taps for liking a post and the wrong number for committing an organisation
// to something irreversible. The missing step is not friction for its own sake -- it is the
// restatement. Before the signature, the person is shown the decision again, in the words it will
// be recorded in, and asked to confirm that specific sentence rather than to confirm "the thing I
// was just looking at".
//
// The biometric prompt cannot do this job. It says "Q-Vault wants to authenticate you", which
// authorises a *person*, not a *statement*. Everything about what is being agreed to has to be on
// screen before that prompt appears.
//
// Motion: the sheet rises on a spring with no overshoot, and the page behind it dims and settles
// back a little. That backward step is doing real work -- it says the page is still there and this
// is a layer over it, which is what makes the cancel affordance obvious without labelling it.

import { type ReactNode, useEffect } from 'react';
import { BackHandler, Modal, Pressable, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import Animated, {
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withTiming,
  withSpring,
} from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { color, elevation, motion, radius, space, type } from '../theme.ts';

export function Sheet({
  visible,
  onClose,
  title,
  children,
  dismissible = true,
}: {
  visible: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
  /** False while a signature is in flight: closing midway would leave the outcome ambiguous. */
  dismissible?: boolean;
}) {
  const reduced = useReducedMotion();
  const insets = useSafeAreaInsets();
  const { height } = useWindowDimensions();

  const progress = useSharedValue(0);

  useEffect(() => {
    if (reduced) {
      progress.value = visible ? 1 : 0;
      return;
    }
    progress.value = visible
      ? withSpring(1, motion.surface)
      : withTiming(0, { duration: motion.quick });
  }, [visible, reduced, progress]);

  useEffect(() => {
    if (!visible) return;
    const sub = BackHandler.addEventListener('hardwareBackPress', () => {
      if (dismissible) onClose();
      return true;
    });
    return () => sub.remove();
  }, [visible, dismissible, onClose]);

  const backdropStyle = useAnimatedStyle(() => ({ opacity: progress.value * 0.45 }));

  const panelStyle = useAnimatedStyle(() => ({
    transform: [{ translateY: (1 - progress.value) * height * 0.5 }],
  }));

  return (
    <Modal visible={visible} transparent animationType="none" onRequestClose={onClose} statusBarTranslucent>
      <View style={s.root}>
        <Animated.View style={[s.backdrop, backdropStyle]} />
        <Pressable
          style={s.backdropTarget}
          accessibilityLabel="Dismiss"
          accessibilityRole="button"
          onPress={() => dismissible && onClose()}
        />
        <Animated.View
          style={[
            s.panel,
            elevation.sheet,
            { paddingBottom: Math.max(space.lg, insets.bottom + space.sm) },
            panelStyle,
          ]}
        >
          <View style={s.grip} />
          {title ? <Text style={s.title}>{title}</Text> : null}
          {children}
        </Animated.View>
      </View>
    </Modal>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, justifyContent: 'flex-end' },
  backdrop: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: '#0E1729' },
  backdropTarget: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 },
  panel: {
    backgroundColor: color.surface,
    borderTopLeftRadius: radius.sheet,
    borderTopRightRadius: radius.sheet,
    paddingHorizontal: space.lg,
    paddingTop: space.sm,
    gap: space.md,
  },
  grip: {
    width: 36,
    height: 4,
    borderRadius: 2,
    backgroundColor: color.sunk2,
    alignSelf: 'center',
    marginBottom: space.sm,
  },
  title: { ...type.title, fontSize: 18, lineHeight: 24 },
});
