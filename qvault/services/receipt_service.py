"""What the machine actually did, at the moment it did it.

Casting a vote is the most-repeated action in this product and, until now, the least legible: a
signer typed a password and a counter moved. The work behind that counter — a 3,309-byte ML-DSA
signature produced and verified before it was emitted, hashed into the audit chain, and folded
into a Merkle tree whose root an independent witness co-signs — left no trace on screen that a
person could see.

This module assembles that trace for one signature. It is a **read-only** presentation service:
it takes no locks, writes nothing, and every value it returns is either read from a committed row
or recomputed on the spot from committed rows. That matters, because a receipt that could not be
reproduced later would be a worse claim than no receipt at all.

Two of the figures are measured here rather than stored:

* ``verify_ms`` times a *fresh* verification of the stored signature. It is not the time the
  original signing took (that is gone, and reconstructing it would be fiction). It is the cost of
  the check anyone can repeat, which is the number a reader can act on.
* ``root_before`` / ``root_after`` recompute the Merkle root over the leaf prefixes either side of
  this vote's ledger entry. The pair is the point: a root is only interesting as something that
  *moved*, and moved in a way the previous root cannot be walked back to.

Everything here degrades to ``None`` rather than raising. A receipt is a courtesy on top of a vote
that has already been committed; failing to render one must never look like a failed vote.
"""

from __future__ import annotations

import json
from time import perf_counter

from flask import current_app
from sqlalchemy import select

from qvault.crypto import sha256_hex
from qvault.extensions import db
from qvault.models.ledger import LedgerEntry
from qvault.models.signature import Signature
from qvault.services import approval_service, checkpoint_service
from qvault.transparency.merkle import merkle_root

#: How many leading bytes of the raw signature to surface. Enough that a reader sees genuine
#: high-entropy material rather than a label claiming it exists, short enough that a 49,856-byte
#: SLH-DSA signature does not take over the page.
PREVIEW_BYTES = 24


def _ledger_entry_for(sig: Signature) -> LedgerEntry | None:
    """The ``proposal_signed`` entry this signature produced.

    Matched on the payload's ``signature_sha256`` rather than on "the newest entry by this signer",
    because the newest-by-signer heuristic silently returns the wrong row the moment a signature is
    ever re-recorded, and a receipt pointing at somebody else's ledger entry is worse than a
    receipt with a blank field.

    Candidates are narrowed in SQL and then matched by parsing the canonical payload, not with a
    ``LIKE '%hash%'``: the payload is attacker-influenced text in the general case, and a substring
    match over it would accept a hash that appeared in some other field.
    """
    wanted = sha256_hex(sig.signature)
    rows = db.session.execute(
        select(LedgerEntry)
        .where(
            LedgerEntry.event_type == "proposal_signed",
            LedgerEntry.ref_type == "proposal",
            LedgerEntry.ref_id == sig.proposal.proposal_uuid,
            LedgerEntry.actor_id == sig.signer_id,
        )
        .order_by(LedgerEntry.seq)
    ).scalars()
    for entry in rows:
        try:
            payload = json.loads(entry.payload_json)
        except ValueError:  # pragma: no cover - payload_json is written by canonical_json
            continue
        if payload.get("signature_sha256") == wanted:
            return entry
    return None


def _roots_around(seq: int) -> tuple[str | None, str | None]:
    """The Merkle root before and after the entry at ``seq`` joined the log.

    ``leaf_hashes()`` is indexed by ``seq`` (leaf *i* is the leaf of entry *i*), a property
    ``leaf_hashes`` itself enforces by refusing a non-contiguous sequence. So the prefix of length
    ``seq`` is exactly the tree as it stood immediately before this entry.
    """
    try:
        leaves = checkpoint_service.leaf_hashes()
    except Exception:  # noqa: BLE001 - a receipt must not surface a log-integrity error as a 500
        return None, None
    if seq >= len(leaves):  # pragma: no cover - would mean the cache is behind its own ledger
        return None, None
    before = merkle_root(leaves[:seq]).hex() if seq > 0 else None
    return before, merkle_root(leaves[: seq + 1]).hex()


def for_signature(sig: Signature) -> dict | None:
    """Assemble the receipt for ``sig``, or ``None`` if it cannot be built.

    The returned dict is shaped for a template and contains no ORM objects beyond the two the
    caller already has, so it is equally usable as a JSON response later.
    """
    if sig is None or sig.proposal is None:
        return None

    proposal = sig.proposal

    started = perf_counter()
    verified = approval_service.verify_signature(sig, proposal)
    verify_ms = (perf_counter() - started) * 1000.0

    entry = _ledger_entry_for(sig)
    root_before, root_after = _roots_around(entry.seq) if entry is not None else (None, None)

    try:
        provider = current_app.extensions["crypto"].signature(sig.alg_id)
        standard = getattr(provider.meta, "nist_standard", None)
        category = getattr(provider.meta, "security_category", None)
    except Exception:  # noqa: BLE001 - an unregistered alg must not break the page
        standard = category = None

    return {
        "signature": sig,
        "decision": sig.decision,
        "verified": verified,
        "verify_ms": verify_ms,
        # The bytes themselves. A signature is the one artefact in this system whose *size* is a
        # research finding (ML-DSA 3,309 B vs SLH-DSA 49,856 B), so it is stated, not implied.
        "size_bytes": len(sig.signature),
        "preview_hex": sig.signature[:PREVIEW_BYTES].hex(),
        "sig_fingerprint": sig.fingerprint(),
        "alg_id": sig.alg_id,
        "standard": standard,
        "security_category": category,
        "backend": sig.backend,
        # ADR-0016's claim is only visible where a device signature is distinguishable from one
        # this server produced. The receipt is the first place the signer sees it about their own
        # vote rather than inferring it from a table column.
        "custody": sig.custody,
        "key_fingerprint": sig.key.public_fingerprint() if sig.key is not None else None,
        "key_id": sig.key_id,
        "ledger_seq": entry.seq if entry is not None else None,
        "ledger_entry_hash": entry.entry_hash if entry is not None else None,
        "ledger_prev_hash": entry.prev_hash if entry is not None else None,
        "ledger_timestamp": entry.timestamp if entry is not None else None,
        "root_before": root_before,
        "root_after": root_after,
        "tree_size": (entry.seq + 1) if entry is not None else None,
        "status": proposal.status,
    }


def for_signature_id(proposal, signature_id: object) -> dict | None:
    """Look up a signature *within* ``proposal`` and build its receipt.

    Scoping the lookup to the proposal is the authorisation check: the caller has already been
    shown to be a member of this proposal's vault, and every signature on it is already listed on
    the page, so a receipt for one of them discloses nothing new. A bare ``Signature.query.get``
    would instead let any member of any vault render a receipt for any signature in the system.
    """
    try:
        wanted = int(signature_id)
    except (TypeError, ValueError):
        return None
    sig = next((s for s in proposal.signatures if s.id == wanted), None)
    return for_signature(sig) if sig is not None else None
