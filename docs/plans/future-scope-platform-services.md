# Future scope: Q-Vault as a platform other applications use

**Status:** future scope, recorded 2026-10-15. Nothing built. This is the direction the owner chose
to record after the SaaS rework was finished and tested: not more screens inside Q-Vault, but
services any real-world application can plug into.

## The idea

A real SaaS sells a capability, not a screen. Stripe sells payments to any app, Auth0 sells login,
Twilio sells messaging, each through an API. Q-Vault today uses its security system for one
product: vaults and decisions. The same system can be sold as capabilities that other companies'
applications call.

What Q-Vault already has, and what every service below reuses:

1. **Post-quantum identity.** Each user has an ML-DSA key, wrapped under their password or held
   on their phone. Old keys are retired but kept, so past signatures still verify after rotation.
2. **M-of-N quorum.** Policies, a frozen list of who may sign, and an approval state machine that
   counts only signatures that verify.
3. **Public verifiability.** An RFC 6962 Merkle log, an independent witness, receipts, and an
   offline verifier (CLI and a single HTML file) that needs no trust in the server.
4. **Encryption at rest.** AES-256-GCM, with the key wrapped by ML-KEM.
5. **Crypto-agility.** Algorithms are switchable, and every artefact pins the algorithm it used.

## The four services

### 1. Approvals API: "this action needs 2 of 3 people"

Almost every company hand-builds approvals: refunds over a limit, deleting customer data, changing
payroll bank details, deploying to production, granting admin rights. These are usually an `if`
statement and a chat message, and they are easy to forge.

- **How it works:** the customer's app calls `POST /approvals {action, policy}`. Q-Vault notifies
  the approvers, they sign on the web or the phone, and the app gets back a signed approval token.
  The app verifies the token itself before acting.
- **Who would use it:** fintech, HR and payroll tools, SaaS admin panels, banks.
- **Comparable products:** Ramp and Zip (spend approvals only), ConductorOne and Opal (access
  approvals only). Neither offers approval as a general primitive.
- **Reuses:** `approval_service`, `signing`, `api` blueprint, notifications and push.

### 2. Tamper-proof audit log API

Regulated companies (finance, healthcare, anything under SOC 2 or HIPAA) must prove their logs were
not edited afterwards. Most trust their own database.

- **How it works:** the customer's app streams events to Q-Vault. Each event goes into the Merkle
  log, the witness co-signs the checkpoints, and the app gets an inclusion proof. An auditor checks
  the whole history offline, without trusting the company or Q-Vault.
- **Why now:** AWS retired QLDB, its managed ledger database, in 2025, and its customers had to
  migrate.
- **Reuses:** `qvault/transparency/`, `checkpoint_service`, `receipt_service`, the witness,
  `qvault/verify/`.

### 3. Signing and timestamping API: quantum-safe signatures as a service

Most developers cannot run ML-DSA correctly themselves. Q-Vault's own finding shows this: the
installed tooling labelled a pre-standard SPHINCS+ construction as FIPS 205.

- **How it works:** the customer's app sends a hash and gets back an ML-DSA signature and a
  trusted timestamp. Q-Vault handles key rotation and algorithm switching.
- **Uses:** software and firmware release signing (the release ships only when 2 of 3 maintainers
  sign), contracts that must stay valid for decades, proof that a document existed on a date.
- **Reuses:** the crypto registry, `key_service`, `rotation_service`, the log for timestamps.

### 4. Quorum-protected secrets

Root credentials, cloud master keys, wallet seeds and database passwords should never be in one
person's hands.

- **How it works:** the secret is revealed only when M of N approve, for a limited time, and every
  reveal is logged.
- **Comparable products:** HashiCorp Vault, CyberArk break-glass access. Neither has quantum-safe
  signatures or public verifiability.
- **Design choice to make first:** in the simple version the server holds the decryption key and
  only policy stops an early release (the same trust model as HashiCorp Vault). The stronger
  version splits the secret with Shamir's scheme and encrypts one share to each approver's own
  ML-KEM key, so the secret can only be rebuilt when M approvers decrypt on their own devices. That
  needs a per-user ML-KEM key, which Q-Vault does not have yet (only vaults have KEM keys). Ship
  the simple version first and label it honestly.

## Why this is a business now

Governments have set deadlines to move off RSA and elliptic-curve cryptography. Check the exact
wording before citing any of these in the report or paper.

- **NIST IR 8547:** deprecates RSA and ECC around 2030 and disallows them around 2035.
- **NSA CNSA 2.0:** requires quantum-safe software and firmware signing by 2030.
- **EU coordinated roadmap:** migration to start by the end of 2026.

Every company that signs things or keeps audit trails has to migrate. The pitch is that they do not
need to become cryptographers: they call an API.

## Industries the same four services serve

| Industry | What they would use |
| --- | --- |
| Banking and fintech | Approvals for payments, audit log for regulators |
| Healthcare | Audit log proving patient records were not altered |
| Software and DevOps | 2-of-3 release signing, deploy approvals, break-glass production access |
| Legal and real estate | Long-term document signatures and timestamps |
| Education and government | Degree certificates and land records signed by more than one official, verifiable by anyone offline |
| Crypto and Web3 | Treasury approvals (already built on-chain, Sepolia) |

## Suggested order if this is ever built

1. **A developer API with keys per workspace**, starting with the Approvals API and the Audit Log
   API. Both mostly expose the existing engine.
2. **A small client SDK** (Python or JavaScript) and a verifier library, so the customer's app
   checks Q-Vault's tokens and proofs itself.
3. **One example app from "another company"** that integrates it: for example, a payroll admin
   panel where changing a bank account needs 2-of-3 approval, or a GitHub Action that blocks a
   deploy until the quorum signs. This shows an unrelated application getting Q-Vault's security
   with a few lines of code.
4. Then signing and timestamping, then quorum-protected secrets.

Constraints that carry over: every user-facing step needs a phone equivalent (phone parity), and
Q-Vault remains a research build that has not been independently audited.

## Smaller in-product ideas, also deferred

Raised in the same discussion, before the platform direction above was preferred:

- Public notarisation page (hash a file, get a witnessed receipt). This is service 3 with a public
  web page in front of it.
- Post-quantum document signing over an uploaded file, checked in the offline verifier.
- Secure data room: encrypted file sharing with a per-recipient ML-KEM key and logged access.
- Dead-man's switch and digital inheritance, built on service 4.
- Quantum-readiness scanner for a domain's TLS certificates and keys. Fits the brand but does not
  use Q-Vault's own security system.
