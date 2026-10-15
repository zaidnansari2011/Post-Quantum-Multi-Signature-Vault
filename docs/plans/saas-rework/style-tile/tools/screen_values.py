"""Recompute every value screens.md marks as computed, using Q-Vault's own code.

The style tile's open payment decision is fictional, but its hashes are not made up: the decision
text, the signed payload, the payload hash, the decision code and the treasury digest come from the
same functions the product uses (qvault/services/signing.py, qvault/chain/action.py). The ML-DSA
signature sizes and fingerprints come from keys generated here, so they change on every run; the
hashes of the payload do not.

Run from anywhere, with the project's interpreter:

    q-vault/.venv/Scripts/python.exe docs/plans/saas-rework/style-tile/tools/screen_values.py

Read-only: it imports the package and prints JSON. It writes nothing.
"""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO))

from qvault.chain import action as chain_action  # noqa: E402
from qvault.chain.digest import proposal_id  # noqa: E402
from qvault.chain.evm import checksum_address  # noqa: E402
from qvault.crypto import build_registry, sha256_hex  # noqa: E402
from qvault.services.signing import proposal_signing_bytes, vote_signing_bytes  # noqa: E402
from qvault.transparency.merkle import inclusion_proof, merkle_root  # noqa: E402
from qvault.transparency.statement import entry_leaf_hash  # noqa: E402


def seed(text: str) -> bytes:
    """Deterministic stand-in randomness, so the tile's values are reproducible."""
    return hashlib.sha256(text.encode()).digest()


def address(text: str) -> str:
    return checksum_address("0x" + seed(text)[:20].hex())


# The Operations vault's treasury: the address chain/deployments/sepolia.json records as linked.
TREASURY = "0xD49174b703d6FBC5088b0f01C6E71B5Ef467f3D0"

out: dict = {}
recipient = address("calderwood release deployer wallet")
raised = datetime(2026, 10, 4, 8, 41, 17, 304551, tzinfo=UTC)  # Sun 4 Oct, 09:41:17 BST
due = datetime(2026, 10, 6, 16, 0, tzinfo=UTC)  # Tue 6 Oct, 17:00 BST

payment = chain_action.build_eth_transfer(
    chain_id=11_155_111,
    treasury=TREASURY,
    to=recipient,
    value_wei=chain_action.parse_eth_value("0.25"),
    deadline=due,
    config_nonce=0,
)
text = payment.describe()
decision_id = str(uuid.UUID(bytes=seed("calderwood decision 1")[:16], version=4))
nonce = seed("calderwood nonce 1")[:16].hex()
payload = proposal_signing_bytes(
    vault_id=1,
    proposal_uuid=decision_id,
    action_text=text,
    file_sha256=None,
    required_m=2,
    required_n=4,
    authorized_signers=[1, 2, 3, 4],  # Zaid, Hassan, Gracian, Atharv
    nonce_hex=nonce,
    created_at_iso=raised.isoformat(),
    action=payment.canonical(),
)
payload_hash = sha256_hex(payload)
code = payload_hash[:8].upper()
treasury_digest = payment.execution_digest(payload_hash)

out.update(
    recipient=recipient,
    decision_text=text,
    signed_payload=payload.decode(),
    signed_payload_bytes=len(payload),
    payload_hash=payload_hash,
    decision_code=f"{code[:4]}-{code[4:]}",
    decision_id=decision_id,
    nonce=nonce,
    raised_at=raised.isoformat(),
    action=payment.canonical(),
    approvals_valid_until=payment.valid_until_utc().isoformat(),
    treasury_digest="0x" + treasury_digest.hex(),
    onchain_proposal_id="0x" + proposal_id(payload_hash).hex(),
)

# Real ML-DSA keys and signatures: sizes are exact; fingerprints differ on every run.
registry = build_registry(classical=False)
mldsa65 = registry.signature("ML-DSA-65")
mldsa87 = registry.signature("ML-DSA-87")
hassan = mldsa65.keygen()
vote = vote_signing_bytes(proposal_payload_hash=payload_hash, decision="approve", signer_id=2)
vote_sig = mldsa65.sign(hassan.secret_key, vote)
treasury_sig = mldsa65.sign(hassan.secret_key, treasury_digest)
assert mldsa65.verify(hassan.public_key, vote, vote_sig)
out.update(
    hassan_key_fingerprint=sha256_hex(hassan.public_key)[:16],
    public_key_bytes=len(hassan.public_key),
    signature_bytes=len(vote_sig),
    vote_signature_sha256=sha256_hex(vote_sig),
    treasury_signature_sha256=sha256_hex(treasury_sig),
    zaid_key_fingerprint=sha256_hex(mldsa65.keygen().public_key)[:16],
    log_key_fingerprint=sha256_hex(mldsa65.keygen().public_key)[:16],
    witness_key_fingerprint=sha256_hex(mldsa87.keygen().public_key)[:16],
    witness_signature_bytes=mldsa87.meta.sizes["signature"],
)

# An illustrative log of 1,286 entries (seq 0 to 1,285): the decision was raised at #1,284 and
# Hassan's approval is #1,285, the newest entry. Entry hashes are stand-ins; the leaf hashes, the
# root and the proofs are computed for real over them.
entries = [seed(f"calderwood ledger entry {i}").hex() for i in range(1286)]
leaves = [entry_leaf_hash(e) for e in entries]
out.update(
    entry_1284_hash=entries[1284],
    entry_1285_hash=entries[1285],
    leaf_1285=leaves[1285].hex(),
    checkpoint_size=len(leaves),
    checkpoint_root=merkle_root(leaves).hex(),
    inclusion_proof_hashes_1284=len(inclusion_proof(leaves, 1284)),
    inclusion_proof_hashes_1285=len(inclusion_proof(leaves, 1285)),
)

# Other addresses on the Home page.
out.update(
    qa_wallet=address("calderwood qa wallet 1"),
    staging_gas_wallet=address("calderwood qa wallet 2"),
    load_test_wallet=address("calderwood qa wallet 3"),
    load_test_payout_tx="0x" + seed("calderwood payout tx 41").hex(),
)

print(json.dumps(out, indent=2))
