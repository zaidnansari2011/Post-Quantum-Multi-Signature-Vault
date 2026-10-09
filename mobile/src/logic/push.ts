// Phone push: what the app decides about it, apart from the native module (plan R8, phone-ux §6.23).
//
// Pure, so tools/push_probe.ts runs every case without a handset:
//
//   - `pushState` folds three facts (does the server send pushes, what did the person allow, does
//     the server hold this phone's token) into the one state the Account page shows.
//   - `shouldPrime` is §6.2 step 3's rule: the OS permission is asked only from the primer's own
//     button, once, after enrolment, and never at launch.
//   - `FOREGROUND` is what a push does while Q-Vault is open: no banner, no sound; the app refetches
//     instead (HIG, §6.23).
//   - `CHANNELS` are the Android channels the server names in `channelId` (delivery_copy.PUSH_GROUPS
//     on the server; tests/test_mobile_push.py holds the two lists together).
//
// Nothing here signs: a push opens a screen (src/logic/links.ts `targetFromPush`), and no
// notification category with action buttons is ever registered (I-12).
//
// No React Native import.

/** The OS permission, as expo-notifications reports it, or `unavailable` (web, Expo Go). */
export type PushPermission = 'granted' | 'denied' | 'undetermined' | 'unavailable';

export type PushState =
  /** The server sends no pushes, or this build cannot receive them. */
  | 'unavailable'
  /** Allowed, and the server holds this phone's token. */
  | 'on'
  /** Allowed, but the server has no token yet (registration pending or failed): retried. */
  | 'registering'
  /** Never asked. */
  | 'off'
  /** The person said no; only system settings can change it. */
  | 'blocked';

export function pushState(args: {
  serverAvailable: boolean;
  permission: PushPermission;
  registered: boolean;
}): PushState {
  if (!args.serverAvailable || args.permission === 'unavailable') return 'unavailable';
  if (args.permission === 'denied') return 'blocked';
  if (args.permission === 'undetermined') return 'off';
  return args.registered ? 'on' : 'registering';
}

/** §6.2 step 3: shown once, after enrolment, only where a push could arrive and nobody asked yet. */
export function shouldPrime(args: {
  serverAvailable: boolean;
  permission: PushPermission;
  primedBefore: boolean;
}): boolean {
  return args.serverAvailable && args.permission === 'undetermined' && !args.primedBefore;
}

export type AccountLine = {
  value: string;
  caption: string | null;
  /** What the row's button does: ask for the permission, open system settings, or nothing. */
  action: 'ask' | 'settings' | null;
  actionLabel: string | null;
};

/** The Notifications row on Account (§6.18): "On" or "Off", and the one thing that changes it. */
export function accountLine(state: PushState): AccountLine {
  switch (state) {
    case 'on':
      return { value: 'On', caption: null, action: null, actionLabel: null };
    case 'registering':
      return {
        value: 'On',
        caption: 'Connecting this phone to Q-Vault. It tries again each time the app opens.',
        action: null,
        actionLabel: null,
      };
    case 'off':
      return {
        value: 'Off',
        caption: "You'll only see new decisions when you open Q-Vault.",
        action: 'ask',
        actionLabel: 'Turn on notifications',
      };
    case 'blocked':
      return {
        value: 'Off',
        caption: "Notifications are off for Q-Vault in this phone's settings.",
        action: 'settings',
        actionLabel: 'Turn on in Settings',
      };
    case 'unavailable':
      return {
        value: 'Not set up',
        caption: 'Q-Vault will notify this phone once notifications are set up. For now, new decisions show in Approvals.',
        action: null,
        actionLabel: null,
      };
  }
}

/** While Q-Vault is open, a push shows nothing: the item is inserted and the badge moves (§6.23). */
export const FOREGROUND = {
  shouldShowBanner: false,
  shouldShowList: false,
  shouldPlaySound: false,
  shouldSetBadge: false,
} as const;

export type Importance = 'high' | 'default';

/** One Android channel per group (§6.23). Lock-screen visibility is private on every one. */
export const CHANNELS: ReadonlyArray<{ id: string; name: string; importance: Importance }> = [
  { id: 'needs_you', name: 'Needs your signature', importance: 'high' },
  { id: 'updates', name: 'Updates', importance: 'default' },
  { id: 'security', name: 'Security', importance: 'high' },
];

/** The Notifications page's groups, as the server sends them; security is locked on. */
export type PushGroup = { id: string; label: string; enabled: boolean; locked: boolean };

/** Whether a switch may be flipped from the phone: never security's. */
export function canToggle(group: PushGroup): boolean {
  return !group.locked && group.id !== 'security';
}
