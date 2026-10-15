// Copy (phone-ux §10.2 N11): the clipboard when the binary has expo-clipboard, otherwise React
// Native's Share sheet, which offers Copy among its targets.
//
// Feedback: Android 13 and later confirm a copy themselves, so nothing is added there; older
// Android gets a short system toast, which shows above an open sheet. A screen reader hears
// "Copied" either way.

import { AccessibilityInfo, Platform, Share, ToastAndroid } from 'react-native';

import { hasExpoModule, optional } from './optional.ts';

type ClipboardModule = typeof import('expo-clipboard');

const clipboard = optional<ClipboardModule>(
  () => hasExpoModule('ExpoClipboard'),
  () => require('expo-clipboard') as ClipboardModule,
);

/** True when Copy puts the text on the clipboard rather than opening the share sheet. */
export function canCopy(): boolean {
  return clipboard() !== null;
}

/**
 * Copy `text`. 'copied': it is on the clipboard. 'shared': the share sheet opened instead (the
 * person may still have chosen Copy there). 'failed': neither worked, so the caller should show
 * the whole value for the person to select.
 */
export async function copyText(text: string): Promise<'copied' | 'shared' | 'failed'> {
  const c = clipboard();
  if (c) {
    try {
      await c.setStringAsync(text);
      if (Platform.OS === 'android' && Number(Platform.Version) < 33) {
        ToastAndroid.show('Copied', ToastAndroid.SHORT);
      }
      AccessibilityInfo.announceForAccessibility('Copied');
      return 'copied';
    } catch {
      // Fall through to the share sheet.
    }
  }
  try {
    await Share.share({ message: text });
    return 'shared';
  } catch {
    return 'failed';
  }
}
