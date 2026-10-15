// The phone's own view of the network (phone-ux §2.6, §10.2 N6), from NetInfo when the binary has
// it. It only makes src/connectivity.ts quicker; it never replaces it:
//
//   - Losing the network shows the offline bar at once, instead of after the next failed request.
//   - Getting it back refetches what is on screen (not while the OS's authentication prompt is up,
//     as for focus), and that answer is what clears the bar: only Q-Vault answering proves Q-Vault
//     can be reached.
//
// Deliberately NOT React Query's onlineManager, which the spec first named. Told "offline", it
// pauses every query and mutation instead of failing them: "Raise" would sit spinning and then send
// the decision by itself whenever the phone reconnected, and "Checking…" before a signature would
// wait with no end. Failing at once, as every screen already handles, is the honest behaviour.
//
// NetInfo's own reachability check (requests to a Google address) is switched off: the operating
// system's connection state is enough, and a signing app should not call anyone but its server.

import type { QueryClient } from '@tanstack/react-query';

import { authPromptInFlight } from '../authPrompt.ts';
import { reportUnreachable } from '../connectivity.ts';
import { onlineFromNetInfo } from '../logic/network.ts';
import { hasReactNativeModule, optional } from './optional.ts';

type NetInfoModule = typeof import('@react-native-community/netinfo').default;

const netinfo = optional<NetInfoModule>(
  () => hasReactNativeModule('RNCNetInfo'),
  () => (require('@react-native-community/netinfo') as typeof import('@react-native-community/netinfo')).default,
);

let unsubscribe: (() => void) | null = null;

/** Start listening, once for the life of the app. False where the binary has no NetInfo. */
export function wireNetInfo(client: QueryClient): boolean {
  if (unsubscribe) return true;
  const n = netinfo();
  if (!n) return false;
  try {
    n.configure({ reachabilityShouldRun: () => false });
    let online: boolean | null = null;
    unsubscribe = n.addEventListener((state) => {
      const next = onlineFromNetInfo(state);
      const was = online;
      online = next;
      if (!next) {
        reportUnreachable();
      } else if (was === false && !authPromptInFlight()) {
        void client.refetchQueries({ type: 'active' });
      }
    });
    return true;
  } catch {
    unsubscribe = null;
    return false;
  }
}
