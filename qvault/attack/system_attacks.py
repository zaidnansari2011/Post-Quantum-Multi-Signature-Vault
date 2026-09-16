"""Attacks against the running system — governance, the ledger, and files at rest (ADR-0021).

These need a database, so unlike ``crypto_attacks`` they run inside a Flask application context.
The CLI builds a throwaway application on a temporary SQLite file for them; nothing here ever
touches a real deployment's data.

The threat model is deliberately generous to the attacker, and it is the one that matters for a
system whose whole purpose is to be trustworthy about what was approved: **the adversary has write
access to the database.** Not a stolen password, not a session — direct SQL. Every attack below
assumes they can insert, update and delete rows at will. If the guarantees only hold while the
database is honest, they are not guarantees, they are assumptions.

Each scenario is built through the real services (``vault_service``, ``proposal_service``,
``approval_service``), never by writing rows directly, so the state being attacked is a state the
application could actually reach — the same discipline ``scripts/seed_demo.py`` follows under
ADR-0011.
"""

from __future__ import annotations

import hashlib
import json
import random

from ..extensions import db
from ..models.ledger import LedgerEntry
from ..models.signature import Signature
from ..services import (
    approval_service,
    auth_service,
    ledger_service,
    proposal_service,
    vault_service,
)
from .harness import Attack, Run, blocked, succeeded

PASSWORD = "attack-lab-password-2026"
_COUNTER = {"n": 0}


def _isolated(fn):
    """Run a database attack, then always clear the session.

    Added after a real failure that is worth recording, because it is the kind of thing that makes
    a suite lie. An early version omitted a NOT NULL column on a forged row; the resulting
    ``IntegrityError`` left SQLAlchemy's session in a rolled-back state, and the next five attacks
    all failed with ``PendingRollbackError``. Three attacks reported ERROR for a reason that had
    nothing to do with what they were testing.

    Had the harness treated an exception as "blocked", that single mistake would have been reported
    as five successful defences. It does not (see ``harness.judge``), which is how the fault was
    visible at all — but the attacks still have to be isolated from each other rather than merely
    honest about failing together.
    """

    def wrapped():
        try:
            return fn()
        finally:
            db.session.rollback()

    return wrapped


def _assert_tampered(seq: int, original: str) -> str:
    """Re-read entry ``seq`` and confirm its payload really changed. Returns the stored value.

    This exists because of a bug that had already slipped through once. The first version of the
    ledger attacks assigned to ``entry.payload``, but the column is ``payload_json`` — so Python
    quietly set an unmapped instance attribute and the database was never touched. The *real* run
    surfaced it as an AttributeError only by luck of ordering; the *control* run reported SUCCESS,
    because its success criterion ("a sequence-only check still passes") is satisfied whether or not
    any tampering occurred.

    That is a vacuous control wearing a pass, and the harness's ``VACUOUS`` rule cannot catch it:
    the rule compares the two runs' verdicts, and a control that never attacked still produces the
    verdict the claim expects. So the non-vacuity obligation does not stop at the harness — an
    attack whose premise is "the attacker changed X" has to prove X changed.
    """
    fresh = LedgerEntry.query.filter_by(seq=seq).one()
    if fresh.payload_json == original:
        raise AssertionError(
            f"the tamper did not land: entry seq={seq} still holds its original payload, so this "
            "attack would have proved nothing"
        )
    return fresh.payload_json


def _unique(prefix: str) -> str:
    """Unique emails and vault names, so repeated runs in one database never collide."""
    _COUNTER["n"] += 1
    return f"{prefix}{_COUNTER['n']}"


def _scenario(*, signers: int = 3, threshold: int = 2):
    """A vault with ``signers`` members and an M-of-N threshold, plus one open proposal.

    Returns ``(vault, proposal, members)``. Built entirely through the services.
    """
    owner = auth_service.register_user(_unique("owner") + "@lab.test", "Owner", PASSWORD)
    vault = vault_service.create_vault(owner, _unique("Vault "), "adversary lab", threshold)
    members = [owner]
    for i in range(signers - 1):
        member = auth_service.register_user(
            _unique("signer") + "@lab.test", f"Signer {i}", PASSWORD
        )
        vault_service.add_member(vault, member.email, "signer", actor_id=owner.id)
        members.append(member)
    proposal = proposal_service.create_proposal(
        vault, owner, _unique("Release funds "), "Transfer 250,000 to the escrow account."
    )
    return vault, proposal, members


# --- attack 7: manufacture an approval by writing to the database ---------------------------------


def forged_vote_row_real(_: random.Random) -> Run:
    """Insert an approval row directly into the database, bypassing every route and check.

    The attacker copies a genuine signature row, changes the decision to ``approve``, and inserts it
    under another signer's identity. Nothing in the HTTP layer is involved: this is SQL.
    """
    run = blocked()
    vault, proposal, members = _scenario(signers=3, threshold=2)
    approval_service.cast_vote(proposal, members[0], PASSWORD, "reject", reason="not convinced")
    before = approval_service.tally(proposal)
    run.step(
        "Starting state",
        "one genuine rejection; the proposal needs 2 approvals of 3 signers",
        f"tally approvals={before[0]} rejections={before[1]}",
    )

    genuine = Signature.query.filter_by(proposal_id=proposal.id).first()
    forged = Signature(
        proposal_id=proposal.id,
        signer_id=members[1].id,
        key_id=genuine.key_id,
        decision="approve",
        signature=genuine.signature,  # a real signature, over the wrong thing
        alg_id=genuine.alg_id,
        backend=genuine.backend,
        public_key=genuine.public_key,
        signed_payload_hash=genuine.signed_payload_hash,
        reason="inserted by the attacker",
    )
    db.session.add(forged)
    db.session.commit()
    run.step(
        "Attacker writes an approval row directly",
        "a real signature blob, copied from the genuine rejection, relabelled as an approval and "
        "attributed to a different signer",
        f"row id={forged.id}, decision=approve, signer_id={members[1].id}",
    )

    rows = Signature.query.filter_by(proposal_id=proposal.id, decision="approve").count()
    after = approval_service.tally(proposal)
    run.step(
        "The database now contains the approval",
        "counting rows would report it",
        f"{rows} row(s) with decision=approve",
    )
    run.step(
        "The tally verifies instead of counting",
        "approval_service.tally re-verifies every signature against the proposal's canonical "
        "payload, so a row whose signature does not verify contributes nothing",
        f"tally approvals={after[0]} rejections={after[1]}",
    )
    if after[0] > before[0]:
        return succeeded(f"the forged row was counted: approvals went {before[0]} -> {after[0]}")
    run.note = (
        "The attacker can write whatever they like into the signatures table. They cannot make it "
        "verify, and only verification counts."
    )
    return run


def forged_vote_row_control(_: random.Random) -> Run:
    """The same insertion, tallied by counting rows — the obvious implementation."""
    run = succeeded()
    vault, proposal, members = _scenario(signers=3, threshold=2)
    approval_service.cast_vote(proposal, members[0], PASSWORD, "reject", reason="not convinced")
    genuine = Signature.query.filter_by(proposal_id=proposal.id).first()

    def counting_tally() -> tuple[int, int]:
        """A tally that trusts the ``decision`` column. No signature is ever checked."""
        rows = Signature.query.filter_by(proposal_id=proposal.id).all()
        return (
            sum(1 for s in rows if s.decision == "approve"),
            sum(1 for s in rows if s.decision == "reject"),
        )

    before = counting_tally()
    for signer in members[1:]:
        db.session.add(
            Signature(
                proposal_id=proposal.id,
                signer_id=signer.id,
                key_id=genuine.key_id,
                decision="approve",
                signature=genuine.signature,
                alg_id=genuine.alg_id,
                backend=genuine.backend,
                public_key=genuine.public_key,
                signed_payload_hash=genuine.signed_payload_hash,
                reason="inserted by the attacker",
            )
        )
    db.session.commit()
    after = counting_tally()
    run.step(
        "Tally weakened to counting the decision column",
        "the shape almost every approval workflow uses: trust the row, the signature is decoration",
        f"approvals {before[0]} -> {after[0]}, threshold is 2",
    )
    if after[0] < 2:  # pragma: no cover - two rows were inserted
        return blocked("the weakened tally did not reach the threshold")
    run.note = "Two inserted rows, no valid signatures, and the proposal is approved."
    return run


# --- attack 8: join the signer list after the vote opened ----------------------------------------


def post_freeze_signer_real(_: random.Random) -> Run:
    """Add yourself to the vault's signers after a proposal has opened, then vote on it.

    The attack a governance system has to survive: changing who is allowed to decide, after the
    thing to be decided is known.
    """
    run = blocked()
    vault, proposal, members = _scenario(signers=2, threshold=2)
    snapshot = set(json.loads(proposal.authorized_signers_snapshot))
    run.step(
        "Proposal opens and freezes its signer list",
        "the set of authorised signers is captured on the proposal row at creation",
        f"snapshot = {sorted(snapshot)}",
    )

    intruder = auth_service.register_user(_unique("intruder") + "@lab.test", "Intruder", PASSWORD)
    vault_service.add_member(vault, intruder.email, "signer", actor_id=members[0].id)
    run.step(
        "Attacker is added to the vault afterwards",
        "through the real membership service - this part succeeds, and should: vault membership is "
        "allowed to change",
        f"intruder id={intruder.id} is now a vault member",
    )

    try:
        approval_service.cast_vote(proposal, intruder, PASSWORD, "approve")
        voted = True
        error = None
    except Exception as exc:  # noqa: BLE001 - any refusal is the expected outcome
        voted, error = False, f"{type(exc).__name__}: {exc}"
    run.step(
        "Attacker votes on the already-open proposal",
        "the vote is checked against the frozen snapshot, not the live membership",
        f"accepted={voted}" + (f" ({error})" if error else ""),
    )
    if voted:
        return succeeded("a signer added after the freeze was allowed to vote")
    run.note = (
        "Membership may change; who could decide *this* proposal may not. The snapshot is what "
        "makes the second sentence true."
    )
    return run


def post_freeze_signer_control(_: random.Random) -> Run:
    """The same sequence judged against live membership instead of the snapshot."""
    run = succeeded()
    vault, proposal, members = _scenario(signers=2, threshold=2)
    intruder = auth_service.register_user(_unique("intruder") + "@lab.test", "Intruder", PASSWORD)
    vault_service.add_member(vault, intruder.email, "signer", actor_id=members[0].id)

    live_members = {m.user_id for m in vault.members}
    snapshot = set(json.loads(proposal.authorized_signers_snapshot))
    allowed_by_live_check = intruder.id in live_members
    run.step(
        "Authorisation weakened to 'is a current vault member'",
        "the natural implementation, and the one that loses: it answers a question about now, "
        "when the question is about when the proposal opened",
        f"live members {sorted(live_members)} vs frozen snapshot {sorted(snapshot)}",
    )
    run.step(
        "Attacker's vote under the weakened check",
        "they joined after the freeze, so only the live check lets them in",
        f"accepted={allowed_by_live_check}",
    )
    return run if allowed_by_live_check else blocked("the weakened check still refused")


# --- attack 9: rewrite the audit trail ------------------------------------------------------------


def ledger_edit_real(_: random.Random) -> Run:
    """Edit one committed ledger entry in place."""
    run = blocked()
    vault, proposal, members = _scenario(signers=2, threshold=2)
    approval_service.cast_vote(proposal, members[0], PASSWORD, "approve")
    ledger_service.maybe_anchor()
    before = ledger_service.verify_ledger()
    entry_count = LedgerEntry.query.count()
    run.step(
        "Audit trail before the attack",
        "a hash chain: each entry commits to the previous entry's digest, and the head is signed "
        "by the SYSTEM anchor key",
        f"{entry_count} entries, chain_ok={before['chain_ok']}, anchor_ok={before['anchor_ok']}, "
        f"overall ok={before['ok']}",
    )

    target = LedgerEntry.query.order_by(LedgerEntry.seq.desc()).first()
    target_seq = target.seq
    original = target.payload_json
    target.payload_json = json.dumps({"tampered": True})
    db.session.commit()

    # Re-read from the database and confirm the write actually landed. Without this the attack
    # could "pass" while having changed nothing -- see _assert_tampered's docstring.
    stored = _assert_tampered(target_seq, original)
    run.step(
        "Attacker edits a committed entry",
        f"entry seq={target_seq}, payload_json replaced by direct database write and confirmed "
        "re-read from the database",
        f"payload sha256 {hashlib.sha256(original.encode()).hexdigest()[:16]} -> "
        f"{hashlib.sha256(stored.encode()).hexdigest()[:16]}",
    )

    after = ledger_service.verify_ledger()
    run.step(
        "Chain re-verified",
        "the edited entry's digest no longer matches the one its successor commits to, so the walk "
        "stops at the tampered row",
        f"chain_ok={after['chain_ok']}, first break at seq={after['chain_break_seq']}, "
        f"overall ok={after['ok']}",
    )
    if after["ok"]:
        return succeeded("the ledger verified after being edited")
    run.note = (
        "Detection, not prevention. A database writer can always change a row; what they cannot do "
        "is leave the chain consistent afterwards."
    )
    return run


def ledger_edit_control(_: random.Random) -> Run:
    """The same edit against an append-only log with no hash chaining — an ordinary audit table."""
    run = succeeded()
    vault, proposal, members = _scenario(signers=2, threshold=2)
    approval_service.cast_vote(proposal, members[0], PASSWORD, "approve")
    target = LedgerEntry.query.order_by(LedgerEntry.seq.desc()).first()

    # The weakened verifier: check the rows are present and sequential, as an audit table does.
    def sequence_only_check() -> bool:
        seqs = [e.seq for e in LedgerEntry.query.order_by(LedgerEntry.seq).all()]
        return seqs == list(range(seqs[0], seqs[0] + len(seqs)))

    before = sequence_only_check()
    target_seq, original = target.seq, target.payload_json
    target.payload_json = json.dumps({"tampered": True})
    db.session.commit()
    _assert_tampered(target_seq, original)  # the control must really tamper, or it proves nothing
    after = sequence_only_check()
    run.step(
        "Integrity check weakened to 'the rows are all there, in order'",
        "what a timestamped audit table actually guarantees: that nothing was deleted, not that "
        "nothing was changed",
        f"before={before}, after={after}",
    )
    run.step(
        "Result",
        "the entry now says something it never said, and the log agrees with itself",
        f"undetected={after}",
    )
    return run if after else blocked("even the weakened check noticed")


# --- attack 10: tamper with an encrypted file ----------------------------------------------------


def file_tamper_real(_: random.Random) -> Run:
    """Flip a byte inside an encrypted attachment at rest."""
    from ..crypto.symmetric import AESGCMProvider

    run = blocked()
    aes = AESGCMProvider()
    key = hashlib.sha256(b"a data-encryption key").digest()
    plaintext = b"Payment instruction: 250,000 to account GB29 NWBK 6016 1331 9268 19\n"
    nonce, blob = aes.encrypt(key, plaintext)
    run.step(
        "File encrypted at rest",
        "AES-256-GCM, the key wrapped under the vault's ML-KEM keypair",
        f"{len(plaintext)} B plaintext -> {len(blob)} B ciphertext+tag",
    )

    corrupted = bytearray(blob)
    corrupted[8] ^= 0x40  # inside the ciphertext body, not the tag
    run.step(
        "Attacker flips one bit of the stored ciphertext",
        "no key required; this is a write to the blob on disk",
        f"byte 8: {blob[8]:#04x} -> {corrupted[8]:#04x}",
    )

    try:
        aes.decrypt(key, nonce, bytes(corrupted))
        opened = True
        detail = "decrypted without complaint"
    except Exception as exc:  # noqa: BLE001 - an authentication failure is the expected outcome
        opened = False
        detail = type(exc).__name__
    run.step(
        "Download attempted",
        "GCM recomputes the authentication tag over the ciphertext it was given",
        f"decrypt raised {detail}" if not opened else detail,
    )
    if opened:
        return succeeded("modified ciphertext decrypted")
    run.note = (
        "The tag makes the file tamper-evident, not merely unreadable: the difference between "
        "'nobody can read this' and 'nobody can change this without being caught'."
    )
    return run


def file_tamper_control(_: random.Random) -> Run:
    """The same flip against AES-CTR — encryption without authentication.

    Not a hypothetical bad choice. Unauthenticated CTR and CBC modes are still widespread, and the
    consequence is not a garbled file: it is a *predictably* altered one, because flipping a
    ciphertext bit in CTR flips exactly the corresponding plaintext bit.
    """
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    run = succeeded()
    key = hashlib.sha256(b"a data-encryption key").digest()
    nonce = b"\x00" * 16
    plaintext = b"Payment instruction: 250,000 to account GB29 NWBK 6016 1331 9268 19\n"

    def ctr(data: bytes) -> bytes:
        cipher = Cipher(algorithms.AES(key), modes.CTR(nonce))
        encryptor = cipher.encryptor()
        return encryptor.update(data) + encryptor.finalize()

    blob = ctr(plaintext)
    target = plaintext.index(b"250,000")
    corrupted = bytearray(blob)
    # "250,000" -> "850,000": flip the bits that differ, in the ciphertext.
    for i, (old, new) in enumerate(zip(b"250,000", b"850,000", strict=True)):
        corrupted[target + i] ^= old ^ new
    recovered = ctr(bytes(corrupted))
    run.step(
        "Authentication removed: AES-256-CTR instead of GCM",
        "confidentiality without integrity - still a common configuration",
        f"{len(blob)} B ciphertext, no tag",
    )
    run.step(
        "Attacker edits the amount through the ciphertext",
        "CTR is a stream cipher, so a flipped ciphertext bit flips exactly that plaintext bit. The "
        "attacker never learns the key and never needs to",
        f"recovered plaintext now reads: {recovered[target:target + 7].decode(errors='replace')!r}",
    )
    changed = b"850,000" in recovered
    run.step("Decryption succeeds and reports no error", "", f"silently altered={changed}")
    return run if changed else blocked("the edit did not land")


# --- the attacks, as the harness sees them -------------------------------------------------------


def attacks(rng: random.Random | None = None) -> list[Attack]:
    rng = rng or random.Random()
    return [
        Attack(
            id="forged-vote-row",
            title="Manufacture an approval by writing straight to the database",
            question="What if someone gets into your database?",
            capability="Direct SQL write access. No password, no session, no route involved.",
            goal="Reach the M-of-N threshold with an approval nobody gave",
            defence="tally() counts only signatures that currently verify.",
            defence_ref="qvault/services/approval_service.py",
            real=_isolated(lambda: forged_vote_row_real(rng)),
            control=_isolated(lambda: forged_vote_row_control(rng)),
            control_note="a tally that counts the decision column instead of verifying",
        ),
        Attack(
            id="post-freeze-signer",
            title="Join the signer list after the vote opened, then vote",
            question="Can the membership be changed to change the outcome?",
            capability="Permission to administer vault membership.",
            goal="Vote on a proposal that opened before the attacker was authorised",
            defence="The proposal freezes its authorised-signer set at creation.",
            defence_ref="qvault/models/proposal.py",
            real=_isolated(lambda: post_freeze_signer_real(rng)),
            control=_isolated(lambda: post_freeze_signer_control(rng)),
            control_note="authorisation checked against live membership rather than the snapshot",
        ),
        Attack(
            id="ledger-edit",
            title="Edit the audit trail to hide what happened",
            question="The log is in the same database - why would I believe it?",
            capability="Direct SQL write access to the ledger table.",
            goal="Change a recorded event and leave the log self-consistent",
            defence="Hash-chained entries: each commits to its predecessor's digest.",
            defence_ref="qvault/services/ledger_service.py",
            real=_isolated(lambda: ledger_edit_real(rng)),
            control=_isolated(lambda: ledger_edit_control(rng)),
            control_note="an append-only audit table with no hash chaining",
        ),
        Attack(
            id="file-tamper",
            title="Alter a stored file without the key",
            question="Encryption hides the file - but can someone change it?",
            capability="Write access to the encrypted blob at rest.",
            goal="Change the contents of an encrypted attachment undetected",
            defence="AES-256-GCM: the authentication tag covers the ciphertext.",
            defence_ref="qvault/crypto/symmetric.py",
            real=_isolated(lambda: file_tamper_real(rng)),
            control=_isolated(lambda: file_tamper_control(rng)),
            control_note="AES-256-CTR, i.e. encryption without authentication",
        ),
    ]
