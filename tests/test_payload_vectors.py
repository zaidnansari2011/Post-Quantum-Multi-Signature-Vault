"""Frozen payload hashes: the bytes every existing signature was made over must never change.

Every other test of the canonical payload is a round trip (create, recompute, compare) or a
comparison between implementations, so a change to ``proposal_signing_bytes`` that altered every
hash consistently would pass all of them while invalidating every signature already stored. These
vectors were computed from the code as it stood on 2026-09-17, before on-chain execution added an
optional ``action`` to the payload (plan Phase 4), and they must still hold after it: a proposal
without an action hashes exactly as it always did.

The file is UTF-8 (the formatter writes non-ASCII literally); the unicode vector's expected hash
is what fails if it is ever decoded any other way.
"""

from __future__ import annotations

import pytest

from qvault.crypto import sha256_hex
from qvault.services.signing import proposal_signing_bytes, vote_signing_bytes

PROPOSALS = {
    "plain": (
        {
            "vault_id": 1,
            "proposal_uuid": "3f2b8c1e-5a4d-4e6f-9b7a-0c1d2e3f4a5b",
            "action_text": "Release the Q3 budget to operations.",
            "file_sha256": None,
            "required_m": 2,
            "required_n": 3,
            "authorized_signers": [3, 1, 2],
            "nonce_hex": "00112233445566778899aabbccddeeff",
            "created_at_iso": "2026-09-17T12:00:00+00:00",
        },
        "3f71b810243a353fc4f761b8149e4bfdc1159d3a830b197901bbc944f6b0c4c5",
    ),
    "with_file": (
        {
            "vault_id": 42,
            "proposal_uuid": "a0b1c2d3-e4f5-4a6b-8c7d-9e0f1a2b3c4d",
            "action_text": "Approve contract v2 (attached).",
            "file_sha256": "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9",
            "required_m": 1,
            "required_n": 1,
            "authorized_signers": [7],
            "nonce_hex": "ffeeddccbbaa99887766554433221100",
            "created_at_iso": "2026-01-31T23:59:59.999999+00:00",
        },
        "d86f208fbb0b16f24d5970167b40a6e25b94b7b7761dc1654287d40c200e531c",
    ),
    "unicode_and_escapes": (
        {
            "vault_id": 7,
            "proposal_uuid": "11111111-2222-4333-8444-555555555555",
            "action_text": 'Pay €1,250 to Zoë — "urgent"\nline two\ttab ✓',
            "file_sha256": None,
            "required_m": 3,
            "required_n": 5,
            "authorized_signers": [10, 2, 33, 4, 5],
            "nonce_hex": "0123456789abcdef0123456789abcdef",
            "created_at_iso": "2026-09-17T08:30:15.123456+00:00",
        },
        "36a8d4ab9fa8fc10501ded17e7b8cc78179b80fd657aba04e8303120bc3fd01a",
    ),
}


@pytest.mark.parametrize("name", sorted(PROPOSALS))
def test_a_proposal_payload_hashes_as_it_always_has(name):
    inputs, expected = PROPOSALS[name]
    assert sha256_hex(proposal_signing_bytes(**inputs)) == expected


def test_a_vote_payload_hashes_as_it_always_has():
    payload = vote_signing_bytes(proposal_payload_hash="ab" * 32, decision="approve", signer_id=3)
    assert sha256_hex(payload) == "2a2c1395ce1ea4b23368468e14372ac700208115a275f6695b5a2af917d9aff6"
