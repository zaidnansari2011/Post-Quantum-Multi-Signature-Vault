# Runbook — treasuries on Sepolia

For whoever operates a deployed Q-Vault with on-chain treasuries (plan D41). The design is
[ADR-0023](../adr/0023-post-quantum-treasury-on-chain.md); what each piece is for is in
[`docs/plans/onchain-execution.md`](../plans/onchain-execution.md). The live deployment's layout is
[OWNER-ACTIONS §2.9](../OWNER-ACTIONS.md).

## What runs where

- **The app's scheduler** does all chain work, one chain action per tick
  (`TREASURY_TICK_SECONDS`, default 60) and in one job, so the relayer is never used from two
  threads. Its three passes, in order: treasury links, reconfigurations, payouts. The app runs
  **one replica, one worker**: two schedulers would both confirm a payout in the ledger (the
  treasury still pays once).
- **The relayer** is an ordinary Sepolia account whose key is the `EXECUTOR_PRIVATE_KEY` secret. It
  pays gas and has **no authority**: every payment and signer change is signed by the approvers and
  checked by the contract. Losing it costs its ETH, nothing else.
- **Every transaction is stored before it is sent** and settled from the chain afterwards, so a
  restart or redeploy at any moment repeats nothing.
- **The admin page** `/admin/chain` shows the relayer's balance against its reserve, the work in
  progress and the last failures. Start there.

## Switching treasuries on

Off by default. Turn on only after the phone parity checklist has passed on a handset (plan D15).

1. Add the secrets and settings to the `qvault` container app:

   ```sh
   az containerapp secret set -n qvault -g rg-qvault --subscription <sub> \
     --secrets executor-private-key=<0x… key> sepolia-rpc-url=<https://… endpoint>
   az containerapp update -n qvault -g rg-qvault --subscription <sub> \
     --set-env-vars SEPOLIA_CHAIN_ID=11155111 EXECUTOR_ADDRESS=<0x… relayer address> \
       SEPOLIA_RPC_URL=secretref:sepolia-rpc-url EXECUTOR_PRIVATE_KEY=secretref:executor-private-key \
       ONCHAIN_EXECUTION_ENABLED=true
   ```

   `EXECUTOR_ADDRESS` is a check: when the key does not match it, the app still starts but builds
   **no relayer**, and logs why (`az containerapp logs show -n qvault …`, "no relayer: …").
2. Open `/admin/chain`. The page should say **Funded**; "No relayer" means a setting is missing or
   wrong, and the log line says which.
3. Fund the relayer (below) before any owner creates a treasury.

## Settings

| Setting | Default | What it limits |
| --- | --- | --- |
| `ONCHAIN_EXECUTION_ENABLED` | `false` | Everything. Off: no chain work starts and no payment decisions can be raised. |
| `TREASURY_RELAYER_RESERVE_WEI` | 0.015 ETH | No new chain work starts below it; work already started finishes. |
| `TREASURY_LINK_COOLDOWN_DAYS` | 30 | One treasury link per vault per period (counts any link that spent). |
| `TREASURY_PAYOUTS_PER_DAY` | 10 | Payment transactions per vault per 24 hours, retries included. |
| `TREASURY_TICK_SECONDS` | 60 | How often the scheduler takes one chain action. |

The relayer also refuses to sign while Sepolia's base fee is above 2 gwei; work **waits** rather
than fails, and the reason is on the job.

## Funding the relayer

Send Sepolia ETH to the relayer address shown on `/admin/chain`. Budget:

| Work | Cost at ~1 gwei |
| --- | --- |
| Linking a three-signer vault | ~0.028 ETH |
| A payout | ~0.004 ETH, plus the amount paid (which comes from the treasury, not the relayer) |
| A reconfiguration | ~0.009 per new key, plus ~0.004 |

"Relayer low" on `/admin/chain` means the balance is under the reserve plus one worst-case payout:
new work is about to start waiting.

## Funding a treasury

A treasury pays from its own balance. Send ETH to the address on the vault's **Treasury** tab. A
payout from an unfunded treasury waits with the reason shown on the decision; it does not fail.

## When something goes wrong

**A job, reconfiguration or payout says "waiting".** Read its reason; it names the limit (reserve,
cooldown, payouts today, base fee, the endpoint not answering). These clear on their own once the
cause does.

**A payout failed.** The decision page's Payout panel and `/admin/chain` give the reason.
Common ones:

- *The treasury would refuse this payment:* the approvals no longer verify on chain, usually
  because a signer's key changed. Raise the payment again after the treasury follows the vault.
- *Voided:* a reconfiguration moved the treasury's configuration after the approvals were given.
  This is by design (D42): raise it again.
- *Expired:* the approvals passed their deadline (7 days by default, plus 72 hours to execute).

A payment that reverts when included is **not** retried: that would pay gas every tick for a
payment that cannot succeed.

**A transaction is stuck pending.** The app leaves a pending transaction alone and signs nothing
new for that relayer until it settles (D21: never two transactions that could both land). A
transaction the network dropped is sent again byte for byte, which is always safe. There is no
tool to speed a stuck transaction up. On Sepolia the base fee almost always falls back within
minutes; if it does not, wait.

**A reorg.** Nothing is recorded as linked or reconfigured until its blocks are finalized, and
transactions are settled against the chain, not the app's memory. A transaction knocked out by a
reorg is found again as dropped and re-sent unchanged.

**The Ethereum endpoint is down.** Approving a payment or a reconfiguration is refused with
"Ethereum could not be asked", by design (D43: never sign without reading the chain's configuration
first). Chain work waits. Nothing needs doing except restoring the endpoint, or pointing
`SEPOLIA_RPC_URL` at another provider.

**The verifier misbehaves or is found vulnerable.** Set `ONCHAIN_EXECUTION_ENABLED=false`. No new
chain work starts and no payment can be raised or approved. Funds stay in the treasuries, which
still pay only with valid approvals. The verifier is pinned (ZKNox `ZKNOX_dilithium65` at
`4c370bb`, deployed at `0x31a85de8CB44BC89c53487A69d20b3DC3dB7487C`), so no upgrade can change it
underneath you.

## Changing the relayer key

The relayer has no authority, so nothing on chain changes. Only do it with **no job,
reconfiguration or payout open** (`/admin/chain`, all three "in progress" at 0). Work started under
the old key waits with "this was started with a different relayer key" rather than failing.

1. Generate a new account and fund it.
2. Replace the `executor-private-key` secret and `EXECUTOR_ADDRESS`, as in *Switching treasuries on*.
3. Move whatever ETH is left on the old account.

## Operator tools

`scripts/link_treasury.py` runs the same engine from a laptop against the app's database
(`DATABASE_URL`). It is for recovery and checks, not the normal path.

```sh
python scripts/link_treasury.py --vault <id> --check                 # read-only: is it what we think?
python scripts/link_treasury.py --vault <id> --by <admin email>      # dry run: plan and cost, sends nothing
python scripts/link_treasury.py --vault <id> --by <admin email> --unlink   # mark unlinked; sends nothing
```

`--check` repeats the whole D31 check against the chain: code, verifier, threshold, every signer's
identity computed from the database's own public keys, and the configuration nonce. Run it after
anything that touched the database by hand.

`scripts/check_verifier_live.py` asks the deployed verifier to judge Q-Vault's own signatures. It
costs nothing and is the quickest way to tell a verifier problem from an app problem.

## Never

- **Reseed a database that has a linked treasury.** New keys mean the old approvers can never sign
  again, and a reconfiguration needs their signatures. `seed_demo.py --reset` refuses unless given
  `--unlink-treasury` (D16).
- **Run two app replicas** while treasuries are on.
- **Edit `treasuries`, `treasury_signers` or `proposal_actions` by hand.** The app refuses to sign
  when its records and the chain disagree (D43), so an edit stops payments rather than redirecting
  them. Recovering needs `--check` and possibly an unlink and relink (~0.03 ETH).
