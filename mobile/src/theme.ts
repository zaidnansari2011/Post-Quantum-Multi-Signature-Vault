// The design system for the handset client.
//
// This is deliberately NOT a port of qvault.css. The web console and this app share a product and
// a vocabulary of *state*, but they are different instruments: a console is read by someone
// sitting down to administer a system, and this is read by someone deciding something between two
// other things. The previous version of this file ported the web tokens directly and inherited
// three console habits that do not survive the move -- uppercase tracked micro-labels, a monospace
// face for ordinary labels, and metadata joined with middle dots. Together those are most of the
// reason the app read as a data dump rather than as a product.
//
// WHAT CARRIES OVER, because it is semantic rather than decorative:
//
//   COLOUR NEVER DECORATES DATA. `sealed` / `waiting` / `broken` are the only saturated hues in
//   the system, and each reports a state someone must act on or trust. There is no brand accent,
//   and no button is coloured to attract a tap.
//
// WHAT CHANGED, and why:
//
//   1. THE NEUTRALS ARE COOL, NOT WARM. The web's #FBFBF9 paper over #16181C ink is a warm-grey
//      pairing. Here the ink is a navy (#16233A) -- a hue, chosen, rather than a black with a tint
//      stirred into it -- and the paper is cooled to meet it. The register is institutional: a
//      private bank, a chambers, a document you countersign.
//
//   2. TWO FACES, A JOB EACH. Source Serif 4 sets the decision itself, because the decision IS a
//      document and should read like one. Public Sans sets every piece of interface around it. The
//      split is functional: a reader can tell at a glance what is the thing being signed and what
//      is apparatus describing it.
//
//   3. MONO IS FOR HASHES ONLY. A monospace face on a label is costume. On a fingerprint it is
//      doing real work, because the reader is comparing characters one at a time against another
//      screen. Restricting it to that is what makes it mean something when it appears.
//
//   4. RADIUS AND SHADOW ARE NOT UNIFORM. One corner radius and one soft grey shadow on everything
//      is what makes an interface read as a card kit. Here elevation is scarce -- it marks the two
//      surfaces that genuinely float above the page, and nothing else. Flat surfaces are separated
//      by rules instead.

import { Platform } from 'react-native';

export const color = {
  // Page and surfaces. The blue in the ink is carried through the neutrals at low saturation, so a
  // white card sits on the page rather than glowing out of it.
  paper: '#F7F8FA',
  surface: '#FFFFFF',
  sunk: '#EFF1F5',
  sunk2: '#E7EAF0',
  rule: '#DDE1E9',
  rule2: '#EBEEF3',

  // Text. A navy rather than a tinted black: at roughly 13:1 on white it is as readable as black,
  // and it gives the product a temperature.
  ink: '#16233A',
  ink2: '#4A5568',
  ink3: '#6B7688',
  ink4: '#8D97A8',

  // Chrome: the tab bar, and any dark surface. Deeper and bluer than the body ink, so the two can
  // never look like a failed attempt at the same colour.
  chrome: '#0E1729',
  chrome2: '#1B2740',
  chromeRule: '#293552',
  chromeInk: '#EEF1F6',
  chromeInk2: '#93A0B8',

  // The status triad, unchanged from the web client. These values are semantic across the whole
  // project -- the ledger, the record export and the console all use them -- so they stay put.
  sealed: '#1B6B4F',
  sealedTint: '#E8F2EC',
  sealedLine: '#B4D5C4',
  waiting: '#8A5A12',
  waitingTint: '#FAF2E3',
  waitingLine: '#E7D3AA',
  broken: '#A82D20',
  brokenTint: '#FBEBE9',
  brokenLine: '#EEC2BC',
} as const;

export const mono = Platform.select({
  ios: 'Menlo',
  android: 'monospace',
  default: 'monospace',
}) as string;

/** Font families, as @expo-google-fonts names them once `useAppFonts` has resolved. */
export const font = {
  serif: 'SourceSerif4_400Regular',
  serifSemi: 'SourceSerif4_600SemiBold',
  sans: 'PublicSans_400Regular',
  sansMedium: 'PublicSans_500Medium',
  sansSemi: 'PublicSans_600SemiBold',
} as const;

/**
 * Corner radii, scaled by how much the surface wants to be picked up.
 *
 * Not one value everywhere. A sheet rising from the bottom edge reads as a physical panel and can
 * carry a large corner; a chip is small enough that anything above 4 turns it into a pill it is
 * not meant to be.
 */
export const radius = {
  chip: 4,
  card: 10,
  control: 12,
  sheet: 20,
} as const;

export const space = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
  xxxl: 48,
} as const;

/**
 * The type scale.
 *
 * `decision` is the only size above 20 in ordinary use, and that is what makes it the moment of
 * scale on the screen where it appears. Nothing competes with it -- in particular the quorum is
 * drawn as marks rather than set as large type, so the two never fight for the same attention.
 */
export const type = {
  // The decision itself. Serif, generous leading: this is the sentence someone is being asked to
  // put their name to, and it should be possible to read it slowly.
  decision: { fontFamily: font.serif, fontSize: 25, lineHeight: 34, color: color.ink },
  decisionSm: { fontFamily: font.serif, fontSize: 17, lineHeight: 25, color: color.ink },

  // Interface chrome.
  title: { fontFamily: font.sansSemi, fontSize: 20, lineHeight: 26, color: color.ink },
  heading: { fontFamily: font.sansSemi, fontSize: 15, lineHeight: 21, color: color.ink },
  body: { fontFamily: font.sans, fontSize: 15, lineHeight: 22, color: color.ink },
  bodyMuted: { fontFamily: font.sans, fontSize: 15, lineHeight: 22, color: color.ink2 },
  meta: { fontFamily: font.sans, fontSize: 13, lineHeight: 18, color: color.ink3 },
  micro: { fontFamily: font.sans, fontSize: 12, lineHeight: 16, color: color.ink3 },
  action: { fontFamily: font.sansSemi, fontSize: 15, lineHeight: 20, color: color.ink },

  // Mono, for values a reader compares character by character, and nothing else.
  hash: { fontFamily: mono, fontSize: 12.5, lineHeight: 18, color: color.ink2 },
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

/**
 * Elevation, used twice in the whole app.
 *
 * A shadow here means "this surface is above the page, and the page is still there underneath" --
 * the action bar pinned over a scrolling decision, and the confirm sheet. Putting it on every card
 * would spend the signal on decoration and leave nothing to say this with.
 */
export const elevation = {
  bar: Platform.select({
    ios: {
      shadowColor: '#0E1729',
      shadowOpacity: 0.08,
      shadowRadius: 12,
      shadowOffset: { width: 0, height: -2 },
    },
    android: { elevation: 12 },
    default: {},
  }),
  sheet: Platform.select({
    ios: {
      shadowColor: '#0E1729',
      shadowOpacity: 0.18,
      shadowRadius: 28,
      shadowOffset: { width: 0, height: -8 },
    },
    android: { elevation: 24 },
    default: {},
  }),
} as const;

/**
 * Motion tokens.
 *
 * Durations are short because nearly every animation in this app answers something the person just
 * did; there is no ambient motion to pace. The exception is `seal`, the single orchestrated moment
 * in the product, which is allowed to take its time: it marks the instant a decision becomes
 * irreversible, and an irreversible thing should not happen in 150ms.
 */
export const motion = {
  instant: 120,
  quick: 180,
  settle: 260,
  seal: 620,
  /** No overshoot, for surfaces. Overshoot on a sheet reads as bounce rather than weight. */
  surface: { damping: 26, stiffness: 240, mass: 1 },
  /** A little overshoot. Used ONLY on the seal. */
  emphatic: { damping: 13, stiffness: 190, mass: 0.9 },
} as const;
