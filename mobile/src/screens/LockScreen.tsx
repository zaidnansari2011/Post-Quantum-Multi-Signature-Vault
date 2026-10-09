// "Q-Vault is locked" (phone-ux §6.1). The prompt runs once by itself as the screen appears; after
// that, only from the button.
//
// Drawn twice over, because the app has more than one top: the root shows it in a full-screen RN
// `<Modal>` mounted last (`LockModal`), and a native modal form (New decision, New vault), which
// iOS presents above the root, draws it over itself (`LockGate`), keeping its draft. Sheets and the
// acknowledgement close themselves (src/lockState.ts). Screen readers reach nothing underneath.

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Modal, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button, Icon, InlineMessage, Text } from '../ui/index.tsx';
import { useAppLocked } from '../ui/lock.ts';
import { makeStyles, useTheme } from '../theme/index.ts';
import { useAppLock } from '../appLock.tsx';
import { useSigningMethod } from '../signingMethod.ts';

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
        {/* The method names the button's job, not the verb twice ("Unlock with face unlock"). */}
        <Button label="Unlock" icon="fingerprint" onPress={() => void unlock()} busy={busy} full />
        {method ? (
          <Text role="caption" tone="muted" align="center">
            {`Uses ${method.name}.`}
          </Text>
        ) : null}
      </View>
    </SafeAreaView>
  );
}

/** The root's lock: a full-screen Modal, so it draws above every other window the app has. */
export function LockModal({ locked, covered }: { locked: boolean; covered: boolean }) {
  const s = useStyles();
  const t = useTheme();
  return (
    <Modal
      visible={locked || covered}
      animationType="none"
      presentationStyle="fullScreen"
      statusBarTranslucent
      // Back does not dismiss the lock.
      onRequestClose={() => {}}
    >
      {locked ? (
        <LockScreen />
      ) : (
        <View style={s.plain} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
          <Icon name="mark" size={48} color={t.color.accent} />
        </View>
      )}
    </Modal>
  );
}

/**
 * For a modal screen iOS presents above the root (New decision, New vault): while the app is
 * locked, its content is hidden from screen readers and the lock is drawn over it. The draft is
 * kept: the form stays mounted underneath.
 */
export function LockGate({ children }: { children: ReactNode }) {
  const s = useStyles();
  const locked = useAppLocked();
  return (
    <View style={s.flex}>
      <View
        style={s.flex}
        accessibilityElementsHidden={locked}
        importantForAccessibility={locked ? 'no-hide-descendants' : 'auto'}
        pointerEvents={locked ? 'none' : 'auto'}
      >
        {children}
      </View>
      {locked ? <LockScreen /> : null}
    </View>
  );
}

const useStyles = makeStyles((t) => ({
  flex: { flex: 1 },
  cover: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, zIndex: 100, backgroundColor: t.color.bg },
  centre: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: t.space[16], paddingHorizontal: t.layout.gutter },
  bottom: { paddingHorizontal: t.layout.gutter, paddingBottom: t.space[24], gap: t.space[8] },
  plain: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: t.color.bg },
}));
