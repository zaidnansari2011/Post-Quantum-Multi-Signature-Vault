"""Phase-1 spike, promoted to a permanent regression test.

Proves that every registered signature provider signs and verifies (and rejects
tampering), and that the KEM encapsulate/decapsulate round-trip agrees on the shared
secret. Parametrised over whatever the active backend registered, so it keeps passing if
the backend changes — the crypto-agile design in action.
"""

from __future__ import annotations

import pytest

from qvault.crypto import build_registry

MESSAGE = b"Release Q3 escrow funds :: proposal 3f9c-...-a12"


def _sig_algs():
    return build_registry().list_signature_algs()


def _kem_algs():
    return build_registry().list_kem_algs()


@pytest.mark.parametrize("alg_id", _sig_algs())
def test_signature_roundtrip(registry, alg_id):
    provider = registry.signature(alg_id)
    kp = provider.keygen()

    assert kp.alg_id == alg_id
    assert len(kp.public_key) == provider.meta.sizes["public_key"]

    signature = provider.sign(kp.secret_key, MESSAGE)
    assert provider.verify(kp.public_key, MESSAGE, signature) is True


@pytest.mark.parametrize("alg_id", _sig_algs())
def test_signature_rejects_tampered_message(registry, alg_id):
    provider = registry.signature(alg_id)
    kp = provider.keygen()
    signature = provider.sign(kp.secret_key, MESSAGE)

    assert provider.verify(kp.public_key, MESSAGE + b"!", signature) is False


@pytest.mark.parametrize("alg_id", _sig_algs())
def test_signature_rejects_tampered_signature(registry, alg_id):
    provider = registry.signature(alg_id)
    kp = provider.keygen()
    signature = bytearray(provider.sign(kp.secret_key, MESSAGE))
    signature[0] ^= 0x01  # flip one bit

    assert provider.verify(kp.public_key, MESSAGE, bytes(signature)) is False


@pytest.mark.parametrize("alg_id", _kem_algs())
def test_kem_roundtrip(registry, alg_id):
    provider = registry.kem(alg_id)
    kp = provider.keygen()

    ciphertext, secret_enc = provider.encapsulate(kp.public_key)
    secret_dec = provider.decapsulate(kp.secret_key, ciphertext)

    assert secret_enc == secret_dec
    assert len(secret_enc) == provider.meta.sizes["shared_secret"]


@pytest.mark.parametrize("alg_id", _kem_algs())
def test_kem_wrong_ciphertext_diverges(registry, alg_id):
    """A mutated ciphertext must not recover the same shared secret (ML-KEM is IND-CCA2)."""
    provider = registry.kem(alg_id)
    kp = provider.keygen()
    ciphertext, secret_enc = provider.encapsulate(kp.public_key)

    bad = bytearray(ciphertext)
    bad[0] ^= 0x01
    secret_bad = provider.decapsulate(kp.secret_key, bytes(bad))

    assert secret_bad != secret_enc
