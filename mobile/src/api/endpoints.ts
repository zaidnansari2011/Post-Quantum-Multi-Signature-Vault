// One function per route in qvault/blueprints/api.py. No crypto and no storage here.

import { request } from './client.ts';
import {
  castVoteResponse,
  challengeResponse,
  createProposalResponse,
  devicesResponse,
  enrolResponse,
  meResponse,
  proposalDetailResponse,
  proposalsResponse,
  revokeResponse,
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

export function revokeDevice(token: string, deviceId: number) {
  return request(revokeResponse, {
    method: 'POST',
    path: `/api/v1/devices/${deviceId}/revoke`,
    token,
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
}) {
  return request(createProposalResponse, {
    method: 'POST',
    path: `/api/v1/vaults/${args.vaultId}/proposals`,
    token: args.token,
    body: {
      title: args.title,
      action_text: args.actionText,
      expires_in_hours: args.expiresInHours ?? null,
    },
  });
}

export function castVote(args: {
  token: string;
  uuid: string;
  decision: Decision;
  signatureB64: string;
  reason?: string | null;
}) {
  return request(castVoteResponse, {
    method: 'POST',
    path: `/api/v1/proposals/${encodeURIComponent(args.uuid)}/vote`,
    token: args.token,
    body: {
      decision: args.decision,
      signature_b64: args.signatureB64,
      reason: args.reason ?? null,
    },
  });
}
