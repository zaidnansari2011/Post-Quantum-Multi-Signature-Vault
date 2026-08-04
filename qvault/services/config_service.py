"""Crypto-agility configuration service (Phase 6).

The runtime "switch algorithm" control mutates exactly one value — ``AlgorithmConfig``'s
``active_signature_alg`` — which selects the algorithm for *future* keys only. Every existing
key, signature, and anchor records its own ``alg_id`` and is always verified by the matching
provider, so a switch can never invalidate stored data. ``verify_all_artefacts`` demonstrates
exactly that: after a switch, all pre-existing signatures still verify under their pinned
algorithms.
"""

from __future__ import annotations

from datetime import UTC, datetime

from flask import current_app
from sqlalchemy import func

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
    signature switch).
    """
    rows = (
        db.session.query(Key.alg_id, func.count(Key.id))
        .filter(Key.role == "sig", Key.status == "active", Key.owner_id.isnot(None))
        .group_by(Key.alg_id)
        .all()
    )
    return {alg_id: count for alg_id, count in rows}


def verify_all_artefacts() -> dict:
    """Verify every stored signature (votes) and ledger anchor under its OWN pinned algorithm.

    This is the crypto-agility proof: the returned counts are all-pass even across a mixed set of
    algorithms and after the active algorithm has been switched. ``by_alg`` breaks the totals down
    per algorithm for display.
    """
    by_alg: dict[str, dict[str, int]] = {}
    ok = 0
    total = 0

    def _tally(alg_id: str, passed: bool) -> None:
        nonlocal ok, total
        total += 1
        ok += 1 if passed else 0
        bucket = by_alg.setdefault(alg_id, {"ok": 0, "total": 0})
        bucket["total"] += 1
        bucket["ok"] += 1 if passed else 0

    for sig in Signature.query.all():
        _tally(sig.alg_id, approval_service.verify_signature(sig, sig.proposal))
    for anchor in LedgerAnchor.query.all():
        _tally(anchor.alg_id, ledger_service.verify_anchor(anchor))

    return {"ok": ok, "total": total, "all_pass": ok == total, "by_alg": by_alg}
