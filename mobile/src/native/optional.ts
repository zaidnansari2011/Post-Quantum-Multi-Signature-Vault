// The rework APK's native modules, loaded only where the binary has them (phone-ux §10.2).
//
// Everything in src/native/ goes through here, so a build without a module (Expo Go, a development
// build made before the rework APK, the web screenshot harness) takes the caller's fallback instead
// of crashing on "Cannot find native module". The check runs BEFORE the package's JavaScript is
// loaded, because most of these packages look up their native half the moment they are imported:
//
//   - an Expo module: `requireOptionalNativeModule(name)` is null when the binary lacks it;
//   - a React Native community module: `TurboModuleRegistry.get(name)`, also null when missing.
//
// On the web every check is false: the harness renders the fallbacks, and loads none of these.
// tests/test_mobile_native_surface.py holds every APK-only package to this folder.

import { NativeModules, Platform, TurboModuleRegistry } from 'react-native';
import { requireOptionalNativeModule } from 'expo';

const native = Platform.OS === 'android' || Platform.OS === 'ios';

/** The binary carries this Expo module ("ExpoClipboard", "ExpoDevice"…). */
export function hasExpoModule(name: string): boolean {
  if (!native) return false;
  try {
    return requireOptionalNativeModule(name) != null;
  } catch {
    return false;
  }
}

/** The binary carries this React Native module ("RNCNetInfo", "RNCDatePicker"). */
export function hasReactNativeModule(name: string): boolean {
  if (!native) return false;
  try {
    return TurboModuleRegistry.get(name) != null || NativeModules[name] != null;
  } catch {
    return false;
  }
}

/** `load()` once, if `present`; null when absent or when loading throws. */
export function optional<T>(present: () => boolean, load: () => T): () => T | null {
  let loaded: { value: T | null } | null = null;
  return () => {
    if (loaded) return loaded.value;
    let value: T | null = null;
    try {
      value = present() ? load() : null;
    } catch {
      value = null;
    }
    loaded = { value };
    return value;
  };
}
