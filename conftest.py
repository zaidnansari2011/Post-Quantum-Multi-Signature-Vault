"""Pytest configuration shared across the suite.

Placing this at the repository root ensures the root is on ``sys.path`` so that
``import qvault`` and ``import config`` resolve when tests run from anywhere.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from qvault.crypto import build_registry  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "separation_default: new vaults take the product's S15 default (whoever raises a decision "
        "can't approve it) instead of the suite's pre-R5 one",
    )


@pytest.fixture(autouse=True)
def _new_vaults_let_the_requester_approve(request, monkeypatch):
    """Most of the suite predates S15: its vaults' owners raise decisions and sign them, to test
    signing, the log, exports and payments, not who may sign. Since 2026-10-08 a new vault stops
    that by default, so here new vaults start as every vault did before R5. Tests of the default
    itself are marked ``separation_default``; tests of the rule set it on their vault explicitly.
    """
    if request.node.get_closest_marker("separation_default"):
        return
    from qvault.services import vault_service

    monkeypatch.setattr(vault_service, "new_vault_separates", lambda owner: False)


@pytest.fixture(scope="session")
def registry():
    """A fully populated CryptoRegistry using the default backend."""
    return build_registry()


@pytest.fixture()
def app():
    """A fresh app on an isolated in-memory testing DB, with an active app context."""
    from qvault import create_app

    application = create_app("testing")
    with application.app_context():
        yield application


@pytest.fixture()
def client(app):
    """A test client for the app fixture."""
    return app.test_client()


@pytest.fixture()
def witnessed(app, tmp_path, monkeypatch):
    """The application wired to a real, separate witness process.

    The witness is a genuinely independent Flask app with its own keypair and its own SQLite file;
    only the *transport* is stubbed, so the suite needs no sockets while the request bodies, the
    signatures and the two stores stay real. Returns the witness app so a test can inspect what it
    co-signed and what it refused.

    ML-DSA-65 rather than the SLH-DSA default purely for speed — SLH-DSA signing is ~39 ms and
    these fixtures co-sign on almost every test. ``tests/test_witness.py`` covers the real default.
    """
    from qvault.services import checkpoint_service
    from witness.app import create_witness_app

    base = "http://witness.invalid"
    witness_app = create_witness_app(
        state_path=tmp_path / "witness.db",
        key_path=tmp_path / "witness_key.json",
        name="witness-1",
        alg_id="ML-DSA-65",
    )
    witness_app.testing = True
    transport = witness_app.test_client()

    def route(url: str) -> str:
        assert url.startswith(base), url
        return url[len(base) :]

    monkeypatch.setattr(
        checkpoint_service, "_get", lambda url, timeout: transport.get(route(url)).get_json()
    )
    monkeypatch.setattr(
        checkpoint_service,
        "_post",
        lambda url, body, timeout: transport.post(route(url), json=body).get_json(),
    )
    app.config["WITNESS_URL"] = base
    return witness_app
