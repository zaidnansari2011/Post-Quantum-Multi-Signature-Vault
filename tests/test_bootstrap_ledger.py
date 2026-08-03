"""Phase 2 — bootstrap seeding and the hash-chained ledger (genesis, append, tamper)."""

from __future__ import annotations

from qvault.extensions import db
from qvault.models.config_models import AlgorithmConfig
from qvault.models.ledger import LedgerEntry
from qvault.services import auth_service, ledger_service
from qvault.services.bootstrap_service import seed


def test_config_and_genesis_seeded(app):
    cfg = AlgorithmConfig.current()
    assert cfg is not None
    assert cfg.active_signature_alg == "ML-DSA-65"
    assert cfg.active_kem_alg == "ML-KEM-768"
    assert cfg.backend == "quantcrypt"

    genesis = LedgerEntry.query.filter_by(seq=0).first()
    assert genesis is not None
    assert genesis.event_type == "genesis"
    assert genesis.prev_hash == ledger_service.GENESIS_PREV_HEX


def test_seed_is_idempotent(app):
    seed()
    seed()
    assert AlgorithmConfig.query.count() == 1
    assert LedgerEntry.query.filter_by(seq=0).count() == 1


def test_clean_chain_verifies(app):
    auth_service.register_user("t1@e.com", "T1", "passphrase-123")
    auth_service.register_user("t2@e.com", "T2", "passphrase-456")

    ok, first_bad = ledger_service.verify_chain()
    assert ok is True and first_bad is None


def test_tampering_a_past_entry_is_detected(app):
    auth_service.register_user("t@e.com", "T", "passphrase-123")

    ok, _ = ledger_service.verify_chain()
    assert ok is True

    # Simulate a DB-level tamper: edit a past entry's payload directly (bypassing append()).
    event = LedgerEntry.query.filter_by(event_type="user_registered").first()
    event.payload_json = event.payload_json.replace("t@e.com", "attacker@e.com")
    db.session.commit()

    ok2, first_bad = ledger_service.verify_chain()
    assert ok2 is False
    assert first_bad == event.seq


def test_tampering_routing_metadata_is_detected(app):
    # actor_id / vault_id / ref_type / ref_id are folded into the entry hash, so altering
    # any of them (not just the payload) breaks the chain.
    auth_service.register_user("m@e.com", "M", "passphrase-123")
    assert ledger_service.verify_chain()[0] is True

    event = LedgerEntry.query.filter_by(event_type="user_registered").first()
    event.ref_id = "999"  # was str(user.id)
    db.session.commit()

    ok, first_bad = ledger_service.verify_chain()
    assert ok is False
    assert first_bad == event.seq


def test_sequence_numbers_are_contiguous(app):
    auth_service.register_user("s1@e.com", "S1", "passphrase-1")
    auth_service.register_user("s2@e.com", "S2", "passphrase-2")

    seqs = [e.seq for e in LedgerEntry.query.order_by(LedgerEntry.seq.asc()).all()]
    assert seqs == list(range(len(seqs)))  # 0,1,2,... no gaps
