// What NetInfo's state means for the offline bar (phone-ux §2.6). Only a definite "not connected"
// counts as offline: an unknown state (null, at start-up) is left to the requests themselves.
//
// No React Native import: tools/native_probe.ts runs it.

export function onlineFromNetInfo(state: { isConnected: boolean | null }): boolean {
  return state.isConnected !== false;
}
