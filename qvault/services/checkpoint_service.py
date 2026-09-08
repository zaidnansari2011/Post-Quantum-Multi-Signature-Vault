"""Signed tree heads over the audit ledger, and the conversation with the witness.

This sits directly on top of :mod:`qvault.services.ledger_service`. The chain there is unchanged
and still authoritative for *content*; this module adds the structure that makes the log's claims
portable — a Merkle root that a single entry can be proved against, and a signature over that root
that an outside party can check.

Two guards are the whole point of the file, and both are refusals rather than repairs:

* :func:`maybe_checkpoint` will not sign a tree that is not a provable extension of the last one
  it signed. A rewrite therefore *stalls* the checkpoint sequence instead of being blessed by it.
* the witness will not co-sign one either, and it is not running here.

The first can be defeated by anyone who can write to this database; the second cannot, which is
the entire reason the witness exists as a separate process with its own key.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from base64 import b64decode, b64encode
from datetime import UTC, datetime

from flask import current_app
from sqlalchemy import select

from qvault import glassbox
from qvault.extensions import db
from qvault.models.checkpoint import LogCheckpoint, WitnessCosignature
from qvault.models.key import Key
from qvault.models.ledger import LedgerEntry
from qvault.security import master_key
from qvault.services import ledger_service
from qvault.transparency import (
    checkpoint_bytes,
    consistency_proof,
    entry_leaf_hash,
    inclusion_proof,
    merkle_root,
    verify_consistency,
    witness_bytes,
)
from qvault.transparency.statement import checkpoint_statement

DEFAULT_ORIGIN = "qvault.local/ledger"


class LogError(RuntimeError):
    """Raised when the ledger cannot be interpreted as a log — e.g. a gap in the sequence."""


def origin() -> str:
    return current_app.config.get("LOG_ORIGIN") or DEFAULT_ORIGIN


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


# --------------------------------------------------------------------------------------------
# Leaves
# --------------------------------------------------------------------------------------------


def _cache() -> list[bytes]:
    return current_app.extensions.setdefault("log_leaves", [])


def leaf_hashes() -> list[bytes]:
    """Every ledger entry's Merkle leaf hash, in sequence order.

    Cached per application and extended incrementally, because the alternative — rehashing the
    whole ledger on each append — is the difference between this being a design that scales and a
    demo. The cache is validated before it is extended: if the newest cached entry's chain hash no
    longer matches the database, history was rewritten underneath us and the cache is discarded
    rather than built upon.

    A **gap** in ``seq`` raises rather than silently producing a shorter tree. A missing entry is
    exactly the truncation attack, and quietly renumbering the leaves around it would hand the
    adversary a clean root for a log that lost rows.
    """
    cache = _cache()
    if cache:
        tip = db.session.execute(
            select(LedgerEntry.entry_hash).where(LedgerEntry.seq == len(cache) - 1)
        ).scalar_one_or_none()
        if tip is None or entry_leaf_hash(tip) != cache[-1]:
            cache.clear()

    rows = db.session.execute(
        select(LedgerEntry.seq, LedgerEntry.entry_hash)
        .where(LedgerEntry.seq >= len(cache))
        .order_by(LedgerEntry.seq)
    ).all()
    for seq, entry_hash in rows:
        if seq != len(cache):
            raise LogError(
                f"ledger sequence is not contiguous: expected seq {len(cache)}, found {seq}. "
                "Entries appear to have been deleted."
            )
        cache.append(entry_leaf_hash(entry_hash))
    return cache


def tree_size() -> int:
    return len(leaf_hashes())


def current_root() -> str:
    return merkle_root(leaf_hashes()).hex()


# --------------------------------------------------------------------------------------------
# Checkpoints
# --------------------------------------------------------------------------------------------


def latest_checkpoint() -> LogCheckpoint | None:
    return LogCheckpoint.query.order_by(
        LogCheckpoint.tree_size.desc(), LogCheckpoint.id.desc()
    ).first()


def checkpoint_covering(seq: int) -> LogCheckpoint | None:
    """The best checkpoint to export a proof against for ledger entry ``seq``.

    **Witnessed first, then newest.** A proof against a checkpoint an independent witness has
    already co-signed is worth strictly more than one against a checkpoint only this server has
    ever seen, so a witnessed checkpoint wins even if it is larger.

    Failing that, the *newest*. The obvious alternative — oldest covering — is wrong, and was a bug
    here: the witness only ever moves forward, so once it has passed an old unwitnessed checkpoint
    that checkpoint can never acquire a co-signature, and exports pinned to it are permanently
    unwitnessed. The newest is the only one still eligible.
    """
    witnessed = (
        LogCheckpoint.query.join(WitnessCosignature)
        .filter(LogCheckpoint.tree_size > seq)
        .order_by(LogCheckpoint.tree_size.asc(), LogCheckpoint.id.asc())
        .first()
    )
    if witnessed is not None:
        return witnessed
    return (
        LogCheckpoint.query.filter(LogCheckpoint.tree_size > seq)
        .order_by(LogCheckpoint.tree_size.desc(), LogCheckpoint.id.desc())
        .first()
    )


def create_checkpoint(*, commit: bool = True) -> LogCheckpoint:
    """Sign the current Merkle root with the SYSTEM key.

    Crypto-agile in the same way as everything else: the algorithm comes from the SYSTEM key at
    signing time and is pinned onto the row, so checkpoints signed before an algorithm switch keep
    verifying afterwards under the provider that made them.
    """
    leaves = leaf_hashes()
    head = LedgerEntry.query.order_by(LedgerEntry.seq.desc()).first()
    if head is None:
        raise LogError("cannot checkpoint an empty ledger")
    if len(leaves) != head.seq + 1:
        raise LogError(f"tree size {len(leaves)} does not match head seq {head.seq}")

    with glassbox.step("Recompute the Merkle root over the whole log", code=merkle_root) as t:
        t.annotate(
            "RFC 6962: leaves are SHA-256(0x00 || entry hash), internal nodes are "
            "SHA-256(0x01 || left || right). Every ledger entry is folded into this one value, so "
            "a single altered entry anywhere changes the root."
        )
        t.input("tree size", glassbox.Number(len(leaves), unit="entries"))
        t.input("first leaf", glassbox.Hex(leaves[0], full=True))
        t.input("last leaf", glassbox.Hex(leaves[-1], full=True))
        root = merkle_root(leaves).hex()
        t.output("root", glassbox.Digest(root))

    # Idempotent at an unchanged tree. Two checkpoints at the same size are at best clutter — and
    # were an actual bug: a second, unwitnessed row at a size the witness had already co-signed
    # got picked for export, so the bundle shipped without a co-signature. A *different* root at
    # the same size is not clutter, it is a fork, and must never be quietly given a second
    # signature.
    existing = latest_checkpoint()
    if existing is not None and existing.tree_size == len(leaves):
        if existing.root_hash != root:
            raise LogError(
                f"refusing to sign a second root at tree_size {len(leaves)}: "
                f"already signed {existing.root_hash[:16]}…, now computed {root[:16]}…"
            )
        return existing

    statement = checkpoint_statement(
        origin=origin(),
        tree_size=len(leaves),
        root_hash=root,
        head_seq=head.seq,
        head_hash=head.entry_hash,
        timestamp=_utcnow_iso(),
    )

    key = ledger_service.ensure_system_key()
    provider = current_app.extensions["crypto"].signature(key.alg_id)
    message = checkpoint_bytes(statement)
    secret = master_key.unwrap_secret(key.secret_key_nonce, key.secret_key_wrapped)
    try:
        with glassbox.step("Sign the checkpoint with the log's own key", code=provider.sign) as t:
            t.annotate(
                "A signed tree head. This is what an independent witness is offered, and what "
                "an exported decision package carries so a third party can check the log's state "
                "without asking this server anything."
            )
            t.input("statement", glassbox.Json(statement))
            t.input("algorithm", glassbox.Label(key.alg_id))
            t.input("signing key", glassbox.Opaque(secret, why="server-custodied SYSTEM key"))
            signature = provider.sign(secret, message)
            t.output("checkpoint signature", glassbox.Hex(signature))
    finally:
        del secret

    # Verify before persisting (ADR-0010). A checkpoint that does not verify is worse than none:
    # it is published, third parties fetch it, and every one of them reports our log as broken.
    if not provider.verify(key.public_key, message, signature):
        raise LogError(f"checkpoint over tree_size {statement['tree_size']} failed self-verification")

    checkpoint = LogCheckpoint(
        origin=statement["origin"],
        tree_size=statement["tree_size"],
        root_hash=statement["root_hash"],
        head_seq=statement["head_seq"],
        head_hash=statement["head_hash"],
        timestamp=statement["timestamp"],
        alg_id=key.alg_id,
        backend=key.backend,
        key_id=key.id,
        signature=signature,
    )
    db.session.add(checkpoint)
    if commit:
        db.session.commit()
    return checkpoint


def maybe_checkpoint(*, commit: bool = True) -> LogCheckpoint | None:
    """Checkpoint the log, but only if doing so cannot bless a rewrite.

    Three refusals, each corresponding to an attack rather than to a housekeeping concern:

    * **the tree did not grow** — nothing to say, and a *same size, different root* is a fork, so
      re-signing at an unchanged size is precisely what must never happen;
    * **the previous checkpoint is not a prefix of the current tree** — history was edited; the
      chain may well still recompute (a consistent forward-rewrite does), but the consistency
      proof does not, and a fresh signature over the rewritten tree would launder it;
    * **the ledger has a gap** — entries were deleted, and :func:`leaf_hashes` raises.

    The stall is the signal. A log whose newest checkpoint is old, while entries keep arriving, is
    a log that cannot prove it still contains its own past.
    """
    try:
        leaves = leaf_hashes()
    except LogError:
        return None
    if not leaves:
        return None

    last = latest_checkpoint()
    if last is not None:
        if last.tree_size >= len(leaves):
            return None
        proof = consistency_proof(leaves, last.tree_size)
        with glassbox.step(
            "Prove the log still contains its own past", code=verify_consistency
        ) as t:
            t.annotate(
                "Before signing a new root, check the previously signed root is still a prefix "
                "of this tree. If it is not, history was edited -- and signing anyway would "
                "launder the rewrite. The refusal stalls the checkpoint sequence, and that stall "
                "is itself the alarm."
            )
            t.input("previously signed size", glassbox.Number(last.tree_size, unit="entries"))
            t.input("previously signed root", glassbox.Digest(last.root_hash))
            t.input("current size", glassbox.Number(len(leaves), unit="entries"))
            t.input("current root", glassbox.Digest(merkle_root(leaves).hex()))
            t.input(
                "proof",
                glassbox.Json([h.hex() for h in proof], note=f"{len(proof)} node hashes"),
            )
            consistent = verify_consistency(
                old_size=last.tree_size,
                old_root=bytes.fromhex(last.root_hash),
                new_size=len(leaves),
                new_root=merkle_root(leaves),
                proof=proof,
            )
            t.output("consistent", glassbox.Label(consistent))
        if not consistent:
            return None  # the signed past is no longer a prefix of the present: do not sign
    return create_checkpoint(commit=commit)


def verify_checkpoint(checkpoint: LogCheckpoint) -> bool:
    """Verify a checkpoint's SYSTEM signature, with the same trust-root binding as an anchor.

    The public key is taken from the checkpoint's pinned ``key_id`` but is only trusted once its
    master-key MAC checks out, so a database-write adversary cannot swap in a keypair of their own
    (ADR-0005). Note this is the *server-side* check; a third party running the exported verifier
    has no master key and instead pins the fingerprint.
    """
    key = db.session.get(Key, checkpoint.key_id)
    if key is None:
        return False
    # All three terms are load-bearing — see ensure_system_key. wrap_domain in particular keeps
    # a device-custodied key (Phase 1) out of the anchor trust path; do not simplify this away.
    if not (key.role == "sig" and key.wrap_domain == "master" and key.owner_id is None):
        return False
    if not master_key.verify_mac(key.public_key, key.public_key_mac):
        return False
    provider = current_app.extensions["crypto"].signature(checkpoint.alg_id)
    return provider.verify(key.public_key, checkpoint_bytes(checkpoint.statement()), checkpoint.signature)


# --------------------------------------------------------------------------------------------
# Proofs
# --------------------------------------------------------------------------------------------


def inclusion_proof_for(seq: int, checkpoint: LogCheckpoint) -> list[str]:
    """Hex audit path proving ledger entry ``seq`` is in ``checkpoint``'s tree."""
    leaves = leaf_hashes()
    if checkpoint.tree_size > len(leaves):
        raise LogError(
            f"checkpoint claims {checkpoint.tree_size} entries but the ledger holds {len(leaves)}"
        )
    if not 0 <= seq < checkpoint.tree_size:
        raise LogError(f"entry {seq} is not covered by a checkpoint of size {checkpoint.tree_size}")
    return [h.hex() for h in inclusion_proof(leaves[: checkpoint.tree_size], seq)]


def consistency_proof_from(old_size: int, new_size: int | None = None) -> list[str]:
    """Hex proof that the tree of ``old_size`` is a prefix of the tree of ``new_size``."""
    leaves = leaf_hashes()
    upto = len(leaves) if new_size is None else new_size
    if upto > len(leaves):
        raise LogError(f"cannot prove up to {upto}: the ledger holds {len(leaves)} entries")
    return [h.hex() for h in consistency_proof(leaves[:upto], old_size)]


# --------------------------------------------------------------------------------------------
# The witness
# --------------------------------------------------------------------------------------------


def witness_url() -> str | None:
    return current_app.config.get("WITNESS_URL") or None


def _read_error(exc: urllib.error.HTTPError) -> dict:
    """Turn a 4xx into the witness's own words.

    ``urlopen`` raises on 4xx, so without this a **refusal** — the single most important message
    this system can receive — surfaces as an exception and gets reported as "witness unreachable".
    An operator would then read "the witness is down" when the truth is "the witness says your log
    shrank", which inverts the meaning of the one alarm that matters.
    """
    body = exc.read().decode("utf-8", errors="replace")
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return {"error": f"HTTP {exc.code}: {body[:200]}"}
    return parsed if isinstance(parsed, dict) and parsed.get("error") else {
        "error": f"HTTP {exc.code}: {body[:200]}"
    }


def _post(url: str, body: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return _read_error(exc)


def _get(url: str, timeout: float) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return _read_error(exc)


def sync_witness(checkpoint: LogCheckpoint | None = None, *, commit: bool = True) -> dict:
    """Offer a checkpoint to the configured witness and record its co-signature.

    Call it with no argument. Passing a specific *historical* checkpoint is refused below, because
    the witness only ever moves forward: offering it something it has already passed cannot
    succeed, and is recorded on its side as a ``shrank`` violation — an alarm raised by honest
    behaviour, which is worse than useless in a tool whose alarms are meant to mean something.

    Returns a status dict rather than raising, and never propagates a network error: a witness
    that is down must degrade to "this checkpoint is not yet witnessed", which is a true and
    useful statement, and must never take the application with it.

    The co-signature is verified here before being stored. That is not for the witness's benefit —
    it is so an unreachable or misbehaving witness cannot poison exported bundles with a signature
    that every third-party verifier would then report as a failure of *our* log.
    """
    url = witness_url()
    if not url:
        return {"configured": False, "witnessed": False, "reason": "no witness configured"}

    head = latest_checkpoint()
    checkpoint = checkpoint or head
    if checkpoint is None:
        return {"configured": True, "witnessed": False, "reason": "no checkpoint to offer"}
    if head is not None and checkpoint.id != head.id and checkpoint.tree_size < head.tree_size:
        # A backfill request. Distinct from the log's head having shrunk, which IS offered below
        # precisely so the witness records it.
        return {
            "configured": True,
            "witnessed": False,
            "reason": "cannot backfill: the witness only moves forward",
        }

    timeout = float(current_app.config.get("WITNESS_TIMEOUT_S", 3.0))
    key = db.session.get(Key, checkpoint.key_id)
    if key is None:
        return {"configured": True, "witnessed": False, "reason": "checkpoint key is missing"}

    try:
        # Ask what the witness last saw, so we can prove our tree extends it. A witness that has
        # never seen this log needs no proof; one that has needs a consistency proof from its own
        # last size, which only we can produce.
        state = _get(f"{url.rstrip('/')}/state?origin={urllib.parse.quote(origin())}", timeout)
        known = state.get("tree_size")
        proof: list[str] = []
        if known and known <= checkpoint.tree_size:
            proof = consistency_proof_from(known, checkpoint.tree_size)
        # If the witness has seen MORE than we are offering, our log has lost entries and no
        # consistency proof exists. The checkpoint is offered anyway, with an empty proof, because
        # the refusal has to be recorded *by the witness* — a client-side "never mind, I can see
        # I have shrunk" would make the evidence depend on the goodwill of the party being
        # audited, which is the one assumption this whole component exists to remove.

        response = _post(
            f"{url.rstrip('/')}/cosign",
            {
                "checkpoint": checkpoint.statement(),
                "log_alg_id": checkpoint.alg_id,
                "log_public_key_b64": b64encode(key.public_key).decode(),
                "log_signature_b64": b64encode(checkpoint.signature).decode(),
                "consistency_proof": proof,
            },
            timeout,
        )
    except (urllib.error.URLError, OSError, ValueError, LogError) as exc:
        return {"configured": True, "witnessed": False, "reason": f"witness unreachable: {exc}"}

    if response.get("error"):
        return {"configured": True, "witnessed": False, "reason": response["error"]}

    name = response["witness"]
    public_key = b64decode(response["public_key_b64"])
    signature = b64decode(response["signature_b64"])
    alg_id = response["alg_id"]

    registry = current_app.extensions["crypto"]
    if not registry.has_signature(alg_id):
        return {"configured": True, "witnessed": False, "reason": f"unknown witness alg {alg_id}"}
    message = witness_bytes(witness=name, statement=checkpoint.statement())
    if not registry.signature(alg_id).verify(public_key, message, signature):
        return {"configured": True, "witnessed": False, "reason": "witness signature did not verify"}

    # Deliberately NOT appended to the ledger. Recording "checkpoint N was witnessed" as a ledger
    # event would grow the very tree that was just co-signed, so the witness would sit permanently
    # one entry behind and "witnessed and current" would be an unreachable state — turning the
    # single most useful operational signal into noise. The co-signature row *is* the record, and
    # it is stronger evidence than a ledger line, because it carries a signature this server
    # cannot produce.
    existing = WitnessCosignature.query.filter_by(
        checkpoint_id=checkpoint.id, witness_name=name
    ).first()
    if existing is None:
        db.session.add(
            WitnessCosignature(
                checkpoint_id=checkpoint.id,
                witness_name=name,
                alg_id=alg_id,
                backend=response.get("backend", "unknown"),
                public_key=public_key,
                signature=signature,
            )
        )
        if commit:
            db.session.commit()

    return {
        "configured": True,
        "witnessed": True,
        "witness": name,
        "alg_id": alg_id,
        "tree_size": checkpoint.tree_size,
    }


def log_summary() -> dict:
    """Cheap facts about the log, for screens that show it as a headline figure.

    Deliberately does **no** signature verification. The obvious version of this would call
    ``config_service.verify_all_artefacts`` and report "n of n verify", which is the better
    number — and it is a real cryptographic workload that grows with the ledger, so it belongs on
    the security console where someone has asked for it, not on the screen every user loads first.
    """
    try:
        entries = tree_size()
        root = current_root()
    except LogError:
        return {"entries": None, "root": None, "witnessed": None, "lag": None, "witness": None}

    latest = latest_checkpoint()
    cosigned = (
        WitnessCosignature.query.join(LogCheckpoint)
        .order_by(LogCheckpoint.tree_size.desc())
        .first()
    )
    return {
        "entries": entries,
        "root": root,
        "checkpointed": latest.tree_size if latest else None,
        "alg_id": latest.alg_id if latest else None,
        "witnessed": cosigned.checkpoint.tree_size if cosigned else None,
        "witness": cosigned.witness_name if cosigned else None,
        "witness_alg": cosigned.alg_id if cosigned else None,
        "lag": (latest.tree_size - cosigned.checkpoint.tree_size) if latest and cosigned else None,
    }


def witness_state() -> dict:
    """A summary for the transparency page: is there a witness, and how current is it?"""
    latest = latest_checkpoint()
    witnessed = (
        WitnessCosignature.query.join(LogCheckpoint)
        .order_by(LogCheckpoint.tree_size.desc())
        .first()
    )
    return {
        "configured": bool(witness_url()),
        "url": witness_url(),
        "latest_size": latest.tree_size if latest else None,
        "latest_witnessed_size": witnessed.checkpoint.tree_size if witnessed else None,
        "witnesses": sorted(
            {
                (c.witness_name, c.key_fingerprint(), c.alg_id)
                for c in WitnessCosignature.query.all()
            }
        ),
        "lag": (
            latest.tree_size - witnessed.checkpoint.tree_size
            if latest and witnessed
            else None
        ),
    }
