"""The canonical proposal signing payload (specification §4.4).

There is exactly ONE definition of the bytes a signer signs, used verbatim at proposal
creation (to snapshot ``payload_hash``) and at verification time (Phase 4). Signing the full
canonical bytes — with a domain-separation tag — binds the vault, the proposal id, the action,
the file hash, the policy, the authorized-signer set, a per-proposal nonce, and the timestamp,
so none of them can be altered after signatures exist.
"""

from __future__ import annotations

import json

from qvault.crypto import canonical_json

DS_PROPOSAL = b"QVAULT-SIG-v1:PROPOSAL"


def proposal_signing_bytes(
    *,
    vault_id: int,
    proposal_uuid: str,
    action_text: str,
    file_sha256: str | None,
    required_m: int,
    required_n: int,
    authorized_signers: list[int],
    nonce_hex: str,
    created_at_iso: str,
) -> bytes:
    """Return the exact canonical bytes to be signed for this proposal."""
    body = canonical_json(
        {
            "vault_id": vault_id,
            "proposal_id": proposal_uuid,
            "action_text": action_text,
            "file_sha256": file_sha256,  # hex string, or null when there is no file
            "policy": {"M": required_m, "N": required_n, "signers": sorted(authorized_signers)},
            "nonce": nonce_hex,
            "created_at": created_at_iso,
        }
    )
    return DS_PROPOSAL + b"|" + body


def signing_bytes_for(proposal) -> bytes:
    """Recompute the canonical signing bytes from a stored Proposal (+ its optional file)."""
    file_sha = proposal.file.content_sha256 if proposal.file is not None else None
    return proposal_signing_bytes(
        vault_id=proposal.vault_id,
        proposal_uuid=proposal.proposal_uuid,
        action_text=proposal.action_text,
        file_sha256=file_sha,
        required_m=proposal.required_m,
        required_n=proposal.required_n,
        authorized_signers=json.loads(proposal.authorized_signers_snapshot),
        nonce_hex=proposal.nonce.hex(),
        created_at_iso=proposal.created_at_iso,
    )
