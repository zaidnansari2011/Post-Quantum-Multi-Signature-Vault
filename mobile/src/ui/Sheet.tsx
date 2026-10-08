// The sheet (phone-ux §5.9).
//
// Before the signature, the person is shown the decision again, in the words it will be recorded
// in, and asked to confirm that sentence rather than "the thing I was just looking at". The OS
// biometric prompt cannot do that job: it authorises a person, not a statement.
//
// Anatomy: a grabber; a fixed header with the title; a scrolling body (a decision can run to 4,000
// characters, and the title, the start of the text and the button must all stay on screen); a
// fixed footer with the buttons above the bottom inset. It stops 24pt short of the top inset.
//
// Dragging the grabber or the header down more than 30% of the sheet, or faster than 800pt/s,
// closes it, unless `dismissible` is false (a signature in flight), when it springs back. Android
// back, a tap on the backdrop and Cancel close it too, under the same rule.
//
// The keyboard: the footer (the sign button) rides above it, and the sheet's height shrinks by it.
// Fields in a sheet are never autofocused, so the content is read before the keyboard arrives.

import { useCallback, useEffect, useRef, useState, type ReactNode, type RefObject } from 'react';
import {
  AccessibilityInfo,
  Keyboard,
  Modal,
  Platform,
  ScrollView,
  View,
  findNodeHandle,
  useWindowDimensions,
  type Text as RNText,
} from 'react-native';
import { Gesture, GestureDetector, GestureHandlerRootView } from 'react-native-gesture-handler';
import Animated, {
  Easing,
  runOnJS,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withSpring,
  withTiming,
} from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { makeStyles, useTheme } from '../theme/index.ts';
import { IconButton } from './Button.tsx';
import { Text } from './Text.tsx';
import { RaisedSurface } from './surface.ts';
import { Touchable } from './Touchable.tsx';

const bezier = (p: readonly number[]) => Easing.bezier(p[0]!, p[1]!, p[2]!, p[3]!);

/** The keyboard's height while it is up, from React Native's own events (§5.9). */
export function useKeyboardHeight(): number {
  const [height, setHeight] = useState(0);
  useEffect(() => {
    const show = Platform.OS === 'ios' ? 'keyboardWillShow' : 'keyboardDidShow';
    const hide = Platform.OS === 'ios' ? 'keyboardWillHide' : 'keyboardDidHide';
    const a = Keyboard.addListener(show, (e) => setHeight(e.endCoordinates.height));
    const b = Keyboard.addListener(hide, () => setHeight(0));
    return () => {
      a.remove();
      b.remove();
    };
  }, []);
  return height;
}

export type SheetProps = {
  visible: boolean;
  onClose: () => void;
  title?: string;
  /** Scrolls when it is taller than the room the sheet has. */
  children: ReactNode;
  /** The actions, pinned under the content. */
  footer?: ReactNode;
  /** False while a signature is in flight: closing midway would leave the outcome unclear. */
  dismissible?: boolean;
  /** A sheet showing a second page of itself (the code explanation) offers Back in its header. */
  onBack?: () => void;
  /** The control that opened the sheet: a screen reader's focus returns to it on close (§5.9). */
  returnFocusTo?: RefObject<View | null>;
};

/** Move a screen reader's focus to a view. Native only; a courtesy that must never throw. */
function focus(node: View | Text | null | undefined) {
  if (Platform.OS === 'web' || !node) return;
  try {
    const tag = findNodeHandle(node as View);
    if (tag) AccessibilityInfo.setAccessibilityFocus(tag);
  } catch {
    // Nothing to do: the sheet works without it.
  }
}

export function Sheet({
  visible,
  onClose,
  title,
  children,
  footer,
  dismissible = true,
  onBack,
  returnFocusTo,
}: SheetProps) {
  const t = useTheme();
  const s = useStyles();
  const reduced = useReducedMotion();
  const insets = useSafeAreaInsets();
  const window = useWindowDimensions();
  const keyboard = useKeyboardHeight();

  const [mounted, setMounted] = useState(visible);
  const [panelHeight, setPanelHeight] = useState(window.height * 0.6);
  const [room, setRoom] = useState(0);
  const [content, setContent] = useState(0);
  const titleRef = useRef<RNText>(null);

  const progress = useSharedValue(0);
  const drag = useSharedValue(0);

  // Unmounted after the exit animation; focus goes back to whatever opened the sheet.
  const closed = useCallback(() => {
    setMounted(false);
    focus(returnFocusTo?.current);
  }, [returnFocusTo]);

  // Mount, animate in; animate out, then unmount.
  useEffect(() => {
    if (visible) {
      setMounted(true);
      drag.value = 0;
      progress.value = withTiming(1, {
        duration: reduced ? t.motion.popover : t.motion.dialog,
        easing: bezier(t.motion.easeEnter),
      });
      // Focus moves to the title, so a screen reader starts at the top of the sheet (§5.9).
      const at = setTimeout(() => focus(titleRef.current as unknown as View), t.motion.dialog);
      return () => clearTimeout(at);
    }
    progress.value = withTiming(
      0,
      { duration: t.motion.dialogExit, easing: bezier(t.motion.easeExit) },
      (finished) => {
        if (finished) runOnJS(closed)();
      },
    );
    return undefined;
  }, [visible, reduced, progress, drag, t.motion, closed]);

  const pan = Gesture.Pan()
    .onUpdate((e) => {
      // Downwards only; while a signature is in flight it gives a little and springs back.
      const y = Math.max(0, e.translationY);
      drag.value = dismissible ? y : y * 0.2;
    })
    .onEnd((e) => {
      const far = drag.value > panelHeight * 0.3 || e.velocityY > 800;
      if (dismissible && far) {
        runOnJS(onClose)();
      } else {
        drag.value = withSpring(0, t.motion.surface);
      }
    });

  const backdrop = useAnimatedStyle(() => ({ opacity: progress.value }));
  const panel = useAnimatedStyle(() =>
    reduced
      ? { opacity: progress.value, transform: [{ translateY: drag.value }] }
      : { transform: [{ translateY: (1 - progress.value) * panelHeight + drag.value }] },
  );

  if (!mounted) return null;

  const overflowing = content > room + 1;
  const maxHeight = window.height - insets.top - t.space[24] - keyboard;
  const bottom = keyboard > 0 ? keyboard + t.space[8] : Math.max(t.space[16], insets.bottom + t.space[8]);

  return (
    <Modal
      visible
      transparent
      animationType="none"
      statusBarTranslucent
      navigationBarTranslucent
      onRequestClose={() => dismissible && onClose()}
    >
      <GestureHandlerRootView style={s.root}>
        <Animated.View style={[s.backdrop, backdrop]} pointerEvents="none" />
        <Touchable
          style={s.backdropTarget}
          onPress={() => dismissible && onClose()}
          accessible={false}
          importantForAccessibility="no"
          focusable={false}
        />
        <Animated.View
          accessibilityViewIsModal
          onLayout={(e) => setPanelHeight(e.nativeEvent.layout.height)}
          style={[s.panel, t.elevation.sheet, { maxHeight, paddingBottom: footer ? 0 : bottom }, panel]}
        >
          <GestureDetector gesture={pan}>
            <View style={s.header}>
              <View style={s.grabber} />
              {title || onBack ? (
                <View style={s.titleRow}>
                  {onBack ? (
                    <IconButton
                      icon={Platform.OS === 'android' ? 'arrow-left' : 'chevron-left'}
                      label="Back"
                      onPress={onBack}
                    />
                  ) : null}
                  {title ? (
                    <Text ref={titleRef} role="titleSm" accessibilityRole="header" style={s.title}>
                      {title}
                    </Text>
                  ) : null}
                </View>
              ) : null}
            </View>
          </GestureDetector>
          <RaisedSurface.Provider value>
          <ScrollView
            style={s.body}
            contentContainerStyle={s.bodyContent}
            onLayout={(e) => setRoom(e.nativeEvent.layout.height)}
            onContentSizeChange={(_, h) => setContent(h)}
            keyboardShouldPersistTaps="handled"
            showsVerticalScrollIndicator={overflowing}
          >
            {children}
          </ScrollView>
          {footer ? (
            <View style={[s.footer, overflowing && s.footerRuled, { paddingBottom: bottom }]}>{footer}</View>
          ) : null}
          </RaisedSurface.Provider>
        </Animated.View>
      </GestureHandlerRootView>
    </Modal>
  );
}

const useStyles = makeStyles((t) => ({
  root: { flex: 1, justifyContent: 'flex-end' },
  backdrop: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: t.color.backdrop },
  backdropTarget: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 },
  panel: {
    width: '100%',
    maxWidth: t.layout.maxContent,
    alignSelf: 'center',
    backgroundColor: t.color.surfaceRaised,
    borderTopLeftRadius: t.radius.sheet,
    borderTopRightRadius: t.radius.sheet,
    borderTopWidth: t.scheme === 'dark' ? 1 : 0,
    borderColor: t.color.border,
  },
  header: { paddingTop: t.space[8], paddingHorizontal: t.layout.gutter, paddingBottom: t.space[12] },
  grabber: {
    width: 36,
    height: 5,
    borderRadius: 3,
    backgroundColor: t.color.borderStrong,
    alignSelf: 'center',
    marginBottom: t.space[12],
  },
  titleRow: { flexDirection: 'row', alignItems: 'center', gap: t.space[4], minHeight: 24 },
  title: { flex: 1 },
  body: { flexGrow: 0, flexShrink: 1 },
  bodyContent: { paddingHorizontal: t.layout.gutter, paddingBottom: t.space[16], gap: t.space[16] },
  footer: { paddingHorizontal: t.layout.gutter, paddingTop: t.space[4], gap: t.space[8] },
  footerRuled: { borderTopWidth: 1, borderTopColor: t.color.border, paddingTop: t.space[12] },
}));
