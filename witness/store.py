"""The witness's own storage — plain ``sqlite3``, deliberately not SQLAlchemy.

Using the standard library directly rather than the application's ORM is not an aesthetic choice.
Importing ``qvault.extensions.db`` here would attach this process to the same metadata and the
same session machinery as the thing it is supposed to be independent of, and the first person to
"tidy up the duplication" would wire them to one database. The awkwardness of a second, smaller
persistence layer is the point: it is difficult to accidentally merge.

Three tables:

``origins``      one row per log this witness has ever spoken to, pinning the log's public key on
                 first contact. A log that later presents a different key is not the same log.
``checkpoints``  the co-signed history. The newest row per origin is the monotonic high-water mark
                 that makes truncation detectable.
``violations``   every refusal, with the offered checkpoint kept verbatim. This is the table that
                 turns the witness from a gate into *evidence*: refusing to co-sign protects the
                 verifier, but recording what was offered — signed by the log's own key — is what
                 lets someone later demonstrate that the operator tried.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS origins (
    origin          TEXT PRIMARY KEY,
    log_alg_id      TEXT NOT NULL,
    log_public_key  BLOB NOT NULL,
    first_seen      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checkpoints (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    origin          TEXT NOT NULL,
    tree_size       INTEGER NOT NULL,
    root_hash       TEXT NOT NULL,
    statement_json  TEXT NOT NULL,
    cosignature     BLOB NOT NULL,
    seen_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_checkpoints_origin_size ON checkpoints(origin, tree_size);
CREATE TABLE IF NOT EXISTS violations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    origin          TEXT NOT NULL,
    kind            TEXT NOT NULL,
    detail          TEXT NOT NULL,
    offered_json    TEXT NOT NULL,
    seen_at         TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class WitnessStore:
    """A tiny, synchronous store. One connection, because a witness is not a busy service."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # --- the pinned log identity ---------------------------------------------------------

    def known_log(self, origin: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM origins WHERE origin = ?", (origin,)
        ).fetchone()

    def pin_log(self, origin: str, alg_id: str, public_key: bytes) -> None:
        """Trust-on-first-use. The first key seen for an origin is the key for that origin.

        TOFU is a real weakness and worth naming: a witness that meets a fraudulent log before it
        meets the real one pins the wrong key. It is nonetheless strictly better than accepting
        any key at any time, and the fingerprint is displayed so the pin can be checked by hand
        against the log operator's published value.
        """
        self._conn.execute(
            "INSERT OR IGNORE INTO origins (origin, log_alg_id, log_public_key, first_seen) "
            "VALUES (?, ?, ?, ?)",
            (origin, alg_id, public_key, _now()),
        )
        self._conn.commit()

    # --- the co-signed history -----------------------------------------------------------

    def latest(self, origin: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM checkpoints WHERE origin = ? ORDER BY tree_size DESC, id DESC LIMIT 1",
            (origin,),
        ).fetchone()

    def at_size(self, origin: str, tree_size: int) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM checkpoints WHERE origin = ? AND tree_size = ? ORDER BY id DESC LIMIT 1",
            (origin, tree_size),
        ).fetchone()

    def record(self, origin: str, statement: dict, cosignature: bytes) -> None:
        self._conn.execute(
            "INSERT INTO checkpoints (origin, tree_size, root_hash, statement_json, "
            "cosignature, seen_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                origin,
                statement["tree_size"],
                statement["root_hash"],
                json.dumps(statement, sort_keys=True),
                cosignature,
                _now(),
            ),
        )
        self._conn.commit()

    def history(self, origin: str, limit: int = 50) -> list[sqlite3.Row]:
        return list(
            self._conn.execute(
                "SELECT * FROM checkpoints WHERE origin = ? ORDER BY tree_size DESC LIMIT ?",
                (origin, limit),
            )
        )

    # --- refusals ------------------------------------------------------------------------

    def record_violation(self, origin: str, kind: str, detail: str, offered: dict) -> None:
        self._conn.execute(
            "INSERT INTO violations (origin, kind, detail, offered_json, seen_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (origin, kind, detail, json.dumps(offered, sort_keys=True), _now()),
        )
        self._conn.commit()

    def violations(self, origin: str | None = None, limit: int = 50) -> list[sqlite3.Row]:
        if origin is None:
            return list(
                self._conn.execute(
                    "SELECT * FROM violations ORDER BY id DESC LIMIT ?", (limit,)
                )
            )
        return list(
            self._conn.execute(
                "SELECT * FROM violations WHERE origin = ? ORDER BY id DESC LIMIT ?",
                (origin, limit),
            )
        )

    def origins(self) -> list[sqlite3.Row]:
        return list(self._conn.execute("SELECT * FROM origins ORDER BY origin"))
