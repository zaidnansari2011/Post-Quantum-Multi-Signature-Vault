// Tactile feedback, rationed (phone-ux §7.2).
//
// If everything buzzes, the buzz stops carrying information. Four events earn one: a signature
// that met the rule (`sealed`), a signature recorded (`signed`), a refusal (`refused`, an integrity
// failure or a server refusal; a network failure while signing too), and a chip or segment changing
// (`selection`). Navigation, scrolling, opening a sheet and changing tabs get nothing. Raising a
// decision and creating a vault should get nothing either (§7.2); the two forms still call
// `signed()` until P3 rebuilds them. A cancelled biometric gets nothing: the person chose it.
//
// Android goes through the device haptics engine (`performAndroidHapticsAsync`), which needs no
// VIBRATE permission; iOS honours the system switch, so there is no in-app setting.

import { Platform } from 'react-native';
import * as Haptics from 'expo-haptics';

/** Fire and forget. A device without a haptic engine, or with haptics off, throws. */
function safely(run: () => Promise<void>) {
  void run().catch(() => {});
}

const android = Platform.OS === 'android';

export const feedback = {
  sealed() {
    safely(() =>
      android
        ? Haptics.performAndroidHapticsAsync(Haptics.AndroidHaptics.Confirm)
        : Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success),
    );
  },
  signed() {
    safely(() =>
      android
        ? Haptics.performAndroidHapticsAsync(Haptics.AndroidHaptics.Confirm)
        : Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium),
    );
  },
  refused() {
    safely(() =>
      android
        ? Haptics.performAndroidHapticsAsync(Haptics.AndroidHaptics.Reject)
        : Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error),
    );
  },
  selection() {
    safely(() =>
      android
        ? Haptics.performAndroidHapticsAsync(Haptics.AndroidHaptics.Segment_Tick)
        : Haptics.selectionAsync(),
    );
  },
};
