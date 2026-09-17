"""Linking as a job the app runs (plan D36, D38).

The engine itself is covered by ``test_treasury_link.py`` and, against the real contracts, by
``test_link_anvil.py``. What matters here is that the job carries it out safely when nobody is
watching: one chain action per tick, every transaction stored before it is sent, a restart between
any two steps, and a refusal to spend when the vault, the fees or the relayer say no.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fake_ethereum import FINALITY_DEPTH, GWEI, FakeNode
from fake_treasury import FakeTreasuries, fake_verifier
from sqlalchemy.exc import IntegrityError
from test_treasury_link import _phone

from qvault.chain import treasury_artifact
from qvault.chain.evm import keccak256
from qvault.chain.relayer import Relayer
from qvault.chain.rpc import EthRpc
from qvault.extensions import db
from qvault.models import LedgerEntry, Treasury, TreasuryJob, TreasuryJobTransaction
from qvault.services import (
    auth_service,
    key_service,
    treasury_jobs,
    treasury_service,
    vault_service,
)
from qvault.services.treasury_service import LinkRefused

SEPOLIA = 11_155_111
VERIFIER = "0x31a85de8CB44BC89c53487A69d20b3DC3dB7487C"
RELAYER_KEY = "0x" + "11" * 32
PASSWORD = "correct horse battery staple"
NOW = datetime(2026, 9, 18, 10, 0, tzinfo=UTC)


@pytest.fixture()
def world(app):
    app.config["ONCHAIN_EXECUTION_ENABLED"] = True
    app.config["TREASURY_RELAYER_RESERVE_WEI"] = 10**16
    app.config["TREASURY_LINK_COOLDOWN_DAYS"] = 30
    node = FakeNode()
    rpc = EthRpc(node.transport)
    relayer = Relayer(rpc, RELAYER_KEY, chain_id=SEPOLIA, sleep=lambda seconds: node.mine())
    node.fund(relayer.address, 10**18)
    node.on(VERIFIER, fake_verifier)
    node.set_nonce(VERIFIER, 1)
    artifact = treasury_artifact.committed()
    FakeTreasuries(node, artifact).install(VERIFIER)
    record = {
        "contracts": {
            "ZKNOX_dilithium65": {
                "address": VERIFIER,
                "runtime_keccak256": "0x" + keccak256(b"\xfe").hex(),
            }
        },
        "treasuries": {},
    }
    users = [
        auth_service.register_user(f"{name}@job.test", name.title(), PASSWORD)
        for name in ("ada", "brij", "chen")
    ]
    vault = vault_service.create_vault(users[0], "Treasury", "", 2)
    for user in users[1:]:
        vault_service.add_member(vault, user.email, "signer", actor_id=users[0].id)
    db.session.commit()
    return SimpleNamespace(
        app=app,
        node=node,
        rpc=rpc,
        relayer=relayer,
        artifact=artifact,
        record=record,
        users=users,
        vault=vault,
    )


def _request(world, by=None):
    return treasury_jobs.request_link(
        world.vault, by=by or world.users[0], relayer=world.relayer, now=lambda: NOW
    )


def _advance(world, job, *, relayer=None):
    return treasury_jobs.advance(
        job,
        relayer=relayer or world.relayer,
        artifact=world.artifact,
        record=world.record,
        now=lambda: NOW,
    )


def _drive(world, job, *, ticks=40, mine=True, finalize=True, fresh_relayer=False):
    """Tick until the job settles, as the scheduler would, mining and ageing the chain between."""
    states = []
    for _ in range(ticks):
        if not job.is_open:
            break
        relayer = None
        if fresh_relayer:
            # A different process, with nothing remembered in memory.
            relayer = Relayer(world.rpc, RELAYER_KEY, chain_id=SEPOLIA)
            db.session.expire_all()
        _advance(world, job, relayer=relayer)
        states.append((job.state, job.reason))
        if mine:
            world.node.mine()
        if finalize:
            world.node.advance(FINALITY_DEPTH + 1)
    return states


# --- asking for one --------------------------------------------------------------------------


def test_an_owner_can_ask_and_nothing_is_sent_yet(world):
    job = _request(world)
    assert (job.state, job.kind, job.requested_by_id) == ("queued", "link", world.users[0].id)
    assert json.loads(job.chosen_keys) == {str(user.id): user.keys[0].id for user in world.users}
    assert world.node.sent() == []
    assert LedgerEntry.query.filter_by(event_type="treasury_link_requested").count() == 1


@pytest.mark.parametrize(
    ("setup", "message"),
    [
        (lambda world: None, "does not own"),
        (lambda world: world.app.config.update(ONCHAIN_EXECUTION_ENABLED=False), "switched off"),
        (
            lambda world: world.node.balances.update({world.relayer.address: 10**15}),
            "below the 0.0100 ETH reserve",
        ),
    ],
)
def test_a_request_is_refused_with_its_reason(world, setup, message):
    by = world.users[0]
    if setup(world) is None and message == "does not own":
        by = world.users[1]  # a signer, not the owner
    with pytest.raises(LinkRefused, match=message):
        _request(world, by=by)
    assert TreasuryJob.query.count() == 0


def test_a_second_request_is_refused_while_one_is_open(world):
    _request(world)
    with pytest.raises(LinkRefused, match="already having one created"):
        _request(world)


def test_the_database_refuses_two_open_jobs_for_one_vault(world):
    _request(world)
    db.session.add(
        TreasuryJob(
            vault_id=world.vault.id,
            kind="link",
            requested_by_id=world.users[0].id,
            state="queued",
            chosen_keys="{}",
        )
    )
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_a_vault_that_already_has_a_treasury_is_refused(world):
    job = _request(world)
    _drive(world, job)
    assert job.state == "done"
    with pytest.raises(LinkRefused, match="already has a treasury"):
        _request(world)


def test_a_vault_cannot_be_linked_again_within_the_cooldown(world):
    job = _request(world)
    _drive(world, job)
    Treasury.query.one().status = "unlinked"
    db.session.commit()
    with pytest.raises(LinkRefused, match="can be created from 2026-10-18"):
        _request(world)
    assert treasury_jobs.remaining_limits(world.vault, now=lambda: NOW)["can_link_from"]


# --- doing the work --------------------------------------------------------------------------


def test_a_job_links_the_vault_one_chain_action_at_a_time(world):
    job = _request(world)
    states = _drive(world, job)

    assert job.state == "done" and job.reason is None and job.finished_at == NOW
    assert [state for state, _reason in states][:2] == ["registering_keys", "registering_keys"]
    assert "deploying" in [state for state, _ in states] and "finalizing" in [
        state for state, _ in states
    ]
    treasury = Treasury.query.one()
    assert job.treasury_id == treasury.id and treasury.is_linked
    assert [row.user_id for row in treasury.signers] == [user.id for user in world.users]
    assert LedgerEntry.query.filter_by(event_type="treasury_linked").count() == 1

    purposes = [tx.purpose for tx in job.transactions]
    assert purposes == [f"set_key:{user.id}" for user in world.users] + ["deploy"]
    assert {tx.state for tx in job.transactions} == {"mined"}
    assert all(tx.block_number and tx.gas_used and int(tx.fee_wei) > 0 for tx in job.transactions)
    # One transaction per chain action, and each was stored before it was sent.
    assert len(world.node.sent()) == len(purposes)


def test_a_job_survives_a_restart_between_every_step(world):
    job = _request(world)
    _drive(world, job, fresh_relayer=True)
    assert job.state == "done"
    assert len(world.node.sent()) == 4  # three keys and one deployment, each sent once
    assert Treasury.query.count() == 1


def test_a_send_whose_answer_is_lost_is_settled_rather_than_sent_again(world):
    job = _request(world)
    _advance(world, job)  # queued -> registering_keys
    world.node.lose_answer("eth_sendRawTransaction")
    _advance(world, job)

    assert job.state == "registering_keys" and "sent" in job.reason
    assert TreasuryJobTransaction.query.count() == 1  # stored before it was sent (D21)
    _drive(world, job)
    assert job.state == "done" and len(world.node.sent()) == 4


def test_a_fee_spike_makes_a_job_wait_and_it_goes_on_afterwards(world):
    job = _request(world)
    _advance(world, job)
    world.node.base_fee = 3 * GWEI
    _advance(world, job)
    assert job.state == "registering_keys" and job.reason.startswith("the network fee is above")
    assert world.node.sent() == []

    world.node.base_fee = GWEI
    _drive(world, job)
    assert job.state == "done"


def test_a_relayer_below_its_reserve_waits_instead_of_spending(world):
    job = _request(world)
    _advance(world, job)
    world.node.balances[world.relayer.address] = 10**15
    _advance(world, job)
    assert job.state == "registering_keys" and "reserve" in job.reason
    assert world.node.sent() == []

    world.node.balances[world.relayer.address] = 10**18
    _drive(world, job)
    assert job.state == "done"


def test_a_job_waits_for_finality_before_writing_anything(world):
    job = _request(world)
    _drive(world, job, finalize=False)
    assert job.state == "finalizing" and "finalize" in job.reason
    assert Treasury.query.count() == 0

    world.node.advance(FINALITY_DEPTH + 1)
    _drive(world, job)
    assert job.state == "done" and Treasury.query.count() == 1


def test_a_vault_changed_after_the_request_fails_the_job_without_spending_more(world):
    job = _request(world)
    _advance(world, job)
    _advance(world, job)  # one key registered
    world.node.mine()
    dara = auth_service.register_user("dara@job.test", "Dara", PASSWORD)
    vault_service.add_member(world.vault, dara.email, "signer", actor_id=world.users[0].id)

    sent = len(world.node.sent())
    _advance(world, job)
    assert job.state == "failed" and "changed after this was asked for" in job.reason
    assert len(world.node.sent()) == sent and Treasury.query.count() == 0

    # Review H-2: the gas this job spent counts against the vault, so it cannot simply ask
    # again and pay for another treasury; the cooldown has to pass first.
    with pytest.raises(LinkRefused, match="can be created from"):
        _request(world)
    assert len(world.node.sent()) == sent


def test_the_scheduler_advances_the_job_that_waited_longest(world):
    assert (
        treasury_jobs.tick(
            relayer=world.relayer, artifact=world.artifact, record=world.record, now=lambda: NOW
        )
        is None
    )
    job = _request(world)
    assert (
        treasury_jobs.tick(
            relayer=world.relayer, artifact=world.artifact, record=world.record, now=lambda: NOW
        ).id
        == job.id
    )
    assert job.state == "registering_keys"


def test_what_the_app_shows_about_a_vaults_treasury(world):
    empty = treasury_jobs.view(world.vault, now=lambda: NOW)
    assert empty == {"treasury": None, "job": None, "limits": {"can_link_from": None}}

    job = _request(world)
    waiting = treasury_jobs.view(world.vault, now=lambda: NOW)
    assert waiting["treasury"] is None and waiting["job"]["state"] == "queued"

    _drive(world, job)
    done = treasury_jobs.view(world.vault, now=lambda: NOW)
    assert done["job"]["state"] == "done"
    assert done["treasury"]["address"] == Treasury.query.one().address
    assert done["treasury"]["threshold_m"] == 2
    assert [signer["custody"] for signer in done["treasury"]["signers"]] == ["password"] * 3
    assert done["limits"]["can_link_from"] == (NOW + timedelta(days=30)).isoformat()


# --- what the review of Phase 5b found --------------------------------------------------------


def test_a_deployment_is_remembered_from_its_own_receipt(world, monkeypatch):
    """Review H-1: re-deriving the address by scanning is a guess, and a guess that misses pays
    for a second treasury."""
    job = _request(world)
    while job.state != "deploying":
        _advance(world, job)
        world.node.mine()
    _advance(world, job)  # sends the deployment
    world.node.mine()
    monkeypatch.setattr(treasury_jobs, "find_deployed_treasury", lambda *a, **k: None)
    _advance(world, job)  # settles it

    deploy = next(tx for tx in job.transactions if tx.purpose == "deploy")
    assert deploy.state == "mined" and deploy.created_address == job.treasury_address
    assert job.state == "finalizing"
    sent = len(world.node.sent())
    _drive(world, job)
    assert job.state == "done" and len(world.node.sent()) == sent  # no second deployment


def test_a_signer_cannot_stop_a_job_by_changing_their_own_choice(world, registry):
    """Review H-2: a non-owner could otherwise burn the relayer's ETH at will."""
    job = _request(world)
    _advance(world, job)
    _advance(world, job)  # one key registered
    world.node.mine()

    chen = world.users[2]
    phone_key, _device = _phone(chen, registry)
    treasury_service.set_key_choice(chen, custody="device", device_key=phone_key)

    _drive(world, job)
    assert job.state == "done"
    registered = {row.user_id: row.key_id for row in Treasury.query.one().signers}
    assert registered[chen.id] == key_service.active_signing_key(chen).id  # the pinned key
    assert registered[chen.id] != phone_key.id


def test_a_job_that_spent_nothing_leaves_the_cooldown_alone(world):
    job = _request(world)
    treasury_jobs.cancel(job, by=world.users[0], now=lambda: NOW)
    assert job.state == "failed" and job.reason == "stopped by ada@job.test"
    assert _request(world).state == "queued"  # nothing was spent, so nothing is used up


def test_only_the_owner_or_an_administrator_can_stop_a_job(world):
    job = _request(world)
    with pytest.raises(LinkRefused, match="does not own"):
        treasury_jobs.cancel(job, by=world.users[1], now=lambda: NOW)
    assert job.is_open


def test_a_transaction_signed_by_another_relayer_key_waits_for_it(world):
    """Review M-1: settling it against another account's nonces would say nothing."""
    job = _request(world)
    _advance(world, job)
    _advance(world, job)  # a setKey is in flight
    stranger = Relayer(world.rpc, "0x" + "22" * 32, chain_id=SEPOLIA)
    world.node.fund(stranger.address, 10**18)

    _advance(world, job, relayer=stranger)
    assert job.state == "registering_keys"
    assert "different relayer key" in job.reason
    assert len(world.node.sent()) == 1  # nothing sent from the new key


def test_a_wrong_chain_is_waited_out_rather_than_failing_the_job(world):
    """Review M-2: a setting an administrator can fix must not end the job for good."""
    job = _request(world)
    _advance(world, job)
    world.node.chain_id = 1
    _advance(world, job)
    assert job.state == "registering_keys" and "wrong chain" in job.reason

    world.node.chain_id = SEPOLIA
    world.relayer._chain_checked = False
    _drive(world, job)
    assert job.state == "done"


def test_a_job_gives_up_rather_than_ticking_for_ever(world, monkeypatch):
    """Review M-3: an open job holds the vault, so it must end by itself."""
    monkeypatch.setattr(treasury_jobs, "MAX_ATTEMPTS", 3)
    job = _request(world)
    world.node.balances[world.relayer.address] = 0
    for _ in range(5):
        _advance(world, job)
    assert job.state == "failed" and job.reason.startswith("gave up:")
    assert job.finished_at == NOW


def test_a_crash_between_the_treasury_and_the_job_is_picked_up(world):
    """Review M-4: the treasury is committed by itself; the job's own commit may not happen."""
    job = _request(world)
    _drive(world, job)
    treasury = Treasury.query.one()
    job.state, job.reason, job.treasury_id, job.finished_at = "finalizing", "", None, None
    db.session.commit()

    _advance(world, job)
    assert job.state == "done" and job.treasury_id == treasury.id
    assert Treasury.query.count() == 1


def test_an_unexpected_error_is_logged_not_shown(world, monkeypatch):
    """Review M-4: reasons are read by every member of the vault."""

    def boom(*args, **kwargs):
        raise RuntimeError("UNIQUE constraint failed: treasuries.vault_id [SQL: INSERT ...]")

    monkeypatch.setattr(treasury_jobs, "_signers", boom)
    job = _request(world)
    _advance(world, job)
    assert job.state == "queued" and "an administrator" in job.reason
    assert "SQL" not in job.reason and "UNIQUE" not in job.reason


def test_the_reserve_counts_what_the_action_would_cost(world):
    """Review L-3: a reserve only checked before the spend is crossed by every action."""
    world.app.config["TREASURY_RELAYER_RESERVE_WEI"] = 10**16
    cost = treasury_jobs.expected_cost_wei(3, relayer=world.relayer)
    world.node.balances[world.relayer.address] = 10**16 + cost // 4
    with pytest.raises(LinkRefused, match="would leave it below"):
        _request(world)


def test_nothing_is_written_while_the_feature_is_off(world):
    """Review L-4: including the last step, which writes the treasury row."""
    job = _request(world)
    while job.state != "finalizing":
        _advance(world, job)
        world.node.mine()
        world.node.advance(FINALITY_DEPTH + 1)
    world.app.config["ONCHAIN_EXECUTION_ENABLED"] = False
    _advance(world, job)
    assert job.state == "finalizing" and "switched off" in job.reason
    assert Treasury.query.count() == 0


def test_the_scheduler_takes_the_job_that_waited_longest(world):
    first = _request(world)
    other_vault = vault_service.create_vault(world.users[0], "Second", "", 1)
    second = treasury_jobs.request_link(
        other_vault, by=world.users[0], relayer=world.relayer, now=lambda: NOW
    )
    first.updated_at = NOW - timedelta(hours=1)
    db.session.commit()
    picked = treasury_jobs.tick(
        relayer=world.relayer, artifact=world.artifact, record=world.record, now=lambda: NOW
    )
    assert picked.id == first.id and second.state == "queued"


def test_a_key_registration_that_reverts_on_chain_fails_the_job(world):
    """It simulated cleanly and reverted anyway: no later tick can fix that."""
    job = _request(world)
    _advance(world, job)
    _advance(world, job)  # sends the first setKey
    world.node.mine()
    for receipt in world.node._receipts.values():
        receipt["status"] = "0x0"

    _advance(world, job)  # settles it as reverted
    _advance(world, job)
    assert job.state == "failed" and "reverted on chain" in job.reason
    assert job.transactions[0].state == "reverted"
    assert Treasury.query.count() == 0


def test_a_superseded_transaction_is_sent_again(world):
    job = _request(world)
    _advance(world, job)
    _advance(world, job)  # a setKey is in flight
    (tx_hash,) = [tx.tx_hash for tx in job.transactions]
    world.node.drop(bytes.fromhex(tx_hash[2:]))
    # Something else of the relayer's takes that nonce, far enough back to be certain of it.
    world.relayer.wait_for_receipt(
        world.relayer.send_call(world.relayer.address, b""), timeout_s=5, poll_s=0
    )
    world.node.advance(20)

    _advance(world, job)
    assert job.transactions[0].state == "superseded"
    _drive(world, job)
    assert job.state == "done"
    assert [tx.state for tx in job.transactions].count("superseded") == 1
    assert [tx.state for tx in job.transactions].count("mined") == 4
    # Two transactions for that one key: the *last* is the one that counts.
    same_purpose = [tx for tx in job.transactions if tx.purpose == job.transactions[0].purpose]
    assert [tx.state for tx in same_purpose] == ["superseded", "mined"]


def test_one_signed_transaction_is_one_row_however_often_it_is_sent(world):
    # A transaction dropped from the mempool and sent again at the same nonce and fee is the
    # *same* transaction, hash included. Storing it a second time breaks the unique index on the
    # hash, so a job that was doing nothing worse than re-sending would die in the database.
    job = _request(world)
    prepared = []
    world.relayer.send_call(world.relayer.address, b"", on_prepared=prepared.append)
    treasury_jobs._record_transaction(job, "set_key:1", prepared[0])
    treasury_jobs._record_transaction(job, "set_key:1", prepared[0])

    rows = TreasuryJobTransaction.query.filter_by(job_id=job.id).all()
    assert [(row.tx_hash, row.state) for row in rows] == [
        ("0x" + prepared[0].tx_hash.hex(), "sent")
    ]


def test_a_relayer_on_the_wrong_chain_waits_for_an_administrator(world):
    # Review M-2: an endpoint pointed at the wrong chain is a setting to put right, not a reason
    # to fail the job and make the owner ask again.
    job = _request(world)
    world.node.chain_id = 1  # the endpoint was pointed at mainnet
    fresh = Relayer(world.rpc, RELAYER_KEY, chain_id=SEPOLIA, sleep=lambda s: world.node.mine())
    _advance(world, job, relayer=fresh)  # queued: nothing on chain yet
    _advance(world, job, relayer=fresh)  # the first step that would spend

    assert job.is_open and job.transactions == []
    assert job.reason == (
        "the Ethereum endpoint is on the wrong chain; an administrator must fix the setting"
    )

    world.node.chain_id = SEPOLIA  # the setting is put right
    _drive(world, job, fresh_relayer=True)
    assert job.state == "done"


def test_a_replacement_in_flight_is_waited_for_rather_than_paid_for_twice(world):
    # Two transactions for one registration: what happens next turns on the *last* of them.
    # Reading the first would see a superseded transaction, conclude nothing of ours is in
    # flight, and pay 8.7M gas for the same key a third time.
    job = _request(world)
    _advance(world, job)
    _advance(world, job)  # a setKey is in flight
    (tx_hash,) = [tx.tx_hash for tx in job.transactions]
    world.node.drop(bytes.fromhex(tx_hash[2:]))
    world.relayer.wait_for_receipt(
        world.relayer.send_call(world.relayer.address, b""), timeout_s=5, poll_s=0
    )
    world.node.advance(20)
    while len(job.transactions) < 2:  # marked superseded, then sent again
        _advance(world, job)
    assert [tx.state for tx in job.transactions] == ["superseded", "sent"]

    _advance(world, job)
    assert [tx.state for tx in job.transactions] == ["superseded", "sent"]
    assert "waiting" in job.reason


def test_who_asked_is_who_the_record_says_linked_it(world):
    job = _request(world, by=world.users[0])
    _drive(world, job)
    treasury = Treasury.query.one()
    assert treasury.linked_by_id == world.users[0].id
    entry = LedgerEntry.query.filter_by(event_type="treasury_linked").one()
    assert entry.actor == f"user:{world.users[0].id}"


def test_the_record_names_who_asked_even_when_they_sign_last(world):
    # Signers are registered in a fixed order, and the owner need not come first in it. The
    # record has to name the person who asked for the treasury, not whoever happens to be
    # signer number one.
    owner = auth_service.register_user("zoe@job.test", "Zoe", PASSWORD)  # the newest account
    vault = vault_service.create_vault(owner, "Grants", "", 2)
    for user in world.users[:2]:
        vault_service.add_member(vault, user.email, "signer", actor_id=owner.id)
    db.session.commit()
    job = treasury_jobs.request_link(vault, by=owner, relayer=world.relayer, now=lambda: NOW)
    _drive(world, job)

    assert job.state == "done"
    treasury = Treasury.query.filter_by(vault_id=vault.id).one()
    assert treasury.signers[0].user_id == world.users[0].id  # not the owner
    assert treasury.linked_by_id == owner.id
    entry = LedgerEntry.query.filter_by(event_type="treasury_linked", vault_id=vault.id).one()
    assert entry.actor == f"user:{owner.id}"


def test_the_view_says_when_a_registered_key_was_replaced(world):
    job = _request(world)
    _drive(world, job)
    key = key_service.active_signing_key(world.users[1])
    key.status, key.can_sign = "retired", False
    db.session.commit()
    signers = treasury_jobs.view(world.vault, now=lambda: NOW)["treasury"]["signers"]
    assert [signer["key_active"] for signer in signers] == [True, False, True]


def test_a_transaction_the_node_dropped_is_sent_again_not_waited_on_for_ever(world):
    """Same nonce, same fee, same bytes: the same transaction, in flight once more."""
    job = _request(world)
    _advance(world, job)
    _advance(world, job)
    (tx,) = job.transactions
    world.node.drop(bytes.fromhex(tx.tx_hash[2:]))
    assert world.node.pending() == []

    _advance(world, job)  # broadcasts the very same transaction again
    assert [t.hex() for t in world.node.pending()] == [tx.tx_hash[2:]]
    assert len(job.transactions) == 1 and job.transactions[0].state == "sent"

    _drive(world, job)
    assert job.state == "done"
    assert len(job.transactions) == 4  # nothing was signed twice
