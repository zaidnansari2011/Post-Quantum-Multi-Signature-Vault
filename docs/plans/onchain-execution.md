# Plan: approved decisions that execute on Sepolia

**Status:** APPROVED 2026-09-17 (D4 and D14 confirmed, on condition D15 holds) · **Started:** 2026-09-17 · **Owner actions:** [§2.8](../OWNER-ACTIONS.md)

This is the working plan. Build in the order below: tick each box when it is done, and add a row to
the [progress log](#progress-log) when a phase lands. If the plan turns out wrong, change the plan
here first, then the code.

---

## 1. Goal

A vault whose decisions **do something real**. When a Treasury payment reaches M-of-N approvals, a
contract on Sepolia pays the recipient. The contract checks the approvers' **ML-DSA-65 signatures
itself**, so neither Q-Vault's server nor the account that sends the transaction can move funds
without them.

**The demo this enables:**
1. Raise "Pay 0.0001 ETH to <address>".
2. Two approvers sign, one of them on the phone.
3. The payment lands. Etherscan shows the transaction, and it carries the decision's
   `payload_hash`.
4. Repeat, but tamper with the recipient in the database after approval. Nothing moves, and
   Etherscan confirms it.

## 2. Already proven (before any of this plan)

Tested in a local Foundry run on 2026-09-17, against the actual libraries and not their
documentation:

- Signatures from Q-Vault's own `MLDSA65Provider` (quantcrypt) verify under a second implementation
  (`@noble/post-quantum`), and on ZKNox's Solidity ML-DSA-65 verifier.
- A 2-of-3 treasury built on OpenZeppelin `MultiSignerERC7913` paid out. It rejected a replay, a
  changed recipient, a raised amount, a single signature, and the same signer twice (10/10).
- Measured gas: one verification ~1.54M; a payout with 2 signatures 3.15M, with 3 signatures
  4.70M. That fits about 10 signatures under the per-transaction limit (16,777,216).
- Measured one-off costs: F1600 helper 4.39M, verifier 4.91M, each signer key ~8.8M,
  treasury 1.25M.
- `eth-account` and `eth-abi` install on Windows with Python 3.13.

## 3. Design decisions

Each decision has a reason and the alternative that was rejected. **⚑ marks decisions the owner
should confirm before Phase 4.**

| # | Decision | Why | Rejected alternative |
|---|---|---|---|
| D1 | Verify signatures **on-chain**, with ZKNox `ZKNOX_dilithium65` pinned at commit `4c370bb` (branch `mldsa-65`; fetched since 2026-09-17 from the owner's fork `zaidnansari2011/ETHDILITHIUM`, tag `qvault-pin-4c370bb`, so the commit cannot vanish with the unmerged upstream branch) | Keeps ML-DSA-65, the vault's current algorithm. Measured and working. | ZKNox's deployed ML-DSA-44 verifier, which would mean changing the vault's algorithm |
| D2 | M-of-N logic comes from **OpenZeppelin `MultiSignerERC7913` v5.7.0**; we write only a thin treasury | Widely used, standard interface (ERC-7913), less code of our own to trust | A hand-written multisig loop |
| D3 | The relayer (an ECDSA account) **only pays gas** and **lives inside the app**, run by the scheduler like the witness sync | Recipient, amount, chain, contract and decision are all signed by the approvers, so the relayer key has no authority. A separate process would add operational cost and no security. | A separate executor process holding a key with authority |
| D4 ✔ | **The payment becomes part of the signed proposal.** When a proposal has an action, the canonical payload gains an `action` object. Proposals without one are unchanged byte for byte. | Every approver signs the machine-readable payment, not only prose describing it | Signing only the text, with the payment appearing in a second signature (the payload is never mistaken for the payment) |
| D5 | The action's text is **generated from the action**, and the proposer cannot edit it | Text and payment can never disagree | A free-text field plus separate recipient and amount fields |
| D6 | An approval on a payment proposal carries **a second signature**, over the 32-byte execution digest the contract checks | The contract cannot parse Q-Vault's canonical JSON; a digest is the standard approach. Vote signatures, ledger, verifiers and receipts stay exactly as they are. | Replacing the vote signature, which would ripple through every verifier |
| D7 | On-chain `proposalId` = the decision's **`payload_hash`** | Anyone can match the Etherscan event to the decision record without asking Q-Vault | A new identifier |
| D8 | Execution digest = `keccak256(abi.encode(TAG_EXECUTE, chainid, treasury, payload_hash, to, value, keccak256(data), callGas, validUntil))` (last two added by D18) | Binds chain, contract, decision, recipient, amount and calldata. `data` lets ERC-20 transfers be added later without redeploying. | A digest without chain or contract (replayable), or ETH-only |
| D9 | The treasury can **change its own signer set** (`reconfigure`), authorised by the current M-of-N | Key rotation (ADR-0007) would otherwise lock approvers out, and redeploying costs ETH | No reconfiguration, which means redeploying after every rotation |
| D10 | Contracts live in `chain/` as a Foundry project; dependencies are **git submodules pinned to commits** | Standard Foundry practice; exact versions are auditable | Copied sources, which lose provenance |
| D11 | Python uses **`eth-account` + `eth-abi`**; ML-DSA key expansion for the contract is **ported to Python** and checked byte for byte against ZKNox's JS | No hand-rolled secp256k1 or RLP. The app must register keys without Node. | Calling Node from Python, or `web3.py` (heavier, not needed) |
| D12 | Cross-implementation fixtures: **Python writes the test vectors and Foundry consumes them**, with the same file checked from both sides | Agreement between two implementations is evidence, in the style of `test_offline_verifier.py` | Separate vectors per side |
| D13 | Amounts are stored as **decimal-string wei** in the signed JSON | JS numbers cannot hold 10^18 exactly, and the phone and browser verifiers recompute the hash | JSON numbers |
| D14 ✔ | **Order: web approvals first, phone second** (Phase 6a/6b). **This is build order only, not a reduced scope for the phone.** | Gets a working end-to-end payout sooner; the phone needs an OTA release | Both at once |
| D15 ✔ | **The phone does everything the web can** (owner requirement, 2026-09-17). Payment decisions stay behind `ONCHAIN_EXECUTION_ENABLED` (off by default) until every row of the [parity checklist](#parity-checklist) passes on **both** web and phone. | The phone app is a first-class approver (ADR-0022), not a lesser client. Between Phase 6a and 6b the web would otherwise be able to do something the phone can't, so the flag keeps that from ever reaching a user. | Shipping web first and letting the phone catch up |
| D17 | **A signer's identity commits to its key's content**: `verifier (20) ‖ pointer0 (20) ‖ pointer1 (20) ‖ codehash0 (32) ‖ codehash1 (32)` = 124 bytes. On adding a signer, the treasury requires: (a) each pointer to hold **canonical SSTORE2 storage**, exactly 20,161 bytes starting with a `0x00` STOP byte; (b) each pointer's code hash to match; and (c) **no current signer to share its key**, where the key is identified by `keccak256(tr)` read from half 0, the 64 bytes the verifier itself feeds into every signature check. *(Review finding 1, and re-review findings 2 and 3, 2026-09-17.)* | Pointer addresses alone commit to nothing until code exists. Anyone can call `setKey`, so a front-runner could put a key anyone can forge for (all-zero A and t1) at a predicted address, or register one real key under two handles so one approver counts twice. The re-review found two more gaps. First, an empty address's code hash (0) passed check (b), leaving the key to whoever deploys there later; (a) closes that, and the STOP prefix also means storage can never self-destruct and be replaced. Second, comparing whole-blob hashes let a re-encoding of the same key (e.g. half 1's unused copy of `tr` changed) count twice. Any encoding that verifies an honest holder's signatures must carry the same half-0 `tr`, so (c) is robust. The verifier reads only the first 40 bytes of the handle, so the extra 64 cost nothing at verification. **Residual:** the contract cannot check the content is a *genuine* key (an all-zero key with honest hashes still passes), so whoever links, and every approver of a reconfiguration, must compute the identity from the real public key. | Pointer-only identities trusting whoever links; whole-blob duplicate check |
| D18 | **Approvals expire and carry their gas:** the execution digest adds `callGas` and `validUntil` (both uint64); `reconfigure` adds `validUntil`. The contract refuses after the deadline, requires enough gas left to give the call exactly `callGas`, and forwards exactly that. Calldata is capped at **4,096 bytes** so that copying it can never eat into that guarantee. *(Review findings 2 and 6; re-review finding 4.)* | A transaction that reverted still publishes a valid approval in its calldata, so without a deadline it could be replayed months later. A submitter choosing the gas limit could otherwise burn a decision against a target that swallows its own errors. Memory for calldata is paid after the gas check, and at ~64 KB it measurably shorted the callee. Q-Vault's calls are 0–68 bytes. **Costs:** an approval whose `callGas` is too low can never execute and must be re-approved (Phase 4 picks a generous default), and deadlines need an application policy (Phase 4). | No deadline, plus a separately approved `cancel` (more surface, same effect); no calldata cap |
| D19 | **Threshold capped at 8** (`MAX_THRESHOLD`), enforced on every path that sets it | Measured: 10 signatures use ~16.04M of the 16,777,216 per-transaction gas cap, and 11 cannot execute at all, which would lock funds forever. 8 leaves real headroom against future gas repricing. | A cap only at linking time (review finding 3) |
| D20 | **Never broadcast a transaction that fails simulation**, the tamper demo included; the executor reconciles state from `Executed` events and treats `AlreadyExecuted` as success | Every broadcast approval is usable by anyone until it expires (D18), and anyone may submit | Broadcasting failures so Etherscan shows a revert |
| D21 | **The relayer never has two transactions that could both land.** A new transaction always takes the account's *confirmed* nonce; nothing new is signed while one of the account's transactions is pending (`RelayerBusy`); a send with no usable answer is `SendOutcomeUnknown`, settled later by `status()` as mined, pending, unknown or **superseded** (nonce used by another transaction ≥ 12 blocks ago); a stuck transaction is replaced only at its own nonce with fees ≥ 12.5% higher. *(Phase 2 review, findings M2–M7.)* | Any two transactions that might both be in flight then share a nonce, so the chain itself admits at most one: a retry can never become a second payment, deployment or `setKey`. Because nothing of the account's is pending when a transaction is simulated, a simulation at `latest` already reflects the relayer's own effects (without this, a second `execute` of one proposal passed simulation and reverted on chain). Only `superseded` licenses signing at a new nonce; the 12-block margin stops a load-balanced provider whose receipt lookup lags from making a mined transaction look superseded. | Tracking a local "next nonce" from the pending count (the first build): verified by the review to double-pay after a lost send, and to wedge after a reservation that could never be filled |
| D22 | **The signed `action` has one fixed shape.** Exactly these keys, all required: `kind` (`"eth_transfer"`), `chain_id` (number), `treasury` and `to` (EIP-55 checksummed strings), `value_wei` (decimal string, no sign or leading zeros, 1 ≤ value < 2^256), `data` (`"0x"`, lowercase hex; always empty for `eth_transfer`), `call_gas` and `valid_until` (numbers). Every number is a JS safe integer (≤ 2^53 − 1). One strict parser in `qvault/chain/action.py` builds and validates it; the verifiers only hash what was signed. | Four implementations hash these bytes, and two are JavaScript: a number past 2^53 silently loses precision in a browser and is refused by the phone, and an address that could be written two ways would hash two ways. `kind` and `data` are there so ERC-20 transfers could be added later without changing the shape of payments already signed. | Free-form objects; numbers as JSON floats; lowercase addresses (a typo cannot be caught by checksum) |
| D23 | **Policy fixed at creation, and signed:** `call_gas` = 100,000 for an ETH transfer; a payment decision must have a deadline (default 7 days, at most 30); `valid_until` = the deadline + a 72-hour execution window. Creation also refuses if the vault's current threshold differs from its treasury's. | 100,000 covers a contract wallet as recipient (an EOA uses none of it) and costs nothing unless used, because unused `callGas` is not charged: the gas *limit* rises, the gas *spent* does not (D18). The window lets the executor ride out an outage or a fee spike after approval, and a bounded deadline means no approval stays spendable for more than 33 days. A threshold mismatch would mean the web says 2-of-3 while the contract says otherwise. | A configurable `call_gas` (a proposer could set one that can never execute); open-ended validity |
| D24 | **The decision text is generated from the action** (D5 made concrete): *"Pay 0.0001 ETH from this vault's treasury 0x… to 0x… on Sepolia."* Amounts are formatted from wei exactly, never through a float. The proposer writes the title only. | The prose and the payment cannot disagree, and a verifier that shows only the text still shows the right amount. | A proposer-written description beside the payment |
| D25 | **Old phone apps refuse payment decisions with a clear message.** The API sends `signing_inputs.action` only for payment decisions, and only to clients that declare the capability (`X-QVault-Capabilities: payment-action-1`); any other device client gets HTTP 426 `upgrade_required` for that decision and cannot vote on it. The phone app declares the capability only in Phase 6b, when it can also produce the execution signature. | An app that cannot compute the new hash already refuses (its schema is strict), but with "unexpected format". An explicit code turns that into "update the app", and the gate means a half-capable app can never approve a payment. | Relying on the strict schema alone |
| D26 | **A decision bundle that carries an action is `qvault.decision/2`.** `/1` bundles must not contain `action`; `/2` bundles must. Both verifiers accept both formats. | A verifier from before this change, including one embedded in an already exported HTML record, then says "unsupported format" instead of reporting a genuine payment decision as tampered. | Keeping `/1` and adding a field that old verifiers would silently ignore |
| D27 | **Tables are complete from the start.** `treasuries` and `proposal_actions` are created in Phase 4 with every column Phases 5–7 need (deployment transaction and block, link status, the signed action copied field by field). | `db.create_all()` never adds a column to an existing table (§4), so a column forgotten now could only be added by a manual migration later. | Adding columns phase by phase |
| D28 | **Linking runs on the owner's machine against the demo database** (Azure Postgres, reached by `DATABASE_URL`), from `scripts/link_treasury.py`. The script opens the app without its startup writes (`AUTO_CREATE_DB=false`, `SCHEDULER_ENABLED=false`). A dry run writes nothing anywhere (with `AUTO_CREATE_DB=false` startup neither creates tables nor seeds; review M3); a real link creates only `treasuries` and `treasury_signers` if they are missing, and leaves anchoring and checkpointing the log to the live app, which signs with its own key and origin (review M2). The relayer key stays in the local `.env` until the executor needs it on Azure (Phase 7). | Every earlier write to the Azure database was made this way (`migrate_to_postgres.py`, `seed_team.py`), and there is no way into the container. Production runs an image from before this plan, so the app's normal startup against its database (every table, seeding, a second scheduler) would make writes nobody asked for. | An admin HTTP endpoint that spends ETH (new attack surface); moving the relayer key to Azure now |
| D29 | **One registered key per signer, chosen when linking.** By default a signer's active password key; `--device <username>` registers that signer's one active phone key instead. The choice is stored per signer in a new `treasury_signers` table (treasury, user, key row, on-chain key id, both pointers, the 124-byte identity), so Phases 6a/6b can require a payment approval to come from the registered key and say where to approve. | The contract de-duplicates signers by key (`keccak256(tr)`), not by person. Registering someone's password key and phone key would let that one person provide two of the M signatures, and anyone may submit to the contract directly. *(D27 missed per-signer rows. A new table is still created by `create_all`, so nothing existing is altered.)* | Registering every key a signer holds |
| D30 | **Look before paying; chain first, database last.** Before a `setKey`, the linker looks among the verifier's contracts for canonical storage of exactly that key (code equal to `0x00 ‖ half`) and reuses it. Before deploying, it looks among the relayer's own deployments for a treasury that already passes the D31 check and is not in the `treasuries` table. After a `setKey` confirms, its pointers are found in the verifier's nonce range at the confirming block and accepted only when their code reads back equal: never predicted. The database is written once, in one transaction (treasury, signer rows, `treasury_linked` ledger entry), after the D31 check passes on finalized blocks and after the vault is read again: if its signers, its threshold or a chosen key changed while the link ran, nothing is written and the next run links the vault as it is then (review M1). A treasury adopted this way has its deployment transaction found again from the chain (review L1). | With D21, a re-run after a crash at any point cannot pay twice for the same key or treasury, and needs no stored transactions. The database never holds a half-linked treasury. `setKey` emits no event, so otherwise its pointers are only a return value. | Recording each step in the database (half-linked states to clean up); predicted pointer addresses (review finding 1) |
| D31 | **What linking verifies from the chain before anything is stored:** the chain id; the verifier is the recorded one with the recorded runtime hash; the treasury's runtime equals the committed artefact with only the `_VERIFIER` immutable masked, and that immutable is the verifier; `verifier()`; `threshold()` = the vault's M; `getSignerCount()` = N; `getSigners` equals, as a set, the identities computed from the database's public keys; `configNonce()` = 0; every pointer's code equals `0x00 ‖ half` of its key; every block involved is finalized and canonical. `link_treasury.py --check` re-runs it read-only. | The D17 residual: the contract cannot tell a genuine key from a well-formed one, so the linker computes every identity from the real public key and trusts nothing it has not read back, its own transactions included. | Trusting the constructor arguments it sent |
| D32 | **The treasury's bytecode is a committed artefact**, `qvault/chain/artifacts/QVaultTreasury.json` (ABI, creation and runtime code, immutable references, compiler settings), exported from `forge build` by `scripts/export_treasury_artifact.py`. The CI `contracts` job rebuilds and fails if the committed file differs. | The image excludes `chain/out` and `chain/lib` (`.dockerignore` already anticipates this); Phase 7 runs on Azure without Foundry but must still recognise the treasury's code; and byte equality ties what is deployed to reviewed source. Etherscan verification uses the same build. | Reading `chain/out` at run time; deploying with `forge script` |
| D33 | **Refuse before spending.** A dry run is the default; `--broadcast` is required to spend. The dry run prints the vault, each signer with the key and custody to be registered, keys already on chain, the estimated gas and cost of each step at the current fee, and the balance each step needs up front. It refuses clearly when a signer has no eligible key (SLH-DSA, ML-DSA-87, no active key, or not exactly one phone key under `--device` whose phone can still sign in, review M5), when two signers share a key, when N > 10, M > 8 or M > N (review M4), when the vault is already linked, when the database lacks a column the link uses, when the base fee is above the D21 policy, or when the balance cannot cover the whole sequence. | The relayer holds ~0.039 ETH for a ~0.03 ETH link. A link that stops halfway loses nothing (D30), but the owner should see the cost and the keys before approving a broadcast. | Broadcasting by default |
| D34 | **A payment requires the vault's signers to be exactly the treasury's.** Creating a payment compares the vault's signer user ids with the treasury's `treasury_signers`, not only their number. Changing a linked vault's members or threshold stays allowed; payments are refused until the treasury is unlinked (`link_treasury.py --unlink`, which changes nothing on chain) and the vault linked again (a reconfiguration flow is out of scope). Payments are also refused while fewer than M of the registered keys can still sign (review L4). | Swapping one member keeps N the same, while the newcomer has no key on the treasury and the person who left still has one. | Blocking membership changes on linked vaults |
| D16 ✔ | **Reseeding cannot silently break a linked treasury.** `seed_demo.py --reset` refuses while a treasury is linked, unless given `--unlink-treasury`, which states what is lost and what relinking costs. | Reseeding creates new keys, so the old approvers can never sign again, and `reconfigure` can't fix it because it needs those old keys | Relying on remembering not to do it |

## 4. How it fits together

```
propose (web/phone)          vote (web: password key / phone: device key)
  action{to,value,...}   ─►   vote sig over DS_VOTE bytes          (unchanged)
  text rendered from it       exec sig over execution digest (D8)  (new, approvals only)
  bound into payload_hash
                                           │ M approvals reached
                                           ▼
scheduler: execution job ── re-check binding + tally + exec sigs off-chain
                         ── eth_call simulate ── sign tx (relayer) ── send
                         ── wait for receipt ── ledger `proposal_executed` {tx, block}
                                           │
Sepolia: QVaultTreasury.execute(payload_hash, to, value, data, callGas, validUntil, multisig)
         └─ MultiSignerERC7913 ─► ZKNOX_dilithium65.verify ×M ─► pay
```

**New tables.** Existing tables are never altered; the project relies on `db.create_all()`:
`treasuries`, `proposal_actions`, `treasury_signers` (D29), `execution_signatures`, `executions`.

**Where the signed-payload rules live.** All four must change together in Phase 4:
`qvault/services/signing.py` · `qvault/verify/core.py` · `qvault/static/verifier.src.html` (then
rebuild) · `mobile/src/crypto/signing.ts`.

---

## 5. Phases

Every phase ends with: tests green (pytest, and forge where relevant) → an adversarial review by a
subagent → fixes → **one commit** → a progress-log row.

### Phase 1: Contracts, and the Python they are tested against · no ETH

*(Reordered 2026-09-17: the contract tests need real quantcrypt signatures over the on-chain digest,
so the digest, the key expansion and the fixture generator move here from Phase 2.)*

- [x] `chain/` Foundry project: `foundry.toml` (solc 0.8.30, via-IR, evm `osaka`), submodules pinned: ETHDILITHIUM `4c370bb`, OpenZeppelin `v5.7.0`, forge-std
- [x] `QVaultTreasury.sol`: `execute`, `reconfigure` (with a config nonce), `executed` mapping, events, `receive`; no owner or admin; every signer must be a 124-byte identity naming this treasury's verifier (D17)
- [x] Add dependencies to `requirements.txt` and the lock file; confirm wheels exist for win/cp313, linux/cp313 and linux/cp312 (Docker)
- [x] `qvault/chain/digest.py`: execution and reconfigure digests
- [x] `qvault/chain/mldsa_key.py`: ML-DSA-65 public key → expanded on-chain blob (ExpandA, NTT(t1·2¹³), tr); checked byte for byte against a reference vector from ZKNox's JS
- [x] `scripts/gen_chain_fixtures.py` → `chain/test/fixtures/*.json` (keys, quantcrypt signatures, digests, blobs); Foundry tests consume it, and pytest checks the same file
- [x] Foundry tests: port the 10 scratch tests, add `reconfigure` (add/remove/threshold, replay), generic call data, a reentrancy attempt, a foreign-verifier signer, and fuzzing of the digest fields
- [x] Deploy script (forge) for the helper and verifier, with Etherscan verification. It only prints addresses; recording happens in Phase 3 from confirmed receipts (review finding 4)
- [x] CI: a `contracts` job (foundry-toolchain, pinned submodules only, `forge test`); `.dockerignore` excludes only `chain/lib`, `out`, `cache`, `broadcast` (review findings 9, 10)
- [x] **Adversarial review (2026-09-17) fixes:** D17 content-bound signers + duplicate-key rejection; D18 `callGas` + `validUntil`; D19 threshold cap; lower-threshold reconfigure scenario; negatives for unreachable threshold, non-member removal, empty/extra-invalid multisig, arbitrary submitter, expiry, insufficient gas, key-content mismatch; `reconfigure` fuzzing; fix the vacuous ordering test; gas measured at the cap
- [x] **Re-review (2026-09-17) fixes:** canonical pointer storage + `tr`-based key identity (D17); moving a key to new pointers in one reconfiguration; 4,096-byte calldata cap (D18); the starvation test really asserts, plus a boundary test proving the callee receives exactly `callGas` at the lowest gas that succeeds; fuzzing changes one field per run; `signer_blob` takes the public key, not a blob; doc drift; justified suppression of the `block-timestamp` lint
- **Done when:** `forge test` and pytest are green locally and in CI, both agree on the same fixture, and the gas figures are recorded in this file.
  Locally green on 2026-09-17: Foundry 65/65, pytest full suite 1,057 passed. CI: first run on push.

**Measured (Phase 1, `forge test`, solc 0.8.30 via-IR):**

| Operation | Gas |
|---|---|
| One ML-DSA-65 verification | 1,541,829 |
| `execute`, 2 signatures | 3,160,407 (3,293,875 with calldata) |
| `execute`, 3 signatures | 4,702,670 |
| `execute` at the cap, 8 signatures | 12,384,446 (12,848,010 with calldata; 12,950,798 under `--isolate`, re-review) |
| `reconfigure`, rotate one signer | 3,340,200 |
| Lowest gas limit for a call approved with `callGas` 1,000,000 (2 signatures) | 4,187,351 |

Runtime sizes: `QVaultTreasury` 9,451 bytes; `ZKNOX_dilithium65` 24,272 bytes (EIP-170 limit 24,576).


### Phase 2: Relayer library · no ETH

- [x] `qvault/chain/rpc.py`: minimal JSON-RPC client over `urllib`, strict parsing, and an RPC URL (which holds the API key) that never appears in an error or `repr`; `qvault/chain/relayer.py`: simulate, sign and send EIP-1559 transactions, settle their status, wait for receipts
- [x] pytest: `tests/fake_ethereum.py` is an in-process node that decodes every raw transaction and recovers its sender, keeps nonces and a mempool, and injects lost requests, lost answers and error responses (**no network in tests**). Response shapes were probed read-only against Alchemy Sepolia on 2026-09-17 and copied into the tests
- [x] **Adversarial review (2026-09-17) fixes:** D21 (confirmed-nonce policy, `RelayerBusy`, `status()` with `superseded`, same-nonce replacement, `on_prepared` so the executor stores a transaction before sending it); every resend re-simulated and checked against its signed bytes; `http.client` exceptions (a truncated body) are "no answer", never a crash; URLs with control characters or plain http refused; lookups bound to the requested hash, and a receipt's created contract checked; "could not simulate" (rate limit, internal error) distinguished from "would fail"; unrecognised send errors are unknown outcomes, not rejections; an absolute fee-per-gas cap and a 0.1 gwei tip cap; test fidelity (the simulation is compared field by field with the signed transaction; the fake's estimate binary-searches like geth)
- **Done when:** the full suite is green. Relayer and RPC tests 146/146 (172 with the Phase 3 deployment-record tests); mutation run 47/47 killed, including the five mutants that survived the reviewer's run.

### Phase 3: Shared contracts on Sepolia · ~0.01 ETH

- [x] Deploy the F1600 helper and `ZKNOX_dilithium65`; verify the verifier's source on Etherscan (the helper is raw bytecode with no Solidity source; it is identified by the code hash the verifier enforces). *Deployed 2026-09-17 with the owner's approval, at the dry run's predicted addresses: helper [`0x8fB7DC8733139924C7b8D12A296F2ff3c0f87ac4`](https://sepolia.etherscan.io/address/0x8fB7DC8733139924C7b8D12A296F2ff3c0f87ac4) (block 11,724,419, 4,716,322 gas), verifier [`0x31a85de8CB44BC89c53487A69d20b3DC3dB7487C`](https://sepolia.etherscan.io/address/0x31a85de8CB44BC89c53487A69d20b3DC3dB7487C#code) (block 11,724,420, 5,242,448 gas). Etherscan: "Pass - Verified". Total cost 0.0109 ETH at ~1 gwei.*
- [x] `scripts/record_deployment.py` + `qvault/chain/deployments.py`: read forge's `broadcast/.../run-latest.json`, then confirm against the chain (finalized, canonical block; sender, nonce and CREATE address; code present) and against the commit (nothing under `chain/` uncommitted, the submodule at the pinned commit, every compiled source hashing to what the compiler recorded, `foundry.toml`'s compiler settings, and the on-chain verifier byte-identical to the build with only its immutable masked). **Merge** into `chain/deployments/sepolia.json` under a lock file, never overwrite. Written, reviewed and tested; runs once the deployment exists.
- [x] Live-check tool: `scripts/check_verifier_live.py` asks the deployed verifier, by `eth_call` with state overrides on the two key pointers only, to accept a fresh quantcrypt signature and refuse a tampered one, a wrong digest and another key's signature. No `setKey` (~8.8M gas) and no ETH. The whole 32-byte result is compared, using the 104-byte key form a treasury passes. Proven against Sepolia on 2026-09-17 with the helper and this commit's verifier also supplied by override.
- [x] Live check run against the deployed verifier (2026-09-17, block 11,724,512): genuine quantcrypt signature `0x024ad318`; one byte changed, a different digest, and another key's signature all `0xffffffff`. The recorder confirmed first that both blocks were finalized and canonical, that nothing under `chain/` was uncommitted at `4a089c2`, and that the verifier on chain is byte-identical to that build.
- **Done when:** the verifier is verified on Etherscan, the deployment is recorded, and the live check passes against it.

### Phase 4: The signed action · no ETH · ⚑ D4

*Design written 2026-09-17 from a map of every place the signed payload is built, sent, shown or verified (D22–D27). Before any of it: today's payload hashes were frozen (`tests/test_payload_vectors.py`), and the map's one live bug was fixed (`4a089c2`).*

- [x] `qvault/chain/action.py` (pure): `EthTransfer` built from a recipient and an amount under the D23 policy, strict `parse` of the D22 shape (refuses every malformed field, extra key or unsafe number), `canonical()` dict, and `execution_digest(payload_hash)` equal to `digest.execution_digest`. The D24 text and exact wei formatting live in `qvault/services/signing.py` (`payment_text`), so the offline verifier can use them without Ethereum libraries
- [x] Models (D27): `Treasury` (vault, chain, address, verifier, threshold, signer count, deployment tx and block, status, linked/unlinked times; unique `(chain_id, address)`; **at most one linked treasury per vault, enforced by a partial unique index**) and `ProposalAction` (proposal, treasury, every signed field); registered in `qvault/models/__init__.py`
- [x] `proposal_signing_bytes(..., action=None)` adds `action` only when given; `signing_bytes_for` includes the stored action; the frozen vectors still pass; a frozen payment vector is added
- [x] `create_proposal(..., payment=...)` keyword-only: requires `ONCHAIN_EXECUTION_ENABLED`, a linked treasury whose threshold **and signer count** match the vault's, and the deadline policy; generates the text; `proposal_created` ledger entry gains `has_action` only for payments
- [x] Binding: tampering with any stored action field is caught by `verify_proposal_binding`, like any other signed field; so is **a text that does not describe the signed payment**, and **a `treasury_id` repointed at another treasury row** (review M1, L1). A row edited to the wrong type is reported as tampering, not raised
- [x] API: `POST /vaults/<id>/proposals` accepts `payment {to, value_wei}` (a client-supplied `action` is refused, not ignored); `GET /proposals/<uuid>` adds `signing_inputs.action` behind the D25 capability, otherwise 426 `upgrade_required`, and voting is gated the same way; proposal summaries say whether a decision is a payment
- [x] Exports and the offline verifier: bundles with an action are `qvault.decision/2` (D26); the Python verifier and CLI accept `/1` and `/2`, show the payment, and **fail the content check when the text does not describe the payment**; integral floats read as the browser reads them
- [x] Browser verifier: `proposalBytes` includes `action`, accepts `/2`, makes the same text check, shows the payment and states what the hash covers, and **a report it cannot draw shows NOT verified instead of leaving a previous verdict on screen** (review M2); rebuilt; Playwright agreement tests on payment bundles (local)
- [x] Phone: `signing.ts` and the strict schema accept an optional `action`; `test_mobile_canonical.py` gains a payment case pinned to the frozen hash. **The phone checks the text against the payment, and refuses to vote on any payment decision, before biometrics, until Phase 6b renders the payment** (`tests/test_mobile_payment_guard.py`, run in CI). The capability header is not sent yet
- [x] `ONCHAIN_EXECUTION_ENABLED` (off by default, also in tests unless a test turns it on); verification and display of an existing payment decision never depend on it
- **Done when:** the full suite is green, the frozen vectors are unchanged, and Python, the offline verifier, the browser verifier and the phone agree on the new payment vectors.

### Phase 5: Link a vault to a treasury · ~0.03 ETH per vault

*Design written 2026-09-17 (D28–D34) from a map of the verifier's `setKey`, the treasury constructor, the key and vault models, and how the Azure database has been written before. Findings: the Azure database is Postgres reached from this machine, production runs an image from before this plan, a signer can hold a password key and several phone keys, `setKey` emits no event, and no treasury bytecode is committed.*

- [x] `qvault/chain/artifacts/QVaultTreasury.json` and `scripts/export_treasury_artifact.py` (D32); the CI `contracts` job checks the committed file against a fresh build
- [x] Model `TreasurySigner` (D29), registered; `treasury_linked` and `treasury_unlinked` added to the audit sentences; `AUTO_CREATE_DB` readable from the environment and gating seeding as well as table creation (D28)
- [x] `qvault/chain/key_storage.py`: find a key's canonical storage among the verifier's contracts; find a confirmed `setKey`'s pointers in the verifier's nonce range; read-back comparison (D30)
- [x] `qvault/chain/treasury_check.py`: the D31 check over RPC, reporting every mismatch rather than the first
- [x] `qvault/services/treasury_service.py`: `plan_link` (eligibility, D33 refusals, costs), `link` (D30 order: reuse or `setKey` each key, reuse or deploy the treasury, wait for finality, D31 check, re-read the vault, then one database transaction with `treasury_linked`), `check` and `unlink`. The relayer and RPC client are passed in. People are named by email: the `users` table has no username
- [x] `scripts/link_treasury.py --vault <id> --by <email> [--device <email>]... [--broadcast | --check | --unlink]`: dry run by default (D33), showing when a phone approver's sign-in expires; opens the app without startup writes (D28); prints the Etherscan verification command; records the treasury in `chain/deployments/sepolia.json` (vault id, threshold, and per signer the user id, custody, public-key SHA-256 and on-chain key id; deployment transaction and block; status). **No names in the record**, which is public. A dry run against Sepolia and the local copy of the demo database (2026-09-17) left that database logically identical
- [x] `_payment_action` compares signer sets, not counts, and counts the registered keys that can still sign (D34)
- [x] **Reseed guard (D16):** `seed_demo.py --reset` (before `drop_all`) and `migrate_to_postgres.py --force` refuse when this database has a linked treasury, or holds a key registered on a treasury the record lists as linked (a restored backup or a copy), or when the record cannot be read. `--unlink-treasury` prints the treasury, a link to its balance (locked for good), the approvers who lose access and the cost of relinking, then marks the treasury unlinked in the record and then in this database; a database whose own row is unlinked while the record still says linked is recognised as that database, not a copy, and finishes the unlink (review L3). Tests cover both refusals, the override, a locked record and a half-finished unlink
- [x] Tests: the fake node gains contracts that create contracts only when a transaction is included (`setKey`), code-hash handlers and blocks' transactions, and a fake treasury answering the views; every D31 mismatch; a crash and re-run at each step pays for nothing twice; a vault changed mid-link writes nothing; the least balance a plan accepts carries the link out; the real script, in its own process, leaves an unseeded database logically unchanged. **Local anvil end to end:** real `setKey` and deployment from the committed artefact, then the D31 check. Measured: `setKey` 8,709,889–8,710,393 gas; treasury deployment 2,497,096 (2 signers) and 2,664,311 (3 signers). Alchemy estimated 8.78M per `setKey`, so the dry run's deployment figure is set about 5% above measured
- [x] **Adversarial review (2026-09-17) fixes:** no critical/high. M1 a vault changed during the finality wait was stored as linked with no way back but a wipe (re-read before writing; `--unlink`); M2 the link signed anchors and checkpoints with this machine's key and log origin (removed); M3 a dry run seeded an unseeded database (seeding gated; subprocess test); M4 a vault needing more approvals than signers paid for keys, then crashed (refused); M5 `--device` accepted a phone that can no longer sign in (refused; expiry shown). L1 a resumed link lost its deployment transaction (found from the chain); L2 a ledger race on brand-new tables failed its retry on Postgres (tables committed first); L3 `--unlink-treasury` wrote the database before the record (reordered); L4 payments allowed with fewer than M usable registered keys (refused; `check` reports it); L5 nine mutants survived (tests added for each)
- [ ] Owner: answer [Q2 and Q3](#open-questions); approve the broadcast after reading the dry run against the Azure database
- [ ] Link the demo Treasury vault against the Azure database (D28); verify the treasury on Etherscan; `--check` passes
- **Done when:** the demo Treasury vault is linked on Sepolia and verified on Etherscan, `--check` passes against the Azure database, and the reseed guard is proven by a test.

### Phase 6a: Execution signatures (web) · no ETH

- [ ] `key_service`: sign several messages with one unlock (one Argon2id run), keeping verify-after-sign (ADR-0010) for each
- [ ] `cast_vote`: approving a payment proposal also signs the execution digest → `ExecutionSignature`; ledger payload gains `execution_signature_sha256`
- [ ] Refuse the approval if the signer's active key is not registered on the treasury (key rotated) and say why
- **Done when:** tests cover a valid signature, a tampered one, a rotated key, and a reject vote (no execution signature).

### Phase 6b: Phone parity · no ETH · OTA release · gates D15

- [ ] Phone computes the digest itself from `signing_inputs.action` (noble keccak + ABI encoding), signs, and sends `execution_signature_b64`; it refuses to sign if its own digest disagrees with the server's
- [ ] Phone shows the payment from `signing_inputs.action` (the hashed values, never the unhashed `payment` view), then removes the Phase 4 `PaymentNotSupportedError` guard and starts sending `X-QVault-Capabilities: payment-action-1`
- [ ] Phone checks that its own key is a signer of the treasury with the expected content (code hashes from its own public key) before signing
- [ ] API verifies and stores it; interop test (JS digest = Python digest)
- [ ] Decision screen shows the payment the same way the web does: recipient, amount, network, treasury
- [ ] Reject works on payment decisions exactly as it does today (no execution signature needed)
- [ ] Raise a payment decision from the phone (API `POST /vaults/<id>/proposals` accepts `payment {to, value_wei}`; a client never sends `action`)
- [ ] Execution state on the phone: queued / submitted / confirmed with a transaction link / failed with a reason (API exposes it)
- [ ] Vault screen shows the treasury: address, balance, threshold
- [ ] Publish the OTA update and test on a real handset (owner, as in §3.3)
- **Done when:** every row of the [parity checklist](#parity-checklist) passes on the phone.

### Phase 7: The executor · ~0.004 ETH per payout

- [ ] `Execution` state machine: `queued → submitted → confirmed | failed`, unique per proposal
- [ ] Scheduler job: re-check binding, tally and execution signatures off-chain → check the on-chain `executed` flag → simulate → send → receipt
- [ ] Idempotent across crashes: the signed transaction is stored via `on_prepared` before it is sent, then reconciled with `Relayer.status()` (rebuilt with `PreparedTransaction.from_raw` after a restart) or from the `Executed` event, never re-signed unless `superseded` (D21); `AlreadyExecuted` (someone else submitted first) counts as success (D20); `RelayerBusy`, `SimulationUnavailable` and `FeeTooHigh` mean "try again later", not failure
- [ ] One `Relayer` per process, held in `app.extensions`
- [ ] Never broadcast if simulation fails (D20); a proposal past its `validUntil` is recorded as expired, not failed
- [ ] Ledger `proposal_executed` {tx_hash, block, gas_used}; `proposal_execution_failed` {reason}
- [ ] Tests with a fake RPC for every transition, including a relayer out of gas, a reverted simulation, a dropped transaction, and a restart mid-flight
- **Done when:** a real Sepolia payout completes end to end from a web approval.

### Phase 8: Interface · no ETH

- [ ] New decision: a "Payment" action (recipient, amount), shown only when the vault has a treasury; the text is generated
- [ ] Decision page: an execution panel (state, transaction link, block, gas, execution signatures n/M)
- [ ] Vault: Treasury tab (address, balance, verifier, registered signers, threshold, configuration nonce)
- [ ] Follow the UI rules in ADR-0014 (no teaching copy; colour only for state); screenshot every changed screen
- [ ] Turn `ONCHAIN_EXECUTION_ENABLED` on only after the parity checklist is fully ticked
- **Done when:** the owner has looked at the screenshots (§3.1-style check) and the parity checklist is complete.

### Phase 9: Evidence and documents

- [ ] ADR-0023 (this design, its limits, the measured costs)
- [ ] `/docs` page for on-chain execution; README section
- [ ] Decision record / export includes the transaction hash and execution signatures; the offline verifier checks the execution signatures
- [ ] Scripted end-to-end tamper demo (tamper after approval → payment refused → Etherscan confirms)
- [ ] Defence pack: new claims and the limits to volunteer
- **Done when:** the demo runs from the script without improvising.

### Parity checklist

The feature is not finished, and the flag stays off, until every row is ticked on both sides.

| Action on a payment decision | Web | Phone |
|---|---|---|
| Raise a payment decision (recipient, amount) | [ ] | [ ] |
| See the payment details before signing | [ ] | [ ] |
| Approve (vote signature + execution signature) | [ ] | [ ] |
| Reject | [ ] | [ ] |
| Refuse to sign when the payment was tampered with | [ ] | [ ] |
| See the execution state and the transaction link | [ ] | [ ] |
| See the vault's treasury (address, balance, threshold) | [ ] | [ ] |

### Open questions

- ~~**Q1: which database does the demo run on?**~~ **Answered 2026-09-17: the Azure instance's
  database.** Consequences for later phases: Phase 5 links against Azure's database (the linking
  script runs where that database is, not against a local copy); the relayer key and RPC settings
  become Container App secrets (a new owner step when Phase 5 starts, depending on §2.7 CI deploy
  or a manual `az` update); the executor runs in the Azure app's scheduler; and the D16 reseed
  guard must protect a reseed of the Azure database, not only a local one.
- **Q2: which approvers register a phone key?** The demo has one approval made on the phone
  (§1). That approver's phone key is registered instead of their password key (D29), so their
  payment approvals must then come from that phone. The phone must be enrolled on the Azure
  instance **before** linking: a key enrolled afterwards, including after reinstalling the app,
  cannot approve payments until the treasury is relinked.
- **Q3: how does the link reach the Azure database?** It needs the Azure Postgres `DATABASE_URL`,
  and the server's firewall must admit this machine (D28). Either the owner runs the dry run and
  the broadcast, or makes the URL available to the session in a way the owner chooses. The URL is
  never written to the repository.

---

## 6. ETH budget

| Phase | Estimate at ~1.1 gwei |
|---|---|
| 3: helper + verifier | ~0.011 |
| 5: one treasury with 3 signers | ~0.028 (measured: 3 × 8.71M + 2.66M gas; dry run 2026-09-17 at 0.97 gwei) |
| 7: each payout (plus the amount sent) | ~0.004 |
| **Total for one linked vault and 5 test payouts** | **~0.062** |

The relayer holds 0.05; a further 0.05 arrives 2026-09-18. Check the fee before every deploy and
wait if it is above 2 gwei.

## 7. Risks and limits to state openly

- **The verifier is experimental and unaudited** (ZKNox say so). Acceptable on a testnet, and must
  be stated in the ADR and the viva.
- **Reseeding the demo database breaks the link.** `seed_demo.py --reset` creates new keys, so the
  treasury's signers no longer match and the old keys are gone, which means `reconfigure` cannot
  fix it. Mitigated by the reseed guard (D16). Link only after the final seed; relinking costs
  ~0.03 ETH.
- **Key rotation**: a rotated approver cannot co-sign until `reconfigure` registers the new key
  (Phase 6a refuses clearly; syncing automatically is out of scope).
- **Custody**: a password-key approver's execution signature is produced by the server, the same
  trust as their vote today. "What you see is what executes" holds end to end only for phone keys.
- **Still classical:** Ethereum consensus, and the relayer, which affects availability only and
  cannot change a payment.
- **Fee spikes** on Sepolia can stall deploys; there is no mainnet path.
- **ML-DSA-65 only.** SLH-DSA and ML-DSA-87 approvers cannot sign on-chain.

## 8. Out of scope

ERC-20 payouts (the contract allows them later; no UI) · mainnet · chains other than Sepolia ·
automatic signer sync after rotation · gas sponsorship or ERC-4337 bundlers.

## 9. What the owner does

Tracked in [OWNER-ACTIONS §2.8](../OWNER-ACTIONS.md): ~~review this plan~~ (done 2026-09-17), fund
the second 0.05 ETH, ~~answer Q1~~ (Azure, 2026-09-17), test the phone on a real handset in Phase 6b, and
look at the Phase 8 screenshots.

---

## Progress log

| Date | Phase | What landed | Commit |
|---|---|---|---|
| 2026-09-17 | 0 | Research, local compatibility proof, relayer wallet funded (0.05), this plan drafted | — |
| 2026-09-17 | 0 | Owner approved D4 and D14 on condition of phone parity; added D15 (parity gate + flag), D16 (reseed guard), Q1 (demo database) | — |
| 2026-09-17 | 1 | Adversarial review of the first Phase 1 build: 13 findings, 2 zero-key/duplicate-key forgeries verified by running. Added D17–D20; findings 1–9, 11, 13 fixed in Phase 1; finding 10 (fork the pinned submodule) is an owner action | — |
| 2026-09-17 | 1 | Re-review of the fixes: no critical/high. Fixed: a starvation test that could not fail (medium); empty-account code hashes and re-encoded duplicate keys still passing (low, both verified by running); calldata memory eating the gas reserve at ≥64 KB (low). D17/D18 amended. Measured under `--isolate`, 8 signatures need 12,950,798 gas, 22.8% headroom | — |
| 2026-09-17 | 1 | Phase 1 landed: treasury contract, Python digests and key expansion, cross-checked fixtures, deploy script, CI `contracts` job. Foundry 65/65, pytest 1,057 passed. CI green on first push, including the new `contracts` job (the advisory mypy job fails with the same 284 pre-existing errors as before; none in `qvault/chain`) | `8b7172a` |
| 2026-09-17 | 2 | Adversarial review of the relayer: no critical/high, 9 medium, 7 low, all verified by running. Root cause of M2–M7 was the nonce model, replaced rather than patched (D21). M1 (truncated HTTP body escaping as `IncompleteRead`, URL with a control character quoted in an error) and all lows fixed. Mutation testing also exposed a harness bug: restoring files with `write_text` on Windows turned them CRLF (caught by an md5 check) | — |
| 2026-09-17 | 2 | Phase 2 landed: RPC client, relayer, fake node; 146 tests. CI green | `e0c0a99` |
| 2026-09-17 | 3 | The broadcast was blocked by the session's permission system (it spends ETH and publishes to a public chain); recorded as an owner action rather than worked around | — |
| 2026-09-17 | 3 | Adversarial review of the recording tooling (run against a local anvil replay of the real dry run): no critical. High: the record claimed "this commit's build" without checking the artefact came from the commit, reproduced by changing a metadata byte in both; fixed with clean-tree, pinned-submodule, source-hash and settings checks. Medium: the script's own checks were untested (now 20 tests); the record file was a weak store for the reseed guard (strict loader, full schema check, lock file). Lows fixed: finality and reorg check, block time instead of the drifting local clock, partial broadcasts named as such, a BOM tolerated, Windows replace retried, ignored temp files | — |
| 2026-09-17 | 3 | Recording and live-check tooling landed (deployment itself pending the owner). 216 chain tests; mutation run on the new checks 25/25 killed; full suite 1,273 passed | `932f1ad` |
| 2026-09-17 | 4 (prep) | Mapping the signed payload found a live bug (a decision whose text ended in a newline failed its own binding check, and its votes went uncounted) and that no test froze the payload hashes. Fixed, and today's hashes frozen before Phase 4 changes the payload | `4a089c2` |
| 2026-09-17 | 3 | **Phase 3 done.** Owner approved the broadcast; helper and verifier deployed at the predicted addresses for 0.0109 ETH, verifier source verified on Etherscan, deployment recorded after finality with every provenance check passing, live check passed against the deployed verifier. Q1 answered: the demo runs on the Azure database. ETHDILITHIUM forked to the owner's account with tag `qvault-pin-4c370bb` | `ad0e3a7` |
| 2026-09-17 | 4 | Adversarial review of Phase 4: no critical/high. M1: nothing compared a payment decision's text with its signed payment, so a server could sign 5 ETH under a description of 0.0001 ETH and every verifier said Verified; now the binding check, both verifiers and the phone compare them (the phone also refuses payments until 6b). M2: a huge `valid_until` crashed the browser's drawing and left an earlier Verified on screen. Lows fixed: `treasury_id` unchecked, 4,301-digit amounts giving 500, no database guard on one linked treasury per vault, a client `action` silently ignored, verifier disagreement on arrays and integral floats, tampered types raising, a vacuous test, signer-count drift, NaN deadlines giving 500 | — |
| 2026-09-17 | 4 | **Phase 4 done.** A payment (`eth_transfer`: chain, treasury, recipient, wei, call gas, expiry) is part of the signed decision payload, so every approval signs it; created only behind `ONCHAIN_EXECUTION_ENABLED` against a linked treasury whose threshold and signer count match the vault; text generated from the payment and checked against it by the binding check, both offline verifiers and the phone; `qvault.decision/2` bundles; old phones get 426 `upgrade_required`, and this phone refuses to vote on a payment until Phase 6b shows it. Frozen vectors unchanged, payment vector frozen and matched by the phone. No ETH spent | `d841f04` |
| 2026-09-17 | 5 | Design written (D28–D34) from a map of `setKey`, the treasury constructor, the key and vault models and how the Azure database has been written | `2d8ebab` |
| 2026-09-17 | 5 | Adversarial review of Phase 5: no critical/high. M1 a vault changed during the finality wait was stored as linked, with no way back but a wipe; M2 the link signed log anchors and checkpoints with this machine's key and origin; M3 a dry run seeded an unseeded database; M4 a vault needing more approvals than signers paid for keys, then crashed; M5 `--device` accepted a phone that can no longer sign in. Lows: a resumed link lost its deployment transaction; a ledger race on brand-new tables failed its retry on Postgres; `--unlink-treasury` wrote the database before the record; payments allowed with fewer than M usable registered keys; nine surviving mutants. All fixed, with a test each. Mutation run after the fixes: 36 of 38 killed (M01 is equivalent to the signer-set comparison; N09 needs Postgres's transactional DDL, which SQLite does not have) | — |
| 2026-09-17 | 5 | **Linking engine, operator tool and reseed guard landed.** Anvil end to end with the real verifier and the committed artefact; a dry run against Sepolia and the local copy of the demo database proven to leave it logically unchanged (~0.028 ETH for three keys and a treasury). Nothing linked yet. Owner re-scoped the work for production the same day (D35–D41, next commit) | *(this commit)* |
