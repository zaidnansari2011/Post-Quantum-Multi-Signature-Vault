// No crypto polyfill here on purpose. Hermes ships no `crypto` global, but rather than depend on
// a third-party native module -- which Expo Go does not bundle, so it would fail on exactly the
// devices this is meant to run on -- the randomness ML-DSA signing needs is supplied explicitly
// from expo-crypto. See setRandomSource in src/crypto/algorithms.ts.
import { useEffect, useState } from 'react';
import { StatusBar } from 'expo-status-bar';
import Constants from 'expo-constants';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { View } from 'react-native';

import { setApiBaseUrl } from './src/config.ts';
import { SessionProvider, useSession } from './src/session.tsx';
import { Loading, Screen } from './src/ui/index.tsx';
import { color } from './src/theme.ts';
import EnrolScreen from './src/screens/EnrolScreen.tsx';
import InboxScreen from './src/screens/InboxScreen.tsx';
import ProposalScreen from './src/screens/ProposalScreen.tsx';
import DeviceScreen from './src/screens/DeviceScreen.tsx';

// Set before any request can be made. `extra.apiBaseUrl` lets a teammate point a build at a
// different server without touching source.
const configured = Constants.expoConfig?.extra?.apiBaseUrl as string | undefined;
if (configured) setApiBaseUrl(configured);

export type RootStackParamList = {
  Inbox: undefined;
  Proposal: { uuid: string };
  Device: undefined;
};

const Stack = createNativeStackNavigator<RootStackParamList>();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // The server scales to zero, so a cold start is expensive. Serving cached data for a minute
      // keeps navigation instant instead of paying that repeatedly.
      staleTime: 60_000,
      refetchOnWindowFocus: false,
    },
  },
});

function Routes() {
  const { status } = useSession();

  if (status === 'loading') {
    return (
      <Screen>
        <View style={{ flex: 1, justifyContent: 'center' }}>
          <Loading label="Unlocking" />
        </View>
      </Screen>
    );
  }

  if (status === 'anonymous') return <EnrolScreen />;

  return (
    <Stack.Navigator screenOptions={{ headerShown: false, contentStyle: { backgroundColor: color.paper } }}>
      <Stack.Screen name="Inbox">
        {({ navigation }) => (
          <InboxScreen
            onOpen={(uuid) => navigation.navigate('Proposal', { uuid })}
            onOpenDevice={() => navigation.navigate('Device')}
          />
        )}
      </Stack.Screen>
      <Stack.Screen name="Proposal">
        {({ navigation, route }) => (
          <ProposalScreen uuid={route.params.uuid} onBack={() => navigation.goBack()} />
        )}
      </Stack.Screen>
      <Stack.Screen name="Device">
        {({ navigation }) => <DeviceScreen onBack={() => navigation.goBack()} />}
      </Stack.Screen>
    </Stack.Navigator>
  );
}

export default function App() {
  // Ensures the light chrome assumption holds even if the OS is in dark mode: the app commits to
  // one visual world, as the web client does.
  const [ready, setReady] = useState(false);
  useEffect(() => setReady(true), []);

  return (
    <SafeAreaProvider>
      <QueryClientProvider client={queryClient}>
        <SessionProvider>
          <NavigationContainer>{ready ? <Routes /> : null}</NavigationContainer>
        </SessionProvider>
      </QueryClientProvider>
      {/* Light glyphs: the header underneath is the dark chrome surface. */}
      <StatusBar style="light" />
    </SafeAreaProvider>
  );
}
