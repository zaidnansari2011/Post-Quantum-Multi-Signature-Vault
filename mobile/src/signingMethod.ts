// The way this phone confirms it's you, named for the sign button (phone-ux §5.13): read once from
// the lock the phone reports and the biometric hardware it lists, then mapped by the pure
// `signingMethod` in src/logic/methodLabel.ts.

import { useEffect, useState } from 'react';
import { Platform } from 'react-native';

import * as keystore from './keystore.ts';
import { signingMethod, type Method } from './logic/methodLabel.ts';

/** Null while it is being read, or when the phone has no lock (it then cannot sign, I-9). */
export function useSigningMethod(): Method | null {
  const [method, setMethod] = useState<Method | null>(null);
  useEffect(() => {
    let cancelled = false;
    Promise.all([keystore.detectProtection(), keystore.supportedHardware()])
      .then(([protection, hardware]) => {
        const platform = Platform.OS === 'ios' || Platform.OS === 'android' ? Platform.OS : 'web';
        if (!cancelled) setMethod(signingMethod(protection, hardware, platform));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);
  return method;
}
