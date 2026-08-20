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
DS_VOTE = b"QVAULT-SIG-v1:VOTE"
DS_DEVICE_ENROL = b"QVAULT-SIG-v1:DEVICE-ENROL"


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


def vote_signing_bytes(*, proposal_payload_hash: str, decision: str, signer_id: int) -> bytes:
    """Return the exact bytes a signer signs when casting a vote.

    A vote is not merely a signature over the proposal action — it also commits to the *decision*
    and the *voter*. Binding all three under a distinct ``DS_VOTE`` domain tag means an approval
    signature can never be replayed as a rejection (or attributed to a different signer), and it
    cannot be confused with the ``DS_PROPOSAL`` bytes. ``proposal_payload_hash`` is the proposal's
    canonical ``payload_hash``, which already binds the vault, action, file, policy, signer set,
    nonce, and timestamp — so the whole proposal is transitively covered.
    """
    if decision not in ("approve", "reject"):
        raise ValueError(f"invalid decision: {decision!r}")
    body = canonical_json(
        {
            "proposal_payload_hash": proposal_payload_hash,
            "decision": decision,
            "signer_id": signer_id,
        }
    )
    return DS_VOTE + b"|" + body


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


def device_enrolment_bytes(
    *, user_id: int, alg_id: str, public_key_b64: str, challenge: str
) -> bytes:
    """The exact bytes a device signs to prove it holds the private half it is enrolling.

    Enrolment is the moment a new signing identity is admitted to the vault, so the server must
    not take a public key on trust: without a proof of possession, anyone able to POST could
    register a key **they do not hold** against a user, and every later signature by the real
    holder of that key would be attributed to that user — deniable delegation of approval
    authority, which is the exact property a multi-signature vault exists to prevent. Requiring a
    signature here is the enrolment analogue of ADR-0010's verify-after-sign: never record a key
    we have not just watched produce a valid signature under it.

    It also catches the mundane failures loudly and early — a truncated base64 body, or a byte
    format that drifted between the device's implementation and ours — at enrolment rather than at
    the first vote, where the same symptom is indistinguishable from a compromised device.

    Binds four things under a domain tag of its own:

    - ``user_id`` — so an enrolment proof cannot be replayed against a different account;
    - ``alg_id`` and ``public_key_b64`` — so the proof covers the exact key being registered, not
      merely *some* key the device holds;
    - ``challenge`` — the server-issued, master-key-MAC'd, time-bounded nonce, so a proof captured
      once cannot be replayed later.

    ``DS_DEVICE_ENROL`` keeps these bytes disjoint from ``DS_PROPOSAL`` and ``DS_VOTE``: an
    enrolment proof can never be reinterpreted as a vote, nor a vote as an enrolment.
    """
    body = canonical_json(
        {
            "user_id": user_id,
            "alg_id": alg_id,
            "public_key": public_key_b64,
            "challenge": challenge,
        }
    )
    return DS_DEVICE_ENROL + b"|" + body
