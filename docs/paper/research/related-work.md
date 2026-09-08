# Related Work — thematic map for the Q-Vault paper

**Status:** research notes, first pass. Compiled 2026-09-08.
**Companion file:** [`references.bib`](references.bib) — every citation key used below is defined there.

## How this file was built, and what that means for trust

Every work cited below was verified by actually fetching a primary page: the standard's own
PDF, a publisher landing page, an IACR ePrint record, an arXiv abstract page, an IETF RFC
Editor or datatracker page, Crossref REST metadata, or — for the library claims — the source
tree installed in this repository. Nothing here was written from memory.

Where a work could not be verified it is **not** in `references.bib`; it is in the
[TO VERIFY](#to-verify) section at the end, and must not be cited until checked.

Three sources that resist automated fetching (ACM DL, IEEE Xplore, USENIX, dblp) were verified
through Crossref or OpenAlex publisher-deposited metadata. That is authoritative for
title/authors/venue/pages/DOI but is **not** a substitute for reading the paper. Anything
quoted from those papers must be checked against the PDF before submission.

---

## 1. NIST post-quantum standardisation

### What the prior work says

The NIST Post-Quantum Cryptography project was created on 3 January 2017 and ran a multi-round
public competition [`nist-pqc-project`]. On **13 August 2024** NIST published the three principal
standards simultaneously:

| Standard | Title | Algorithm | DOI |
|---|---|---|---|
| FIPS 203 | Module-Lattice-Based Key-Encapsulation Mechanism Standard | ML-KEM-512/768/1024 | `10.6028/NIST.FIPS.203` |
| FIPS 204 | Module-Lattice-Based Digital Signature Standard | ML-DSA-44/65/87 | `10.6028/NIST.FIPS.204` |
| FIPS 205 | Stateless Hash-Based Digital Signature Standard | SLH-DSA, 12 parameter sets | `10.6028/NIST.FIPS.205` |

Note the publication date carefully: the CSRC records give **13 August 2024**, while the Federal
Register notice announcing issuance is dated 14 August 2024. Use 13 August 2024 and cite the DOI.

FIPS 203 carries a NIST planning note dated 17 November 2025 flagging an issue to be corrected in
a future update — worth a footnote if the paper claims to implement FIPS 203 exactly.

The transition timetable is set out in NIST IR 8547 ipd [`nist-ir8547`], published 12 November
2024, which describes NIST's expected approach to retiring quantum-vulnerable algorithms.

### Where Q-Vault sits

Q-Vault implements all three families together (ML-KEM-768 for confidentiality, ML-DSA-65 and
SLH-DSA-SHAKE-256f for signatures). **This is not novel.** Implementing published standards is
table stakes; dozens of libraries and products do it. The paper should claim the *integration* —
three families, one agility layer, one artefact format — not the algorithms.

What *is* worth saying: the project uses both a lattice signature and a hash-based signature
side by side and keeps a heterogeneous corpus verifiable, which is a deployment posture NIST IR
8547 and the NCCoE migration project explicitly anticipate but which few systems demonstrate end
to end.

---

## 2. The underlying schemes

### What the prior work says

- **Kyber → ML-KEM.** `bos2018kyber` (EuroS&P 2018, pp. 353–367) is the design paper: a CCA-secure
  KEM whose security rests on Module-LWE. FIPS 203 states it is derived from the CRYSTALS-KYBER
  submission.
- **Dilithium → ML-DSA.** `ducas2018dilithium` (TCHES 2018(1):238–268) introduces the Fiat–Shamir-
  with-aborts lattice signature that deliberately avoids discrete Gaussian sampling so it can be
  implemented in constant time.
- **SPHINCS+ → SLH-DSA.** `bernstein2019sphincsplus` (CCS 2019) is the framework paper, contributing
  FORS and tweakable hash functions. Two submission documents matter and must be distinguished:
  **v3** (2020, the round-3 submission, FIPS 205 ref [4]) [`sphincsplus-r3`] and **v3.1** (2022,
  FIPS 205 ref [10]) [`sphincsplus-r31`]. FIPS 205 states it is based on v3.1. **This distinction is
  load-bearing for §9 of this document.**
- **Ancestry.** SLH-DSA descends from Merkle's tree signatures [`merkle1989certified`] via XMSS
  [`rfc8391`]; the stateful schemes are approved separately in SP 800-208 [`nist-sp800-208`].

### Where Q-Vault sits

Q-Vault contributes nothing to scheme design and should say so plainly. These are background
citations. The one place the scheme literature earns its keep in the paper is the SLH-DSA
signature-size and signing-cost discussion (§7) and the round-3-vs-FIPS-205 finding (§9).

---

## 3. Crypto-agility

### What the prior work says

This is the area where Q-Vault's headline claim is **most exposed**, because crypto-agility is a
crowded and increasingly well-specified field.

**Standards and guidance.**
- `rfc7696` (BCP 201, November 2015) is the foundational IETF guidance. It requires that a protocol
  using cryptographic algorithms *"MUST include a mechanism to identify the algorithm or suite that
  is being used"*, warns that algorithm negotiation must itself be integrity-protected, and cautions
  against both too many choices and a single immutable suite. **Q-Vault's "every artefact pins its
  `alg_id`" invariant is a direct instance of this requirement, not an invention.**
- `nist-cswp39` — *Considerations for Achieving Crypto Agility: Strategies and Practices*. Careful:
  CSWP 39 was **withdrawn on 29 June 2026** and superseded in its entirety by **CSWP 39-upd1**.
  Cite the `-upd1` DOI.
- `nist-ir8547` and `nccoe-sp1800-38` (NCCoE Migration to PQC practice guide, volumes A/B/C) supply
  the migration framing; volume B is cryptographic discovery, volume C is interoperability and
  performance testing.
- `rfc9958` (*Post-Quantum Cryptography for Engineers*, August 2026) — the IETF PQUIP working
  group's guidance, formerly `draft-ietf-pquip-pqc-engineers`. Now a published RFC; cite the RFC,
  not the draft.

**Academic.**
- `naether2024agility` — a systematic review of 84 screened sources that finds "cryptographic
  agility" is *inconsistently defined*, identifies six definition categories and proposes a
  canonical one. This is the single best citation for "the term needs pinning down before you claim
  it".
- `alnahawi2023cryptoagility` — survey of requirements, characteristics and challenges.
- `wiesmaier2021migration` — PQC migration and crypto-agility literature survey.
- `badertscher2023agile` (TCC 2023) — the theory side: formalises updateability as an *updatable
  ideal functionality* in the UC model, capturing which security properties survive an algorithm
  update. Notably it isolates exactly the property Q-Vault relies on: security is retained *provided
  the update happens before the deprecated implementation is exploited*.

### Where Q-Vault sits

**Honest assessment: the mechanism is not novel, the discipline of it might be.**

- A registry resolving algorithms by identifier at runtime is standard practice (JOSE/COSE algorithm
  registries, OpenSSL providers, liboqs' `OQS_SIG_new(name)`).
- Pinning the algorithm in the stored artefact is RFC 7696's explicit requirement.
- "Switch the default; never re-encode existing data" (ADR-0006) is a sensible engineering rule, not
  a research contribution.

What the paper *can* defensibly claim, given `naether2024agility`'s finding that the term is
vaguely defined:

1. **An operational definition with a test.** Q-Vault's agility claim is falsifiable — the admin
   page re-verifies every stored signature and anchor under its *pinned* algorithm after a switch.
   Most crypto-agility literature is definitional or architectural; comparatively little of it
   ships a running system with a mechanised demonstration that a mixed-algorithm corpus still
   verifies.
2. **Agility across two *paradigms*, not two parameter sets.** Switching ML-DSA-65 → ML-DSA-87 is
   easy. Switching ML-DSA → SLH-DSA changes the signature from ~3.3 KB to ~49.9 KB and the signing
   cost by more than an order of magnitude. That is a real stress test of the abstraction, and it is
   what `badertscher2023agile`'s notion of updateability is actually about.
3. **The retired-key case.** See §5 below — agility interacts with key rotation, and the interaction
   is where most implementations break.

The paper should **not** claim to have invented crypto-agility, an algorithm registry, or artefact
self-description. It should position them as a faithful implementation of RFC 7696 and CSWP 39-upd1
guidance, and claim the *demonstration*.

---

## 4. Transparency logs, Certificate Transparency, and witnessing

### What the prior work says

**The construction.** `rfc6962` (June 2013) defines everything Q-Vault's log uses: the Merkle Tree
Hash with `0x00`/`0x01` leaf/interior prefixes, inclusion proofs, consistency proofs, and signed
tree heads. `rfc9162` (December 2021) is version 2.0 and obsoletes it — though deployed logs still
implement 6962, which is worth one sentence to justify targeting 6962. `laurie2014ct` is the
designer's accessible framing.

**Measurement and deployment.** `stark2019ctbreakweb` shows CT is deployable at internet scale.
`scheitle2018riseofct` quantifies log growth and its privacy side-effects. `gustafsson2017ctlandscape`
characterises operating logs. **`li2019monitors` is the most directly useful**: it shows that real CT
monitors are unreliable in practice — the empirical argument for adding an independent witness rather
than trusting a monitoring service. `kumar2018misissuance` shows what log auditing actually catches.

**Gossip — the road not taken.** `nordberg-ctgossip` (`draft-ietf-trans-gossip-05`) defines SCT
Feedback, STH Pollination and the Trusted Auditor Relationship, framed explicitly against a log
"presenting a split view". **It expired without publication.** `chuat2015gossip` is the foundational
academic gossip paper; `dahlberg` (see TO VERIFY) proposes network-level aggregation;
`oxford2020quantitative` model-checks how often gossip actually detects a split world;
`meiklejohn2020thinkglobal` argues clients should audit for themselves.

**Witnessing — the road taken.** This is the direct prior art for Q-Vault's witness:
- `syta2016cosigning` (IEEE S&P 2016) — CoSi, the origin of "witness cosigning": a statement is
  validated and publicly logged by a diverse group of witnesses before any client accepts it.
- `c2sp-tlog-witness` — the C2SP *Transparency Log Witness Protocol*. **This is the closest existing
  specification to what Q-Vault built.** The log submits a new checkpoint plus an RFC 6962
  consistency proof; the witness checks the offered old size against the latest checkpoint it
  cosigned for that origin and **MUST respond `409 Conflict` if it does not match**; the check and
  the persist **must be atomic**.
- `c2sp-tlog-cosignature` (v1.0.0) and `c2sp-tlog-checkpoint` — the wire formats. The checkpoint spec
  explicitly says clients MUST ignore unknown signatures *"to enable, for example, log key rotation,
  and witness cosigning"*.
- `sigsum-design` — the deployed system architecturally closest to Q-Vault. Sigsum deliberately
  **replaces reactive gossip with proactive witness cosigning**; witnesses poll at least once per
  minute, require tree heads no older than five minutes, and against honest witnesses an attacker
  *"can at most deny service"*.
- `transparencydev-witness` — the operational rule of thumb: **one witness proves append-only; a
  quorum detects split views.** Describes ArmoredWitness (15 deployed devices).
- `nikitin2017chainiac` — collective signing applied to a software-update log.
- `cox2019tlog` / `cox2019sumdb` — the Go checksum database. (Exact title is *"Transparent Logs for
  Skeptical Clients"*, not "for Skeptics".) `cox2019sumdb` specifies an auditor role and
  proxy-mediated gossip for fork detection.
- `tomescu2017catena` — the alternative: anchor in Bitcoin so forking costs a double-spend.
- `merkle-tree-certs` (`draft-ietf-plants-merkle-tree-certs-05`) — **the PQC/transparency
  intersection.** Motivated explicitly by post-quantum signature size (it cites ML-DSA-65's 1,952-byte
  public key and 3,309-byte signature) and defines cosigners that validate an append-only view and
  cosign checkpoints and subtrees.

**Formal and cryptographic depth.** `cheval2023transparencyverification` gives a ProVerif model of CT
including tree-extension proofs. `tomescu2019aad` addresses proof-size cost.
`hicks2023soktransparency` systematises what log-based transparency can and cannot promise.
Key transparency — `melara2015coniks`, `chase2019seemless`, `malvai2023parakeet`,
`keytrans-architecture` — is the adjacent lineage; Parakeet's consensusless distribution of short
consistent commitments solves the same problem a witness does. `newman2022sigstore` is the largest
non-certificate deployment.

### Where Q-Vault sits

**Be blunt in the paper: the witness idea is not new, and the C2SP witness protocol already
specifies it, including the exact refusal semantics.** Claiming novelty here would be
straightforwardly wrong and any examiner who knows the area will catch it.

What is defensible:

1. **Domain transfer, not invention.** Witness cosigning is established in *certificate* and
   *software-supply-chain* transparency. Applying it to an *organisational approval vault* — where
   the thing being made non-repudiable is a business decision rather than a certificate or a binary
   — is a reasonable, modest contribution. Note that the closest neighbours (Sigsum, CT, Go sumdb,
   Sigstore) all publish *public* artefacts, whereas an approval vault must expose a single decision
   without exposing the ledger. That is a genuine difference in the threat model, and it is exactly
   what an inclusion proof is for (ADR-0015 makes this argument: proving decision #4,102 without
   shipping 100,000 entries).
2. **Post-quantum checkpoints.** CT, Sigsum and the Go sumdb all sign checkpoints with Ed25519.
   Q-Vault signs checkpoints with a pinned post-quantum algorithm and the witness has its own PQ
   key. `merkle-tree-certs` shows the community is only now working through what PQC does to
   transparency structures. A PQ-signed, PQ-cosigned checkpoint with an `alg_id` pin is a
   small but real point of difference — **and the honest caveat is that a 49.9 KB SLH-DSA checkpoint
   signature has real cost, which the paper should measure rather than hand-wave.**
3. **Scope honesty.** One witness. `transparencydev-witness` and `sigsum-design` both make clear that
   one witness gives you append-only assurance while split-view resistance needs a quorum. The paper
   must state that limitation explicitly and cite these; claiming split-view resistance from a single
   witness would be false. What one witness genuinely closes is the **truncation/rollback** gap
   ADR-0005 documented and ADR-0015 retired — and that framing is both accurate and defensible.

---

## 5. Tamper-evident logging, hash chains, and key rotation

### What the prior work says

- `haber1991timestamp` (J. Cryptology 3(2):99–111) — linking-and-hashing so a document cannot be
  back-dated or forward-dated, later extended with Merkle trees to batch many documents per interval.
  The ancestor of every hash-chained ledger.
- `schneier1998securelogs` (USENIX Security 1998, pp. 53–62) — the classic forward-secure hash-chained
  audit log on an untrusted machine.
- `crosby2009tamperevident` (USENIX Security 2009) — **the most important citation in this section.**
  The *history tree*. It defines tamper-evidence *semantically, in terms of an auditing process*, and
  gives logarithmic membership and incremental (consistency) proofs. Its own headline comparison is
  the argument for Q-Vault's design: a classic hash chain needs an 800 MB trace to prove one event out
  of 80 million; the tree returns a 3 KB proof.
- `tamassia2003ads` (ESA 2003) — the authenticated-data-structure model: an untrusted responder
  answers queries for a trusted source and supplies a validity proof.
- `nist-sp800-57pt1r5` §7.4 — **the standards statement of retire-but-retain**: keys in the
  *deactivated* state "shall not be used to apply cryptographic protection but, in some cases, may be
  used to process cryptographically protected information", and specifically *"Public signature
  verification keys may be used to verify the digital signatures that were generated before the end
  of the corresponding private key's originator-usage period."*

### Where Q-Vault sits

**Nothing in this section is novel to Q-Vault, and the paper should say so in one sentence each.**

- The hash-chained append-only ledger with server-signed head anchors is Schneier–Kelsey plus a
  signature. Standard.
- Layering an RFC 6962 tree *over* the chain (ADR-0015: each leaf is the chain's existing
  `entry_hash`) is a sensible engineering composition. The *motivation* for it is precisely
  Crosby & Wallach's argument, and the paper should cite them for it rather than re-deriving it.
- **"Retire-but-retain" is NIST SP 800-57 §7.4's deactivated state.** ADR-0007 named it
  independently, which is fine, but the paper must cite SP 800-57 and present the design as
  conforming to it — not as a new idea. The genuinely useful engineering statement is the
  *invariant*: verification resolves the key pinned in the artefact (`signature.key_id`,
  `VaultFile.kem_key_id`), never "the current key". That invariant is what makes rotation and
  algorithm switching safe by construction, and it is worth stating precisely because it is the
  thing implementations most often get wrong.

---

## 6. Multi-signature and threshold signatures in the post-quantum setting

This is the section that **justifies a design decision**, so it needs the strongest sourcing. The
evidence is good.

### What the prior work says

**Classical baseline.**
- `rfc9591` — FROST, the IRTF CFRG threshold Schnorr protocol. It depends only on a prime-order group
  and a hash, so **it has no direct post-quantum analogue**. This is the cleanest way to show what is
  lost in the PQ transition.
- `bellare2006multisig` (CCS 2006) — the foundational multi-signature paper. Crucially, its own
  abstract states the baseline Q-Vault uses: *"A trivial way to implement a multi-signature scheme is
  to let the multi-signature of message m be the list"* of each signer's individual signature. It is
  large, but it requires no distributed key generation and no proofs of knowledge at registration.
  **Q-Vault's application-level M-of-N is precisely this "trivial" construction — and the paper should
  own that word, because Bellare and Neven's objection to it is signature *size*, which is a very
  different problem from the *security* and *feasibility* problems that afflict PQ thresholding.**

**Why PQ thresholding is hard — concrete, citable evidence.**
- `sedghighadikolaei2025thresholdsurvey` (ACM Computing Surveys 58(6), Article 143, December 2025) is
  the key citation.
  - **Hash-based (§7.2):** SPHINCS+ requires **321,553 SHA-3 calls**; with efficient garbled-circuit
    implementations the thresholded execution time is *"estimated to be around 85 minutes"*, and
    following the natural order of operations *"could significantly prolong the execution time by
    several hundred minutes."* An 85-minute signing operation is not a design option for an approval
    vault.
  - **Lattice (§7.1):** rejection sampling is the obstacle — intermediate values must stay
    confidential until sampling completes, requiring garbled-circuit MPC for non-linear operations
    *and* secret-sharing MPC for linear operations, plus daBit conversions between them.
- `delpino2025compactthreshold` (PKC 2025) is the state of the art and is *still* limited: signature
  sizes close to a single Dilithium signature, but **only for thresholds of at most 8 users**, and
  the abstract concedes that difficulties such as sharing a secret in small shares and simulating
  rejecting transcripts *"have kept such an efficient threshold signature out of reach until now."*
- `desclavis2026thresholding` (2026 preprint) surveys the whole space and notes that applications
  remain dominated by pre-quantum signatures.
- `nist-ir8214c` — NIST's threshold effort is still a **call for submissions** (2nd public draft,
  March 2025), whose Class N was only recently extended to include NIST PQC-selected primitives.
  There is no NIST threshold standard for ML-DSA or SLH-DSA. **FIPS 204 and FIPS 205 define no
  threshold or multi-signature mode at all.**
- `fleischhacker2022squirrel` (CCS 2022) and `fleischhacker2023chipmunk` (CCS 2023) show PQ
  multi-signatures *do* exist but in a restricted **synchronized, a-priori bounded** setting:
  Squirrel's individual signature is 52 KB and its aggregate 771 KB; Chipmunk compresses 8,192
  signatures to ~136 KB at 112-bit security. Neither is a drop-in for "M of these N named humans
  approved this proposal".
- `porechna2026thresholdauth` (2026 preprint) independently reaches Q-Vault's conclusion:
  *"standardized hash-based signatures resist efficient threshold signing, and lattice-based
  threshold protocols remain an emerging research track"*, and therefore separates member
  authentication from threshold authorization so that changing signature scheme becomes a key
  rotation rather than a protocol redesign.

### Where Q-Vault sits

**This is the project's best-supported design argument, and the citations carry it.** The chain runs:

1. FIPS 204/205 define no threshold mode; NIST's threshold work is still a call, not a standard
   [`nist-ir8214c`].
2. The classical option, FROST, is group-based and does not transfer [`rfc9591`].
3. Generic MPC thresholding of SLH-DSA costs ~85 minutes per signature
   [`sedghighadikolaei2025thresholdsurvey`].
4. Lattice thresholding is blocked on rejection sampling, and even the 2025 state of the art caps at
   8 signers [`delpino2025compactthreshold`].
5. PQ multi-signatures exist but only synchronized and bounded
   [`fleischhacker2022squirrel`, `fleischhacker2023chipmunk`].
6. Therefore: enforce M-of-N in application logic over independent single-signer signatures — the
   "trivial" multi-signature [`bellare2006multisig`] — which is exactly the separation
   `porechna2026thresholdauth` argues for.

**The honest cost, which the paper must state.** The trivial construction gives up the two things
threshold signatures provide: (a) a *constant-size* combined signature — Q-Vault's approval evidence
grows linearly in M, which with SLH-DSA at 49.9 KB per signature is a real storage and transport
cost worth measuring; and (b) *cryptographic* rather than *procedural* enforcement of the threshold —
an attacker who fully controls the application server can count to M incorrectly, whereas a threshold
signature cannot be forged without t shares. Q-Vault's mitigations (frozen authorised-signer
snapshot, `UNIQUE(proposal_id, signer_id)`, re-verifying every stored signature at count time rather
than trusting a cached flag, and the transparency log making the tally externally checkable) reduce
but do not eliminate that gap. Say so.

---

## 7. PQC performance evaluation

### What the prior work says

**Methodology.** `kannwischer2019pqm4` and `kannwischer2024pqm4` (pqm4) define the embedded
benchmarking discipline; `ebacs` (SUPERCOP) is the desktop/server counterpart — note there is no
SUPERCOP paper, the site itself is the citable artefact.

**Same-machine comparison across all three families.** `commey2025consumerelectronics` is the single
most useful positioning table (preprint; Apple M4, 1 kB message):

| Scheme | Sign | Verify | Public key | Signature |
|---|---|---|---|---|
| ML-DSA-44 | 0.16 ms | 0.04 ms | 1,312 B | 2,420 B |
| ML-DSA-65 | 0.26 ms | 0.06 ms | 1,952 B | 3,309 B |
| ML-DSA-87 | 0.31 ms | 0.10 ms | 2,592 B | 4,627 B |
| SPHINCS+-SHA2-128s | 310.81 ms | 0.32 ms | 32 B | 7,856 B |
| SPHINCS+-SHA2-128f | 15.05 ms | 0.91 ms | 32 B | 17,088 B |
| SPHINCS+-SHA2-256s | 489.49 ms | 0.68 ms | 64 B | 29,792 B |
| Falcon-512 | 0.11 ms | 0.02 ms | 897 B | 655 B |

The ~1,900× gap between ML-DSA-44 signing and SLH-DSA-128s signing is the headline anchor.

**Protocol-level performance, and why microbenchmarks mislead.** `paquin2020benchmarkingtls` shows
packet loss above 3–5% disproportionately penalises algorithms whose messages fragment across
packets. `sosnowski2023pqtls` (CoNEXT Companion '23) is the best-instrumented study: even the
*fastest* SPHINCS+ variant raised handshake latency and data usage by **up to 20×**, and every
SPHINCS+ configuration required multiple round trips because server messages exceeded the initial
TCP congestion window. `sikeridis2020tls13` covers PQ authentication in TLS 1.3.
`schwabe2020kemtls` is the "you can avoid handshake signatures entirely" counterpoint.

**Embedded.** `buerstinghaus2020embedded` establishes the **signer/verifier asymmetry**: SPHINCS+
signature size and signing cost limit an embedded device acting as a *server*, while the *client*
(verifier) role stays feasible.

### Where Q-Vault sits

Q-Vault's own spike (ADR-0001, measured 2026-08-02 on the development machine) reports ML-DSA-65
sign ≈ 2.3 ms / 3,309 B signature; SLH-DSA-SHAKE-256f sign ≈ 55 ms / 49,856 B signature; ML-KEM-768
encapsulate ≈ 1.7 ms.

Positioning advice for the paper:

- **The signature sizes are exactly right** and match FIPS 205 / published tables — good, that is a
  correctness check on the harness.
- **The timings are slower than `commey2025consumerelectronics`** (2.3 ms vs 0.26 ms for ML-DSA-65).
  This is expected — different CPU, Python/CFFI call overhead versus native, single-run versus
  batched — but the paper must *acknowledge and explain* it rather than present the numbers as
  comparable. Report the harness (warm-up, iterations, wall-clock vs CPU time) per `kannwischer2019pqm4`
  discipline, and state explicitly that these are application-level Python-binding timings, not
  primitive cycle counts.
- **The interesting number is not raw speed, it is the ratio.** SLH-DSA signing at ~24× ML-DSA and a
  signature ~15× larger is the crypto-agility cost the paper is uniquely placed to report, because
  Q-Vault actually runs a mixed corpus. `sosnowski2023pqtls` and `buerstinghaus2020embedded` give
  published evidence that this asymmetry is real and consequential.
- **Verifier-side cost matters for the offline verifier.** SLH-DSA verification is cheap
  (0.32–0.91 ms in the table above) even though signing is not — which is a genuinely favourable fact
  for a design where a signature is produced once and verified by many parties offline. That is worth
  making explicitly, citing `buerstinghaus2020embedded`'s signer/verifier asymmetry.
- **Do not claim a benchmark contribution.** Q-Vault measures an application, not a primitive. Frame
  it as "system-level cost of crypto-agility in a real application", positioned against the published
  primitive numbers, not competing with them.

---

## 8. PQC implementations and libraries

### What the prior work says

- `stebila2016oqs` (SAC 2016) introduces **liboqs** and Open Quantum Safe.
- `kannwischer2022pqclean` (SSR 2022) is the **PQClean** paper — a continuous-integration testing
  framework holding vetted implementations of **NIST round-3 candidate schemes**. Note that scope:
  round 3, not the final standards. That scoping is the root of §9.
- `pqclean-repo` — PQClean was **archived read-only on 4 August 2026**. Its README classifies
  SPHINCS+ as a "to-be standard" scheme, carries no FIPS 203/204/205 or SLH-DSA reference and no
  pre-standard warning, and now redirects users to the PQ Code Package `slhdsa-c` repository.
- `oqs-slhdsa-algpage` — liboqs' SLH-DSA now comes from `pq-code-package/slhdsa-c` with specification
  version "SLH-DSA" referencing FIPS 205 — a *different upstream* from its earlier PQClean-derived
  SPHINCS+.
- `quantcrypt` — the Python library Q-Vault uses, a wrapper over precompiled PQClean binaries.
  Archived read-only 4 September 2026, following PQClean.
- `noble-postquantum` — `@noble/post-quantum` v0.7.0, the independent JavaScript library used by the
  browser verifier. Its README describes SLH-DSA as "hash-based Winternitz signatures from FIPS-205".

### Where Q-Vault sits

Q-Vault's `SignatureProvider`/`KEMProvider` interface over a swappable backend is ordinary
engineering. What is genuinely worth reporting is the **cross-implementation consequence**: because
the offline verifier is implemented twice, in Python over PQClean-derived binaries and in browser
JavaScript over an independent FIPS 205 implementation, the two implementations cross-check each
other — and that cross-check is what surfaced the finding in §9. That is a methodological point worth
making: *dual independent implementation is not just redundancy, it is a conformance oracle.*

---

## 9. SPECIAL INVESTIGATION — is the SPHINCS+ / FIPS 205 conflation already documented?

**Question asked:** the project found that `quantcrypt`'s `FAST_SPHINCS` is PQClean's
`sphincs-shake-256f-simple`, which is the **SPHINCS+ round-3 submission, not FIPS 205 SLH-DSA**;
signatures from one do not verify under the other despite identical key and signature sizes. Is this
already known, and where?

### Short answer

**Yes — this is a known and documented issue, not an undocumented discovery.** It is documented in
four independent places: NIST's own standard, two library issue trackers, and a vendor advisory.
**However**, the specific chain — *quantcrypt's `FAST_SPHINCS` → PQClean `sphincs-shake-256f-simple`
→ round-3 SPHINCS+, presented to users under NIST-standard framing* — is **not** documented
anywhere I could find. That gap is the publishable part, and it is a much narrower claim than
"we discovered SPHINCS+ ≠ SLH-DSA".

### The evidence, from most to least authoritative

**1. FIPS 205 itself says the implementations are incompatible.** [`nist-fips205`]

Appendix A ("Differences From the SPHINCS+ Submission") states the standard is based on v3.1 and
lists modifications relative to v3 (the round-3 submission): two new address types `WOTS_PRF` and
`FORS_PRF`; `PK.seed` added as an input to `PRF`; SHA-512 replacing SHA-256 for category 3 and 5
SHA2 parameter sets; and `R` and `PK.seed` added to `MGF1`. It then says, of the FORS index
extraction method — **verbatim**:

> "The method described in this standard is not compatible with the method used in the reference
> implementation that was submitted along with the round three specification."

It also restricts approval to 12 of the 36 parameter sets, and §A.1 records that after the initial
public draft the signing and verification functions were **modified to add domain separation**.

**2. The message prefix is the cleanest single explanation.** FIPS 205 §10.2.1 (pure SLH-DSA
signature generation) prepends to the message a one-byte domain separator (value 0 for pure signing),
one byte of context-string length, and the context string, before calling `slh_sign_internal`:

> `M' ← toByte(0,1) ‖ toByte(|ctx|,1) ‖ ctx ‖ M`

With the default empty context this is `0x00 0x00 ‖ M`. Round-3 SPHINCS+ signs `M` directly. The
domain separator exists, in the standard's own words, "to prevent pre-hash signatures from verifying
as pure signatures and vice versa". **Sizes are unchanged, so the two are silently
non-interoperable — which is exactly the failure mode the project observed.**

This is directly visible in the two libraries Q-Vault uses. `@noble/post-quantum` exposes the
prefixing top-level `sign`/`verify` *and* the unprefixed `slh_sign_internal` separately as
`.internal` — i.e. it models the distinction explicitly. PQClean has no such split, because it
predates the distinction.

**3. PQClean never made the change, and the record proves it.**
- `pqclean-issue526` (opened 19 November 2023) asks PQClean to adopt the FIPS 205 ipd changes and
  enumerates exactly the four modifications listed in FIPS 205 Appendix A. That it was *asked for*
  establishes PQClean was still at the round-3 v3.0 specification at that date.
- `pqclean-issue562` — *"Update SPHINCS+/SLH-DSA to be compliant with FIPS205"* — was opened on
  **14 August 2024, the day after FIPS 205 was published**, and was **still open** when the repository
  was **archived read-only on 4 August 2026**. PQClean's SPHINCS+ was therefore never brought into
  line with FIPS 205.
- `pqclean-repo` — the README calls SPHINCS+ a "to-be standard" scheme, mentions neither FIPS 205 nor
  SLH-DSA, and carries **no warning that the implementation is pre-standard**. It now redirects users
  to `pq-code-package/slhdsa-c`.

**4. liboqs states the discrepancy in as many words.** `liboqs-issue1894` ("SLH-DSA: integrate final
standard", opened 15 August 2024, closed in milestone 0.15.0) records that liboqs at the time
supported **only Round 3 SPHINCS+, sourced from PQClean upstream**, and that this differs from the
finalized standard. liboqs subsequently switched its SLH-DSA upstream to `pq-code-package/slhdsa-c`
[`oqs-slhdsa-algpage`] — a different codebase, not a patch to the PQClean one.

**5. A vendor has shipped an advisory about it.** `redhat-pqc-interop` (updated 11 November 2025)
states that the oqsprovider package in RHEL 10.0 *"provides an early draft version of SLH-DSA ...,
the SPHINCS+ algorithm, which will not be supported in the future"*, whereas RHEL 10.1 supports only
the NIST-standardized SLH-DSA variants. This is an operating-system vendor telling customers that
pre-standard SPHINCS+ shipped under the SLH-DSA name.

**6. The naming confusion is visible in the standards record itself.** The IETF COSE draft
[`cose-slhdsa`] is *titled* "SLH-DSA for JOSE and COSE" while its filename is still
`draft-ietf-cose-sphincs-plus-10`; it pins the registered algorithms to `slh_sign` in FIPS 205
§10.2.1 and forbids use with `hash_slh_sign`. NIST CAVP's external-interface test vectors
[`celi2025acvp`] target precisely the prefixed external interface. `saarinen2023slhdsa` is an
independent from-the-spec implementation of FIPS 205 ipd matching the reference KATs for all 12
parameter sets.

### What is NOT documented — the actual contribution

Searching the academic literature, the PQClean and liboqs trackers, NIST documentation and the
`quantcrypt` repository, I could not find:

1. **Any documentation of `quantcrypt`'s mapping and its standards status.** The repository maps
   `FAST_SPHINCS → sphincs-shake-256f-simple` in `internal/constants.py` and states in its README
   that the library *"contains multiple variants of PQC algorithms that are standardized by NIST"*,
   while making no FIPS 205 or SLH-DSA compliance claim and carrying **no warning** that its SPHINCS+
   is the pre-standard round-3 construction. A downstream user reading "standardized by NIST" and a
   `SPHINCS` class name has no signal that this is not SLH-DSA. Q-Vault's own ADR-0001 records exactly
   that error: it labelled `FAST_SPHINCS` as "SLH-DSA (SHAKE-256f)" with `alg_id`
   `SLH-DSA-SHAKE-256f`. **That is a reproducible, documentable instance of the mislabelling
   propagating into an application's artefact metadata — which for a crypto-agile system that pins
   `alg_id` in every stored artefact is a correctness bug in the pin itself.**
2. **Any academic paper on pre-standard/standard conflation in PQC tooling.** The closest verified
   work is `redhat-pqc-interop` (vendor advisory) and general PQC-library-gap surveys. There appears
   to be no peer-reviewed treatment of *identifier mislabelling as a crypto-agility failure mode*.
3. **Any published demonstration of the failure being caught by cross-implementation verification.**
   Q-Vault has one: a Python verifier over PQClean-derived binaries and a browser verifier over an
   independent FIPS 205 implementation, disagreeing on the same signature.

### Recommended framing for the paper — and what NOT to claim

**Do not write:** "we discovered that SPHINCS+ round 3 and FIPS 205 SLH-DSA are incompatible."
FIPS 205 Appendix A says so, in the standard, in 2024. Claiming that as a discovery would be a
serious credibility error and is exactly the kind of thing an examiner will check.

**Do write** something like: *"The incompatibility between the round-3 SPHINCS+ submission and FIPS
205 SLH-DSA is documented in FIPS 205 Appendix A and acknowledged in the liboqs and PQClean issue
trackers. What is not documented is that this pre-standard construction remains reachable through
widely-installed tooling under NIST-standard framing: quantcrypt's `FAST_SPHINCS` resolves to
PQClean's `sphincs-shake-256f-simple`, PQClean's FIPS 205 update request (#562) remained open until
the project was archived, and neither library warns the user. We report this as a crypto-agility
failure mode: an identifier that names a standard but binds to a pre-standard construction defeats
the artefact-pinning discipline that agility depends on, and we show it is detectable by
cross-implementation verification."*

**Verification to do before submitting** (see [TO VERIFY](#to-verify) item 1): run the
disagreement as an explicit, reproducible test — sign with `quantcrypt.FAST_SPHINCS`, verify with
`@noble/post-quantum`'s `slh_dsa_shake_256f.verify` (expect failure) and with its
`.internal.verify` (expect the round-3 construction to be closer, though the FORS index-extraction
and PRF changes mean it may still differ). The result of that test determines exactly how strong a
claim the paper can make, and it should be reported as measured behaviour with the parameter set,
library versions and commit hashes stated.

---

## 10. Honest novelty assessment

| Area | Q-Vault's position | Novel? |
|---|---|---|
| ML-KEM / ML-DSA / SLH-DSA use | Faithful implementation of published standards | **No** |
| Algorithm registry + `alg_id` pinning | Direct instance of RFC 7696's identification requirement | **No** |
| Runtime algorithm switch, new keys only | Sound engineering; standard migration practice | **No** |
| Cross-*paradigm* agility demonstrated on a live mixed corpus | Rarely shown end to end in the literature | **Modest** |
| Application-level M-of-N | Bellare–Neven's "trivial" multi-signature | **No** — but well justified |
| The *justification* for avoiding PQ thresholds | Backed by CSUR survey, PKC 2025, NIST IR 8214C | **No, but strong** |
| Retire-but-retain rotation | NIST SP 800-57 §7.4 deactivated state | **No** |
| Hash-chained ledger + signed anchors | Schneier–Kelsey lineage | **No** |
| RFC 6962 Merkle log over the chain | Crosby–Wallach's argument, correctly applied | **No** |
| Independent witness refusing shrink/fork | C2SP `tlog-witness`, Sigsum, CoSi | **No** |
| Witnessed PQ transparency log for *organisational approvals* | Domain transfer from certificate/supply-chain transparency | **Modest** |
| Post-quantum-signed checkpoints and cosignatures | CT/Sigsum/sumdb all use Ed25519; MTC is early work | **Modest** |
| Dual independent offline verifier as a conformance oracle | Uncommon as a stated method | **Modest** |
| quantcrypt/PQClean pre-standard SPHINCS+ reachable under NIST framing | Not found documented anywhere | **Yes, narrowly** |

The paper's strongest honest claim is **integration and demonstrability**, plus the narrow §9
finding — not primitive or protocol novelty.

---

## TO VERIFY

Do not cite any of these until checked. None are in `references.bib`.

1. **The Q-Vault cross-implementation disagreement itself.** Must be run as a reproducible test with
   library versions and commit hashes recorded before any claim is made in the paper. This is the
   highest-priority item in this file.
2. **Dahlberg, Pulls, Vestin, Høiland-Jørgensen, Kassler — "Aggregation-Based Certificate
   Transparency Gossip."** arXiv:1806.08817 is verified, but the SECURWARE 2019 venue and page
   numbers come only from third-party hosts, and a title variant ("Aggregation-Based Gossip for
   Certificate Transparency") is in circulation. Cite the arXiv version, or confirm on the
   IARIA/ThinkMind proceedings page.
3. **Dahlberg & Pulls — "Verifiable Light-Weight Monitoring for Certificate Transparency Logs."**
   NordSec 2018, LNCS 11252, DOI `10.1007/978-3-030-03638-6_11`. arXiv:1711.03952 confirms title and
   authors but carries no journal-ref; the Springer DOI is unverified.
4. **Trillian "Verifiable Data Structures" — the 2015 Eijdenberg/Laurie/Cutter attribution.** The live
   document is corporately attributed to the Google TrustFabric team. Either find the archived 2015
   PDF or cite corporately (as `references.bib` currently does).
5. **C2SP specification editors and version strings.** `tlog-witness` and `tlog-checkpoint` display no
   authors, editors or version string. Check the C2SP GitHub repository if a named editor is needed.
6. **Sigsum design document provenance.** Self-identifies as "v0", work in progress, no author or
   date. Cite with a git commit hash if precision is needed.
7. **CHAINIAC page numbers** (USENIX Security 2017, pp. 1271–1287) — OpenAlex only; usenix.org blocks
   automated fetches.
8. **CONIKS page numbers** (USENIX Security '15, pp. 383–398) — same problem.
9. **Kumar et al. author ordering** (Beck vs Mason) — Crossref and secondary sources disagree.
10. **Sikeridis, Kampanakis, Devetsikiotis — "Assessing the overhead of post-quantum cryptography in
    TLS 1.3 and SSH."** CoNEXT '20, DOI `10.1145/3386367.3431305`. Metadata confirmed via Wikidata and
    via the bibliography of the fetched Sosnowski PDF, but the widely quoted "1–300% for TLS,
    0.5–50% for SSH" figure came from a search snippet and must be checked against the PDF.
11. **Jayalaxmi H et al. — "Benchmarking SLH-DSA: A Comparative Hardware Analysis…"**, IACR ePrint
    2025/2273. Verified as a preprint; single-parameter-set FPGA study, weaker than the other
    benchmark sources. Use only if a hardware comparison is needed.
12. **Westerbaan — "Sizing Up Post-Quantum Signatures"** (Cloudflare blog, 8 November 2021). Verified,
    but it is a vendor engineering blog post. Good for framing the signature-size problem; pair with
    `sosnowski2023pqtls` for any measured claim.
13. **"Nowhere to Hide: Using Transparency Logs to Secure Your Supply Chain"**, SCORED '24, DOI
    `10.1145/3689944.3696349`. Surfaced in search, never fetched.
14. **Falcon** (`fn-dsa`) — not researched, as Q-Vault does not use it. If the paper compares
    signature sizes it will need a Falcon citation; `commey2025consumerelectronics` has numbers but
    the Falcon design paper is not yet verified here.

---

## Gaps worth closing before the paper is written

- **A citation for the "frozen authorised-signer snapshot" pattern.** No prior-art search was done for
  policy-snapshot / time-of-check-time-of-use in approval workflows. Likely exists in the access
  control literature.
- **Downgrade resistance.** ADR-0012 exists; RFC 7696's warning about protecting algorithm
  negotiation is the obvious hook, but no dedicated search for PQC downgrade attacks was done.
- **Falcon / FN-DSA**, if the paper's comparison table includes it.
- **Device-held signing keys** (ADR-0016/0017) — no prior-art search performed.
