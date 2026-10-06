// The phone's own type, space, radius, motion and elevation (phone-ux §4, §7.1).
//
// Colours and motion durations come from the web's tokens.css (tokens.generated.ts). Everything
// here is the phone's: the web's 14px body suits a mouse at arm's length, a phone at reading
// distance wants 16. The token NAMES match the web's, so a component reads the same in both
// codebases; the VALUES are the phone's.
//
// This file is the only place outside the generated tokens where a font size is written as a
// number. tests/test_mobile_structure.py fails on any `fontSize` elsewhere that is not one of these.

import { Platform, type ViewStyle } from 'react-native';

import type { ColorTokens } from './tokens.generated.ts';
import { motionTokens } from './tokens.generated.ts';

/** Font family names, as @expo-google-fonts registers them once `useAppFonts` has resolved. */
export const fontFamily = {
  sans: 'PublicSans_400Regular',
  sansMedium: 'PublicSans_500Medium',
  sansSemi: 'PublicSans_600SemiBold',
  serif: 'SourceSerif4_400Regular',
  mono: 'JetBrainsMono_400Regular',
  monoMedium: 'JetBrainsMono_500Medium',
  icons: 'QVaultIcons',
} as const;

export type TypeRole =
  | 'caption'
  | 'label'
  | 'body'
  | 'bodyStrong'
  | 'titleSm'
  | 'title'
  | 'figure'
  | 'decisionHero'
  | 'decision'
  | 'code'
  | 'codeDisplay';

export type TypeSpec = {
  fontFamily: string;
  fontSize: number;
  lineHeight: number;
  letterSpacing?: number;
  /** Tabular figures: every amount, count and time (§4.1). */
  tabular?: boolean;
  /**
   * The largest multiple of its size this role reaches at large text (§4.3). `null` means no cap:
   * the signed text grows with the system, and steps down to `decision` at 1.3x instead.
   */
  maxScale: number | null;
};

/** §4.1. Line heights follow iOS's text metrics on a 2pt grid. */
export const typeScale: Record<TypeRole, TypeSpec> = {
  caption: { fontFamily: fontFamily.sans, fontSize: 13, lineHeight: 18, maxScale: 2 },
  label: { fontFamily: fontFamily.sansMedium, fontSize: 12, lineHeight: 16, maxScale: 1.6 },
  body: { fontFamily: fontFamily.sans, fontSize: 16, lineHeight: 24, maxScale: 2 },
  bodyStrong: { fontFamily: fontFamily.sansSemi, fontSize: 16, lineHeight: 22, maxScale: 2 },
  titleSm: { fontFamily: fontFamily.sansSemi, fontSize: 17, lineHeight: 22, maxScale: 2 },
  title: {
    fontFamily: fontFamily.sansSemi,
    fontSize: 24,
    lineHeight: 30,
    letterSpacing: -0.2,
    maxScale: 1.6,
  },
  figure: {
    fontFamily: fontFamily.sansSemi,
    fontSize: 28,
    lineHeight: 34,
    letterSpacing: -0.3,
    tabular: true,
    maxScale: 1.6,
  },
  decisionHero: { fontFamily: fontFamily.serif, fontSize: 22, lineHeight: 30, maxScale: null },
  decision: { fontFamily: fontFamily.serif, fontSize: 18, lineHeight: 28, maxScale: null },
  code: { fontFamily: fontFamily.mono, fontSize: 14, lineHeight: 20, maxScale: 2 },
  codeDisplay: {
    fontFamily: fontFamily.monoMedium,
    fontSize: 22,
    lineHeight: 28,
    letterSpacing: 1,
    maxScale: 1.6,
  },
};

/** Caps that depend on where a role is used rather than on the role (§4.3). */
export const scaleCap = {
  button: 1.6,
  navTitle: 1.4,
  tab: 1.3,
  badge: 1.6,
} as const;

/** Thresholds where layouts change shape at large text (§4.3, §5.3, §5.6). */
export const breakpoints = {
  /** The signed text steps down from decisionHero to decision. */
  decisionStepDown: 1.3,
  /** Rows, the action bar and segmented controls stack. */
  stacked: 1.6,
  /** The action bar also stacks on a window narrower than this. */
  narrowWidth: 340,
} as const;

/** Named by value (§4.4): space[16], never space.lg. */
export const space = {
  2: 2,
  4: 4,
  8: 8,
  12: 12,
  16: 16,
  20: 20,
  24: 24,
  32: 32,
  40: 40,
  48: 48,
} as const;

/** Gutters are 16 everywhere, sheets included; content is capped at 600 on tablets (§4.4). */
export const layout = { gutter: 16, maxContent: 600, hitMin: 48, maxSlop: 12 } as const;

/** By role (§4.5). A control inside a card keeps 10: child never exceeds parent. */
export const radius = { badge: 4, control: 10, card: 12, sheet: 20, full: 999 } as const;

/** §7.1: shared durations, plus the springs and the one looping motion the phone owns. */
export const motion = {
  ...motionTokens,
  /** No overshoot, for surfaces. */
  surface: { damping: 26, stiffness: 240, mass: 1 },
  /** A little overshoot. The seal only. */
  emphatic: { damping: 13, stiffness: 190, mass: 0.9 },
  /** The skeleton waits this long before appearing, so a fast answer never flashes one. */
  skeletonDelay: 150,
  /** One full breath of the skeleton, 0.55 -> 1 -> 0.55. */
  skeletonBreath: 1600,
  toast: 4000,
} as const;

export type Elevation = { bar: ViewStyle; sheet: ViewStyle };

/**
 * Only the sheet and the action bar are elevated (§4.5). In dark mode they step lighter instead,
 * with a hairline and no shadow (Carbon layering, S25): a shadow on near-black reads as nothing.
 */
export function elevationFor(scheme: 'light' | 'dark', color: ColorTokens): Elevation {
  if (scheme === 'dark') return { bar: {}, sheet: {} };
  const shadow = (opacity: number, radius_: number, y: number, android: number): ViewStyle =>
    Platform.select<ViewStyle>({
      ios: {
        shadowColor: color.shadow,
        shadowOpacity: opacity,
        shadowRadius: radius_,
        shadowOffset: { width: 0, height: y },
      },
      android: { elevation: android, shadowColor: color.shadow },
      default: {
        shadowColor: color.shadow,
        shadowOpacity: opacity,
        shadowRadius: radius_,
        shadowOffset: { width: 0, height: y },
      },
    }) ?? {};
  return { bar: shadow(0.08, 12, -2, 12), sheet: shadow(0.18, 28, -8, 24) };
}
