"""Run the witness: ``python -m witness --port 5001``.

Deliberately a separate command from ``flask --app wsgi run``. Two processes, two keys, two
databases — if it were a thread inside Q-Vault, the operator who can rewrite the ledger could
rewrite the witness's memory of it in the same transaction, and the co-signature would attest to
nothing.
"""

from __future__ import annotations

import argparse

from .app import create_witness_app
from .identity import DEFAULT_WITNESS_ALG


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m witness",
        description="An independent witness for a Q-Vault transparency log.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--name", default="witness-1", help="identity inside the signed bytes")
    parser.add_argument("--state", default="instance/witness.db", help="its SQLite file")
    parser.add_argument("--key", default="instance/witness_key.json", help="its keypair file")
    parser.add_argument(
        "--alg",
        default=None,
        help=(
            f"signature algorithm for a NEW key (default {DEFAULT_WITNESS_ALG}, chosen to differ "
            "from the log's lattice-based ML-DSA so one broken assumption cannot invalidate both)"
        ),
    )
    parser.add_argument("--backend", default="quantcrypt")
    args = parser.parse_args()

    app = create_witness_app(
        state_path=args.state,
        key_path=args.key,
        name=args.name,
        alg_id=args.alg,
        backend=args.backend,
    )
    identity = app.config["WITNESS_IDENTITY"]
    print(f"witness {identity.name!r} — {identity.alg_id}, fingerprint {identity.fingerprint()}")
    print(f"  state {args.state}   key {args.key}")
    print(f"  publish this fingerprint; verifiers pin it with --expect-witness {identity.fingerprint()}")
    app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
