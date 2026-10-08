// Every piece of text in the app (phone-ux §4.1, §4.3).
//
// A required `role` from the phone's type scale sets the family, size, line height, tracking and the
// cap on how far the system's text size may grow it. Nothing else in the app imports Text from
// react-native (a test enforces it), so no label can fall back to the system font again, which is
// what the status words, chips and banners did before.
//
// At large text sizes the OS scales each role up to its cap. The web harness cannot ask the OS, so
// with an emulated font scale (`?fontScale=2`) this multiplies the size itself, capped the same way
// (§8.1). The signed text has no cap: it steps down from decisionHero to decision at 1.3x instead.

import { forwardRef } from 'react';
import { Text as RNText, type TextProps as RNTextProps, type TextStyle } from 'react-native';

import { useTheme, type Theme, type TypeRole } from '../theme/index.ts';

export type TextTone =
  | 'text'
  | 'muted'
  | 'subtle'
  | 'disabled'
  | 'link'
  | 'accentFg'
  | 'onAccent'
  | 'onDanger'
  | 'success'
  | 'warning'
  | 'critical'
  | 'info'
  | 'neutral'
  | 'chrome'
  | 'chromeMuted';

export function toneColor(t: Theme, tone: TextTone): string {
  const c = t.color;
  switch (tone) {
    case 'text':
      return c.text;
    case 'muted':
      return c.textMuted;
    case 'subtle':
      return c.textSubtle;
    case 'disabled':
      return c.textDisabled;
    case 'link':
      return c.link;
    case 'accentFg':
      return c.accentFg;
    case 'onAccent':
      return c.accentText;
    case 'onDanger':
      return c.dangerText;
    case 'chrome':
      return c.chrome.text;
    case 'chromeMuted':
      return c.chrome.textMuted;
    default:
      return c.status[tone].fg;
  }
}

/** The style one role produces under the current theme, for the rare caller that needs numbers. */
export function roleStyle(t: Theme, role: TypeRole, cap?: number | null): TextStyle {
  const spec = t.type[role];
  const limit = cap === undefined ? spec.maxScale : cap;
  const factor = t.emulatedFontScale ? Math.min(t.fontScale, limit ?? t.fontScale) : 1;
  return {
    fontFamily: spec.fontFamily,
    fontSize: spec.fontSize * factor,
    lineHeight: spec.lineHeight * factor,
    letterSpacing: spec.letterSpacing,
    fontVariant: spec.tabular ? ['tabular-nums'] : undefined,
  };
}

export type TextProps = Omit<RNTextProps, 'role'> & {
  role: TypeRole;
  tone?: TextTone;
  /** A colour from the theme, when no tone fits (e.g. a status token on a tinted surface). */
  color?: string;
  /** A tighter cap than the role's own, for where it is used (§4.3: buttons 1.6, nav title 1.4). */
  maxScale?: number | null;
  /** Every amount, count and time (§4.1). */
  tabular?: boolean;
  align?: TextStyle['textAlign'];
};

export const Text = forwardRef<RNText, TextProps>(function Text(
  { role, tone = 'text', color, maxScale, tabular, align, style, ...rest },
  ref,
) {
  const t = useTheme();
  const spec = t.type[role];
  const cap = maxScale === undefined ? spec.maxScale : maxScale;
  return (
    <RNText
      ref={ref}
      {...rest}
      allowFontScaling={!t.emulatedFontScale}
      // 0 means "no cap" to React Native.
      maxFontSizeMultiplier={cap ?? 0}
      style={[
        roleStyle(t, role, cap),
        { color: color ?? toneColor(t, tone) },
        tabular ? { fontVariant: ['tabular-nums'] } : null,
        align ? { textAlign: align } : null,
        style,
      ]}
    />
  );
});
