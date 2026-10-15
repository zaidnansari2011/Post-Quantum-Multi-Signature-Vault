"""Automated key rotation and proposal expiry (Phase 7).

Rotation is **retire-but-retain**: a rotated key is marked ``status='retired'`` (and ``can_sign``
cleared) but kept, with ``can_verify`` intact, so every artefact it ever produced still verifies /
decrypts. What can be rotated *unattended* is bounded by custody (see ADR-0004):

* **Server-custodied keys** — the SYSTEM ledger-anchor key and each vault's KEM key are wrapped
  under the server master key, so the scheduler can rotate them with no human present.
* **User signing keys** — wrapped under a password-derived KEK, so they CANNOT be rotated
  unattended (no password at 03:00). The job only *flags* them as due; the user re-keys
  interactively (``key_service.reissue_signing_key``).

Both scheduled jobs (`run_key_rotation`, `expire_stale_proposals`) are plain functions so they can
be driven directly by a test or an admin "run now" button, independent of the scheduler.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from flask import current_app

from qvault.extensions import db
from qvault.models.key import Key
from qvault.models.proposal import Proposal
from qvault.models.vault import Vault
from qvault.security import master_key
from qvault.services import approval_service, ledger_service
from qvault.services.rotation_policy import rotation_deadline


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


# -- discovery ---------------------------------------------------------------------------------


def active_system_key() -> Key | None:
    # role + wrap_domain + owner_id together identify the one SYSTEM anchor key. The wrap_domain
    # term also excludes device-custodied keys (Phase 1), which the server cannot sign with.
    return Key.query.filter_by(
        role="sig", wrap_domain="master", owner_id=None, status="active"
    ).first()


def due_user_signing_keys(now: datetime | None = None) -> list[Key]:
    """Active user signing keys past their rotation deadline (rotated interactively, not here).

    Password-custodied only. A device key's private half never leaves the signer's phone, so the
    server cannot re-issue it and must not advertise it as due — the "Replace key" prompt would
    be an instruction the user has no way to carry out. Device custody is time-bounded on the
    *token* instead (``DEVICE_TOKEN_MAX_AGE_DAYS``): the server cannot rotate a key it does not
    hold, but it can stop accepting a device that has not re-authenticated. See ADR-0016.
    """
    now = _now(now)
    return [
        k
        for k in Key.query.filter_by(role="sig", status="active").all()
        if k.owner_id is not None
        and k.wrap_domain == "password"
        and k.rotate_after is not None
        and k.rotate_after < now
    ]


def demo_expire_keys(*, actor: str = "SYSTEM", actor_id: int | None = None) -> int:
    """Dev-only: bring every active key's rotation deadline forward so it is due right now.

    Rotation is genuinely time-driven — ``KEY_MAX_AGE_DAYS`` defaults to 90 — so on a database
    created minutes ago there is correctly nothing to rotate, and "Run rotation now" reports doing
    nothing. That is right, and it is also unwatchable: automated key rotation is a third of this
    project's title and demonstrating it should not require waiting a quarter of a year.

    This moves the *deadlines*, never the keys, and appends a ``demo_keys_expired`` ledger event
    so the audit trail records that the clock was moved rather than quietly appearing to age. The
    rotation that follows is the real code path, unmodified.

    Callers MUST gate on ``qvault.security.demo_gate.demo_enabled`` — as with the ledger and
    proposal demonstrations, the gate lives at the route so there is exactly one of it.
    """
    yesterday = datetime.now(UTC) - timedelta(days=1)
    # Device keys are excluded explicitly, not merely by their NULL rotate_after: this function
    # writes a deadline onto every active key it selects, so without the filter it would
    # manufacture a "due" row that nothing can action — in front of an examiner.
    keys = Key.query.filter_by(status="active").filter(Key.wrap_domain != "device").all()
    for key in keys:
        key.rotate_after = yesterday

    ledger_service.append(
        "demo_keys_expired",
        {"keys_affected": len(keys), "rotate_after": yesterday.isoformat()},
        actor=actor,
        actor_id=actor_id,
        commit=False,
    )
    db.session.commit()
    return len(keys)


def _is_due(key: Key | None, now: datetime) -> bool:
    return key is not None and key.rotate_after is not None and key.rotate_after < now


# -- server-custodied rotation (unattended) ----------------------------------------------------


def rotate_system_key(*, actor: str = "SYSTEM", actor_id: int | None = None, commit: bool = True):
    """Retire the current SYSTEM anchor key and issue a fresh one; old anchors still verify."""
    old = active_system_key()
    old_id = old.id if old is not None else None
    if old is not None:
        old.status = "retired"
        old.can_sign = False
        old.retired_at = datetime.now(UTC)  # can_verify stays True: old anchors remain verifiable
        db.session.flush()  # ensure the retirement is visible before ensure_system_key's query

    new = ledger_service.ensure_system_key()  # creates a fresh active SYSTEM key (none active now)
    ledger_service.append(
        "system_key_rotated",
        {"old_key_id": old_id, "new_key_id": new.id, "alg_id": new.alg_id},
        actor=actor,
        actor_id=actor_id,
        ref_type="key",
        ref_id=str(new.id),
        commit=False,
    )
    if commit:
        db.session.commit()
    return new


def rotate_vault_key(
    vault: Vault, *, actor: str = "SYSTEM", actor_id: int | None = None, commit: bool = True
) -> Key:
    """Issue a fresh KEM key for ``vault``; the old key is retained so old files still decrypt."""
    old = db.session.get(Key, vault.kem_key_id)
    registry = current_app.extensions["crypto"]
    kem_alg = vault.kem_alg_id  # keep the KEM algorithm; only the key material rotates
    kem = registry.kem(kem_alg)
    keypair = kem.keygen()
    nonce, wrapped = master_key.wrap_secret(keypair.secret_key)

    new = Key(
        owner_id=vault.owner_id,
        role="kem",
        alg_id=kem_alg,
        backend=kem.meta.backend,
        public_key=keypair.public_key,
        secret_key_wrapped=wrapped,
        secret_key_nonce=nonce,
        wrap_domain="master",
        status="active",
        can_sign=False,
        can_verify=False,
        version=(old.version + 1) if old is not None else 1,
        rotate_after=rotation_deadline(),
    )
    db.session.add(new)
    db.session.flush()  # assign new.id

    if old is not None:
        old.status = "retired"
        old.retired_at = datetime.now(UTC)  # retained: files pinned to it (VaultFile.kem_key_id)

    vault.kem_key_id = new.id
    vault.kem_public_key = keypair.public_key
    vault.kem_alg_id = kem_alg

    ledger_service.append(
        "vault_key_rotated",
        {"vault_id": vault.id, "old_key_id": old.id if old else None, "new_key_id": new.id},
        actor=actor,
        actor_id=actor_id,
        vault_id=vault.id,
        ref_type="vault",
        ref_id=str(vault.id),
        commit=False,
    )
    if commit:
        db.session.commit()
    return new


# -- the scheduled jobs ------------------------------------------------------------------------


def run_key_rotation(
    *,
    now: datetime | None = None,
    actor: str = "SYSTEM",
    actor_id: int | None = None,
    commit: bool = True,
) -> dict:
    """Rotate every due server-custodied key and flag due user keys. Returns a summary."""
    now = _now(now)
    summary = {"system_rotated": False, "vaults_rotated": [], "user_keys_due": []}

    if _is_due(active_system_key(), now):
        rotate_system_key(actor=actor, actor_id=actor_id, commit=False)
        summary["system_rotated"] = True

    for vault in Vault.query.all():
        if _is_due(db.session.get(Key, vault.kem_key_id), now):
            rotate_vault_key(vault, actor=actor, actor_id=actor_id, commit=False)
            summary["vaults_rotated"].append(vault.id)

    summary["user_keys_due"] = [k.id for k in due_user_signing_keys(now)]

    # Log + re-anchor only when a key actually rotated. A user key merely staying overdue is not a
    # state change, so it must not append a fresh event on every scheduled run (ledger noise).
    if summary["system_rotated"] or summary["vaults_rotated"]:
        ledger_service.append(
            "key_rotation_run",
            {
                "system_rotated": summary["system_rotated"],
                "vaults_rotated": summary["vaults_rotated"],
                "user_keys_due": summary["user_keys_due"],
            },
            actor=actor,
            actor_id=actor_id,
            ref_type="maintenance",
            ref_id="key_rotation",
            commit=False,
        )
        ledger_service.maybe_anchor(commit=False)  # re-anchor the advanced head with the new key

    if commit:
        db.session.commit()
    return summary


def expire_stale_proposals(*, now: datetime | None = None, commit: bool = True) -> int:
    """Expire every OPEN proposal whose deadline has passed. Returns the number expired.

    Replaces the reliance on Phase-4's read-time lazy expiry, so a proposal expires on schedule
    even if nobody opens it.
    """
    now = _now(now)
    stale = Proposal.query.filter(
        Proposal.status == "open",
        Proposal.expires_at.isnot(None),
        Proposal.expires_at < now,
    ).all()
    expired = 0
    for proposal in stale:
        if approval_service.refresh_expiry(proposal, now=now, commit=False):
            expired += 1

    if expired:
        ledger_service.maybe_anchor(commit=False)
    if commit:
        db.session.commit()
    return expired
