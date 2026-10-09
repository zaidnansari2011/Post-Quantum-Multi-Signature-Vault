// Deep links and notification taps, applied to the running app (phone-ux §2.4).
//
// One function, `openLink`, handles a link whether the app has just started or was already open:
// it asks the pure `routeLink` (src/logic/links.ts, where §2.4's seven rules are probed) what to do
// given what the app is doing, and does it. The decision screen reports its signing state here, so
// a link that arrives while a signature is in flight is held until the signature settles and the
// acknowledgement has closed: a link never interrupts a signature.
//
// A link that cannot be applied yet (not enrolled, the session ended, a signature in flight, a form
// open under a target that cannot be pushed over it) is kept and applied as soon as it can be. It is
// never dropped.
//
// Push: `openPush` takes a notification's data, once expo-notifications is in the APK (N12); until
// then nothing calls it. Marking the notification read (`POST /notifications/<id>/read`) waits for
// that route (A8).

import { Linking } from 'react-native';
import { CommonActions, StackActions, createNavigationContainerRef } from '@react-navigation/native';
import type { QueryClient } from '@tanstack/react-query';

import { getApiBaseUrl } from './config.ts';
import { parseLink, routeLink, targetFromPush, type LinkTarget, type Situation } from './logic/links.ts';

export const navigationRef = createNavigationContainerRef<any>();

type SigningState = {
  sheet: Situation['sheet'];
  acknowledging: boolean;
  /**
   * Closes an idle sheet as Cancel would (rule 3). False when it did not close, because a signature
   * started in the same frame: the link is then held like rule 2.
   */
  closeSheet: (() => boolean) | null;
};

let signing: SigningState = { sheet: 'none', acknowledging: false, closeSheet: null };
let pending: LinkTarget | null = null;
let enrolled = false;
let locked = false;
let queries: QueryClient | null = null;

export function configureLinks(client: QueryClient): void {
  queries = client;
}

/** The app is enrolled and its screens are mounted (or not): a kept link may now apply. */
export function setLinksEnrolled(value: boolean): void {
  enrolled = value;
  if (value) flushLinks();
}

/** App lock (§6.1): while locked, a link is kept (rule 6) and opened once unlocked. */
export function setLinksLocked(value: boolean): void {
  locked = value;
  if (!value) flushLinks();
}

/** The decision screen's signing state. Back to none, a held link applies. */
export function reportSigning(next: SigningState): void {
  signing = next;
  if (next.sheet === 'none' && !next.acknowledging) flushLinks();
}

/** Apply a kept link, if it can be applied now. Called on every navigation change too. */
export function flushLinks(): void {
  if (!pending) return;
  const target = pending;
  pending = null;
  openLink(target);
}

function situation(): Situation {
  const route = navigationRef.isReady() ? navigationRef.getCurrentRoute() : undefined;
  const params = (route?.params ?? {}) as Record<string, unknown>;
  const id =
    route?.name === 'Decision'
      ? (params.uuid as string | undefined)
      : route?.name === 'Vault'
        ? (params.vaultId as number | undefined)
        : route?.name === 'TreasuryChange'
          ? (params.changeId as number | undefined)
          : null;
  return {
    enrolled: enrolled && route !== undefined,
    locked,
    top: route ? { name: route.name, id: id ?? null } : null,
    sheet: signing.sheet,
    acknowledging: signing.acknowledging,
    formOpen: route?.name === 'NewDecision' || route?.name === 'NewVault',
  };
}

/** The tabs, on `tab`, with its own stack holding `inner` (root first, then any pushed screens). */
const tabs = (tab: string, inner: Array<{ name: string; params?: object }> = []) => ({
  name: 'Tabs',
  state: {
    routes: [{ name: tab, ...(inner.length ? { state: { index: inner.length - 1, routes: inner } } : {}) }],
  },
});

/** Rule 5's stack for a target: the tab, its root, and the target on top. */
function routesFor(target: LinkTarget): object[] {
  switch (target.kind) {
    case 'decision':
      return [tabs('Home', [{ name: 'Approvals' }]), { name: 'Decision', params: { uuid: target.uuid, via: target.via } }];
    case 'treasuryChange':
      // Its own route over the queue, like a decision (§6.15).
      return [
        tabs('Home', [{ name: 'Approvals' }]),
        { name: 'TreasuryChange', params: { vaultId: target.vaultId, changeId: target.changeId } },
      ];
    case 'vault':
      // Inside the Vaults tab, with the list under it (§2.1): Back lands on the vaults.
      return [tabs('Vaults', [{ name: 'VaultList' }, { name: 'Vault', params: { vaultId: target.vaultId } }])];
    case 'activity':
      return [tabs('Activity')];
    case 'security':
      // Account, Other devices, with the remove sheet for that device open (§6.18).
      return [
        tabs('Account', [{ name: 'AccountHome' }, { name: 'OtherDevices', params: { removeDeviceId: target.deviceId } }]),
      ];
  }
}

/** Rule 5: switch tab, pop it to its root, push the target. Back always lands under it. */
function open(target: LinkTarget): void {
  const routes = routesFor(target);
  navigationRef.dispatch(CommonActions.reset({ index: routes.length - 1, routes: routes as never }));
}

/** Rule 3's close. True once the sheet is closed; false if a signature started meanwhile. */
function closeIdleSheet(): boolean {
  const closed = signing.closeSheet ? signing.closeSheet() : false;
  if (closed) signing = { ...signing, sheet: 'none', closeSheet: null };
  return closed;
}

/**
 * Rule 1: the target is already on top. Refetch it there; a handoff link (`via=web`) also switches
 * the decision's approve sheet to the full comparison block (§5.11).
 */
function refetchInPlace(target: LinkTarget): void {
  if (target.kind === 'decision') {
    if (target.via) navigationRef.dispatch(CommonActions.setParams({ via: target.via }));
    void queries?.invalidateQueries({ queryKey: ['proposal', target.uuid] });
  }
  if (target.kind === 'vault') void queries?.invalidateQueries({ queryKey: ['vault', target.vaultId] });
  if (target.kind === 'treasuryChange') void queries?.invalidateQueries({ queryKey: ['treasury', target.vaultId] });
}

export function openLink(target: LinkTarget): void {
  const step = routeLink(target, situation());
  switch (step.step) {
    case 'store':
    case 'hold':
      pending = target;
      return;
    case 'refetch':
      refetchInPlace(target);
      return;
    case 'closeSheetThenOpen':
    case 'closeSheetThenRefetch':
      if (!closeIdleSheet()) {
        pending = target;
        return;
      }
      if (step.step === 'closeSheetThenOpen') open(target);
      else refetchInPlace(target);
      return;
    case 'pushOver':
      // Rule 4: over the form, which stays intact underneath. A decision or a treasury change is
      // pushed; a target inside a tab (a vault, Activity, Account) is kept and applied once the form
      // is left, because reaching a tab would close the form under it.
      if (target.kind === 'decision') {
        navigationRef.dispatch(StackActions.push('Decision', { uuid: target.uuid, via: target.via }));
      } else if (target.kind === 'treasuryChange') {
        navigationRef.dispatch(
          StackActions.push('TreasuryChange', { vaultId: target.vaultId, changeId: target.changeId }),
        );
      } else {
        pending = target;
      }
      return;
    case 'open':
      open(target);
  }
}

/** This app's server, whose decision pages an https link may point at. */
function webHost(): string | null {
  const match = /^https:\/\/([^/:]+)/i.exec(getApiBaseUrl());
  return match ? match[1]! : null;
}

/** A URL from the system (a cold start or a running app). Anything not ours is ignored. */
export function openUrl(url: string | null | undefined): void {
  if (!url) return;
  const target = parseLink(url, webHost());
  if (target) openLink(target);
}

/** A notification tap's data (§2.4). Nothing calls this until push exists (N12, R8). */
export function openPush(data: unknown): void {
  const read = targetFromPush(data);
  if (read) openLink(read.target);
}

/** Listen for links for the life of the app: the one it started with, and every one after. */
export function listenForLinks(): () => void {
  void Linking.getInitialURL()
    .then(openUrl)
    .catch(() => {});
  const subscription = Linking.addEventListener('url', (event) => openUrl(event.url));
  return () => subscription.remove();
}
