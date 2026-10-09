"""Wrong passwords typed by someone already signed in are limited per account (R6 review, item 13).

The password unlocks the signing key, and the signed-in paths that ask for it (voting, approving a
treasury change, re-issuing the key, changing the password) sat behind a session where the public
per-address limiter never looked. A stolen session cookie meant unlimited guessing. Now
``MAX_FAILURES`` wrong passwords in ``WINDOW_SECONDS`` lock that account's password checks, before
any Argon2id work, with a sentence that says so.
"""

from __future__ import annotations

import html
import re

import pytest

from qvault.models.proposal import Proposal
from qvault.security import password_attempts
from qvault.services import auth_service, key_service, proposal_service, vault_service
from qvault.services.key_service import KeyUnlockError, PasswordLockedError

PW = "password-123"
LIMIT = password_attempts.MAX_FAILURES


@pytest.fixture()
def clock(monkeypatch):
    now = [10_000.0]
    monkeypatch.setattr(password_attempts.time, "monotonic", lambda: now[0])
    return now


@pytest.fixture()
def ada(app):
    return auth_service.register_user("ada@e.com", "Ada", PW)


def _text(resp) -> str:
    return html.unescape(re.sub(r"\s+", " ", resp.get_data(as_text=True)))


def _lock(user):
    for _ in range(LIMIT):
        with pytest.raises(KeyUnlockError) as caught:
            key_service.reissue_signing_key(user, "wrong-password")
        assert not isinstance(caught.value, PasswordLockedError)


def test_ten_wrong_passwords_lock_the_account_before_any_argon2_work(ada, clock, monkeypatch):
    _lock(ada)
    calls = []
    monkeypatch.setattr(key_service, "verify_password", lambda *a: calls.append(a) or True)
    monkeypatch.setattr(key_service, "derive_kek", lambda *a, **k: calls.append(a) or b"")
    with pytest.raises(PasswordLockedError, match="Too many wrong passwords"):
        key_service.reissue_signing_key(ada, PW)
    with pytest.raises(PasswordLockedError):
        key_service.change_password(ada, PW, "new-password-456")
    with pytest.raises(PasswordLockedError):
        key_service.sign_with_key(ada, key_service.active_signing_key(ada), PW, b"m")
    assert calls == [], "a refused check costs no Argon2id work and learns nothing"


def test_the_lock_ends_when_the_oldest_failure_leaves_the_window(ada, clock):
    _lock(ada)
    with pytest.raises(PasswordLockedError, match="15 minutes"):
        key_service.reissue_signing_key(ada, PW)
    clock[0] += password_attempts.WINDOW_SECONDS + 1
    assert key_service.reissue_signing_key(ada, PW).alg_id


def test_a_correct_password_clears_the_count(ada, clock):
    for _ in range(LIMIT - 1):
        with pytest.raises(KeyUnlockError):
            key_service.reissue_signing_key(ada, "wrong-password")
    key_service.reissue_signing_key(ada, PW)
    for _ in range(LIMIT - 1):
        with pytest.raises(KeyUnlockError) as caught:
            key_service.reissue_signing_key(ada, "wrong-password")
        assert not isinstance(caught.value, PasswordLockedError)


def test_the_lock_is_per_account(ada, clock):
    bea = auth_service.register_user("bea@e.com", "Bea", PW)
    _lock(ada)
    assert key_service.reissue_signing_key(bea, PW).alg_id


def test_a_wrong_password_when_signing_counts_too(ada, clock):
    key = key_service.active_signing_key(ada)
    for _ in range(LIMIT):
        with pytest.raises(KeyUnlockError):
            key_service.sign_with_key(ada, key, "wrong-password", b"m")
    with pytest.raises(PasswordLockedError):
        key_service.sign_with_key(ada, key, PW, b"m")


def _signed_in(client, email="ada@e.com"):
    client.post("/login", data={"email": email, "password": PW})
    return client


def test_the_vote_page_says_why_it_refused(app, client, ada, clock):
    vault = vault_service.create_vault(ada, "V", "", 1)
    pid = proposal_service.create_proposal(vault, ada, "T", "a").proposal_uuid
    _signed_in(client)
    url = f"/vaults/{vault.id}/proposals/{pid}/vote"
    for _ in range(LIMIT):
        client.post(url, data={"password": "wrong-password", "approve": "Approve & sign"})
    resp = client.post(
        url, data={"password": PW, "approve": "Approve & sign"}, follow_redirects=True
    )
    assert "Too many wrong passwords for this account" in _text(resp)
    assert Proposal.query.filter_by(proposal_uuid=pid).one().status == "open"


def test_the_password_and_reissue_forms_say_why_they_refused(app, client, ada, clock):
    _signed_in(client)
    data = {"current_password": "wrong-password", "new_password": "new-password-456",
            "confirm": "new-password-456"}  # fmt: skip
    for _ in range(LIMIT):
        client.post("/account/password", data=data)
    resp = client.post("/account/password", data={**data, "current_password": PW})
    assert "Too many wrong passwords for this account" in _text(resp)
    resp = client.post("/keys/reissue", data={"password": PW}, follow_redirects=True)
    assert "Too many wrong passwords for this account" in _text(resp)
    # Still signed in, still the old password: nothing changed.
    assert auth_service.authenticate("ada@e.com", PW) is not None
