"""Crypto-agility configuration service (Phase 6).

The runtime "switch algorithm" control mutates exactly one value — ``AlgorithmConfig``'s
``active_signature_alg`` — which selects the algorithm for *future* keys only. Every existing
key, signature, and anchor records its own ``alg_id`` and is always verified by the matching
provider, so a switch can never invalidate stored data. ``verify_all_artefacts`` demonstrates
exactly that: after a switch, all pre-existing signatures still verify under their pinned
algorithms.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from flask import current_app
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from qvault.extensions import db
from qvault.models.anchor import LedgerAnchor
from qvault.models.config_models import AlgorithmConfig
from qvault.models.key import Key
from qvault.models.signature import Signature
from qvault.services import approval_service, ledger_service


class ConfigError(ValueError):
    """Raised for an invalid configuration change (e.g. an unregistered algorithm)."""


class DowngradeRefused(ConfigError):
    """Raised when a switch would lower the security category without explicit authorisation."""


def security_category(alg_id: str) -> int:
    """The NIST security category of a registered signature algorithm."""
    return current_app.extensions["crypto"].signature(alg_id).meta.security_category


def set_active_signature_algorithm(
    alg_id: str,
    *,
    actor_id: int,
    allow_downgrade: bool = False,
    reason: str | None = None,
    commit: bool = True,
):
    """Switch the active signature algorithm used for NEW keys. Idempotent for a no-op change.

    **Agility is not neutral about direction.** The lesson of a decade of TLS downgrade attacks is
    that a mechanism able to negotiate *to* a weaker option is a mechanism an attacker will use to
    do exactly that. This system's switch is admin-only, but "admin-only" is not an argument — a
    compromised or careless administrator moving the default from category 5 to category 3 would,
    before this check existed, produce a ledger event indistinguishable from an upgrade.

    So a decrease in NIST security category is **refused** unless the caller explicitly passes
    ``allow_downgrade=True`` with a non-empty ``reason``, and it is recorded as a distinct
    ``algorithm_downgraded`` event carrying both categories and the stated reason. An auditor
    reading the ledger can then find every weakening decision by event type alone, rather than by
    knowing which algorithm ids happen to be stronger.

    Note the scope: this governs *new* keys. Artefacts already signed under a stronger algorithm
    keep their own ``alg_id`` and are unaffected — a downgrade cannot retroactively weaken history.
    """
    registry = current_app.extensions["crypto"]
    if not registry.has_signature(alg_id):
        raise ConfigError(f"{alg_id!r} is not a registered signature algorithm.")

    cfg = AlgorithmConfig.current()
    previous = cfg.active_signature_alg
    if alg_id == previous:
        return cfg  # no-op: nothing to record

    from_cat = security_category(previous)
    to_cat = security_category(alg_id)
    is_downgrade = to_cat < from_cat

    if is_downgrade:
        if not allow_downgrade:
            raise DowngradeRefused(
                f"Switching from {previous} (category {from_cat}) to {alg_id} "
                f"(category {to_cat}) lowers the security category. Confirm the downgrade "
                "explicitly and state a reason if this is intended."
            )
        if not (reason or "").strip():
            raise DowngradeRefused("A downgrade must be accompanied by a stated reason.")

    cfg.active_signature_alg = alg_id
    cfg.updated_by = actor_id
    cfg.updated_at = datetime.now(UTC)

    payload = {"kind": "signature", "from": previous, "to": alg_id}
    if is_downgrade:
        payload |= {"from_category": from_cat, "to_category": to_cat, "reason": reason.strip()}

    ledger_service.append(
        "algorithm_downgraded" if is_downgrade else "algorithm_switched",
        payload,
        actor=f"user:{actor_id}",
        actor_id=actor_id,
        ref_type="config",
        ref_id="active_signature_alg",
        commit=False,
    )
    if commit:
        db.session.commit()
    return cfg


def signing_keys_by_algorithm() -> dict[str, int]:
    """Count active USER signing keys grouped by algorithm — shows the live algorithm mix.

    The owner-less SYSTEM anchor key is excluded (it is not a user identity and is unaffected by a
    signature switch). Device-custodied keys are excluded too: this figure answers "what will the
    switch affect?", and a device key is enrolled at a fixed algorithm the server cannot re-issue,
    so counting a user's phone alongside their password key would double-count one identity.
    """
    rows = (
        db.session.query(Key.alg_id, func.count(Key.id))
        .filter(
            Key.role == "sig",
            Key.status == "active",
            Key.owner_id.isnot(None),
            Key.wrap_domain == "password",
        )
        .group_by(Key.alg_id)
        .all()
    )
    return {alg_id: count for alg_id, count in rows}


def verify_all_artefacts(*, detail: bool = False) -> dict:
    """Verify every stored signature (votes) and ledger anchor under its OWN pinned algorithm.

    This is the crypto-agility proof: the returned counts are all-pass even across a mixed set of
    algorithms and after the active algorithm has been switched. ``by_alg`` breaks the totals down
    per algorithm for display.

    ``elapsed_ms`` is the wall-clock time spent inside the verification calls themselves — the
    database round-trips that fetch the rows are deliberately excluded, so the interface can state
    "N verifications in X ms" without that being a half-truth about where the time went.

    ``detail=True`` additionally returns ``artefacts``: one record per artefact, oldest first, each
    naming what it is in ordinary words, which algorithm it is pinned to, and whether the key that
    verifies it is still active or has been retired. Two things need that list. An inventory view
    cannot show heterogeneity without per-artefact algorithms; and ``key_status`` is the only place
    retire-but-retain becomes visible — a signature verifying against a *retired* key is the proof
    that replacing a key does not invalidate what it already signed. It is off by default because
    it costs an extra eager-load that the plain counters do not need.
    """
    by_alg: dict[str, dict[str, int]] = {}
    artefacts: list[dict] = []
    ok = 0
    total = 0
    elapsed_ns = 0

    def _tally(alg_id: str, passed: bool) -> None:
        nonlocal ok, total
        total += 1
        ok += 1 if passed else 0
        bucket = by_alg.setdefault(alg_id, {"ok": 0, "total": 0})
        bucket["total"] += 1
        bucket["ok"] += 1 if passed else 0

    sig_q = Signature.query
    anchor_q = LedgerAnchor.query
    if detail:
        sig_q = sig_q.options(
            joinedload(Signature.signer), joinedload(Signature.proposal), joinedload(Signature.key)
        )
        anchor_q = anchor_q.options(joinedload(LedgerAnchor.key))

    for sig in sig_q.all():
        t0 = time.perf_counter_ns()
        passed = approval_service.verify_signature(sig, sig.proposal)
        elapsed_ns += time.perf_counter_ns() - t0
        _tally(sig.alg_id, passed)
        if detail:
            artefacts.append(
                {
                    "kind": "signature",
                    "alg_id": sig.alg_id,
                    "backend": sig.backend,
                    "verified": passed,
                    "size_bytes": len(sig.signature),
                    "created_at": sig.created_at,
                    "who": (sig.signer.display_name or sig.signer.email) if sig.signer else "someone",
                    "what": sig.proposal.title if sig.proposal else "a decision",
                    "action": "approved" if sig.decision == "approve" else "rejected",
                    "key_status": sig.key.status if sig.key else "unknown",
                    "fingerprint": sig.fingerprint(),
                }
            )

    for anchor in anchor_q.all():
        t0 = time.perf_counter_ns()
        passed = ledger_service.verify_anchor(anchor)
        elapsed_ns += time.perf_counter_ns() - t0
        _tally(anchor.alg_id, passed)
        if detail:
            artefacts.append(
                {
                    "kind": "seal",
                    "alg_id": anchor.alg_id,
                    "backend": anchor.backend,
                    "verified": passed,
                    "size_bytes": len(anchor.signature),
                    "created_at": anchor.created_at,
                    "who": "The system",
                    "what": f"the record up to entry #{anchor.seq}",
                    "action": "sealed",
                    "key_status": anchor.key.status if anchor.key else "unknown",
                    "fingerprint": anchor.fingerprint(),
                }
            )

    report = {
        "ok": ok,
        "total": total,
        "all_pass": ok == total,
        "by_alg": by_alg,
        "elapsed_ms": round(elapsed_ns / 1e6, 2),
    }
    if detail:
        # Oldest first: in a system that has switched algorithms, chronological order is what
        # makes the change legible — the pinned algorithm visibly changes partway down the list.
        report["artefacts"] = sorted(
            artefacts, key=lambda a: (a["created_at"] is None, a["created_at"])
        )
    return report
