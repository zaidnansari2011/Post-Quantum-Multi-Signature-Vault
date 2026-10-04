// Web screenshot harness ONLY (see ../metro.config.js). expo-secure-store has no web
// implementation, so this keeps the same API over localStorage. NOT secure -- it exists so the
// enrolled screens can render in a browser for design review.

export type SecureStoreOptions = Record<string, unknown>;
export const WHEN_UNLOCKED_THIS_DEVICE_ONLY = 'WHEN_UNLOCKED_THIS_DEVICE_ONLY';
export const WHEN_UNLOCKED = 'WHEN_UNLOCKED';

const PREFIX = 'webshots.securestore.';

export async function isAvailableAsync(): Promise<boolean> {
  return true;
}

export async function setItemAsync(key: string, value: string, _options?: SecureStoreOptions) {
  window.localStorage.setItem(PREFIX + key, value);
}

export async function getItemAsync(key: string, _options?: SecureStoreOptions) {
  return window.localStorage.getItem(PREFIX + key);
}

export async function deleteItemAsync(key: string, _options?: SecureStoreOptions) {
  window.localStorage.removeItem(PREFIX + key);
}
