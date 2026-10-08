// Session ended, device removed, key missing (phone-ux §6.20).
//
// A 401 never deletes the key (I-3): this screen is shown with the key still on the phone, and
// nothing is deleted until the person chooses "Set up this phone again", after being told what that
// does. Until the server can re-authenticate an existing device (A9), setting up again is the only
// way back, and it makes a new key: the copy says so rather than offering a "Sign in" that would
// quietly do the same.
//
// Every 401 today is the server's plain `token_invalid` (expired, revoked and unknown alike), so the
// session-ended copy is the one shown; `device_revoked` gets its own once A9 sends it. A link that
// arrived meanwhile is kept, and opens once the phone is set up again (§2.4).

import { useState } from 'react';
import { View } from 'react-native';

import { Button, Icon, Screen, Scroll, Text } from '../ui/index.tsx';
import { makeStyles, useTheme } from '../theme/index.ts';
import { useSession, type Ended } from '../session.tsx';

const COPY: Record<Ended, { title: string; body: string; caption: string | null }> = {
  session: {
    title: 'Your session on this phone ended',
    body: 'Your key stays on this phone. To keep approving here, set the phone up again with your email and password.',
    caption:
      "Setting up again makes a new key on this phone. The old one can't sign without a session, and stays listed on the web until you remove it there.",
  },
  revoked: {
    title: 'This phone was removed from your account',
    body: "Its key can't sign any more. To approve from this phone, set it up again.",
    caption: null,
  },
  key_missing: {
    title: 'This phone no longer holds its signing key',
    body: 'Set it up again to approve here.',
    caption: 'The old key stays listed on the web until you remove it there.',
  },
  key_unusable: {
    title: "This phone's key can't sign any more",
    body: "Q-Vault didn't accept a signature from it. Set this phone up again to approve here.",
    caption: 'Setting up again deletes the old key from this phone and makes a new one.',
  },
};

export default function SessionEndedScreen() {
  const s = useStyles();
  const t = useTheme();
  const { ended, setUpAgain, retrySession, identity, token } = useSession();
  const [busy, setBusy] = useState(false);
  const copy = COPY[ended ?? 'session'];
  // Back to the app to ask the server again: after a session that may only have blipped, or a
  // refused signature. Never when the seed itself has gone: there is nothing to retry with.
  const canRetry = (ended === 'session' || ended === 'key_unusable') && !!identity && !!token;

  return (
    <Screen edges={['top', 'bottom']}>
      <Scroll>
        <View style={s.body}>
          <View style={[s.mark, { backgroundColor: t.color.fill }]}>
            <Icon name="key" size={28} color={t.color.textMuted} />
          </View>
          <Text role="title" accessibilityRole="header">
            {copy.title}
          </Text>
          <Text role="body">{copy.body}</Text>
          {copy.caption ? (
            <Text role="caption" tone="muted">
              {copy.caption}
            </Text>
          ) : null}
          <View style={s.actions}>
            <Button
              label="Set up this phone again"
              busy={busy}
              onPress={() => {
                setBusy(true);
                void setUpAgain().finally(() => setBusy(false));
              }}
              full
            />
            {canRetry ? <Button label="Try again" variant="quiet" onPress={retrySession} disabled={busy} full /> : null}
          </View>
        </View>
      </Scroll>
    </Screen>
  );
}

const useStyles = makeStyles((t) => ({
  body: { gap: t.space[16], paddingTop: t.space[48] },
  mark: { width: 56, height: 56, borderRadius: 28, alignItems: 'center', justifyContent: 'center' },
  actions: { gap: t.space[8], marginTop: t.space[8] },
}));
