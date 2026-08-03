"""Append-only, hash-chained audit ledger — the single canonical hashing rule (spec §4.6).

Every security-relevant event is appended here. Each entry's hash covers its ordered fields
plus the previous entry's hash, under a domain-separation tag, so any edit to a past entry is
detectable by ``verify_chain``.

Phase 2 provides genesis, append, and verification. Phase 5 adds the SYSTEM-signed head anchor
(defence against a full forward-rewrite by a DB-write adversary) and the tamper demonstration.
"""

from __future__ import annotations

from datetime import UTC, datetime

from qvault.crypto import canonical_json, sha256_hex
from qvault.extensions import db
from qvault.models.ledger import LedgerEntry

ENTRY_DS = b"QVAULT-LEDGER-v1|"
GENESIS_PREV_HEX = sha256_hex(b"QVAULT-LEDGER-GENESIS-v1")


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
