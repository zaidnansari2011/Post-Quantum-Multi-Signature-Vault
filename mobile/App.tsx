// No crypto polyfill here on purpose. Hermes ships no `crypto` global, but rather than depend on
// a third-party native module -- which Expo Go does not bundle, so it would fail on exactly the
// devices this is meant to run on -- the randomness ML-DSA signing needs is supplied explicitly
// from expo-crypto. See setRandomSource in src/crypto/algorithms.ts.
//
// Navigation (phone-ux §2.1): four tabs, Approvals, Activity, Vaults and Account, each with its own
// stack so switching tabs keeps each one's place, and the tab bar stays on every screen inside
// them. Only Decision and Treasury change hide it: they sit on the app's stack above the tabs,
// because their action bar owns the bottom edge and a tab bar would invite someone to wander off
// mid-signature (D1). The discussion thread opens over a decision the same way. New decision and New
// vault are modals: tasks with a Close, not places.

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
import { View } from 'react-native';

import { setApiBaseUrl } from './src/config.ts';
import { SessionProvider, useSession } from './src/session.tsx';
import { AppLockProvider, useAppLock } from './src/appLock.tsx';
import { Icon, TabBar, ToastProvider } from './src/ui/index.tsx';
import { useAppFonts } from './src/ui/fonts.ts';
import { ThemeProvider, makeStyles, useTheme, type Scheme } from './src/theme/index.ts';
import { useApprovals, useTreasuryChanges } from './src/approvals.ts';
import type { RaisedFields } from './src/logic/raised.ts';
import type { AgainFrom } from './src/screens/NewDecisionScreen.tsx';
import EnrolScreen from './src/screens/EnrolScreen.tsx';
import HomeScreen from './src/screens/HomeScreen.tsx';
import ActivityScreen from './src/screens/ActivityScreen.tsx';
import AccountScreen from './src/screens/AccountScreen.tsx';
import ThisPhoneScreen from './src/screens/account/ThisPhoneScreen.tsx';
import OtherDevicesScreen from './src/screens/account/OtherDevicesScreen.tsx';
import TreasuryApprovalsScreen from './src/screens/account/TreasuryApprovalsScreen.tsx';
import NotificationSettingsScreen from './src/screens/account/NotificationSettingsScreen.tsx';
import HelpScreen from './src/screens/account/HelpScreen.tsx';
import DecisionScreen from './src/screens/DecisionScreen.tsx';
import DiscussionScreen from './src/screens/DiscussionScreen.tsx';
import VaultsScreen from './src/screens/VaultsScreen.tsx';
import VaultScreen from './src/screens/VaultScreen.tsx';
import VaultDecisionsScreen from './src/screens/VaultDecisionsScreen.tsx';
import TreasuryChangeScreen from './src/screens/TreasuryChangeScreen.tsx';
import NewDecisionScreen from './src/screens/NewDecisionScreen.tsx';
import NewVaultScreen from './src/screens/NewVaultScreen.tsx';
import WaitingScreen from './src/screens/WaitingScreen.tsx';
import SessionEndedScreen from './src/screens/SessionEndedScreen.tsx';
import LockScreen from './src/screens/LockScreen.tsx';
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
  Tabs: { screen?: string; params?: object } | undefined;
  // `getId` is the uuid, so a link to the decision already on top never stacks a second copy.
  // `raised`: what this phone just raised, held in memory only, checked against what was stored (I-5).
  Decision: { uuid: string; via?: 'web'; opened?: 'queue'; raised?: RaisedFields };
  // `getId` is the change's id (§6.15).
  TreasuryChange: { vaultId: number; changeId: number; opened?: 'queue' };
  Discussion: { uuid: string; title?: string };
  // Undefined params: reached from the queue, where no vault is chosen yet.
  NewDecision: { vaultId?: number; vaultName?: string; again?: AgainFrom } | undefined;
  NewVault: undefined;
};

export type ApprovalsStackParamList = {
  Approvals: undefined;
  Waiting: undefined;
};

export type VaultsStackParamList = {
  VaultList: undefined;
  Vault: { vaultId: number };
  VaultDecisions: { vaultId: number; which: 'open' | 'history' };
};

export type AccountStackParamList = {
  AccountHome: undefined;
  ThisPhone: undefined;
  OtherDevices: { removeDeviceId?: number } | undefined;
  NotificationSettings: undefined;
  TreasuryApprovals: { fromPayment?: boolean } | undefined;
  Help: undefined;
};

const Stack = createNativeStackNavigator<RootStackParamList>();
const ApprovalsStack = createNativeStackNavigator<ApprovalsStackParamList>();
const VaultsStack = createNativeStackNavigator<VaultsStackParamList>();
const AccountStack = createNativeStackNavigator<AccountStackParamList>();
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
 * The same hooks the queue renders from, so the number on the tab is the number of rows under
 * "Needs your signature" -- a badge that outlives its list is how an approvals app trains someone
 * to ignore it -- and it never counts something this phone cannot sign ("Approve on the web").
 * Treasury changes waiting on this phone's key count too (§6.15).
 */
function useAwaitingCount(): number | undefined {
  const n = useApprovals().groups.needsYou.length + useTreasuryChanges().here.length;
  return n > 0 ? n : undefined;
}

type Open = {
  onOpen: (uuid: string) => void;
  onOpenQueued: (uuid: string) => void;
  onOpenChange: (vaultId: number, changeId: number, queued?: boolean) => void;
  onRaise: (vaultId?: number, vaultName?: string) => void;
  onCreateVault: () => void;
};

/** The Approvals tab's own stack: the queue, and Waiting on others under it, tab bar kept (§2.1). */
function ApprovalsTab({ open, onOpenTreasuryApprovals }: { open: Open; onOpenTreasuryApprovals: () => void }) {
  const t = useTheme();
  return (
    <ApprovalsStack.Navigator screenOptions={{ headerShown: false, contentStyle: { backgroundColor: t.color.bg } }}>
      <ApprovalsStack.Screen name="Approvals">
        {({ navigation }) => (
          <HomeScreen
            onOpen={open.onOpenQueued}
            onOpenChange={(vaultId, changeId) => open.onOpenChange(vaultId, changeId, true)}
            onRaise={() => open.onRaise()}
            onOpenWaiting={() => navigation.navigate('Waiting')}
            onOpenTreasuryApprovals={onOpenTreasuryApprovals}
          />
        )}
      </ApprovalsStack.Screen>
      <ApprovalsStack.Screen name="Waiting">
        {({ navigation }) => <WaitingScreen onBack={() => navigation.goBack()} onOpen={open.onOpen} />}
      </ApprovalsStack.Screen>
    </ApprovalsStack.Navigator>
  );
}

/** The Vaults tab: the list, a vault, and a vault's full lists, tab bar kept (§2.1, D1). */
function VaultsTab({ open }: { open: Open }) {
  const t = useTheme();
  return (
    <VaultsStack.Navigator screenOptions={{ headerShown: false, contentStyle: { backgroundColor: t.color.bg } }}>
      <VaultsStack.Screen name="VaultList">
        {({ navigation }) => (
          <VaultsScreen onOpen={(vaultId) => navigation.navigate('Vault', { vaultId })} onCreate={open.onCreateVault} />
        )}
      </VaultsStack.Screen>
      <VaultsStack.Screen name="Vault">
        {({ navigation, route }) => (
          <VaultScreen
            vaultId={route.params.vaultId}
            onBack={() => navigation.goBack()}
            onOpenDecision={open.onOpen}
            onOpenChange={(changeId) => open.onOpenChange(route.params.vaultId, changeId)}
            onRaise={open.onRaise}
            onSeeAll={(which) => navigation.navigate('VaultDecisions', { vaultId: route.params.vaultId, which })}
          />
        )}
      </VaultsStack.Screen>
      <VaultsStack.Screen name="VaultDecisions">
        {({ navigation, route }) => (
          <VaultDecisionsScreen
            vaultId={route.params.vaultId}
            which={route.params.which}
            onBack={() => navigation.goBack()}
            onOpen={open.onOpen}
          />
        )}
      </VaultsStack.Screen>
    </VaultsStack.Navigator>
  );
}

/** The Account tab: who I am here, this phone, other devices, and the rest one row each (§6.18). */
function AccountTab() {
  const t = useTheme();
  return (
    <AccountStack.Navigator screenOptions={{ headerShown: false, contentStyle: { backgroundColor: t.color.bg } }}>
      <AccountStack.Screen name="AccountHome">
        {({ navigation }) => (
          <AccountScreen
            onOpen={(page) => navigation.navigate(page)}
          />
        )}
      </AccountStack.Screen>
      <AccountStack.Screen name="ThisPhone">
        {({ navigation }) => <ThisPhoneScreen onBack={() => navigation.goBack()} />}
      </AccountStack.Screen>
      <AccountStack.Screen name="OtherDevices">
        {({ navigation, route }) => (
          <OtherDevicesScreen onBack={() => navigation.goBack()} removeDeviceId={route.params?.removeDeviceId} />
        )}
      </AccountStack.Screen>
      <AccountStack.Screen name="NotificationSettings">
        {({ navigation }) => <NotificationSettingsScreen onBack={() => navigation.goBack()} />}
      </AccountStack.Screen>
      <AccountStack.Screen name="TreasuryApprovals">
        {({ navigation, route }) => (
          <TreasuryApprovalsScreen onBack={() => navigation.goBack()} fromPayment={route.params?.fromPayment} />
        )}
      </AccountStack.Screen>
      <AccountStack.Screen name="Help">
        {({ navigation }) => <HelpScreen onBack={() => navigation.goBack()} />}
      </AccountStack.Screen>
    </AccountStack.Navigator>
  );
}

function MainTabs({ open }: { open: Open }) {
  const awaiting = useAwaitingCount();
  const t = useTheme();

  return (
    <Tabs.Navigator
      tabBar={(props) => <TabBar {...props} />}
      screenOptions={{ headerShown: false, sceneStyle: { backgroundColor: t.color.bg } }}
    >
      <Tabs.Screen name="Home" options={{ title: 'Approvals', tabBarBadge: awaiting }}>
        {({ navigation }) => (
          <ApprovalsTab
            open={open}
            onOpenTreasuryApprovals={() =>
              navigation.navigate('Account', { screen: 'TreasuryApprovals', params: { fromPayment: true } })
            }
          />
        )}
      </Tabs.Screen>
      {/* Second, because it is the second most visited place (§2.2). */}
      <Tabs.Screen name="Activity" options={{ title: 'Activity' }}>
        {() => <ActivityScreen onOpen={open.onOpen} />}
      </Tabs.Screen>
      <Tabs.Screen name="Vaults" options={{ title: 'Vaults' }}>
        {() => <VaultsTab open={open} />}
      </Tabs.Screen>
      <Tabs.Screen name="Account" options={{ title: 'Account' }}>
        {() => <AccountTab />}
      </Tabs.Screen>
    </Tabs.Navigator>
  );
}

/**
 * Before the first frame: the mark on `bg`, never "Unlocking" and a spinner (§6.1). `bare` until
 * the fonts are in, since the mark is a glyph of the app's icon font.
 */
function Launch({ bare = false }: { bare?: boolean }) {
  const s = useStyles();
  const t = useTheme();
  return (
    <View style={s.launch} accessibilityLabel="Q-Vault">
      {bare ? null : <Icon name="mark" size={48} color={t.color.accent} />}
    </View>
  );
}

function Routes() {
  const { status, token } = useSession();
  const lock = useAppLock();
  const t = useTheme();
  // Push for the life of an enrolled session: foreground behaviour, the token, taps (R8, §2.4).
  usePushWiring(status === 'enrolled' ? token : null, queryClient);

  // A link kept while not enrolled (or while the session had ended) opens once the screens are up.
  useEffect(() => setLinksEnrolled(status === 'enrolled'), [status]);

  if (status === 'loading' || (status === 'enrolled' && !lock.ready)) return <Launch />;
  if (status === 'anonymous') return <EnrolScreen />;
  // The key is still on the phone (I-3); this screen says what ended and what setting up again does.
  if (status === 'ended') return <SessionEndedScreen />;

  return (
    <>
      <Stack.Navigator screenOptions={{ headerShown: false, contentStyle: { backgroundColor: t.color.bg } }}>
        <Stack.Screen name="Tabs">
          {({ navigation }) => (
            <MainTabs
              open={{
                onOpen: (uuid) => navigation.navigate('Decision', { uuid }),
                onOpenQueued: (uuid) => navigation.navigate('Decision', { uuid, opened: 'queue' }),
                onOpenChange: (vaultId, changeId, queued) =>
                  navigation.navigate('TreasuryChange', { vaultId, changeId, opened: queued ? 'queue' : undefined }),
                onRaise: (vaultId, vaultName) => navigation.navigate('NewDecision', vaultId ? { vaultId, vaultName } : undefined),
                onCreateVault: () => navigation.navigate('NewVault'),
              }}
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
              raised={route.params.raised}
              onBack={() => navigation.goBack()}
              // Replaces this decision, so Back from the next one lands on the queue (§2.3).
              onNext={(next) => navigation.replace('Decision', { uuid: next, opened: 'queue' })}
              onOpenTreasuryApprovals={() =>
                navigation.navigate('Tabs', { screen: 'Account', params: { screen: 'TreasuryApprovals', params: { fromPayment: true } } })
              }
              onRaiseAgain={(again) => navigation.navigate('NewDecision', { vaultId: again.vaultId, vaultName: again.vaultName, again })}
              onOpenDiscussion={(title) => navigation.navigate('Discussion', { uuid: route.params.uuid, title })}
            />
          )}
        </Stack.Screen>
        <Stack.Screen name="TreasuryChange" getId={({ params }) => String(params.changeId)}>
          {({ navigation, route }) => (
            <TreasuryChangeScreen
              key={route.params.changeId}
              vaultId={route.params.vaultId}
              changeId={route.params.changeId}
              opened={route.params.opened}
              onBack={() => navigation.goBack()}
              onOpenTreasuryApprovals={() =>
                navigation.navigate('Tabs', { screen: 'Account', params: { screen: 'TreasuryApprovals', params: { fromPayment: true } } })
              }
            />
          )}
        </Stack.Screen>
        <Stack.Screen name="Discussion">
          {({ navigation, route }) => (
            <DiscussionScreen uuid={route.params.uuid} title={route.params.title} onBack={() => navigation.goBack()} />
          )}
        </Stack.Screen>
        <Stack.Group screenOptions={{ presentation: 'modal' }}>
          <Stack.Screen name="NewVault">
            {({ navigation }) => (
              <NewVaultScreen
                onClose={() => navigation.goBack()}
                // To the new vault inside the Vaults tab, so Back lands on the list rather than on a
                // filled form that would create a duplicate if submitted again.
                onCreated={(vaultId) =>
                  navigation.navigate('Tabs', { screen: 'Vaults', params: { screen: 'Vault', params: { vaultId } } })
                }
              />
            )}
          </Stack.Screen>
          <Stack.Screen name="NewDecision">
            {({ navigation, route }) => (
              <NewDecisionScreen
                vaultId={route.params?.vaultId}
                vaultName={route.params?.vaultName}
                again={route.params?.again}
                onClose={() => navigation.goBack()}
                // Replace rather than push: going "back" from a decision you just raised should not
                // return to a filled-in form that would raise a second copy if resubmitted (§2.3).
                onRaised={(uuid, raised) => navigation.replace('Decision', { uuid, raised })}
              />
            )}
          </Stack.Screen>
        </Stack.Group>
      </Stack.Navigator>
      {/* Once, after enrolment, where this server sends pushes (§6.2 step 3). */}
      <NotificationsPrimer />
      {lock.locked ? <LockScreen /> : lock.covered ? <PrivacyCover /> : null}
    </>
  );
}

/** iOS: drawn while the switcher may snapshot the app, with app lock on (§6.1). */
function PrivacyCover() {
  const s = useStyles();
  return (
    <View style={s.cover} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      <Launch />
    </View>
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

/** App lock follows the session: only an enrolled phone has anything to lock. */
function Locked({ children }: { children: ReactNode }) {
  const { status } = useSession();
  return <AppLockProvider active={status === 'enrolled'}>{children}</AppLockProvider>;
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
                <Locked>
                  <Chrome>{ready && fontsReady ? <Routes /> : <Launch bare />}</Chrome>
                </Locked>
              </SessionProvider>
            </QueryClientProvider>
          </ToastProvider>
        </SafeAreaProvider>
      </ThemeProvider>
    </GestureHandlerRootView>
  );
}

const useStyles = makeStyles((t) => ({
  launch: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: t.color.bg },
  cover: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, zIndex: 100 },
}));
