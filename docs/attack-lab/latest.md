# Q-Vault adversary lab

Generated 2026-09-12T18:21:50+00:00 on Windows-11-10.0.26100-SP0, Python 3.13.5, backend `quantcrypt`. Completed in 7.49s.

Every attack runs twice: once against the system as built, and once against a control in which the named mechanism is removed or the algorithm is swapped. An attack that is blocked in both runs is reported VACUOUS and fails the suite, because it has demonstrated nothing. See `docs/adr/0021-adversary-lab.md`.

**10 of 10 as expected** (0 breached, 0 vacuous, 0 errored).

| # | Attack | Threat model | Real run | Control run | Status |
| - | ------ | ------------ | -------- | ----------- | ------ |
| 1 | Recover a signing key by factoring, then forge an approval | The victim's public key. Nothing else - no secret, no side channel. | succeeded | blocked | as expected |
| 2 | Record an encrypted file now, decrypt it after the quantum computer arrives | A recorded copy of the wrapped key and the ciphertext - a stolen backup. | succeeded | blocked | as expected |
| 3 | Alter an approved decision by one bit | Write access to the signature bytes in transit or at rest. | blocked | succeeded | as expected |
| 4 | Forge under an algorithm you control, then name it in the request | Full control of the submitted artefact, including its algorithm label. | blocked | succeeded | as expected |
| 5 | Reuse one genuine approval somewhere it was never given | A copy of one valid signature - no key, no forgery needed. | blocked | succeeded | as expected |
| 6 | Guess passwords offline against a stolen database | The entire database: salts, wrapped private keys, everything but passwords. | blocked | succeeded | as expected |
| 7 | Manufacture an approval by writing straight to the database | Direct SQL write access. No password, no session, no route involved. | blocked | succeeded | as expected |
| 8 | Join the signer list after the vote opened, then vote | Permission to administer vault membership. | blocked | succeeded | as expected |
| 9 | Edit the audit trail to hide what happened | Direct SQL write access to the ledger table. | blocked | succeeded | as expected |
| 10 | Alter a stored file without the key | Write access to the encrypted blob at rest. | blocked | succeeded | as expected |

## The cost of the attack at real parameters

Classically 6.3e14 core-years (45589x the age of the universe on one core). Quantumly, under 1 week on 1,000,000 noisy qubits (Gidney, arXiv:2505.15917).


## Attack detail

### 1. Recover a signing key by factoring, then forge an approval

- **Asks:** Can you actually break RSA, or are you just citing a paper?
- **Attacker has:** The victim's public key. Nothing else - no secret, no side channel.
- **Trying to:** Forge an approval that the real verifier accepts
- **Stopped by:** None available to RSA. Key recovery defeats every padding scheme. (`qvault/attack/shor.py`)
- **Control:** the identical pipeline pointed at ML-DSA-65
- **Reference:** Shor 1994; Gidney 2025 (arXiv:2505.15917) for the 2048-bit estimate
- **Status:** as expected - Succeeded against the classical algorithm; no traction post-quantum

**Against RSA/ECDSA** - succeeded

1. Victim publishes a signing key. RSA at a scaled 9-bit modulus (see toy_rsa.py for exactly how this differs from RSA-2048). **n=437, e=17**
1. Attacker's starting knowledge. the public key, and nothing else - no secret, no side channel, no implementation flaw. **n=437, e=17**
1. Quantum order-finding. statevector simulation over a 18-qubit control register; the textbook circuit for this modulus needs 27 qubits in total. **262,144 amplitudes held, measured k=26479, phase=26479/262144, order r=198 in 1 shot(s)**
1. Modulus factored. 1 order-finding round(s), 748 ms on this CPU. **437 = 23 x 19**
1. Private exponent recovered. a single modular inverse once the factors are known - no brute force, and nothing the key owner can do about it. **d=35**
1. Forged approval submitted to the real verifier. the canonical vote payload for decision='approve' by signer 7, signed with the recovered key. **verify() returned True**
1. What this does and does not show. the algorithm ran to completion at a scaled parameter. At 2048 bits the same algorithm needs 4,099 logical qubits and cubic gate count, against 6.3e14 core-years classically. **2.3e+11x the work of RSA-250, the largest modulus ever factored**

> The victim's key is a scale model; the attack is not. Key recovery defeats any padding, so the textbook signing in toy_rsa.py is not what lost.

**Against the post-quantum algorithm** - blocked

1. Victim publishes a signing key. ML-DSA-65, FIPS 204 - the project's default. **public key 1952 bytes**
1. Step 1 of the pipeline: obtain a modulus to factor. an ML-DSA public key is (rho, t1): a 32-byte seed and a vector of packed polynomial coefficients. There is no integer modulus, no group element, and no order to find. **no input available**
1. Why the attack has no formulation rather than merely failing. The ML-DSA secret is a pair of short vectors over a polynomial ring, and recovering it is a Module-LWE problem. There is no group element whose order encodes it, so there is no period for phase estimation to find. Shor's algorithm does not fail against ML-DSA; it has no input to be given.. **3 preconditions required, 0 present**
1. Fallback: blind forgery, the best attack actually available. 2,000 random signatures of the correct length submitted to the real verifier. The signature space is 2^26472, so the expected number of successes is 2000 / 2^26472. **0 accepted**
1. Best known quantum improvement. Grover-accelerated lattice sieving — sub-quadratic at best, leaving the cost exponential in the lattice dimension. This is the reason NIST's categories are expressed against both classical and quantum attack cost.. **still exponential**

> This is the state of public knowledge, not a proof. No lower bound on quantum lattice algorithms is known, which is exactly why the project also demonstrates agility: the response to a break is to switch algorithms, not to have bet correctly.

### 2. Record an encrypted file now, decrypt it after the quantum computer arrives

- **Asks:** Why migrate today if no quantum computer exists today?
- **Attacker has:** A recorded copy of the wrapped key and the ciphertext - a stolen backup.
- **Trying to:** Read a file that was encrypted years before the attack
- **Stopped by:** ML-KEM-768 wrapping: the recording gives the attacker no factoring target. (`qvault/crypto/providers/quantcrypt_kem.py`)
- **Control:** the identical capture wrapped with ML-KEM-768 instead of RSA
- **Reference:** NIST IR 8547 ipd - the migration timeline this threat drives
- **Status:** as expected - Succeeded against the classical algorithm; no traction post-quantum

**Against RSA/ECDSA** - succeeded

1. 2026: attacker records the traffic. public key, RSA-wrapped data-encryption key, and the AES-256-GCM blob. The AES layer is at full strength and is never attacked. **n=403, wrapped DEK 2 B (scaled modulus; RSA-2048 would be 256 B), ciphertext 128 B**
1. 2026: attacker tries to read it. AES-256-GCM with an unknown key - nothing to do but store the capture and wait. **no plaintext**
1. Years later: a quantum computer exists. the recorded capture is still valid. Rotating the key in the meantime would not have helped - the ciphertext was already taken. **403 = 31 x 13, d=53**
1. Data-encryption key unwrapped, file decrypted. the AES-256-GCM tag verifies, because this is the genuine key. **112 bytes recovered: 'BOARD MINUTES - CONFIDENTIAL'**

> This is why confidentiality cannot wait for a quantum computer to appear. A signature forged in 2035 is an attack on 2035; a file recorded in 2026 is an attack on 2026, carried out later.

**Against the post-quantum algorithm** - blocked

1. 2026: attacker records the traffic. the identical capture - public key, wrapped data-encryption key, AES-256-GCM blob. **public key 1184 B, wrapped DEK 1088 B**
1. Attempt the pipeline that worked against RSA. step 1 needs an integer modulus to factor. An ML-KEM public key is a seed plus packed polynomial coefficients over a module lattice; there is nothing to factor. **no input available**
1. Fallback: guess the 256-bit data-encryption key. the AES-256-GCM authentication tag rejects a wrong key. The search space is 2^256, and Grover's algorithm reduces that to about 2^128 operations - still out of reach, and the reason ML-KEM-768 targets NIST category 3. **1 attempt, accepted=False**

> The capture stays a capture. Note what is *not* claimed: ML-KEM is not proven unbreakable, only that no published attack applies. The system's answer to that residual risk is agility - the ability to change algorithm without losing the data.

### 3. Alter an approved decision by one bit

- **Asks:** What happens if someone edits a signed approval?
- **Attacker has:** Write access to the signature bytes in transit or at rest.
- **Trying to:** Have a modified approval accepted as genuine
- **Stopped by:** ML-DSA verification over the exact canonical bytes (ADR-0010). (`qvault/crypto/providers/quantcrypt_signature.py`)
- **Control:** the verifier reduced to a signature-length check
- **Reference:** FIPS 204
- **Status:** as expected - Blocked — and the control confirms the named mechanism is what blocked it

**Against the real system** - blocked

1. Genuine approval signed. ML-DSA-65 over the canonical vote payload. **signature 3309 bytes, sha256 00fd9da6d0b749a8f3a4dd829bad151d**
1. One bit flipped. the least significant bit of byte 0 - the smallest possible change. **sha256 80d7e2e4f061d904c4154246600eafe7**
1. Submitted to the real verifier. **verify() returned False**

**Against the control** - succeeded

1. Verifier replaced with a length check. accept any 3309-byte blob - the 'signature as opaque token' mistake. **accepted=True**

### 4. Forge under an algorithm you control, then name it in the request

- **Asks:** Your system supports several algorithms - can I pick the weak one?
- **Attacker has:** Full control of the submitted artefact, including its algorithm label.
- **Trying to:** Have the system verify a forgery under an attacker-chosen algorithm
- **Stopped by:** alg_id, backend and public_key are pinned to the signer's Key row (ADR-0001). (`qvault/models/signature.py`)
- **Control:** the verifier resolving alg_id from the attacker's own claim
- **Reference:** the JWT 'alg' confusion class (CVE-2015-9235 and successors)
- **Status:** as expected - Blocked — and the control confirms the named mechanism is what blocked it

**Against the real system** - blocked

1. Victim's registered key. alg_id and public key are pinned to the signer's Key row at the moment of signing. **pinned alg_id=ML-DSA-65**
1. Attacker forges under an algorithm they own. a valid RSA-TOY-9 signature over the identical payload, made with a key they generated themselves. **claimed alg_id=RSA-TOY-9, signature 2 bytes**
1. Verification resolves the provider from the PINNED alg_id. the attacker's claim is never consulted, so the forgery is checked as ML-DSA against the victim's real public key. **verify() returned False**

**Against the control** - succeeded

1. Verifier resolves alg_id from the submitted artefact. the attacker names the algorithm and supplies the matching public key - the same shape as JWT alg confusion. **accepted=True under RSA-TOY-9**

### 5. Reuse one genuine approval somewhere it was never given

- **Asks:** Could an approval of one thing be replayed as approval of another?
- **Attacker has:** A copy of one valid signature - no key, no forgery needed.
- **Trying to:** Make a genuine signature authorise a different decision, proposal or signer
- **Stopped by:** Domain-separated canonical payloads: DS_VOTE binds every deciding field. (`qvault/services/signing.py`)
- **Control:** a payload that signs only the decision word
- **Reference:** domain separation, NIST SP 800-185
- **Status:** as expected - Blocked — and the control confirms the named mechanism is what blocked it

**Against the real system** - blocked

1. One genuine approval, signed once. decision=approve on proposal A by signer 7. **signature sha256 9358d13ef15bf6048542f1e523beb992**
1. Replay: flip the decision to reject. the same signature bytes, presented against a different canonical payload. **verify() returned False**
1. Replay: move the vote to another proposal. the same signature bytes, presented against a different canonical payload. **verify() returned False**
1. Replay: attribute the vote to another signer. the same signature bytes, presented against a different canonical payload. **verify() returned False**
1. Replay: reuse it to enrol an attacker-controlled device. the same signature bytes, presented against a different canonical payload. **verify() returned False**

> Every field the decision depends on is inside the signed bytes, behind the DS_VOTE domain tag, so there is no context the signature can be moved to.

**Against the control** - succeeded

1. Weakened payload: the decision word alone. no domain separation, no proposal binding, no signer binding. **signed bytes = b'approve'**
1. Replay onto any other proposal. the bytes carry nothing that identifies which proposal was approved, so the same signature is a valid approval of every proposal in the system. **accepted=True**

### 6. Guess passwords offline against a stolen database

- **Asks:** If the database leaks, how long do the signing keys last?
- **Attacker has:** The entire database: salts, wrapped private keys, everything but passwords.
- **Trying to:** Recover a password and unwrap the signing key it protects
- **Stopped by:** Argon2id at memory-hard parameters, with a unique salt per user. (`qvault/crypto/kdf.py`)
- **Control:** the password store weakened to a single unsalted SHA-256
- **Reference:** OWASP password storage; RFC 9106 (Argon2)
- **Status:** as expected - Blocked — and the control confirms the named mechanism is what blocked it

**Against the real system** - blocked

1. Stolen database. Argon2id at the application's parameters: t=3, m=64 MiB, p=4. **salt 16 bytes, 400 candidate passwords**
1. Dictionary attack, 2-second budget. each guess must pay the full Argon2id cost; there is no shortcut and no precomputation, because the salt is unique per user. **40 of 400 candidates tried, 19.9 guesses/sec**
1. Extrapolated cost. at the measured rate, an eight-character lowercase-alphanumeric space (36^8) would take 4,502 years of one machine's time. **19.9 guesses/sec**

**Against the control** - succeeded

1. Password store weakened to one SHA-256 pass. no salt, no iteration count - a design still found in production systems. **400 candidates in 0.48 ms (839,278 guesses/sec)**
1. Result. the same dictionary, the same machine, the same budget. **recovered 'correct-horse-battery-staple'**

### 7. Manufacture an approval by writing straight to the database

- **Asks:** What if someone gets into your database?
- **Attacker has:** Direct SQL write access. No password, no session, no route involved.
- **Trying to:** Reach the M-of-N threshold with an approval nobody gave
- **Stopped by:** tally() counts only signatures that currently verify. (`qvault/services/approval_service.py`)
- **Control:** a tally that counts the decision column instead of verifying
- **Status:** as expected - Blocked — and the control confirms the named mechanism is what blocked it

**Against the real system** - blocked

1. Starting state. one genuine rejection; the proposal needs 2 approvals of 3 signers. **tally approvals=0 rejections=1**
1. Attacker writes an approval row directly. a real signature blob, copied from the genuine rejection, relabelled as an approval and attributed to a different signer. **row id=2, decision=approve, signer_id=2**
1. The database now contains the approval. counting rows would report it. **1 row(s) with decision=approve**
1. The tally verifies instead of counting. approval_service.tally re-verifies every signature against the proposal's canonical payload, so a row whose signature does not verify contributes nothing. **tally approvals=0 rejections=1**

> The attacker can write whatever they like into the signatures table. They cannot make it verify, and only verification counts.

**Against the control** - succeeded

1. Tally weakened to counting the decision column. the shape almost every approval workflow uses: trust the row, the signature is decoration. **approvals 0 -> 2, threshold is 2**

> Two inserted rows, no valid signatures, and the proposal is approved.

### 8. Join the signer list after the vote opened, then vote

- **Asks:** Can the membership be changed to change the outcome?
- **Attacker has:** Permission to administer vault membership.
- **Trying to:** Vote on a proposal that opened before the attacker was authorised
- **Stopped by:** The proposal freezes its authorised-signer set at creation. (`qvault/models/proposal.py`)
- **Control:** authorisation checked against live membership rather than the snapshot
- **Status:** as expected - Blocked — and the control confirms the named mechanism is what blocked it

**Against the real system** - blocked

1. Proposal opens and freezes its signer list. the set of authorised signers is captured on the proposal row at creation. **snapshot = [7, 8]**
1. Attacker is added to the vault afterwards. through the real membership service - this part succeeds, and should: vault membership is allowed to change. **intruder id=9 is now a vault member**
1. Attacker votes on the already-open proposal. the vote is checked against the frozen snapshot, not the live membership. **accepted=False (ApprovalError: You are not an authorised signer for this proposal.)**

> Membership may change; who could decide *this* proposal may not. The snapshot is what makes the second sentence true.

**Against the control** - succeeded

1. Authorisation weakened to 'is a current vault member'. the natural implementation, and the one that loses: it answers a question about now, when the question is about when the proposal opened. **live members [10, 11, 12] vs frozen snapshot [10, 11]**
1. Attacker's vote under the weakened check. they joined after the freeze, so only the live check lets them in. **accepted=True**

### 9. Edit the audit trail to hide what happened

- **Asks:** The log is in the same database - why would I believe it?
- **Attacker has:** Direct SQL write access to the ledger table.
- **Trying to:** Change a recorded event and leave the log self-consistent
- **Stopped by:** Hash-chained entries: each commits to its predecessor's digest. (`qvault/services/ledger_service.py`)
- **Control:** an append-only audit table with no hash chaining
- **Status:** as expected - Blocked — and the control confirms the named mechanism is what blocked it

**Against the real system** - blocked

1. Audit trail before the attack. a hash chain: each entry commits to the previous entry's digest, and the head is signed by the SYSTEM anchor key. **37 entries, chain_ok=True, anchor_ok=True, overall ok=True**
1. Attacker edits a committed entry. entry seq=36, payload_json replaced by direct database write and confirmed re-read from the database. **payload sha256 ee3d7d34a7b1b42c -> 38dfe37a585a7144**
1. Chain re-verified. the edited entry's digest no longer matches the one its successor commits to, so the walk stops at the tampered row. **chain_ok=False, first break at seq=36, overall ok=False**

> Detection, not prevention. A database writer can always change a row; what they cannot do is leave the chain consistent afterwards.

**Against the control** - succeeded

1. Integrity check weakened to 'the rows are all there, in order'. what a timestamped audit table actually guarantees: that nothing was deleted, not that nothing was changed. **before=True, after=True**
1. Result. the entry now says something it never said, and the log agrees with itself. **undetected=True**

### 10. Alter a stored file without the key

- **Asks:** Encryption hides the file - but can someone change it?
- **Attacker has:** Write access to the encrypted blob at rest.
- **Trying to:** Change the contents of an encrypted attachment undetected
- **Stopped by:** AES-256-GCM: the authentication tag covers the ciphertext. (`qvault/crypto/symmetric.py`)
- **Control:** AES-256-CTR, i.e. encryption without authentication
- **Status:** as expected - Blocked — and the control confirms the named mechanism is what blocked it

**Against the real system** - blocked

1. File encrypted at rest. AES-256-GCM, the key wrapped under the vault's ML-KEM keypair. **68 B plaintext -> 84 B ciphertext+tag**
1. Attacker flips one bit of the stored ciphertext. no key required; this is a write to the blob on disk. **byte 8: 0x2e -> 0x6e**
1. Download attempted. GCM recomputes the authentication tag over the ciphertext it was given. **decrypt raised InvalidTag**

> The tag makes the file tamper-evident, not merely unreadable: the difference between 'nobody can read this' and 'nobody can change this without being caught'.

**Against the control** - succeeded

1. Authentication removed: AES-256-CTR instead of GCM. confidentiality without integrity - still a common configuration. **68 B ciphertext, no tag**
1. Attacker edits the amount through the ciphertext. CTR is a stream cipher, so a flipped ciphertext bit flips exactly that plaintext bit. The attacker never learns the key and never needs to. **recovered plaintext now reads: '850,000'**
1. Decryption succeeds and reports no error. **silently altered=True**
