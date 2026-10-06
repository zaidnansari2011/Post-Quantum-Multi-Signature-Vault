"""The evidence behind the decision page and the audit log, gathered from real checks (rework R2).

Plan S5 puts evidence in three layers: an outcome sentence, a checks summary in plain words, then
the technical detail. Every line those layers show is assembled here from a check this module (or
the service it calls) actually performs on this request: the payload hash recomputed, the log's
record compared, each signature verified, the checkpoint's signature verified, the inclusion proof
recomputed against its root, the witness's co-signature verified again. Nothing is inferred from a
stored flag, and a check that cannot run says so (Unavailable) rather than passing.

Read-only: nothing here writes, signs or changes what is signed. The pure rules (decision code,
check words, integrity states) are in ``qvault.evidence``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from flask import current_app
from sqlalchemy import select

from qvault import evidence
from qvault.crypto import sha256_hex
from qvault.extensions import db
from qvault.models.checkpoint import LogCheckpoint, WitnessCosignature
from qvault.models.ledger import LedgerEntry
from qvault.models.treasury import ExecutionSignature
from qvault.models.user import User
from qvault.services import approval_service, checkpoint_service, receipt_service
from qvault.services.ledger_service import compute_entry_hash
from qvault.services.signing import (
    DS_PROPOSAL,
    DS_VOTE,
    PAYMENT_NETWORKS,
    format_wei,
    signing_bytes_for,
)
from qvault.transparency.merkle import merkle_root, verify_inclusion
from qvault.transparency.statement import entry_leaf_hash, witness_bytes
from qvault.ui import absolute_time
from qvault.verify.execution import execution_digest


@dataclass
class Check:
    """One row of layer 2: a plain title, one line, and a result that came from a real check."""

    key: str
    title: str
    line: str
    state: str  # passed | failed | unavailable (qvault.evidence.CHECK_WORDS)
    short: str  # the few words the Overview tab's summary uses

    @property
    def word(self) -> str:
        return evidence.check_word(self.state)


@dataclass
class DecisionEvidence:
    code: str
    checks: list[Check] = field(default_factory=list)
    summary: str = ""
    outcome: tuple[str, str] = ("", "")
    names: dict[int, str] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    signatures: list[dict] = field(default_factory=list)
    checkpoint: dict | None = None
    witnesses: list[dict] = field(default_factory=list)
    inclusion: dict | None = None
    payload: dict = field(default_factory=dict)
    payment: dict | None = None
    log: dict = field(default_factory=dict)
    witness_check: dict = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return any(c.state == "failed" for c in self.checks)


# ------------------------------------------------------------------------------ people


def names_for(proposal, viewer_id: int | None = None) -> dict[int, str]:
    """Display names for everyone the decision names: its frozen approvers and who raised it.
    The viewer is "You" (style tile section 0)."""
    ids = set(json.loads(proposal.authorized_signers_snapshot)) | {proposal.creator_id}
    ids |= {s.signer_id for s in proposal.signatures}
    people = {u.id: (u.display_name or u.email) for u in User.query.filter(User.id.in_(ids))}
    if viewer_id in people:
        people[viewer_id] = "You"
    return people


def approver_ids(proposal) -> list[int]:
    return list(json.loads(proposal.authorized_signers_snapshot))


def _possessive(name: str) -> str:
    return "Your" if name == "You" else f"{name}’s"


# ------------------------------------------------------------------------------ the log


def _decision_entries(proposal) -> list[LedgerEntry]:
    return list(
        db.session.execute(
            select(LedgerEntry)
            .where(
                LedgerEntry.ref_type == "proposal",
                LedgerEntry.ref_id == proposal.proposal_uuid,
            )
            .order_by(LedgerEntry.seq)
        )
        .scalars()
        .all()
    )


def _leaf_hex(entry_hash: str) -> str:
    return entry_leaf_hash(entry_hash).hex()


def verify_cosignature(cosignature: WitnessCosignature) -> bool:
    """Verify a stored witness co-signature again, now, over its checkpoint's statement.

    It was verified before it was stored (``checkpoint_service.sync_witness``); this repeats the
    check so an edited signature or statement cannot be shown as Valid. It is checked against the
    key stored with the row, which the server does not pin: a row whose key and signature were
    both replaced would still verify, which is why every screen shows the witness's key
    fingerprint beside the result, for comparison with the witness's own.
    """
    registry = current_app.extensions["crypto"]
    if not registry.has_signature(cosignature.alg_id):
        return False
    message = witness_bytes(
        witness=cosignature.witness_name, statement=cosignature.checkpoint.statement()
    )
    try:
        return registry.signature(cosignature.alg_id).verify(
            cosignature.public_key, message, cosignature.signature
        )
    except Exception:  # noqa: BLE001 - a malformed row is a failed check, not a 500
        return False


def _inclusion(seq: int, checkpoint: LogCheckpoint) -> dict:
    """The audit path for entry ``seq`` in ``checkpoint``'s tree, recomputed to its root."""
    try:
        proof = checkpoint_service.inclusion_proof_for(seq, checkpoint)
        leaves = checkpoint_service.leaf_hashes()
        valid = verify_inclusion(
            leaf=leaves[seq],
            index=seq,
            tree_size=checkpoint.tree_size,
            proof=[bytes.fromhex(h) for h in proof],
            root=bytes.fromhex(checkpoint.root_hash),
        )
    except (checkpoint_service.LogError, IndexError, ValueError):
        return {"seq": seq, "length": None, "valid": False}
    return {"seq": seq, "length": len(proof), "valid": valid}


def entry_intact(entry: LedgerEntry) -> bool:
    """Recompute one log entry's hash and its payload's hash, as ``verify_chain`` does for each.

    The decision page cites its own entries ("entry #12 recorded this decision"); this is what
    lets it say so only of an entry whose contents still match the hash the Merkle tree holds.
    """
    if sha256_hex(entry.payload_json.encode("utf-8")) != entry.payload_hash:
        return False
    return (
        compute_entry_hash(
            seq=entry.seq,
            timestamp=entry.timestamp,
            actor=entry.actor,
            event_type=entry.event_type,
            payload_hash=entry.payload_hash,
            prev_hash=entry.prev_hash,
            actor_id=entry.actor_id,
            vault_id=entry.vault_id,
            ref_type=entry.ref_type,
            ref_id=entry.ref_id,
        )
        == entry.entry_hash
    )


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _alg_meta(alg_id: str):
    try:
        return current_app.extensions["crypto"].signature(alg_id).meta
    except Exception:  # noqa: BLE001 - an unregistered algorithm must not break the page
        return None


# ------------------------------------------------------------------------------ the decision


def decision_evidence(
    proposal, *, binding, votes: list[dict], viewer_id: int | None, payout: dict | None
) -> DecisionEvidence:
    """Everything the Evidence and Technical tabs show for one decision.

    ``binding`` is ``approval_service.verify_proposal_binding(proposal)`` and ``votes`` the
    page's ``[{"sig", "verified"}]``: both already computed by the route, and reused rather than
    recomputed so the tabs and the header can never disagree.
    """
    names = names_for(proposal, viewer_id)
    ev = DecisionEvidence(code=evidence.decision_code(proposal.payload_hash), names=names)
    action = proposal.action
    is_payment = action is not None

    # ---- the log: this decision's own entries, and which one records each signature
    entries = _decision_entries(proposal)
    created = next((e for e in entries if e.event_type == "proposal_created"), None)
    sig_entry = {v["sig"].id: receipt_service._ledger_entry_for(v["sig"]) for v in votes}
    ev.events = [
        {
            "seq": e.seq,
            "event_type": e.event_type,
            "entry_hash": e.entry_hash,
            "leaf_hash": _leaf_hex(e.entry_hash),
            "timestamp": e.timestamp,
            "actor_id": e.actor_id,
        }
        for e in entries
    ]
    highest = entries[-1].seq if entries else None

    # ---- the checkpoint covering the newest of them, its signature, the inclusion proof
    checkpoint = checkpoint_service.checkpoint_covering(highest) if highest is not None else None
    if checkpoint is not None:
        key = checkpoint.key
        ev.checkpoint = {
            "row": checkpoint,
            "valid": checkpoint_service.verify_checkpoint(checkpoint),
            "key_fingerprint": key.public_fingerprint() if key is not None else None,
        }
        ev.inclusion = _inclusion(highest, checkpoint)
        ev.witnesses = [
            {"row": c, "valid": verify_cosignature(c), "fingerprint": c.key_fingerprint()}
            for c in checkpoint.cosignatures
        ]
    ev.log = checkpoint_service.log_summary()
    ev.witness_check = witness_check()
    # Every entry the page cites, recomputed: an edited entry must not be quoted as a record.
    cited = list(entries) + [e for e in sig_entry.values() if e is not None]
    broken = sorted({e.seq for e in cited if not entry_intact(e)})

    # ---- layer 2: the checks
    checks: list[Check] = []
    recomputed_code = evidence.decision_code(binding.recomputed_hash)
    hash_ok = binding.recomputed_hash == binding.recorded_hash
    # "Every signature covers it" is checked, not assumed: the stored hash must be the one the
    # log recorded when the decision was raised, and the one each signature committed to. A row
    # edited together with its own hash column passes the first comparison and fails these.
    covered = all(v["sig"].signed_payload_hash == binding.recorded_hash for v in votes)
    what = "text, payment and approval rule" if is_payment else "text and approval rule"
    if hash_ok and binding.ledger_matches and covered and created is not None:
        line = f"The {what} still produce code {ev.code}, the code the log recorded"
        line += " and every signature covers." if votes else " when this decision was raised."
        checks.append(
            Check("content", "Contents match what was signed", line, "passed", "Content verified")
        )
    elif hash_ok:
        signed = binding.ledger_hash or next((v["sig"].signed_payload_hash for v in votes), None)
        checks.append(
            Check(
                "content",
                "Contents match what was signed",
                f"What is stored now produces code {ev.code}, but "
                + (
                    f"what was signed has code {evidence.decision_code(signed)}."
                    if signed
                    else "no record of what was signed survives."
                ),
                "failed",
                "Content altered",
            )
        )
    else:
        checks.append(
            Check(
                "content",
                "Contents match what was signed",
                f"What is stored now produces code {recomputed_code}, not {ev.code}. "
                "The signatures don’t cover this text.",
                "failed",
                "Content altered",
            )
        )

    if is_payment:
        # The same rule the binding check applies (plan D24): the text must be the text generated
        # from the signed payment, and the treasury must be the one that was signed.
        problem = approval_service._payment_problem(proposal)
        checks.append(
            Check(
                "payment_text",
                "The text matches the payment",
                (
                    "The decision text describes exactly the payment the treasury will make."
                    if problem is None
                    else problem
                ),
                "passed" if problem is None else "failed",
                (
                    "Text matches the payment"
                    if problem is None
                    else (
                        "Treasury doesn’t match the payment"
                        if "treasury" in problem
                        else "Text doesn’t match the payment"
                    )
                ),
            )
        )

    unlogged = [
        names.get(v["sig"].signer_id, "Someone") for v in votes if not sig_entry[v["sig"].id]
    ]
    if binding.ledger_hash is None or created is None:
        log_check = ("failed", "No record of this decision survives in the transparency log.")
    elif not binding.ledger_matches:
        log_check = (
            "failed",
            f"The log recorded code {evidence.decision_code(binding.ledger_hash)} for this "
            f"decision, not {ev.code}.",
        )
    elif broken:
        numbers = ", ".join(f"#{n:,}" for n in broken)
        log_check = (
            "failed",
            f"Log {'entry' if len(broken) == 1 else 'entries'} {numbers} no longer "
            f"{'matches' if len(broken) == 1 else 'match'} the hash the log holds, so "
            f"{'it' if len(broken) == 1 else 'they'} can’t be relied on.",
        )
    elif unlogged:
        log_check = (
            "failed",
            f"Entry #{created.seq:,} recorded this decision, but no entry records the "
            f"signature by {', '.join('you' if n == 'You' else n for n in unlogged)}.",
        )
    else:
        line = f"Entry #{created.seq:,} recorded this decision with the same code."
        for v in votes:
            entry = sig_entry[v["sig"].id]
            who = names.get(v["sig"].signer_id, "Someone")
            act = "approval" if v["sig"].decision == "approve" else "rejection"
            line += f" {_possessive(who)} {act} is entry #{entry.seq:,}."
        log_check = ("passed", line)
    checks.append(
        Check(
            "log",
            "Recorded in the transparency log",
            log_check[1],
            log_check[0],
            "Recorded in the log" if log_check[0] == "passed" else "Not recorded in the log",
        )
    )

    for v in votes:
        sig = v["sig"]
        who = names.get(sig.signer_id, "Someone")
        kind = "phone" if sig.custody == "device" else "password"
        whose = "you" if who == "You" else who
        if v["verified"]:
            checks.append(
                Check(
                    f"signature:{sig.id}",
                    f"{_possessive(who)} signature is valid",
                    f"Checked against the {kind} key registered to {whose}.",
                    "passed",
                    "",
                )
            )
        else:
            checks.append(
                Check(
                    f"signature:{sig.id}",
                    f"{_possessive(who)} signature is valid",
                    "It didn’t verify against the key registered to "
                    f"{whose}, so it isn’t counted.",
                    "failed",
                    f"{_possessive(who)} signature didn’t verify",
                )
            )

    if ev.checkpoint is None:
        checks.append(
            Check(
                "checkpoint",
                "Included in a signed checkpoint",
                "No signed checkpoint covers this decision’s newest entry yet.",
                "unavailable",
                "Not checkpointed yet",
            )
        )
    else:
        cp = ev.checkpoint["row"]
        ok = ev.checkpoint["valid"] and ev.inclusion["valid"] and highest not in broken
        if ok:
            line = (
                f"The log signed a checkpoint of {cp.tree_size:,} entries, and an inclusion proof "
                f"of {_plural(ev.inclusion['length'], 'hash', 'hashes')} places entry "
                f"#{highest:,} in it."
            )
        elif highest in broken:
            line = f"Entry #{highest:,} no longer matches the hash the checkpoint includes."
        elif not ev.checkpoint["valid"]:
            line = "The checkpoint’s signature didn’t verify against the log key."
        else:
            line = f"Entry #{highest:,} isn’t in the tree the checkpoint signed."
        checks.append(
            Check(
                "checkpoint",
                "Included in a signed checkpoint",
                line,
                "passed" if ok else "failed",
                "Checkpointed" if ok else "Not in the checkpoint",
            )
        )

    good = [w for w in ev.witnesses if w["valid"]]
    if good:
        first = good[0]["row"]
        checks.append(
            Check(
                "witness",
                "Witnessed",
                f"{first.witness_name}, an independent witness, co-signed that checkpoint on "
                f"{evidence.precise_time(first.created_at)}, with the key whose fingerprint is "
                f"{good[0]['fingerprint']}.",
                "passed",
                "Witnessed",
            )
        )
    elif ev.witnesses:
        checks.append(
            Check(
                "witness",
                "Witnessed",
                f"{ev.witnesses[0]['row'].witness_name}’s co-signature didn’t verify.",
                "failed",
                "Witness signature invalid",
            )
        )
    else:
        configured = bool(checkpoint_service.witness_url())
        checks.append(
            Check(
                "witness",
                "Witnessed",
                (
                    "Not witnessed yet. The witness hasn’t co-signed a checkpoint that includes "
                    "this decision’s newest entry."
                    if configured
                    else "No witness is configured for this log, so nothing outside it vouches "
                    "for this decision."
                ),
                "unavailable",
                "Not witnessed yet" if configured else "No witness",
            )
        )
    ev.checks = checks
    ev.summary = evidence.checks_summary([c.state for c in checks])

    # ---- layer 3: the signatures, as records
    executions = {
        e.signer_id: e for e in ExecutionSignature.query.filter_by(proposal_id=proposal.id).all()
    }
    for v in votes:
        sig = v["sig"]
        meta = _alg_meta(sig.alg_id)
        entry = sig_entry[sig.id]
        execution = executions.get(sig.signer_id) if sig.decision == "approve" else None
        ev.signatures.append(
            {
                "sig": sig,
                "name": names.get(sig.signer_id, "Someone"),
                "verified": v["verified"],
                "custody": sig.custody,
                "standard": getattr(meta, "nist_standard", None),
                "category": getattr(meta, "security_category", None),
                "size": len(sig.signature),
                "public_key_size": len(sig.public_key),
                "key_fingerprint": sig.key.public_fingerprint() if sig.key is not None else None,
                "sha256": sha256_hex(sig.signature),
                "entry": entry,
                "execution_sha256": sha256_hex(execution.signature) if execution else None,
                "execution_digest": "0x" + execution.digest.hex() if execution else None,
            }
        )

    # ---- layer 3: the payload
    raw = signing_bytes_for(proposal)
    ev.payload = {
        "bytes": len(raw),
        "domain": DS_PROPOSAL.decode(),
        "vote_domain": DS_VOTE.decode(),
        "raw": raw.decode("utf-8", errors="replace"),
        "nonce": proposal.nonce.hex(),
        "created_seq": created.seq if created is not None else None,
    }

    # ---- the payment, as signed
    if is_payment:
        try:
            value = format_wei(int(action.value_wei))
        except ValueError:
            value = None
        try:
            digest = "0x" + execution_digest(action.canonical(), proposal.payload_hash).hex()
        except ValueError:
            digest = None
        ev.payment = {
            "amount": value,
            "to": action.to_address,
            "treasury": action.treasury_address,
            "chain_id": action.chain_id,
            "network": PAYMENT_NETWORKS.get(action.chain_id, f"chain {action.chain_id}"),
            "value_wei": action.value_wei,
            "call_gas": action.call_gas,
            "valid_until": action.valid_until,
            "config_nonce": action.config_nonce,
            "data": action.data_hex,
            "kind": action.kind,
            "digest": digest,
        }

    ev.outcome = outcome_sentence(proposal, binding=binding, payout=payout, ev=ev)
    return ev


def outcome_sentence(proposal, *, binding, payout: dict | None, ev: DecisionEvidence):
    """Layer 1: what is true about this decision, in one bold clause and one plain one."""
    if not binding.ok:
        if binding.content_matches and binding.ledger_hash is None:
            first = "The log’s record of this decision is missing."
        elif binding.content_matches:
            first = "The stored code disagrees with the log."
        else:
            first = "Content altered since signing."
        valid = sum(1 for c in ev.checks if c.key.startswith("signature:") and c.state == "passed")
        return first, (
            f"{_plural(valid, 'signature')} still verif{'ies' if valid == 1 else 'y'}, but none "
            "is counted, because what they cover isn’t provably this text."
        )
    approvals, _ = approval_service.tally(proposal)
    m = proposal.required_m
    payment = ev.payment["amount"] if ev.payment else None
    if proposal.status == "open":
        left = max(m - approvals, 0)
        need = f"{left} more approval{'' if left == 1 else 's'}"
        due = f" by {absolute_time(proposal.expires_at)}" if proposal.expires_at else ""
        if payment:
            return "Nothing has been paid.", f"This payment needs {need}{due}."
        return "Not decided yet.", f"This decision needs {need}{due}."
    if proposal.status == "approved":
        when = evidence.precise_time(proposal.approved_at)
        if payout is not None:
            state = payout.get("state")
            if state == "confirmed":
                block = payout.get("block_number")
                return "Paid.", (
                    f"The treasury sent {payment or 'the payment'}"
                    + (f", confirmed in block {block:,}." if block else ".")
                )
            if state in ("failed", "voided", "expired"):
                reason = payout.get("reason") or "no reason was recorded"
                return "Approved, but not paid.", f"{reason[:1].upper()}{reason[1:]}."
            return "Approved, not paid yet.", "The payout is queued for the treasury."
        return "Approved.", f"It reached {m} approval{'' if m == 1 else 's'} on {when}."
    if proposal.status == "rejected":
        when = evidence.precise_time(proposal.rejected_at)
        return "Rejected.", f"Enough approvers rejected it on {when} that it can’t be approved."
    if proposal.status == "expired":
        due = evidence.precise_time(proposal.expires_at) if proposal.expires_at else "its due time"
        return "Expired.", f"Its due time, {due}, passed before it had {_plural(m, 'approval')}."
    return "", ""


# ------------------------------------------------------------------------------ the audit log


def witness_check() -> dict:
    """The page-level witness fact the audit log's integrity column rests on.

    Finds the newest checkpoint a witness co-signed, verifies that co-signature again, and
    recomputes the root of the log's first ``tree_size`` leaves to confirm the log still contains
    exactly the tree the witness saw. Done once per page, not per row.
    """
    configured = bool(checkpoint_service.witness_url())
    cosignature = (
        WitnessCosignature.query.join(LogCheckpoint)
        .order_by(LogCheckpoint.tree_size.desc(), WitnessCosignature.id.desc())
        .first()
    )
    if cosignature is None:
        return {"configured": configured, "size": None, "ok": False, "row": None}
    checkpoint = cosignature.checkpoint
    try:
        leaves = checkpoint_service.leaf_hashes()
        root_ok = checkpoint.tree_size <= len(leaves) and (
            merkle_root(leaves[: checkpoint.tree_size]).hex() == checkpoint.root_hash
        )
    except checkpoint_service.LogError:
        root_ok = False
    sig_ok = verify_cosignature(cosignature)
    return {
        "configured": configured,
        "size": checkpoint.tree_size,
        "ok": root_ok and sig_ok,
        "root_ok": root_ok,
        "sig_ok": sig_ok,
        "row": cosignature,
    }


def integrity_for(rows: list[dict], report: dict, witness: dict) -> None:
    """Add each audit row's integrity state (``qvault.evidence.entry_integrity``) in place."""
    for row in rows:
        row["integrity"] = evidence.entry_integrity(
            row["entry"].seq,
            chain_break_seq=report.get("chain_break_seq"),
            witnessed_size=witness["size"],
            witnessed_ok=witness["ok"],
            witness_configured=witness["configured"],
        )


def entry_proof(entry: LedgerEntry, report: dict) -> dict:
    """The proof drawer for one audit entry: its place in the chain, its leaf, the checkpoint that
    covers it with the inclusion proof recomputed, and that checkpoint's witnesses verified."""
    chain_ok = report.get("chain_break_seq") is None or entry.seq < report["chain_break_seq"]
    checkpoint = checkpoint_service.checkpoint_covering(entry.seq)
    proof = None
    witnesses = []
    cp = None
    if checkpoint is not None:
        cp = {
            "row": checkpoint,
            "valid": checkpoint_service.verify_checkpoint(checkpoint),
            "key_fingerprint": (
                checkpoint.key.public_fingerprint() if checkpoint.key is not None else None
            ),
        }
        proof = _inclusion(entry.seq, checkpoint)
        witnesses = [
            {"row": c, "valid": verify_cosignature(c), "fingerprint": c.key_fingerprint()}
            for c in checkpoint.cosignatures
        ]
    return {
        "entry": entry,
        "chain_ok": chain_ok,
        "leaf_hash": _leaf_hex(entry.entry_hash),
        "checkpoint": cp,
        "inclusion": proof,
        "witnesses": witnesses,
    }


# ------------------------------------------------------------------------------ audit sentences

#: The role words the product uses (plan S10): "signer" stays in code and signed data.
ROLE_WORDS = {"signer": "an approver", "viewer": "a viewer", "owner": "an owner"}


def _payload(entry: LedgerEntry) -> dict:
    try:
        value = json.loads(entry.payload_json)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def describe(rows: list[dict], viewer) -> None:
    """Name who and what an audit sentence is about, in place (research 05: "Zaid added a member"
    three times without saying whom).

    Only for entries in a vault the viewer belongs to: the audit scope also shows the system's
    entries for every vault, and a decision's title or a member's name must not reach someone
    outside that vault. Elsewhere ``audit_service.narrate``'s sentence stands as it is. Each row
    gains ``href`` when it is about a decision the viewer can open.
    """
    from qvault.models.proposal import Proposal
    from qvault.models.vault import VaultMember

    mine = {m.vault_id for m in VaultMember.query.filter_by(user_id=viewer.id).all()}
    visible = [r for r in rows if r["entry"].vault_id in mine]
    uuids = {r["entry"].ref_id for r in visible if r["entry"].ref_type == "proposal"}
    proposals = (
        {p.proposal_uuid: p for p in Proposal.query.filter(Proposal.proposal_uuid.in_(uuids))}
        if uuids
        else {}
    )
    member_ids = {
        _payload(r["entry"]).get("user_id")
        for r in visible
        if r["entry"].event_type in ("member_added", "member_removed", "member_role_changed")
    }
    member_ids = {i for i in member_ids if isinstance(i, int)}
    people = (
        {u.id: (u.display_name or u.email) for u in User.query.filter(User.id.in_(member_ids))}
        if member_ids
        else {}
    )
    for row in visible:
        e = row["entry"]
        who, vault = row["who"], row["vault"]
        data = _payload(e)
        proposal = proposals.get(e.ref_id) if e.ref_type == "proposal" else None
        title = f"“{proposal.title}”" if proposal is not None else "a decision"
        if proposal is not None:
            row["href"] = (proposal.vault_id, proposal.proposal_uuid)
        sentence = None
        if e.event_type == "proposal_created":
            sentence = f"{who} raised {title} in {vault}."
        elif e.event_type == "proposal_signed":
            verb = "rejected" if data.get("decision") == "reject" else "approved"
            sentence = f"{who} {verb} {title} in {vault}."
        elif e.event_type == "proposal_approved":
            sentence = f"{title[:1].upper()}{title[1:]} in {vault} reached the approvals it needed."
        elif e.event_type == "proposal_rejected":
            sentence = f"{title[:1].upper()}{title[1:]} in {vault} was rejected."
        elif e.event_type == "proposal_expired":
            sentence = (
                f"{title[:1].upper()}{title[1:]} in {vault} expired before it had enough "
                "approvals."
            )
        elif e.event_type in ("member_added", "member_removed", "member_role_changed"):
            member = people.get(data.get("user_id"))
            if member is not None:
                if e.event_type == "member_added":
                    role = ROLE_WORDS.get(data.get("role"), "a member")
                    sentence = f"{who} added {member} to {vault} as {role}."
                elif e.event_type == "member_removed":
                    sentence = f"{who} removed {member} from {vault}."
                else:
                    role = ROLE_WORDS.get(data.get("to"), "a member")
                    sentence = f"{who} made {member} {role} in {vault}."
        if sentence:
            row["sentence"] = sentence


#: The audit filter's options, in plain words. Unknown event types fall back to their name.
EVENT_LABELS = {
    "proposal_created": "Decision raised",
    "proposal_signed": "Decision signed",
    "proposal_approved": "Decision approved",
    "proposal_rejected": "Decision rejected",
    "proposal_expired": "Decision expired",
    "proposal_executed": "Payment paid",
    "proposal_execution_failed": "Payment failed",
    "user_registered": "Person joined",
    "vault_created": "Vault created",
    "member_added": "Member added",
    "member_removed": "Member removed",
    "member_role_changed": "Member's role changed",
    "vault_threshold_changed": "Approval rule changed",
    "file_encrypted": "File attached",
    "key_reissued": "Signing key replaced",
    "password_changed": "Password changed",
    "decision_published": "Decision published",
    "decision_unpublished": "Public link revoked",
    "device_enrolled": "Phone added",
    "device_revoked": "Phone removed",
}


def event_label(event_type: str) -> str:
    if event_type in EVENT_LABELS:
        return EVENT_LABELS[event_type]
    words = event_type.replace("_", " ").replace("proposal", "decision")
    return words[:1].upper() + words[1:]
