// Buttons, icon buttons and text links (phone-ux §5.2, §4.6).
//
// One primary action per screen, in the accent. Pressed steps the fill (never a scale); disabled is
// its own colour scheme (never opacity, which is what made today's disabled buttons fail contrast);
// busy keeps the label and puts a native spinner before it, so it keeps turning while the ML-DSA
// work holds the JS thread (§6.10).

import { ActivityIndicator, View, type ViewStyle } from 'react-native';

import { makeStyles, scaleCap, useTheme, type Theme } from '../theme/index.ts';
import { Icon, type IconName } from './Icon.tsx';
import { Text, type TextTone } from './Text.tsx';
import { Touchable } from './Touchable.tsx';

export type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'dangerSecondary' | 'quiet';

export type ButtonProps = {
  label: string;
  onPress: () => void;
  variant?: ButtonVariant;
  /** Only when the action is truly unavailable, with a visible reason beside it (§5.2). */
  disabled?: boolean;
  busy?: boolean;
  /** Full width (sheets and bars). Elsewhere a button is as wide as its label. */
  full?: boolean;
  icon?: IconName;
  accessibilityHint?: string;
  accessibilityLabel?: string;
  style?: ViewStyle;
};

function paint(t: Theme, variant: ButtonVariant, pressed: boolean, disabled: boolean) {
  const c = t.color;
  if (disabled) {
    return {
      bg: variant === 'quiet' ? 'transparent' : c.fillDisabled,
      border: variant === 'quiet' ? 'transparent' : c.borderDisabled,
      fg: 'disabled' as TextTone,
    };
  }
  switch (variant) {
    case 'primary':
      return { bg: pressed ? c.accentPressed : c.accent, border: 'transparent', fg: 'onAccent' as TextTone };
    case 'danger':
      return { bg: pressed ? c.dangerPressed : c.danger, border: 'transparent', fg: 'onDanger' as TextTone };
    case 'secondary':
      return { bg: pressed ? c.fill : c.surface, border: c.borderStrong, fg: 'text' as TextTone };
    case 'dangerSecondary':
      // The label is the critical status foreground, not --danger: dark --danger on a dark surface
      // is 3.4:1, under the 4.5 a 16pt label needs. In light the two are the same colour.
      return { bg: pressed ? c.fill : c.surface, border: c.borderStrong, fg: 'critical' as TextTone };
    case 'quiet':
    default:
      return { bg: pressed ? c.fill : 'transparent', border: 'transparent', fg: 'muted' as TextTone };
  }
}

export function Button({
  label,
  onPress,
  variant = 'primary',
  disabled = false,
  busy = false,
  full = false,
  icon,
  accessibilityHint,
  accessibilityLabel,
  style,
}: ButtonProps) {
  const t = useTheme();
  const s = useStyles();
  return (
    <Touchable
      onPress={onPress}
      // Inert while busy, but not drawn as disabled: it is working, not unavailable.
      disabled={disabled || busy}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityHint={accessibilityHint}
      accessibilityState={{ disabled, busy }}
      ringRadius={t.radius.control}
      style={({ pressed }) => {
        const p = paint(t, variant, pressed, disabled);
        return [s.button, full && s.full, { backgroundColor: p.bg, borderColor: p.border }, style];
      }}
    >
      {({ pressed }) => {
        const p = paint(t, variant, pressed, disabled);
        const fg = p.fg;
        return (
          <View style={s.inner}>
            {busy ? (
              <ActivityIndicator size="small" color={toneHex(t, fg)} style={s.spinner} />
            ) : icon ? (
              <Icon name={icon} size={20} color={toneHex(t, fg)} />
            ) : null}
            <Text role="bodyStrong" tone={fg} maxScale={scaleCap.button} align="center">
              {label}
            </Text>
          </View>
        );
      }}
    </Touchable>
  );
}

function toneHex(t: Theme, tone: TextTone): string {
  const c = t.color;
  switch (tone) {
    case 'onAccent':
      return c.accentText;
    case 'onDanger':
      return c.dangerText;
    case 'critical':
      return c.status.critical.fg;
    case 'disabled':
      return c.textDisabled;
    case 'muted':
      return c.textMuted;
    default:
      return c.text;
  }
}

/**
 * A 44pt icon button with a 48 target: back, overflow, the header plus, copy, the eye (§4.6).
 * The label is spoken, not drawn.
 */
export function IconButton({
  icon,
  label,
  onPress,
  color,
  size = 24,
  disabled,
  tone = 'plain',
  hint,
}: {
  icon: IconName;
  label: string;
  onPress: () => void;
  color?: string;
  size?: number;
  disabled?: boolean;
  /** `filled` draws the round accent-filled header action. */
  tone?: 'plain' | 'filled';
  hint?: string;
}) {
  const t = useTheme();
  const s = useStyles();
  const filled = tone === 'filled';
  return (
    <Touchable
      onPress={onPress}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityHint={hint}
      accessibilityState={{ disabled: !!disabled }}
      ringRadius={22}
      style={({ pressed }) => [
        s.iconButton,
        filled && { backgroundColor: pressed ? t.color.accentPressed : t.color.accent },
        !filled && pressed && { backgroundColor: t.color.fill },
      ]}
    >
      <Icon
        name={icon}
        size={size}
        color={
          disabled ? t.color.textDisabled : (color ?? (filled ? t.color.accentText : t.color.textMuted))
        }
      />
    </Touchable>
  );
}

/** "Change", "Show full", "Choose signers": a link whose target is 44pt tall, not its 16pt text. */
export function TextLink({
  label,
  onPress,
  accessibilityLabel,
  tone = 'link',
  disabled,
  role = 'body',
}: {
  label: string;
  onPress: () => void;
  accessibilityLabel?: string;
  tone?: TextTone;
  disabled?: boolean;
  role?: 'body' | 'bodyStrong' | 'caption';
}) {
  const s = useStyles();
  return (
    <Touchable
      onPress={onPress}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? label}
      style={({ pressed }) => [s.link, pressed && s.linkPressed]}
      ringRadius={6}
    >
      <Text role={role} tone={disabled ? 'disabled' : tone}>
        {label}
      </Text>
    </Touchable>
  );
}

const useStyles = makeStyles((t) => ({
  button: {
    minHeight: 48,
    borderRadius: t.radius.control,
    borderWidth: 1,
    paddingHorizontal: t.space[20],
    paddingVertical: t.space[12],
    justifyContent: 'center',
    alignItems: 'center',
    alignSelf: 'flex-start',
  },
  full: { alignSelf: 'stretch' },
  inner: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: t.space[8] },
  spinner: { width: 16, height: 16, transform: [{ scale: 0.8 }] },
  iconButton: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: 'center',
    justifyContent: 'center',
  },
  link: { minHeight: 44, justifyContent: 'center', alignSelf: 'flex-start', borderRadius: 6 },
  linkPressed: { backgroundColor: t.color.fill },
}));
