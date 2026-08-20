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
