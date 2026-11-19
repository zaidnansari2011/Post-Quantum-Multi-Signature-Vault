"""A sign-in email change is logged, and verifiers follow it (found on live 2026-11-20).

The team's emails were changed straight in the database at the 14 Oct switch, with no log entry.
Every decision they signed then failed the offline verifier's identity check: the export named
them by today's address, the log by the one they registered with. ``auth_service.change_email``
logs ``user_email_changed``; the export carries it; both verifiers follow the chain.
"""

from __future__ import annotations

import pytest

from qvault.extensions import db
from qvault.models.ledger import LedgerEntry
from qvault.services import (
    approval_service,
    auth_service,
    export_service,
    ledger_service,
    proposal_service,
    vault_service,
)
from qvault.verify import verify_bundle

PASSWORD = "password-123"


def make_decision():
    owner = auth_service.register_user("ada@e.com", "Ada Lovelace", PASSWORD)
    vault = vault_service.create_vault(owner, "Treasury", "Payments", 2)
    other = auth_service.register_user("bob@e.com", "Bob", PASSWORD)
    vault_service.add_member(vault, other.email, "signer", actor_id=owner.id)
    proposal = proposal_service.create_proposal(vault, owner, "Hire", "Hire a designer.")
    for signer in (owner, other):
        approval_service.cast_vote(proposal, signer, PASSWORD, "approve")
    return proposal, owner, other


def verify(app, proposal):
    bundle = export_service.build_decision_bundle(proposal)
    return verify_bundle(bundle, registry=app.extensions["crypto"])


def identity(report):
    return next(c for c in report.checks if c.key == "identity")


def test_an_unlogged_rename_fails_the_identity_check(app, witnessed):
    """What live did on 14 Oct: the address changed, the log never heard of it."""
    proposal, owner, _ = make_decision()
    owner.email = "ada.real@e.com"
    db.session.commit()

    report = verify(app, proposal)
    assert not report.ok
    assert "the log recorded 'ada@e.com'" in identity(report).detail


def test_a_logged_rename_verifies_and_names_the_old_address(app, witnessed):
    proposal, owner, _ = make_decision()
    auth_service.change_email(owner, "Ada.Real@e.com", reason="moved to her real address")

    report = verify(app, proposal)
    assert report.ok, [(c.key, c.detail) for c in report.failures]
    assert identity(report).detail == "ada.real@e.com (was ada@e.com), bob@e.com"


def test_renames_chain_in_order(app, witnessed):
    proposal, owner, _ = make_decision()
    auth_service.change_email(owner, "ada2@e.com", reason="first")
    auth_service.change_email(owner, "ada3@e.com", reason="second")

    report = verify(app, proposal)
    assert report.ok
    assert "ada3@e.com (was ada@e.com, ada2@e.com)" in identity(report).detail


def test_a_rename_that_does_not_chain_from_the_logged_address_is_ignored(app, witnessed):
    """An entry cannot claim someone it does not chain from: its from_email must be the address
    the log already holds. Here the database is changed and an entry names the wrong 'from'."""
    proposal, owner, _ = make_decision()
    owner.email = "mallory@e.com"
    ledger_service.append(
        "user_email_changed",
        {"user_id": owner.id, "from_email": "someone@e.com", "to_email": "mallory@e.com"},
        actor="operator",
        ref_type="user",
        ref_id=str(owner.id),
    )

    report = verify(app, proposal)
    assert not report.ok
    assert "the log recorded 'ada@e.com'" in identity(report).detail


def test_the_change_is_in_the_log_with_both_addresses_and_the_reason(app):
    user = auth_service.register_user("ada@e.com", "Ada", PASSWORD)
    auth_service.change_email(user, "ada.real@e.com", reason="real address")

    entry = LedgerEntry.query.filter_by(event_type="user_email_changed").one()
    assert (entry.actor, entry.ref_type, entry.ref_id) == ("operator", "user", str(user.id))
    assert '"from_email":"ada@e.com"' in entry.payload_json
    assert '"to_email":"ada.real@e.com"' in entry.payload_json
    assert '"reason":"real address"' in entry.payload_json
    assert auth_service.authenticate("ada.real@e.com", PASSWORD) is not None


@pytest.mark.parametrize(
    "new, reason, error",
    [
        ("bob@e.com", "x", auth_service.EmailTakenError),
        ("ada@e.com", "x", ValueError),
        ("not-an-email", "x", ValueError),
        ("ada2@e.com", "  ", ValueError),
    ],
)
def test_a_bad_change_is_refused_and_logs_nothing(app, new, reason, error):
    user = auth_service.register_user("ada@e.com", "Ada", PASSWORD)
    auth_service.register_user("bob@e.com", "Bob", PASSWORD)
    with pytest.raises(error):
        auth_service.change_email(user, new, reason=reason)
    db.session.rollback()
    assert LedgerEntry.query.filter_by(event_type="user_email_changed").count() == 0
    assert db.session.get(type(user), user.id).email == "ada@e.com"
