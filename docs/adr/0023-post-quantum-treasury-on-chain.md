# ADR-0023 — Approved decisions execute on chain, and the chain checks the post-quantum signatures

- **Status:** Accepted
- **Date:** 2026-09-27
- **Working record:** [`docs/plans/onchain-execution.md`](../plans/onchain-execution.md) — decisions
  D1–D46, every review finding and its fix, and the progress log. This ADR is the summary; the
  plan is the evidence.
- **Amends:** ADR-0002 (M-of-N stays application-level for ordinary decisions; for payments the
  contract enforces it too) and ADR-0003 (the ledger is still a hash chain, not a blockchain; a
  treasury is a *consumer* of approved decisions, not a replacement for the ledger).

## Context

Every earlier ADR makes a decision *provable*: signed, recorded, witnessed, exportable, checkable
offline. None makes it *do* anything. A vault that approves "pay the auditor" still needs a person
with a bank login to go and pay, and that person — or whoever controls the server — can pay
someone else. The approval and the action were joined by trust.

The obvious fix, a smart contract that pays when the app says so, moves the trust rather than
removing it: the contract would obey whichever key the server holds. The fix that removes it is a
contract that **checks the approvers' own signatures** before paying, so neither Q-Vault's server
nor the account that sends the transaction can move funds without them. For this project those
signatures are ML-DSA-65, and until recently no chain could afford to verify one.

## Decision

A vault can have a **treasury**: a contract on Sepolia that holds ETH and pays out only when
M of its registered approvers have signed that exact payment with ML-DSA-65, verified **on chain**.

**The contract.** `chain/src/QVaultTreasury.sol` is a thin treasury over OpenZeppelin's
`MultiSignerERC7913` (v5.7.0), with ZKNox's Solidity verifier `ZKNOX_dilithium65` pinned at commit
`4c370bb` (D1, D2). Each signer is a 124-byte identity that commits to its key's content — verifier,
two storage pointers and their code hashes — so a key cannot be swapped or counted twice (D17). It
exposes two authorised operations:

- `execute` pays one approved payment. It checks M signatures over an **execution digest** that
  binds chain, treasury, the configuration nonce, the decision's `payload_hash`, recipient, amount,
  call data, the gas given to the call and a deadline (D8, D18, D42).
- `reconfigure` changes the signer set and threshold, authorised by the *current* M-of-N (D9, D39).

The threshold is capped at 8 so a payout always fits in one transaction (D19).

**The signed payment is part of the decision.** A payment decision's canonical payload carries a
fixed-shape `action` (D4, D22), its text is generated from that action (D5, D24), and a bundle that
carries one is `qvault.decision/2` (D26). Approvers sign the machine-readable payment, not prose
about it. Approving produces two signatures from one password or one biometric prompt: the vote,
exactly as before, and the execution signature the contract checks (D6). The on-chain proposal id
is the decision's `payload_hash`, so anyone can match an Etherscan event to a decision record
without asking Q-Vault (D7).

**The phone does not trust the server.** It recomputes the payload hash, the execution digest and
the `reconfigureDigest` itself — the last including the dynamic `bytes[]` ABI encoding — and
refuses before the biometric prompt when the server's claims differ from what it computed, or when
the treasury holds another key for this person (Phase 6b, 7b). Its digests match Python's byte for
byte, and Python's match the contract's (cross-implementation fixtures, D12).

**The relayer pays gas and has no authority** (D3). An ordinary ECDSA account inside the app sends
the transactions; everything that matters is signed by the approvers, so its key can change
nothing. It never broadcasts a transaction that fails simulation (D20), never has two transactions
that could both land (D21), and runs within limits — a reserve, a link cooldown, payouts per vault
per day — so one vault or one bug cannot drain it (D38).

**Self-service and durable.** An owner creates a treasury from the web or the phone; the scheduler
links it as a resumable job, one chain action per tick, storing each signed transaction before it
is sent (D36). Each signer chooses which of their keys the treasury registers (D37). When the vault
changes, the owner asks for a reconfiguration and the treasury's current signers approve it (D39,
D44–D46). The app writes nothing about the chain until it has read it back from finalized blocks
and checked it against the committed bytecode (D30–D32).

**Signing only at the chain's own configuration.** Approving a payment or a reconfiguration first
reads `configNonce()` from the chain and refuses on a mismatch or when the chain cannot be asked
(D43): a database edit can then never have honest approvers sign for a configuration that does not
exist yet.

## Consequences

**What now holds that did not before.** With a phone-held key (ADR-0016), "what you approved is
what gets paid" holds from the approver's screen to the chain: a server that changes the
recipient, the amount or the signer set after approval produces a payment the contract refuses.
The server and the relayer can delay a payment; they cannot redirect one.

**Measured on Sepolia and anvil.**

| | Gas | At ~1 gwei |
|---|---|---|
| Registering one signer's key (`setKey`) | 8.71M | ~0.009 ETH |
| Deploying a treasury (2 / 3 signers) | 2.50M / 2.66M | ~0.003 ETH |
| Linking a three-signer vault in total | ~28.8M | **~0.028 ETH** |
| A payout with two approvals (Sepolia, block 11,793,551) | **3,272,465** | ~0.0034 ETH |
| A reconfiguration with two approvals (anvil) | 3,534,024 | ~0.0035 ETH |
| One ML-DSA-65 verification | ~1.54M | |

The first real payout was paid through the app's own paths on 2026-09-27: treasury
`0xD49174b703d6FBC5088b0f01C6E71B5Ef467f3D0`, transaction `0xe0ce951a…78f3`.

**Costs accepted.**

- Approving a payment needs the Ethereum endpoint to answer (D43, fail closed).
- A reconfiguration voids every payment approval collected before it (D42); those payments are
  raised again. Approvals given to one set of signers are not carried to another.
- Payments are refused while a reconfiguration is open, and while the vault and its treasury
  disagree about who the signers are (D34).
- The operator funds the relayer, and a relayer out of ETH stops chain work for every vault.
- Only ML-DSA-65 keys can sit on a treasury; SLH-DSA and ML-DSA-87 approvers cannot.

## Limits, stated before anyone asks

- **The verifier is unaudited.** ZKNox say so themselves. That is why this runs on Sepolia and why
  mainnet waits for an independent audit (D35).
- **Password-key approvals are only as trustworthy as the server,** exactly as their votes are:
  the server unwraps that key to sign. The end-to-end claim is for phone-held keys.
- **The phone cannot yet derive an on-chain identity from a public key.** Doing so needs the
  verifier's expanded key form in JavaScript. So the phone takes the server's word for *whose* key
  each identity in a reconfiguration is; it checks the digest, the counts, the threshold and that
  the names match the signed identities one for one. The same gap makes its seat check compare key
  fingerprints rather than on-chain code hashes (plan, Phases 6b and 7b).
- **The contract cannot tell a genuine key from a well-formed one** (D17 residual). Linking and
  every reconfiguration approver compute identities from the real public keys, and linking checks
  everything it deployed against what it read back (D31).
- **Locked funds are possible.** If fewer than M registered keys can ever sign again, the treasury
  cannot be reconfigured. The app warns before any change that would cause this; nothing can undo
  it afterwards.
- **Still classical underneath:** Ethereum consensus, and the relayer's ECDSA key. The latter
  affects availability only.

## Alternatives rejected

- **A contract that trusts the server's key.** Moves the trust instead of removing it.
- **ZKNox's deployed ML-DSA-44 verifier.** It would have meant changing the vault's algorithm to
  fit the chain.
- **Relinking a new treasury after every membership change.** Each relink costs ~0.03 ETH and
  strands the old treasury's funds behind the old keys (D39).
- **Syncing signers automatically.** That would let the server change who controls the funds; the
  current signers approve every change instead (D39, D45).
- **Mainnet now.** Real money behind an unaudited verifier is not a trade-off this project gets to
  make.
