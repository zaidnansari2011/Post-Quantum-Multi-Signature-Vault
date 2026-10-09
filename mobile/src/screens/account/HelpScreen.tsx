// Help and about (phone-ux §6.18): the documentation and status on the web, the licences, and
// "Check for updates". At the bottom, in a caption, what support may ask for: the version, the
// runtime, the channel and the update's date (expo-constants and expo-updates, both installed).

import { useState } from 'react';
import { Linking, View } from 'react-native';
import Constants from 'expo-constants';
import * as Updates from 'expo-updates';

import { InlineMessage, List, ListRow, NavBar, Screen, Scroll, Sheet, Text } from '../../ui/index.tsx';
import { makeStyles } from '../../theme/index.ts';
import { getApiBaseUrl } from '../../config.ts';
import { dayMonth } from '../../logic/words.ts';

export default function HelpScreen({ onBack }: { onBack: () => void }) {
  const s = useStyles();
  const [licences, setLicences] = useState(false);
  const [update, setUpdate] = useState<{ tone: 'neutral' | 'warning'; text: string } | null>(null);
  const [checking, setChecking] = useState(false);
  const base = getApiBaseUrl();
  const web = (path: string) => () => void Linking.openURL(`${base}${path}`).catch(() => {});

  const check = async () => {
    if (checking) return;
    setChecking(true);
    setUpdate(null);
    try {
      const result = await Updates.checkForUpdateAsync();
      setUpdate(
        result.isAvailable
          ? { tone: 'neutral', text: 'An update is ready. It applies the next time Q-Vault starts.' }
          : { tone: 'neutral', text: 'Q-Vault is up to date.' },
      );
      if (result.isAvailable) void Updates.fetchUpdateAsync().catch(() => {});
    } catch {
      setUpdate({ tone: 'warning', text: "Couldn't check for updates from here." });
    } finally {
      setChecking(false);
    }
  };

  const created = Updates.createdAt ? dayMonth(Updates.createdAt.toISOString(), Date.now()) : null;
  const details = [
    `Version ${Constants.expoConfig?.version ?? 'unknown'}`,
    Updates.runtimeVersion ? `Runtime ${Updates.runtimeVersion}` : null,
    Updates.channel ? `Channel ${Updates.channel}` : null,
    created ? `Update from ${created}` : null,
  ].filter(Boolean);

  return (
    <Screen>
      <NavBar onBack={onBack} title="Help and about" />
      <Scroll>
        <View style={s.stack}>
          <List>
            <ListRow icon="docs" title="Documentation" onPress={web('/docs')} accessibilityHint="Opens on the web" />
            <ListRow icon="pulse" title="Status" onPress={web('/status')} accessibilityHint="Opens on the web" />
            <ListRow icon="document" title="Licences" onPress={() => setLicences(true)} />
            <ListRow
              icon="download"
              title="Check for updates"
              caption={checking ? 'Checking…' : null}
              chevron={false}
              onPress={() => void check()}
            />
          </List>
          {update ? <InlineMessage tone={update.tone} text={update.text} /> : null}
          <Text role="caption" tone="subtle">
            {details.join('\n')}
          </Text>
        </View>
      </Scroll>
      <Sheet visible={licences} onClose={() => setLicences(false)} title="Licences">
        <Text role="body">
          Public Sans, Source Serif 4 and JetBrains Mono are used under the SIL Open Font License 1.1. The signing
          algorithms come from the noble-post-quantum library, under the MIT licence.
        </Text>
      </Sheet>
    </Screen>
  );
}

const useStyles = makeStyles((t) => ({
  stack: { gap: t.space[16], paddingTop: t.space[8] },
}));
