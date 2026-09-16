// No crypto polyfill here on purpose. Hermes ships no `crypto` global, but rather than depend on
// a third-party native module -- which Expo Go does not bundle, so it would fail on exactly the
// devices this is meant to run on -- the randomness ML-DSA signing needs is supplied explicitly
// from expo-crypto. See setRandomSource in src/crypto/algorithms.ts.
//
// Navigation is a tab bar over a stack, replacing the flat three-screen stack this app used to be.
// The old shape had no route to anything except the approvals list and a decision, and reached the
// device screen through a fingerprint printed in the list footer. Tabs make the product's surfaces
// addressable: the queue, the record of what has been decided, and the person's own key.
//
// The decision screen is pushed above the tabs rather than living inside one, because it is
// reachable from both the queue and the record and it is modal in intent -- someone on it is doing
// one thing, and the tab bar would invite them to wander off mid-signature.
import 'react-native-gesture-handler';
import { useEffect, useState } from 'react';
import { StatusBar } from 'expo-status-bar';
import Constants from 'expo-constants';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { View } from 'react-native';

import { setApiBaseUrl } from './src/config.ts';
import { SessionProvider, useSession, useEnrolledSession } from './src/session.tsx';
import { Loading, Screen } from './src/ui/index.tsx';
import { TabBar } from './src/ui/TabBar.tsx';
import { useAppFonts } from './src/ui/fonts.ts';
import { color } from './src/theme.ts';
import * as api from './src/api/endpoints.ts';
import EnrolScreen from './src/screens/EnrolScreen.tsx';
import HomeScreen from './src/screens/HomeScreen.tsx';
import ActivityScreen from './src/screens/ActivityScreen.tsx';
import AccountScreen from './src/screens/AccountScreen.tsx';
import DecisionScreen from './src/screens/DecisionScreen.tsx';
import VaultsScreen from './src/screens/VaultsScreen.tsx';
import VaultScreen from './src/screens/VaultScreen.tsx';
import NewDecisionScreen from './src/screens/NewDecisionScreen.tsx';
import NewVaultScreen from './src/screens/NewVaultScreen.tsx';

// Set before any request can be made. `extra.apiBaseUrl` lets a teammate point a build at a
// different server without touching source.
const configured = Constants.expoConfig?.extra?.apiBaseUrl as string | undefined;
if (configured) setApiBaseUrl(configured);

export type RootStackParamList = {
  Tabs: undefined;
  Decision: { uuid: string };
  Vault: { vaultId: number };
  // Undefined params: reached from the queue, where no vault is chosen yet.
  NewDecision: { vaultId?: number; vaultName?: string } | undefined;
  NewVault: undefined;
};

const Stack = createNativeStackNavigator<RootStackParamList>();
const Tabs = createBottomTabNavigator();

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

/**
 * The badge count.
 *
 * Read from the same query key the queue uses, so the number on the tab and the number of cards on
 * the screen cannot disagree -- a badge that outlives its list is how an approvals app trains
 * someone to ignore it.
 */
function useAwaitingCount(): number | undefined {
  const { token } = useEnrolledSession();
  const { data } = useQuery({
    queryKey: ['proposals', 'awaiting'],
    queryFn: ({ signal }) => api.fetchProposals(token, 'awaiting', signal),
  });
  const n = data?.proposals.length ?? 0;
  return n > 0 ? n : undefined;
}

function MainTabs({
  onOpen,
  onOpenVault,
  onRaise,
  onCreateVault,
}: {
  onOpen: (uuid: string) => void;
  onOpenVault: (vaultId: number) => void;
  onRaise: () => void;
  onCreateVault: () => void;
}) {
  const awaiting = useAwaitingCount();

  return (
    <Tabs.Navigator
      tabBar={(props) => <TabBar {...props} />}
      screenOptions={{
        headerShown: false,
        sceneStyle: { backgroundColor: color.paper },
      }}
    >
      <Tabs.Screen name="Home" options={{ title: 'Approvals', tabBarBadge: awaiting }}>
        {() => <HomeScreen onOpen={onOpen} onRaise={onRaise} />}
      </Tabs.Screen>
      <Tabs.Screen name="Vaults" options={{ title: 'Vaults' }}>
        {() => <VaultsScreen onOpen={onOpenVault} onCreate={onCreateVault} />}
      </Tabs.Screen>
      <Tabs.Screen name="Activity" options={{ title: 'Activity' }}>
        {() => <ActivityScreen onOpen={onOpen} />}
      </Tabs.Screen>
      <Tabs.Screen name="Account" options={{ title: 'Account' }}>
        {() => <AccountScreen />}
      </Tabs.Screen>
    </Tabs.Navigator>
  );
}

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
    <Stack.Navigator
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: color.paper },
      }}
    >
      <Stack.Screen name="Tabs">
        {({ navigation }) => (
          <MainTabs
            onOpen={(uuid) => navigation.navigate('Decision', { uuid })}
            onOpenVault={(vaultId) => navigation.navigate('Vault', { vaultId })}
            onRaise={() => navigation.navigate('NewDecision')}
            onCreateVault={() => navigation.navigate('NewVault')}
          />
        )}
      </Stack.Screen>
      <Stack.Screen name="Decision">
        {({ navigation, route }) => (
          <DecisionScreen uuid={route.params.uuid} onBack={() => navigation.goBack()} />
        )}
      </Stack.Screen>
      <Stack.Screen name="Vault">
        {({ navigation, route }) => (
          <VaultScreen
            vaultId={route.params.vaultId}
            onBack={() => navigation.goBack()}
            onOpenDecision={(uuid) => navigation.navigate('Decision', { uuid })}
            onRaise={(vaultId, vaultName) =>
              navigation.navigate('NewDecision', { vaultId, vaultName })
            }
          />
        )}
      </Stack.Screen>
      <Stack.Screen name="NewVault">
        {({ navigation }) => (
          <NewVaultScreen
            onBack={() => navigation.goBack()}
            // Replace, so back from the new vault lands on the vault list rather than on a filled
            // form that would create a duplicate if submitted again.
            onCreated={(vaultId) => navigation.replace('Vault', { vaultId })}
          />
        )}
      </Stack.Screen>
      <Stack.Screen name="NewDecision">
        {({ navigation, route }) => (
          <NewDecisionScreen
            vaultId={route.params?.vaultId}
            vaultName={route.params?.vaultName}
            onBack={() => navigation.goBack()}
            // Replace rather than push: going "back" from a decision you just raised should return
            // to the vault, not to a filled-in form that would raise a second copy if resubmitted.
            onRaised={(uuid) => navigation.replace('Decision', { uuid })}
          />
        )}
      </Stack.Screen>
    </Stack.Navigator>
  );
}

export default function App() {
  const fontsReady = useAppFonts();
  // Ensures the light chrome assumption holds even if the OS is in dark mode: the app commits to
  // one visual world, as the web client does.
  const [ready, setReady] = useState(false);
  useEffect(() => setReady(true), []);

  return (
    <SafeAreaProvider>
      <QueryClientProvider client={queryClient}>
        <SessionProvider>
          <NavigationContainer>{ready && fontsReady ? <Routes /> : null}</NavigationContainer>
        </SessionProvider>
      </QueryClientProvider>
      {/* Dark glyphs: every root screen is light paper. The tab bar is dark, but it sits at the
          bottom of the screen and the status bar is not over it. */}
      <StatusBar style="dark" />
    </SafeAreaProvider>
  );
}
