"""The classical comparison baseline — RSA-2048 and ECDSA-P256 (ADR-0021).

These providers exist to be compared against and attacked, but they are registered in the real
registry, so they need the same contract tests as everything else. Three things are being pinned
here:

1. They work. A baseline that quietly failed would flatter the post-quantum algorithms.
2. They are *labelled* as quantum-vulnerable, and the application refuses to adopt one without an
   explicit, reasoned, logged downgrade — a behaviour that emerges from ADR-0012's existing guard
   reading ``security_category = 0``, with no special case anywhere for RSA.
3. The KEM contract they revealed. ``RSA-2048-OAEP`` had to implement implicit rejection to satisfy
   an interface written against ML-KEM, and that behaviour is now a requirement rather than an
   accident of how it was first written.
"""

from __future__ import annotations

import pytest

from qvault.crypto import build_registry
from qvault.crypto.providers.classical_kem import RSA2048OAEPProvider
from qvault.crypto.providers.classical_signature import ECDSAP256Provider, RSA2048PSSProvider
from qvault.models.config_models import AlgorithmConfig
from qvault.models.ledger import LedgerEntry
from qvault.services import auth_service, config_service
from qvault.services.config_service import DowngradeRefused

CLASSICAL_SIGNATURES = ("RSA-2048-PSS", "ECDSA-P256")
MESSAGE = b"approve: transfer 250,000 to the escrow account"
PASSWORD = "password-123"


# --- 1. they work -------------------------------------------------------------------------------


@pytest.mark.parametrize("alg_id", CLASSICAL_SIGNATURES)
def test_classical_signatures_round_trip(registry, alg_id):
    provider = registry.signature(alg_id)
    keypair = provider.keygen()
    signature = provider.sign(keypair.secret_key, MESSAGE)
    assert provider.verify(keypair.public_key, MESSAGE, signature) is True
    assert provider.verify(keypair.public_key, MESSAGE + b"!", signature) is False


@pytest.mark.parametrize("alg_id", CLASSICAL_SIGNATURES)
def test_classical_signatures_reject_another_key(registry, alg_id):
    provider = registry.signature(alg_id)
    mine, theirs = provider.keygen(), provider.keygen()
    signature = provider.sign(mine.secret_key, MESSAGE)
    assert provider.verify(theirs.public_key, MESSAGE, signature) is False


@pytest.mark.parametrize("alg_id", CLASSICAL_SIGNATURES)
def test_declared_sizes_are_fixed_and_real(registry, alg_id):
    """Public-key and signature widths must be constant, which the agility contract assumes.

    Run several times because this is exactly where DER-encoded ECDSA would fail: its r and s are
    minimal-length, so a DER signature varies per signature. Fixed-width r||s is what makes the
    declared size true every time rather than usually.
    """
    provider = registry.signature(alg_id)
    for _ in range(8):
        keypair = provider.keygen()
        assert len(keypair.public_key) == provider.meta.sizes["public_key"]
        assert len(provider.sign(keypair.secret_key, MESSAGE)) == provider.meta.sizes["signature"]


def test_a_signature_from_one_algorithm_is_rejected_by_the_other(registry):
    """Cross-algorithm blobs must be a clean False, never an exception or an accidental accept."""
    rsa_provider = registry.signature("RSA-2048-PSS")
    ec_provider = registry.signature("ECDSA-P256")
    rsa_key, ec_key = rsa_provider.keygen(), ec_provider.keygen()
    rsa_sig = rsa_provider.sign(rsa_key.secret_key, MESSAGE)
    ec_sig = ec_provider.sign(ec_key.secret_key, MESSAGE)

    assert ec_provider.verify(ec_key.public_key, MESSAGE, rsa_sig) is False
    assert rsa_provider.verify(rsa_key.public_key, MESSAGE, ec_sig) is False
    # And a post-quantum signature presented to a classical verifier.
    ml = registry.signature("ML-DSA-65")
    ml_key = ml.keygen()
    ml_sig = ml.sign(ml_key.secret_key, MESSAGE)
    assert ec_provider.verify(ec_key.public_key, MESSAGE, ml_sig) is False
    assert rsa_provider.verify(rsa_key.public_key, MESSAGE, ml_sig) is False


# --- 2. they are labelled, and cannot be adopted casually ----------------------------------------


@pytest.mark.parametrize(
    "provider", [RSA2048PSSProvider(), ECDSAP256Provider(), RSA2048OAEPProvider()]
)
def test_classical_providers_declare_themselves_quantum_vulnerable(provider):
    """The metadata is what every downstream refusal and warning reads. It has to be honest."""
    assert provider.meta.quantum_vulnerable is True
    assert provider.meta.security_category == 0
    assert "Shor" in (provider.meta.broken_by or "")
    assert (
        "NOT post-quantum" in provider.meta.nist_standard
        or "breakable" in provider.meta.nist_standard
    )


def test_post_quantum_providers_are_not_flagged(registry):
    """The flag must discriminate, or the warnings it drives are noise."""
    for alg_id in ("ML-DSA-65", "ML-DSA-87", "SLH-DSA-SHAKE-256f"):
        assert registry.signature(alg_id).meta.quantum_vulnerable is False
        assert registry.signature(alg_id).meta.security_category >= 3


@pytest.mark.parametrize("alg_id", CLASSICAL_SIGNATURES)
def test_adopting_a_classical_algorithm_is_refused_as_a_downgrade(app, alg_id):
    """The emergent result: ADR-0012's guard blocks RSA with no rule written about RSA.

    ``security_category = 0`` is simply the truth about a quantum-vulnerable algorithm, and the
    existing downgrade check does the rest.
    """
    admin = auth_service.register_user("admin@e.com", "A", PASSWORD)
    with pytest.raises(DowngradeRefused):
        config_service.set_active_signature_algorithm(alg_id, actor_id=admin.id)
    assert AlgorithmConfig.current().active_signature_alg != alg_id


def test_a_downgrade_to_rsa_needs_a_stated_reason_and_is_logged(app):
    """It must remain *possible* — the attack lab needs it — but never quiet."""
    admin = auth_service.register_user("admin@e.com", "A", PASSWORD)
    with pytest.raises(DowngradeRefused, match="reason"):
        config_service.set_active_signature_algorithm(
            "RSA-2048-PSS", actor_id=admin.id, allow_downgrade=True
        )

    config_service.set_active_signature_algorithm(
        "RSA-2048-PSS",
        actor_id=admin.id,
        allow_downgrade=True,
        reason="adversary-lab demonstration",
    )
    assert AlgorithmConfig.current().active_signature_alg == "RSA-2048-PSS"
    events = LedgerEntry.query.filter_by(event_type="algorithm_downgraded").all()
    assert len(events) == 1, "adopting a quantum-vulnerable algorithm must be in the audit trail"


# --- 3. the KEM contract the classical provider revealed -----------------------------------------


def test_rsa_kem_round_trips(registry):
    provider = registry.kem("RSA-2048-OAEP")
    keypair = provider.keygen()
    ciphertext, secret = provider.encapsulate(keypair.public_key)
    assert provider.decapsulate(keypair.secret_key, ciphertext) == secret
    assert len(secret) == provider.meta.sizes["shared_secret"]


def test_rsa_kem_rejects_implicitly_like_ml_kem(registry):
    """A corrupted ciphertext must yield a *different secret*, not an exception.

    The interface was written against ML-KEM, whose Fujisaki-Okamoto transform returns a
    pseudorandom secret for an invalid ciphertext. RSA-OAEP raises instead, so this provider had to
    implement implicit rejection to conform — the same defence whose absence enabled
    Bleichenbacher's
    attack. This test pins that behaviour so it cannot be "simplified" back into a raise.
    """
    provider = registry.kem("RSA-2048-OAEP")
    keypair = provider.keygen()
    ciphertext, secret = provider.encapsulate(keypair.public_key)

    corrupted = bytearray(ciphertext)
    corrupted[0] ^= 0x01
    rejected = provider.decapsulate(keypair.secret_key, bytes(corrupted))

    assert rejected != secret
    assert len(rejected) == provider.meta.sizes["shared_secret"]


def test_implicit_rejection_is_deterministic_for_the_same_ciphertext(registry):
    """FIPS 203 derives the rejection secret from (key, ciphertext); a random one would leak."""
    provider = registry.kem("RSA-2048-OAEP")
    keypair = provider.keygen()
    garbage = bytes(256)
    first = provider.decapsulate(keypair.secret_key, garbage)
    second = provider.decapsulate(keypair.secret_key, garbage)
    assert first == second


def test_two_keys_reject_the_same_ciphertext_differently(registry):
    """The rejection value must be key-bound, or it would identify invalid ciphertexts globally."""
    provider = registry.kem("RSA-2048-OAEP")
    a, b = provider.keygen(), provider.keygen()
    garbage = bytes(256)
    assert provider.decapsulate(a.secret_key, garbage) != provider.decapsulate(
        b.secret_key, garbage
    )


# --- 4. the registry can still be built without them ---------------------------------------------


def test_the_registry_can_exclude_the_classical_baseline():
    """Tests that assert post-quantum-only invariants need a registry that really is."""
    registry = build_registry(classical=False)
    assert registry.list_signature_algs() == ["ML-DSA-65", "ML-DSA-87", "SLH-DSA-SHAKE-256f"]
    assert registry.list_kem_algs() == ["ML-KEM-768"]
    assert all(not m.quantum_vulnerable for m in registry.signature_metas())


def test_the_default_registry_includes_both_paradigms():
    """The agility claim's evidence: one registry, two eras, one interface."""
    registry = build_registry()
    families = {m.family for m in registry.signature_metas()}
    assert {"ML-DSA", "SLH-DSA", "RSA", "ECDSA"} <= families
    assert {m.family for m in registry.kem_metas()} == {"ML-KEM", "RSA"}
