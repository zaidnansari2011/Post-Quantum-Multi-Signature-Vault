"""The witness service: two endpoints and a status page.

``GET  /state?origin=…``  what this witness last saw for a log — the high-water mark a log must
                          prove it still contains.
``POST /cosign``          offer a checkpoint; get a countersignature, or a refusal that is also
                          recorded.
``GET  /``                a human-readable record of what it has seen and what it has refused.

The refusals are the substance. A witness that co-signed whatever it was handed would be a second
signature over the same claim, worth nothing; the value is entirely in the conditions under which
it says no.
"""

from __future__ import annotations

import json
from base64 import b64decode, b64encode
from pathlib import Path

from flask import Flask, Response, jsonify, render_template_string, request

from qvault.crypto import build_registry, sha256_hex
from qvault.transparency import checkpoint_bytes, verify_consistency, witness_bytes

from .identity import load_or_create
from .store import WitnessStore

#: A checkpoint statement must have exactly these fields. Exactly — not "at least".
#: The witness signs a serialisation of whatever dict it is given, so an unrecognised extra field
#: would be silently countersigned. Refusing anything we cannot fully account for means a
#: co-signature always attests to a statement the witness actually understood.
STATEMENT_FIELDS = {"origin", "tree_size", "root_hash", "head_seq", "head_hash", "timestamp"}


def _bad(reason: str, status: int = 400) -> tuple[Response, int]:
    return jsonify({"error": reason}), status


def _valid_statement(statement: object) -> str | None:
    """Return an error string, or None if the statement is well-formed."""
    if not isinstance(statement, dict):
        return "checkpoint must be an object"
    if set(statement) != STATEMENT_FIELDS:
        missing = sorted(STATEMENT_FIELDS - set(statement))
        extra = sorted(set(statement) - STATEMENT_FIELDS)
        return f"checkpoint fields wrong (missing={missing}, unexpected={extra})"
    if not isinstance(statement["origin"], str) or not statement["origin"]:
        return "origin must be a non-empty string"
    for field in ("tree_size", "head_seq"):
        if not isinstance(statement[field], int) or isinstance(statement[field], bool):
            return f"{field} must be an integer"
    if statement["tree_size"] < 1:
        return "tree_size must be at least 1"
    if statement["tree_size"] != statement["head_seq"] + 1:
        # Ledger sequence numbers are contiguous from genesis at 0, so this identity always
        # holds for an intact log. A mismatch means entries are missing from the middle.
        return (
            f"tree_size {statement['tree_size']} does not match head_seq "
            f"{statement['head_seq']} + 1"
        )
    for field in ("root_hash", "head_hash"):
        value = statement[field]
        if not isinstance(value, str) or len(value) != 64:
            return f"{field} must be 64 hex characters"
        try:
            bytes.fromhex(value)
        except ValueError:
            return f"{field} is not hex"
    if not isinstance(statement["timestamp"], str):
        return "timestamp must be a string"
    return None


def create_witness_app(
    *,
    state_path: str | Path = "witness.db",
    key_path: str | Path = "witness_key.json",
    name: str = "witness-1",
    alg_id: str | None = None,
    backend: str = "quantcrypt",
) -> Flask:
    app = Flask(__name__)
    registry = build_registry(prefer=backend)
    identity = load_or_create(key_path, name=name, registry=registry, alg_id=alg_id)
    store = WitnessStore(state_path)

    app.config["WITNESS_IDENTITY"] = identity
    app.config["WITNESS_STORE"] = store
    app.extensions["crypto"] = registry

    # -- what we last saw -----------------------------------------------------------------

    @app.get("/state")
    def state():
        origin = request.args.get("origin", "")
        latest = store.latest(origin) if origin else None
        pinned = store.known_log(origin) if origin else None
        return jsonify(
            {
                **identity.public_dict(),
                "origin": origin,
                "tree_size": latest["tree_size"] if latest else None,
                "root_hash": latest["root_hash"] if latest else None,
                "log_key_fingerprint": (
                    sha256_hex(pinned["log_public_key"])[:16] if pinned else None
                ),
            }
        )

    # -- the decision ---------------------------------------------------------------------

    @app.post("/cosign")
    def cosign():
        body = request.get_json(silent=True) or {}
        statement = body.get("checkpoint")
        if (problem := _valid_statement(statement)) is not None:
            return _bad(problem)

        origin = statement["origin"]
        try:
            log_public_key = b64decode(body.get("log_public_key_b64", ""))
            log_signature = b64decode(body.get("log_signature_b64", ""))
        except (ValueError, TypeError):
            return _bad("log_public_key_b64 and log_signature_b64 must be base64")
        log_alg_id = body.get("log_alg_id", "")
        if not registry.has_signature(log_alg_id):
            return _bad(f"unknown log algorithm {log_alg_id!r}")

        # 1. Identity. The first key seen for an origin is that origin's key, forever.
        pinned = store.known_log(origin)
        if pinned is None:
            store.pin_log(origin, log_alg_id, log_public_key)
        elif bytes(pinned["log_public_key"]) != log_public_key:
            store.record_violation(
                origin,
                "key_changed",
                f"pinned {sha256_hex(bytes(pinned['log_public_key']))[:16]}, "
                f"offered {sha256_hex(log_public_key)[:16]}",
                statement,
            )
            return _bad("log public key does not match the key pinned for this origin", 409)

        # 2. Authenticity. Only the log itself may move its own high-water mark; without this an
        #    unrelated party could park a huge tree_size here and lock the real log out forever.
        message = checkpoint_bytes(statement)
        if not registry.signature(log_alg_id).verify(log_public_key, message, log_signature):
            store.record_violation(origin, "bad_signature", "log signature did not verify", statement)
            return _bad("log signature over the checkpoint did not verify", 409)

        # 3. Monotonicity and consistency — the reason this process exists.
        latest = store.latest(origin)
        if latest is not None:
            old_size, new_size = latest["tree_size"], statement["tree_size"]
            if new_size < old_size:
                store.record_violation(
                    origin,
                    "shrank",
                    f"co-signed {old_size} entries previously; offered {new_size}",
                    statement,
                )
                return _bad(
                    f"log shrank: this witness has co-signed {old_size} entries, "
                    f"and was offered {new_size}",
                    409,
                )
            if new_size == old_size:
                if latest["root_hash"] != statement["root_hash"]:
                    store.record_violation(
                        origin,
                        "fork",
                        f"two roots at size {new_size}: {latest['root_hash']} then "
                        f"{statement['root_hash']}",
                        statement,
                    )
                    return _bad(f"fork: a different root was already co-signed at size {new_size}", 409)
                # Same size, same root. Reissue the stored signature only if the offered statement
                # is byte-identical to the one it was made over — matching on (size, root) alone
                # was a bug: a checkpoint re-created after a restart carries a new `timestamp`, so
                # the reissued signature verified against nothing the caller held, and the
                # co-signature was silently discarded at the far end. Same tree, different
                # statement is not a fork; it is simply a new statement, and gets signed as one.
                if json.loads(latest["statement_json"]) == statement:
                    return jsonify(
                        {
                            **identity.public_dict(),
                            "signature_b64": b64encode(bytes(latest["cosignature"])).decode(),
                            "tree_size": new_size,
                            "reissued": True,
                        }
                    )
            proof = [bytes.fromhex(h) for h in body.get("consistency_proof", [])]
            if not verify_consistency(
                old_size=old_size,
                old_root=bytes.fromhex(latest["root_hash"]),
                new_size=new_size,
                new_root=bytes.fromhex(statement["root_hash"]),
                proof=proof,
            ):
                store.record_violation(
                    origin,
                    "inconsistent",
                    f"no valid consistency proof from {old_size} to {new_size}",
                    statement,
                )
                return _bad(
                    f"the tree of {new_size} entries does not provably contain the tree of "
                    f"{old_size} entries this witness already co-signed",
                    409,
                )

        # 4. Co-sign. Verify-after-sign, for the same reason the log does it: a co-signature that
        #    does not verify would be published and would read as the log's failure, not ours.
        provider = registry.signature(identity.alg_id)
        to_sign = witness_bytes(witness=identity.name, statement=statement)
        signature = provider.sign(identity.secret_key, to_sign)
        if not provider.verify(identity.public_key, to_sign, signature):
            return _bad("witness signature failed self-verification", 500)

        store.record(origin, statement, signature)
        return jsonify(
            {
                **identity.public_dict(),
                "signature_b64": b64encode(signature).decode(),
                "tree_size": statement["tree_size"],
                "reissued": False,
            }
        )

    # -- the record -----------------------------------------------------------------------

    @app.get("/")
    def index():
        origins = []
        for row in store.origins():
            latest = store.latest(row["origin"])
            origins.append(
                {
                    "origin": row["origin"],
                    "log_alg_id": row["log_alg_id"],
                    "log_fingerprint": sha256_hex(bytes(row["log_public_key"]))[:16],
                    "first_seen": row["first_seen"],
                    "tree_size": latest["tree_size"] if latest else None,
                    "root_hash": latest["root_hash"] if latest else None,
                    "history": [
                        {
                            "tree_size": h["tree_size"],
                            "root_hash": h["root_hash"],
                            "seen_at": h["seen_at"],
                        }
                        for h in store.history(row["origin"], limit=10)
                    ],
                }
            )
        return render_template_string(
            _PAGE,
            identity=identity,
            origins=origins,
            violations=[dict(v) for v in store.violations(limit=25)],
            state_path=store.path,
        )

    return app


_PAGE = """<!doctype html>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ identity.name }} — transparency log witness</title>
<style>
  :root { color-scheme: light dark; }
  body { font: 14px/1.55 ui-monospace, "SF Mono", Menlo, Consolas, monospace;
         max-width: 60rem; margin: 3rem auto; padding: 0 1.5rem;
         background: #101014; color: #d8d8d2; }
  h1 { font-size: 1.15rem; letter-spacing: .02em; margin: 0 0 .25rem; }
  h2 { font-size: .8rem; text-transform: uppercase; letter-spacing: .12em;
       color: #8a8a94; margin: 2.5rem 0 .75rem; font-weight: 600; }
  .sub { color: #8a8a94; margin: 0 0 2rem; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; font-weight: 600; color: #8a8a94; font-size: .75rem;
       text-transform: uppercase; letter-spacing: .08em; padding: .4rem .6rem .4rem 0; }
  td { padding: .35rem .6rem .35rem 0; border-top: 1px solid #26262e; vertical-align: top; }
  .hash { color: #6f9fd8; word-break: break-all; }
  .ok { color: #4f9f76; } .bad { color: #d2685c; }
  .empty { color: #6a6a74; font-style: italic; }
  code { background: #1a1a20; padding: .1rem .35rem; border-radius: 3px; }
</style>
<h1>{{ identity.name }}</h1>
<p class="sub">
  An independent witness. It co-signs a log's checkpoint only when that checkpoint provably
  contains everything it has already co-signed.<br>
  Signing with <strong>{{ identity.alg_id }}</strong> ·
  key fingerprint <span class="hash">{{ identity.fingerprint() }}</span> ·
  state in <code>{{ state_path }}</code>
</p>

<h2>Logs</h2>
{% if not origins %}<p class="empty">No log has contacted this witness yet.</p>{% endif %}
{% for o in origins %}
  <table>
    <tr><th style="width:12rem">Origin</th><td>{{ o.origin }}</td></tr>
    <tr><th>Log key</th>
        <td>{{ o.log_alg_id }} · <span class="hash">{{ o.log_fingerprint }}</span>
            <span class="empty">pinned {{ o.first_seen }}</span></td></tr>
    <tr><th>Co-signed to</th>
        <td>{% if o.tree_size %}{{ o.tree_size }} entries ·
            <span class="hash">{{ o.root_hash }}</span>{% else %}
            <span class="empty">nothing</span>{% endif %}</td></tr>
  </table>
  <table style="margin-top:.75rem">
    <tr><th style="width:12rem">Size</th><th>Root</th><th style="width:14rem">Seen</th></tr>
    {% for h in o.history %}
      <tr><td>{{ h.tree_size }}</td><td class="hash">{{ h.root_hash }}</td><td>{{ h.seen_at }}</td></tr>
    {% endfor %}
  </table>
{% endfor %}

<h2>Refusals</h2>
{% if not violations %}
  <p class="ok">None. Every checkpoint offered so far extended the one before it.</p>
{% else %}
  <table>
    <tr><th style="width:9rem">Kind</th><th>Detail</th><th style="width:14rem">Seen</th></tr>
    {% for v in violations %}
      <tr><td class="bad">{{ v.kind }}</td><td>{{ v.detail }}</td><td>{{ v.seen_at }}</td></tr>
    {% endfor %}
  </table>
{% endif %}
"""
