"""ADR-0010 — the verify-after-sign invariant, exercised by injecting faults.

A signature that fails verification under its own public key should be impossible. That is exactly
why it needs a test: an invariant nobody can trigger is an invariant nobody has checked.

These tests install a provider that corrupts every signature it produces, then assert that each
signing path *refuses to emit or persist the result*. This models an induced fault (the basis of
published fault attacks against FIPS 204, where a faulted lattice signature can leak secret-key
information) and equally the mundane causes: a corrupted key blob, a provider/algorithm mismatch,
or a backend whose byte format changed underneath us.

The harness swaps the provider inside ``app.extensions["crypto"]``, which is the same seam the
application resolves through — so nothing under test is aware it is being faulted.
"""

from __future__ import annotations

import pytest

from qvault.extensions import db
from qvault.models.ledger import LedgerEntry
from qvault.models.signature import Signature
from qvault.services import (
    approval_service,
    auth_service,
    key_service,
    ledger_service,
    proposal_service,
    vault_service,
)
from qvault.services.key_service import SignFaultError

PASSWORD = "password-123"


class FaultInjectingProvider:
    """Wraps a real signature provider and flips one bit of every signature it produces.

    Everything else delegates untouched — in particular ``verify`` is the genuine implementation,
    so a corrupted signature fails for the real reason rather than because the double is lying.
    """

    def __init__(self, inner):
        self._inner = inner
        self.meta = inner.meta
        self.signs = 0

    def keygen(self):
        return self._inner.keygen()

    def sign(self, secret_key: bytes, message: bytes) -> bytes:
        self.signs += 1
        corrupted = bytearray(self._inner.sign(secret_key, message))
        corrupted[0] ^= 0x01
        return bytes(corrupted)

    def verify(self, public_key: bytes, message: bytes, signature: bytes) -> bool:
        return self._inner.verify(public_key, message, signature)


@pytest.fixture()
def inject_faults(app):
    """Install the faulting wrapper for every registered signature algorithm, for one test."""
    registry = app.extensions["crypto"]
    originals = {a: registry.signature(a) for a in registry.list_signature_algs()}
    doubles = {a: FaultInjectingProvider(p) for a, p in originals.items()}
    for double in doubles.values():
        registry.register_signature(double)
    yield doubles
    for original in originals.values():
        registry.register_signature(original)


def _signer_with_key(prefix):
    user = auth_service.register_user(f"{prefix}@e.com", "S", PASSWORD)
    return user, key_service.active_signing_key(user)


# --- the harness itself must not be a no-op ---------------------------------------------------


def test_the_fault_harness_actually_corrupts_signatures(app, inject_faults):
    """Guard against a vacuous suite: prove the double really does break signatures."""
    user, key = _signer_with_key("harness")
    faulting = app.extensions["crypto"].signature(key.alg_id)
    genuine = faulting._inner
    secret = key_service.unlock_secret_key(user, key, PASSWORD)

    honest = genuine.sign(secret, b"message")
    assert genuine.verify(key.public_key, b"message", honest) is True

    faulted = faulting.sign(secret, b"message")
    assert faulted != honest
    assert genuine.verify(key.public_key, b"message", faulted) is False
    assert faulting.signs == 1


def test_signing_works_normally_without_injection(app):
    user, key = _signer_with_key("normal")
    sig = key_service.sign_with_key(user, key, PASSWORD, b"message")
    provider = app.extensions["crypto"].signature(key.alg_id)
    assert provider.verify(key.public_key, b"message", sig) is True


# --- user signing key -------------------------------------------------------------------------


def test_sign_with_key_refuses_to_return_a_faulted_signature(app, inject_faults):
    user, key = _signer_with_key("faulted")
    with pytest.raises(SignFaultError, match="failed immediate verification"):
        key_service.sign_with_key(user, key, PASSWORD, b"message")


def test_a_faulted_vote_records_nothing_at_all(app, inject_faults):
    """The whole point: no signature row, and no ledger event claiming one exists."""
    owner = auth_service.register_user("vote-fault@e.com", "O", PASSWORD)
    vault = vault_service.create_vault(owner, "V", "", 1)
    proposal = proposal_service.create_proposal(vault, owner, "T", "do the thing")
    signed_before = LedgerEntry.query.filter_by(event_type="proposal_signed").count()

    with pytest.raises(SignFaultError):
        approval_service.cast_vote(proposal, owner, PASSWORD, "approve")
    db.session.rollback()

    assert Signature.query.filter_by(proposal_id=proposal.id).count() == 0
    assert LedgerEntry.query.filter_by(event_type="proposal_signed").count() == signed_before
    assert proposal.status == "open", "a faulted vote must not decide the proposal"


def test_a_faulted_vote_over_http_does_not_report_success(app, client, inject_faults):
    """A 500 is the correct outcome here — far better than a page that says the vote was cast."""
    client.post(
        "/register",
        data={
            "display_name": "V",
            "email": "http-fault@e.com",
            "password": PASSWORD,
            "confirm": PASSWORD,
        },
        follow_redirects=True,
    )
    client.post(
        "/vaults/new",
        data={"name": "V", "threshold_m": 1, "description": ""},
        follow_redirects=True,
    )
    import re

    resp = client.post(
        "/vaults/1/proposals/new",
        data={"title": "T", "action_text": "do the thing", "submit": "Create proposal"},
        follow_redirects=True,
    )
    pid = re.search(r"/vaults/1/proposals/([0-9a-f-]{36})", resp.get_data(as_text=True)).group(1)

    app.config["PROPAGATE_EXCEPTIONS"] = False
    voted = client.post(
        f"/vaults/1/proposals/{pid}/vote",
        data={"password": PASSWORD, "approve": "Approve & sign"},
    )
    assert voted.status_code == 500
    assert Signature.query.count() == 0


# --- SYSTEM anchor key ------------------------------------------------------------------------


def test_anchor_head_refuses_to_persist_a_faulted_anchor(app, inject_faults):
    from qvault.models.anchor import LedgerAnchor

    ledger_service.ensure_genesis()
    before = LedgerAnchor.query.count()

    with pytest.raises(ledger_service.LedgerError, match="failed immediate verification"):
        ledger_service.anchor_head()
    db.session.rollback()

    assert LedgerAnchor.query.count() == before, "a faulted anchor must never reach the database"


def test_a_faulted_anchor_does_not_break_the_response(app, client, inject_faults):
    """Anchoring runs in an after_request hook. A fault there must not take the page down.

    The honest outcome is an un-anchored head — verify_ledger() will report that the anchor no
    longer covers the head, which is exactly the visible, investigable state we want.
    """
    resp = client.get("/")
    assert resp.status_code == 200


def test_a_faulted_anchor_leaves_the_chain_reporting_honestly(app, inject_faults):
    """No silent success: verification must not claim the ledger is fully anchored."""
    ledger_service.ensure_genesis()
    ledger_service.append("test_event", {"i": 1}, actor="SYSTEM")
    try:
        ledger_service.anchor_head()
    except ledger_service.LedgerError:
        db.session.rollback()

    report = ledger_service.verify_ledger()
    assert report["chain_ok"] is True, "the hash chain itself is untouched by a signing fault"
    assert report["ok"] is False, "but the ledger must not be reported as fully verified"
