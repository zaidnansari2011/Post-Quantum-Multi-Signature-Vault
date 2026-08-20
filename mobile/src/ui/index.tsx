// The component vocabulary, ported from the .chip / .panel / .meta / .dt set in qvault.css.
//
// Rule 2 of the design system is enforced here rather than left to each screen: `Chip` and
// `Banner` are the only components that take a tone, and the only saturated colour in the app
// comes from them. Buttons are achromatic. Nothing decorative is coloured.

import type { ReactNode } from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  type TextInputProps,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { color, radius, space, tone, type, type StatusTone } from '../theme.ts';

export function Screen({ children }: { children: ReactNode }) {
  return (
    <SafeAreaView style={s.screen} edges={['top', 'left', 'right']}>
      {children}
    </SafeAreaView>
  );
}

export function Body({ children }: { children: ReactNode }) {
  return (
    <ScrollView
      style={s.body}
      contentContainerStyle={s.bodyContent}
      keyboardShouldPersistTaps="handled"
    >
      {children}
    </ScrollView>
  );
}

/**
 * The dark spine, carried over from the web rail. Achromatic, so it gives the product a shape
 * without introducing a hue that would compete with status.
 *
 * `figure` is the screen's single moment of scale (rule 3). A screen passes it at most once.
 */
export function Header({
  title,
  subtitle,
  figure,
  figureLabel,
  onBack,
}: {
  title: string;
  subtitle?: string;
  figure?: string;
  figureLabel?: string;
  onBack?: () => void;
}) {
  return (
    <View style={s.header}>
      <View style={s.headerTop}>
        {onBack ? (
          <Pressable onPress={onBack} hitSlop={12} accessibilityRole="button">
            <Text style={s.back}>Back</Text>
          </Pressable>
        ) : null}
        <View style={s.headerText}>
          <Text style={s.headerTitle} numberOfLines={2}>
            {title}
          </Text>
          {subtitle ? (
            <Text style={s.headerSubtitle} numberOfLines={1}>
              {subtitle}
            </Text>
          ) : null}
        </View>
      </View>
      {figure ? (
        <View style={s.figureWrap}>
          <Text style={s.figure}>{figure}</Text>
          {figureLabel ? <Text style={s.figureLabel}>{figureLabel}</Text> : null}
        </View>
      ) : null}
    </View>
  );
}

export function Panel({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <View style={s.panel}>
      {title ? <Text style={s.panelTitle}>{title}</Text> : null}
      {children}
    </View>
  );
}

/** A label/value pair. Cryptographic fact belongs here, as ordinary metadata (rule 3). */
export function Meta({
  label,
  value,
  mono,
  children,
}: {
  label: string;
  value?: string | null;
  mono?: boolean;
  children?: ReactNode;
}) {
  return (
    <View style={s.metaRow}>
      <Text style={s.metaLabel}>{label}</Text>
      <View style={s.metaValue}>
        {children ?? (
          <Text style={mono ? s.metaMono : s.metaText} numberOfLines={2}>
            {value ?? '—'}
          </Text>
        )}
      </View>
    </View>
  );
}

export function Chip({ label, tone: t = 'neutral' }: { label: string; tone?: StatusTone }) {
  const palette = tone[t];
  return (
    <View style={[s.chip, { backgroundColor: palette.bg, borderColor: palette.border }]}>
      <Text style={[s.chipText, { color: palette.fg }]}>{label}</Text>
    </View>
  );
}

export function Row({ children, gap = 8 }: { children: ReactNode; gap?: number }) {
  return <View style={[s.row, { gap }]}>{children}</View>;
}

export function Hash({ value }: { value: string }) {
  return (
    <Text style={s.hash} selectable numberOfLines={2}>
      {value}
    </Text>
  );
}

export function Button({
  label,
  onPress,
  variant = 'primary',
  disabled,
  busy,
}: {
  label: string;
  onPress: () => void;
  variant?: 'primary' | 'secondary' | 'danger';
  disabled?: boolean;
  busy?: boolean;
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
        variant === 'primary' && s.buttonPrimary,
        variant === 'secondary' && s.buttonSecondary,
        variant === 'danger' && s.buttonDanger,
        pressed && !inactive && s.buttonPressed,
        inactive && s.buttonDisabled,
      ]}
    >
      {busy ? (
        <ActivityIndicator color={variant === 'primary' ? color.chromeInk : color.ink} />
      ) : (
        <Text
          style={[
            s.buttonText,
            variant === 'secondary' && s.buttonTextSecondary,
            variant === 'danger' && s.buttonTextDanger,
          ]}
        >
          {label}
        </Text>
      )}
    </Pressable>
  );
}

export function Field({ label, hint, ...props }: TextInputProps & { label: string; hint?: string }) {
  return (
    <View style={s.field}>
      <Text style={s.fieldLabel}>{label}</Text>
      <TextInput
        style={s.input}
        placeholderTextColor={color.ink3}
        autoCapitalize="none"
        autoCorrect={false}
        {...props}
      />
      {hint ? <Text style={s.fieldHint}>{hint}</Text> : null}
    </View>
  );
}

/** Survives only for genuine failures: an integrity mismatch or a refused action. */
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

/** Empty states invite an action; they never teach a concept (rule 1). */
export function Empty({ title, action }: { title: string; action?: ReactNode }) {
  return (
    <View style={s.empty}>
      <Text style={s.emptyTitle}>{title}</Text>
      {action}
    </View>
  );
}

export function Loading({ label }: { label: string }) {
  return (
    <View style={s.loading}>
      <ActivityIndicator color={color.ink2} />
      <Text style={s.loadingText}>{label}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.paper },
  body: { flex: 1, backgroundColor: color.paper },
  bodyContent: { padding: space.lg, paddingBottom: space.xxl, gap: space.md },

  header: {
    backgroundColor: color.chrome,
    paddingHorizontal: space.lg,
    paddingTop: space.md,
    paddingBottom: space.lg,
    borderBottomWidth: 1,
    borderBottomColor: color.chromeRule,
  },
  headerTop: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  headerText: { flex: 1 },
  headerTitle: { ...type.title, color: color.chromeInk },
  headerSubtitle: { ...type.meta, color: color.chromeInk2, marginTop: 2 },
  back: { ...type.body, color: color.chromeInk2 },
  figureWrap: { marginTop: space.lg },
  figure: { ...type.figure, color: color.chromeInk },
  figureLabel: { ...type.label, color: color.chromeInk2, marginTop: 2 },

  panel: {
    backgroundColor: color.surface,
    borderWidth: 1,
    borderColor: color.rule,
    borderRadius: radius,
    padding: space.md,
    gap: space.sm,
  },
  panelTitle: { ...type.label, marginBottom: space.xs },

  metaRow: { flexDirection: 'row', alignItems: 'flex-start', gap: space.md, minHeight: 22 },
  metaLabel: { ...type.meta, width: 104, color: color.ink3 },
  metaValue: { flex: 1, alignItems: 'flex-start' },
  metaText: { ...type.body },
  metaMono: { ...type.hash },

  row: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap' },

  chip: {
    borderWidth: 1,
    borderRadius: radius,
    paddingHorizontal: space.sm,
    paddingVertical: 3,
    alignSelf: 'flex-start',
  },
  chipText: { ...type.label, fontSize: 10 },

  hash: { ...type.hash },

  button: {
    minHeight: 48,
    borderRadius: radius,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: space.lg,
    borderWidth: 1,
  },
  buttonPrimary: { backgroundColor: color.chrome, borderColor: color.chrome },
  buttonSecondary: { backgroundColor: color.surface, borderColor: color.rule },
  buttonDanger: { backgroundColor: color.surface, borderColor: color.brokenLine },
  buttonPressed: { opacity: 0.82 },
  buttonDisabled: { opacity: 0.45 },
  buttonText: { ...type.heading, color: color.chromeInk },
  buttonTextSecondary: { color: color.ink },
  buttonTextDanger: { color: color.broken },

  field: { gap: space.xs },
  fieldLabel: { ...type.label },
  input: {
    minHeight: 46,
    borderWidth: 1,
    borderColor: color.rule,
    borderRadius: radius,
    backgroundColor: color.surface,
    paddingHorizontal: space.md,
    ...type.body,
  },
  fieldHint: { ...type.meta },

  banner: { borderWidth: 1, borderRadius: radius, padding: space.md, gap: space.xs },
  bannerTitle: { ...type.heading },
  bannerDetail: { ...type.meta, opacity: 0.9 },

  empty: { alignItems: 'center', gap: space.md, paddingVertical: space.xxl },
  emptyTitle: { ...type.body, color: color.ink3 },

  loading: { alignItems: 'center', gap: space.sm, paddingVertical: space.xxl },
  loadingText: { ...type.meta },
});
