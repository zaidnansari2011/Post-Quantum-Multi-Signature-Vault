"""Verify an exported decision bundle without trusting the server that produced it.

The shape of the argument
-------------------------
The checks below are ordered as a chain of reasoning, not as a checklist, and each one closes a
gap the previous one leaves open. Read top to bottom it says:

1. **content** — the text in front of you is the text that was hashed;
2. **signatures** — real post-quantum signatures over exactly that;
3. **authorisation** — by people the proposal named as signers *when it opened*;
4. **threshold** — enough of them to meet the rule that was frozen at the same moment;
5. **log entries** — the audit log's own records of those events recompute;
6. **binding** — and those records name these exact signature bytes, so the export cannot be a
   different set of signatures dressed up in the same log;
7. **inclusion** — those records are provably inside a published Merkle tree;
8. **checkpoint** — that tree's root is signed by the log;
9. **witness** — and countersigned by a party that keeps its own append-only record, so the log
   cannot have quietly dropped or rewritten anything since;
10. **pinned keys** — and the keys involved are the ones you were told to expect.

Steps 1-4 alone are what a naive "export the signatures" format gives you, and they are worth
much less than they look: the server chooses what to put in the file, so it can simply omit a
rejection, or export a decision that never happened. Steps 5-9 are what stop that, and step 9 is
the only one that survives the server's operator being the adversary.

Why the public keys are not in the log
--------------------------------------
A reasonable objection to step 6: the ledger records a signature's **hash**, its signer and its
decision, but not the signer's public key — so could the exporter substitute a public key it
controls? No. The message is pinned (it is derived from ``payload_hash``, ``signer_id`` and
``decision``, all three recorded in the log) and the signature bytes are pinned by their hash. A
substituted public key would therefore have to verify a *fixed* signature over a *fixed* message,
which is an existential forgery of ML-DSA. The log commits to the key implicitly, by committing to
something only that key could have produced.

What a passing report does not tell you
---------------------------------------
That the log operator is honest. It tells you they have not been *inconsistently* dishonest: every
claim here is checkable against a Merkle tree that an independent witness has confirmed only ever
grew. A log that never showed anyone the entry in the first place is out of scope for any
transparency system, and is why real deployments gossip checkpoints between clients.
"""

from __future__ import annotations

import binascii
import json
from base64 import b64decode
from dataclasses import dataclass, field
from typing import Any

from qvault.crypto import CryptoRegistry, sha256_hex
from qvault.services.signing import proposal_signing_bytes, vote_signing_bytes
from qvault.transparency import (
    checkpoint_bytes,
    entry_leaf_hash,
    verify_inclusion,
    witness_bytes,
)
from qvault.transparency.statement import entry_hash as compute_entry_hash

#: Bump the minor part for additive fields; the major part is a compatibility break, and a
#: verifier that does not recognise the major version must refuse rather than guess.
BUNDLE_FORMAT = "qvault.decision/1"


@dataclass
class Check:
    """One step of the argument."""

    key: str
    title: str
    ok: bool
    detail: str
    # Not every bundle can answer every question — an unwitnessed log has no witness to check.
    # A skipped step is neither pass nor fail and must not be silently counted as either.
    skipped: bool = False


@dataclass
class Report:
    ok: bool
    checks: list[Check] = field(default_factory=list)
    summary: str = ""
    facts: dict = field(default_factory=dict)
    fingerprints: dict = field(default_factory=dict)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.ok and not c.skipped]

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "summary": self.summary,
            "facts": self.facts,
            "fingerprints": self.fingerprints,
            "checks": [
                {
                    "key": c.key,
                    "title": c.title,
                    "ok": c.ok,
                    "skipped": c.skipped,
                    "detail": c.detail,
                }
                for c in self.checks
            ],
        }


class _Malformed(Exception):
    """The bundle is not shaped like a bundle. Distinct from 'the bundle is shaped right and
    the claims in it are false', which is a verification failure rather than a parse failure."""


def _b64(value: Any, what: str) -> bytes:
    if not isinstance(value, str):
        raise _Malformed(f"{what} must be a base64 string")
    try:
        return b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise _Malformed(f"{what} is not valid base64: {exc}") from None


def _hex32(value: Any, what: str) -> bytes:
    if not isinstance(value, str) or len(value) != 64:
        raise _Malformed(f"{what} must be 64 hex characters")
    try:
        return bytes.fromhex(value)
    except ValueError:
        raise _Malformed(f"{what} is not hex") from None


def _need(obj: Any, key: str, what: str) -> Any:
    if not isinstance(obj, dict) or key not in obj:
        raise _Malformed(f"{what} is missing {key!r}")
    return obj[key]


def verify_bundle(
    bundle: Any,
    *,
    registry: CryptoRegistry,
    expect_log: str | None = None,
    expect_witness: str | None = None,
) -> Report:
    """Check an exported decision. Never raises; a malformed bundle is a failing report.

    ``expect_log`` / ``expect_witness`` are SHA-256 fingerprint prefixes the caller obtained out of
    band. Supplying them is what converts "signed by *a* log" into "signed by *the* log", and the
    report says plainly which of the two it is checking.
    """
    report = Report(ok=False)
    add = report.checks.append

    try:
        _verify_into(report, bundle, registry, expect_log, expect_witness)
    except _Malformed as exc:
        add(Check("format", "The file is a Q-Vault decision bundle", False, str(exc)))
    except Exception as exc:  # noqa: BLE001 - a verifier that crashes teaches the reader nothing
        add(Check("internal", "Verification completed", False, f"unexpected error: {exc!r}"))

    graded = [c for c in report.checks if not c.skipped]
    report.ok = bool(graded) and all(c.ok for c in graded)
    if report.ok:
        skipped = [c for c in report.checks if c.skipped]
        report.summary = "Verified" + (f" ({len(skipped)} check(s) not applicable)" if skipped else "")
    else:
        first = report.failures[0] if report.failures else None
        report.summary = f"NOT verified — {first.detail}" if first else "NOT verified"
    return report


def _verify_into(
    report: Report,
    bundle: Any,
    registry: CryptoRegistry,
    expect_log: str | None,
    expect_witness: str | None,
) -> None:
    add = report.checks.append

    # ---------------------------------------------------------------------------------------
    # 0. Format
    # ---------------------------------------------------------------------------------------
    if not isinstance(bundle, dict):
        raise _Malformed("bundle must be a JSON object")
    fmt = bundle.get("format")
    if not isinstance(fmt, str) or "/" not in fmt:
        raise _Malformed(f"unrecognised format {fmt!r}")
    family, _, major = fmt.rpartition("/")
    expected_family, _, expected_major = BUNDLE_FORMAT.rpartition("/")
    if family != expected_family or major != expected_major:
        raise _Malformed(
            f"this verifier understands {BUNDLE_FORMAT}, the bundle claims {fmt}"
        )
    add(Check("format", "The file is a Q-Vault decision bundle", True, fmt))

    decision = _need(bundle, "decision", "bundle")
    signatures = _need(bundle, "signatures", "bundle")
    log = _need(bundle, "log", "bundle")
    if not isinstance(signatures, list):
        raise _Malformed("signatures must be a list")

    # ---------------------------------------------------------------------------------------
    # 1. The content is what was hashed
    # ---------------------------------------------------------------------------------------
    signers_claimed = _need(decision, "authorized_signers", "decision")
    if not isinstance(signers_claimed, list) or not all(isinstance(s, int) for s in signers_claimed):
        raise _Malformed("decision.authorized_signers must be a list of integers")

    recomputed_bytes = proposal_signing_bytes(
        vault_id=_need(decision, "vault_id", "decision"),
        proposal_uuid=_need(decision, "proposal_uuid", "decision"),
        action_text=_need(decision, "action_text", "decision"),
        file_sha256=decision.get("file_sha256"),
        required_m=_need(decision, "required_m", "decision"),
        required_n=_need(decision, "required_n", "decision"),
        authorized_signers=signers_claimed,
        nonce_hex=_need(decision, "nonce_hex", "decision"),
        created_at_iso=_need(decision, "created_at_iso", "decision"),
    )
    recomputed_hash = sha256_hex(recomputed_bytes)
    claimed_hash = _need(decision, "payload_hash", "decision")
    content_ok = recomputed_hash == claimed_hash
    add(
        Check(
            "content",
            "The decision text is the text that was signed",
            content_ok,
            (
                f"recomputed {recomputed_hash[:16]}…"
                if content_ok
                else f"recomputed {recomputed_hash[:16]}…, bundle claims {str(claimed_hash)[:16]}…"
            ),
        )
    )

    report.facts = {
        "proposal_uuid": decision.get("proposal_uuid"),
        "title": decision.get("title"),
        "vault": decision.get("vault_name"),
        "action_text": decision.get("action_text"),
        "status": decision.get("status"),
        "required_m": decision.get("required_m"),
        "required_n": decision.get("required_n"),
        "payload_hash": recomputed_hash,
        "created_at": decision.get("created_at_iso"),
    }

    # ---------------------------------------------------------------------------------------
    # 2. Every signature verifies — over the RECOMPUTED hash, so a content mismatch cascades
    #    here rather than being papered over by the exporter's own claim.
    # ---------------------------------------------------------------------------------------
    verified: list[dict] = []
    problems: list[str] = []
    algs: set[str] = set()
    for i, entry in enumerate(signatures):
        where = f"signatures[{i}]"
        signer_id = _need(entry, "signer_id", where)
        vote = _need(entry, "decision", where)
        alg_id = _need(entry, "alg_id", where)
        public_key = _b64(_need(entry, "public_key_b64", where), f"{where}.public_key_b64")
        signature = _b64(_need(entry, "signature_b64", where), f"{where}.signature_b64")
        algs.add(alg_id)

        if not registry.has_signature(alg_id):
            problems.append(f"{entry.get('signer_email', signer_id)}: unknown algorithm {alg_id}")
            continue
        if vote not in ("approve", "reject"):
            problems.append(f"{entry.get('signer_email', signer_id)}: invalid decision {vote!r}")
            continue

        message = vote_signing_bytes(
            proposal_payload_hash=recomputed_hash, decision=vote, signer_id=signer_id
        )
        if registry.signature(alg_id).verify(public_key, message, signature):
            verified.append({**entry, "_signature": signature, "_public_key": public_key})
        else:
            problems.append(f"{entry.get('signer_email', signer_id)}: signature did not verify")

    add(
        Check(
            "signatures",
            "Each signature is a valid post-quantum signature over it",
            not problems and bool(signatures),
            (
                f"{len(verified)} of {len(signatures)} verified"
                + (f" using {', '.join(sorted(algs))}" if algs else "")
                if not problems
                else "; ".join(problems)
            )
            if signatures
            else "the bundle carries no signatures",
        )
    )

    # ---------------------------------------------------------------------------------------
    # 3. Authorisation, against the signer set frozen when the decision opened — not against
    #    whoever is a member today, which is the same distinction cast_vote enforces server-side.
    # ---------------------------------------------------------------------------------------
    authorised = set(signers_claimed)
    intruders = [
        str(s.get("signer_email", s["signer_id"])) for s in verified if s["signer_id"] not in authorised
    ]
    seen: set[int] = set()
    duplicates = []
    for s in verified:
        if s["signer_id"] in seen:
            duplicates.append(str(s.get("signer_email", s["signer_id"])))
        seen.add(s["signer_id"])
    add(
        Check(
            "authorisation",
            "Every signer was authorised when the decision opened",
            not intruders and not duplicates,
            "; ".join(
                [
                    *(f"{n} was not an authorised signer" for n in intruders),
                    *(f"{n} signed more than once" for n in duplicates),
                ]
            )
            or f"{len(authorised)} authorised signer(s)",
        )
    )

    # ---------------------------------------------------------------------------------------
    # 4. The threshold that was frozen with the signer set
    # ---------------------------------------------------------------------------------------
    required_m = decision["required_m"]
    approvals = [s for s in verified if s["decision"] == "approve" and s["signer_id"] in authorised]
    rejections = [s for s in verified if s["decision"] == "reject" and s["signer_id"] in authorised]
    status = decision.get("status")
    if status == "approved":
        met = len(approvals) >= required_m
        detail = f"{len(approvals)} of {required_m} required approvals"
    elif status == "rejected":
        met = len(rejections) > decision["required_n"] - required_m
        detail = f"{len(rejections)} rejection(s) make {required_m} approvals unreachable"
    else:
        met = len(approvals) < required_m
        detail = f"{status}: {len(approvals)} of {required_m} approvals so far"
    add(Check("threshold", "The approval rule was satisfied", met, detail))

    # ---------------------------------------------------------------------------------------
    # 5-6. The log's own records, and their binding to these exact signatures
    # ---------------------------------------------------------------------------------------
    entries = _need(log, "entries", "log")
    if not isinstance(entries, list) or not entries:
        raise _Malformed("log.entries must be a non-empty list")

    by_seq: dict[int, dict] = {}
    bad_entries: list[str] = []
    for raw in entries:
        seq = _need(raw, "seq", "log entry")
        payload_json = _need(raw, "payload_json", "log entry")
        payload_hash = _need(raw, "payload_hash", "log entry")
        if sha256_hex(payload_json.encode("utf-8")) != payload_hash:
            bad_entries.append(f"entry {seq}: stored payload does not match its hash")
            continue
        recomputed = compute_entry_hash(
            seq=seq,
            timestamp=_need(raw, "timestamp", "log entry"),
            actor=_need(raw, "actor", "log entry"),
            event_type=_need(raw, "event_type", "log entry"),
            payload_hash=payload_hash,
            prev_hash=_need(raw, "prev_hash", "log entry"),
            actor_id=raw.get("actor_id"),
            vault_id=raw.get("vault_id"),
            ref_type=raw.get("ref_type"),
            ref_id=raw.get("ref_id"),
        )
        if recomputed != raw.get("entry_hash"):
            bad_entries.append(f"entry {seq}: fields do not hash to its recorded hash")
            continue
        by_seq[seq] = raw

    add(
        Check(
            "log_entries",
            "The audit log's records of these events recompute",
            not bad_entries,
            "; ".join(bad_entries) or f"{len(by_seq)} entr{'y' if len(by_seq) == 1 else 'ies'}",
        )
    )

    uuid = decision["proposal_uuid"]
    payloads = [(raw, json.loads(raw["payload_json"])) for raw in by_seq.values()]
    binding: list[str] = []

    created = [p for raw, p in payloads if raw["event_type"] == "proposal_created"]
    if not created:
        binding.append("the log entry that opened this decision is not in the bundle")
    elif created[0].get("payload_hash") != recomputed_hash:
        binding.append("the log recorded a different payload hash for this decision")

    signed_events = {
        (p.get("signer_id"), p.get("decision"), p.get("signature_sha256"))
        for raw, p in payloads
        if raw["event_type"] == "proposal_signed" and raw.get("ref_id") == uuid
    }
    for s in verified:
        want = (s["signer_id"], s["decision"], sha256_hex(s["_signature"]))
        if want not in signed_events:
            binding.append(
                f"the log has no record of {s.get('signer_email', s['signer_id'])} "
                f"casting this exact signature"
            )
    if len(signed_events) > len(verified):
        binding.append(
            f"the log records {len(signed_events)} signature(s) but the bundle carries "
            f"{len(verified)} — the export is incomplete"
        )

    add(
        Check(
            "binding",
            "The log records these exact signatures, and no others",
            not binding,
            "; ".join(binding) or f"{len(signed_events)} signing event(s) matched",
        )
    )

    # ---------------------------------------------------------------------------------------
    # 6b. Identity. Without this, "signer 3" could be labelled with any email the exporter liked;
    #     the registration entry is where the log itself binds an account id to an address.
    # ---------------------------------------------------------------------------------------
    registrations = {
        p.get("user_id"): p.get("email")
        for raw, p in payloads
        if raw["event_type"] == "user_registered"
    }
    identity: list[str] = []
    for s in verified:
        claimed = s.get("signer_email")
        recorded = registrations.get(s["signer_id"])
        if recorded is None:
            identity.append(f"the log has no registration record for signer {s['signer_id']}")
        elif claimed is not None and claimed != recorded:
            identity.append(
                f"the bundle calls signer {s['signer_id']} {claimed!r}, the log recorded {recorded!r}"
            )
    add(
        Check(
            "identity",
            "The signers are the accounts the log recorded",
            not identity,
            "; ".join(identity)
            or ", ".join(sorted(str(v) for v in registrations.values() if v)),
        )
    )

    # ---------------------------------------------------------------------------------------
    # 7. Inclusion in the published tree
    # ---------------------------------------------------------------------------------------
    checkpoint = _need(log, "checkpoint", "log")
    tree_size = _need(checkpoint, "tree_size", "checkpoint")
    root = _hex32(_need(checkpoint, "root_hash", "checkpoint"), "checkpoint.root_hash")

    not_included: list[str] = []
    for seq, raw in sorted(by_seq.items()):
        proof_hex = raw.get("inclusion_proof")
        if not isinstance(proof_hex, list):
            not_included.append(f"entry {seq}: no inclusion proof")
            continue
        try:
            proof = [bytes.fromhex(h) for h in proof_hex]
        except (ValueError, TypeError):
            not_included.append(f"entry {seq}: malformed inclusion proof")
            continue
        if not verify_inclusion(
            leaf=entry_leaf_hash(raw["entry_hash"]),
            index=seq,
            tree_size=tree_size,
            proof=proof,
            root=root,
        ):
            not_included.append(f"entry {seq}: not in the published log")

    add(
        Check(
            "inclusion",
            "Those records are inside the published transparency log",
            not not_included,
            "; ".join(not_included)
            or f"proved against a log of {tree_size} entries, root {root.hex()[:16]}…",
        )
    )

    # ---------------------------------------------------------------------------------------
    # 8. The checkpoint is the log's own statement
    # ---------------------------------------------------------------------------------------
    if checkpoint.get("tree_size") != (checkpoint.get("head_seq") or 0) + 1:
        add(
            Check(
                "checkpoint",
                "The log signed that tree",
                False,
                f"tree_size {checkpoint.get('tree_size')} does not match head_seq "
                f"{checkpoint.get('head_seq')} + 1 — entries are missing from the middle",
            )
        )
    else:
        cp_sig = _need(log, "checkpoint_signature", "log")
        cp_alg = _need(cp_sig, "alg_id", "checkpoint_signature")
        cp_key = _b64(_need(cp_sig, "public_key_b64", "checkpoint_signature"), "log public key")
        cp_bytes = _b64(_need(cp_sig, "signature_b64", "checkpoint_signature"), "log signature")
        log_fp = sha256_hex(cp_key)[:16]
        report.fingerprints["log"] = log_fp

        if not registry.has_signature(cp_alg):
            add(Check("checkpoint", "The log signed that tree", False, f"unknown algorithm {cp_alg}"))
        else:
            valid = registry.signature(cp_alg).verify(
                cp_key, checkpoint_bytes(checkpoint), cp_bytes
            )
            add(
                Check(
                    "checkpoint",
                    "The log signed that tree",
                    valid,
                    f"{cp_alg}, log key {log_fp}"
                    if valid
                    else "the checkpoint signature did not verify",
                )
            )

    # ---------------------------------------------------------------------------------------
    # 9. An independent witness countersigned it
    # ---------------------------------------------------------------------------------------
    witnesses = log.get("witnesses") or []
    if not isinstance(witnesses, list):
        raise _Malformed("log.witnesses must be a list")

    good_witnesses: list[tuple[str, str]] = []
    witness_problems: list[str] = []
    for i, w in enumerate(witnesses):
        where = f"witnesses[{i}]"
        name = _need(w, "witness", where)
        alg = _need(w, "alg_id", where)
        key = _b64(_need(w, "public_key_b64", where), f"{where}.public_key_b64")
        sig = _b64(_need(w, "signature_b64", where), f"{where}.signature_b64")
        if not registry.has_signature(alg):
            witness_problems.append(f"{name}: unknown algorithm {alg}")
            continue
        if registry.signature(alg).verify(key, witness_bytes(witness=name, statement=checkpoint), sig):
            good_witnesses.append((name, sha256_hex(key)[:16]))
        else:
            witness_problems.append(f"{name}: co-signature did not verify")

    report.fingerprints["witnesses"] = [{"name": n, "fingerprint": f} for n, f in good_witnesses]

    if not witnesses:
        add(
            Check(
                "witness",
                "An independent witness countersigned it",
                False,
                "no witness co-signature — nothing outside this log vouches that it only ever grew",
                skipped=True,
            )
        )
    else:
        add(
            Check(
                "witness",
                "An independent witness countersigned it",
                not witness_problems and bool(good_witnesses),
                "; ".join(witness_problems)
                or ", ".join(f"{n} ({f})" for n, f in good_witnesses),
            )
        )

    # ---------------------------------------------------------------------------------------
    # 10. Pinned keys — the step that turns "a log" into "the log"
    # ---------------------------------------------------------------------------------------
    if expect_log is not None:
        actual = report.fingerprints.get("log")
        add(
            Check(
                "pinned_log",
                "The log key is the one you expected",
                actual is not None and actual.startswith(expect_log.lower()),
                f"expected {expect_log}, found {actual}",
            )
        )
    if expect_witness is not None:
        found = [f for _, f in good_witnesses]
        add(
            Check(
                "pinned_witness",
                "The witness key is the one you expected",
                any(f.startswith(expect_witness.lower()) for f in found),
                f"expected {expect_witness}, found {', '.join(found) or 'none'}",
            )
        )
