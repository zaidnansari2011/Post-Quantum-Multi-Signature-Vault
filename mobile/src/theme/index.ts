// The theme's public surface: `useTheme()` and `makeStyles()` (phone-ux §3.1).
//
// Every component and screen styles itself through `makeStyles`, which builds its StyleSheet once
// per theme (scheme and font scale) and hands the same object back on every render after that.
// There are no module-level colour constants anywhere in the app: a test fails on any hex literal
// outside this folder.

import { useContext } from 'react';
import { StyleSheet } from 'react-native';

import { ThemeContext, type Theme } from './ThemeProvider.tsx';

export { ThemeProvider, type Scheme, type Theme } from './ThemeProvider.tsx';
export type { ColorTokens } from './tokens.generated.ts';
export { fontFamily, typeScale, scaleCap, type TypeRole, type TypeSpec } from './scale.ts';

export function useTheme(): Theme {
  const theme = useContext(ThemeContext);
  if (!theme) throw new Error('useTheme must be used inside a ThemeProvider');
  return theme;
}

type NamedStyles<T> = StyleSheet.NamedStyles<T> | StyleSheet.NamedStyles<any>;

/**
 * `const useStyles = makeStyles((t) => ({ row: { backgroundColor: t.color.surface } }))`, then
 * `const s = useStyles()` inside the component.
 */
export function makeStyles<T extends NamedStyles<T>>(factory: (theme: Theme) => T): () => T {
  const cache = new WeakMap<Theme, T>();
  return function useStyles(): T {
    const theme = useTheme();
    let styles = cache.get(theme);
    if (!styles) {
      styles = StyleSheet.create(factory(theme));
      cache.set(theme, styles);
    }
    return styles;
  };
}

/** The tone names of S6's closed vocabulary (§3.3). */
export type Tone = 'success' | 'warning' | 'critical' | 'info' | 'neutral';
