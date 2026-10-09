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
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { StatusBar } from 'expo-status-bar';
import Constants from 'expo-constants';
import * as SystemUI from 'expo-system-ui';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { DarkTheme, DefaultTheme, NavigationContainer, type Theme as NavTheme } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { ActivityIndicator, View } from 'react-native';

import { setApiBaseUrl } from './src/config.ts';
import { SessionProvider, useSession } from './src/session.tsx';
import { Screen, TabBar, Text, ToastProvider } from './src/ui/index.tsx';
import { useAppFonts } from './src/ui/fonts.ts';
import { ThemeProvider, useTheme, type Scheme } from './src/theme/index.ts';
import { useApprovals } from './src/approvals.ts';
import EnrolScreen from './src/screens/EnrolScreen.tsx';
import HomeScreen from './src/screens/HomeScreen.tsx';
import ActivityScreen from './src/screens/ActivityScreen.tsx';
import AccountScreen from './src/screens/AccountScreen.tsx';
import DecisionScreen from './src/screens/DecisionScreen.tsx';
import VaultsScreen from './src/screens/VaultsScreen.tsx';
import VaultScreen from './src/screens/VaultScreen.tsx';
import NewDecisionScreen from './src/screens/NewDecisionScreen.tsx';
import NewVaultScreen from './src/screens/NewVaultScreen.tsx';
import WaitingScreen from './src/screens/WaitingScreen.tsx';
import SessionEndedScreen from './src/screens/SessionEndedScreen.tsx';
import { configureLinks, flushLinks, listenForLinks, navigationRef, setLinksEnrolled } from './src/links.ts';
import { usePushWiring } from './src/push.ts';
import { NotificationsPrimer } from './src/screens/NotificationsPrimer.tsx';
import { wireFocusManager } from './src/freshness.tsx';
import { RETRY } from './src/queries.ts';
import { STALE_MS } from './src/logic/freshness.ts';

// Set before any request can be made. `extra.apiBaseUrl` lets a teammate point a build at a
// different server without touching source.
const configured = Constants.expoConfig?.extra?.apiBaseUrl as string | undefined;
if (configured) setApiBaseUrl(configured);

export type RootStackParamList = {
  Tabs: { screen?: string } | undefined;
  // `getId` is the uuid, so a link to the decision already on top never stacks a second copy.
  Decision: { uuid: string; via?: 'web'; opened?: 'queue' };
  Vault: { vaultId: number };
  // Undefined params: reached from the queue, where no vault is chosen yet.
  NewDecision: { vaultId?: number; vaultName?: string } | undefined;
  NewVault: undefined;
};

export type ApprovalsStackParamList = {
  Approvals: undefined;
  Waiting: undefined;
};

const Stack = createNativeStackNavigator<RootStackParamList>();
const ApprovalsStack = createNativeStackNavigator<ApprovalsStackParamList>();
const Tabs = createBottomTabNavigator();

// Returning to the app refetches what is stale, except while the OS's own authentication prompt
// has it in the background (phone-ux §2.6, src/authPrompt.ts).
wireFocusManager();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Each query in src/queries.ts sets its own time from §2.6's table; a minute for the rest. The
      // server scales to zero, so serving a fresh answer keeps navigation instant.
      staleTime: STALE_MS.vaults,
      // Refetch what is stale when the app comes back to the front (focusManager, above).
      refetchOnWindowFocus: true,
      // One retry after 2 s, transport failures only; never a 401 or a refusal.
      ...RETRY,
    },
  },
});
// A link to a decision already on screen refetches it in place (§2.4 rule 1).
configureLinks(queryClient);

/**
 * The badge count (phone-ux §2.5).
 *
 * The same hook the queue renders from, so the number on the tab is the number of rows under
 * "Needs your signature" -- a badge that outlives its list is how an approvals app trains someone
 * to ignore it -- and it never counts a payment this phone cannot sign ("Approve on the web").
 */
function useAwaitingCount(): number | undefined {
  const n = useApprovals().groups.needsYou.length;
  return n > 0 ? n : undefined;
}

/** The Approvals tab's own stack: the queue, and Waiting on others under it, tab bar kept (§2.1). */
function ApprovalsTab({
  onOpen,
  onRaise,
  onOpenTreasuryApprovals,
}: {
  onOpen: (uuid: string) => void;
  onRaise: () => void;
  onOpenTreasuryApprovals: () => void;
}) {
  const t = useTheme();
  return (
    <ApprovalsStack.Navigator
      screenOptions={{ headerShown: false, contentStyle: { backgroundColor: t.color.bg } }}
    >
      <ApprovalsStack.Screen name="Approvals">
        {({ navigation }) => (
          <HomeScreen
            onOpen={onOpen}
            onRaise={onRaise}
            onOpenWaiting={() => navigation.navigate('Waiting')}
            onOpenTreasuryApprovals={onOpenTreasuryApprovals}
          />
        )}
      </ApprovalsStack.Screen>
      <ApprovalsStack.Screen name="Waiting">
        {({ navigation }) => <WaitingScreen onBack={() => navigation.goBack()} onOpen={onOpen} />}
      </ApprovalsStack.Screen>
    </ApprovalsStack.Navigator>
  );
}

function MainTabs({
  onOpen,
  onOpenQueued,
  onOpenVault,
  onRaise,
  onCreateVault,
}: {
  onOpen: (uuid: string) => void;
  /** From a list that showed it open: a closed answer then says it closed before you opened it. */
  onOpenQueued: (uuid: string) => void;
  onOpenVault: (vaultId: number) => void;
  onRaise: () => void;
  onCreateVault: () => void;
}) {
  const awaiting = useAwaitingCount();
  const t = useTheme();

  return (
    <Tabs.Navigator
      tabBar={(props) => <TabBar {...props} />}
      screenOptions={{
        headerShown: false,
        sceneStyle: { backgroundColor: t.color.bg },
      }}
    >
      <Tabs.Screen name="Home" options={{ title: 'Approvals', tabBarBadge: awaiting }}>
        {({ navigation }) => (
          <ApprovalsTab
            onOpen={onOpenQueued}
            onRaise={onRaise}
            onOpenTreasuryApprovals={() => navigation.navigate('Account')}
          />
        )}
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
  const { status, token } = useSession();
  const t = useTheme();
  // Push for the life of an enrolled session: foreground behaviour, the token, taps (R8, §2.4).
  usePushWiring(status === 'enrolled' ? token : null, queryClient);

  // A link kept while not enrolled (or while the session had ended) opens once the screens are up.
  useEffect(() => setLinksEnrolled(status === 'enrolled'), [status]);

  if (status === 'loading') {
    return (
      <Screen>
        <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center', gap: t.space[12] }}>
          <ActivityIndicator color={t.color.textMuted} />
          <Text role="caption" tone="muted">
            Unlocking
          </Text>
        </View>
      </Screen>
    );
  }

  if (status === 'anonymous') return <EnrolScreen />;
  // The key is still on the phone (I-3); this screen says what ended and what setting up again does.
  if (status === 'ended') return <SessionEndedScreen />;

  return (
    <>
      <Stack.Navigator
        screenOptions={{
          headerShown: false,
          contentStyle: { backgroundColor: t.color.bg },
        }}
      >
        <Stack.Screen name="Tabs">
          {({ navigation }) => (
            <MainTabs
              onOpen={(uuid) => navigation.navigate('Decision', { uuid })}
              onOpenQueued={(uuid) => navigation.navigate('Decision', { uuid, opened: 'queue' })}
              onOpenVault={(vaultId) => navigation.navigate('Vault', { vaultId })}
              onRaise={() => navigation.navigate('NewDecision')}
              onCreateVault={() => navigation.navigate('NewVault')}
            />
          )}
        </Stack.Screen>
        <Stack.Screen name="Decision" getId={({ params }) => params.uuid}>
          {({ navigation, route }) => (
            <DecisionScreen
              key={route.params.uuid}
              uuid={route.params.uuid}
              via={route.params.via}
              opened={route.params.opened}
              onBack={() => navigation.goBack()}
              // Replaces this decision, so Back from the next one lands on the queue (§2.3).
              onNext={(next) => navigation.replace('Decision', { uuid: next, opened: 'queue' })}
              onOpenTreasuryApprovals={() => navigation.navigate('Tabs', { screen: 'Account' })}
              onRaiseIn={(vaultId, vaultName) => navigation.navigate('NewDecision', { vaultId, vaultName })}
            />
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
      {/* Once, after enrolment, where this server sends pushes (§6.2 step 3). */}
      <NotificationsPrimer />
    </>
  );
}

/**
 * Everything that is not a component but still has a colour (§3.5): the status bar's glyphs, the
 * window behind the app, and React Navigation's own surfaces, so no white frame flashes in dark.
 */
function Chrome({ children }: { children: ReactNode }) {
  const t = useTheme();
  useEffect(() => {
    void SystemUI.setBackgroundColorAsync(t.color.bg).catch(() => {});
  }, [t.color.bg]);
  const navTheme = useMemo<NavTheme>(() => {
    const base = t.scheme === 'dark' ? DarkTheme : DefaultTheme;
    return {
      ...base,
      colors: {
        ...base.colors,
        primary: t.color.accent,
        background: t.color.bg,
        card: t.color.bg,
        text: t.color.text,
        border: t.color.border,
        notification: t.color.chrome.badgeBg,
      },
    };
  }, [t]);
  return (
    <NavigationContainer theme={navTheme} ref={navigationRef} onReady={flushLinks} onStateChange={flushLinks}>
      {children}
      <StatusBar style={t.scheme === 'dark' ? 'light' : 'dark'} />
    </NavigationContainer>
  );
}

export default function App() {
  return <QVaultApp />;
}

/** The app with the harness's overrides: tools/web-shots/HarnessApp.tsx renders this directly. */
export function QVaultApp({
  scheme,
  fontScale,
}: {
  /** The web screenshot harness only: the app itself follows the system (§3.6). */
  scheme?: Scheme;
  /** The web screenshot harness only: emulate a system text size (§8.1). */
  fontScale?: number;
}) {
  const fontsReady = useAppFonts();
  const [ready, setReady] = useState(false);
  useEffect(() => setReady(true), []);
  // Links for the life of the app: the one it started with, and every one while it runs (§2.4).
  useEffect(() => listenForLinks(), []);

  return (
    // The gesture root the sheets' drag needs (§5.9). Modals carry their own, for Android.
    <GestureHandlerRootView style={{ flex: 1 }}>
      <ThemeProvider scheme={scheme} fontScale={fontScale}>
        <SafeAreaProvider>
          <ToastProvider>
            <QueryClientProvider client={queryClient}>
              <SessionProvider>
                <Chrome>{ready && fontsReady ? <Routes /> : null}</Chrome>
              </SessionProvider>
            </QueryClientProvider>
          </ToastProvider>
        </SafeAreaProvider>
      </ThemeProvider>
    </GestureHandlerRootView>
  );
}
