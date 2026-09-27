"""The payment tamper demonstration (``scripts/demo_payment_tamper.py``, plan §1 step 4).

Run against a treasury linked by the real job on the in-process node: a payment approved and then
edited in the database is refused by the executor, nothing is simulated or sent, the treasury's
balance and ``executed()`` are unchanged, and the refusal is in the ledger.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from test_payouts import PASSWORD, RECIPIENT, VALUE, _approved_payment
from test_payouts import world as payout_world  # noqa: F401 - the fixture, by this name

from qvault.models import Execution, ExecutionTransaction, LedgerEntry
from qvault.services import approval_service, payout_service

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def demo():
    spec = importlib.util.spec_from_file_location(
        "demo_payment_tamper", ROOT / "scripts" / "demo_payment_tamper.py"
    )
    module = importlib.util.module_from_spec(spec)
    # A dataclass in a module loaded this way looks itself up in sys.modules while it is built.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run(demo, world, **kwargs):
    said = []
    outcome = demo.run(
        vault=world.vault,
        by=world.users[0],
        approvers=[world.users[1]],
        password=PASSWORD,
        relayer=world.relayer,
        to=RECIPIENT,
        value_wei=VALUE,
        say=said.append,
        **kwargs,
    )
    return outcome, "\n".join(said)


def test_a_payment_edited_after_approval_is_refused_and_nothing_moves(
    demo, payout_world  # noqa: F811
):
    outcome, said = _run(demo, payout_world)
    assert outcome.refused, outcome.reason
    assert outcome.nothing_moved
    assert outcome.balance_before == outcome.balance_after == 10**18
    assert "no longer matches what was signed" in outcome.reason
    assert "TAMPERED" in said and "executed() = false" in said
    failed = LedgerEntry.query.filter_by(
        event_type="proposal_execution_failed", ref_id=outcome.proposal_uuid
    ).one()
    assert "no longer matches" in failed.payload_json


def test_restoring_the_recipient_makes_the_record_verify_again(demo, payout_world):  # noqa: F811
    outcome, said = _run(demo, payout_world, restore=True)
    assert outcome.refused and "Restored" in said
    execution = Execution.query.filter_by(state="failed").one()
    assert approval_service.verify_proposal_binding(execution.proposal).ok


def test_the_demonstration_pays_nothing_else(demo, payout_world):  # noqa: F811
    """It queues and advances its own payout only: another approved payment stays unpaid."""
    other = _approved_payment(payout_world)
    _run(demo, payout_world)
    assert payout_service.payout_of(other) is None
    assert ExecutionTransaction.query.count() == 0


def test_an_honest_payment_through_the_same_path_would_be_paid(payout_world):  # noqa: F811
    """The control: without the edit, the same queue-and-advance path gets as far as sending."""
    proposal = _approved_payment(payout_world)
    execution = payout_service.queue(proposal)
    payout_service.advance(execution, relayer=payout_world.relayer)
    assert execution.state == "submitting", execution.reason
    assert ExecutionTransaction.query.filter_by(execution_id=execution.id).count() == 1
