"""Reconfiguration (plan Phase 7b, D39, D44–D46): a treasury follows its vault on chain.

Built on ``test_payouts``' world: a treasury linked by the real 5b job on the in-process node,
whose fake ``reconfigure`` (``tests/fake_treasury.py``) checks what the contract checks — the
deadline, M approvals by current signers at the current nonce, the new signers' storage — and
keeps the new configuration. ``tests/test_link_anvil.py`` does it against the real contracts.
"""

from __future__ import annotations

import json

import pytest
from fake_ethereum import FINALITY_DEPTH, GENESIS_TIME
from test_payouts import (  # noqa: F401 - the fixture
    PASSWORD,
    RECIPIENT,
    VALUE,
    VERIFIER,
    _events,
    _execution,
    _sent,
)
from test_payouts import world as payout_world  # noqa: F401 - the fixture, by this name

from qvault.chain import treasury_artifact
from qvault.chain.evm import keccak256
from qvault.extensions import db
from qvault.models import LedgerEntry, Reconfiguration, TreasurySigner
from qvault.services import (
    approval_service,
    auth_service,
    key_service,
    payout_service,
    proposal_service,
    reconfiguration_service,
    vault_service,
)
from qvault.services.proposal_service import PaymentRequest, ProposalError
from qvault.services.reconfiguration_service import (
    ApprovalRefused,
    NeedsConfirmation,
    ReconfigurationRefused,
)


@pytest.fixture()
def rworld(payout_world):  # noqa: F811 - pytest injects the imported fixture by name
    world = payout_world
    # Verify approvals against whichever key the treasury (the database) says an identity is.
    provider = world.app.extensions["crypto"].signature("ML-DSA-65")

    def verify(identity, digest, signature):
        row = TreasurySigner.query.filter_by(identity_hex="0x" + identity.hex()).first()
        return row is not None and provider.verify(bytes(row.key.public_key), digest, signature)

    world.fake.verify = verify
    world.artifact = treasury_artifact.committed()
    world.record = {
        "contracts": {
            "ZKNOX_dilithium65": {
                "address": VERIFIER,
                "runtime_keccak256": "0x" + keccak256(b"\xfe").hex(),
            }
        },
        "treasuries": {},
    }
    return world


def _dara(world):
    dara = auth_service.register_user("dara@pay.test", "Dara", PASSWORD)
    vault_service.add_member(world.vault, dara.email, "signer", actor_id=world.users[0].id)
    db.session.commit()
    return dara


def _advance(world, reconfiguration, ticks=1):
    for _ in range(ticks):
        reconfiguration_service.advance(
            reconfiguration, relayer=world.relayer, artifact=world.artifact, record=world.record
        )
        world.node.mine()
    db.session.refresh(reconfiguration)
    return reconfiguration


def _until(world, reconfiguration, state, ticks=12):
    for _ in range(ticks):
        if reconfiguration.state == state or not reconfiguration.is_open:
            break
        _advance(world, reconfiguration)
    return reconfiguration


def _finalize(world, reconfiguration):
    world.node.advance(FINALITY_DEPTH + 1)
    return _advance(world, reconfiguration)


def _approve(reconfiguration, *users):
    for user in users:
        reconfiguration_service.approve_with_password(reconfiguration, user, PASSWORD)


def _request(world, **kwargs):
    return reconfiguration_service.request(
        world.vault, by=world.users[0], relayer=world.relayer, **kwargs
    )


def _done(world, reconfiguration, approvers):
    _until(world, reconfiguration, "collecting_approvals")
    assert reconfiguration.state == "collecting_approvals", reconfiguration.reason
    _approve(reconfiguration, *approvers)
    _advance(world, reconfiguration)  # submit
    _advance(world, reconfiguration)  # mined: finalizing
    _finalize(world, reconfiguration)
    return reconfiguration


# --- what differs ------------------------------------------------------------------------------


def test_a_freshly_linked_treasury_needs_no_change(rworld):
    change = reconfiguration_service.pending_change(rworld.vault)
    assert change is not None and change.empty
    with pytest.raises(ReconfigurationRefused, match="nothing to change"):
        _request(rworld)


def test_a_new_member_is_a_change_to_add(rworld):
    dara = _dara(rworld)
    change = reconfiguration_service.pending_change(rworld.vault)
    assert change.added == (dara.id,) and not change.removed and not change.rotated


# --- the whole path ---------------------------------------------------------------------------


def test_a_member_is_added_on_chain_and_the_new_set_pays_out(rworld):
    dara = _dara(rworld)
    reconfiguration = _request(rworld)
    assert reconfiguration.config_nonce == 0 and reconfiguration.state == "queued"

    _done(rworld, reconfiguration, rworld.users[:2])

    assert reconfiguration.state == "done", reconfiguration.reason
    treasury = rworld.treasury
    db.session.refresh(treasury)
    assert treasury.config_nonce == 1 and treasury.signer_count == 4
    assert sorted(row.user_id for row in treasury.signers) == sorted(
        [u.id for u in rworld.users] + [dara.id]
    )
    (event,) = _events("treasury_reconfigured")
    assert event["config_nonce"] == 1 and event["tx_hash"]

    # The new signer set pays out, without redeploying (plan: done when).
    proposal = proposal_service.create_proposal(
        rworld.vault, rworld.users[0], "Pay", "", payment=PaymentRequest(RECIPIENT, VALUE)
    )
    assert proposal.action.config_nonce == 1
    approval_service.cast_vote(proposal, dara, PASSWORD, "approve")
    approval_service.cast_vote(proposal, rworld.users[2], PASSWORD, "approve")
    payout_service.tick(relayer=rworld.relayer)
    rworld.node.mine()
    payout_service.tick(relayer=rworld.relayer)
    assert _execution(proposal).state == "confirmed"


def test_a_rotated_key_is_replaced_and_its_retired_key_approves_the_change(rworld):
    ada, brij, _chen = rworld.users
    old = key_service.active_signing_key(brij)
    key_service.reissue_signing_key(brij, PASSWORD)
    db.session.commit()
    change = reconfiguration_service.pending_change(rworld.vault)
    assert change.rotated == (brij.id,)
    reconfiguration = _request(rworld)

    # brij's seat is still the retired key: D39 lets it sign the change that replaces it.
    _done(rworld, reconfiguration, [ada, brij])

    assert reconfiguration.state == "done", reconfiguration.reason
    row = TreasurySigner.query.filter_by(treasury_id=rworld.treasury.id, user_id=brij.id).one()
    assert row.key_id == key_service.active_signing_key(brij).id != old.id


def test_removing_a_member_and_lowering_the_threshold_needs_confirmation(rworld):
    ada, _brij, chen = rworld.users
    vault_service.set_threshold(rworld.vault, 1, actor_id=ada.id)
    vault_service.remove_member(rworld.vault, chen.id, actor_id=ada.id)
    db.session.commit()

    with pytest.raises(NeedsConfirmation) as raised:
        _request(rworld)
    assert any("chen" in w for w in raised.value.warnings)
    assert Reconfiguration.query.count() == 0

    reconfiguration = _request(rworld, confirm=True)
    _done(rworld, reconfiguration, rworld.users[:2])
    assert reconfiguration.state == "done", reconfiguration.reason
    db.session.refresh(rworld.treasury)
    assert rworld.treasury.threshold_m == 1 and rworld.treasury.signer_count == 2


# --- refusals ---------------------------------------------------------------------------------


def test_only_the_owner_asks(rworld):
    _dara(rworld)
    with pytest.raises(ReconfigurationRefused, match="does not own"):
        reconfiguration_service.request(rworld.vault, by=rworld.users[1], relayer=rworld.relayer)


def test_one_open_at_a_time(rworld):
    _dara(rworld)
    _request(rworld)
    with pytest.raises(ReconfigurationRefused, match="already being reconfigured"):
        _request(rworld)


def test_records_that_disagree_with_the_chain_are_refused(rworld):
    _dara(rworld)
    rworld.treasury.config_nonce = 1  # a database edit
    db.session.commit()
    with pytest.raises(ReconfigurationRefused, match="an administrator must look"):
        _request(rworld)


def test_a_decision_naming_a_future_configuration_blocks_a_change(rworld):
    # D42: applying the change would bring that decision's approvals to life.
    proposal = proposal_service.create_proposal(
        rworld.vault, rworld.users[0], "Pay", "", payment=PaymentRequest(RECIPIENT, VALUE)
    )
    db.session.execute(
        db.text("UPDATE proposal_actions SET config_nonce = 1 WHERE proposal_id = :p"),
        {"p": proposal.id},
    )
    db.session.commit()
    _dara(rworld)
    with pytest.raises(ReconfigurationRefused, match="does not exist yet"):
        _request(rworld)


def test_too_few_current_signers_able_to_approve_is_refused(rworld):
    ada, brij, chen = rworld.users
    _dara(rworld)
    for user in (brij, chen):
        row = TreasurySigner.query.filter_by(treasury_id=rworld.treasury.id, user_id=user.id).one()
        row.key.secret_key_wrapped = None  # can no longer sign anything
    db.session.commit()
    with pytest.raises(ReconfigurationRefused, match="unlink and link a new treasury"):
        _request(rworld)


def test_payments_are_refused_while_a_change_is_open(rworld):
    payment = proposal_service.create_proposal(
        rworld.vault, rworld.users[0], "Pay", "", payment=PaymentRequest(RECIPIENT, VALUE)
    )
    _dara(rworld)
    _request(rworld)

    with pytest.raises(ProposalError, match="being reconfigured"):
        proposal_service.create_proposal(
            rworld.vault, rworld.users[0], "Pay", "", payment=PaymentRequest(RECIPIENT, VALUE)
        )
    with pytest.raises(approval_service.ApprovalError, match="being reconfigured"):
        approval_service.cast_vote(payment, rworld.users[0], PASSWORD, "approve")


# --- approvals (D46) --------------------------------------------------------------------------


def test_only_current_signers_approve_and_only_once(rworld):
    dara = _dara(rworld)
    reconfiguration = _until(rworld, _request(rworld), "collecting_approvals")
    with pytest.raises(ApprovalRefused, match="current signers"):
        _approve(reconfiguration, dara)  # joining, not yet a signer
    _approve(reconfiguration, rworld.users[0])
    with pytest.raises(ApprovalRefused, match="already approved"):
        _approve(reconfiguration, rworld.users[0])


def test_no_approval_is_signed_before_the_keys_are_registered(rworld):
    _dara(rworld)
    reconfiguration = _request(rworld)
    with pytest.raises(ApprovalRefused, match="still being registered"):
        _approve(reconfiguration, rworld.users[0])


def test_an_approval_is_signed_only_at_the_chains_nonce(rworld):
    _dara(rworld)
    reconfiguration = _until(rworld, _request(rworld), "collecting_approvals")
    rworld.fake.lies["configNonce"] = 1
    with pytest.raises(ApprovalRefused, match="changed since"):
        _approve(reconfiguration, rworld.users[0])


def test_it_waits_for_enough_approvals(rworld):
    _dara(rworld)
    reconfiguration = _until(rworld, _request(rworld), "collecting_approvals")
    _approve(reconfiguration, rworld.users[0])
    sent = _sent(rworld)
    _advance(rworld, reconfiguration)
    assert reconfiguration.state == "collecting_approvals"
    assert "1 of the 2" in reconfiguration.reason and _sent(rworld) == sent


# --- how it can end ---------------------------------------------------------------------------


def test_the_treasury_changed_by_something_else_voids_it(rworld):
    _dara(rworld)
    reconfiguration = _until(rworld, _request(rworld), "collecting_approvals")
    rworld.fake.lies["configNonce"] = 2
    _advance(rworld, reconfiguration)
    assert reconfiguration.state == "voided"


def test_approvals_past_their_deadline_expire(rworld):
    _dara(rworld)
    reconfiguration = _until(rworld, _request(rworld), "collecting_approvals")
    _approve(reconfiguration, *rworld.users[:2])
    rworld.node.advance(
        (reconfiguration.valid_until - GENESIS_TIME) // 12 + 10 - rworld.node.block_number
    )
    _advance(rworld, reconfiguration)
    assert reconfiguration.state == "expired"


def test_a_new_configuration_that_is_not_the_one_asked_for_is_not_recorded(rworld):
    _dara(rworld)
    reconfiguration = _until(rworld, _request(rworld), "collecting_approvals")
    _approve(reconfiguration, *rworld.users[:2])
    _advance(rworld, reconfiguration)
    _advance(rworld, reconfiguration)
    rworld.fake.lies["threshold"] = 3  # the chain disagrees with what was asked for
    _finalize(rworld, reconfiguration)
    assert reconfiguration.state == "failed" and "not the one asked for" in reconfiguration.reason
    db.session.refresh(rworld.treasury)
    assert rworld.treasury.config_nonce == 0 and rworld.treasury.signer_count == 3


def test_every_step_is_on_the_ledger(rworld):
    _dara(rworld)
    _done(rworld, _request(rworld), rworld.users[:2])
    kinds = [e.event_type for e in LedgerEntry.query.order_by(LedgerEntry.id)]
    assert kinds.count("treasury_reconfiguration_requested") == 1
    assert kinds.count("treasury_reconfiguration_approved") == 2
    assert kinds.count("treasury_reconfigured") == 1
    requested = json.loads(
        LedgerEntry.query.filter_by(event_type="treasury_reconfiguration_requested")
        .one()
        .payload_json
    )
    assert requested["config_nonce"] == 0


# --- found by the mutation pass --------------------------------------------------------------


def _collecting(world):
    _dara(world)
    return _until(world, _request(world), "collecting_approvals")


def test_an_approval_stored_for_another_identity_does_not_count(rworld):
    reconfiguration = _collecting(rworld)
    _approve(reconfiguration, *rworld.users[:2])
    # A database edit: brij's approval now claims chen's seat, an identity the treasury does hold.
    # Counted, it would be sent as chen's and the treasury would refuse the whole change.
    brij, chen = rworld.users[1], rworld.users[2]
    row = next(s for s in reconfiguration.signatures if s.signer_id == brij.id)
    row.identity_hex = (
        TreasurySigner.query.filter_by(treasury_id=rworld.treasury.id, user_id=chen.id)
        .one()
        .identity_hex
    )
    db.session.commit()
    sent = _sent(rworld)
    _advance(rworld, reconfiguration)
    assert "1 of the 2" in reconfiguration.reason and _sent(rworld) == sent


def test_an_approver_the_treasury_no_longer_holds_does_not_count(rworld):
    reconfiguration = _collecting(rworld)
    _approve(reconfiguration, *rworld.users[:2])
    held = [bytes.fromhex(r.identity_hex[2:]) for r in rworld.treasury.signers]
    gone = bytes.fromhex(reconfiguration.signatures[0].identity_hex[2:])
    rworld.fake.lies["signers"] = [i for i in held if i != gone]
    sent = _sent(rworld)
    _advance(rworld, reconfiguration)
    assert "1 of the 2" in reconfiguration.reason and _sent(rworld) == sent


def test_a_vault_whose_members_changed_after_asking_must_ask_again(rworld):
    reconfiguration = _dara(rworld) and _request(rworld)
    eve = auth_service.register_user("eve@pay.test", "Eve", PASSWORD)
    vault_service.add_member(rworld.vault, eve.email, "signer", actor_id=rworld.users[0].id)
    db.session.commit()
    _advance(rworld, reconfiguration)
    assert reconfiguration.state == "failed" and "ask again" in reconfiguration.reason


def test_an_unlinked_treasury_is_not_reconfigured(rworld):
    reconfiguration = _collecting(rworld)
    rworld.treasury.status = "unlinked"
    db.session.commit()
    _advance(rworld, reconfiguration)
    assert reconfiguration.state == "failed" and "unlinked" in reconfiguration.reason


def test_a_seat_held_by_a_phone_is_approved_on_the_phone_not_the_web(rworld):
    ada = rworld.users[0]
    reconfiguration = _collecting(rworld)
    provider = rworld.app.extensions["crypto"].signature("ML-DSA-65")
    phone_key = key_service.enrol_device_key(
        ada, alg_id="ML-DSA-65", public_key=provider.keygen().public_key
    )
    seat = TreasurySigner.query.filter_by(treasury_id=rworld.treasury.id, user_id=ada.id).one()
    seat.key_id = phone_key.id
    db.session.commit()
    with pytest.raises(ApprovalRefused, match="on your phone"):
        _approve(reconfiguration, ada)


def test_an_expired_change_ends_even_while_the_relayer_is_short(rworld):
    reconfiguration = _collecting(rworld)
    _approve(reconfiguration, *rworld.users[:2])
    rworld.node.advance(
        (reconfiguration.valid_until - GENESIS_TIME) // 12 + 10 - rworld.node.block_number
    )
    rworld.node.balances[rworld.relayer.address] = 10**15
    _advance(rworld, reconfiguration)
    assert reconfiguration.state == "expired"
