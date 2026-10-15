"""A10: the pairing formats, pinned (pairing-design §3.8).

``tests/vectors/device_pairing.json`` is read here and by the phone's own code under Node
(``mobile/tools/pairing_probe.ts``, ``tests/test_mobile_pairing.py``), so the two can never drift
apart. The first case is also rebuilt here by hand, from the design's words rather than the
functions under test, so the vectors cannot simply agree with a mistake.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from qvault.services.device_service import token_digest
from qvault.services.signing import DS_DEVICE_PAIR, device_pairing_bytes, pairing_check_code

VECTORS = json.loads(
    (Path(__file__).parent / "vectors" / "device_pairing.json").read_text(encoding="utf-8")
)["cases"]


def test_every_vector_matches_the_server():
    for case in VECTORS:
        digest = token_digest(case["pending_token"]).hex()
        assert digest == case["pending_token_digest"]
        message = device_pairing_bytes(
            user_id=case["user_id"],
            pairing_uuid=case["pairing_uuid"],
            alg_id=case["alg_id"],
            public_key_b64=case["public_key_b64"],
            pending_token_digest=digest,
        )
        assert message.hex() == case["pairing_bytes_hex"]
        assert (
            pairing_check_code(
                pairing_uuid=case["pairing_uuid"],
                public_key_sha256=case["public_key_sha256"],
                pending_token_digest=digest,
            )
            == case["check_code"]
        )


def test_the_first_vector_rebuilt_from_the_design_by_hand():
    case = VECTORS[0]
    digest = hashlib.sha256(b"qvault:device-token:v1|" + case["pending_token"].encode()).hexdigest()
    body = (
        f'{{"alg_id":"{case["alg_id"]}","pairing_uuid":"{case["pairing_uuid"]}",'
        f'"pending_token_digest":"{digest}","public_key":"{case["public_key_b64"]}",'
        f'"user_id":{case["user_id"]}}}'
    )
    assert (b"QVAULT-SIG-v1:DEVICE-PAIR|" + body.encode()).hex() == case["pairing_bytes_hex"]
    pre = f"qvault:pair-check:v1|{case['pairing_uuid']}|{case['public_key_sha256']}|{digest}"
    code = int.from_bytes(hashlib.sha256(pre.encode()).digest()[:8], "big") % 1_000_000
    assert f"{code:06d}" == case["check_code"]


def test_the_pairing_tag_is_disjoint_from_every_other_signed_format():
    from qvault.services.signing import DS_DEVICE_ENROL, DS_PROPOSAL, DS_VOTE

    assert DS_DEVICE_PAIR == b"QVAULT-SIG-v1:DEVICE-PAIR"
    assert len({DS_DEVICE_PAIR, DS_DEVICE_ENROL, DS_PROPOSAL, DS_VOTE}) == 4


def test_the_check_code_changes_with_every_input():
    base = {"pairing_uuid": "u", "public_key_sha256": "a" * 64, "pending_token_digest": "b" * 64}
    code = pairing_check_code(**base)
    assert len(code) == 6 and code.isdigit()
    for field in base:
        other = dict(base, **{field: base[field][:-1] + "c"})
        assert pairing_check_code(**other) != code
