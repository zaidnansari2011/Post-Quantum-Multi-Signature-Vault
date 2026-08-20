// The wire contract, mirrored from qvault/blueprints/api.py.
//
// Parsed rather than cast. A `as ProposalDetail` would make TypeScript stop complaining without
// checking anything, and the one field that must never be silently absent is `signing_inputs` --
// if it arrived malformed and we treated it as present, the app would sign a payload hash it had
// not actually derived. Parsing turns that into a visible error at the boundary.

import { z } from 'zod';

export const errorBody = z.object({
  ok: z.literal(false),
  code: z.string(),
  error: z.string(),
});

export const deviceSchema = z.object({
  id: z.number().int(),
  name: z.string(),
  alg_id: z.string().nullable(),
  fingerprint: z.string().nullable(),
  created_at: z.string().nullable(),
  last_seen_at: z.string().nullable(),
  expires_at: z.string().nullable(),
  revoked_at: z.string().nullable(),
  is_current: z.boolean(),
});
export type Device = z.infer<typeof deviceSchema>;

export const challengeResponse = z.object({
  ok: z.literal(true),
  user_id: z.number().int(),
  display_name: z.string(),
  challenge: z.string(),
  expires_at: z.string(),
  eligible_algorithms: z.array(z.string()),
  default_algorithm: z.string(),
});

export const enrolResponse = z.object({
  ok: z.literal(true),
  token: z.string(),
  expires_at: z.string().nullable(),
  device: deviceSchema,
});

export const meResponse = z.object({
  ok: z.literal(true),
  user: z.object({
    id: z.number().int(),
    email: z.string(),
    display_name: z.string(),
  }),
  device: deviceSchema,
});
export type Me = z.infer<typeof meResponse>;

export const devicesResponse = z.object({
  ok: z.literal(true),
  devices: z.array(deviceSchema),
});

export const revokeResponse = z.object({
  ok: z.literal(true),
  device: deviceSchema,
});

export const proposalSummary = z.object({
  proposal_uuid: z.string(),
  title: z.string(),
  vault_id: z.number().int(),
  vault_name: z.string().nullable(),
  status: z.string(),
  required_m: z.number().int(),
  required_n: z.number().int(),
  approvals: z.number().int(),
  rejections: z.number().int(),
  expires_at: z.string().nullable(),
  signed_by_me: z.boolean(),
  can_sign: z.boolean(),
});
export type ProposalSummary = z.infer<typeof proposalSummary>;

export const proposalsResponse = z.object({
  ok: z.literal(true),
  proposals: z.array(proposalSummary),
  state: z.string(),
});

// Must match SigningInputs in src/crypto/signing.ts exactly. Strict, so a server that renamed or
// dropped a field fails here rather than producing a hash that silently disagrees.
export const signingInputsSchema = z
  .object({
    vault_id: z.number().int(),
    proposal_id: z.string(),
    action_text: z.string(),
    file_sha256: z.string().nullable(),
    policy: z
      .object({
        M: z.number().int(),
        N: z.number().int(),
        signers: z.array(z.number().int()),
      })
      .strict(),
    nonce: z.string(),
    created_at: z.string(),
  })
  .strict();

export const voteRecord = z.object({
  signer_id: z.number().int(),
  signer_name: z.string().nullable(),
  decision: z.string(),
  custody: z.enum(['device', 'server']),
  alg_id: z.string().nullable(),
  reason: z.string().nullable(),
  signed_at: z.string().nullable(),
});
export type VoteRecord = z.infer<typeof voteRecord>;

export const proposalDetail = proposalSummary.extend({
  action_text: z.string(),
  signing_inputs: signingInputsSchema,
  payload_hash: z.string(),
  signing_bytes_sha256: z.string(),
  votes: z.array(voteRecord),
});
export type ProposalDetail = z.infer<typeof proposalDetail>;

export const proposalDetailResponse = z.object({
  ok: z.literal(true),
  proposal: proposalDetail,
});

export const castVoteResponse = z.object({
  ok: z.literal(true),
  vote: z.object({
    id: z.number().int(),
    decision: z.string(),
    custody: z.enum(['device', 'server']),
    alg_id: z.string().nullable(),
    signature_sha256: z.string(),
    signed_at: z.string().nullable(),
  }),
  proposal: z.object({
    status: z.string(),
    approvals: z.number().int(),
    rejections: z.number().int(),
  }),
});
export type CastVoteResult = z.infer<typeof castVoteResponse>;
