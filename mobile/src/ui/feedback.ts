// Tactile feedback.
//
// Haptics are rationed on the same principle as colour and elevation: if everything buzzes, the
// buzz stops carrying information. Three events earn one, and they are the three where something
// became true in the world rather than merely on screen.
//
//   sealed   -- a signature was accepted and the quorum is now met. The heaviest feedback the
//               product gives, because it is the only irreversible thing a person can do here.
//   signed   -- a signature was accepted. Something real happened, but the decision is still open.
//   refused  -- the app declined to sign, or the server rejected what we sent.
//
// Scrolling, navigating, opening a sheet and changing a tab get nothing. A phone that responds
// physically to navigation feels eager; this product should feel composed.

import * as Haptics from 'expo-haptics';

/** Fire and forget. A device without a taptic engine, or one in silent-with-haptics-off, throws. */
function safely(run: () => Promise<void>) {
  void run().catch(() => {});
}

export const feedback = {
  sealed() {
    safely(() => Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success));
  },
  signed() {
    safely(() => Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium));
  },
  refused() {
    safely(() => Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning));
  },
};
