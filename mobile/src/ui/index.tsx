// The component vocabulary.
//
// Two things govern everything here, and both are reactions to what the previous version got
// wrong:
//
//   NO LABEL SHOUTS. The old system set every field label in tracked uppercase and every small
//   value in monospace, which made a screen of six facts look like a readout from an instrument.
//   Labels here are sentence case in the interface face, sized down and lightened rather than
//   transformed. Monospace appears only on a hash.
//
//   NOTHING IS JOINED WITH A MIDDLE DOT. `ML-DSA-65 · 12 Mar, 14:02 · device key` is three facts
//   pretending to be a sentence. Where several facts belong together they are laid out as
//   separate elements with real spacing, and where one of them matters more than the others it is
//   allowed to be bigger.

import { useEffect, type ReactNode } from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  type TextInputProps,
  View,
  type ViewStyle,
} from 'react-native';
import Animated, {
  cancelAnimation,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withRepeat,
  withTiming,
} from 'react-native-reanimated';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';

import { color, elevation, motion, radius, space, tone, type as type_, type StatusTone } from '../theme.ts';

export { Seal } from './Seal.tsx';
export { feedback } from './feedback.ts';

/* ---------------------------------------------------------------- structure */

export function Screen({ children, edges = ['top'] }: { children: ReactNode; edges?: Array<'top' | 'bottom'> }) {
  return (
    <SafeAreaView style={s.screen} edges={edges}>
      {children}
    </SafeAreaView>
  );
}

export function Scroll({
  children,
  padded = true,
  footerSpace = 0,
}: {
  children: ReactNode;
  padded?: boolean;
  /** Extra bottom padding, for a screen with a pinned action bar over it. */
  footerSpace?: number;
}) {
  // The bottom inset is added here rather than by giving `Screen` a `bottom` edge. A safe-area view
  // pads the *container*, which would stop the scrollport short of the screen edge and leave a
  // dead strip that content slides under anyway. Padding the content instead lets the list run to
  // the physical edge while still being able to scroll clear of the navigation bar.
  //
  // Without this, a decision with no action bar over it -- one already at threshold, or one this
  // person cannot sign -- runs its last row underneath the Android gesture bar.
  const insets = useSafeAreaInsets();

  return (
    <ScrollView
      style={s.scroll}
      contentContainerStyle={[
        padded ? s.scrollContent : s.scrollContentBare,
        { paddingBottom: space.xxl + footerSpace + insets.bottom },
      ]}
      showsVerticalScrollIndicator={false}
    >
      {children}
    </ScrollView>
  );
}

/**
 * The title block at the top of a root screen.
 *
 * `lead` is a short human line above the title, and it is the one place the product addresses the
 * person directly. Everything else in the interface talks about decisions, not about them.
 */
export function PageTitle({
  title,
  lead,
  trailing,
}: {
  title: string;
  lead?: string;
  trailing?: ReactNode;
}) {
  return (
    <View style={s.pageTitle}>
      <View style={{ flex: 1 }}>
        {lead ? <Text style={s.pageLead}>{lead}</Text> : null}
        <Text style={s.pageTitleText}>{title}</Text>
      </View>
      {trailing}
    </View>
  );
}

/** The bar on a pushed screen. Back is a target, not a word: the label goes in the content. */
export function NavBar({
  onBack,
  title,
  trailing,
}: {
  onBack?: () => void;
  title?: string;
  trailing?: ReactNode;
}) {
  return (
    <View style={s.nav}>
      {onBack ? (
        <Pressable
          onPress={onBack}
          accessibilityRole="button"
          accessibilityLabel="Go back"
          hitSlop={12}
          style={({ pressed }) => [s.navBack, pressed && { opacity: 0.5 }]}
        >
          <Text style={s.navChevron}>‹</Text>
        </Pressable>
      ) : (
        <View style={s.navBack} />
      )}
      <Text style={s.navTitle} numberOfLines={1}>
        {title ?? ''}
      </Text>
      <View style={s.navTrailing}>{trailing}</View>
    </View>
  );
}

/**
 * A group of related content under a plain heading.
 *
 * Flat by default -- a rule above the heading, no card, no shadow. Surfaces are for things that
 * can be picked up (a decision) and sections are for things that can only be read.
 */
export function Section({
  title,
  trailing,
  children,
  flush = false,
}: {
  title?: string;
  trailing?: ReactNode;
  children: ReactNode;
  flush?: boolean;
}) {
  return (
    <View style={[s.section, flush && { marginTop: 0 }]}>
      {title ? (
        <View style={s.sectionHead}>
          <Text style={s.sectionTitle}>{title}</Text>
          {trailing}
        </View>
      ) : null}
      <View style={s.sectionBody}>{children}</View>
    </View>
  );
}

/** A white surface that can be tapped. The press response is scale, not a colour change. */
export function Card({
  children,
  onPress,
  style,
  accessibilityLabel,
}: {
  children: ReactNode;
  onPress?: () => void;
  style?: ViewStyle;
  accessibilityLabel?: string;
}) {
  const reduced = useReducedMotion();
  const pressed = useSharedValue(0);

  const animated = useAnimatedStyle(() => ({
    transform: [{ scale: reduced ? 1 : 1 - pressed.value * 0.014 }],
    opacity: 1 - pressed.value * 0.04,
  }));

  if (!onPress) return <View style={[s.card, style]}>{children}</View>;

  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      onPressIn={() => {
        pressed.value = withTiming(1, { duration: motion.instant });
      }}
      onPressOut={() => {
        pressed.value = withTiming(0, { duration: motion.quick });
      }}
    >
      <Animated.View style={[s.card, style, animated]}>{children}</Animated.View>
    </Pressable>
  );
}

export function Row({
  children,
  gap = space.sm,
  align = 'center',
  style,
}: {
  children: ReactNode;
  gap?: number;
  align?: 'center' | 'flex-start' | 'baseline';
  style?: ViewStyle;
}) {
  return <View style={[{ flexDirection: 'row', alignItems: align, gap }, style]}>{children}</View>;
}

export function Divider() {
  return <View style={s.divider} />;
}

/* -------------------------------------------------------------------- data */

/**
 * A labelled value.
 *
 * Label above, value below, label lighter and smaller -- not tracked uppercase, and not in a
 * monospace face unless the value is a hash and says so with `mono`.
 */
export function KeyValue({
  label,
  value,
  children,
  mono = false,
}: {
  label: string;
  value?: string | null;
  children?: ReactNode;
  mono?: boolean;
}) {
  return (
    <View style={s.kv}>
      <Text style={s.kvLabel}>{label}</Text>
      {children ?? (
        <Text style={mono ? s.kvMono : s.kvValue} selectable={mono}>
          {value ?? '—'}
        </Text>
      )}
    </View>
  );
}

/** A status token. Sentence case, because an interface that shouts every state is exhausting. */
export function Chip({ label, tone: t = 'neutral' }: { label: string; tone?: StatusTone }) {
  const palette = tone[t];
  return (
    <View style={[s.chip, { backgroundColor: palette.bg, borderColor: palette.border }]}>
      <Text style={[s.chipText, { color: palette.fg }]}>{label}</Text>
    </View>
  );
}

/** A dot and a phrase. Lighter than a chip, for use inside a dense row. */
export function StatusLine({ label, tone: t = 'neutral' }: { label: string; tone?: StatusTone }) {
  const palette = tone[t];
  return (
    <Row gap={space.sm}>
      <View style={[s.dot, { backgroundColor: palette.fg }]} />
      <Text style={[s.statusText, { color: palette.fg }]}>{label}</Text>
    </Row>
  );
}

export function Hash({ value, lines = 2 }: { value: string; lines?: number }) {
  return (
    <Text style={s.hash} selectable numberOfLines={lines}>
      {value}
    </Text>
  );
}

/* ----------------------------------------------------------------- actions */

export function Button({
  label,
  onPress,
  variant = 'primary',
  disabled,
  busy,
  full = true,
}: {
  label: string;
  onPress: () => void;
  variant?: 'primary' | 'secondary' | 'danger' | 'quiet';
  disabled?: boolean;
  busy?: boolean;
  full?: boolean;
}) {
  const inactive = disabled || busy;
  return (
    <Pressable
      onPress={onPress}
      disabled={inactive}
      accessibilityRole="button"
      accessibilityState={{ disabled: !!inactive, busy: !!busy }}
      style={({ pressed }) => [
        s.button,
        full && { alignSelf: 'stretch' },
        variant === 'primary' && s.buttonPrimary,
        variant === 'secondary' && s.buttonSecondary,
        variant === 'danger' && s.buttonDanger,
        variant === 'quiet' && s.buttonQuiet,
        pressed && !inactive && { opacity: 0.75 },
        inactive && { opacity: 0.45 },
      ]}
    >
      {busy ? (
        <ActivityIndicator color={variant === 'primary' ? color.chromeInk : color.ink2} />
      ) : (
        <Text
          style={[
            s.buttonText,
            variant === 'primary' && { color: color.chromeInk },
            variant === 'danger' && { color: color.broken },
            variant === 'quiet' && { color: color.ink2 },
          ]}
        >
          {label}
        </Text>
      )}
    </Pressable>
  );
}

/** The bar pinned to the bottom of a decision. One of only two elevated surfaces in the app. */
export function ActionBar({ children }: { children: ReactNode }) {
  const insets = useSafeAreaInsets();
  return (
    <View style={[s.actionBar, elevation.bar, { paddingBottom: Math.max(space.md, insets.bottom) }]}>
      {children}
    </View>
  );
}

export function Field({
  label,
  hint,
  ...props
}: TextInputProps & { label: string; hint?: string }) {
  return (
    <View style={s.field}>
      <Text style={s.fieldLabel}>{label}</Text>
      <TextInput
        style={s.input}
        placeholderTextColor={color.ink4}
        autoCapitalize="none"
        autoCorrect={false}
        {...props}
      />
      {hint ? <Text style={s.fieldHint}>{hint}</Text> : null}
    </View>
  );
}

/* ------------------------------------------------------------------ states */

/** Survives only for genuine failures: an integrity mismatch, or an action the app refused. */
export function Banner({
  tone: t,
  title,
  detail,
}: {
  tone: StatusTone;
  title: string;
  detail?: string;
}) {
  const palette = tone[t];
  return (
    <View style={[s.banner, { backgroundColor: palette.bg, borderColor: palette.border }]}>
      <Text style={[s.bannerTitle, { color: palette.fg }]}>{title}</Text>
      {detail ? <Text style={[s.bannerDetail, { color: palette.fg }]}>{detail}</Text> : null}
    </View>
  );
}

/** An empty screen invites an action. It never explains what the screen would have contained. */
export function Empty({ title, detail, action }: { title: string; detail?: string; action?: ReactNode }) {
  return (
    <View style={s.empty}>
      <Text style={s.emptyTitle}>{title}</Text>
      {detail ? <Text style={s.emptyDetail}>{detail}</Text> : null}
      {action ? <View style={{ marginTop: space.lg }}>{action}</View> : null}
    </View>
  );
}

export function Loading({ label }: { label?: string }) {
  return (
    <View style={s.loading}>
      <ActivityIndicator color={color.ink3} />
      {label ? <Text style={s.loadingText}>{label}</Text> : null}
    </View>
  );
}

/**
 * A placeholder shaped like the content that is coming.
 *
 * Used instead of a spinner wherever the shape is known in advance. A spinner says "wait"; a
 * skeleton says "here is what you are waiting for", and on a list that difference is the whole
 * perceived speed of the screen.
 */
export function Skeleton({
  height = 16,
  width = '100%' as ViewStyle['width'],
  style,
}: {
  height?: number;
  width?: ViewStyle['width'];
  style?: ViewStyle;
}) {
  const reduced = useReducedMotion();
  const pulse = useSharedValue(0.55);

  // Started from an effect, not from the render body. Assigning to a shared value while rendering
  // is a write during React's render phase: it runs again on every re-render, restarting the
  // animation from wherever it had got to, and under StrictMode's double render it schedules the
  // same animation twice.
  useEffect(() => {
    if (reduced) return;
    // A slow breath rather than a shimmer sweep. A sweep draws the eye to the placeholder, which
    // is the one thing on screen that does not matter.
    pulse.value = withRepeat(withTiming(1, { duration: 900 }), -1, true);
    return () => cancelAnimation(pulse);
  }, [reduced, pulse]);

  const animated = useAnimatedStyle(() => ({ opacity: reduced ? 0.55 : pulse.value }));

  return <Animated.View style={[s.skeleton, { height, width }, style, animated]} />;
}

const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.paper },
  scroll: { flex: 1, backgroundColor: color.paper },
  scrollContent: { paddingHorizontal: space.lg },
  scrollContentBare: {},

  pageTitle: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: space.md,
    paddingTop: space.lg,
    paddingBottom: space.lg,
  },
  pageLead: { ...type_.meta, marginBottom: 2 },
  pageTitleText: { ...type_.title, fontSize: 26, lineHeight: 32 },

  nav: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: space.sm,
    height: 44,
    gap: space.xs,
  },
  navBack: { width: 40, height: 44, alignItems: 'center', justifyContent: 'center' },
  navChevron: { fontSize: 32, lineHeight: 36, color: color.ink2, marginTop: -4 },
  navTitle: { ...type_.heading, flex: 1, textAlign: 'center' },
  navTrailing: { width: 40, alignItems: 'flex-end', paddingRight: space.sm },

  section: { marginTop: space.xl },
  sectionHead: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: space.md,
  },
  sectionTitle: { ...type_.heading },
  sectionBody: { gap: space.sm },

  card: {
    backgroundColor: color.surface,
    borderWidth: 1,
    borderColor: color.rule,
    borderRadius: radius.card,
    padding: space.lg,
    gap: space.md,
  },

  divider: { height: 1, backgroundColor: color.rule2 },

  kv: { gap: 3, paddingVertical: space.xs },
  kvLabel: { ...type_.micro, color: color.ink3 },
  kvValue: { ...type_.body },
  kvMono: { ...type_.hash },

  chip: {
    borderWidth: 1,
    borderRadius: radius.chip,
    paddingHorizontal: space.sm,
    paddingVertical: 3,
  },
  chipText: { fontSize: 12.5, lineHeight: 16 },

  dot: { width: 7, height: 7, borderRadius: 3.5 },
  statusText: { fontSize: 13, lineHeight: 18 },

  hash: { ...type_.hash },

  button: {
    minHeight: 50,
    borderRadius: radius.control,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: space.xl,
    borderWidth: 1,
  },
  buttonPrimary: { backgroundColor: color.chrome, borderColor: color.chrome },
  buttonSecondary: { backgroundColor: color.surface, borderColor: color.rule },
  buttonDanger: { backgroundColor: color.surface, borderColor: color.brokenLine },
  buttonQuiet: { backgroundColor: 'transparent', borderColor: 'transparent', minHeight: 40 },
  buttonText: { ...type_.action, color: color.ink },

  actionBar: {
    backgroundColor: color.surface,
    borderTopWidth: 1,
    borderTopColor: color.rule,
    paddingHorizontal: space.lg,
    paddingTop: space.md,
    gap: space.sm,
  },

  field: { gap: space.xs },
  fieldLabel: { ...type_.micro, color: color.ink2 },
  input: {
    ...type_.body,
    backgroundColor: color.surface,
    borderWidth: 1,
    borderColor: color.rule,
    borderRadius: radius.control,
    paddingHorizontal: space.md,
    minHeight: 48,
  },
  fieldHint: { ...type_.micro },

  banner: {
    borderWidth: 1,
    borderRadius: radius.card,
    padding: space.md,
    gap: space.xs,
  },
  bannerTitle: { fontSize: 14.5, lineHeight: 20, fontWeight: '600' },
  bannerDetail: { fontSize: 13.5, lineHeight: 19 },

  empty: { alignItems: 'center', paddingVertical: space.xxxl, gap: space.sm },
  emptyTitle: { ...type_.body, color: color.ink2, textAlign: 'center' },
  emptyDetail: { ...type_.meta, textAlign: 'center', maxWidth: 280 },

  loading: { alignItems: 'center', paddingVertical: space.xxl, gap: space.md },
  loadingText: { ...type_.meta },

  skeleton: { backgroundColor: color.sunk2, borderRadius: 6 },
});
