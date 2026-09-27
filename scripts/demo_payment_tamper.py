"""The payment tamper demonstration (plan §1, step 4): edit an approved payment, and nothing moves.

    # against the database and chain the app is configured for (.env: DATABASE_URL, SEPOLIA_*)
    .venv/Scripts/python scripts/demo_payment_tamper.py --vault 1 --by ada@qvault.demo \\
        --approver brij@qvault.demo

What it does, saying each step as it goes:

1. raises a payment from the vault's treasury (0.0001 ETH to the relayer by default) and has the
   owner and each ``--approver`` approve it with their password, exactly as the web does;
2. **tampers with it after approval**: a direct database edit changes the recipient, the attack a
   compromised server or database administrator would make;
3. asks the executor to pay it. The executor re-checks the decision against what was signed
   (ADR-0009), finds the recipient is not the one the approvers signed, and refuses. It reads the
   chain to decide (``executed()``, the deadline, ``configNonce()``) and never simulates or sends
   anything: **this demonstration costs no ETH**;
4. reads the chain again: the treasury's balance is unchanged and ``executed()`` is false, with the
   Etherscan link to see it for yourself.

Even if the executor had been fooled, the treasury would refuse: the approvers' signatures are over
the original recipient, and the contract checks them itself (ADR-0023). The executor refusing
first is what keeps the relayer from paying gas for a transaction that cannot succeed (D20).

``--restore`` puts the original recipient back afterwards, so the decision's record verifies again.
Run it with the app's scheduler stopped (or against a database no app is serving): the demo advances
only its own payout, but a live scheduler could reach it between the approval and the edit.

Exit status: 0 the tampered payment was refused and nothing moved; 1 anything else.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
from collections.abc import Callable
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ETHERSCAN = "https://sepolia.etherscan.io"
#: Where the tampered payment would send the money: an address nobody controls.
ATTACKER = "0x000000000000000000000000000000000000bEEF"


@dataclass
class Outcome:
    refused: bool
    state: str
    reason: str | None
    balance_before: int
    balance_after: int
    executed: bool
    transactions_sent: int
    proposal_uuid: str

    @property
    def nothing_moved(self) -> bool:
        return (
            self.balance_after == self.balance_before
            and not self.executed
            and self.transactions_sent == 0
        )


def _eth(wei: int) -> str:
    from qvault.chain.action import format_wei

    return format_wei(wei)


def run(
    *,
    vault,
    by,
    approvers: list,
    password: str,
    relayer,
    to: str,
    value_wei: int,
    attacker: str = ATTACKER,
    restore: bool = False,
    say: Callable[[str], None] = print,
) -> Outcome:
    """The demonstration itself, inside an app context. Raises on anything but a clean run."""
    from qvault.extensions import db
    from qvault.models import ExecutionTransaction
    from qvault.services import approval_service, payout_service, proposal_service
    from qvault.services.proposal_service import PaymentRequest
    from qvault.services.treasury_service import linked_treasury

    treasury = linked_treasury(vault)
    if treasury is None:
        raise RuntimeError(f"{vault.name} has no linked treasury")
    before = relayer.rpc.get_balance(treasury.address)
    say(f"Treasury {treasury.address} holds {_eth(before)}.")

    # 1. A payment, approved as the web approves it.
    proposal = proposal_service.create_proposal(
        vault, by, "Tamper demonstration", "", payment=PaymentRequest(to, value_wei)
    )
    say(f"Raised: {proposal.action_text}")
    for approver in [by, *approvers]:
        approval_service.cast_vote(proposal, approver, password, "approve")
        who = approver.display_name or approver.email
        say(f"  approved by {who} (vote + payment authorisation)")
    if proposal.status != "approved":
        raise RuntimeError(f"the decision is {proposal.status}: not enough approvers were given")

    # 2. The attack: after approval, the database says someone else is to be paid.
    original = proposal.action.to_address
    proposal.action.to_address = attacker
    db.session.commit()
    say(f"TAMPERED: the database now says pay {attacker} instead of {original}.")

    # 3. The executor, on this payout only.
    execution = payout_service.queue(proposal)
    payout_service.advance(execution, relayer=relayer)
    db.session.refresh(execution)
    if execution.is_open:
        # The chain did not answer, so nothing was decided. Close it anyway: once restored, a
        # scheduler on this database would otherwise pay the demonstration's payment for real.
        execution.state = "failed"
        execution.reason = f"stopped by the tamper demonstration ({execution.reason})"
        db.session.commit()
    say(f"Executor: {execution.state}: {execution.reason}")

    # 4. The chain, read again.
    after = relayer.rpc.get_balance(treasury.address)
    executed = payout_service.executed_on_chain(relayer, treasury.address, proposal.payload_hash)
    sent = ExecutionTransaction.query.filter_by(execution_id=execution.id).count()
    say(f"Treasury {treasury.address} holds {_eth(after)}; executed() = {str(executed).lower()}.")
    say(f"Transactions sent: {sent}. See for yourself: {ETHERSCAN}/address/{treasury.address}")

    if restore:
        proposal.action.to_address = original
        db.session.commit()
        say("Restored the original recipient: the decision's record verifies again.")

    return Outcome(
        refused=execution.state == "failed" and "no longer matches" in (execution.reason or ""),
        state=execution.state,
        reason=execution.reason,
        balance_before=before,
        balance_after=after,
        executed=executed,
        transactions_sent=sent,
        proposal_uuid=proposal.proposal_uuid,
    )


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--vault", type=int, required=True, help="a vault with a linked treasury")
    parser.add_argument("--by", required=True, metavar="EMAIL", help="who raises the payment")
    parser.add_argument(
        "--approver",
        action="append",
        default=[],
        metavar="EMAIL",
        help="another approver, enough with --by to meet the threshold",
    )
    parser.add_argument("--to", help="the honest recipient (default: the relayer)")
    parser.add_argument("--amount", default="0.0001", help="ETH (default 0.0001)")
    parser.add_argument("--restore", action="store_true", help="put the recipient back afterwards")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    # Before config.py is read: no startup writes, no scheduler that could pay anything else.
    os.environ["AUTO_CREATE_DB"] = "false"
    os.environ["SCHEDULER_ENABLED"] = "false"
    password = os.environ.get("QVAULT_DEMO_PASSWORD")
    if not password:
        from seed_demo import PASSWORD as password  # the demo accounts' shared password

    from qvault import create_app
    from qvault.chain.action import parse_eth_value
    from qvault.chain.relayer import RelayerSettings
    from qvault.extensions import db
    from qvault.models import User, Vault

    app = create_app("production")  # loads .env, where the relayer's settings are
    relayer = RelayerSettings.from_environ(os.environ).build()
    app.config["ONCHAIN_EXECUTION_ENABLED"] = True  # this process only
    app.extensions["relayer"] = relayer  # approving reads configNonce() from the chain (D43)
    with app.app_context():
        vault = db.session.get(Vault, args.vault)
        by = User.query.filter_by(email=args.by).one_or_none()
        approvers = [User.query.filter_by(email=e).one_or_none() for e in args.approver]
        if vault is None or by is None or None in approvers:
            print("refused: no such vault or account", file=sys.stderr)
            return 1
        outcome = run(
            vault=vault,
            by=by,
            approvers=approvers,
            password=password,
            relayer=relayer,
            to=args.to or relayer.address,
            value_wei=parse_eth_value(args.amount),
            restore=args.restore,
        )
    if outcome.refused and outcome.nothing_moved:
        print("Refused, and nothing moved.")
        return 0
    print("UNEXPECTED: see above.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "scripts"))
    raise SystemExit(main())
