# ADR-0012 — Agility has a direction

- **Status:** Accepted
- **Date:** 2026-08-04
- **Extends:** [ADR-0006](0006-runtime-algorithm-switch.md)

## Context

[ADR-0006](0006-runtime-algorithm-switch.md) made the active signature algorithm switchable at
runtime. That is the project's headline capability, and it was implemented as a symmetric
operation: any registered algorithm could replace any other, recording an `algorithm_switched`
ledger event that looked identical whichever way the change went.

The problem is that **agility and downgrade are the same mechanism viewed from opposite ends.** The
history of TLS is largely the history of that observation: a protocol able to negotiate down to a
weaker option is a protocol an attacker will make negotiate down. SSL 3.0 fallback, FREAK, Logjam
and POODLE are all, structurally, the same bug — flexibility with no floor.

Q-Vault's switch is `admin_required`, which is a meaningful control but not an argument. It assumes
the administrator is both uncompromised and attentive. Before this ADR, an administrator moving the
default from ML-DSA-87 (category 5) to ML-DSA-65 (category 3) — whether attacked, mistaken, or
simply clicking through a dropdown — produced an audit record indistinguishable from an upgrade. An
auditor could only spot it by already knowing which `alg_id` outranks which.

This is precisely the question an examiner who knows anything about crypto agility will ask, and it
was a genuine hole in the feature the project calls its star.

## Decision

A switch that **lowers the NIST security category** is refused unless it is explicitly authorised,
and it is recorded as a **different kind of event**.

- `config_service.set_active_signature_algorithm` reads `security_category` from the registry
  metadata — never a hardcoded ranking — and compares the outgoing and incoming algorithms.
- A decrease raises `DowngradeRefused` unless the caller passes `allow_downgrade=True` **and** a
  non-empty `reason`. Whitespace is not a reason.
- An authorised downgrade appends `algorithm_downgraded` (not `algorithm_switched`) carrying
  `from_category`, `to_category` and the stated reason. **An auditor can now find every weakening
  decision by event type alone**, without knowing the relative strength of any algorithm id.
- Consent is per call. A confirmed downgrade does not leave the door open for the next one.
- The admin form requires a distinct tick and a typed reason, styled as a warning. That is a prompt
  for deliberation, not the control — the service refuses regardless of what the form sends.
- An equal-category move is **not** a downgrade. Switching ML-DSA-87 → SLH-DSA-SHAKE-256f (both
  category 5) is assumption diversity — trading a lattice assumption for a hash-based one — and
  should stay frictionless, because it is exactly the migration this project exists to make easy.

## Consequences

- The strongest version of the agility claim is now defensible: the system can move between
  algorithms freely, but moving *down* is a deliberate, separately-recorded act.
- **Scope, and why it is enough.** This governs new keys only. Artefacts signed under a stronger
  algorithm keep their own `alg_id` and continue to verify under it, so a downgrade cannot
  retroactively weaken history — a test asserts exactly that, since it is the property that makes
  the whole design safe.
- Categories come from `AlgMeta`, so registering a future algorithm (FN-DSA, HQC) gets downgrade
  protection with no changes here — provided its metadata states a category honestly.
- **Deliberately not built: a per-vault floor.** Letting a vault demand "category 5 signatures
  only" sounds attractive, but enforcing it at vote time would require snapshotting the floor into
  the signing payload, or reintroducing exactly the mutable-policy problem that
  `authorized_signers_snapshot` already solves. The natural extension is noted; it is not worth
  reopening a solved problem for a demo feature.
- **Honest limitation:** an attacker with direct database write access can edit
  `algorithm_config.active_signature_alg` and bypass this entirely. That adversary is out of scope
  here for the same reason as elsewhere — they are the ledger's problem, not the form's — but the
  resulting `Key` rows would carry the weaker `alg_id` visibly, and no corresponding
  `algorithm_downgraded` entry would exist to explain them. The discrepancy is detectable; nothing
  currently alerts on it.
