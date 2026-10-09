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
  my_key: z.lazy(() => myKeySchema).nullable().optional(),
  // R3: the workspace this person works in. Null when an admin has removed them (Approvals says
  // so, §6.3); absent from an older server. A shape this app does not know is dropped, not fatal.
  workspace: z
    .object({
      id: z.number().int(),
      name: z.string(),
      role: z.string(),
      // P3, additive: the role as the interface writes it, and whether a vault created now stops
      // whoever raises a decision from approving it (plan S15).
      role_name: z.string().optional().catch(undefined),
      separation_of_duties_default: z.boolean().optional().catch(undefined),
    })
    .nullable()
    .optional()
    .catch(undefined),
  // R8: whether this server sends pushes, and holds this phone's token. Absent from an older one.
  push: z
    .lazy(() => pushStatus)
    .optional()
    .catch(undefined),
});
export type Me = z.infer<typeof meResponse>;
export const myKeySchema = z.object({
  custody: z.string(),
  key_id: z.number().int().nullable(),
  usable: z.boolean(),
});

export const devicesResponse = z.object({
  ok: z.literal(true),
  devices: z.array(deviceSchema),
});

export const revokeResponse = z.object({
  ok: z.literal(true),
  device: deviceSchema,
});

/**
 * Someone who could be made a signer.
 *
 * A name and an opaque id, and deliberately nothing else. The server does not send addresses to
 * the picker -- an address is a login identifier, and the device only needs something to show and
 * something to send back. See GET /people.
 */
export const person = z.object({
  user_id: z.number().int(),
  name: z.string(),
});
export type Person = z.infer<typeof person>;

export const peopleResponse = z.object({
  ok: z.literal(true),
  people: z.array(person),
});

export const vaultMember = z.object({
  user_id: z.number().int(),
  name: z.string().nullable(),
  email: z.string().nullable(),
  role: z.string(),
  is_me: z.boolean(),
  // P3, additive: whether they hold a key that can sign (phone-ux §6.14).
  has_key: z.boolean().optional().catch(undefined),
});
export type VaultMember = z.infer<typeof vaultMember>;

export const vaultSummary = z.object({
  vault_id: z.number().int(),
  name: z.string(),
  description: z.string().nullable(),
  role: z.string().nullable(),
  threshold_m: z.number().int().nullable(),
  signer_count: z.number().int(),
  member_count: z.number().int(),
  // Decisions in this vault still awaiting THIS signer -- not the number open overall.
  awaiting_me: z.number().int(),
  kem_alg_id: z.string().nullable(),
});
export type VaultSummary = z.infer<typeof vaultSummary>;

export const vaultsResponse = z.object({
  ok: z.literal(true),
  vaults: z.array(vaultSummary),
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
  // Display only, never signed: lets the queue find the payments whose treasury seat it must look
  // up (phone-ux §6.3). Absent from an older server; a wrong shape is dropped, never fatal.
  is_payment: z.boolean().optional().catch(undefined),
  // P3 and P4 (phone-ux §10.3: A1 to A4, A11, A17; R5), all unsigned display, each dropped rather
  // than refused when its shape is not the one this app knows.
  display_status: z
    .object({ key: z.string(), word: z.string(), tone: z.string() })
    .optional()
    .catch(undefined),
  can_still_approve: z.array(z.number().int()).optional().catch(undefined),
  can_still_pass: z.boolean().optional().catch(undefined),
  cannot_pass_why: z.array(z.string()).optional().catch(undefined),
  raised_by: z.object({ id: z.number().int(), name: z.string().nullable() }).nullable().optional().catch(undefined),
  separation_of_duties: z.boolean().optional().catch(undefined),
  can_withdraw: z.boolean().optional().catch(undefined),
  raised_again_from: z
    .object({ proposal_uuid: z.string(), title: z.string() })
    .nullable()
    .optional()
    .catch(undefined),
  raised_again_as: z
    .array(z.object({ proposal_uuid: z.string(), title: z.string() }))
    .optional()
    .catch(undefined),
  withdrawn_by: z.object({ id: z.number().int(), name: z.string().nullable() }).nullable().optional().catch(undefined),
  withdrawn_at: z.string().nullable().optional().catch(undefined),
  decision_type: z.string().nullable().optional().catch(undefined),
  signers: z
    .array(
      z.object({
        user_id: z.number().int(),
        name: z.string().nullable(),
        has_key: z.boolean().optional().catch(undefined),
      }),
    )
    .optional()
    .catch(undefined),
  decided_at: z.string().nullable().optional().catch(undefined),
  amount: z.string().nullable().optional().catch(undefined),
  seat: z.enum(['this_device', 'password', 'other_device']).nullable().optional().catch(undefined),
});
export type ProposalSummary = z.infer<typeof proposalSummary>;

export const proposalsResponse = z.object({
  ok: z.literal(true),
  proposals: z.array(proposalSummary),
  state: z.string(),
});

/** A change to a vault's rule, as before and after (R5; phone-ux §6.14, §6.21). Unsigned. */
export const ruleChange = z.object({
  event: z.string(),
  who: z.string(),
  when: z.string().nullable(),
  label: z.string(),
  before: z.string(),
  after: z.string(),
});
export type RuleChange = z.infer<typeof ruleChange>;

export const vaultDetail = vaultSummary.extend({
  members: z.array(vaultMember),
  proposals: z.array(proposalSummary),
  // P3, additive: separation of duties as it stands, and the latest rule changes.
  separation_of_duties: z.boolean().optional().catch(undefined),
  rule_changes: z.array(ruleChange).optional().catch(undefined),
});
export type VaultDetail = z.infer<typeof vaultDetail>;

export const vaultDetailResponse = z.object({
  ok: z.literal(true),
  vault: vaultDetail,
});

export const createProposalResponse = z.object({
  ok: z.literal(true),
  proposal: proposalSummary,
});

export const createVaultResponse = z.object({
  ok: z.literal(true),
  vault: vaultSummary,
});

// The payment inside a payment decision's signed payload, in exactly the shape the server signs
// (docs/plans/onchain-execution.md, D22). Strict for the same reason as the inputs below; every
// number must be a safe integer, which zod's int() already requires.
export const paymentActionSchema = z
  .object({
    kind: z.literal('eth_transfer'),
    chain_id: z.number().int(),
    treasury: z.string().regex(/^0x[0-9a-fA-F]{40}$/),
    to: z.string().regex(/^0x[0-9a-fA-F]{40}$/),
    value_wei: z.string().regex(/^(0|[1-9][0-9]*)$/),
    data: z.literal('0x'),
    call_gas: z.number().int(),
    valid_until: z.number().int(),
    // A count of reconfigurations (D42): never negative, which a signed-integer check alone allows.
    config_nonce: z.number().int().nonnegative(),
  })
  .strict();

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
    // Present only on payment decisions. The server sends it only to an app that declares the
    // payment capability, which this app does from Phase 6b (plan D25).
    action: paymentActionSchema.optional(),
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

export const payoutView = z.object({
  state: z.string(),
  reason: z.string().nullable(),
  tx_hash: z.string().nullable(),
  block_number: z.number().int().nullable(),
  gas_used: z.number().int().nullable(),
  execution_signatures: z.number().int(),
  needed: z.number().int(),
  finished_at: z.string().nullable(),
});
export type PayoutView = z.infer<typeof payoutView>;

export const proposalDetail = proposalSummary.extend({
  action_text: z.string(),
  signing_inputs: signingInputsSchema,
  payload_hash: z.string(),
  signing_bytes_sha256: z.string(),
  votes: z.array(voteRecord),
  // Payment decisions only: claims the phone checks before any prompt, never signs (Phase 6b).
  execution: z
    .object({
      digest: z.string().regex(/^[0-9a-f]{64}$/).nullable(),
      seat_fingerprint: z.string().nullable(),
    })
    .optional(),
  // Payment decisions only: how the payout stands (Phase 8). Shown, never signed.
  payout: payoutView.nullable().optional(),
  // Planned API fields (phone-ux §10.3: A1, A3, A4, R5), all unsigned display. Read when a server
  // sends them; a server that sends none, or a shape this app does not know, loses nothing but the
  // sentence they would add (`.catch` drops them rather than refusing the whole decision).
  raised_by: z.object({ id: z.number().int(), name: z.string().nullable() }).nullable().optional().catch(undefined),
  separation_of_duties: z.boolean().optional().catch(undefined),
  signers: z
    .array(z.object({ user_id: z.number().int(), name: z.string().nullable() }))
    .optional()
    .catch(undefined),
  decided_at: z.string().nullable().optional().catch(undefined),
  withdrawn_by: z.object({ id: z.number().int(), name: z.string().nullable() }).nullable().optional().catch(undefined),
  withdrawn_at: z.string().nullable().optional().catch(undefined),
  // R5 (S13, A13): a typed decision's stored type, its fields and the template version that wrote
  // its text. Unsigned: the phone writes the text again from them (src/logic/decisionTypes.ts) and
  // trusts them only when that is the signed text, byte for byte. Lenient on purpose: a shape this
  // app does not know means no typed card, never a refusal of the decision itself.
  fields: z.record(z.string(), z.unknown()).nullable().optional().catch(undefined),
  template_version: z.number().int().nullable().optional().catch(undefined),
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
    execution_signature_sha256: z.string().nullable().optional(),
    signed_at: z.string().nullable(),
  }),
  proposal: z.object({
    status: z.string(),
    approvals: z.number().int(),
    rejections: z.number().int(),
  }),
});
export type CastVoteResult = z.infer<typeof castVoteResponse>;

// -- treasury (plan D40, Phase 7b) ---------------------------------------------------------------

// Exactly what a treasury change's approvers sign; the phone recomputes the digest from these and
// never signs the server's. Strict, so a renamed field fails here rather than hashing differently.
export const reconfigureInputsSchema = z
  .object({
    chain_id: z.number().int().nonnegative(),
    treasury: z.string().regex(/^0x[0-9a-fA-F]{40}$/),
    config_nonce: z.number().int().nonnegative(),
    add: z.array(z.string()),
    remove: z.array(z.string()),
    threshold: z.number().int(),
    valid_until: z.number().int().nonnegative(),
  })
  .strict();

const identityOwner = z.object({
  user_id: z.number().int().nullable(),
  name: z.string().nullable(),
  key_fingerprint: z.string().nullable(),
});

export const reconfigurationView = z.object({
  id: z.number().int(),
  state: z.string(),
  reason: z.string().nullable(),
  requested_at: z.string(),
  valid_until: z.string(),
  threshold: z.number().int(),
  approvals: z.number().int(),
  needed: z.number().int(),
  approved_by_me: z.boolean(),
  approval_problem: z.string().nullable(),
  my_custody: z.enum(['password', 'device']).nullable(),
  // Claims the phone checks before any prompt, never inputs it signs.
  seat_fingerprint: z.string().nullable(),
  signing_inputs: reconfigureInputsSchema.nullable(),
  digest: z.string().regex(/^[0-9a-f]{64}$/).nullable(),
  confirmed_warnings: z.array(z.string()),
  tx_hash: z.string().nullable(),
  // Whose key each signed identity holds, in order, as the server describes it.
  people: z
    .object({ add: z.array(identityOwner), remove: z.array(identityOwner) })
    .nullable()
    .optional(),
});
export type ReconfigurationView = z.infer<typeof reconfigurationView>;

const changedPerson = z.object({ user_id: z.number().int(), name: z.string().nullable() });

export const treasuryChange = z.object({
  pending_change: z
    .object({
      added: z.array(changedPerson),
      removed: z.array(changedPerson),
      rotated: z.array(changedPerson),
      threshold_from: z.number().int(),
      threshold_to: z.number().int(),
    })
    .nullable(),
  may_request: z.boolean(),
  problems: z.array(z.string()).optional(),
  warnings: z.array(z.string()),
  warnings_digest: z.string().nullable().optional(),
  reconfiguration: reconfigurationView.nullable(),
});
export type TreasuryChange = z.infer<typeof treasuryChange>;

export const treasuryResponse = z.object({
  ok: z.literal(true),
  treasury: z
    .object({
      address: z.string().regex(/^0x[0-9a-fA-F]{40}$/),
      chain_id: z.number().int(),
      threshold_m: z.number().int(),
      signer_count: z.number().int(),
      linked_at: z.string(),
      signers: z.array(
        z.object({
          user_id: z.number().int(),
          custody: z.enum(['device', 'password']),
          key_active: z.boolean(),
        }),
      ),
    })
    .nullable(),
  job: z
    .object({
      id: z.number().int(),
      state: z.string(),
      reason: z.string().nullable(),
      requested_at: z.string(),
      updated_at: z.string(),
    })
    .nullable(),
  may_create: z.boolean(),
  change: treasuryChange.nullable().optional(),
  status: z
    .object({
      balance_wei: z.string().regex(/^(0|[1-9][0-9]*)$/).nullable(),
      balance: z.string().nullable(),
      payouts_left_today: z.number().int(),
      payouts_per_day: z.number().int(),
    })
    .nullable()
    .optional(),
  my_key: z
    .object({ custody: z.string(), key_id: z.number().int().nullable(), usable: z.boolean() })
    .nullable()
    .optional(),
});
export type TreasuryResponse = z.infer<typeof treasuryResponse>;

export const requestReconfigurationResponse = z.object({
  ok: z.literal(true),
  reconfiguration: reconfigurationView,
});

export const approveReconfigurationResponse = z.object({
  ok: z.literal(true),
  approval: z.object({ signature_sha256: z.string(), signed_at: z.string().nullable() }),
  reconfiguration: z.object({
    state: z.string(),
    approvals: z.number().int(),
    needed: z.number().int(),
  }),
});

export const signingChoiceResponse = z.object({
  ok: z.literal(true),
  my_key: z.object({
    custody: z.string(),
    key_id: z.number().int().nullable(),
    usable: z.boolean(),
  }),
});

export const createTreasuryResponse = z.object({
  ok: z.literal(true),
  job: z.object({ id: z.number().int(), state: z.string(), reason: z.string().nullable() }),
});

// --- Notifications (plan R4): the inbox the phone reads. ---------------------------------------
//
// A notification is a pointer, never an action: it names a decision (`proposal_uuid`), which the
// app opens on its own decision screen, where signing happens after the person has read what they
// sign. `path` is the web page for the same thing. `kind` is a plain string so a newer server's
// kinds still list; `title` and `body` are written by the server and shown as they are.

export const notificationSection = z.enum(['needs_you', 'updates', 'archived']);
export type NotificationSection = z.infer<typeof notificationSection>;

export const notificationSchema = z.object({
  id: z.number().int(),
  kind: z.string(),
  // null: a request already answered, or overtaken, which is in no list any more.
  section: notificationSection.nullable(),
  title: z.string(),
  body: z.string(),
  path: z.string(),
  actionable: z.boolean(),
  security: z.boolean(),
  unread: z.boolean(),
  created_at: z.string(),
  read_at: z.string().nullable(),
  archived_at: z.string().nullable(),
  actor: z.object({ id: z.number().int(), display_name: z.string() }).nullable(),
  vault: z.object({ id: z.number().int(), name: z.string() }).nullable(),
  proposal_uuid: z.string().nullable(),
});
export type AppNotification = z.infer<typeof notificationSchema>;

export const unreadCounts = z.object({
  needs_you: z.number().int(),
  updates: z.number().int(),
  total: z.number().int(),
});
export type UnreadCounts = z.infer<typeof unreadCounts>;

export const notificationsResponse = z.object({
  ok: z.literal(true),
  section: notificationSection,
  page: z.number().int(),
  per_page: z.number().int(),
  total: z.number().int(),
  has_more: z.boolean(),
  notifications: z.array(notificationSchema),
  unread: unreadCounts,
});

export const unreadResponse = z.object({
  ok: z.literal(true),
  unread: unreadCounts,
});

export const notificationResponse = z.object({
  ok: z.literal(true),
  notification: notificationSchema,
  unread: unreadCounts,
});

export const readAllResponse = z.object({
  ok: z.literal(true),
  marked: z.number().int(),
  unread: unreadCounts,
});

export const remindResponse = z.object({
  ok: z.literal(true),
  reminded: z.number().int(),
});

// --- P3 and P4 (phone-ux §6.21): withdraw, the discussion thread ------------------------------

export const withdrawResponse = z.object({
  ok: z.literal(true),
  proposal: proposalSummary,
});

/** One run of a comment: plain text, or a mention the server resolved (never one the app guessed). */
export const commentSegment = z.object({
  text: z.string(),
  mention: z.unknown().optional(),
});

export const commentSchema = z.object({
  id: z.number().int(),
  author: z.object({ id: z.number().int(), name: z.string().nullable() }),
  created_at: z.string().nullable(),
  deleted: z.boolean(),
  mine: z.boolean(),
  body: z.string(),
  segments: z.array(commentSegment).optional().catch(undefined),
});
export type Comment = z.infer<typeof commentSchema>;

export const commentsResponse = z.object({
  ok: z.literal(true),
  signed: z.boolean().optional(),
  note: z.string().optional(),
  can_post: z.boolean().optional(),
  comments: z.array(commentSchema),
  next_after: z.number().int().nullable().optional(),
});

// --- Phone push (plan R8). ----------------------------------------------------------------------
//
// Whether this server sends pushes and holds this phone's token. The token itself is never sent
// back. Absent from an older server, which sends no pushes.

export const pushStatus = z.object({ available: z.boolean(), registered: z.boolean() });
export type PushStatus = z.infer<typeof pushStatus>;

export const pushTokenResponse = z.object({ ok: z.literal(true), push: pushStatus });

export const pushGroupSchema = z.object({
  id: z.string(),
  label: z.string(),
  enabled: z.boolean(),
  locked: z.boolean(),
});

export const notificationSettingsResponse = z.object({
  ok: z.literal(true),
  push: pushStatus.extend({ groups: z.array(pushGroupSchema) }),
  email: z.object({ available: z.boolean() }),
});
export type NotificationSettings = z.infer<typeof notificationSettingsResponse>;
