// The platform date picker for New decision's "Pick a day…" (phone-ux §6.16, §10.2 N16): the
// Material date dialog on Android, from @react-native-community/datetimepicker when the binary has
// it. Not on a screen yet: until New decision offers the chip, the four deadline chips stand alone
// (P3), and where this returns false they still do.

import { Platform } from 'react-native';

import { hasReactNativeModule, optional } from './optional.ts';

type PickerModule = typeof import('@react-native-community/datetimepicker');

const picker = optional<PickerModule>(
  () => Platform.OS === 'android' && hasReactNativeModule('RNCDatePicker'),
  () => require('@react-native-community/datetimepicker') as PickerModule,
);

/** True where "Pick a day…" can open the platform's date dialog. */
export function canPickDate(): boolean {
  return picker() !== null;
}

/** Open the date dialog; the chosen day, or null when it was dismissed or cannot open. */
export function pickDate(options: { value: Date; minimumDate: Date; maximumDate: Date }): Promise<Date | null> {
  const p = picker();
  if (!p) return Promise.resolve(null);
  return new Promise((resolve) => {
    try {
      p.DateTimePickerAndroid.open({
        ...options,
        mode: 'date',
        onChange: (event, date) => resolve(event.type === 'set' && date ? date : null),
      });
    } catch {
      resolve(null);
    }
  });
}
