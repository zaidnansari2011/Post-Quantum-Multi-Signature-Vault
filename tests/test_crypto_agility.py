"""Tests for the crypto-agile invariants — the academic centrepiece.

These encode the properties the viva will probe: providers are isolated, dispatch is by
stored ``alg_id``, unknown algorithms fail loudly, and — critically — a signature made
under one algorithm still verifies after the *default* is switched to another (mixed-artefact
correctness).
"""

from __future__ import annotations

import pytest

from qvault.crypto import UnknownAlgorithm

MESSAGE = b"approve contract v2"


def test_registry_dispatch_returns_matching_provider(registry):
    for alg_id in registry.list_signature_algs():
        assert registry.signature(alg_id).meta.alg_id == alg_id


def test_unknown_algorithm_raises(registry):
    with pytest.raises(UnknownAlgorithm):
        registry.signature("RSA-2048")  # deliberately not registered — must not resolve


def test_cross_algorithm_signature_does_not_verify(registry):
    """A signature from one algorithm must not verify under a different algorithm."""
    algs = registry.list_signature_algs()
    if len(algs) < 2:
        pytest.skip("need at least two signature algorithms")

    a, b = algs[0], algs[1]
    prov_a, prov_b = registry.signature(a), registry.signature(b)
    kp_a = prov_a.keygen()
    sig_a = prov_a.sign(kp_a.secret_key, MESSAGE)

    # Verified under the correct provider: True. Under the other provider: False.
    assert prov_a.verify(kp_a.public_key, MESSAGE, sig_a) is True
    assert prov_b.verify(kp_a.public_key, MESSAGE, sig_a) is False


def test_signature_from_other_key_does_not_verify(registry):
    """Same algorithm, different keypair — must not verify."""
    prov = registry.signature(registry.list_signature_algs()[0])
    kp1, kp2 = prov.keygen(), prov.keygen()
    sig = prov.sign(kp1.secret_key, MESSAGE)

    assert prov.verify(kp1.public_key, MESSAGE, sig) is True
    assert prov.verify(kp2.public_key, MESSAGE, sig) is False


def test_signature_survives_default_algorithm_switch(registry):
    """Mixed-artefact correctness: switching the default must not break old signatures.

    We model an artefact as ``(alg_id, public_key, signature)``. Verification always
    re-resolves the provider from the artefact's stored ``alg_id`` — never from any global
    default — so a signature made under the first algorithm keeps verifying after the
    'default' is switched to the second.
    """
    algs = registry.list_signature_algs()
    if len(algs) < 2:
        pytest.skip("need at least two signature algorithms")

    old_default, new_default = algs[0], algs[1]

    # 1) Create an artefact under the OLD default.
    prov_old = registry.signature(old_default)
    kp = prov_old.keygen()
    artefact = {
        "alg_id": old_default,
        "public_key": kp.public_key,
        "signature": prov_old.sign(kp.secret_key, MESSAGE),
    }

    # 2) "Switch the default" — in the real app this mutates one config row. New keys would
    #    now be generated under new_default; nothing about the stored artefact changes.
    assert new_default != old_default

    # 3) Verify the OLD artefact by its OWN stored alg_id. Still valid.
    prov = registry.signature(artefact["alg_id"])
    assert prov.verify(artefact["public_key"], MESSAGE, artefact["signature"]) is True


def test_all_providers_declare_consistent_metadata(registry):
    """Every provider's declared sizes match reality (guards copy-paste errors in AlgMeta)."""
    for alg_id in registry.list_signature_algs():
        prov = registry.signature(alg_id)
        kp = prov.keygen()
        assert len(kp.public_key) == prov.meta.sizes["public_key"], alg_id
        assert len(prov.sign(kp.secret_key, MESSAGE)) == prov.meta.sizes["signature"], alg_id
