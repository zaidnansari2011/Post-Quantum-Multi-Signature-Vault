# Scope: payment approval from the phone (chunked on-chain key storage)

**Status:** scoping only, 2026-10-15. Nothing built, nothing sent to any network. Read-only study of
`saas-rework`. **Decision needed from the owner** before any work (see "The decision").

## The problem

Phone payment approval needs a treasury seat that holds the phone's ML-DSA-65 key, and putting a
key on chain (`ZKNOX_dilithium65.setKey`) writes 2 × 20,161 bytes of contract code through SSTORE2.
Sepolia now charges about 1,543 gas per code byte, so `setKey` needs about 62.9M gas, against a
per-transaction cap of 16,777,216 (revert `0x08d4abb6`, SSTORE2 `WriteError`).

## What the study found

1. **The phone already signs payments.** `mobile/src/flows.ts` (`paymentApproval`,
   `voteOnProposal`) signs `executionDigest` (`mobile/src/crypto/execution.ts`) whenever the seat's
   fingerprint is this phone's key, and `queue.ts` moves `this_device` seats out of "Approve on the
   web". What is missing is a treasury whose seat holds the phone key.
2. **Chunking the key fixes `setKey` but not the deployment.** Two more blockers sit under the same
   per-byte price:
   - The verifier cannot be redeployed in one transaction: its runtime is 24,272 B (about 37.5M
     gas). One transaction can deploy about 10.6 KB at most, so an adapted verifier must be split
     into at least 3 contracts. The F1600 helper (21,622 B) must be reused at
     `0x8fB7DC8733139924C7b8D12A296F2ff3c0f87ac4` (it is bound by code hash, which is fine).
   - A new `QVaultTreasury` (9,471 B runtime) costs about 15.4M gas for 3 signers, under the cap
     by only 1.4M. A 10-signer treasury does not fit, and if new storage slots were also repriced,
     even 3 may not.
3. **The deployed verifier cannot be wrapped.** It reads keys only from two whole-half pointers,
   and `verifyInternal` is internal, so the owner's fork (`zaidnansari2011/ETHDILITHIUM`, branch
   `mldsa-65`, commit 4c370bb) has to be adapted.
4. **Stale gas constants:** `treasury_service.DEPLOY_GAS_BASE` (2,275,000) and `SET_KEY_GAS`
   (8,710,129) predate the repricing, so `plan_link`, `treasury_jobs.expected_cost_wei`,
   `reconfiguration_service.request` and `reseed_guard` under-reserve ETH. Existing treasuries
   should still pay (verification is a read); re-measure (E5).

## Design sketch

- **Chunks:** keep today's 40,320-byte blob byte for byte (so `mldsa_key.py`, the fixtures and
  vectors stay valid) and cut each half into 3 chunks of 6,720 B, so 6 per key, each written as
  `0x00 ‖ chunk`. About 10.5M gas per chunk, about 63M per key in 6 transactions. 6,720 rather than
  10,080 because a 10,080-byte chunk through a factory crosses the cap under the 63/64 rule, and
  6,720 leaves about 37% headroom if the price rises again.
- **Writer:** a tiny factory `chain/src/QVaultKeyChunks.sol` (CREATE2, salt 0, SSTORE2 initcode,
  `ChunkStored` event). Chunks become content-addressed: Python predicts each address, so finding
  existing storage is 6 `eth_getCode` calls, and front-running is harmless.
- **Signer identity v2:** `verifier(20) ‖ p0..p5 (120) ‖ C(32)` = 172 bytes, where
  `C = keccak256(codehash(p0) ‖ … ‖ codehash(p5))`. Treasury v2 `_addSigners` checks the length,
  the verifier, that all 6 pointers are canonical (6,721 B, first byte STOP) and `C`. The key id
  comes from `tr` in chunk 2 at offset 3,264, refused if it would cross a chunk boundary. No
  separate on-chain finalise step is needed.
- **Verifier:** a chunked read (3 `extcodecopy` per half into one buffer, then the same parsing),
  drop `setKey` to save bytes, and split into pieces of 10 KB or less (library contracts or
  staticcalls). Cost: about +10.4k gas per signature for the cold reads, plus 20–100k for the
  split (to measure). 8 signatures go from about 12.95M to 13.1–13.8M, so `MAX_THRESHOLD = 8`
  (D19) probably holds.
- **Digest tags stay `QVAULT-TREASURY-v1`** (`address(this)` already prevents replay across
  treasuries). Record this as decision D47.

## App-side changes

`mldsa_key.py` (chunks, commitment); `digest.py` (`signer_blob_v2`, 172 B); `key_storage.py`
(chunked storage, CREATE2 prediction, resumable writes; the v1 code is kept for the old treasury);
`treasury_check.py` and `treasury_artifact.py` (v1 and v2 artifacts); `deployments.py` (library
link references in the "code equals artifact" checks); `treasury_service.py` (each existing
treasury is checked against its own `verifier_address`, 6 steps per key, new measured gas
constants, a gas limit no higher than the cap); `treasury_jobs.py` and `reconfiguration_service.py`
(one chunk per tick); an Alembic migration (`key_pointers`, `storage_layout`, `pointer0`/`pointer1`
made nullable); both offline verifiers accept 172-byte identities (consider `qvault.decision/3`);
phone: `IDENTITY_BYTES` in `execution.ts` accepts 124 or 172 (JavaScript only, so it ships OTA).

## Moving the Finance treasury

The old treasury's verifier is immutable, so it can never hold a chunked key: moving means a new
treasury. Steps: decide on open payments #19, #20, #25, #26, #27; deploy and record the factory
and verifier pieces; the owner picks "This phone's key"; drain Finance to an owner wallet (2 of 3
web approvals) while it is still linked; unlink; link a v2 treasury (watch
`TREASURY_LINK_COOLDOWN_DAYS = 30`; about 20 transactions); fund it; test a phone-plus-web payment;
export and commit the record and the decision. Note that `0x3b18ea6f…` is not in the committed
`chain/deployments/sepolia.json`: export its record from live first.

## Experiments to run first (read-only RPC or local)

E1 `eth_estimateGas` for CREATE transactions of 0 / 1,000 / 6,721 / 10,081 B and k new SSTOREs (the
exact prices). E2 which fork and EIPs Sepolia runs, and whether any allowance lets a transaction
exceed 2^24 gas (if so, the fix is just a larger gas limit). E3 whether a treasury deploys for N = 3
and N = 10. E4 `forge build --sizes` for the verifier pieces. E5 verification gas under the new
prices. E6 whether the CREATE2 deployer exists. Anvil 1.7.1 probably lacks the new pricing
(`foundryup` changes the system, so ask first).

### Measured 2026-10-15 (read-only `eth_estimateGas` and `eth_config` on Sepolia, block 11,920,142)

| What | Gas | Note |
| --- | --- | --- |
| Contract creation, empty code | 210,487 | account creation repriced (it was about 53k) |
| Each code byte | about 1,542 | (1,752,947 − 210,487) / 1,000 |
| 6,721-byte chunk | 10,577,255 | fits, as designed |
| 10,081-byte chunk | 15,759,917 | fits from a wallet, not through a factory |
| Largest single deployment | about 10.7 KB | 10,700 B = 16,714,700 |
| One old `setKey` half (20,161 B) | 31,308,161 | |
| Verifier (24,272 B) | 37,649,422 | |
| Each new storage slot | about 111,000 | it was 22,100; 10 slots = 1,320,209 |

- **New slots changed:** a new treasury's constructor writes its signer identities and key ids
  into new slots, so code (about 14.6M) plus creation (0.21M) plus a few dozen slots at about 111k
  each is over the cap for 3 signers. E3 is very likely a fail, so treasury v2 needs a split deploy
  (a minimal clone, or an `initialize` spread over several transactions), and reconfigurations
  that add signers cost about five times more than they used to.
- **E2 is not settled:** `eth_estimateGas` returned 31.3M and 37.6M without complaint, but the
  node does not apply the 16,777,216 cap when estimating. The 14 Oct `setKey` failure shows it is
  applied to real transactions. Only a real transaction above the cap would settle whether any
  allowance exists (it costs Sepolia ETH, so it needs the owner's OK).
- The CREATE2 deployer `0x4e59b448…` exists on Sepolia (E6).

## Effort

About **15 to 25 developer-days**. The verifier split is the critical path and the biggest unknown
(3–6 days); the treasury v2 can grow by 1–5 days if E3 fails. Every other part is 0.5–3 days.

## Needs the owner

Sepolia ETH (about 0.25 ETH for the first migration; top up 0.3–0.5), the deployer key and the
Etherscan key, push rights to the ETHDILITHIUM fork, 2 of 3 web approvals for the drain, a decision
on the open payments, choosing the phone key on the handset, applying the live migration, the OTA
release. After the move, that treasury's payments can no longer be approved on the web (one key per
person, D29).

## The decision

This is large next to the dissertation, and approving on the web from the phone's browser works
today at no cost (payment #18 was paid that way). Recommendation: run E1 and E2 first (an hour,
read-only). If E2 shows an allowance above 2^24, the fix is small. If not, keep this as Future Work
in the report, with these numbers as the evidence, unless the owner wants it for the demo.
