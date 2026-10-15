"""On-chain execution: the pieces of Q-Vault that talk to an Ethereum treasury contract.

See ``docs/plans/onchain-execution.md`` for the design, and ``chain/`` for the contracts.

Everything in this package that computes bytes a contract will check — digests, key blobs,
signer identities — is a pure function with no Flask, database or network dependency. That is
what lets a fixture generated here be checked from both sides: by pytest against these functions
and by Foundry against the Solidity that has to agree with them.

Like the rest of the codebase, this package never imports a PQC backend directly
(``tests/test_module_boundaries.py``). ML-DSA signing and verification go through the
``CryptoRegistry``; the only lattice arithmetic here is the public-key expansion the verifier
contract needs, which uses nothing but SHAKE and modular arithmetic.
"""
