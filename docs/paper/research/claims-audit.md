# Q-Vault — Claims Audit for a Research Paper

**Purpose.** Establish what a paper about this codebase can *honestly* claim, with the evidence
that backs each claim and the specific place a reviewer would push back. This is an evidence
document, not an advertisement: an inflated claim here becomes a failed defence later.

**Method.** Read of all ADRs (19 at the start, 20 by the end), `README.md`, `docs/PROJECT-SPECIFICATION-AND-PLAN.md`,
`docs/benchmarks/`, and the implementation in `qvault/{crypto,services,transparency,verify}`,
`witness/`, `scripts/`, plus the test suite (794 collected cases across 42 files at the close of the audit). Verdicts are
assigned from what the tests actually assert, not from what the docstrings say.

**Audit date.** 2026-09-08 → 09. Working tree at commit `90591dc` **plus substantial uncommitted
work** (see §3.8).

> ⚠️ **This is a snapshot of a moving repository.** The tree changed materially *during* the audit:
> ADR-0020 and 40 glass-box tests were added between the first and last measurement, taking the
> collected suite from 752 to 794 cases. Two findings in an earlier draft of this report were
> obsolete before it was finished. **Re-run `pytest --collect-only -q` and re-check §0.1 before
> quoting any number or defect from this document.**

---

## 0. Headline verdict on framing

> **The evidence supports an engineering / experience-report framing, not a novelty framing.**

There is no new cryptographic construction, no new protocol, no security proof, and no measurement
that the PQClean/liboqs benchmarking literature does not already provide more rigorously. What
there *is*, and what is genuinely worth publishing:

1. **One new empirical fact** — a reproducible, size-invisible interoperability defect in a
   shipping PyPI PQC library's algorithm labelling (§2.1.1). This is the paper's only genuinely
   novel contribution and it generalises into a real lesson about standards transitions.
2. **A methodology** for establishing that a decision-record format is independently verifiable —
   two implementations across a language boundary, required to agree on forgeries as well as on
   genuine artefacts (§2.1.2).
3. **A clean, testable demonstration of the limits of self-verification** — a system that
   documented truncation as an accepted non-goal, then retired that non-goal with an external
   witness, and has a single test showing `verify_ledger()` returns `ok=True` on a truncated log
   while the witness refuses (§2.1.3).
4. **An honestly-scoped integration study** of crypto-agility that actually executes end-to-end,
   which most papers asserting agility do not do (§2.2).

**Recommended title shape:** *"Crypto-agility in practice: building and evaluating a post-quantum
multi-signature vault"* — an integration and experience study, with an interoperability finding
and a verification methodology. A paper claiming a novel scheme or protocol would be dismantled in
review within a page.

**Realistic venue:** a PQC-migration / deployment-experience workshop, a student research track, or
an engineering track. Not a top-tier security venue.

### 0.1 Must-fix before anything is written up

Seven items, all cheap, each of which would otherwise be found by a reviewer or examiner:

| # | Problem | Where | Fix |
|---|---|---|---|
| 1 | README, the specification and both benchmark artefacts still claim **FIPS 205** for an algorithm the code itself now labels "SPHINCS+ round 3 … not interoperable with it" | §3.1 | Regenerate the benchmark; edit five documents |
| 2 | `pyproject.toml` still says **"immutable audit ledger"** — the exact word ADR-0003/0005 retired | §3.1 | One-line edit |
| 3 | The specification's threat model claims **rate limiting** that is implemented nowhere | §3.10 | Implement it, or correct the claim |
| 4 | ~~Glass box untested, cites a non-existent ADR~~ — **fixed during this audit** (ADR-0020 + 40 tests added). Residual: `source.py:10` names `tests/test_glassbox_source.py`, the file is `tests/test_glassbox.py` | §3.8 | One-word docstring edit |
| 5 | **36 browser differential tests skip silently in CI** — the evidence for the project's most distinctive claim is unprotected | V4, §5 G1 | Add `playwright` to dev requirements + a CI install step |
| 6 | The **key fingerprints are published inside the repository the log ships from**, which is circular by the project's own reasoning | §3.5, G13 | Commit them out of band before evaluation |
| 7 | Test-count claim of "668" versus 794 collected / 563 functions, with no note about parametrisation | §3.9 | State both numbers, freshly counted |

---

## 1. Claim inventory

Verdicts:
**SOLID** = implemented and pinned by a test that would fail if the property broke ·
**PARTIAL** = implemented, but weakly tested, tested only indirectly, or not tested in CI ·
**ASPIRATIONAL** = documented intent, structure only, or not yet demonstrated.

### 1.1 Crypto-agility (the headline claim)

| # | Claim as it would appear in a paper | Evidence | Verdict |
|---|---|---|---|
| A1 | *Every cryptographic artefact self-describes the algorithm it was made with, and verification always resolves the provider from the artefact, never from a global default.* | `qvault/crypto/interfaces.py` (`AlgMeta`, `KeyPair.alg_id`); `qvault/crypto/registry.py::CryptoRegistry.signature/kem/symmetric`; `approval_service.verify_signature` resolves `sig.alg_id`; `ledger_service.verify_anchor` resolves `anchor.alg_id`; `checkpoint_service.create_checkpoint` pins `key.alg_id`. Tests: `test_crypto_agility.py::test_signature_survives_default_algorithm_switch`, `::test_cross_algorithm_signature_does_not_verify`. | **SOLID** |
| A2 | *The active signature algorithm can be switched at runtime, and a heterogeneous corpus of artefacts produced under different algorithms all continues to verify afterwards.* | `config_service.set_active_signature_algorithm`; `config_service.verify_all_artefacts`. **The test that proves it:** `tests/test_algorithm_switch.py::test_mixed_algorithm_corpus_all_verifies` — signs under ML-DSA-65, switches the default to SLH-DSA, re-keys, signs again, then asserts `verify_all_artefacts()["all_pass"] is True` **and** that both `alg_id`s appear in `report["by_alg"]`. | **SOLID** |
| A3 | *Key rotation retires but retains: a rotated key's past signatures still verify and its encrypted files still decrypt.* | `key_service.reissue_signing_key`; `rotation_service.run_key_rotation`. Tests: `test_algorithm_switch.py::test_reissue_retires_old_key_but_keeps_past_signatures_verifiable` (asserts `status=='retired'`, `can_sign is False`, `can_verify is True`, old signature still verifies); `test_rotation.py::test_rotate_vault_key_keeps_old_files_decryptable`; `::test_rotate_system_key_retains_old_anchor_verification`. | **SOLID** |
| A4 | *Algorithm switching and key rotation compose: an artefact survives both.* | `test_algorithm_switch.py::test_mixed_algorithm_corpus_all_verifies` (switch + re-key); `test_checkpoint_service.py::test_a_checkpoint_signed_before_an_algorithm_switch_still_verifies_after_it`. | **SOLID** |
| A5 | *A downgrade to a lower NIST security category is refused unless explicitly confirmed with a reason, and is recorded as a distinct ledger event type so an auditor can find every weakening decision without knowing which `alg_id` outranks which.* | `config_service.set_active_signature_algorithm` reads `security_category` from `AlgMeta` (never a hardcoded ranking) and raises `DowngradeRefused`. `tests/test_downgrade.py` (11) — incl. `test_downgrade_is_refused_without_explicit_confirmation`, `::_without_a_reason`, `test_a_confirmed_downgrade_is_allowed_and_recorded_distinctly`, `test_downgrade_confirmation_does_not_leak_into_the_next_switch`, `test_a_sideways_move_at_equal_category_is_not_a_downgrade`, and `test_the_fixture_algorithms_really_differ_in_category` (a guard against a vacuous fixture). | **SOLID** |
| A6 | *A downgrade cannot retroactively weaken history.* | `test_downgrade.py::test_a_downgrade_cannot_weaken_existing_artefacts` — signs under category 5, downgrades to category 3, asserts the signature still carries `alg_id == CAT5` and `verify_all_artefacts()["all_pass"] is True`. | **SOLID** |
| A7 | *The abstraction does not leak: a PQC backend may be imported only inside `qvault/crypto/providers/`, enforced mechanically rather than by convention.* | `tests/test_module_boundaries.py::test_no_backend_imports_outside_providers` greps every `qvault/**/*.py` for `import quantcrypt\|oqs\|pqcrypto` outside the allowed directory. | **SOLID** |
| A8 | *Agility extends across cryptographic backends (implementations), not merely across algorithms.* | **Not implemented.** `qvault/crypto/bootstrap.py::_register_pqc` carries only a comment — `# Future: if prefer == "liboqs", try importing the oqs providers here` — and always returns `"quantcrypt"`. ADR-0001 states quantcrypt (PQClean round-3) and liboqs (FIPS-final) byte formats "are **not** interchangeable" and that switching backends is "a fresh-database operation, not a live migration". | **ASPIRATIONAL** |
| A9 | *Agility covers KEM and symmetric primitives as well as signatures.* | Structurally yes (`KEMProvider`, `SymmetricProvider` exist; artefacts pin `alg_id`); operationally no. Only `ML-KEM-768` is registered, so ADR-0006 states a KEM switch "is a no-op until a second KEM provider is registered". `interfaces.py::SymmetricProvider`: "not swappable in the MVP". | **ASPIRATIONAL** (structure only) |

> **Scoping sentence the paper must include.** *Agility is demonstrated for the signature primitive
> across three algorithms (ML-DSA-65, ML-DSA-87, SLH-DSA-SHAKE-256f) served by a single backend.
> Backend agility and KEM agility are structural properties of the interface, not demonstrated
> capabilities.* Omitting this is the single most likely cause of a hostile review.

### 1.2 What the threat model actually covers

The stated model is a STRIDE-lite table at `docs/PROJECT-SPECIFICATION-AND-PLAN.md` §4.11 (line 563).
The operative adversary throughout the ADRs is **an attacker with raw write access to the
application database**, explicitly *without* the server master key.

| # | Claim | Evidence | Verdict |
|---|---|---|---|
| T1 | *An isolated edit to a past ledger entry is detected by chain recomputation.* | `ledger_service.verify_chain` recomputes `entry_hash` from fields, checks `prev_hash` linkage, and re-hashes `payload_json` against `payload_hash`. Test: `test_anchor.py::test_edit_tamper_breaks_the_chain`. | **SOLID** |
| T2 | *A fully consistent forward-rewrite — every hash recomputed so the chain still verifies — is detected because the head moves and the SYSTEM anchor no longer covers it, and a replacement anchor cannot be forged without the master key.* | `ledger_service.anchor_head`, `maybe_anchor`, `verify_anchor`, `verify_ledger`. Tests: `test_anchor.py::test_rewrite_tamper_is_caught_by_the_anchor`, `::test_reanchor_refused_over_a_rewritten_history`, `::test_verify_anchor_rejects_a_forged_signature`. | **SOLID** |
| T3 | *A DB-write adversary cannot substitute their own anchor keypair, because the SYSTEM public key is bound to the master key by an HMAC that `verify_anchor` checks before trusting it.* | `Key.public_key_mac` set in `ledger_service.ensure_system_key` via `master_key.mac`; checked in `verify_anchor` via `master_key.verify_mac`. Test: `test_anchor.py::test_injected_substitute_anchor_key_is_rejected`. | **SOLID** |
| T4 | *An adversary who edits an approved proposal's text — leaving every signature byte-for-byte intact and valid — cannot make it count, because the tally re-derives the canonical bytes and cross-checks the hash the ledger independently recorded.* | `approval_service.verify_proposal_binding` (two independent checks: content recomputation via `signing.signing_bytes_for`; comparison against the `proposal_created` ledger entry). `tally()` returns `(0,0)` on binding failure. Tests: `tests/test_proposal_binding.py` (17) — notably `test_editing_action_text_breaks_the_binding`, `test_the_individual_signatures_still_verify_after_an_edit` (the point: the crypto is fine, the *correspondence* is not), `test_rewriting_the_hash_to_match_is_caught_by_the_ledger`, `test_every_signed_field_is_covered_by_the_binding` (parametrised over columns), `test_binding_failure_cannot_manufacture_an_approval`. | **SOLID** |
| T5 | *Changing vault membership cannot alter an approval in flight, because the authorised signer set and threshold are frozen into the signed payload at creation.* | `signing.proposal_signing_bytes` includes `policy.{M,N,signers}`; `approval_service._authorize_vote` authorises against `authorized_signers_snapshot`, not live membership. Tests: `tests/test_membership.py` (18); repeated independently by the offline verifier (`verify/core.py` step 3) and `test_decision_bundle.py::test_a_signature_from_someone_outside_the_frozen_signer_set_is_caught`. | **SOLID** |
| T6 | *An approval signature cannot be replayed as a rejection, nor attributed to another signer, because the vote binds decision and signer under a distinct domain tag.* | `signing.vote_signing_bytes` with `DS_VOTE`, disjoint from `DS_PROPOSAL` and `DS_DEVICE_ENROL`. Tests: `test_decision_bundle.py::test_flipping_a_rejection_into_an_approval_is_caught`, `::test_relabelling_a_signer_with_someone_elses_email_is_caught`. | **SOLID** |
| T7 | *No signature is ever emitted without being verified under its own public key first, so an induced or accidental fault cannot produce a persisted artefact.* | `key_service.sign_with_key` raises `SignFaultError`; `ledger_service.anchor_head` raises `LedgerError`; `approval_service._record_vote` re-verifies as documented defence in depth. Tests: `tests/test_fault_injection.py` (8) installs a bit-flipping provider and asserts a faulted vote leaves **no** `Signature` row and **no** `proposal_signed` entry, that a faulted anchor never reaches the database, and — crucially — `test_the_fault_harness_actually_corrupts_signatures`, which exists so a silently-disabled injector cannot make the suite pass forever. | **SOLID** |
| T8 | *For a vote whose custody reads `device`, this server never possessed the private key, so a full compromise of this server cannot forge it.* | `Key.wrap_domain='device'` with both ciphertext columns NULL; `approval_service.record_device_vote` *admits* a signature rather than producing one; `_require_device_signing_key` asserts ownership, role, custody domain, active status and provider availability. Enrolment requires proof of possession against a master-key-MAC'd five-minute challenge. Tests: `tests/test_device_keys.py` (17), `test_device_signing.py` (18), `test_device_api.py` (19). | **SOLID** for the stated scope |
| T9 | *Third-party non-repudiation.* | **Explicitly NOT claimed** for server-custodied keys — ADR-0004 and spec §4.11 both state Q-Vault provides "integrity + attributable intra-server audit, **not** third-party non-repudiation". ADR-0016 narrows the stronger claim to device custody only, and further excludes a compromised device, a key exported from a rooted phone, and the legal sense of non-repudiation (no identity-binding ceremony is performed). | **Correctly disclaimed** |
| T10 | *An attacker holding the server master key is detected.* | **Out of scope by design and stated as such** (ADR-0005, ADR-0012): such an attacker can forge anchors, and can edit `algorithm_config.active_signature_alg` to bypass downgrade protection entirely. ADR-0012 notes the resulting discrepancy is *detectable* (weaker `alg_id`s with no `algorithm_downgraded` entry) but that **nothing currently alerts on it**. | **Honest non-goal** |

### 1.3 What the witness genuinely detects that self-verification cannot

The most defensible security argument in the project, because the *negative* half is asserted by
the same test as the positive half.

| # | Claim | Evidence | Verdict |
|---|---|---|---|
| T11 | *An operator who deletes tail entries, their anchors and their checkpoints, then re-anchors and re-checkpoints the shortened log, produces a state that the system's own verification reports as healthy (`verify_ledger() → ok=True`) and that only the external witness refuses.* | **The single best test in the repository:** `tests/test_witness_integration.py::test_a_truncated_ledger_is_caught_by_the_witness_and_by_nothing_else` — performs the full attack and asserts *both halves*, exactly as ADR-0005 predicted it would behave. Reinforced by `::test_truncating_then_growing_past_the_old_size_is_still_caught` and `::test_a_rewritten_ledger_cannot_be_re_witnessed`. | **SOLID** |
| T12 | *The witness refuses to co-sign unless the log proves the new tree contains the last tree the witness saw, and every refusal is recorded with the offered checkpoint kept verbatim, so a refusal is evidence rather than merely a rejection.* | `witness/app.py::cosign` (identity pin → log-signature verification → monotonicity/consistency); `witness/store.py` `violations` table. Refusal kinds: `shrank`, `fork`, `inconsistent`, `key_changed`, `bad_signature`. Tests: `tests/test_witness.py` (27) — `test_a_truncated_log_is_refused_and_recorded`, `test_truncation_cannot_be_laundered_by_growing_again`, `test_two_different_roots_at_the_same_size_is_a_fork`, `test_a_consistent_forward_rewrite_is_refused`, `test_a_missing_or_bogus_consistency_proof_is_refused`, `test_a_different_log_key_for_a_known_origin_is_refused`, `test_an_unsigned_checkpoint_is_refused`, plus a parametrised `test_a_malformed_statement_is_never_co_signed`. | **SOLID** |
| T13 | *Locally, the log itself refuses to sign a tree that is not a provable extension of the last one it signed, so a rewrite produces a stall rather than a fresh signature blessing the operator's preferred history.* | `checkpoint_service.maybe_checkpoint` — three documented refusals (tree did not grow; previous checkpoint is not a prefix; a `seq` gap raises rather than being renumbered around). Tests: `test_checkpoint_service.py::test_a_consistent_forward_rewrite_stalls_the_checkpoint_sequence`, `::test_the_stall_is_visible_as_a_gap_between_the_log_and_its_checkpoint`, `::test_a_deleted_entry_is_refused_rather_than_renumbered`, `::test_a_second_root_at_the_same_size_is_refused_loudly`. | **SOLID** |
| T14 | *The witness holds no Q-Vault state and no Q-Vault keys.* | `witness/store.py` uses raw `sqlite3` deliberately, with a docstring explaining that importing `qvault.extensions.db` would attach it to the same metadata and "the first person to tidy up the duplication" would merge the databases. Test: `test_witness.py::test_the_witness_stores_nothing_in_the_vault_database`. | **SOLID** |
| T15 | *The witness signs different bytes from the log, so standing one up does not hand out the ability to mint checkpoints.* | Distinct domain tags `QVAULT-WITNESS-v1` vs `QVAULT-CHECKPOINT-v1`, with the witness's own name inside the signed bytes (`transparency/statement.py::witness_bytes`). Test: `test_witness.py::test_the_witness_signature_does_not_verify_as_a_log_signature`. | **SOLID** |
| T16 | *A witness outage degrades to "not yet witnessed" and never affects the application.* | `checkpoint_service.sync_witness` returns a status dict and never propagates network errors; offered on a timer from `qvault/scheduler.py`, never in `after_request`. Tests: `test_witness_integration.py::test_an_unreachable_witness_never_breaks_the_application`, `::test_a_refusal_is_reported_as_a_refusal_not_as_an_outage`, `::test_no_configured_witness_is_reported_rather_than_hidden`. | **SOLID** |
| T17 | *The witness is genuinely independent.* | **Materially qualified — and the project says so first.** (a) It **shares code**: `qvault.transparency` (RFC 6962, statement encodings) and `qvault.crypto` (providers). ADR-0015 and `witness/README.md` defend this trade explicitly ("two hand-written implementations of RFC 6962 that disagreed would be a far worse failure"). (b) In the suite only the *transport* is stubbed — `conftest.py::witnessed` monkeypatches `checkpoint_service._get/_post` onto a test client — so there is no socket, no separate process and no separate machine; `config.py:116` states "tests drive the witness in-process; no sockets in the suite". (c) In *deployment* it is genuinely better than the ADR's laptop caveat: `docs/OWNER-ACTIONS.md` §2.4 records the witness running as a **second Azure Container App**, with its own SQLite file on Azure Files (mounted `nobrl`, "because SQLite cannot take byte-range locks over SMB"). That is separate infrastructure — but the **same operator**, which is the half that matters and which OWNER-ACTIONS §2.1 records as still `TODO`: "an examiner can fairly say that is not independence." (d) Key pinning is **trust-on-first-use**: "a witness that meets a fraudulent log before the real one pins the wrong key." (e) The witness's own signing key "lives in a JSON file … a project-scale stand-in and is not pretended to be more than that" (`witness/identity.py:31-33`). | **PARTIAL** — mechanism SOLID; independence is a deployment property, partially achieved (separate infrastructure, same operator) |
| T17a | *The witness's algorithm choice provides assumption diversity from the log's.* | The witness defaults to **ML-DSA-87** while the log signs with ML-DSA-65 — different parameter sets of the *same* lattice family, so this is **not** assumption diversity in the strong sense. `witness/identity.py:10-27` records honestly why the intended SLH-DSA default was abandoned: the SPHINCS+/FIPS 205 incompatibility (§2.1.1) would have produced "a verifier that works completely, over an assumption-diversity argument that only pays off in a world where the decisions themselves are already unverifiable." A hash-based witness remains available via `--alg` and is tested (`test_witness.py::test_a_hash_based_witness_is_still_available`). | **Claim must be softened** — the default is *key* diversity, not *assumption* diversity |
| T18 | *A log that hides an entry from everybody is detected.* | **Explicit non-goal.** ADR-0015 and `verify/core.py`'s module docstring both state split-view detection requires clients gossiping checkpoints between themselves; the witness catches a log showing *different* histories, not one hiding an entry from all readers. | **Honest non-goal** |

### 1.4 What the two verifier implementations really prove

| # | Claim | Evidence | Verdict |
|---|---|---|---|
| V1 | *The verification logic is pure — no Flask, no SQLAlchemy, no application configuration — so a third party can run it without the application.* | `qvault/verify/core.py` imports only `qvault.crypto`, `qvault.services.signing`, `qvault.transparency`. Test: `tests/test_verifier_purity.py` (5) asserts this **in a subprocess by inspecting `sys.modules`**, including `test_importing_the_application_package_alone_starts_nothing` and `test_the_verifier_still_works_without_any_application_configuration`. Achieving it required moving the entry-hash rule into `qvault.transparency` and making `qvault/__init__.py` import nothing at module level. | **SOLID** |
| V2 | *`qvault/static/verifier.html` is a second, independent implementation — different language, hand-written JSON canonicaliser, `@noble/post-quantum` instead of PQClean-via-quantcrypt, its own transcription of the RFC 6962 walk.* | 271,634 bytes, generated by `scripts/build_verifier.py` from a vendored `qvault/static/vendor/pqc.js` (229 KB) built by `scripts/bundle_pqc.py`. Staleness is a test failure: `test_offline_verifier.py::test_the_committed_verifier_matches_its_sources`. | **SOLID** (that it *is* a second implementation) |
| V3 | *The two implementations return identical verdicts on genuine decisions and on eight distinct classes of forgery.* | `tests/test_offline_verifier.py` — the `agree()` helper requires both the same `ok` verdict **and** the same *set of failed check keys*. Forgeries: edited text, corrupted signature, substituted signing key, tampered Merkle proof, forged checkpoint signature, forged witness co-signature, dropped signature, relabelled signer; plus a parametrised sweep over every signed field (`required_m`, `nonce_hex`, `created_at_iso`, `vault_id`) and a parametrised malformed-input sweep. Also `test_both_implementations_recompute_the_same_payload_hash` and `test_unicode_and_awkward_text_canonicalise_identically`. | **SOLID locally / PARTIAL in CI — see V4** |
| V4 | *This agreement is continuously verified.* | **No.** `playwright` appears in **no** requirements file (`requirements.txt`, `requirements-dev.txt`, `requirements.lock.txt`) and in **no** CI step; `.github/workflows/ci.yml` installs only `requirements.lock.txt`. The module-level `pytest.importorskip("playwright.sync_api")` therefore fires and **all 36 cases in `tests/test_offline_verifier.py` silently skip in CI**. Playwright 1.62.0 *is* installed in the developer's local `.venv`, so the claim is true on the author's machine and unprotected everywhere else. | **PARTIAL — see §5, G1** |
| V5 | *Two agreeing implementations prove the format is correct.* | **Overclaim as stated.** Both were written by one author from one reading of the specification. Differential testing of this kind catches **transcription divergence** (a mis-typed RFC 6962 walk, a canonicalisation byte difference, an off-by-one proof index) — real and valuable — but cannot catch a **shared conceptual error**, because both implementations would contain it. State this explicitly; it costs nothing and pre-empts the obvious objection. | **Must be qualified** |
| V6 | *The RFC 6962 proof generators and verifiers are independent of each other.* | `qvault/transparency/merkle.py`: generators are recursive transcriptions of the RFC's definitions; verifiers are the iterative form and "share no code with the generators". `tests/test_merkle.py` brute-forces **every** proof for **every** tree size up to `MAX_N = 33` in both directions (153 collected cases), plus negative cases: `test_a_node_preimage_cannot_be_passed_off_as_a_leaf`, `test_a_valid_proof_does_not_verify_at_a_different_index`, `test_a_log_that_shrank_is_never_consistent`, `test_a_rewritten_prefix_breaks_consistency`, and parametrised proof-mutation sweeps. `merkle.py` is at **100% line coverage**. | **SOLID** — the best-tested module in the project |
| V7 | *The export commits to signer identity and to these exact signatures, so an exporter cannot substitute keys, drop an inconvenient signature, or relabel a signer.* | `verify/core.py` step 6 (binding: the log records these exact `signature_sha256` values *and no others*) and step 6b (identity: the `user_registered` entry binds account id to email). The key-substitution argument (a substituted key would have to verify a *fixed* signature over a *fixed* message) is documented in the module docstring and pinned by `test_decision_bundle.py::test_a_signature_made_by_a_key_of_the_exporters_own_is_caught`; dropping by `::test_dropping_an_inconvenient_signature_is_caught`. | **SOLID** |
| V8 | *A bundle proves only that "some log" signed it until the reader supplies a fingerprint obtained out of band.* | `verify/core.py` step 10 (`expect_log` / `expect_witness`); `Report.fingerprints`; CLI flags `--expect-log` / `--expect-witness`. Tests: `test_decision_bundle.py::test_a_checkpoint_re_signed_with_a_fresh_key_fails_the_pin`, `test_offline_verifier.py::test_pinning_keys_agrees_with_python`, `::test_pinning_a_fingerprint_is_reachable_without_hunting_for_it`. The `/verify` page states in its own copy that it is a convenience rather than evidence, being the same server that produced the file. | **SOLID** |
| V9 | *A skipped check is neither a pass nor a fail.* | `Check.skipped`; an unwitnessed bundle yields `witness` skipped rather than failed. Tests: `test_offline_verifier.py::test_an_unwitnessed_bundle_is_weaker_not_invalid`, `test_decision_bundle.py::test_stripping_the_witness_is_visible_rather_than_silent`. | **SOLID** |
| V10 | *The browser verifier declares algorithms it cannot check rather than reporting them as forged.* | A direct consequence of the SPHINCS+/FIPS 205 finding (§2.1.1). Test: `test_offline_verifier.py::test_an_algorithm_the_browser_cannot_check_is_declared_not_assumed`. | **SOLID** |
| V11 | *The default export is a single self-contained HTML file that is simultaneously the readable record, the evidence and the verifier, and it renders its readable half from the embedded bundle at runtime so a tampered file shows its own tampering rather than displaying the original wording over broken signatures.* | ADR-0019; `export_service`; `verify/reader.py` (content-based format detection, never by filename). Tests: `test_offline_verifier.py::test_the_document_verifies_itself_on_open`, `::test_editing_the_embedded_evidence_is_caught_by_the_document_itself`, `::test_a_document_whose_evidence_is_unparseable_says_so`; `test_decision_bundle.py::test_every_artefact_the_export_produces_is_accepted_by_the_verify_page` (parametrised over all three formats), `::test_building_a_document_fails_loudly_if_the_slot_is_gone`. | **SOLID** (subject to V4) |
| V12 | *Attacker-controlled proposal text cannot inject script into the exported record.* | `<`, `>`, `&` escaped as `\uXXXX` inside the embedded `<script>` JSON; the asserted invariant is stronger than "no `</script>`" — **no raw angle brackets at all**. Test: `test_decision_bundle.py::test_a_decision_cannot_inject_script_into_its_own_record`. | **SOLID** |

### 1.5 Multi-signature, custody, operations

| # | Claim | Evidence | Verdict |
|---|---|---|---|
| M1 | *Application-level M-of-N: N independent single-signer PQC signatures, M valid and distinct required. Threshold PQC is explicitly out of scope.* | ADR-0002; `approval_service.tally` / `_finalize_if_decided`; distinctness by `uq_signature_signer` on `(proposal_id, signer_id)`. Tests: `tests/test_approval.py` (17). | **SOLID**, correctly disclaimed |
| M2 | *The tally counts only signatures that verify right now — never a cached flag.* | `approval_service.tally` re-runs `verify_signature` per row on every call. (`Signature.is_valid` exists in the spec as a "display cache only".) | **SOLID** |
| M3 | *One human gets one vote even when holding both a password key and several device keys.* | `uq_signature_signer` is on `(proposal_id, signer_id)`, not on key (ADR-0016). Tests in `tests/test_device_signing.py`. | **SOLID** |
| M4 | *Failure is refusal, never a half-written vote: verification happens before the flush that trips the uniqueness constraint.* | `approval_service._record_vote` — the ordering is documented at length as load-bearing (a post-flush failure would burn the signer's only vote slot, emit a false ledger entry, and permanently desynchronise the offline verifier's cross-check). Test: `test_fault_injection.py::test_a_faulted_vote_records_nothing_at_all`. | **SOLID** |
| M5 | *Three-tier key custody: password-wrapped user signing keys, master-wrapped server keys, device keys whose private half the server never receives.* | ADR-0004 + ADR-0016; `crypto/kdf.py` (Argon2id `time_cost=3`, `memory_cost=65536` (64 MiB), `parallelism=4`); `key_service`; `security/master_key.py`. Tests: `tests/test_key_at_rest.py` (4), `tests/test_change_password.py` (10). | **SOLID** |
| M6 | *Unattended automation can only rotate what it can unwrap; user signing keys are flagged for interactive re-key, never rotated by the scheduler.* | `rotation_service.run_key_rotation`. Test: `test_rotation.py::test_run_key_rotation_rotates_due_server_keys_and_flags_user_keys`. | **SOLID** |
| M7 | *Changing a password re-wraps active and retired password-wrapped keys in one transaction, rotates the KEK salt, and never touches master-wrapped vault keys.* | ADR-0014 records this as a bug caught during development: selecting a user's keys by ownership alone would have re-wrapped vault ML-KEM keys under a password KEK and made every encrypted file permanently unreadable. Tests: `tests/test_change_password.py` (10). | **SOLID** |
| M8 | *Files are AES-256-GCM encrypted at rest with the DEK encapsulated to the vault's ML-KEM key; rotation never strands a file because `VaultFile.kem_key_id` pins the encapsulating key.* | `file_crypto_service`; `crypto/kdf.py::hkdf_sha256` (no salt — the KEM shared secret is already uniform; documented choice). Tests: `tests/test_file_crypto.py` (8), `test_rotation.py::test_rotate_vault_key_keeps_old_files_decryptable`. | **SOLID** |
| M9 | *Device enrolment requires proof of possession before anything is persisted, using a stateless, master-key-MAC'd, five-minute challenge.* | `device_service.issue_challenge`; `signing.device_enrolment_bytes` binds `user_id`, `alg_id`, the exact base64 public key and the challenge under `DS_DEVICE_ENROL`. Tests: `tests/test_device_api.py` (19), `tests/test_device_keys.py` (17). | **SOLID** |
| M10 | *Device signing keys are restricted to an explicit algorithm allowlist that deliberately does not inherit the active default.* | `key_service.DEVICE_ELIGIBLE_SIG_ALGS = ("ML-DSA-65", "ML-DSA-87")`, with a comment explaining why a size check cannot substitute. Test: `test_device_interop.py::test_slh_dsa_does_not_interoperate_which_is_why_it_is_not_device_eligible`. | **SOLID** |
| M11 | *The device recomputes `payload_hash` itself and refuses to sign on disagreement; the server serves full canonical inputs, never just the hash.* | ADR-0016; `qvault/blueprints/api.py`. Tests: `tests/test_mobile_canonical.py` (16), `tests/test_mobile_e2e.py` (4) — both run in CI. | **SOLID** |
| M12 | *Device keys are derived from a 32-byte seed rather than stored expanded, so the expanded private key is never written to persistent storage.* | ADR-0017; `mobile/src/custody.ts` port + `keystore.ts`; `expo-secure-store` with `WHEN_UNLOCKED_THIS_DEVICE_ONLY` (excludes iCloud Keychain and encrypted backups). Motivated by a measured constraint: `expo-secure-store` caps values at ~2,048 bytes while an ML-DSA-65 secret key is 4,032 bytes. | **PARTIAL** — the Custody port is testable and CI type-checks and bundles the client, but ADR-0017 lists two open items that "need a handset": timing on real hardware, and whether the `crypto.getRandomValues` polyfill installs before `@noble/post-quantum` under Hermes |
| M13 | *ML-DSA is byte-compatible between PQClean-via-quantcrypt and `@noble/post-quantum`, in both directions.* | `tests/test_device_interop.py` runs a real Node client (`tests/interop/device_client.mjs`), parametrised over ML-DSA-65 and ML-DSA-87, in both directions, plus `test_canonical_json_is_byte_identical_across_languages` and a full end-to-end device approval. **Runs in CI** (the `mobile` job). | **SOLID** |
| M14 | *A demonstration aid may never make the system claim something untrue.* | ADR-0011; a single gate `security/demo_gate.py::demo_enabled` requiring `ENABLE_TAMPER_DEMO` **and** a debug/testing context; `rotation_service.demo_expire_keys` moves deadlines only and writes its own `demo_keys_expired` ledger entry so the audit trail records that the clock moved. Tests: `test_proposal_binding.py::test_tamper_demo_is_absent_in_a_production_like_config`, `::test_tamper_demo_requires_vault_membership`, `test_anchor.py::test_http_tamper_then_restore`. | **SOLID** |
| M15 | *The demonstration seed drives the real services, so it cannot seed a state the application could not have produced.* | `scripts/seed_demo.py` (545 lines) drives `auth_service`, `vault_service`, `proposal_service`, `approval_service`. Test: `tests/test_demo_seed.py` (12) runs it against the test database — the broadest end-to-end test in the suite. | **SOLID** |
| M16 | *The application runs and demonstrates with no network at all.* | ADR-0011; all assets vendored to `qvault/static/vendor/`. Tests: `tests/test_offline_assets.py` (38) fails on any external `href`/`src`, on a reintroduced Bootstrap class, and includes a guard that the template glob is non-empty. `test_offline_verifier.py::test_the_verifier_fetches_nothing` checks for `fetch(`, `XMLHttpRequest`, `WebSocket`, `importScripts`, subresource tags and dynamic `import()`. | **SOLID** |
| M17 | *The PQC backend genuinely works on the target platform, not merely that `pip install` succeeded.* | CI runs `python scripts/run_benchmark.py --quick` as a smoke step on both `windows-latest` and `ubuntu-24.04`; the `Dockerfile` self-checks ML-DSA sign+verify during the image build. | **SOLID** |
| M18 | *The system is tamper-evident under an external anchor — not "immutable".* | ADR-0003 insists on this terminology explicitly. The paper should reuse the phrase verbatim. | **Correct terminology, already adopted** |

---

## 2. Novelty assessment — ruthless

### 2.1 Genuinely novel or unusual

#### 2.1.1 The SPHINCS+ / FIPS 205 mislabelling finding — the one real contribution

**The finding.** `quantcrypt` 1.0.1 exposes `FAST_SPHINCS`, which Q-Vault registered as
`SLH-DSA-SHAKE-256f` with `nist_standard = "FIPS 205"`. It in fact wraps PQClean's
`sphincs-shake-256f-simple` — the **SPHINCS+ round-3 submission**, from which FIPS 205 is derived
but with which it is **not byte-compatible**.

**Why it is more than a typo.** The two produce **identical** artefact shapes: 64-byte public keys
and 49,856-byte signatures. Nothing about the data reveals the mismatch. A system that switched to
this algorithm would strand every client using a conforming FIPS 205 implementation, and the
failure would surface at the first signature verification as a bare "signature did not verify" —
*indistinguishable from a compromised key*.

**How it was established (this is the methodologically interesting part).** Empirically, not by
reading documentation: real signatures from this provider were checked against
`@noble/post-quantum`'s FIPS 205 implementation at identical key and signature sizes, and they fail
**even through noble's `internal.verify`**, which skips the FIPS 205 message prefix — localising the
incompatibility to the *construction* rather than to message preprocessing.

**Evidence in the repository.**
- `qvault/crypto/providers/quantcrypt_signature.py` — the `SLHDSAShake256fProvider`
  "INTEROPERABILITY NOTE — measured, not assumed", and `nist_standard` now reads
  `"SPHINCS+ round 3 (basis of FIPS 205; not interoperable with it)"`.
- `tests/test_device_interop.py::test_slh_dsa_does_not_interoperate_which_is_why_it_is_not_device_eligible`
  — asserts the sizes are 64 / 49,856, that the JavaScript verdict is `valid is False`, and that
  the algorithm is absent from `DEVICE_ELIGIBLE_SIG_ALGS`.
- ADR-0015 ("A labelling defect surfaced and is recorded") and ADR-0016 (`DEVICE_ELIGIBLE_SIG_ALGS`
  as an allowlist rather than a size check).
- `key_service.py` lines 33–43 — the engineering consequence, written out.

**The generalisable lesson, which is what makes it publishable.** During a standards transition,
*an algorithm identifier in a library API is a claim, not a fact, and parameter sizes are not a
compatibility oracle.* A crypto-agile system that trusts either will strand its own history
silently. The correct mitigation is a cross-implementation interoperability test as an admission
gate — which is exactly what `DEVICE_ELIGIBLE_SIG_ALGS` plus `test_device_interop.py` implements.
This is a small but genuine result with a concrete, reusable design recommendation.

**Caveat to state.** The finding is against one library version (`quantcrypt==1.0.1`) at one point
in time, established against one reference implementation (`@noble/post-quantum`). It should be
reported with those bounds and with the exact reproduction steps, not as a general claim about
PQClean.

#### 2.1.2 Differential verification across a language boundary, on forgeries

Differential testing is not new. What is unusual, and defensible as a *methodological*
contribution, is the specific discipline: **two implementations must agree on the same set of
*failed check keys*, not merely on the boolean verdict, across eight distinct forgery classes and a
parametrised sweep of every signed field** — and the pure-verifier property is asserted in a
subprocess by inspecting `sys.modules` (`test_verifier_purity.py`), because purity erodes one
convenient import at a time.

Framed as a question — *"how do you establish that a transparency artefact is genuinely checkable
by someone who does not have your codebase?"* — this is a real contribution to practice. It is not
a research novelty; it is a good answer to a question most projects do not ask.

**Must be qualified** per V5: one author, one reading of the spec. It bounds transcription error,
not conceptual error.

#### 2.1.3 A documented non-goal, retired, with the negative half asserted by test

The ADR-0005 → ADR-0015 arc is the most intellectually honest thing in the project and is unusual
in a student artefact. ADR-0005 stated truncation as an accepted, undetectable limitation and
explained precisely what would be required to close it. ADR-0015 built exactly that, retired the
non-goal, and left the original paragraph intact rather than rewriting history. And
`test_a_truncated_ledger_is_caught_by_the_witness_and_by_nothing_else` asserts *both* halves —
that `verify_ledger()` reports `ok=True` on the truncated log, **and** that the witness refuses.

This is a clean, teachable demonstration of the limits of self-verification, and it is the single
best figure the paper can produce (see §6, F3).

#### 2.1.4 Smaller design touches worth a paragraph each

- **The refusal-as-alarm pattern.** `maybe_checkpoint` declines to sign a non-extension, so a
  rewrite produces a *stall* rather than a signature blessing it. "A log whose newest checkpoint is
  old while entries keep arriving is a log that cannot prove it still contains its own past." The
  idea is present in the CT literature in spirit; the crisp articulation and the test that pins the
  visible gap are the contribution.
- **Downgrades as a distinct event type.** ADR-0012's observation — *agility and downgrade are the
  same mechanism viewed from opposite ends* — is a well-known TLS lesson, but recording an
  authorised downgrade as `algorithm_downgraded` rather than `algorithm_switched`, so an auditor
  can find every weakening decision **by event type alone without knowing which `alg_id` outranks
  which**, is a genuinely nice small design move, and the security category is read from
  `AlgMeta` rather than hardcoded so a future algorithm inherits the protection for free.
- **Runtime-rendered self-verifying documents.** ADR-0019's argument that pre-rendering the
  readable half would let a tampered file display the original wording while its signatures
  silently failed — "inviting precisely the wrong conclusion" — is sharp and not commonly
  articulated.
- **Custody as an evidentiary class, not a merged property.** `Signature.custody` returns
  `'device'` or `'server'`, the ledger records it, and the exported bundle displays it, "so an
  auditor must not be able to mistake the weaker claim for the stronger one just because both are
  ML-DSA-65."

### 2.2 Competent engineering integration of existing ideas — which is most of it

Say this plainly in the paper. It is not a weakness; it is the honest description of an
integration study, and integration studies are publishable when they report what integration
actually cost.

| Component | Prior art it integrates |
|---|---|
| Crypto-agility via a provider registry + per-artefact `alg_id` | Textbook, ~30 years old: X.509 `AlgorithmIdentifier`, JOSE/COSE `alg`, JWK `kid`, PKCS#11 mechanisms. "Store the algorithm with the artefact and resolve the provider from it" is not a new idea. **What is worth reporting is that it was executed end-to-end and demonstrated with a mixed-artefact corpus** — most papers asserting agility do not do this. |
| M-of-N as N independent signatures | Standard multisig. Threshold PQC correctly declared out of scope (ADR-0002). |
| SHA-256 hash-chained audit log | Standard tamper-evident logging. |
| RFC 6962 Merkle tree, inclusion + consistency proofs | Certificate Transparency, followed to the byte. Explicitly a transcription, not an invention. |
| Witness co-signing with TOFU pinning, high-water mark, consistency-or-refuse, recorded violations | Essentially the CT / Sigsum / Go checksum-database witness model. Correctly applied, not new. |
| Retire-but-retain key rotation | Standard key lifecycle practice. |
| Argon2id-derived KEK wrapping private keys at rest | Standard; OWASP-aligned parameters. |
| ML-KEM encapsulation of an AES-256-GCM DEK | Standard KEM-DEM. |
| Verify-after-sign as a fault countermeasure | Known and recommended in the ML-DSA fault-attack literature. ADR-0010 applies it correctly and — importantly — **does not overclaim**: "this detects faults, it does not prevent them, and it cannot detect a fault that produces a *valid* signature over a *different* message." |
| Domain-separation tags on every signed payload | Standard. |
| Re-deriving the proposal binding at verification time | Just "verify what you display", correctly applied. |

**The `verify_proposal_binding` story is nonetheless excellent paper material** — not as novelty,
but as an *experience report*. ADR-0009 documents a real, live defect (the code compared one stored
column against another; `signing_bytes_for` existed, was correct, and was called only from tests),
explains why every test passed anyway ("every test operated on honest data"), and records that it
was found by adversarial review of their own code rather than by a failing test. That is a
publishable observation about testing methodology: **a test suite built from honest inputs cannot
find a missing integrity check.**

### 2.3 Standard practice, correctly applied

Layered service/blueprint architecture; CI matrix across Windows and Ubuntu 24.04 with pinned
dependencies; `ruff` + `black` gating; a coverage floor (`--cov-fail-under=88`); an architectural
boundary enforced by a test; vendored offline assets; CSRF via Flask-WTF with a documented,
narrowly-scoped exemption for the device API; SQLAlchemy ORM written to stay PostgreSQL-compatible;
an advisory (non-gating) mypy job with an honest comment about why it does not gate.

### 2.4 What would be dismantled in review if claimed

| If the paper claims… | The reviewer's response |
|---|---|
| "Implements the three NIST post-quantum standards (FIPS 203/204/205)" | **False for FIPS 205.** The code itself says so. See §3.1. |
| "Novel crypto-agile architecture" | Provider registry + per-artefact algorithm identifier is decades old. |
| "Independent witness provides truncation detection" | Only under deployment separation the artefact does not demonstrate; and it shares code. |
| "Two independent verifiers prove the format correct" | One author, one spec reading. Bounds transcription error only. |
| "Quantifies the cost of crypto-agility" | It quantifies the cost of *algorithm choice*. The cost of the agility *mechanism* (registry dispatch, per-artefact resolution) is never measured. See §4.4. |
| "Non-repudiation" | Explicitly disclaimed for server custody; hardware-*gated* not hardware-*held* for device custody. |
| "668 tests, all green" | 794 collected / 563 test functions and rising; ~36 of the most important skip silently in CI. See §3.9. |
| "Immutable audit ledger" (still in `pyproject.toml`) | The project's own documentation says "Immutable is the wrong word." See §3.1. |
| "Rate limiting is in scope" (spec §4.11) | Implemented nowhere. See §3.10. |
| "Type-checked codebase" | mypy "has never run clean"; the job is `continue-on-error`. See §3.9. |
| "The witness provides assumption diversity" | Its default is ML-DSA-87 against the log's ML-DSA-65 — same lattice family. See T17a. |

---

## 3. Documented limitations and threats to validity

The project has already admitted most of these. **A paper that states them itself is stronger than
one that waits to be asked.** Locations are given so each can be cited.

### 3.1 The FIPS 205 labelling inconsistency (unresolved in the documentation)

The code was corrected; **three artefacts still carry the old, false claim**:

| File | Line | Claim |
|---|---|---|
| `README.md` | 13 | "Built on the three NIST post-quantum standards … **SLH-DSA (FIPS 205)**" |
| `README.md` | 67 | Benchmark table row: `SLH-DSA-SHAKE-256f \| FIPS 205, cat 5` |
| `docs/benchmarks/latest.json` | 152 | `"nist_standard": "FIPS 205"` |
| `docs/benchmarks/latest.md` | 13 | `SLH-DSA-SHAKE-256f \| FIPS 205 \| 5 \| …` |
| `docs/PROJECT-SPECIFICATION-AND-PLAN.md` | 16, 36, 58, 162, 247, 435 | Repeated "SLH-DSA (FIPS 205)" |

The benchmark artefacts were generated `2026-08-04T15:42:55+00:00`; the finding is dated
2026-08-11 (ADR-0015). **They predate the discovery and were never regenerated.** ADR-0011's own
rule — "a demonstration aid may never make the system claim something untrue" — is currently
violated by the project's own README and its published numbers. This must be fixed before anything
is submitted, and the fix is a `python scripts/run_benchmark.py` run plus three text edits.

**A second, independent terminology regression.** `pyproject.toml:4` still describes the project as
having an **"immutable audit ledger"** — precisely the word ADR-0003 and ADR-0005 spent their
"Consequences" sections retiring in favour of *tamper-evident under an external anchor*, and which
`docs/OWNER-ACTIONS.md` §4.3 (line 460) has an open action to remove from the project title.
`qvault/templates/docs/audit.html:52` gets it right ("**Immutable is the wrong word.**"). The
packaging metadata was missed. A paper that argues for careful terminology and ships a package
description contradicting it hands a reviewer a free point.

### 3.2 Scope boundaries the project declares itself

| Limitation | Location |
|---|---|
| Application-level M-of-N, not threshold PQC ("an open research problem") | ADR-0002 |
| Hash chain, not a blockchain; "tamper-evident under an external anchor", **not** "immutable" | ADR-0003 |
| No third-party non-repudiation for server-custodied keys | ADR-0004 "Honesty:"; spec §4.11 |
| The server master key is "an env secret documented as an HSM/KMS surrogate" | ADR-0004 |
| An attacker holding the master key can forge anchors | ADR-0005 "Scope/honesty:" |
| An attacker with DB write access can edit `algorithm_config` and bypass downgrade protection entirely; the discrepancy is detectable but **nothing currently alerts on it** | ADR-0012 "Honest limitation" |
| Deleting the `proposal_created` entry makes the ledger binding check unsatisfiable; reported as a failure, not a pass | ADR-0009 "Honest residual" |
| A proposal mutated *before* any vote is not an attack — signers see the current text | ADR-0009 "Not addressed" |
| Verify-after-sign detects faults, does not prevent them, and cannot detect a fault yielding a *valid* signature over a *different* message | ADR-0010 "Not claimed" |
| No side-channel (timing/power) analysis of the underlying PQClean implementations | ADR-0010; README "Known limitations" |
| Split-view (a log hiding an entry from everybody) is out of scope; needs client gossip | ADR-0015; `verify/core.py` docstring |
| Only the *signature* default is switchable; the KEM switch is a no-op with one registered KEM | ADR-0006 |
| The SYSTEM anchor key keeps its original algorithm across a switch | ADR-0006 |
| Retained (retired) keys accumulate; pruning them is out of scope | ADR-0007 |
| Per-vault security-category floor deliberately not built | ADR-0012 |
| Rate limiting on `/devices/challenge` and `/devices` deliberately not built — "unauthenticated password-guessing surfaces"; the web login has the same property | ADR-0016 "Deliberately not built" |
| No master-key MAC over device public keys; token renewal, push registration and a device-management screen not built | ADR-0016 |
| **Plaintext-hash guess-and-confirm oracle.** Storing the plaintext file's SHA-256 (so it can be signed into the proposal) "permits a guess-and-confirm oracle under DB theft; documented as an accepted limitation … the ~2³² birthday bound per key is documented." | spec §4.9, line 557 |
| **No account recovery.** "a lost password with no recovery is a stated limitation" — and because the signing key is wrapped under a password-derived KEK, a lost password is a lost signing key. | spec FR-46, line 157 |
| **Changing a password does not invalidate existing sessions.** "Known limitation: this does not invalidate sessions established with the old password." | `qvault/services/key_service.py:290` |
| **Vault ownership transfer is not supported** — "a real feature, not a one-liner": it would have to move `owner_id`, re-check the signer count and decide the outgoing owner's role in one transaction. | `qvault/services/vault_service.py:9-12, 169-170` |
| **Publication revocation cannot recall a downloaded bundle.** "it stops this server serving the record, and it does not — cannot — retract a bundle somebody already downloaded." The UI wording is deliberately "stops serving", never "revoked" or "deleted". | `publication_service.py:24-25`; `blueprints/vaults.py:388-390`; `forms.py:217` |
| **Key zeroisation is best-effort only** — "Python cannot guarantee zeroisation of immutable bytes". | `key_service.py:83, 318`; `ledger_service.py:250` |
| **Anchoring and checkpointing are best-effort and swallow errors** — "a failure to sign must never fail a user's request". The honest outcome is an un-anchored head, which `verify_ledger()` then reports. | `qvault/__init__.py:190` |

### 3.3 Concurrency, races and single-process assumptions

| Limitation | Location |
|---|---|
| **Multi-worker deployment would start one scheduler per worker** → N concurrent rotations. `qvault/scheduler.py::init_scheduler` guards only the Werkzeug reloader; the inline NOTE says "run the app single-worker, or run the scheduler in a dedicated process". Ledger `UNIQUE(seq)` prevents corruption; the loser rolls back. | `qvault/scheduler.py`; ADR-0007 "Deployment limit" |
| The `uq_signature_signer` race is handled but **only reachable under real concurrency**, which the suite never exercises: `approval_service._is_duplicate_vote` and the `flush()`-inside-`try` comment ("a concurrently-committed vote by the same signer that `vote_of()` could not see"). | `qvault/services/approval_service.py` |
| A ledger `seq` collision must not be reported to an honest voter as a re-vote — handled by matching the constraint name, again untested under concurrency. | `approval_service._is_duplicate_vote` |
| The tamper-demo backup `_DEMO_BACKUP` is **process-local module state**; `demo_restore` returns `False` if a restart lost it. | `ledger_service.demo_restore` |
| The glassbox recorder's buffer "itself *is* process-global, and bounded". | `qvault/glassbox/recorder.py:22-24` |
| **The first-registrant-becomes-admin check is an unguarded check-then-set.** "(Single-process demo: this check-then-set is unguarded; a concurrent first-registration race is out of scope. A hardened deploy would provision the admin out-of-band.)" — i.e. under concurrency two accounts could both become admin. | `qvault/services/auth_service.py:40-41` |
| The deployed container runs **one worker deliberately** for this reason: "APScheduler runs in-process, so N workers would start N schedulers — the limitation ADR-0007 documents." | `Dockerfile:46-48` |
| The glass-box page polls rather than using SSE because on "the deployed **single-worker container** … one viewer of this page is enough to stop the application answering anything else." | `qvault/blueprints/glassbox.py:56` |
| The witness store is "a tiny, synchronous store. One connection, because a witness is not a busy service", opened with `check_same_thread=False`. | `witness/store.py:61,65` |
| Further mapped races, all handled but none exercised concurrently: `uq_vault_member` on concurrent member add; ledger-`seq` collisions in `proposal_service` and in two `admin.py` handlers; a read-time expiry write that "must never 500 because a read-time expiry write raced/failed". | `vault_service.py:131`; `proposal_service.py:175`; `admin.py:239,263`; `vaults.py:246-249` |
| SQLite is the demo store; a PostgreSQL migration script exists (`scripts/migrate_to_postgres.py`) but the concurrency characteristics of the two differ materially and are not compared. Related portability trap already found: "SQLite's DATETIME discards the offset, so aware values round-trip as *naive* on SQLite but *aware* on PostgreSQL". | `qvault/models/_types.py:14-17` |

**There is no concurrency test anywhere in the suite**, and `TestConfig` sets
`SCHEDULER_ENABLED = False`, so the scheduler's own wiring — including the reloader/multi-worker
guard at `scheduler.py:32` — is **never executed under test**. This is the largest untested area of
carefully-written code in the project. Note also that the spec's own risk register still lists
**R13 "Scheduler double-fires (reloader / multi-worker)"** as open, mitigated only by
"single-process for demo; documented multi-worker approach".

### 3.4 Development-only and demonstration-only features

| Feature | Gate |
|---|---|
| Ledger tamper demo (`edit` / `rewrite`), proposal tamper demo, key-ageing control | `security/demo_gate.py::demo_enabled` — requires `ENABLE_TAMPER_DEMO` **and** `DEBUG or TESTING` |
| Glass-box trace page | `GLASSBOX_ENABLED`, default `false` (`true` in dev and test), admin-only, "not a product feature" |
| Live in-request benchmark | `BENCHMARK_LIVE_MAX_ITERATIONS` (5) and `BENCHMARK_LIVE_BUDGET_S` (10); labelled indicative |

ADR-0011's own admission is the one to quote: *"these aids are development-only by construction, so
the exact configuration demonstrated is not the configuration that would be deployed."*

### 3.5 Deployment and operational

- **Witness independence is a deployment property.** `witness/README.md`: "On one laptop it
  demonstrates the mechanism; it does not deliver the security."
- **Trust-on-first-use key pinning** at the witness — "a real weakness … strictly better than
  accepting any key at any time" (`witness/README.md`).
- **No rate limiting anywhere** — confirmed by search: no limiter, no `rate_limit`, no `Limiter`
  in `qvault/` or `config.py`.
- **No explicit session hardening** — `config.py` sets no `SESSION_COOKIE_SECURE`,
  `SESSION_COOKIE_HTTPONLY` or `SESSION_COOKIE_SAMESITE`. For an HTTPS deployment,
  `SESSION_COOKIE_SECURE` being unset is a standard finding a reviewer will make.
- **Schema is created with `db.create_all()` and there is no Alembic**, so it "creates missing
  tables but never ALTERs an existing one". ADR-0016 explains at length that a new column on an
  existing table "would fail at **boot** … while the test suite stayed green, because tests build a
  fresh in-memory schema." This is a real, admitted operational fragility and it has already shaped
  two designs (`Signature.custody` as a derived property; publication state as ledger events rather
  than a column).
- **The mobile `runtimeVersion` is static**, trading automatic refusal-to-ship for a discipline
  rule; "a missed bump ships a crash" (ADR-0018).
- **Not production-audited**: no independent security review (README "Known limitations"); the
  landing page carries "Reference system, not production-audited" as a persistent footer.
- **Licence not yet chosen** — "currently unlicensed, all rights reserved" (README). A paper
  claiming a public reference implementation needs this resolved.

**Live deployment defects recorded in `docs/OWNER-ACTIONS.md` that bear on the evaluation:**

- **§2.6 (marked demo-blocking, `TODO`): uploaded attachments are destroyed on every restart.** The
  `qvault` Container App has "**no volumes and no volume mounts**", so "every uploaded file is
  destroyed on restart, redeploy, scale event or revision change" and "the row promises a file that
  no longer exists." Also: "**Files already uploaded are gone for good.**" Any evaluation performed
  against the deployed instance must exclude file-attachment paths, or say so.
- **The deployed image is older than the repository.** "the deployed image predates that fix and
  will keep returning 500 until a new image ships." A paper must therefore be explicit about
  whether its numbers come from the deployed instance or from a local run — they are not the same
  system.
- **§2.2 warning:** "**Do not run `scripts/seed_demo.py --reset` on this database.** It calls
  `db.drop_all()` unconditionally and mints a new SYSTEM key, which makes the existing witness
  reject the whole log as `key_changed`." This is worth a sentence in the paper: the witness
  correctly treats a re-seeded log as a different log, which is the property working, but it also
  means the demonstration corpus cannot be reset without re-establishing the trust root.
- **§2.4 (`TODO`): tearing down the Azure witness after the demo silently downgrades every
  export** — "it is what turns the last verifier check from NOT-APPLICABLE into PASS."
- **§2.5 (`PARTLY DONE`): the key fingerprints are published inside the repository the log ships
  from**, which OWNER-ACTIONS itself identifies as circular: "a fingerprint is only worth anything
  if it reaches the reader through a channel the log does not control. Me writing it into the repo
  the log ships from is exactly the circularity it exists to break." Recorded values: log
  `951dbf99653347de` (ML-DSA-65), witness `c79ad5683b2e9109` (ML-DSA-87). The stated remedy —
  "**put the witness fingerprint on a slide, or write it on the board, before the demo starts** …
  A fingerprint produced after the fact proves nothing; one committed to in advance is evidence" —
  is **the step that converts the whole witness argument from mechanism into property**, and it is
  still open. See §5, G13.

### 3.6 Mobile / device custody

- **The key is hardware-*gated*, not hardware-*held*** — no consumer secure element supports
  ML-DSA, so the private key lives in OS keystore encrypted storage released after a biometric
  check. "A rooted device with the screen unlocked can extract it." (ADR-0016, "Honest limitation")
- **Per-signature key regeneration cost is unmeasured on real hardware** — "6–27 ms on desktop V8;
  on Hermes it will be some multiple of that … This has not yet been measured on real hardware."
  (ADR-0017, "Open")
- **Unconfirmed:** that the `crypto.getRandomValues` polyfill installs before
  `@noble/post-quantum` loads under Hermes (ADR-0017, "Open"). The code comment is blunt about the
  stakes: "Hermes has no `crypto` global, so on a handset that call throws — and it throws inside
  signing, which is the one place a failure is most expensive and least reproducible on a laptop"
  (`mobile/src/crypto/algorithms.ts:26-29`).
- **The reported biometric factor is the strongest the handset offers, not the one actually
  used.** "The OS does not tell us which one was … Claiming otherwise would be inventing precision
  the platform does not give us" (`mobile/src/keystore.ts:96-101`). `disableDeviceFallback: false`
  means a PIN or pattern can stand in for a fingerprint — "a deliberate choice rather than
  laziness" — and a handset with no lock at all returns `'none'`, falling back to the account
  password (`keystore.ts:92-94, 103-104`).
- **No device attestation of any kind.** A search of `mobile/**` finds no root/jailbreak detection,
  no Play Integrity, no DeviceCheck and no hardware key attestation. Device custody rests entirely
  on `expo-secure-store` plus the OS lock — which is consistent with ADR-0016's "hardware-*gated*,
  not hardware-*held*" admission, but means the server has **no evidence** that an enrolling device
  is not rooted. Worth stating explicitly: the proof of possession proves the device holds the key,
  never that the device protects it.
- **OTA/build constraints:** the release-signing key "is the app's identity for its lifetime" — a
  different key means Android refuses to install over an existing copy "and the ML-DSA seed in that
  install's keychain becomes unreachable — every enrolled device has to enrol again"
  (`mobile/README.md:135-138`). Face ID does not work in Expo Go, so biometrics can only be
  validated on a real build (`mobile/README.md:99-101`).

### 3.7 Benchmark validity (the project's own statements)

From ADR-0008 "Consequences", verbatim in substance:
- **Laptop-class.** "Thermal throttling and OS scheduling are the dominant error terms, so absolute
  values are not comparable across machines — the *ratios* between algorithms are the durable
  result and are what the report should argue from."
- **Single-threaded and uncontended.** "It says nothing about throughput under concurrent load,
  which is a different experiment and out of scope."
- **Verification fixtures are pooled** at eight and cycled; the ADR argues the residual bias "is
  optimistic for verify by a negligible margin" — argued, **not measured**.
- `scripts/run_benchmark.py` docstring: "close other applications first and run on mains power".

### 3.8 Uncommitted work in the audited tree

The last commit is `90591dc` (2026-08-21). The working tree additionally contains **untracked and
unmerged** work:

- `qvault/glassbox/` (4 modules, ~30 KB — recorder, redaction, source) — **created 2026-09-08**
- `qvault/blueprints/glassbox.py`, `qvault/blueprints/record.py`, `qvault/templates/record/`
- `qvault/services/publication_service.py`, `qvault/services/receipt_service.py`
- `tests/test_public_record.py` (19 cases), `tests/test_signing_receipt.py` (16 cases)
- Modifications to 15 tracked files including `approval_service.py`, `checkpoint_service.py`,
  `key_service.py`, `ledger_service.py`, `config.py`

Implications for the paper:
1. **The paper must state which revision it describes.** Commit this work, or describe the
   committed state only.
2. **The glass box was completed during this audit — re-check before citing.** At the start of this
   audit `qvault/glassbox/` had no dedicated tests and both `config.py:82` and
   `qvault/glassbox/__init__.py:32` cited "ADR-0017", which is *seed-derived device keys*. **Both
   defects were fixed while the audit was in progress:** `docs/adr/0020-glass-box-live-trace.md`
   now exists (dated 2026-09-08, "Extends ADR-0011, ADR-0015; Bounded by ADR-0014"), the citations
   point to ADR-0020, and `tests/test_glassbox.py` (26 cases) plus `tests/test_glassbox_routes.py`
   (14 cases) now pin the package. Collected tests rose from 752 to **794 across 42 files** (563
   test functions) during the audit window. **Treat every count in this report as a snapshot, and
   re-run `pytest --collect-only -q` before quoting a number in the paper.**
3. **The glass-box tests cover the properties that matter**, which is worth recording because they
   are exactly the ones a reviewer would probe: `test_captured_source_matches_the_file_on_disk`
   (reads the file independently of `inspect` and compares, so a cached or rewritten capture
   fails), `test_a_broken_presenter_cannot_fail_the_operation`, `test_a_step_outside_an_operation_is_discarded`,
   `test_the_buffer_is_bounded`, `test_no_secret_material_reaches_the_trace`,
   `test_tracing_does_not_change_what_is_recorded`, `test_recorder_does_not_import_flask_at_module_level`,
   and route-level gating (`test_trace_is_404_when_disabled`, `test_trace_requires_an_administrator`).
   The residual is cosmetic: `source.py:10` still names `tests/test_glassbox_source.py` while the
   file is `tests/test_glassbox.py`.
4. **Strict redaction remains a testing-only guarantee.** `qvault/glassbox/redaction.py:14-17`:
   strict mode "is on under TESTING so the suite fails on an unwrapped value, and off in every
   other configuration" — so in a running deployment a mis-wrapped traced value **silently degrades
   to `Opaque` rather than raising**. The fail-safe direction is correct (withhold rather than
   leak), and `test_unwrapped_value_is_withheld_not_shown` pins the non-strict behaviour, so this
   is a documented design choice rather than a gap. State it as such.
5. **The glass box defaults to ON in `DevConfig`** (`config.py:99`) — the configuration the
   documented demo runs under (`flask --app wsgi run --debug`). `qvault/blueprints/glassbox.py` is
   candid that on that page "a reader sees other people's public keys, signatures and payload
   hashes." Correct for a demo; describe it as a demo-only configuration.
6. **The glass box cannot show what most readers will assume it shows.** `glassbox/source.py:13-17`:
   "this shows Python we wrote. It cannot show the interior of ML-DSA or SLH-DSA, which are
   compiled PQClean binaries." Any figure derived from it must carry that caption.
7. The stale `.coverage` file (dated 2026-08-24, `TOTAL … 78%`) predates the glass box entirely and
   is almost certainly from a partial run, since CI enforces `--cov-fail-under=88` and comments
   "92% at the time of writing". **Do not quote 78%.** Regenerate before citing any coverage
   figure.

### 3.9 Test-suite claims

- README says **"668 tests"**. Collection at the close of this audit was **794 cases** across 42
  files, from **563 distinct `def test_` functions**. The gap is parametrisation, and it is
  concentrated:
  `test_merkle.py` alone contributes **153** cases (tree sizes 1…33 swept four times) and
  `test_offline_assets.py` contributes **38**. The honest phrasing is *"563 test functions, 794
  parametrised cases"* — quoting the larger number without that qualification will look like
  padding to anyone who runs `--collect-only`.
- **36 cases skip silently in CI** (`test_offline_verifier.py`) because `playwright` is
  undeclared — see V4 and §5 G1. These are precisely the cases backing the project's most
  distinctive claim.
- `tests/test_device_interop.py` (7 cases) skips unless Node and `@noble/post-quantum` resolve —
  but the CI `mobile` job **does** install them, so these do run in CI. Likewise
  `test_mobile_e2e.py` and `test_mobile_canonical.py`, which skip unless `pnpm install` has been
  run in `mobile/` ("Checking for the `node` binary alone is not enough").
- **The coverage gate measures `qvault` only.** `pytest --cov=qvault` excludes `witness/`,
  `scripts/` and `mobile/` from the floor, so the witness service — a load-bearing security
  component with 40 tests of its own — contributes to no coverage number the project reports.
- **The type checker has never passed.** `.github/workflows/ci.yml:67-69`: "mypy has never run
  clean against this codebase (`disallow_untyped_defs` is aspirational). Reported, never gating."
  The job carries `continue-on-error: true`, with an honest justification ("a red X on a check
  nobody intends to fix teaches people to ignore red Xs") — but the paper should not describe the
  project as type-checked.
- `tests/test_crypto_agility.py` contains two `pytest.skip("need at least two signature
  algorithms")` guards. They do not fire today, but they mean the central agility test is
  *structurally* capable of vacuously passing if the registry were ever reduced.

### 3.10 Specification-versus-implementation drift

`docs/PROJECT-SPECIFICATION-AND-PLAN.md` is presented as the master requirements document but has
not been reconciled with the last three phases of work. A reviewer reading it alongside the code
will find four contradictions:

| Spec says | Reality |
|---|---|
| §4.11 STRIDE, *Denial of service*: "App-level **rate limits** + auth checks; partially in scope" (line 571) | **No rate limiting is implemented anywhere.** A repository-wide search for `rate.?limit\|throttl\|lockout\|brute` across `qvault/**` returns no implementation. Login, `/devices/challenge` and `/devices` are all unthrottled. ADR-0016 is honest about this ("deliberately not built"); the specification is not. **This is the one place where a document claims a control that does not exist**, and it must be corrected. |
| §1.3 out of scope: "**No mobile/native client**; browser dashboard only" (line 68) | A full Expo mobile client exists (`mobile/`), with device-held signing keys (ADR-0016/0017), and CI builds and type-checks it. |
| §1.3: "**User-to-third-party non-repudiation is explicitly not claimed**" (line 71); §4.7 repeats it (line 533) | Superseded *in part* by ADR-0016: for device-custodied votes the server never held the private key. The spec was never updated, so the two documents now disagree about the project's strongest claim. |
| §4.6 / §1.3 terminology corrected to "tamper-evident" throughout | `pyproject.toml:4` still says "immutable audit ledger" (§3.1). |

The paper should cite the **ADRs** rather than the specification wherever they disagree: the ADRs
are current and the specification is not. Say which document is authoritative, once, early.

### 3.11 Risk register status

Spec §12 (lines 797–816) carries a 17-row risk register. Rows **R7–R12 and R15** are marked
resolved. Still open, and relevant to a paper's threats-to-validity section:

| Risk | Likelihood / impact | Note |
|---|---|---|
| **R1** liboqs will not build on Windows | High / High | Mitigated by choosing quantcrypt (ADR-0001) — but this is *why* claim A8 (backend agility) remains aspirational |
| **R4** correctness bug — a bad verification, or a duplicate counted | Med / High | Substantially mitigated by `tally()` re-verification and `uq_signature_signer`, but untested under concurrency (§3.3) |
| **R5** rotation breaks history | Med / High | Well mitigated and well tested (A3) |
| **R6** **crypto-agility superficial** | Med / Med | **The paper's central risk, and the register names it.** §2.2 and A8/A9 are the honest answer |
| **R13** scheduler double-fires (reloader / multi-worker) | Low / Med | Mitigation is operational, not code (§3.3) |
| **R14** key-at-rest / password-change mishandled | Low / High | Mitigated; ADR-0014 records a real bug caught here (M7) |
| **R16** live demo fails | Med / High | See the deployment defects in §3.5 |
| **R17** dependency drift | Low / Med | Mitigated by `requirements.lock.txt` in CI |

R2 (over-scope) and R3 (time slippage) are project-management risks, not paper content.

---

## 4. Evaluation assets that already exist, and their methodological quality

### 4.1 What has been measured

`docs/benchmarks/latest.json` (275 lines) and `latest.md`, generated `2026-08-04T15:42:55+00:00`:

| Algorithm | Standard *as labelled* | Cat. | Public key | Signature | Keygen | Sign | Verify | Verify/s |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| ML-DSA-65 | FIPS 204 | 3 | 1,952 B | 3,309 B | 0.754 ms | 1.714 ms | 0.627 ms | 1,596 |
| ML-DSA-87 | FIPS 204 | 5 | 2,592 B | 4,627 B | 0.811 ms | 1.603 ms | 0.716 ms | 1,398 |
| SLH-DSA-SHAKE-256f | *(mislabelled — see §3.1)* | 5 | 64 B | 49,856 B | 2.503 ms | 38.657 ms | 1.768 ms | 566 |
| ML-KEM-768 | FIPS 203 | 3 | 1,184 B | 1,088 B ct | 0.636 ms | encaps 1.017 ms | decaps 0.734 ms | — |

Parameters: 50 iterations, 5 warm-up rounds, 256-byte messages, 20 s per-operation budget.
Environment recorded: CPython 3.13.5, Windows 11, AMD64, AMD Family 25 Model 80, 12 logical CPUs.
Total run time 3.54 s.

A derived table exists in ADR-0010: **verify-after-sign overhead** — ML-DSA-65 +37%, ML-DSA-87
+45%, SLH-DSA +4.6%. This is the most interesting result the project has produced and it is
currently buried in an ADR rather than presented as a finding.

### 4.2 Methodology quality — what holds up

`qvault/services/benchmark_service.py` is, for a project at this level, **unusually
well-constructed**. A reviewer attacking methodology first will find most of the obvious attacks
already closed:

| Threat to a micro-benchmark | Defence | Location |
|---|---|---|
| Wrong clock | `time.perf_counter_ns` — monotonic, highest resolution, immune to wall-clock adjustment | `_measure` |
| Setup charged to the measurement | `setup()` runs outside the timed region; only the crypto call is between `t0` and `t1` | `_measure` |
| Cold-start costs in the first sample | Untimed warm-up rounds, themselves correctness-checked | `_measure` |
| A GC pause inside a sample | `gc.disable()` for the loop, restored in a `finally` so a failed run cannot leave the process with GC off — **and a test pins that**: `test_measure_restores_the_garbage_collector_even_on_failure` | `_measure` |
| **Timing a wrong answer** | Every sample is correctness-checked; a failure raises `BenchmarkError` and aborts. KEM secrets compared with `hmac.compare_digest` | `_measure`, `benchmark_kem` |
| **An always-true verifier posting the best numbers** | Each signature algorithm must additionally *reject* a flipped signature bit **and** a modified message, else `BenchmarkError` | `benchmark_signature` |
| Sizes quoted from the spec rather than measured | `measured_sizes` from freshly generated keys and real signatures, reported alongside declared `AlgMeta.sizes`; `test_all_providers_declare_consistent_metadata` asserts they agree | `benchmark_signature`, `test_crypto_agility.py` |
| A mean dominated by one scheduler stall | Median and p95 reported alongside mean, with min/max, stdev and sample count; **throughput derived from the median** | `_summarise` |
| p95 computed wrongly | Nearest-rank `ceil(0.95n)`, with an explicit comment that `round` would use banker's rounding and pick the wrong sample; pinned by `test_p95_uses_nearest_rank_not_bankers_rounding` | `_summarise` |
| Wrong stdev estimator | Sample (Bessel-corrected) `statistics.stdev`, with a comment justifying it | `_summarise` |
| Silently reporting fewer samples than claimed | `budget_exhausted` flag + `iterations` vs `requested_iterations`; the Markdown report emits an explicit truncation warning and the admin page discloses it. "Results are never padded or extrapolated." | `_measure`, `to_markdown` |
| Measuring a different code path from production | Measured **through the `CryptoRegistry`** — the same seam the application signs through | module docstring |
| Application overhead contaminating the figures | `scripts/run_benchmark.py` builds a registry directly; no Flask, no DB, no config | script docstring |
| A demo measurement passed off as canonical | The in-request `/admin/benchmark` run is hard-capped and labelled indicative | ADR-0008 |
| A stored report breaking the UI | Missing / unreadable / malformed / foreign-schema files render the empty state — four separate tests | `test_benchmark.py` |

The harness is itself tested: **36 cases** in `tests/test_benchmark.py`, including tests that the
harness's own failure modes work (`test_measure_rejects_an_incorrect_result`,
`test_measure_rejects_an_incorrect_result_during_warmup`,
`test_measure_truncates_honestly_when_the_budget_is_exhausted`,
`test_total_budget_never_widens_the_per_op_budget`). Benchmarking a benchmark harness is not
common and is worth a sentence in the evaluation chapter.

### 4.3 Methodology quality — what a reviewer will attack anyway

Ordered by how damaging each is.

1. **No classical baseline. This is the biggest single hole.** Confirmed by search: RSA, ECDSA and
   Ed25519 appear nowhere in the benchmark path. A paper about the *cost of migrating to PQC* that
   never measures what is being migrated *from* cannot support its central economic argument. The
   `cryptography` library (50.0.0) is already a pinned dependency and provides all three.
2. **n = 1 run, on 1 machine, at 1 point in time.** Fifty iterations within a single run bounds
   within-run variance; it says nothing about run-to-run or machine-to-machine variance. No
   confidence intervals are reported. The project already concedes absolute values do not travel —
   but it then publishes absolute values in the README as its headline table.
3. **The "cost of agility" is not the cost of agility.** ADR-0008 frames the benchmark as
   justifying crypto-agility, but what is measured is the cost of *choosing a different algorithm*.
   The cost of the *agility mechanism* — dictionary dispatch in `CryptoRegistry.signature()`, plus
   resolving `alg_id` per artefact — is never measured. It is almost certainly nanoseconds against
   a 1.7 ms signature, and **that is the publishable result**: agility is free at runtime; its real
   cost is schema surface and engineering discipline. Currently the paper cannot say so with
   numbers.
4. **The pooled-verify bias is argued, not measured.** Eight `(message, signature)` pairs cycled
   over 50 iterations means the data is L1/L2-resident. ADR-0008 asserts the bias is "optimistic
   for verify by a negligible margin". A one-line experiment (pool = 8 vs pool = 50) would convert
   an assertion into a measurement.
5. **One message size (256 bytes), no sensitivity analysis.** Defensible for hash-then-sign
   schemes, but unstated as a design assumption and unmeasured.
6. **No end-to-end application latency at all.** The only timing outside the benchmark harness is
   `receipt_service`'s `verify_ms` (a live re-verification), loosely bounded by
   `test_signing_receipt.py::assert 0 < receipt["verify_ms"] < 5000`. Nothing measures the cost of
   casting a vote, which is dominated by an ~80 ms Argon2id derivation, not by PQC. ADR-0010 cites
   that ~80 ms figure repeatedly as its cost argument — **it appears to be an estimate, and it is
   the most-reused number in the ADR series.**
7. **Nothing measures how the system scales with log size.** `verify_chain()` is O(n) and runs on
   every ledger page view; `checkpoint_service.leaf_hashes()` maintains an incremental cache whose
   *correctness* is well tested (`test_the_leaf_cache_is_extended_not_rebuilt`,
   `test_the_cache_produces_the_same_tree_as_a_cold_start`) but whose *performance* is never
   measured. This is the system's actual scaling wall and it is unquantified.
8. **Proof and bundle sizes are analytic, not empirical.** ADR-0015 states "17 of them, ~550 bytes,
   at 100,000 entries" — a calculation. The only empirical size assertion is
   `test_decision_bundle.py::test_the_bundle_is_a_reasonable_size` (`assert size < 200_000`), which
   is a bound, not a measurement.
9. **No concurrency measurement**, matching §3.3's testing gap. ADR-0008 declares this out of
   scope; a reviewer will still ask, and the code contains careful race handling that is
   consequently unvalidated.
10. **`elapsed_s: 3.54`** for the whole committed run. A reviewer will notice that a 50-iteration
    sweep of four algorithms completing in 3.5 seconds leaves little room for thermal effects — a
    point *in the project's favour* on stability, but it also means the run is far too cheap to
    justify not repeating it.

### 4.4 Other evaluation assets

- **CI as evidence.** `.github/workflows/ci.yml` — Windows + Ubuntu 24.04, Python 3.13, pinned
  lock file, ruff + black gating, `pytest --cov=qvault --cov-fail-under=88`, plus a PQC smoke run.
  A separate `mobile` job runs typecheck, the three cross-language contract test files, and a
  Metro/Hermes bundle check. `build-image.yml` builds a container whose Dockerfile self-checks
  ML-DSA sign+verify. This is genuinely good evidence of portability and should be a table.
- **Coverage.** CI floor 88%, comment says 92%. The committed `.coverage` shows 78% but is stale
  and partial — **regenerate before quoting** (§3.8).
- **Architectural conformance.** `test_module_boundaries.py` is a measurable architectural
  property, not a claim.

---

## 5. Gaps — what to add for a credible paper

Ordered by (value to the paper) ÷ (cost to produce).

**G1. Put the browser differential tests in CI.** *Cost: an hour.* Add `playwright` to
`requirements-dev.txt` (and the lock file) and a `playwright install chromium` step to
`ci.yml`. This converts the project's most distinctive claim (V3) from "true on one laptop" to
"continuously verified on two operating systems". **Highest value-to-cost ratio in this list.**

**G2. Regenerate the benchmark and fix the FIPS 205 text.** *Cost: an hour.* Run
`python scripts/run_benchmark.py --iterations 50`; correct `README.md` lines 13 and 67 and the
specification's six occurrences. Non-negotiable before submission (§3.1).

**G3. Add a classical baseline to the benchmark.** *Cost: half a day.* Register RSA-3072,
ECDSA P-256 and Ed25519 providers behind the existing `SignatureProvider` interface using the
already-pinned `cryptography` library, and an X25519 or ECDH KEM analogue. This does three things
at once: it supplies the missing migration-cost baseline; it **demonstrates that the agility
interface accepts a genuinely foreign implementation** (partially answering A8); and it produces
the paper's most quotable table. Note the classical providers must be excluded from
`DEVICE_ELIGIBLE_SIG_ALGS` and from the active-algorithm dropdown, or add a `post_quantum: bool`
to `AlgMeta` so `config_service` can refuse them as an active default — which is itself a nice
extension of the ADR-0012 downgrade logic.

**G4. Measure the agility mechanism itself.** *Cost: two hours.* Micro-benchmark
`registry.signature(alg_id).verify(...)` against a direct provider call, and measure the
per-artefact resolution overhead in `tally()`. Expected result: unmeasurable. **Report it** — "the
runtime cost of crypto-agility is below the noise floor; its cost is schema and discipline" is a
crisp, defensible finding and it fixes the mis-framing in §4.3(3).

**G5. Decompose the cost of one vote.** *Cost: half a day.* Instrument
`approval_service.cast_vote` end-to-end: Argon2id KEK derivation, AES-GCM unwrap, ML-DSA sign,
verify-after-sign, ledger append + hash, Merkle leaf extension, commit. The glass-box recorder
already times every step (`perf_counter_ns` in `recorder.py`) — the data may be almost free to
extract. Expected finding: **PQC is not the dominant cost; the password KDF is.** That reframes the
entire "is PQC too slow?" question honestly and replaces the repeatedly-cited ~80 ms estimate with
a measurement.

**G6. Measure scaling against log size.** *Cost: one day.* Seed logs of 10², 10³, 10⁴, 10⁵ entries
and measure: `verify_chain()` wall time; `maybe_checkpoint()` wall time cold vs cached;
inclusion-proof length and byte size; consistency-proof size; decision-bundle size; `/ledger` page
render time. This closes §4.3(7) and (8), validates ADR-0015's analytic "17 hashes ~550 bytes"
claim empirically, and produces the paper's best quantitative figure (F5). It will also probably
expose the real scaling limit, which is a *finding*, not a failure.

**G7. Add concurrency tests.** *Cost: one day.* N threads voting on one proposal (assert exactly
one `Signature` row and that the loser gets "already voted", not a 500); N threads appending to the
ledger (assert `UNIQUE(seq)` behaviour and that `verify_chain()` still passes); two simultaneous
`run_key_rotation()` calls. This directly attacks the largest untested area (§3.3) and either
validates the admitted deferred races or finds a real bug — both are publishable.

**G8. Repeat the benchmark for variance.** *Cost: a day, mostly waiting.* k ≥ 5 runs across
reboots, and if at all possible on a second machine (the CI Linux runner is free and already
present). Report medians with interquartile ranges or bootstrap CIs. Also run the pool = 8 vs
pool = 50 verify comparison (§4.3(4)) to close the acknowledged residual bias.

**G9. Regenerate coverage and report it honestly.** *Cost: 20 minutes.* Full-suite run with
`--cov=qvault --cov-report=term-missing`; report the real figure and name the least-covered
modules rather than a single headline number.

**G10. Extend the coverage gate beyond `qvault`.** *Cost: 20 minutes.* `pytest --cov=qvault`
excludes `witness/` and `scripts/` (§3.9), so the witness — a load-bearing security component with
40 tests — contributes to no reported coverage figure. Add `--cov=witness`; if a paper argues the
witness is what makes the transparency claim real, its coverage should be visible.
*(The former G10 — "write the missing glass-box ADR" — was completed during this audit: see §3.8.)*

**G11. Adversarial evaluation by someone else.** *Cost: variable; cheap if a peer or supervisor
will do it.* Every forgery in the suite was written by the person who wrote the verifier. Giving a
third party a genuine bundle and asking them to produce one that verifies falsely — a
capture-the-flag of one flag — would convert self-assessment into external evidence. Even a
negative result ("three people tried for two hours and failed") is materially stronger than the
current position, and it is the single cheapest way to strengthen the transparency claim.

**G12. Measure on-device signing.** *Cost: needs a handset.* ADR-0017 flags this explicitly as
open. Time seed → keygen → sign under Hermes on real hardware, and confirm the
`crypto.getRandomValues` polyfill ordering. Without it, the device-custody chapter has no numbers
at all.

**G13. Commit the key fingerprints out of band, before the evaluation.** *Cost: minutes; value:
disproportionate.* The witness already runs on separate Azure infrastructure (§3.5), so the
remaining gap is not infrastructure but **channel**: OWNER-ACTIONS §2.5 correctly observes that
publishing the fingerprint inside the repository the log ships from "is exactly the circularity it
exists to break". Put log `951dbf99653347de` and witness `c79ad5683b2e9109` somewhere the log does
not control — a slide, a printed handout, a timestamped post — **before** any demonstration or data
collection, then run the verifier with `--expect-log` / `--expect-witness` and show it passing.
This is what converts the entire witness argument from *mechanism* into *property*, and it is the
cheapest high-value item in this list after G1.

**G14. Basic hardening a reviewer will otherwise flag.** *Cost: an hour.* Set
`SESSION_COOKIE_SECURE`, `SESSION_COOKIE_HTTPONLY`, `SESSION_COOKIE_SAMESITE` in `ProdConfig`, and
add rate limiting to `/login`, `/devices/challenge` and `/devices`. ADR-0016 argues that fixing one
without the other "would be theatre" — fix both and the argument resolves. **Note this is not
merely hygiene: the specification currently claims rate limiting exists (§3.10), so either the
control or the claim has to change.**

**G15. Reconcile the specification with the ADRs, or declare the ADRs authoritative.** *Cost: two
hours.* Fix the four drifts in §3.10, and fix `pyproject.toml`'s "immutable audit ledger". A paper
whose own design record contradicts itself on non-repudiation, mobile scope and rate limiting
invites the reviewer to check everything else.

**G16. ~~Test the glass box.~~ Done during this audit** — ADR-0020 and 40 tests landed while the
report was being written (§3.8). Remaining: correct the filename in `source.py:10`, and decide
whether the glass box belongs in the paper at all. It is a demonstrability instrument, not a
security control; the honest place for it is a short subsection on making cryptography inspectable,
with `test_captured_source_matches_the_file_on_disk` cited as what stops the panel being
decoration — and with the PQClean-opacity limit stated in the same paragraph.

**G17. Choose a licence.** *Cost: minutes.* A paper presenting a reference implementation that is
"all rights reserved" is not offering a reference implementation.

---

## 6. Figures and tables

### From data that already exists

**T1 — Algorithm comparison.** Regenerated `latest.md`, with the SLH-DSA row honestly labelled and
`measured_sizes` shown alongside declared sizes. *Add classical baseline rows once G3 lands.*

**T2 — Verify-after-sign overhead.** ML-DSA-65 +37%, ML-DSA-87 +45%, SLH-DSA-SHAKE-256f +4.6%
(ADR-0010). **Promote this out of the ADR into the evaluation chapter.** The asymmetry is the
project's most interesting measured result: *the scheme that is slowest to sign pays the least,
proportionally, to be safe*, because hash-based signatures are expensive to produce and cheap to
check. One sentence of analysis, one small bar chart.

**T3 — Forgery / verdict matrix.** Rows: the eight forgery classes plus the parametrised
signed-field sweep. Columns: Python verifier verdict, browser verifier verdict, which check key
failed. Built directly from `tests/test_offline_verifier.py` and `tests/test_decision_bundle.py`.
This is the table that substantiates V3, and it is far more persuasive than prose.

**T4 — Threat model with evidence.** Take the STRIDE-lite table from spec §4.11 and **add a fourth
column: "pinned by"**, naming the test. A threat-model table where every row cites an executable
test is unusual and will read very well.

**T5 — Custody domains.** From ADR-0016: {user password key, device key, vault KEM key, SYSTEM
anchor key} × {wrapped under, server can sign?, unattended ops?, rotation path}. Four rows that
carry the whole custody argument.

**T6 — Claim → evidence → verdict.** A condensed version of §1, with the SOLID / PARTIAL /
ASPIRATIONAL column intact. **Including this table is itself a contribution** — it is the artefact
that demonstrates the paper is not overclaiming, and reviewers reward it.

**T7 — Portability evidence.** CI matrix: OS × Python × job (tests, lint, format, coverage floor,
PQC smoke, mobile typecheck, cross-language contract tests, bundle check, container self-check).

**F1 — The crypto-agile seam.** Services → `CryptoRegistry` → providers, with `AlgMeta` /
`alg_id` shown travelling with each artefact, and `test_module_boundaries.py` marked as the
mechanism that enforces the boundary. One box per layer; do not over-decorate.

**F2 — The layered evidence structure (the centrepiece).** A single vertical diagram:
proposal fields → canonical bytes (`DS_PROPOSAL`) → `payload_hash` → vote signature (`DS_VOTE`) →
ledger entry → `entry_hash` chain → Merkle leaf (`0x00 ‖ entry_hash`) → root → log checkpoint
signature (`QVAULT-CHECKPOINT-v1`) → witness co-signature (`QVAULT-WITNESS-v1`). Annotate each
layer with *the attack it stops and the one it does not*. This one figure carries most of the
paper's security argument.

**F3 — The truncation attack, two verdicts (the money figure).** Left: `verify_ledger() → ok=True,
chain_ok=True, anchor_covers_head=True` on a truncated log. Right: the witness's `shrank` violation
row, with the offered checkpoint kept verbatim. Straight out of
`test_a_truncated_ledger_is_caught_by_the_witness_and_by_nothing_else`. Caption it with ADR-0005's
original non-goal text and ADR-0015's retirement of it — the arc *is* the argument.

**F4 — Mixed-artefact correctness timeline.** A horizontal timeline: keys issued under ML-DSA-65 →
`algorithm_switched` → re-key → signatures under SLH-DSA → `key_rotation_run` → retire-but-retain,
with `verify_all_artefacts()["all_pass"] = True` shown at each step and artefacts colour-coded by
pinned `alg_id`. This is the visual proof of A2/A3/A4.

**F5 — Verifier agreement.** A small two-column strip: the Python `Report.checks` and the browser
`checks` array side by side for one genuine and one forged bundle, showing identical check keys and
identical verdicts.

### Requiring the cheap experiments above

**F6 — Cost decomposition of one vote** *(needs G5)*. A stacked bar: Argon2id derivation, AES-GCM
unwrap, ML-DSA sign, verify-after-sign, ledger append, Merkle extension, commit. Expected to show
the KDF dominating the PQC operations by an order of magnitude — the honest answer to "is
post-quantum too slow for this?".

**F7 — Scaling with log size** *(needs G6)*. Log-log axes, log size on x: `verify_chain()` time,
`maybe_checkpoint()` time (cold vs cached), inclusion-proof size in bytes, bundle size. Overlay the
analytic `ceil(log2 n)` curve on the measured proof size to show the implementation matches theory.

**F8 — PQC vs classical, matched security** *(needs G3)*. Grouped bars, log-scaled y: sign, verify
and signature size for RSA-3072 / ECDSA P-256 / Ed25519 / ML-DSA-65 / ML-DSA-87 /
SPHINCS+-SHAKE-256f. This is the figure that makes the migration-cost argument, and the project
currently cannot draw it.

**T8 — Agility mechanism overhead** *(needs G4)*. Registry dispatch vs direct call, in nanoseconds,
next to the millisecond signature cost. A table whose entire point is that the number is
negligible.

---

## 7. One-paragraph summary for the paper's contributions section

> This paper reports the design, implementation and evaluation of Q-Vault, a crypto-agile
> post-quantum multi-signature vault. We make four contributions. First, we report a measured
> interoperability defect: a widely-installed Python PQC library labels PQClean's SPHINCS+ round-3
> submission as SLH-DSA/FIPS 205, producing signatures that a conforming FIPS 205 implementation
> rejects at *identical* key and signature sizes — so parameter shape is not a compatibility
> oracle, and we describe the cross-implementation admission gate this forced. Second, we describe
> a methodology for establishing that a decision-record format is independently verifiable, using
> two implementations in different languages required to agree not only on genuine artefacts but
> on eight classes of forgery and on which check fails. Third, we give an executable demonstration
> of the limits of self-verification: our own ledger verification reports a truncated log as
> healthy, and only an external witness holding state outside the database detects it. Fourth, we
> report an integration study of crypto-agility, in which the active signature algorithm is
> switched at runtime and keys rotated while a mixed-algorithm corpus of historical artefacts
> continues to verify. We are explicit about scope: agility is demonstrated across three signature
> algorithms served by one backend; backend and KEM agility remain structural properties of the
> interface rather than demonstrated capabilities.

---

## Appendix A — Sources consulted

`README.md` · `config.py` · `conftest.py` · `pyproject.toml` · `requirements*.txt` ·
`.github/workflows/{ci,build-image}.yml` · `docs/adr/0001`–`0019` (all 19) ·
`docs/PROJECT-SPECIFICATION-AND-PLAN.md` (§4.11 threat model, §5 data model) ·
`docs/benchmarks/{latest.json,latest.md}` · `qvault/crypto/{registry,interfaces,bootstrap,kdf}.py` ·
`qvault/crypto/providers/quantcrypt_signature.py` ·
`qvault/services/{approval,ledger,checkpoint,key,benchmark,signing,publication,receipt}*.py` ·
`qvault/transparency/merkle.py` · `qvault/verify/core.py` · `qvault/scheduler.py` ·
`qvault/glassbox/recorder.py` · `qvault/security/demo_gate.py` · `witness/{app,store,README}` ·
`scripts/run_benchmark.py` · and the test suite (42 files, 794 collected cases), read for
assertions rather than for names.
