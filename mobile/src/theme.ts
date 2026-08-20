// The Signal design system, ported from qvault/static/qvault.css.
//
// Same tokens, same three rules, adapted for a thumb rather than a mouse:
//
//   1. COLOUR NEVER DECORATES DATA. sealed / waiting / broken are the only saturated hues, and
//      each reports a state the reader must act on or trust. No brand accent on a button.
//   2. THE INTERFACE EXPLAINS NOTHING. Cryptographic fact appears as ordinary product metadata --
//      algorithm, fingerprint, custody, byte counts -- never as a lesson.
//   3. ONE MOMENT OF SCALE PER SCREEN. On a phone this matters more than on a console: the tally
//      on a decision, the fingerprint on the device screen, and nothing competing with it.
//
// Density is relaxed from the web's 38px rows -- a 38px row is not tappable -- but the type scale,
// palette and mono treatment are carried over unchanged so the two clients read as one product.
// The app is light-only, as the web app is. That is a commitment, not an omission: every surface
// below sets its colour explicitly rather than inheriting one.

import { Platform } from 'react-native';

export const color = {
  paper: '#FBFBF9',
  surface: '#FFFFFF',
  sunk: '#F5F5F2',
  sunk2: '#EFEFEB',
  rule: '#E2E2DC',
  rule2: '#EDEDE8',
  ink: '#16181C',
  ink2: '#4A4E56',
  ink3: '#6A6F78',

  // Achromatic on purpose: it gives the product a spine without introducing a hue that would
  // compete with status colour.
  chrome: '#15191C',
  chrome2: '#22282C',
  chromeRule: '#2B3237',
  chromeInk: '#ECEEED',
  chromeInk2: '#98A1A6',

  sealed: '#1B6B4F',
  sealedTint: '#EAF3EE',
  sealedLine: '#B9D8C8',
  waiting: '#8A5A12',
  waitingTint: '#FAF2E4',
  waitingLine: '#E8D4AC',
  broken: '#A82D20',
  brokenTint: '#FBECEA',
  brokenLine: '#EFC4BE',
} as const;

export const mono = Platform.select({
  ios: 'Menlo',
  android: 'monospace',
  default: 'monospace',
}) as string;

export const radius = 4;

export const space = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
} as const;

export const type = {
  figure: { fontFamily: mono, fontSize: 26, letterSpacing: -0.5, color: color.ink },
  title: { fontSize: 19, fontWeight: '600' as const, letterSpacing: -0.2, color: color.ink },
  heading: { fontSize: 15, fontWeight: '600' as const, color: color.ink },
  body: { fontSize: 14, color: color.ink, lineHeight: 20 },
  meta: { fontSize: 12.5, color: color.ink3 },
  // Uppercase micro-labels earn their letter-spacing; without it they read as shouting.
  label: {
    fontSize: 10.5,
    fontWeight: '600' as const,
    letterSpacing: 0.8,
    textTransform: 'uppercase' as const,
    color: color.ink3,
  },
  hash: { fontFamily: mono, fontSize: 11.5, color: color.ink2 },
} as const;

/** The three status hues, and the only place a saturated colour is allowed near a value. */
export type StatusTone = 'sealed' | 'waiting' | 'broken' | 'neutral';

export const tone: Record<StatusTone, { fg: string; bg: string; border: string }> = {
  sealed: { fg: color.sealed, bg: color.sealedTint, border: color.sealedLine },
  waiting: { fg: color.waiting, bg: color.waitingTint, border: color.waitingLine },
  broken: { fg: color.broken, bg: color.brokenTint, border: color.brokenLine },
  neutral: { fg: color.ink2, bg: color.sunk, border: color.rule },
};

/** Map a proposal status onto a tone. Open work is 'waiting', not 'neutral' -- it needs someone. */
export function statusTone(status: string): StatusTone {
  switch (status) {
    case 'approved':
      return 'sealed';
    case 'rejected':
    case 'expired':
      return 'broken';
    case 'open':
      return 'waiting';
    default:
      return 'neutral';
  }
}
