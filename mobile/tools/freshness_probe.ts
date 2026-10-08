// Runs the phone's freshness rules under Node (phone-ux §2.6) for tests/test_mobile_freshness.py:
//
//   I-7   the signing gate: a network fetch made IN THIS PROCESS under a minute ago, recorded by the
//         decision's own query function, never `dataUpdatedAt`; a restored entry with a fresh
//         `dataUpdatedAt` cannot pass, nor can a copy that is not the object the fetch returned, nor
//         a fetch that was cancelled. While a sheet holds the decision, returning to the app
//         refetches it for no observer (I-6).
//   I-14  the dehydrate allow-list: of a cache holding every kind of query, only the three list
//         summaries are written, with only their summary fields; the seal is AES-256-GCM bound to
//         the buster; reading back drops anything old, foreign or not on the list.
//
// Also the retry rule, the cold-start hint's stages, the offline bar's time and the auth-prompt
// flag. Real React Query (query-core) and the app's own query options are used throughout. The
// network is a stub: no request leaves this process.
//
//   TZ=UTC node tools/freshness_probe.ts <output.json>

import { writeFileSync } from 'node:fs';
import { dehydrate, focusManager, QueryClient, QueryObserver } from '@tanstack/query-core';

import { ApiError, TransportError } from '../src/api/client.ts';
import { AUTH_PROMPT_GRACE_MS, authPromptInFlight, beginAuthPrompt, endAuthPrompt } from '../src/authPrompt.ts';
import { setApiBaseUrl } from '../src/config.ts';
import { isOffline, reportReached } from '../src/connectivity.ts';
import { signingInputsToPayloadHash, type SigningInputs } from '../src/crypto/signing.ts';
import {
  canOpenSigningSheet,
  coldStartStage,
  fetchKey,
  NetworkFetchLog,
  offlineSince,
  retryTransport,
  SIGN_FRESH_MS,
} from '../src/logic/freshness.ts';
import {
  CACHE_MAX_AGE_MS,
  cacheBody,
  openCache,
  readCacheBody,
  sealCache,
  shouldDehydrateQuery,
  SUMMARY_FIELDS,
  VAULT_FIELDS,
} from '../src/logic/persistence.ts';
import {
  allQuery,
  awaitingQuery,
  holdDecision,
  keys,
  networkFetches,
  proposalQuery,
  vaultsQuery,
} from '../src/queries.ts';

const out: Record<string, unknown> = {};
const NOW = Date.parse('2026-10-08T09:40:00Z');
const UUID = '00000000-0000-4000-8000-000000000001';
const EMAIL = 'ada@qvault.demo';
const RECIPIENT = '0x41Ed2b6f0C8fE4b1aC3D5e7F9a0B1c2D3e4F8A19';
const TREASURY = '0xD49174b703d6FBC5088b0f01C6E71B5Ef467f3D0';
const TOKEN = 'probe-bearer-token-must-never-be-written';

setApiBaseUrl('http://probe.invalid');

// -- fixtures ---------------------------------------------------------------------------------

const SIGNING: SigningInputs = {
  vault_id: 4,
  proposal_id: 'p-1',
  action_text: 'Pay the March back pay to the contractors.',
  file_sha256: null,
  policy: { M: 2, N: 3, signers: [1, 2, 3] },
  nonce: '6f'.repeat(16),
  created_at: '2026-10-08T09:00:00+00:00',
};

const SUMMARY = {
  proposal_uuid: UUID,
  title: 'Payroll adjustment schedule',
  vault_id: 4,
  vault_name: 'Treasury',
  status: 'open',
  required_m: 2,
  required_n: 3,
  approvals: 1,
  rejections: 0,
  expires_at: '2026-10-09T09:00:00+00:00',
  signed_by_me: false,
  can_sign: true,
  is_payment: false,
};

function detailResponse() {
  return {
    ok: true,
    proposal: {
      ...SUMMARY,
      action_text: SIGNING.action_text,
      signing_inputs: SIGNING,
      payload_hash: signingInputsToPayloadHash(SIGNING),
      signing_bytes_sha256: '00'.repeat(32),
      votes: [],
    },
  };
}

/** A summary as a careless server might send it: carrying signed text, an address and an email. */
const LEAKY_SUMMARY = {
  ...SUMMARY,
  action_text: SIGNING.action_text,
  signing_inputs: SIGNING,
  to: RECIPIENT,
  raised_by_email: EMAIL,
  nested: { secret: TOKEN },
};

// -- a stubbed network ------------------------------------------------------------------------

/** `ignoresAbort`: a network stack that answers anyway after the request was cancelled. */
type Reply = { status: number; body: unknown; delayMs?: number; ignoresAbort?: boolean };
let replies: Reply[] = [];
let requests = 0;

(globalThis as { fetch: unknown }).fetch = async (_url: string, init: { signal?: AbortSignal }) => {
  requests += 1;
  const reply = replies.shift() ?? { status: 200, body: detailResponse() };
  if (reply.delayMs) {
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(resolve, reply.delayMs);
      if (reply.ignoresAbort) return;
      init.signal?.addEventListener('abort', () => {
        clearTimeout(timer);
        reject(new Error('aborted'));
      });
    });
  }
  return {
    ok: reply.status >= 200 && reply.status < 300,
    status: reply.status,
    json: async () => JSON.parse(JSON.stringify(reply.body)),
  };
};

const client = () => new QueryClient({ defaultOptions: { queries: { retry: false } } });

// -- I-7: the signing gate --------------------------------------------------------------------

out.gate_table = Object.fromEntries(
  (
    [
      ['never fetched', undefined],
      ['null', null],
      ['not a number', Number.NaN],
      ['this instant', NOW],
      ['one second ago', NOW - 1_000],
      ['59.999 s ago', NOW - 59_999],
      ['exactly 60 s ago', NOW - SIGN_FRESH_MS],
      ['two minutes ago', NOW - 120_000],
      ['one second in the future', NOW + 1_000],
    ] as Array<[string, number | null | undefined]>
  ).map(([name, at]) => [name, canOpenSigningSheet(at, NOW)]),
);

async function gate() {
  const key = fetchKey(keys.proposal(UUID));
  const decisionKey = keys.proposal(UUID);

  // A decision put in the cache with a fresh `dataUpdatedAt` but no fetch in this process: what a
  // restore from disk would look like if decision bodies were ever persisted (they are not).
  const restored = client();
  restored.setQueryData(decisionKey, detailResponse(), { updatedAt: Date.now() - 1_000 });
  const state = restored.getQueryState(decisionKey)!;
  out.restored = {
    data_updated_at_is_fresh: canOpenSigningSheet(state.dataUpdatedAt, Date.now()),
    gate_on_process_record: canOpenSigningSheet(networkFetches.fetchedAt(key), Date.now()),
    signable: networkFetches.signable(key, restored.getQueryData(decisionKey), Date.now()),
    process_has_record: networkFetches.has(key),
  };

  // A real fetch through the decision screen's own query options.
  const live = client();
  requests = 0;
  replies = [{ status: 200, body: detailResponse() }];
  await live.fetchQuery(proposalQuery(TOKEN, UUID));
  const shown = live.getQueryData(decisionKey);
  const at = networkFetches.fetchedAt(key)!;
  out.fetched = {
    requests,
    recorded: networkFetches.has(key),
    signable_now: networkFetches.signable(key, shown, Date.now()),
    // The same content in a different object: not the answer of the recorded fetch.
    signable_equal_copy: networkFetches.signable(key, JSON.parse(JSON.stringify(shown)), Date.now()),
    signable_after_59s: networkFetches.signable(key, shown, at + 59_000),
    signable_after_60s: networkFetches.signable(key, shown, at + 60_000),
    signable_undefined: networkFetches.signable(key, undefined, Date.now()),
    structural_sharing_off: proposalQuery(TOKEN, UUID).structuralSharing === false,
    stale_at_once: proposalQuery(TOKEN, UUID).staleTime === 0,
  };

  // A second fetch with the same content still replaces the object (no structural sharing), and
  // the record follows it: the copy from before is no longer what was last fetched.
  replies = [{ status: 200, body: detailResponse() }];
  await live.fetchQuery({ ...proposalQuery(TOKEN, UUID), staleTime: 0 });
  const second = live.getQueryData(decisionKey);
  out.refetched = {
    new_object: second !== shown,
    old_copy_signable: networkFetches.signable(key, shown, Date.now()),
    new_copy_signable: networkFetches.signable(key, second, Date.now()),
  };

  // A fetch cancelled before its answer arrives records nothing.
  const cancelUuid = '00000000-0000-4000-8000-000000000002';
  const cancelKey = fetchKey(keys.proposal(cancelUuid));
  const cancelled = client();
  replies = [{ status: 200, body: detailResponse(), delayMs: 50 }];
  const pending = cancelled.fetchQuery(proposalQuery(TOKEN, cancelUuid)).catch(() => 'cancelled');
  await new Promise((r) => setTimeout(r, 5));
  await cancelled.cancelQueries({ queryKey: keys.proposal(cancelUuid) });
  await pending;
  await new Promise((r) => setTimeout(r, 80));
  out.cancelled = { recorded: networkFetches.has(cancelKey) };

  // Cancelled, but the answer still arrives and parses (the stack ignored the abort): React Query
  // throws it away, so it was never what the page shows, and it records nothing either.
  const lateUuid = '00000000-0000-4000-8000-000000000005';
  const late = client();
  replies = [{ status: 200, body: detailResponse(), delayMs: 50, ignoresAbort: true }];
  const latePending = late.fetchQuery(proposalQuery(TOKEN, lateUuid)).catch(() => 'cancelled');
  await new Promise((r) => setTimeout(r, 5));
  await late.cancelQueries({ queryKey: keys.proposal(lateUuid) });
  await latePending;
  await new Promise((r) => setTimeout(r, 80));
  out.cancelled_late_answer = {
    recorded: networkFetches.has(fetchKey(keys.proposal(lateUuid))),
    in_cache: late.getQueryData(keys.proposal(lateUuid)) !== undefined,
  };

  // A failed fetch records nothing either.
  const failUuid = '00000000-0000-4000-8000-000000000003';
  const failing = client();
  replies = [{ status: 500, body: { ok: false, code: 'unexpected', error: 'boom' } }];
  await failing.fetchQuery(proposalQuery(TOKEN, failUuid)).catch(() => null);
  out.failed = { recorded: networkFetches.has(fetchKey(keys.proposal(failUuid))) };

  // A fresh log (a new process) knows nothing, whatever the cache says.
  out.new_process = { signable: new NetworkFetchLog().signable(key, second, Date.now()) };

  // Held (a sheet open): returning to the app refetches nothing for any observer of the decision;
  // released, it refetches (stale at once).
  const heldUuid = '00000000-0000-4000-8000-000000000004';
  const watched = client();
  watched.mount();
  const observer = new QueryObserver(watched, proposalQuery(TOKEN, heldUuid));
  const unsubscribe = observer.subscribe(() => {});
  await new Promise((r) => setTimeout(r, 30));
  const focusOnce = async () => {
    const before = requests;
    focusManager.setFocused(false);
    focusManager.setFocused(true);
    await new Promise((r) => setTimeout(r, 30));
    return requests - before;
  };
  const release = holdDecision(heldUuid);
  const whileHeld = await focusOnce();
  release();
  const afterRelease = await focusOnce();
  unsubscribe();
  watched.unmount();
  out.focus_refetch = { while_held: whileHeld, after_release: afterRelease };
}

// -- I-14: what may be written ----------------------------------------------------------------

const BUSTER = '1:rework-1';
const KEY = Uint8Array.from({ length: 32 }, (_, i) => i + 1);
const NONCE = Uint8Array.from({ length: 12 }, (_, i) => 200 - i);

function fullCache(): QueryClient {
  const c = client();
  c.setQueryData(keys.awaiting, { ok: true, state: 'awaiting', proposals: [LEAKY_SUMMARY] });
  c.setQueryData(keys.all, { ok: true, state: 'all', proposals: [LEAKY_SUMMARY, { ...SUMMARY, proposal_uuid: 'x' }] });
  c.setQueryData(keys.vaults, {
    ok: true,
    vaults: [
      {
        vault_id: 4,
        name: 'Treasury',
        description: 'Payroll and payments',
        role: 'signer',
        threshold_m: 2,
        signer_count: 3,
        member_count: 4,
        awaiting_me: 1,
        kem_alg_id: null,
        members: [{ user_id: 1, name: 'Ada', email: EMAIL, role: 'owner', is_me: true }],
      },
    ],
  });
  c.setQueryData(keys.proposal(UUID), detailResponse());
  c.setQueryData(keys.me, { ok: true, user: { id: 1, email: EMAIL, display_name: 'Ada' } });
  c.setQueryData(keys.devices, { ok: true, devices: [{ id: 9, name: 'Probe phone', fingerprint: '0123456789abcdef' }] });
  c.setQueryData(['treasury', 4], { ok: true, treasury: { address: TREASURY, signers: [{ address: RECIPIENT }] } });
  c.setQueryData(keys.vault(4), { ok: true, vault: { members: [{ email: EMAIL }], proposals: [LEAKY_SUMMARY] } });
  c.setQueryData(['people'], { ok: true, people: [{ user_id: 2, name: 'Brij' }] });
  c.setQueryData(['session', 'token'], { token: TOKEN });
  return c;
}

function persistence() {
  const c = fullCache();
  const dehydrated = dehydrate(c, { shouldDehydrateQuery });
  out.dehydrated_keys = dehydrated.queries.map((q) => q.queryKey);
  // What `dehydrate` would write with no allow-list: every key, as a contrast.
  out.default_dehydrated_count = dehydrate(c).queries.length;

  const body = cacheBody(dehydrated, BUSTER, NOW);
  const parsed = JSON.parse(body) as { queries: Array<{ key: unknown[]; data: Record<string, unknown> }> };
  out.body = body;
  out.written_keys = parsed.queries.map((q) => q.key);
  out.summary_fields_written = [
    ...new Set(
      parsed.queries
        .filter((q) => q.key[0] === 'proposals')
        .flatMap((q) => (q.data.proposals as Array<Record<string, unknown>>).flatMap((p) => Object.keys(p))),
    ),
  ].sort();
  out.vault_fields_written = [
    ...new Set(
      parsed.queries
        .filter((q) => q.key[0] === 'vaults')
        .flatMap((q) => (q.data.vaults as Array<Record<string, unknown>>).flatMap((v) => Object.keys(v))),
    ),
  ].sort();
  out.summary_fields_allowed = [...SUMMARY_FIELDS].sort();
  out.vault_fields_allowed = [...VAULT_FIELDS].sort();

  // Errors and pending fetches are not written; nor is a list the query options did not allow.
  const partial = client();
  partial.setQueryData(keys.vaults, { ok: true, vaults: [] });
  void partial.prefetchQuery({ queryKey: keys.awaiting, queryFn: () => new Promise(() => {}) });
  out.pending_or_missing_written = dehydrate(partial, { shouldDehydrateQuery }).queries.map((q) => q.queryKey);

  // The app's own list options are the keys on the list, so their answers are what is written.
  out.list_option_keys = [awaitingQuery(TOKEN).queryKey, allQuery(TOKEN).queryKey, vaultsQuery(TOKEN).queryKey];

  // The seal.
  const sealed = sealCache(KEY, NONCE, body, BUSTER);
  const wrongKey = KEY.slice();
  wrongKey[0] ^= 1;
  const env = JSON.parse(sealed) as { v: number; n: string; c: string };
  const flipped = JSON.stringify({ ...env, c: (env.c[0] === 'A' ? 'B' : 'A') + env.c.slice(1) });
  out.seal = {
    sealed_has_no_title: !sealed.includes('Payroll'),
    sealed_has_no_text: !sealed.includes('contractors'),
    round_trip: openCache(KEY, sealed, BUSTER) === body,
    wrong_key: openCache(wrongKey, sealed, BUSTER),
    other_person: openCache(KEY, sealed, '2:rework-1'),
    other_runtime: openCache(KEY, sealed, '1:rework-2'),
    changed_byte: openCache(KEY, flipped, BUSTER),
    garbage: openCache(KEY, 'not json', BUSTER),
    short_key: openCache(KEY.slice(0, 16), sealed, BUSTER),
  };

  // Reading back.
  const read = readCacheBody(body, BUSTER, NOW + 60_000);
  out.read = {
    keys: read?.map((e) => e.key) ?? null,
    awaiting_title: (read?.find((e) => e.key[1] === 'awaiting')?.data as { proposals: Array<{ title: string }> })
      ?.proposals[0]?.title,
    other_buster: readCacheBody(body, '2:rework-1', NOW),
    eight_days_later: readCacheBody(body, BUSTER, NOW + CACHE_MAX_AGE_MS + 1),
    six_days_later_count: readCacheBody(body, BUSTER, NOW + 6 * 24 * 3600 * 1000)?.length ?? null,
    future_file: readCacheBody(body, BUSTER, NOW - CACHE_MAX_AGE_MS - 1),
    bad_json: readCacheBody('{', BUSTER, NOW),
  };

  // A file holding more than this build writes (a decision body, a summary with signed text): the
  // decision is dropped, the summary cut back to its fields.
  const doctored = JSON.stringify({
    v: 1,
    savedAt: NOW,
    buster: BUSTER,
    queries: [
      { key: ['proposal', UUID], at: NOW, data: detailResponse() },
      { key: ['me'], at: NOW, data: { ok: true, user: { email: EMAIL } } },
      { key: ['proposals', 'awaiting'], at: NOW, data: { ok: true, state: 'awaiting', proposals: [LEAKY_SUMMARY] } },
      { key: ['vaults'], at: NOW - CACHE_MAX_AGE_MS - 5, data: { ok: true, vaults: [] } },
      { key: ['proposals', 'all'], at: NOW, data: { ok: true, state: 'all', proposals: [{ title: 'missing fields' }] } },
    ],
  });
  const back = readCacheBody(doctored, BUSTER, NOW);
  out.doctored = { keys: back?.map((e) => e.key) ?? null, text: JSON.stringify(back) };

  // Characters outside ASCII survive the seal (the body is written as \u escapes).
  const accented = client();
  accented.setQueryData(keys.awaiting, {
    ok: true,
    state: 'awaiting',
    proposals: [{ ...SUMMARY, title: 'Café ✓ 日本 😀' }],
  });
  const accentedBody = cacheBody(dehydrate(accented, { shouldDehydrateQuery }), BUSTER, NOW);
  const reopened = openCache(KEY, sealCache(KEY, NONCE, accentedBody, BUSTER), BUSTER);
  const entries = reopened ? readCacheBody(reopened, BUSTER, NOW) : null;
  out.unicode = {
    body_is_ascii: /^[\x00-\x7f]*$/.test(accentedBody),
    title: (entries?.[0]?.data as { proposals: Array<{ title: string }> } | undefined)?.proposals[0]?.title ?? null,
  };
}

// -- the rest of §2.6 -------------------------------------------------------------------------

function rest() {
  out.retry = {
    transport_first: retryTransport(0, new TransportError('x')),
    transport_second: retryTransport(1, new TransportError('x')),
    api_error: retryTransport(0, new ApiError('unexpected', 'x', 500)),
    unauthorised: retryTransport(0, new ApiError('unauthorized', 'x', 401)),
  };
  out.cold_start = Object.fromEntries([0, 3_999, 4_000, 19_999, 20_000, 60_000].map((ms) => [String(ms), coldStartStage(ms)]));
  out.offline_since = {
    today: offlineSince(Date.parse('2026-10-08T09:40:00Z'), NOW),
    earlier_today: offlineSince(Date.parse('2026-10-08T07:05:00Z'), NOW),
    another_day: offlineSince(Date.parse('2026-10-04T10:24:00Z'), NOW),
    never: offlineSince(0, NOW),
    undefined: offlineSince(undefined, NOW),
  };

  const t = 1_000_000;
  const prompt: Record<string, boolean> = { before: authPromptInFlight(t) };
  beginAuthPrompt();
  prompt.during = authPromptInFlight(t + 30_000);
  endAuthPrompt(t + 30_000);
  prompt.just_after = authPromptInFlight(t + 30_000 + AUTH_PROMPT_GRACE_MS - 1);
  prompt.after_grace = authPromptInFlight(t + 30_000 + AUTH_PROMPT_GRACE_MS);
  out.auth_prompt = prompt;
}

async function connectivity() {
  reportReached();
  const before = isOffline();
  replies = [];
  const failingFetch = (globalThis as { fetch: unknown }).fetch;
  (globalThis as { fetch: unknown }).fetch = async () => {
    throw new TypeError('Network request failed');
  };
  const c = client();
  await c.fetchQuery(vaultsQuery(TOKEN)).catch(() => null);
  const afterFailure = isOffline();
  (globalThis as { fetch: unknown }).fetch = failingFetch;
  replies = [{ status: 401, body: { ok: false, code: 'unauthorized', error: 'no' } }];
  await c.fetchQuery({ ...vaultsQuery(TOKEN), staleTime: 0 }).catch(() => null);
  out.connectivity = { before, after_failure: afterFailure, after_any_answer: isOffline() };
}

await gate();
persistence();
rest();
await connectivity();
writeFileSync(process.argv[2], JSON.stringify(out, null, 1));
