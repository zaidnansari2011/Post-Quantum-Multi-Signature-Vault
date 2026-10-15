// Toasts (phone-ux §5.10): only to confirm something done in the background ("Link copied",
// "Reminder sent"). Never for errors, which go where the action was. One at a time, four seconds,
// 16 above the tab bar or action bar, on the chrome navy.

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { AccessibilityInfo, Platform, View } from 'react-native';
import Animated, { FadeInDown, FadeOut, useReducedMotion } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { makeStyles, useTheme } from '../theme/index.ts';
import { Text } from './Text.tsx';

type ToastApi = {
  show(text: string): void;
  /** How far above the bottom inset the toast sits: the tab bar's or the action bar's height. */
  setOffset(offset: number): void;
};

const ToastContext = createContext<ToastApi | null>(null);

/** Tab bar height above the safe area (§2.2). */
const TAB_BAR = 49;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [text, setText] = useState<string | null>(null);
  const [offset, setOffset] = useState(TAB_BAR);
  const [serial, setSerial] = useState(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const t = useTheme();

  const show = useCallback(
    (next: string) => {
      setText(next);
      setSerial((n) => n + 1);
      if (Platform.OS === 'ios') AccessibilityInfo.announceForAccessibility(next);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setText(null), t.motion.toast);
    },
    [t.motion.toast],
  );
  useEffect(() => () => void (timer.current && clearTimeout(timer.current)), []);

  const api = useMemo(() => ({ show, setOffset }), [show]);
  return (
    <ToastContext.Provider value={api}>
      {children}
      {text ? <ToastView key={serial} text={text} offset={offset} /> : null}
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const api = useContext(ToastContext);
  if (!api) throw new Error('useToast must be used inside a ToastProvider');
  return api;
}

/** The toast itself; exported for the gallery. */
export function ToastView({ text, offset = TAB_BAR, inline = false }: { text: string; offset?: number; inline?: boolean }) {
  const s = useStyles();
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const reduced = useReducedMotion();
  return (
    <View
      pointerEvents="none"
      style={inline ? null : [s.layer, { bottom: insets.bottom + offset + t.space[16] }]}
    >
      <Animated.View
        entering={reduced ? undefined : FadeInDown.duration(t.motion.dialog)}
        exiting={reduced ? undefined : FadeOut.duration(t.motion.popover)}
        style={s.toast}
        accessibilityLiveRegion="polite"
        accessibilityRole="text"
      >
        <Text role="body" tone="chrome">
          {text}
        </Text>
      </Animated.View>
    </View>
  );
}

const useStyles = makeStyles((t) => ({
  layer: { position: 'absolute', left: t.layout.gutter, right: t.layout.gutter, alignItems: 'center' },
  toast: {
    backgroundColor: t.color.chrome.bg,
    borderRadius: t.radius.card,
    paddingHorizontal: t.space[16],
    paddingVertical: t.space[12],
    borderWidth: t.scheme === 'dark' ? 1 : 0,
    borderColor: t.color.chrome.border,
    maxWidth: t.layout.maxContent,
  },
}));
