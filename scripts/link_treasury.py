"""Link a vault to a treasury contract on Sepolia (plan Phase 5, D28–D34).

    # a dry run: what would be registered and deployed, and what it costs. Sends and writes nothing.
    export DATABASE_URL="postgresql+psycopg://..."
    .venv/Scripts/python scripts/link_treasury.py --vault 3 --by ada@qvault.demo

    # a phone approver registers their phone key instead of their password key (D29)
    ... --vault 3 --by ada@qvault.demo --device chen@qvault.demo

    # spend ETH and link (asks nothing; run the dry run first and read it)
    ... --vault 3 --by ada@qvault.demo --device chen@qvault.demo --broadcast

    # later: is the linked treasury still exactly this vault's? Read-only.
    ... --vault 3 --check

    # after the vault's signers or threshold change: unlink (nothing on chain changes), then link
    ... --vault 3 --by ada@qvault.demo --unlink

The database is whatever ``DATABASE_URL`` names; the line starting ``Database`` says which, with
the password hidden. Link against the database the demo runs on (D28). The relayer settings
(``SEPOLIA_RPC_URL``, ``SEPOLIA_CHAIN_ID``, ``EXECUTOR_PRIVATE_KEY``) and the app's secrets come
from ``.env``. The app is opened without its startup writes and without its scheduler.

A broadcast registers each signer's key that is not already on chain, deploys the treasury unless
an identical one is already deployed, waits until every block involved is finalized (about 13
minutes), checks the whole contract against the database's keys, and only then writes the
database, once. If it stops at any point, run the same command again: nothing already on chain is
paid for twice. The linked treasury is then added to ``chain/deployments/sepolia.json``.

Exit status: 0 done (or a clean dry run or check), 1 refused, unfinished or failing its check.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
from datetime import UTC, datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ETHERSCAN = "https://sepolia.etherscan.io"


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--vault", type=int, required=True, help="the vault's id")
    parser.add_argument(
        "--by", metavar="EMAIL", help="the administrator linking it (required unless --check)"
    )
    parser.add_argument(
        "--device",
        action="append",
        default=[],
        metavar="EMAIL",
        help="register this signer's one active phone key instead of their password key",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--broadcast", action="store_true", help="spend ETH and link")
    mode.add_argument("--check", action="store_true", help="check a linked treasury; read-only")
    mode.add_argument(
        "--unlink",
        action="store_true",
        help="mark the linked treasury unlinked so the vault can be linked again; sends nothing",
    )
    args = parser.parse_args(argv)
    if not args.check and not args.by:
        parser.error("--by is required unless --check")
    if (args.check or args.unlink) and args.device:
        parser.error("--device only applies to linking")
    return args


def _eth(wei: int) -> str:
    return f"{wei / 10**18:.6f} ETH"


def _gwei(wei: int) -> str:
    return f"{wei / 10**9:.4f} gwei"


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    # Before anything imports config.py, which reads the environment once (D28).
    os.environ["AUTO_CREATE_DB"] = "false"
    os.environ["SCHEDULER_ENABLED"] = "false"

    from sqlalchemy.engine import make_url

    from qvault import create_app
    from qvault.chain import treasury_artifact
    from qvault.chain.deployments import DeploymentError, deployments_path, load_record
    from qvault.chain.evm import ChainValueError
    from qvault.chain.relayer import RelayerError, RelayerSettings
    from qvault.chain.rpc import RpcError
    from qvault.extensions import db
    from qvault.models import User, Vault
    from qvault.services import treasury_service as service

    app = create_app("production")
    print(
        "Database :",
        make_url(app.config["SQLALCHEMY_DATABASE_URI"]).render_as_string(hide_password=True),
    )
    try:
        relayer = RelayerSettings.from_environ(os.environ).build()
        record_path = deployments_path(relayer.chain_id)
        record = load_record(record_path, relayer.chain_id, must_exist=True)
        artifact = treasury_artifact.committed()
    except (RelayerError, DeploymentError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1

    with app.app_context():
        try:
            schema = service.schema_problems()
            if schema:
                raise service.LinkRefused(
                    ["this database is not the schema this code expects", *schema]
                )
            vault = db.session.get(Vault, args.vault)
            if vault is None:
                raise service.LinkRefused([f"there is no vault {args.vault} in this database"])
            print(
                f"Vault    : #{vault.id} {vault.name} "
                f"({vault.policy.threshold_m} of {len(vault.signer_ids())})"
            )
            linked = service.linked_treasury(vault)
            by = None
            if args.by:
                by = User.query.filter_by(email=args.by.strip().lower()).one_or_none()
                if by is None:
                    raise service.LinkRefused([f"there is no user {args.by} in this database"])
            if args.unlink:
                return _unlink(vault, linked, by, relayer, record_path)
            if args.check or linked is not None:
                return _check(args, linked, relayer, record, record_path, artifact)

            plan = service.plan_link(
                vault,
                by=by,
                device_emails=set(args.device),
                relayer=relayer,
                record=record,
                artifact=artifact,
            )
            _print_plan(plan)
            if not args.broadcast:
                print("\nDry run: nothing was sent and nothing was written.")
                print("To link, run the same command with --broadcast.")
                return 0

            done = service.link(
                plan,
                relayer=relayer,
                artifact=artifact,
                now=lambda: datetime.now(UTC),
                progress=lambda message: print(message, flush=True),
            )
            treasury = done.treasury
            print(f"\nLinked {vault.name} to {treasury.address}; spent {_eth(done.fee_wei)}.")
            _record(record_path, relayer.chain_id, treasury)
            _print_verification(plan, treasury, artifact)
            return 0
        except service.LinkRefused as exc:
            print("\nrefused:", file=sys.stderr)
            for problem in exc.problems:
                print(f"  - {problem}", file=sys.stderr)
            return 1
        except (service.LinkError, RelayerError, RpcError, DeploymentError, ChainValueError) as exc:
            print(f"\nnot finished: {exc}", file=sys.stderr)
            print("Run the same command again to continue.", file=sys.stderr)
            return 1


def _record(record_path: pathlib.Path, chain_id: int, treasury) -> None:
    from qvault.chain.deployments import merge_treasury, update_record
    from qvault.services.treasury_service import record_entry

    update_record(
        record_path,
        chain_id,
        lambda current: merge_treasury(current, treasury.address, record_entry(treasury))[0],
    )
    shown = record_path.relative_to(ROOT) if record_path.is_relative_to(ROOT) else record_path
    print(f"Recorded in {shown.as_posix()}.")


def _unlink(vault, linked, by, relayer, record_path) -> int:
    from qvault.services.treasury_service import unlink

    if linked is None:
        print("This vault is not linked to a treasury.")
        return 1
    balance = relayer.rpc.get_balance(linked.address)
    unlink(
        linked,
        by=by,
        now=lambda: datetime.now(UTC),
        record_path=record_path,
        chain_id=relayer.chain_id,
    )
    print(f"Unlinked {vault.name} from {linked.address}. Nothing on chain changed.")
    print(
        f"The old treasury holds {_eth(balance)}; it stays under the keys registered on it, and "
        "can still pay out on their approvals."
    )
    print("Linking the vault again deploys a new treasury.")
    return 0


def _check(args, linked, relayer, record, record_path, artifact) -> int:
    """A linked vault: check it (read-only), and with --broadcast record it if it is missing."""
    from qvault.services.treasury_service import check

    if linked is None:
        print("This vault is not linked to a treasury.")
        return 1
    print(f"Treasury : {linked.address} ({ETHERSCAN}/address/{linked.address})")
    problems = check(linked, rpc=relayer.rpc, record=record, artifact=artifact)
    if problems:
        print("The check FAILED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("The check passed: the finalized contract is exactly this vault's treasury.")
    if linked.address not in record["treasuries"]:
        if args.broadcast:
            _record(record_path, relayer.chain_id, linked)
        else:
            print(f"It is not yet in {record_path.name}; run with --broadcast to record it.")
    if not args.check:
        print("The vault is already linked; there is nothing to send.")
    return 0


def _print_plan(plan) -> None:
    print(f"Relayer  : {plan.relayer} holds {_eth(plan.balance)}")
    print(
        f"Fees     : base {_gwei(plan.base_fee)}, tip {_gwei(plan.priority_fee)}, "
        f"signed with at most {_gwei(plan.max_fee)}"
    )
    print(f"Verifier : {plan.verifier}")
    print("\nSigners, and the one key each registers:")
    for choice in plan.signers:
        storage = plan.storage.get(choice.user.id)
        where = (
            f"already on chain at {storage.pointer0}, {storage.pointer1}"
            if storage
            else "to register"
        )
        print(
            f"  {choice.user.email:<28} user {choice.user.id:<4} {choice.custody} key "
            f"#{choice.key.id} ({choice.key.alg_id}): {where}"
        )
        if choice.device is not None and choice.device.expires_at is not None:
            # After this the phone cannot sign in, so its approver cannot approve (review M5).
            print(f"  {'':<28} the phone's sign-in expires {choice.device.expires_at:%Y-%m-%d}")
    if plan.existing_treasury:
        print(f"\nAn identical treasury is already deployed at {plan.existing_treasury}.")
    print("\nSteps:")
    if not plan.steps:
        print("  none: everything is already on chain; the link only checks and records it")
    for number, step in enumerate(plan.steps, start=1):
        print(
            f"  {number}. {step.what}: ~{step.gas:,} gas (limit {step.gas_limit:,}), "
            f"~{_eth(step.expected_fee_wei)}, needs {_eth(step.upfront_wei)} available up front"
        )
    print(
        f"\nExpected cost: ~{_eth(plan.expected_cost_wei)}; the relayer would keep "
        f"~{_eth(plan.balance - plan.expected_cost_wei)}."
    )


def _print_verification(plan, treasury, artifact) -> None:
    identities = [bytes.fromhex(row.identity_hex[2:]) for row in treasury.signers]
    arguments = artifact.init_code(plan.verifier, identities, plan.threshold)[
        len(artifact.creation_code) :
    ]
    print(f"\nEtherscan: {ETHERSCAN}/address/{treasury.address}")
    print("Verify its source, from chain/, with the key in the environment:")
    print(
        f"  forge verify-contract {treasury.address} src/QVaultTreasury.sol:QVaultTreasury "
        f"--chain sepolia --constructor-args 0x{arguments.hex()} "
        "--etherscan-api-key $ETHERSCAN_API_KEY --watch"
    )


if __name__ == "__main__":
    raise SystemExit(main())
