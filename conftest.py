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
