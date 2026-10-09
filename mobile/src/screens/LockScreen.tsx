// "Q-Vault is locked" (phone-ux §6.1): drawn over everything while app lock holds the app. The
// prompt runs once by itself as the screen appears; after that, only from the button.

import { useEffect, useRef, useState } from 'react';
import { View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button, Icon, InlineMessage, Text } from '../ui/index.tsx';
import { makeStyles, useTheme } from '../theme/index.ts';
import { useAppLock } from '../appLock.tsx';
import { useSigningMethod } from '../signingMethod.ts';
import { methodButton } from '../logic/methodLabel.ts';

export default function LockScreen() {
  const s = useStyles();
  const t = useTheme();
  const lock = useAppLock();
  const method = useSigningMethod();
  const [busy, setBusy] = useState(false);
  const [cancelled, setCancelled] = useState(false);
  const asked = useRef(false);

  const unlock = async () => {
    if (busy) return;
    setBusy(true);
    const ok = await lock.unlock();
    setBusy(false);
    setCancelled(!ok);
  };

  useEffect(() => {
    if (asked.current) return;
    asked.current = true;
    void unlock();
    // Once, on appearance.
  }, []);

  return (
    <SafeAreaView style={s.cover} edges={['top', 'bottom']}>
      <View style={s.centre} accessibilityViewIsModal>
        <Icon name="mark" size={48} color={t.color.accent} />
        <Text role="title" accessibilityRole="header" align="center">
          Q-Vault is locked
        </Text>
        {cancelled ? <InlineMessage tone="neutral" text="Still locked. Nothing on this phone has changed." /> : null}
      </View>
      <View style={s.bottom}>
        <Button label={methodButton('Unlock', method)} onPress={() => void unlock()} busy={busy} full />
      </View>
    </SafeAreaView>
  );
}

const useStyles = makeStyles((t) => ({
  cover: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, zIndex: 100, backgroundColor: t.color.bg },
  centre: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: t.space[16], paddingHorizontal: t.layout.gutter },
  bottom: { paddingHorizontal: t.layout.gutter, paddingBottom: t.space[24] },
}));
