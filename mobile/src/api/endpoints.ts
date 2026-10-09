// One function per route in qvault/blueprints/api.py. No crypto and no storage here.

import { request } from './client.ts';
import {
  approveReconfigurationResponse,
  castVoteResponse,
  challengeResponse,
  createProposalResponse,
  createVaultResponse,
  devicesResponse,
  enrolResponse,
  meResponse,
  notificationResponse,
  notificationSettingsResponse,
  pushTokenResponse,
  peopleResponse,
  proposalDetailResponse,
  proposalsResponse,
  requestReconfigurationResponse,
  revokeResponse,
  signingChoiceResponse,
  createTreasuryResponse,
  treasuryResponse,
  vaultDetailResponse,
  vaultsResponse,
} from './schemas.ts';
import type { Decision } from '../crypto/signing.ts';

export function requestChallenge(args: { email: string; password: string }) {
  return request(challengeResponse, {
    method: 'POST',
    path: '/api/v1/devices/challenge',
    body: { email: args.email, password: args.password },
  });
}

export function enrolDevice(args: {
  email: string;
  password: string;
  deviceName: string;
  algId: string;
  publicKeyB64: string;
  challenge: string;
  popSignatureB64: string;
}) {
  return request(enrolResponse, {
    method: 'POST',
    path: '/api/v1/devices',
    body: {
      email: args.email,
      password: args.password,
      device_name: args.deviceName,
      alg_id: args.algId,
      public_key_b64: args.publicKeyB64,
      challenge: args.challenge,
      pop_signature_b64: args.popSignatureB64,
    },
  });
}

export function fetchMe(token: string, signal?: AbortSignal) {
  return request(meResponse, { path: '/api/v1/me', token, signal });
}

export function fetchDevices(token: string, signal?: AbortSignal) {
  return request(devicesResponse, { path: '/api/v1/devices', token, signal });
}

/**
 * `quietUnauthorized`: for this phone's own removal, a 401 is the remove sheet's to explain (§6.19);
 * the session is not ended under it.
 */
export function revokeDevice(token: string, deviceId: number, options: { quietUnauthorized?: boolean } = {}) {
  return request(revokeResponse, {
    method: 'POST',
    path: `/api/v1/devices/${deviceId}/revoke`,
    token,
    quietUnauthorized: options.quietUnauthorized,
  });
}

/** `state` is 'awaiting' (needs this signer) or anything else for everything visible. */
export function fetchProposals(token: string, state: 'awaiting' | 'all', signal?: AbortSignal) {
  return request(proposalsResponse, {
    path: `/api/v1/proposals?state=${encodeURIComponent(state)}`,
    token,
    signal,
  });
}

export function fetchProposal(token: string, uuid: string, signal?: AbortSignal) {
  return request(proposalDetailResponse, {
    path: `/api/v1/proposals/${encodeURIComponent(uuid)}`,
    token,
    signal,
  });
}

/**
 * Create a vault, with its signers, in one call.
 *
 * Members go with the create rather than following it: `create_proposal` refuses when M exceeds
 * the signer count, so a 3-of-N vault created alone would reject every decision raised in it until
 * somebody remembered a second request. One round trip also means a dropped connection cannot
 * leave a half-built vault behind.
 */
export function createVault(args: {
  token: string;
  name: string;
  description?: string;
  thresholdM: number;
  /** Ids from the picker. The handset never holds an address; the server resolves these. */
  memberIds: number[];
}) {
  return request(createVaultResponse, {
    method: 'POST',
    path: '/api/v1/vaults',
    token: args.token,
    body: {
      name: args.name,
      description: args.description ?? '',
      threshold_m: args.thresholdM,
      member_ids: args.memberIds,
    },
  });
}

export function addVaultMember(args: {
  token: string;
  vaultId: number;
  email: string;
  role?: 'signer' | 'viewer';
}) {
  return request(createVaultResponse, {
    method: 'POST',
    path: `/api/v1/vaults/${args.vaultId}/members`,
    token: args.token,
    body: { email: args.email, role: args.role ?? 'signer' },
  });
}

/** Names to build a vault from. Never returns addresses -- see the server docstring for why. */
export function fetchPeople(token: string, signal?: AbortSignal) {
  return request(peopleResponse, { path: '/api/v1/people', token, signal });
}

export function fetchVaults(token: string, signal?: AbortSignal) {
  return request(vaultsResponse, { path: '/api/v1/vaults', token, signal });
}

export function fetchVault(token: string, vaultId: number, signal?: AbortSignal) {
  return request(vaultDetailResponse, { path: `/api/v1/vaults/${vaultId}`, token, signal });
}

/**
 * Raise a decision.
 *
 * No attachment: the canonical signing payload binds an attached file's SHA-256, so a version that
 * uploaded one without binding it would produce decisions whose signatures did not cover the
 * document they are about. The web client keeps that job until this path is built to the same
 * standard.
 */
export function createProposal(args: {
  token: string;
  vaultId: number;
  title: string;
  actionText: string;
  expiresInHours?: number | null;
  /** A payment decision (plan Phase 8): the server builds the signed action and writes the text. */
  payment?: { to: string; valueWei: string } | null;
}) {
  return request(createProposalResponse, {
    method: 'POST',
    path: `/api/v1/vaults/${args.vaultId}/proposals`,
    token: args.token,
    body: {
      title: args.title,
      ...(args.payment
        ? { payment: { to: args.payment.to, value_wei: args.payment.valueWei } }
        : { action_text: args.actionText }),
      expires_in_hours: args.expiresInHours ?? null,
    },
  });
}

export function castVote(args: {
  token: string;
  uuid: string;
  decision: Decision;
  signatureB64: string;
  /** Present exactly when approving a payment (plan Phase 6b). */
  executionSignatureB64?: string | null;
  reason?: string | null;
}) {
  return request(castVoteResponse, {
    method: 'POST',
    path: `/api/v1/proposals/${encodeURIComponent(args.uuid)}/vote`,
    token: args.token,
    body: {
      decision: args.decision,
      signature_b64: args.signatureB64,
      ...(args.executionSignatureB64 ? { execution_signature_b64: args.executionSignatureB64 } : {}),
      reason: args.reason ?? null,
    },
  });
}

// -- treasury (plan D40, Phase 7b) ---------------------------------------------------------------

export function fetchTreasury(token: string, vaultId: number, signal?: AbortSignal) {
  return request(treasuryResponse, { path: `/api/v1/vaults/${vaultId}/treasury`, token, signal });
}

/**
 * Ask for the treasury to follow the vault (D45). The server answers `needs_confirmation` with
 * its warnings until this is sent again with `confirm`.
 */
/** Ask for a treasury for this vault (D36). Sends nothing now: the server does the work. */
export function createTreasury(args: { token: string; vaultId: number }) {
  return request(createTreasuryResponse, {
    method: 'POST',
    path: `/api/v1/vaults/${args.vaultId}/treasury`,
    token: args.token,
    body: {},
  });
}

export function requestReconfiguration(args: {
  token: string;
  vaultId: number;
  /** `warnings_digest` of the warnings shown to the owner, or null when there were none (D45). */
  confirm: string | null;
}) {
  return request(requestReconfigurationResponse, {
    method: 'POST',
    path: `/api/v1/vaults/${args.vaultId}/treasury/reconfigure`,
    token: args.token,
    body: { confirm: args.confirm },
  });
}

export function approveReconfiguration(args: {
  token: string;
  vaultId: number;
  reconfigurationId: number;
  signatureB64: string;
}) {
  return request(approveReconfigurationResponse, {
    method: 'POST',
    path: `/api/v1/vaults/${args.vaultId}/treasury/reconfigurations/${args.reconfigurationId}/approve`,
    token: args.token,
    body: { signature_b64: args.signatureB64 },
  });
}

/** Which key treasuries register for this person (D37): this phone's, or the password key. */
export function setSigningChoice(args: { token: string; custody: 'device' | 'password' }) {
  return request(signingChoiceResponse, {
    method: 'PUT',
    path: '/api/v1/me/signing-choice',
    token: args.token,
    body: { custody: args.custody },
  });
}

// -- Phone push (plan R8) ---------------------------------------------------------------------------

/** This phone's Expo push token. The server takes it for the calling device only. */
export function registerPushToken(token: string, pushToken: string) {
  return request(pushTokenResponse, {
    method: 'PUT',
    path: '/api/v1/me/push-token',
    token,
    body: { token: pushToken },
  });
}

/** `quietUnauthorized`: called while this phone is being wiped, when its token may already be dead. */
export function clearPushToken(token: string) {
  return request(pushTokenResponse, {
    method: 'DELETE',
    path: '/api/v1/me/push-token',
    token,
    quietUnauthorized: true,
  });
}

export function fetchNotificationSettings(token: string, signal?: AbortSignal) {
  return request(notificationSettingsResponse, { path: '/api/v1/me/notification-settings', token, signal });
}

export function setPushGroup(token: string, group: string, enabled: boolean) {
  return request(notificationSettingsResponse, {
    method: 'PUT',
    path: '/api/v1/me/notification-settings',
    token,
    body: { group, enabled },
  });
}

/** A tapped push's notification, marked read (fire and forget, phone-ux §2.4). */
export function markNotificationRead(token: string, notificationId: number) {
  return request(notificationResponse, {
    method: 'POST',
    path: `/api/v1/notifications/${notificationId}/read`,
    token,
  });
}
