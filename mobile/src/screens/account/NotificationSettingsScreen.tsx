// Notifications (phone-ux §6.18), before push reaches this phone (R8, P4b): one honest line, and the
// web's full preferences one tap away. Push permission, its switches and the priming screen arrive
// with R8; nothing here asks the OS for anything.

import { Linking, View } from 'react-native';

import { List, ListRow, NavBar, Screen, Scroll, Text } from '../../ui/index.tsx';
import { makeStyles } from '../../theme/index.ts';
import { getApiBaseUrl } from '../../config.ts';

export default function NotificationSettingsScreen({ onBack }: { onBack: () => void }) {
  const s = useStyles();
  return (
    <Screen>
      <NavBar onBack={onBack} title="Notifications" />
      <Scroll>
        <View style={s.stack}>
          <Text role="body">
            Q-Vault will notify this phone once notifications are set up. For now, new decisions show in Approvals.
          </Text>
          <List>
            <ListRow
              icon="external"
              title="Email and other settings are on the web"
              onPress={() => void Linking.openURL(`${getApiBaseUrl()}/account/notifications`).catch(() => {})}
            />
          </List>
        </View>
      </Scroll>
    </Screen>
  );
}

const useStyles = makeStyles((t) => ({
  stack: { gap: t.space[24], paddingTop: t.space[8] },
}));
