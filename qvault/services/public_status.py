"""What the public pages say about the log and the witness (plan S22): facts, never a fake number.

Two readers: the landing page's log strip ("Log head #12,481 · witnessed 9 s ago") and the status
page. Both are signed out, so this module is cheap on purpose. It reads the log's size from the
per-application leaf cache (``checkpoint_service.tree_size``), the newest checkpoint and the newest
witness co-signature, and checks that one co-signature again. It never recomputes the Merkle root
over the whole log (``current_root``, ``evidence_service.witness_check`` and ``log_summary`` all do,
and grow with the log), so a stranger loading the front page costs two small queries and one
signature check.

**Every state degrades honestly.** A log with a gap says it cannot be read; no witness says so; a
co-signature that does not check says so. The witness is *behind* only when the log has grown past
what it last co-signed AND the oldest entry it has not seen is older than ``witness_grace``: a quiet
log keeps an old co-signature time, which is true and is not a fault.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from flask import current_app
from sqlalchemy import select, text

from qvault.extensions import db
from qvault.models.checkpoint import LogCheckpoint, WitnessCosignature
from qvault.models.ledger import LedgerEntry
from qvault.services import checkpoint_service, evidence_service

#: The witness is offered the newest checkpoint every ``WITNESS_SYNC_SECONDS`` (60 s by default);
#: this many missed rounds, or ``MIN_GRACE`` if longer, before an unwitnessed entry counts as late.
GRACE_ROUNDS = 10
MIN_GRACE = timedelta(minutes=10)

#: The newest entries may wait for the request that wrote them to sign a checkpoint
#: (``maybe_checkpoint`` runs after each request). Past this, unsigned entries are late.
SIGNING_GRACE = timedelta(minutes=10)


def witness_grace() -> timedelta:
    """How long an entry may wait for the witness before the witness counts as behind."""
    every = int(current_app.config.get("WITNESS_SYNC_SECONDS") or 60)
    return max(MIN_GRACE, timedelta(seconds=every * GRACE_ROUNDS))


def _utc(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def span(moment: datetime | None, now: datetime | None = None) -> str:
    """How long ago ``moment`` was: ``9 seconds``, ``4 minutes``, ``3 hours``, ``2 days``, rounded
    down, so a time never reads as older than it is."""
    moment = _utc(moment)
    if moment is None:
        return ""
    now = _utc(now) or datetime.now(UTC)
    seconds = max(0, int((now - moment).total_seconds()))
    size, unit = next(
        (size, unit)
        for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute"), (1, "second"))
        if seconds >= size or unit == "second"
    )
    n = seconds // size
    return f"{n} {unit}{'' if n == 1 else 's'}"


def ago(moment: datetime | None, now: datetime | None = None) -> str:
    """``9 seconds ago``; empty for no time."""
    text_ = span(moment, now)
    return f"{text_} ago" if text_ else ""


def _entry_time(seq: int) -> datetime | None:
    return _utc(
        db.session.execute(
            select(LedgerEntry.created_at).where(LedgerEntry.seq == seq)
        ).scalar_one_or_none()
    )


@dataclass
class LogFacts:
    """The log strip's facts. ``state`` is one of the words below; the template words them."""

    #: readable | empty | unreadable
    log: str
    size: int | None = None
    #: none (no witness configured, none ever) | waiting (configured, nothing co-signed yet) |
    #: failed (the newest co-signature does not check) | current | behind
    witness: str = "none"
    witnessed_size: int | None = None
    witnessed_at: datetime | None = None
    witness_name: str | None = None
    #: Entries the witness has not co-signed yet, and since when the oldest of them has waited.
    unwitnessed: int = 0
    waiting_since: datetime | None = None
    #: The newest signed tree head: its size and when it was signed.
    signed_size: int | None = None
    signed_at: datetime | None = None
    #: Entries written but not yet in a signed tree head, and since when the oldest has waited.
    unsigned: int = 0
    unsigned_since: datetime | None = None

    @property
    def signing_late(self) -> bool:
        return bool(
            self.unsigned
            and self.unsigned_since is not None
            and datetime.now(UTC) - self.unsigned_since > SIGNING_GRACE
        )


def log_facts() -> LogFacts:
    """The log's size, its newest signed head, and the witness's state, cheaply (see the module)."""
    try:
        size = checkpoint_service.tree_size()
    except checkpoint_service.LogError:
        return LogFacts(log="unreadable")
    if size == 0:
        return LogFacts(log="empty", size=0)

    facts = LogFacts(log="readable", size=size)

    latest = checkpoint_service.latest_checkpoint()
    if latest is not None:
        facts.signed_size = latest.tree_size
        facts.signed_at = _utc(latest.created_at)
    signed = latest.tree_size if latest is not None else 0
    if size > signed:
        facts.unsigned = size - signed
        facts.unsigned_since = _entry_time(signed)

    cosignature = (
        WitnessCosignature.query.join(LogCheckpoint)
        .order_by(LogCheckpoint.tree_size.desc(), WitnessCosignature.id.desc())
        .first()
    )
    if cosignature is None:
        facts.witness = "waiting" if checkpoint_service.witness_url() else "none"
        if facts.witness == "waiting":
            facts.unwitnessed = size
            facts.waiting_since = _entry_time(0)
        return facts

    facts.witnessed_size = cosignature.checkpoint.tree_size
    facts.witnessed_at = _utc(cosignature.created_at)
    facts.witness_name = cosignature.witness_name
    if not evidence_service.verify_cosignature(cosignature):
        facts.witness = "failed"
        return facts

    facts.unwitnessed = max(0, size - facts.witnessed_size)
    if facts.unwitnessed:
        facts.waiting_since = _entry_time(facts.witnessed_size)
    late = (
        facts.waiting_since is not None
        and datetime.now(UTC) - facts.waiting_since > witness_grace()
    )
    facts.witness = "behind" if late else "current"
    return facts


# ------------------------------------------------------------------------------ the status page

#: The three levels, worst last. ``ok`` green, ``degraded`` amber, ``down`` red.
LEVELS = ("ok", "degraded", "down")


@dataclass
class Check:
    name: str
    level: str
    summary: str
    detail: str


def _database_ok() -> bool:
    try:
        db.session.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - a status page reports a broken database, it doesn't 500
        db.session.rollback()
        return False


def _have(n: int) -> str:
    return "entry has" if n == 1 else "entries have"


def checks() -> list[Check]:
    """The status page's rows: the service (what /healthz reports), the log, and the witness."""
    registry = current_app.extensions["crypto"]
    default_sig = current_app.config.get("DEFAULT_SIG_ALGORITHM")
    crypto_ok = bool(default_sig) and registry.has_signature(default_sig)
    out: list[Check] = []

    if not _database_ok():
        out.append(
            Check(
                "Service",
                "down",
                "The database isn't answering",
                "Signing in, approving and the log are unavailable until it is back.",
            )
        )
        return out
    if not crypto_ok:
        out.append(
            Check(
                "Service",
                "down",
                "Signing isn't available",
                f"The signature algorithm new keys use ({default_sig}) isn't loaded, so nobody "
                "can sign.",
            )
        )
    else:
        out.append(
            Check(
                "Service",
                "ok",
                "Up",
                f"The server, its database and its signing library are answering. Signatures use "
                f"{default_sig}. The same facts are at /healthz.",
            )
        )

    facts = log_facts()
    if facts.log == "unreadable":
        out.append(
            Check(
                "Audit log",
                "down",
                "The log can't be read",
                "An entry is missing from the sequence, so no new signed head is published. "
                "Treat recent records as unconfirmed.",
            )
        )
    elif facts.signing_late:
        out.append(
            Check(
                "Audit log",
                "degraded",
                "New entries aren't signed yet",
                f"{facts.unsigned:,} newest {_have(facts.unsigned)} "
                f"waited {span(facts.unsigned_since)} for a signed head. They are recorded, "
                "but can't be proved against a published head until one is signed.",
            )
        )
    else:
        head = f"#{facts.signed_size:,}" if facts.signed_size else "none yet"
        signed = f", signed {ago(facts.signed_at)}" if facts.signed_at else ""
        out.append(
            Check(
                "Audit log",
                "ok",
                "Recording and signing",
                f"{facts.size:,} entries. Newest signed head: {head}{signed}. A quiet log keeps "
                "an older head, which is normal.",
            )
        )

    if facts.log == "unreadable":
        pass
    elif facts.witness == "none":
        out.append(
            Check(
                "Witness",
                "degraded",
                "No witness",
                "No independent witness is configured, so the log's heads are signed only by "
                "this server. Records are still signed; they can't show that the operator didn't "
                "rewrite them.",
            )
        )
    elif facts.witness == "waiting":
        out.append(
            Check(
                "Witness",
                "degraded",
                "Not witnessed yet",
                "A witness is configured but hasn't co-signed a head yet.",
            )
        )
    elif facts.witness == "failed":
        out.append(
            Check(
                "Witness",
                "down",
                "The witness's signature doesn't check",
                "The newest co-signature stored here doesn't verify. Don't rely on the log's "
                "witnessed heads until this is explained.",
            )
        )
    elif facts.witness == "behind":
        out.append(
            Check(
                "Witness",
                "degraded",
                "Behind",
                f"{facts.unwitnessed:,} {_have(facts.unwitnessed)} "
                f"waited {span(facts.waiting_since)} for the witness. Last co-signed "
                f"{ago(facts.witnessed_at)}, at #{facts.witnessed_size:,}.",
            )
        )
    else:
        out.append(
            Check(
                "Witness",
                "ok",
                "Current",
                f"Last co-signed {ago(facts.witnessed_at)}, at #{facts.witnessed_size:,}. "
                f"Entries wait at most {int(witness_grace().total_seconds() // 60)} minutes "
                "before this turns amber.",
            )
        )
    return out


def overall(rows: list[Check]) -> str:
    """The worst level among ``rows``."""
    return max((r.level for r in rows), key=LEVELS.index, default="ok")


# ------------------------------------------------------------------------------ the public head

#: The public checkpoint document's format. The verifier (``qvault.verify.checkpoint``) refuses a
#: version it does not know rather than guessing.
CHECKPOINT_FORMAT = "qvault.checkpoint/1"


def _signed_head(checkpoint: LogCheckpoint) -> dict:
    """One signed head, in the shape a decision bundle's ``log`` section already publishes, plus
    the key fingerprints a reader pins. Nothing in it names a person, a vault or a decision."""
    from base64 import b64encode

    from qvault.crypto import sha256_hex

    key = checkpoint.key
    return {
        "checkpoint": checkpoint.statement(),
        "checkpoint_signature": {
            "alg_id": checkpoint.alg_id,
            "backend": checkpoint.backend,
            "public_key_b64": b64encode(key.public_key).decode(),
            "signature_b64": b64encode(checkpoint.signature).decode(),
            "key_fingerprint": sha256_hex(key.public_key)[:16],
        },
        "witnesses": [
            {
                "witness": c.witness_name,
                "alg_id": c.alg_id,
                "backend": c.backend,
                "public_key_b64": b64encode(c.public_key).decode(),
                "signature_b64": b64encode(c.signature).decode(),
                "key_fingerprint": c.key_fingerprint(),
                "cosigned_at": iso(c.created_at),
            }
            for c in checkpoint.cosignatures
        ],
    }


def iso(moment: datetime | None) -> str | None:
    moment = _utc(moment)
    return moment.isoformat().replace("+00:00", "Z") if moment else None


def checkpoint_document() -> dict:
    """The log's newest signed head, and the newest one a witness co-signed, for anyone to fetch.

    Read from the stored checkpoints only: no Merkle root is recomputed here, so the cost does not
    grow with the log. The two heads differ while the witness has not yet seen the newest one;
    both are given, so the gap is visible rather than hidden. An empty table, or no witness, reads
    as ``null`` with ``witness_configured`` saying which it is.
    """
    latest = checkpoint_service.latest_checkpoint()
    cosigned = (
        WitnessCosignature.query.join(LogCheckpoint)
        .order_by(LogCheckpoint.tree_size.desc(), WitnessCosignature.id.desc())
        .first()
    )
    return {
        "format": CHECKPOINT_FORMAT,
        "origin": checkpoint_service.origin(),
        "witness_configured": bool(checkpoint_service.witness_url()),
        "latest": _signed_head(latest) if latest is not None else None,
        "witnessed": _signed_head(cosigned.checkpoint) if cosigned is not None else None,
    }
