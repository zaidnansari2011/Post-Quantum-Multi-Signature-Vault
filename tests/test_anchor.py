"""Phase 5 — SYSTEM head anchor, full ledger verification, and the tamper demonstration."""

from __future__ import annotations

import pytest

from qvault.models.anchor import LedgerAnchor
from qvault.models.key import Key
from qvault.services import ledger_service


@pytest.fixture(autouse=True)
def _reset_demo_backup():
    """The tamper-demo backup is a process-global; reset it around each test for isolation."""
    ledger_service._DEMO_BACKUP = None
    yield
    ledger_service._DEMO_BACKUP = None


def _append(n: int = 1) -> None:
    for i in range(n):
        ledger_service.append("test_event", {"i": i}, actor="SYSTEM")


# --- SYSTEM key + seed anchor -----------------------------------------------------------------


def test_system_key_seeded_and_unique(app):
    keys = Key.query.filter_by(role="sig", wrap_domain="master", owner_id=None).all()
    assert len(keys) == 1
    assert ledger_service.ensure_system_key().id == keys[0].id  # idempotent


def test_genesis_is_anchored_and_verifies(app):
    anchor = ledger_service.latest_anchor()
    assert anchor is not None and anchor.seq == 0
    assert ledger_service.verify_anchor(anchor) is True
    assert ledger_service.verify_ledger()["ok"] is True


# --- anchoring cadence ------------------------------------------------------------------------


def test_new_entries_need_reanchoring(app):
    _append(1)  # head is now seq 1, but the anchor still covers seq 0
    report = ledger_service.verify_ledger()
    assert report["chain_ok"] is True
    assert report["anchor_covers_head"] is False
    assert report["ok"] is False

    ledger_service.anchor_head()
    assert ledger_service.verify_ledger()["ok"] is True


def test_maybe_anchor_only_fires_on_new_entries(app):
    before = LedgerAnchor.query.count()
    _append(1)
    assert ledger_service.maybe_anchor() is not None  # seq advanced → new anchor
    assert ledger_service.maybe_anchor() is None  # nothing new → no anchor
    assert LedgerAnchor.query.count() == before + 1


# --- tamper: two attacks, two defences --------------------------------------------------------


def test_edit_tamper_breaks_the_chain(app):
    _append(2)
    ledger_service.anchor_head()
    assert ledger_service.verify_ledger()["ok"] is True

    ledger_service.demo_tamper(1, "edit")
    report = ledger_service.verify_ledger()
    assert report["chain_ok"] is False
    assert report["chain_break_seq"] == 1
    assert report["ok"] is False

    ledger_service.demo_restore()
    assert ledger_service.verify_ledger()["ok"] is True


def test_rewrite_tamper_is_caught_by_the_anchor(app):
    _append(2)
    ledger_service.anchor_head()  # anchor now covers the current head
    assert ledger_service.verify_ledger()["ok"] is True

    ledger_service.demo_tamper(1, "rewrite")
    report = ledger_service.verify_ledger()
    # A consistent forward-rewrite keeps the chain internally valid...
    assert report["chain_ok"] is True
    # ...but the head moved, so the (validly-signed) anchor no longer covers it.
    assert report["anchor_ok"] is True
    assert report["anchor_covers_head"] is False
    assert report["ok"] is False

    ledger_service.demo_restore()
    assert ledger_service.verify_ledger()["ok"] is True


def test_verify_anchor_rejects_a_forged_signature(app):
    anchor = ledger_service.latest_anchor()
    blob = bytearray(anchor.signature)
    blob[0] ^= 0x01
    anchor.signature = bytes(blob)
    assert ledger_service.verify_anchor(anchor) is False


def test_injected_substitute_anchor_key_is_rejected(app):
    """A DB-write adversary who brings their OWN keypair cannot forge a passing anchor: the
    substitute public key fails the master-key MAC binding."""
    from qvault.extensions import db

    _append(1)
    ledger_service.anchor_head()
    head = ledger_service._last_entry()

    # Attacker generates their own keypair, inserts it as a Key row, and re-signs the head.
    registry = app.extensions["crypto"]
    provider = registry.signature("ML-DSA-65")
    kp = provider.keygen()
    forged_key = Key(
        owner_id=None,
        role="sig",
        alg_id="ML-DSA-65",
        backend=provider.meta.backend,
        public_key=kp.public_key,
        public_key_mac=b"not-a-valid-mac",  # cannot be forged without the master key
        wrap_domain="master",
        status="active",
    )
    db.session.add(forged_key)
    db.session.flush()
    forged_sig = provider.sign(
        kp.secret_key, ledger_service._anchor_message(head.seq, head.entry_hash)
    )
    forged_anchor = LedgerAnchor(
        seq=head.seq,
        head_hash=head.entry_hash,
        alg_id="ML-DSA-65",
        backend=provider.meta.backend,
        key_id=forged_key.id,
        signature=forged_sig,
    )
    db.session.add(forged_anchor)
    db.session.commit()

    # The signature is valid for the forged key, but the key is not the authentic SYSTEM key.
    assert ledger_service.verify_anchor(forged_anchor) is False


def test_reanchor_refused_over_a_rewritten_history(app):
    """After a consistent rewrite, appending a genuine new entry must NOT mint an anchor that
    blesses the tamper — maybe_anchor refuses to extend the lineage."""
    _append(2)
    ledger_service.anchor_head()
    ledger_service.demo_tamper(1, "rewrite")  # chain stays consistent, head moved

    _append(1)  # a genuine new entry advances the head over the rewritten history
    assert ledger_service.maybe_anchor() is None  # refused
    assert ledger_service.verify_ledger()["ok"] is False

    ledger_service.demo_restore()


def test_bad_seq_tamper_does_not_mark_tampered(app):
    _append(1)
    with pytest.raises(ledger_service.LedgerError):
        ledger_service.demo_tamper(999, "edit")
    assert ledger_service.demo_is_tampered() is False
    assert ledger_service.verify_ledger()["ok"] is False  # head advanced, needs re-anchor
    ledger_service.anchor_head()
    assert ledger_service.verify_ledger()["ok"] is True


# --- routes -----------------------------------------------------------------------------------


def _register(client, email="led@e.com"):
    return client.post(
        "/register",
        data={
            "display_name": "L",
            "email": email,
            "password": "password-123",
            "confirm": "password-123",
        },
        follow_redirects=True,
    )


def test_ledger_requires_login(client):
    assert client.get("/ledger/").status_code == 302


def test_ledger_view_reports_verified(client):
    _register(client)  # creates entries; after_request anchors the head
    resp = client.get("/ledger/")
    assert resp.status_code == 200
    assert b"Ledger verified" in resp.data


def test_ledger_view_is_scoped_to_the_user(client):
    """A non-member must not see another tenant's vault events (integrity is still verified over
    the full chain; only the displayed slice is scoped)."""
    from qvault.services import auth_service, vault_service

    owner = auth_service.register_user("owner-scope@e.com", "O", "password-123")
    vault_service.create_vault(owner, "OwnerVault", "", 1)  # emits a vault_created event
    auth_service.register_user("stranger-scope@e.com", "S", "password-123")

    client.post("/login", data={"email": "stranger-scope@e.com", "password": "password-123"})
    resp = client.get("/ledger/")
    assert resp.status_code == 200
    assert b"vault_created" not in resp.data  # the owner's vault event is not disclosed


def test_http_tamper_then_restore(client):
    _register(client)
    # Tamper entry #1 (the registration event) via the dev-only demo endpoint.
    client.post("/ledger/demo/tamper", data={"target_seq": 1, "edit": "Tamper: edit payload"})
    resp = client.get("/ledger/")
    assert b"Tamper detected" in resp.data

    client.post("/ledger/demo/restore", data={"restore": "Restore ledger"})
    resp = client.get("/ledger/")
    assert b"Ledger verified" in resp.data
