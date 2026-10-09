"""Check a Q-Vault log's public signed head (``/transparency/checkpoint.json``) offline.

The document holds the log's newest signed head and the newest one a witness co-signed, each in
the shape a decision bundle's ``log`` section already uses. This module checks what can be checked
from the file alone: each head is internally consistent, the log's signature on it verifies, each
witness's co-signature verifies, and, when the reader pins them, the keys are the expected ones.

What it cannot do on its own is prove the newest head extends the witnessed one (that needs a
consistency proof the document does not carry). Its use is the fingerprints: fetched from the
server's public address rather than from a file someone handed you, they are the values to pass
to ``--expect-log`` and ``--expect-witness`` when checking a decision.

Same import boundary as the rest of ``qvault.verify``: no Flask, no database
(``tests/test_verifier_purity.py``).
"""

from __future__ import annotations

import binascii
from base64 import b64decode

from qvault.crypto import CryptoRegistry, sha256_hex
from qvault.transparency import checkpoint_bytes, witness_bytes
from qvault.verify.core import Check, Report

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


def _head(label: str, head: dict, registry: CryptoRegistry, report: Report) -> tuple:
    """Check one signed head; returns (log fingerprint, [witness fingerprints that verified])."""
    add = report.checks.append
    statement = head.get("checkpoint") if isinstance(head, dict) else None
    sig = head.get("checkpoint_signature") if isinstance(head, dict) else None
    if not isinstance(statement, dict) or not isinstance(sig, dict):
        add(Check(f"{label}_log", f"The log signed the {label} head", False, "malformed head"))
        return None, []

    size, head_seq = statement.get("tree_size"), statement.get("head_seq")
    shape_ok = isinstance(size, int) and isinstance(head_seq, int) and size == head_seq + 1
    key, signature = _b64(sig.get("public_key_b64")), _b64(sig.get("signature_b64"))
    alg = sig.get("alg_id")
    log_fp = sha256_hex(key)[:16] if key else None
    if not shape_ok:
        ok, detail = False, f"tree_size {size} does not match head_seq {head_seq} + 1"
    elif not key or not signature or not registry.has_signature(str(alg)):
        ok, detail = False, f"unreadable key or signature, or unknown algorithm {alg}"
    else:
        try:
            ok = registry.signature(alg).verify(key, checkpoint_bytes(statement), signature)
        except Exception:  # noqa: BLE001 - a malformed value is a failed check
            ok = False
        detail = f"#{size}, {alg}, log key {log_fp}" if ok else "the log's signature did not verify"
    add(Check(f"{label}_log", f"The log signed the {label} head", ok, detail))

    good: list[str] = []
    problems: list[str] = []
    for w in head.get("witnesses") or []:
        name, w_alg = w.get("witness"), w.get("alg_id")
        w_key, w_sig = _b64(w.get("public_key_b64")), _b64(w.get("signature_b64"))
        verified = False
        if w_key and w_sig and registry.has_signature(str(w_alg)):
            try:
                verified = registry.signature(w_alg).verify(
                    w_key, witness_bytes(witness=name, statement=statement), w_sig
                )
            except Exception:  # noqa: BLE001
                verified = False
        if verified:
            good.append(sha256_hex(w_key)[:16])
        else:
            problems.append(f"{name}: co-signature did not verify")
    if head.get("witnesses"):
        add(
            Check(
                f"{label}_witness",
                f"A witness co-signed the {label} head",
                not problems,
                "; ".join(problems) or ", ".join(good),
            )
        )
    return (log_fp if ok else None), good


def verify_checkpoint_document(
    doc: dict,
    *,
    registry: CryptoRegistry,
    expect_log: str | None = None,
    expect_witness: str | None = None,
) -> Report:
    """Check the public head document. ``ok`` only when every present signature verifies and
    every pinned fingerprint matches; an absent witness is reported, not counted as a failure."""
    report = Report(ok=False)
    add = report.checks.append
    if doc.get("format") != CHECKPOINT_FORMAT:
        add(Check("format", "A format this verifier knows", False, str(doc.get("format"))))
        report.summary = "Unsupported format"
        return report

    log_fps: set[str] = set()
    witness_fps: list[str] = []
    for label in ("latest", "witnessed"):
        head = doc.get(label)
        if head is None:
            continue
        fp, good = _head(label, head, registry, report)
        if fp:
            log_fps.add(fp)
        witness_fps += good

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
    if len(log_fps) > 1:
        add(Check("one_log", "Both heads are signed by one log key", False, ", ".join(log_fps)))

    report.fingerprints = {"log": next(iter(log_fps), None), "witnesses": sorted(set(witness_fps))}
    if expect_log is not None:
        actual = report.fingerprints["log"]
        add(
            Check(
                "pinned_log",
                "The log key is the one you expected",
                bool(actual) and actual.startswith(expect_log.lower()),
                f"expected {expect_log}, found {actual}",
            )
        )
    if expect_witness is not None:
        found = report.fingerprints["witnesses"]
        add(
            Check(
                "pinned_witness",
                "The witness key is the one you expected",
                any(f.startswith(expect_witness.lower()) for f in found),
                f"expected {expect_witness}, found {', '.join(found) or 'none'}",
            )
        )

    report.ok = not report.failures
    latest = (doc.get("latest") or {}).get("checkpoint") or {}
    report.facts = {"origin": doc.get("origin"), "tree_size": latest.get("tree_size")}
    report.summary = "Signed head verified" if report.ok else "Signed head not verified"
    return report
