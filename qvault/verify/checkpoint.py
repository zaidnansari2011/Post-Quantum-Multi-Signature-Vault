"""Check a Q-Vault log's public signed head (``/transparency/checkpoint.json``) offline.

The document holds the log's newest signed head and the newest one a witness co-signed, each in
the shape a decision bundle's ``log`` section already uses. This module checks what can be checked
from the file alone: each head is internally consistent, the log's signature on it verifies, each
witness's co-signature verifies, both heads name one log (the ``origin`` inside the signed
statement), and, when the reader pins them, the keys are the expected ones.

What it cannot do on its own is prove the newest head extends the witnessed one (that needs a
consistency proof the document does not carry). Its use is the fingerprints: they are the values
to pass to ``--expect-log`` and ``--expect-witness`` when checking a decision. Fetched from the
server's public address they protect against a file someone hands you, not against the operator
who publishes them; the witness's own fingerprint, from the witness, is the stronger pin.

**Never raises.** A document of the wrong shape (a list, a string where a head belongs, a witness
that is not an object) is a failed check, so the command line can always print a verdict.

**Classical keys fail.** The log and the witness are meant to sign with post-quantum algorithms. A
key whose algorithm a quantum computer breaks outright (RSA, ECDSA: ``AlgMeta.quantum_vulnerable``)
is also cheap to make by the million, which is how a short pin gets ground; such a key is a failed
check unless the reader passes ``allow_classical`` (``--allow-classical``).

Same import boundary as the rest of ``qvault.verify``: no Flask, no database
(``tests/test_verifier_purity.py``).
"""

from __future__ import annotations

import binascii
from base64 import b64decode

from qvault.crypto import CryptoRegistry, sha256_hex
from qvault.transparency import checkpoint_bytes, witness_bytes
from qvault.verify.core import Check, Report, pin_check

CHECKPOINT_FORMAT = "qvault.checkpoint/1"


def is_checkpoint_document(doc: object) -> bool:
    return isinstance(doc, dict) and str(doc.get("format", "")).startswith("qvault.checkpoint/")


def _b64(value) -> bytes | None:
    if not isinstance(value, str):
        return None
    try:
        return b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None


def _classical(registry: CryptoRegistry, alg) -> bool:
    """Whether ``alg`` is a registered algorithm a quantum computer breaks outright."""
    if not isinstance(alg, str) or not registry.has_signature(alg):
        return False
    return bool(getattr(registry.signature(alg).meta, "quantum_vulnerable", False))


class _Head:
    """What one head contributed: its log key, the witnesses that verified, the signed origin,
    and any classical algorithm it used."""

    def __init__(self) -> None:
        self.log_sha: str | None = None
        self.witnesses: list[tuple[str, str]] = []  # (name, full SHA-256 of the key)
        self.origin: str | None = None
        self.classical: list[str] = []


def _head(label: str, head, registry: CryptoRegistry, report: Report) -> _Head:
    """Check one signed head and add its checks to ``report``."""
    add = report.checks.append
    out = _Head()
    statement = head.get("checkpoint") if isinstance(head, dict) else None
    sig = head.get("checkpoint_signature") if isinstance(head, dict) else None
    if not isinstance(statement, dict) or not isinstance(sig, dict):
        add(Check(f"{label}_log", f"The log signed the {label} head", False, "malformed head"))
        return out

    size, head_seq = statement.get("tree_size"), statement.get("head_seq")
    shape_ok = isinstance(size, int) and isinstance(head_seq, int) and size == head_seq + 1
    key, signature = _b64(sig.get("public_key_b64")), _b64(sig.get("signature_b64"))
    alg = sig.get("alg_id")
    log_sha = sha256_hex(key) if key else None
    if not shape_ok:
        ok, detail = False, f"tree_size {size} does not match head_seq {head_seq} + 1"
    elif not key or not signature or not isinstance(alg, str) or not registry.has_signature(alg):
        ok, detail = False, f"unreadable key or signature, or unknown algorithm {alg}"
    else:
        try:
            ok = registry.signature(alg).verify(key, checkpoint_bytes(statement), signature)
        except Exception:  # noqa: BLE001 - a malformed value is a failed check
            ok = False
        detail = (
            f"#{size}, {alg}, log key {log_sha[:16]}"
            if ok
            else "the log's signature did not verify"
        )
    add(Check(f"{label}_log", f"The log signed the {label} head", ok, detail))
    if ok:
        out.log_sha = log_sha
        origin = statement.get("origin")
        out.origin = origin if isinstance(origin, str) else None
        if _classical(registry, alg):
            out.classical.append(f"log key {log_sha[:16]} ({alg})")

    witnesses = head.get("witnesses")
    problems: list[str] = []
    if witnesses is None:
        witnesses = []
    if not isinstance(witnesses, list):
        problems.append("the witness list is not a list")
        witnesses = []
    for i, w in enumerate(witnesses):
        if not isinstance(w, dict):
            problems.append(f"witness {i + 1}: not a co-signature")
            continue
        name, w_alg = w.get("witness"), w.get("alg_id")
        w_key, w_sig = _b64(w.get("public_key_b64")), _b64(w.get("signature_b64"))
        verified = False
        if (
            ok
            and isinstance(name, str)
            and isinstance(w_alg, str)
            and w_key
            and w_sig
            and registry.has_signature(w_alg)
        ):
            try:
                verified = registry.signature(w_alg).verify(
                    w_key, witness_bytes(witness=name, statement=statement), w_sig
                )
            except Exception:  # noqa: BLE001
                verified = False
        if verified:
            out.witnesses.append((name, sha256_hex(w_key)))
            if _classical(registry, w_alg):
                out.classical.append(f"witness {name} key {sha256_hex(w_key)[:16]} ({w_alg})")
        else:
            problems.append(
                f"{name if isinstance(name, str) else i + 1}: co-signature did not verify"
            )

    # The witnessed head is the one the document says a witness co-signed: without a co-signature
    # that verifies, that claim is false, not merely unproven.
    if label == "witnessed" and not out.witnesses and not problems:
        problems.append("the head offered as witnessed carries no co-signature")
    if witnesses or problems:
        add(
            Check(
                f"{label}_witness",
                f"A witness co-signed the {label} head",
                not problems and bool(out.witnesses),
                "; ".join(problems) or ", ".join(f"{n} ({s[:16]})" for n, s in out.witnesses),
            )
        )
    return out


def verify_checkpoint_document(
    doc,
    *,
    registry: CryptoRegistry,
    expect_log: str | None = None,
    expect_witness: str | None = None,
    allow_classical: bool = False,
) -> Report:
    """Check the public head document. ``ok`` only when every present signature verifies, both
    heads name one log, no key is classical (unless allowed) and every pin matches; an absent
    witness is reported, not counted as a failure. Never raises."""
    report = Report(ok=False)
    add = report.checks.append
    if not isinstance(doc, dict) or doc.get("format") != CHECKPOINT_FORMAT:
        found = doc.get("format") if isinstance(doc, dict) else type(doc).__name__
        add(Check("format", "A format this verifier knows", False, f"found {found!r}"))
        report.summary = "Unsupported format"
        report.fingerprints = {"log": None, "witnesses": []}
        return report

    heads: dict[str, _Head] = {}
    for label in ("latest", "witnessed"):
        head = doc.get(label)
        if head is not None:
            heads[label] = _head(label, head, registry, report)

    if doc.get("latest") is None:
        add(Check("latest_log", "The log signed the latest head", False, "no signed head yet"))
    if doc.get("witnessed") is None:
        add(
            Check(
                "witness",
                "A witness co-signed a head",
                False,
                "no witness co-signature"
                + (" yet" if doc.get("witness_configured") else ": no witness is configured"),
                skipped=True,
            )
        )

    log_shas = sorted({h.log_sha for h in heads.values() if h.log_sha})
    if len(log_shas) > 1:
        add(
            Check(
                "one_log",
                "Both heads are signed by one log key",
                False,
                ", ".join(s[:16] for s in log_shas),
            )
        )

    # The origin names the log inside the signed bytes; the top-level copy is a convenience and
    # is believed only when it agrees.
    origins = {h.origin for h in heads.values() if h.log_sha}
    origin = next(iter(origins)) if len(origins) == 1 else None
    if len(origins) > 1:
        add(
            Check(
                "one_origin",
                "Both heads name the same log",
                False,
                "the heads name " + " and ".join(sorted(str(o) for o in origins)),
            )
        )
    elif origins and doc.get("origin") is not None and doc.get("origin") != origin:
        add(
            Check(
                "origin",
                "The document names the log its heads signed",
                False,
                f"the document says {doc.get('origin')!r}, the signed heads say {origin!r}",
            )
        )

    classical = [c for h in heads.values() for c in h.classical]
    if classical:
        add(
            Check(
                "post_quantum",
                "The log and witness keys are post-quantum",
                allow_classical,
                "classical, which a quantum computer breaks: "
                + "; ".join(sorted(set(classical)))
                + (" (allowed by --allow-classical)" if allow_classical else ""),
            )
        )

    witnesses: dict[str, str] = {}
    for h in heads.values():
        for name, sha in h.witnesses:
            witnesses.setdefault(sha, name)
    report.fingerprints = {
        "log": log_shas[0][:16] if len(log_shas) == 1 else None,
        "witnesses": [
            {"fingerprint": sha[:16], "name": name} for sha, name in sorted(witnesses.items())
        ],
    }
    if expect_log is not None:
        add(pin_check("pinned_log", "The log key is the one you expected", expect_log, log_shas))
    if expect_witness is not None:
        add(
            pin_check(
                "pinned_witness",
                "The witness key is the one you expected",
                expect_witness,
                sorted(witnesses),
            )
        )

    report.ok = not report.failures and "latest" in heads
    latest = doc.get("latest")
    statement = latest.get("checkpoint") if isinstance(latest, dict) else None
    size = statement.get("tree_size") if isinstance(statement, dict) else None
    report.facts = {"origin": origin, "tree_size": size if "latest" in heads else None}
    report.summary = "Signed head verified" if report.ok else "Signed head not verified"
    return report
