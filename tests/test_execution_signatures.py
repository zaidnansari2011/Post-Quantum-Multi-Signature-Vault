"""Execution signatures on the web (plan Phase 6a): approving a payment authorises the chain.

Approving a payment decision produces two signatures from one password: the vote this server
verifies, and a signature over the 32 bytes ``QVaultTreasury`` checks before it moves any ETH.
What matters here is that the second one is real — made with the key the treasury actually holds,
over a digest recomputed from the stored payment *after* the decision's binding has been checked —
and that an approval which could never be executed is refused while the person is still looking
at it, rather than discovered later by an executor holding an approval the contract will not
accept.

Nothing in this file touches a chain: the treasury rows are the ones a link writes, and the
digest is the same pure function the contract mirrors (``qvault/chain/digest.py``).
"""

from __future__ import annotations

import base64
import json

import pytest
from test_device_api import _enrol_over_http
from test_payment_decisions import PASSWORD, PAYMENTS, RECIPIENT, TREASURY, _payment, _vault

from qvault.chain.digest import execution_digest, proposal_id
from qvault.crypto import sha256_hex
from qvault.extensions import db
from qvault.models import Device, ExecutionSignature, Key, LedgerEntry, TreasurySigner
from qvault.services import (
    approval_service,
    device_service,
    execution_service,
    key_service,
    proposal_service,
    vault_service,
)
from qvault.services.approval_service import ApprovalError
from qvault.services.key_service import SignFaultError
from qvault.services.signing import vote_signing_bytes

# A wrong password. A refusal that arrives as ApprovalError rather than KeyUnlockError was made
# before the password was tried, which is the only way a test can tell "before" from "after".
WRONG = "not-the-password"
MALLORY = "0x000000000000000000000000000000000000dEaD"


@pytest.fixture()
def payments_on(app):
    app.config["ONCHAIN_EXECUTION_ENABLED"] = True
    return app


def _provider(app, alg="ML-DSA-65"):
    return app.extensions["crypto"].signature(alg)


def _signature_of(proposal, user) -> ExecutionSignature | None:
    return ExecutionSignature.query.filter_by(proposal_id=proposal.id, signer_id=user.id).first()


def _count_unlocks(monkeypatch) -> list[int]:
    unlocks: list[int] = []
    original = key_service.unlock_secret_key
    monkeypatch.setattr(
        key_service,
        "unlock_secret_key",
        lambda user, key, password: (unlocks.append(key.id), original(user, key, password))[1],
    )
    return unlocks


def _tamper(proposal, column, value):
    """An edit made at the database level, as someone with write access and nothing else would."""
    db.session.execute(
        db.text(f"UPDATE proposal_actions SET {column} = :v WHERE proposal_id = :p"),
        {"v": value, "p": proposal.id},
    )
    db.session.commit()


def _phone_seat(client, user, treasury):
    """Enrol a phone for ``user`` and make it the key the treasury holds for them (D37)."""
    _body, secret, _auth = _enrol_over_http(client, user)
    key = Key.query.filter_by(owner_id=user.id, wrap_domain="device").one()
    row = TreasurySigner.query.filter_by(treasury_id=treasury.id, user_id=user.id).one()
    row.key_id = key.id
    db.session.commit()
    return key, secret


def _device_vote(app, proposal, user, key, secret, decision, *, execution=None):
    vote = _provider(app).sign(
        secret,
        vote_signing_bytes(
            proposal_payload_hash=proposal.payload_hash, decision=decision, signer_id=user.id
        ),
    )
    return approval_service.record_device_vote(
        proposal, user, key, decision, vote, execution=execution
    )


# --- the signature a treasury would accept ---------------------------------------------------


def test_approving_a_payment_signs_what_the_treasury_will_check(payments_on):
    owner, _other, vault, treasury = _vault("exec")
    registered = TreasurySigner.query.filter_by(treasury_id=treasury.id, user_id=owner.id).one()
    registered.identity_hex = "0x" + "11" * 124  # distinct from every other signer's
    db.session.commit()
    proposal = _payment(vault, owner)

    approval_service.cast_vote(proposal, owner, PASSWORD, "approve")

    stored = _signature_of(proposal, owner)
    assert stored is not None
    key = key_service.active_signing_key(owner)
    assert (stored.key_id, stored.alg_id, stored.custody) == (key.id, "ML-DSA-65", "server")
    # The executor submits this identity beside the signature, and a reconfiguration may rewrite
    # the signer row, so the identity it was made for is pinned on the signature itself.
    assert stored.identity_hex == "0x" + "11" * 124

    # The digest is the contract's, recomputed here from the payment as stored.
    action = proposal.action.canonical()
    expected = execution_digest(
        chain_id=action["chain_id"],
        treasury=action["treasury"],
        proposal_id=proposal_id(proposal.payload_hash),
        to=action["to"],
        value_wei=int(action["value_wei"]),
        call_gas=action["call_gas"],
        valid_until=action["valid_until"],
    )
    assert bytes(stored.digest) == expected
    assert treasury.address == action["treasury"] == TREASURY

    # And it verifies under the key the treasury has registered for this signer, which is the
    # only question the chain will ask.
    assert registered.key_id == stored.key_id
    assert _provider(payments_on).verify(
        bytes(stored.public_key), expected, bytes(stored.signature)
    )


def test_the_ledger_records_the_execution_signature_beside_the_vote(payments_on):
    owner, _other, vault, _treasury = _vault("ledger")
    proposal = _payment(vault, owner)
    approval_service.cast_vote(proposal, owner, PASSWORD, "approve")

    entry = LedgerEntry.query.filter_by(
        event_type="proposal_signed", ref_id=proposal.proposal_uuid
    ).one()
    payload = json.loads(entry.payload_json)
    stored = _signature_of(proposal, owner)
    assert payload["execution_signature_sha256"] == sha256_hex(bytes(stored.signature))
    assert payload["decision"] == "approve"


def test_one_password_produces_both_signatures(payments_on, monkeypatch):
    # One unlock is one Argon2id run, and the two signatures are one act of approval: a second
    # unlock would be a second chance for the password to be wrong after the vote was made.
    owner, _other, vault, _treasury = _vault("once")
    proposal = _payment(vault, owner)
    unlocks = _count_unlocks(monkeypatch)

    approval_service.cast_vote(proposal, owner, PASSWORD, "approve")

    assert len(unlocks) == 1
    assert _signature_of(proposal, owner) is not None


def test_a_decision_without_a_payment_signs_nothing_extra(payments_on):
    # An ordinary decision in a vault that *has* a treasury: having one changes nothing about
    # decisions that authorise no payment.
    owner, _other, vault, _treasury = _vault("plainvote")
    plain = proposal_service.create_proposal(vault, owner, "Hire", "Hire a second auditor.")

    approval_service.cast_vote(plain, owner, PASSWORD, "approve")

    assert plain.action is None
    assert ExecutionSignature.query.count() == 0
    entry = LedgerEntry.query.filter_by(
        event_type="proposal_signed", ref_id=plain.proposal_uuid
    ).one()
    assert "execution_signature_sha256" not in json.loads(entry.payload_json)


def test_two_approvals_are_two_signatures_over_the_same_digest(payments_on):
    owner, other, vault, _treasury = _vault("both")
    proposal = _payment(vault, owner)

    approval_service.cast_vote(proposal, owner, PASSWORD, "approve")
    approval_service.cast_vote(proposal, other, PASSWORD, "approve")

    stored = execution_service.signatures_for(proposal)
    assert [row.signer_id for row in stored] == [owner.id, other.id]
    assert {bytes(row.digest) for row in stored} == {execution_service.digest_for(proposal)}
    assert bytes(stored[0].signature) != bytes(stored[1].signature)
    assert proposal.status == "approved"


class _FaultsTheSecondSignature:
    """Signs honestly once, then corrupts: a fault in the payment half of one approval.

    The suite's own fault harness (``tests/test_fault_injection.py``) corrupts *every* signature,
    so on a payment the vote fails first and the second message is never reached. This one models
    the case that only exists now that one unlock produces two signatures.
    """

    def __init__(self, inner):
        self._inner = inner
        self.meta = inner.meta
        self.signs = 0

    def keygen(self):
        return self._inner.keygen()

    def sign(self, secret_key, message):
        self.signs += 1
        signature = self._inner.sign(secret_key, message)
        if self.signs < 2:
            return signature
        corrupted = bytearray(signature)
        corrupted[0] ^= 0x01
        return bytes(corrupted)

    def verify(self, public_key, message, signature):
        return self._inner.verify(public_key, message, signature)


def test_a_fault_in_the_payment_half_records_no_vote_at_all(payments_on):
    # ADR-0010 across two messages: the vote signature was good, but the one the treasury would
    # check was not, so nothing is recorded. An approval whose payment half was lost would be a
    # decision the app calls approved and the chain refuses.
    owner, _other, vault, _treasury = _vault("fault")
    proposal = _payment(vault, owner)
    registry = payments_on.extensions["crypto"]
    original = registry.signature("ML-DSA-65")
    faulting = _FaultsTheSecondSignature(original)
    registry.register_signature(faulting)
    try:
        with pytest.raises(SignFaultError, match="failed immediate verification"):
            approval_service.cast_vote(proposal, owner, PASSWORD, "approve")
    finally:
        registry.register_signature(original)
    db.session.rollback()

    assert faulting.signs == 2  # both were produced from the one unlock
    assert approval_service.vote_of(proposal, owner.id) is None
    assert ExecutionSignature.query.count() == 0
    assert (
        LedgerEntry.query.filter_by(
            event_type="proposal_signed", ref_id=proposal.proposal_uuid
        ).count()
        == 0
    )
    assert proposal.status == "open"


# --- a payment that is not the one that was signed (review H-1) ------------------------------


@pytest.mark.parametrize(
    "prefix, column, value",
    [
        ("early-to", "to_address", MALLORY),
        ("early-value", "value_wei", str(10**18)),
        ("early-gas", "call_gas", 1_000_000),
        ("early-until", "valid_until", 4_102_444_800),
    ],
)
def test_a_payment_edited_before_anyone_approves_is_never_signed(
    payments_on, monkeypatch, prefix, column, value
):
    # The digest is built from the payment row and the contract checks nothing else, so an edit
    # made before the first approval would be signed faithfully by every honest approver while
    # the page still showed the payment they meant. The vote alone was never at risk (it signs
    # the payload hash); the execution signature was, so the binding is checked before it.
    owner, _other, vault, _treasury = _vault(prefix)
    proposal = _payment(vault, owner)
    _tamper(proposal, column, value)
    unlocks = _count_unlocks(monkeypatch)

    with pytest.raises(ApprovalError, match="no longer matches what was signed"):
        approval_service.cast_vote(proposal, owner, PASSWORD, "approve")

    assert unlocks == []  # refused before the password was used: nothing was signed at all
    assert ExecutionSignature.query.count() == 0
    assert approval_service.vote_of(proposal, owner.id) is None


def test_the_web_withholds_approve_from_a_payment_edited_after_the_page_loaded(payments_on, client):
    owner, _other, vault, _treasury = _vault("webtamper")
    proposal = _payment(vault, owner)
    page = f"/vaults/{vault.id}/proposals/{proposal.proposal_uuid}"
    client.post("/login", data={"email": owner.email, "password": PASSWORD})
    assert 'name="approve"' in client.get(page).get_data(as_text=True)

    _tamper(proposal, "to_address", MALLORY)

    # The page loaded before the edit still has its button; the server does not take its word.
    submitted = client.post(
        f"{page}/vote",
        data={"password": PASSWORD, "approve": "Approve & sign"},
        follow_redirects=True,
    )
    assert "no longer matches what was signed" in submitted.get_data(as_text=True)
    db.session.expire_all()
    assert ExecutionSignature.query.count() == 0
    assert approval_service.vote_of(proposal, owner.id) is None

    reloaded = client.get(page).get_data(as_text=True)
    assert 'name="approve"' not in reloaded
    assert 'name="reject"' in reloaded  # objecting authorises nothing, so it stays


def test_a_phone_signature_over_an_edited_payment_is_refused(payments_on, client):
    # The phone will compute its own digest (6b), but the one checked is the server's, and only
    # once the binding holds: a phone that signed the edited payment is refused like the web.
    owner, _other, vault, treasury = _vault("phonetamper")
    key, secret = _phone_seat(client, owner, treasury)
    proposal = _payment(vault, owner)
    _tamper(proposal, "to_address", MALLORY)
    signed_edit = _provider(payments_on).sign(secret, execution_service.digest_for(proposal))

    with pytest.raises(ApprovalError, match="no longer matches what was signed"):
        _device_vote(payments_on, proposal, owner, key, secret, "approve", execution=signed_edit)

    assert ExecutionSignature.query.count() == 0
    assert approval_service.vote_of(proposal, owner.id) is None


def test_a_payment_edited_after_approval_leaves_signatures_that_no_longer_verify(payments_on):
    # The digest is recomputed from the row every time, never cached: editing the recipient after
    # an approval leaves a stored signature that no longer matches what the treasury would check,
    # which is exactly how the tampering is caught.
    owner, _other, vault, _treasury = _vault("tamper")
    proposal = _payment(vault, owner)
    approval_service.cast_vote(proposal, owner, PASSWORD, "approve")
    stored = _signature_of(proposal, owner)
    assert bytes(stored.digest) == execution_service.digest_for(proposal)

    proposal.action.to_address = MALLORY
    db.session.commit()

    assert bytes(stored.digest) != execution_service.digest_for(proposal)
    assert not _provider(payments_on).verify(
        bytes(stored.public_key),
        execution_service.digest_for(proposal),
        bytes(stored.signature),
    )
    # The vote's own binding check reports it too, so the decision stops counting either way.
    assert not approval_service.verify_proposal_binding(proposal).ok


def test_a_payment_row_edited_to_nonsense_is_named_rather_than_crashing(payments_on):
    # SQLite is untyped: a row edited at the database level must produce a refusal a person can
    # read, not an exception the vote path reports as an internal error.
    owner, _other, vault, _treasury = _vault("nonsense")
    proposal = _payment(vault, owner)
    _tamper(proposal, "value_wei", "not a number")

    with pytest.raises(ApprovalError, match="no longer matches what was signed"):
        approval_service.cast_vote(proposal, owner, PASSWORD, "approve")
    with pytest.raises(execution_service.ExecutionSignatureError, match="cannot be read"):
        execution_service.digest_for(proposal)


@pytest.mark.parametrize(
    "prefix, column, value",
    [("loose-data", "data_hex", "ab"), ("loose-to", "to_address", RECIPIENT.lower())],
)
def test_the_digest_reads_the_payment_as_strictly_as_a_signed_payload(
    payments_on, prefix, column, value
):
    # Call data without its 0x would otherwise have become empty call data, and a lower-case
    # address a checksummed one: coerced into a payment nobody signed, instead of refused (D22).
    owner, _other, vault, _treasury = _vault(prefix)
    proposal = _payment(vault, owner)
    _tamper(proposal, column, value)

    with pytest.raises(execution_service.ExecutionSignatureError, match="cannot be read"):
        execution_service.digest_for(proposal)


# --- approvals the contract would not count, refused before the password ---------------------


def test_a_rejection_signs_no_payment(payments_on):
    # A rejection authorises nothing, so there is nothing for the treasury to check.
    owner, _other, vault, _treasury = _vault("reject")
    proposal = _payment(vault, owner)

    approval_service.cast_vote(proposal, owner, PASSWORD, "reject", reason="Not this quarter.")

    assert _signature_of(proposal, owner) is None
    entry = LedgerEntry.query.filter_by(
        event_type="proposal_signed", ref_id=proposal.proposal_uuid
    ).one()
    assert "execution_signature_sha256" not in json.loads(entry.payload_json)


def test_a_signer_whose_key_was_rotated_is_refused_and_told_what_fixes_it(payments_on):
    # The contract counts keys, not people: a new key is a stranger to it until a reconfiguration
    # registers it. Refused before the password is tried, and before the vote is recorded.
    owner, _other, vault, _treasury = _vault("rotated")
    proposal = _payment(vault, owner)
    key_service.reissue_signing_key(owner, PASSWORD)
    db.session.commit()

    with pytest.raises(ApprovalError, match="reconfigured to register your current key"):
        approval_service.cast_vote(proposal, owner, WRONG, "approve")

    assert _signature_of(proposal, owner) is None
    assert approval_service.vote_of(proposal, owner.id) is None


def test_a_signer_the_treasury_never_registered_is_refused(payments_on):
    owner, other, vault, treasury = _vault("stranger")
    proposal = _payment(vault, owner)
    TreasurySigner.query.filter_by(treasury_id=treasury.id, user_id=other.id).delete()
    db.session.commit()

    with pytest.raises(ApprovalError, match="None of your keys is registered"):
        approval_service.cast_vote(proposal, other, WRONG, "approve")
    assert approval_service.vote_of(proposal, other.id) is None


def test_a_signer_whose_seat_is_held_by_their_phone_is_sent_to_their_phone(payments_on, registry):
    # D37: the treasury registered this signer's phone key, so the web cannot produce a signature
    # the contract would accept — and must say where it can be made.
    owner, _other, vault, treasury = _vault("phone")
    phone_key = key_service.enrol_device_key(
        owner, alg_id="ML-DSA-65", public_key=registry.signature("ML-DSA-65").keygen().public_key
    )
    row = TreasurySigner.query.filter_by(treasury_id=treasury.id, user_id=owner.id).one()
    row.key_id = phone_key.id
    db.session.commit()
    proposal = _payment(vault, owner)

    with pytest.raises(ApprovalError, match="approved on your phone"):
        approval_service.cast_vote(proposal, owner, WRONG, "approve")
    assert _signature_of(proposal, owner) is None


def test_a_signer_whose_registered_phone_was_revoked_is_not_sent_back_to_it(payments_on, client):
    # Revoking a phone does not change the treasury, which still holds its key. Sending its owner
    # "to your phone" would name a remedy they cannot use (review L).
    owner, _other, vault, treasury = _vault("revoked")
    key, _secret = _phone_seat(client, owner, treasury)
    proposal = _payment(vault, owner)
    device_service.revoke(Device.query.filter_by(key_id=key.id).one())

    with pytest.raises(ApprovalError, match="holds a phone that can no longer sign") as refused:
        approval_service.cast_vote(proposal, owner, WRONG, "approve")
    assert "on your phone" not in str(refused.value)
    assert "reconfigured" in str(refused.value)


def test_a_payment_whose_treasury_was_unlinked_cannot_be_approved(payments_on):
    owner, _other, vault, treasury = _vault("unlinked")
    proposal = _payment(vault, owner)
    treasury.status = "unlinked"
    db.session.commit()

    with pytest.raises(ApprovalError, match="no longer linked"):
        approval_service.cast_vote(proposal, owner, WRONG, "approve")
    assert approval_service.vote_of(proposal, owner.id) is None


def test_a_treasury_row_moved_to_another_vault_carries_none_of_this_vaults_payments(
    payments_on,
):
    # ``treasury_id`` is not signed. The binding check compares the treasury's address and chain;
    # this is the vault, which only the seat check compares.
    owner, _other, vault, treasury = _vault("moved")
    proposal = _payment(vault, owner)
    elsewhere = vault_service.create_vault(owner, "elsewhere", "", 1)
    treasury.vault_id = elsewhere.id
    db.session.commit()

    with pytest.raises(ApprovalError, match="no longer linked"):
        approval_service.cast_vote(proposal, owner, WRONG, "approve")


def test_an_unregistered_algorithm_is_refused(payments_on):
    # The verifier on chain is ML-DSA-65 alone; a registered key of another algorithm could never
    # be checked, whatever the vault says.
    owner, _other, vault, treasury = _vault("alg")
    proposal = _payment(vault, owner)
    registered = TreasurySigner.query.filter_by(treasury_id=treasury.id, user_id=owner.id).one()
    db.session.get(Key, registered.key_id).alg_id = "SLH-DSA-SHAKE-256f"
    db.session.commit()

    with pytest.raises(ApprovalError, match="verifies ML-DSA-65 signatures only"):
        approval_service.cast_vote(proposal, owner, WRONG, "approve")


def test_a_treasury_unlinked_while_the_password_is_checked_stores_nothing(payments_on, monkeypatch):
    # The checks before the password are a courtesy; the ones that count run again after it, just
    # before anything is written, because an unlink can land while Argon2id is running.
    owner, _other, vault, treasury = _vault("midway")
    proposal = _payment(vault, owner)
    original = key_service.unlock_secret_key

    def unlink_then_unlock(user, key, password):
        treasury.status = "unlinked"
        db.session.commit()
        return original(user, key, password)

    monkeypatch.setattr(key_service, "unlock_secret_key", unlink_then_unlock)

    with pytest.raises(ApprovalError, match="no longer linked"):
        approval_service.cast_vote(proposal, owner, PASSWORD, "approve")
    db.session.rollback()
    assert approval_service.vote_of(proposal, owner.id) is None
    assert ExecutionSignature.query.count() == 0


# --- what is recorded, and by whom -----------------------------------------------------------


def test_a_forged_execution_signature_is_refused_without_using_up_the_vote(payments_on, client):
    # The web path verifies its own bytes (ADR-0010); the phone path depends on this check
    # entirely. It must refuse before the one-per-signer slot is spent, or a single forged
    # request would lock the real signer out of the decision for good.
    owner, _other, vault, treasury = _vault("forged")
    key, secret = _phone_seat(client, owner, treasury)
    proposal = _payment(vault, owner)
    provider = _provider(payments_on)
    digest = execution_service.digest_for(proposal)
    forged = provider.sign(provider.keygen().secret_key, digest)

    with pytest.raises(ApprovalError, match="did not verify"):
        _device_vote(payments_on, proposal, owner, key, secret, "approve", execution=forged)
    assert approval_service.vote_of(proposal, owner.id) is None

    vote = _device_vote(
        payments_on,
        proposal,
        owner,
        key,
        secret,
        "approve",
        execution=provider.sign(secret, digest),
    )
    assert vote.custody == "device"
    stored = _signature_of(proposal, owner)
    assert stored.custody == "device" and stored.key_id == key.id


def test_a_signature_of_the_wrong_length_is_refused_before_the_verifier_sees_it(
    payments_on, client
):
    owner, _other, vault, treasury = _vault("short")
    key, secret = _phone_seat(client, owner, treasury)
    proposal = _payment(vault, owner)

    with pytest.raises(ApprovalError, match="must be .* bytes"):
        _device_vote(payments_on, proposal, owner, key, secret, "approve", execution=b"\x00" * 32)
    assert approval_service.vote_of(proposal, owner.id) is None


def test_a_rejection_carrying_an_execution_signature_is_refused(payments_on, client):
    # A valid execution signature stored beside a "no" would be an authorisation to pay from
    # someone who objected. Present if and only if the vote approves a payment.
    owner, _other, vault, treasury = _vault("rejectsig")
    key, secret = _phone_seat(client, owner, treasury)
    proposal = _payment(vault, owner)
    genuine = _provider(payments_on).sign(secret, execution_service.digest_for(proposal))

    with pytest.raises(ApprovalError, match="Only an approval of a payment"):
        _device_vote(payments_on, proposal, owner, key, secret, "reject", execution=genuine)
    assert ExecutionSignature.query.count() == 0

    _device_vote(payments_on, proposal, owner, key, secret, "reject")
    assert approval_service.tally(proposal) == (0, 1)
    assert ExecutionSignature.query.count() == 0


def test_no_caller_can_record_a_payment_approval_without_its_execution_signature(payments_on):
    # Both callers establish the rule with their own message; it is also held where every vote
    # passes, so a third caller cannot forget it.
    owner, _other, vault, _treasury = _vault("invariant")
    proposal = _payment(vault, owner)
    key = key_service.active_signing_key(owner)
    vote = key_service.sign_with_key(
        owner,
        key,
        PASSWORD,
        vote_signing_bytes(
            proposal_payload_hash=proposal.payload_hash, decision="approve", signer_id=owner.id
        ),
    )

    with pytest.raises(ApprovalError, match="must carry the signature the treasury checks"):
        approval_service._record_vote(
            proposal, owner, key, "approve", vote, reason=None, commit=True
        )
    assert approval_service.vote_of(proposal, owner.id) is None


def test_an_execution_signature_is_only_recorded_under_the_signers_own_key(payments_on):
    owner, other, vault, _treasury = _vault("whosekey")
    proposal = _payment(vault, owner)
    digest = execution_service.digest_for(proposal)

    with pytest.raises(execution_service.ExecutionSignatureError, match="does not belong"):
        execution_service.record(
            proposal, owner, key_service.active_signing_key(other), digest, b""
        )


def test_a_signer_racing_their_own_approval_is_told_they_already_voted(payments_on, monkeypatch):
    # Two submissions of one approval at the same moment each pass the advisory check before the
    # other commits, and the database's one-per-signer rule decides. On a payment either table can
    # be the one that refuses; both must read as what happened.
    owner, _other, vault, _treasury = _vault("race")
    proposal = _payment(vault, owner)
    approval_service.cast_vote(proposal, owner, PASSWORD, "approve")  # the one that won

    real = approval_service.vote_of
    calls = []

    def not_yet_visible(p, user_id):
        calls.append(user_id)
        return None if len(calls) == 1 else real(p, user_id)

    monkeypatch.setattr(approval_service, "vote_of", not_yet_visible)

    with pytest.raises(ApprovalError, match="already voted"):
        approval_service.cast_vote(proposal, owner, PASSWORD, "approve")
    assert len(calls) == 2  # the advisory check, then the one that explains the clash
    assert len(execution_service.signatures_for(proposal)) == 1


def test_an_execution_signature_stored_without_its_vote_is_not_called_a_vote(payments_on):
    # The app writes both rows in one transaction, so this is a damaged or restored database.
    # "You have already voted" would be false, and would leave the person no way to learn why.
    owner, _other, vault, _treasury = _vault("orphan")
    proposal = _payment(vault, owner)
    key = key_service.active_signing_key(owner)
    db.session.add(
        ExecutionSignature(
            proposal_id=proposal.id,
            signer_id=owner.id,
            key_id=key.id,
            alg_id=key.alg_id,
            backend=key.backend,
            public_key=key.public_key,
            digest=b"\x00" * 32,
            signature=b"\x00",
            identity_hex="0x",
        )
    )
    db.session.commit()

    with pytest.raises(ApprovalError, match="stored for you without its vote"):
        approval_service.cast_vote(proposal, owner, PASSWORD, "approve")
    assert approval_service.vote_of(proposal, owner.id) is None


# --- an app that cannot sign payments yet ----------------------------------------------------


def test_an_app_claiming_the_capability_cannot_approve_a_payment_with_a_vote_alone(
    payments_on, client
):
    # The capability header is a claim the client makes about itself. Until an app sends the
    # signature the treasury checks (Phase 6b), an approval from it would push the decision to
    # approved and tell the person a payment was authorised that nothing could execute.
    owner, _other, vault, _treasury = _vault("halfapp")
    proposal = _payment(vault, owner)
    _body, secret, auth = _enrol_over_http(client, owner)
    signature = base64.b64encode(
        _provider(payments_on).sign(
            secret,
            vote_signing_bytes(
                proposal_payload_hash=proposal.payload_hash, decision="approve", signer_id=owner.id
            ),
        )
    ).decode()

    vote = client.post(
        f"/api/v1/proposals/{proposal.proposal_uuid}/vote",
        json={"decision": "approve", "signature_b64": signature},
        headers={**auth, **PAYMENTS},
    )

    assert vote.status_code == 422
    body = vote.get_json()
    assert body["code"] == "execution_signature_required"  # something an app can branch on
    assert "Update the app" in body["error"]
    assert approval_service.tally(proposal) == (0, 0)
    assert ExecutionSignature.query.count() == 0


def test_the_same_app_may_still_reject_a_payment(payments_on, client):
    # Rejecting authorises nothing, so it needs no execution signature — and a signer who is
    # unhappy with a payment must never be blocked from saying so by their app's version.
    owner, _other, vault, _treasury = _vault("rejectapp")
    proposal = _payment(vault, owner)
    _body, secret, auth = _enrol_over_http(client, owner)
    signature = base64.b64encode(
        _provider(payments_on).sign(
            secret,
            vote_signing_bytes(
                proposal_payload_hash=proposal.payload_hash, decision="reject", signer_id=owner.id
            ),
        )
    ).decode()

    vote = client.post(
        f"/api/v1/proposals/{proposal.proposal_uuid}/vote",
        json={"decision": "reject", "signature_b64": signature},
        headers={**auth, **PAYMENTS},
    )

    assert vote.status_code == 201
    assert approval_service.tally(proposal) == (0, 1)
    assert ExecutionSignature.query.count() == 0
