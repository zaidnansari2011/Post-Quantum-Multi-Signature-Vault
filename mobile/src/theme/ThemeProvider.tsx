// One theme provider for the whole app (phone-ux §3.1).
//
// The scheme follows the system through `useColorScheme()`, so switching the phone to dark while
// Q-Vault is open re-renders it without a restart (the HIG's Auto case). There is no in-app
// appearance setting (§3.6; the owner's answer to §12 Q4). The `scheme` and `fontScale` props are
// for the web screenshot harness and tests only: react-native-web reports neither a dark system nor
// a font scale, so the harness emulates both through here (§8.1).

import { createContext, type ReactNode, useMemo } from 'react';
import { useColorScheme, useWindowDimensions } from 'react-native';

import { dark, light, type ColorTokens } from './tokens.generated.ts';
import {
  breakpoints,
  elevationFor,
  layout,
  motion,
  radius,
  space,
  typeScale,
  type Elevation,
} from './scale.ts';

export type Scheme = 'light' | 'dark';

export type Theme = {
  scheme: Scheme;
  color: ColorTokens;
  type: typeof typeScale;
  space: typeof space;
  radius: typeof radius;
  motion: typeof motion;
  layout: typeof layout;
  breakpoints: typeof breakpoints;
  elevation: Elevation;
  /** The system's text size multiplier, or the harness's emulated one. */
  fontScale: number;
  /**
   * True only in the harness with `?fontScale=`: `ui/Text` then multiplies each role's size itself
   * (capped by the role's maxScale), because react-native-web ignores the system's text size.
   */
  emulatedFontScale: boolean;
  /** Rows, the action bar and the segmented control take their stacked layouts (§4.3). */
  stacked: boolean;
};

export const ThemeContext = createContext<Theme | null>(null);

export function ThemeProvider({
  children,
  scheme: schemeOverride,
  fontScale: fontScaleOverride,
}: {
  children: ReactNode;
  /** Harness and tests only. The app itself always follows the system. */
  scheme?: Scheme;
  /** Harness and tests only: emulate a system text size (§8.1). */
  fontScale?: number;
}) {
  const system = useColorScheme();
  const window = useWindowDimensions();
  const scheme: Scheme = schemeOverride ?? (system === 'dark' ? 'dark' : 'light');
  const emulated = fontScaleOverride !== undefined;
  const fontScale = fontScaleOverride ?? window.fontScale ?? 1;

  // One object per scheme and scale, so makeStyles can memoise on its identity.
  const theme = useMemo<Theme>(() => {
    const color = scheme === 'dark' ? dark : light;
    return {
      scheme,
      color,
      type: typeScale,
      space,
      radius,
      motion,
      layout,
      breakpoints,
      elevation: elevationFor(scheme, color),
      fontScale,
      emulatedFontScale: emulated,
      stacked: fontScale >= breakpoints.stacked,
    };
  }, [scheme, fontScale, emulated]);

  return <ThemeContext.Provider value={theme}>{children}</ThemeContext.Provider>;
}
