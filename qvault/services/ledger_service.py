"""Append-only, hash-chained audit ledger — the single canonical hashing rule (spec §4.6).

Every security-relevant event is appended here. Each entry's hash covers its ordered fields
plus the previous entry's hash, under a domain-separation tag, so any edit to a past entry is
detectable by ``verify_chain``.

Phase 2 provides genesis, append, and verification. Phase 5 adds the SYSTEM-signed head anchor
(defence against a full forward-rewrite by a DB-write adversary) and the tamper demonstration.
"""

from __future__ import annotations

from datetime import UTC, datetime

from flask import current_app

from qvault.crypto import canonical_json, sha256_hex
from qvault.extensions import db
from qvault.models.anchor import LedgerAnchor
from qvault.models.config_models import AlgorithmConfig
from qvault.models.key import Key
from qvault.models.ledger import LedgerEntry
from qvault.security import master_key

ENTRY_DS = b"QVAULT-LEDGER-v1|"
GENESIS_PREV_HEX = sha256_hex(b"QVAULT-LEDGER-GENESIS-v1")

# Domain-separated preimage for a SYSTEM head-anchor signature (distinct from the entry hash).
ANCHOR_DS = b"QVAULT-LEDGER-ANCHOR-v1|"


class LedgerError(RuntimeError):
    """Raised for invalid ledger operations (e.g. a tamper-demo target that does not exist)."""


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def compute_entry_hash(
    *,
    seq: int,
    timestamp: str,
    actor: str,
    event_type: str,
    payload_hash: str,
    prev_hash: str,
    actor_id: int | None = None,
    vault_id: int | None = None,
    ref_type: str | None = None,
    ref_id: str | None = None,
) -> str:
    """The one canonical entry-hash computation. Covers EVERY persisted, security-relevant
    field (not only the six core ones) so that the routing metadata — actor_id, vault_id,
    ref_type, ref_id — is authenticated too and cannot be silently altered in the database.
    ``canonical_json`` sorts keys, so the literal order below does not affect the digest.
    """
    preimage = ENTRY_DS + canonical_json(
        {
            "seq": seq,
            "timestamp": timestamp,
            "actor": actor,
            "actor_id": actor_id,
            "event_type": event_type,
            "vault_id": vault_id,
            "ref_type": ref_type,
            "ref_id": ref_id,
            "payload_hash": payload_hash,
            "prev_hash": prev_hash,
        }
    )
    return sha256_hex(preimage)


def _last_entry() -> LedgerEntry | None:
    return LedgerEntry.query.order_by(LedgerEntry.seq.desc()).first()


def ensure_genesis(*, commit: bool = True) -> LedgerEntry:
    """Create the seq=0 genesis entry if the ledger is empty. Idempotent."""
    existing = LedgerEntry.query.filter_by(seq=0).first()
    if existing is not None:
        return existing

    payload = {"note": "QVAULT ledger genesis"}
    payload_bytes = canonical_json(payload)
    payload_hash = sha256_hex(payload_bytes)
    timestamp = _utcnow_iso()
    entry_hash = compute_entry_hash(
        seq=0,
        timestamp=timestamp,
        actor="SYSTEM",
        event_type="genesis",
        payload_hash=payload_hash,
        prev_hash=GENESIS_PREV_HEX,
    )
    entry = LedgerEntry(
        seq=0,
        timestamp=timestamp,
        event_type="genesis",
        actor="SYSTEM",
        actor_id=None,
        payload_json=payload_bytes.decode("utf-8"),
        payload_hash=payload_hash,
        prev_hash=GENESIS_PREV_HEX,
        entry_hash=entry_hash,
    )
    db.session.add(entry)
    if commit:
        db.session.commit()
    return entry


def append(
    event_type: str,
    payload: dict,
    *,
    actor: str = "SYSTEM",
    actor_id: int | None = None,
    vault_id: int | None = None,
    ref_type: str | None = None,
    ref_id: str | None = None,
    commit: bool = True,
) -> LedgerEntry:
    """Append an event to the ledger, linking it to the current chain head."""
    last = _last_entry()
    if last is None:
        last = ensure_genesis(commit=False)

    seq = last.seq + 1
    prev_hash = last.entry_hash
    timestamp = _utcnow_iso()
    payload_bytes = canonical_json(payload)
    payload_hash = sha256_hex(payload_bytes)
    entry_hash = compute_entry_hash(
        seq=seq,
        timestamp=timestamp,
        actor=actor,
        event_type=event_type,
        payload_hash=payload_hash,
        prev_hash=prev_hash,
        actor_id=actor_id,
        vault_id=vault_id,
        ref_type=ref_type,
        ref_id=ref_id,
    )
    entry = LedgerEntry(
        seq=seq,
        timestamp=timestamp,
        event_type=event_type,
        actor=actor,
        actor_id=actor_id,
        vault_id=vault_id,
        ref_type=ref_type,
        ref_id=ref_id,
        payload_json=payload_bytes.decode("utf-8"),
        payload_hash=payload_hash,
        prev_hash=prev_hash,
        entry_hash=entry_hash,
    )
    db.session.add(entry)
    if commit:
        db.session.commit()
    return entry


def verify_chain() -> tuple[bool, int | None]:
    """Recompute the whole chain. Return ``(True, None)`` if intact, else ``(False, seq)`` of
    the first broken entry.
    """
    entries = LedgerEntry.query.order_by(LedgerEntry.seq.asc()).all()
    expected_prev = GENESIS_PREV_HEX
    for e in entries:
        if e.prev_hash != expected_prev:
            return False, e.seq
        recomputed = compute_entry_hash(
            seq=e.seq,
            timestamp=e.timestamp,
            actor=e.actor,
            event_type=e.event_type,
            payload_hash=e.payload_hash,
            prev_hash=e.prev_hash,
            actor_id=e.actor_id,
            vault_id=e.vault_id,
            ref_type=e.ref_type,
            ref_id=e.ref_id,
        )
        if recomputed != e.entry_hash:
            return False, e.seq
        # payload integrity: the stored payload must still hash to payload_hash
        if sha256_hex(e.payload_json.encode("utf-8")) != e.payload_hash:
            return False, e.seq
        expected_prev = e.entry_hash
    return True, None


# --------------------------------------------------------------------------------------------
# SYSTEM head anchor (specification §4.6): a signature over the ledger head that the chain alone
# cannot provide. Defends against a full, internally-consistent forward-rewrite.
# --------------------------------------------------------------------------------------------


def ensure_system_key() -> Key:
    """Return the SYSTEM ledger-anchor signing key, creating it (once) if absent.

    It is an ordinary signing ``Key`` with no human owner, wrapped under the server master key so
    it can sign unattended. Uniquely identified by ``role='sig'`` + ``wrap_domain='master'`` +
    ``owner_id IS NULL`` (vault KEM keys are master-wrapped too, but have ``role='kem'``).
    """
    key = Key.query.filter_by(
        role="sig", wrap_domain="master", owner_id=None, status="active"
    ).first()
    if key is not None:
        return key

    registry = current_app.extensions["crypto"]
    alg_id = AlgorithmConfig.current().active_signature_alg
    provider = registry.signature(alg_id)
    keypair = provider.keygen()
    nonce, wrapped = master_key.wrap_secret(keypair.secret_key)

    key = Key(
        owner_id=None,
        role="sig",
        alg_id=alg_id,
        backend=provider.meta.backend,
        public_key=keypair.public_key,
        # Bind the public key to the master trust root so a DB-injected substitute is rejected.
        public_key_mac=master_key.mac(keypair.public_key),
        secret_key_wrapped=wrapped,
        secret_key_nonce=nonce,
        wrap_domain="master",
        status="active",
        can_sign=True,
        can_verify=True,
        version=1,
    )
    db.session.add(key)
    db.session.flush()
    return key


def _anchor_message(seq: int, head_hash: str) -> bytes:
    return ANCHOR_DS + canonical_json({"seq": seq, "head_hash": head_hash})


def latest_anchor() -> LedgerAnchor | None:
    return LedgerAnchor.query.order_by(LedgerAnchor.seq.desc(), LedgerAnchor.id.desc()).first()


def anchor_head(*, commit: bool = True) -> LedgerAnchor:
    """Sign the current ledger head with the SYSTEM key and store an append-only anchor."""
    head = _last_entry() or ensure_genesis(commit=False)
    key = ensure_system_key()

    secret = master_key.unwrap_secret(key.secret_key_nonce, key.secret_key_wrapped)
    try:
        signature = (
            current_app.extensions["crypto"]
            .signature(key.alg_id)
            .sign(secret, _anchor_message(head.seq, head.entry_hash))
        )
    finally:
        del secret  # best-effort; drop the plaintext key reference promptly

    anchor = LedgerAnchor(
        seq=head.seq,
        head_hash=head.entry_hash,
        alg_id=key.alg_id,
        backend=key.backend,
        key_id=key.id,
        signature=signature,
    )
    db.session.add(anchor)
    if commit:
        db.session.commit()
    return anchor


def maybe_anchor(*, commit: bool = True) -> LedgerAnchor | None:
    """Anchor the head only when NEW entries have been appended since the last anchor.

    Two conditions gate a re-anchor, and both are essential to keep tampering detectable:

    * A change at the *same* seq (same entry count, different hash) is exactly a rewrite, so it
      must NOT trigger a re-anchor.
    * Even when the seq advances, we refuse to extend the anchor lineage if the previously-anchored
      point no longer matches the live chain — otherwise appending a genuine new entry over a
      rewritten history would produce a fresh, valid anchor that blesses the tamper.
    """
    head = _last_entry()
    if head is None:
        return None
    last = latest_anchor()
    if last is not None:
        if last.seq >= head.seq:
            return None
        anchored = LedgerEntry.query.filter_by(seq=last.seq).first()
        if anchored is None or anchored.entry_hash != last.head_hash:
            return None  # the anchored history was mutated; do not sign over it
    return anchor_head(commit=commit)


def verify_anchor(anchor: LedgerAnchor) -> bool:
    """Verify a head anchor: it must be signed by the authentic SYSTEM key and be valid.

    The verification key is taken from the anchor's pinned ``key_id`` but is only trusted after its
    public key is confirmed against the master-key MAC — so a DB-write adversary cannot substitute
    their own keypair (they cannot forge the MAC without the server master key).
    """
    key = db.session.get(Key, anchor.key_id)
    if key is None:
        return False
    if not (key.role == "sig" and key.wrap_domain == "master" and key.owner_id is None):
        return False
    if not master_key.verify_mac(key.public_key, key.public_key_mac):
        return False
    provider = current_app.extensions["crypto"].signature(anchor.alg_id)
    return provider.verify(
        key.public_key, _anchor_message(anchor.seq, anchor.head_hash), anchor.signature
    )


def verify_ledger() -> dict:
    """Full integrity report: the hash-chain AND the SYSTEM head anchor.

    ``ok`` is True only if the chain recomputes cleanly, an anchor exists, its SYSTEM signature
    verifies, and it covers the current head. A naive edit trips ``chain_ok``; a consistent
    forward-rewrite leaves ``chain_ok`` True but trips ``anchor_covers_head`` (the head moved and
    cannot be re-signed).
    """
    chain_ok, break_seq = verify_chain()
    head = _last_entry()
    anchor = latest_anchor()

    anchor_ok = verify_anchor(anchor) if anchor is not None else False
    covers_head = (
        anchor is not None
        and head is not None
        and anchor.seq == head.seq
        and anchor.head_hash == head.entry_hash
    )
    return {
        "ok": chain_ok and anchor is not None and anchor_ok and covers_head,
        "chain_ok": chain_ok,
        "chain_break_seq": break_seq,
        "head_seq": head.seq if head is not None else None,
        "anchor_present": anchor is not None,
        "anchor_ok": anchor_ok,
        "anchor_covers_head": covers_head,
        "anchor_seq": anchor.seq if anchor is not None else None,
    }


# --------------------------------------------------------------------------------------------
# Tamper demonstration (dev/demo only; gated by ENABLE_TAMPER_DEMO at the route). Reversible: the
# affected rows are snapshotted so the ledger can be restored intact after the demo.
# --------------------------------------------------------------------------------------------

_DEMO_BACKUP: list[dict] | None = None


def _snapshot(e: LedgerEntry) -> dict:
    return {
        "seq": e.seq,
        "payload_json": e.payload_json,
        "payload_hash": e.payload_hash,
        "prev_hash": e.prev_hash,
        "entry_hash": e.entry_hash,
    }


def demo_is_tampered() -> bool:
    return _DEMO_BACKUP is not None


def demo_tamper(target_seq: int, mode: str = "edit", *, commit: bool = True) -> None:
    """Corrupt entry ``target_seq`` to demonstrate detection. ``mode``:

    * ``"edit"`` — alter the payload only; the chain breaks at ``target_seq``.
    * ``"rewrite"`` — alter the payload AND recompute every hash forward, so the chain stays
      internally consistent but the head moves and the SYSTEM anchor no longer covers it.
    """
    global _DEMO_BACKUP
    if mode not in ("edit", "rewrite"):
        raise LedgerError("mode must be 'edit' or 'rewrite'.")

    entries = LedgerEntry.query.order_by(LedgerEntry.seq.asc()).all()
    idx = next((i for i, e in enumerate(entries) if e.seq == target_seq), None)
    if idx is None:
        # Validate BEFORE snapshotting, so a bad target never marks the ledger "tampered".
        raise LedgerError(f"No ledger entry with seq={target_seq}.")

    if _DEMO_BACKUP is None:
        _DEMO_BACKUP = [_snapshot(e) for e in entries]

    target = entries[idx]
    import json as _json

    payload = _json.loads(target.payload_json)
    payload["_tamper"] = "unauthorised edit"  # a visible, illustrative mutation
    target.payload_json = canonical_json(payload).decode("utf-8")

    if mode == "rewrite":
        target.payload_hash = sha256_hex(target.payload_json.encode("utf-8"))
        prev_hash = entries[idx - 1].entry_hash if idx > 0 else GENESIS_PREV_HEX
        for e in entries[idx:]:
            e.prev_hash = prev_hash
            e.entry_hash = compute_entry_hash(
                seq=e.seq,
                timestamp=e.timestamp,
                actor=e.actor,
                event_type=e.event_type,
                payload_hash=e.payload_hash,
                prev_hash=prev_hash,
                actor_id=e.actor_id,
                vault_id=e.vault_id,
                ref_type=e.ref_type,
                ref_id=e.ref_id,
            )
            prev_hash = e.entry_hash
    # mode == "edit": leave payload_hash/entry_hash stale so the chain visibly breaks.

    if commit:
        db.session.commit()


def demo_restore(*, commit: bool = True) -> bool:
    """Restore the ledger from the snapshot. Returns True if a restore was performed, False if
    there was no backup to restore from (e.g. a restart lost the process-local snapshot)."""
    global _DEMO_BACKUP
    if _DEMO_BACKUP is None:
        return False
    by_seq = {b["seq"]: b for b in _DEMO_BACKUP}
    for e in LedgerEntry.query.all():
        b = by_seq.get(e.seq)
        if b is not None:
            e.payload_json = b["payload_json"]
            e.payload_hash = b["payload_hash"]
            e.prev_hash = b["prev_hash"]
            e.entry_hash = b["entry_hash"]
    if commit:
        db.session.commit()
    _DEMO_BACKUP = None
    return True
