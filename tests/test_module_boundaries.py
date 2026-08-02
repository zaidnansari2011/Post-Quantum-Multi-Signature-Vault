"""Enforces the architectural rule that keeps Q-Vault crypto-agile.

A PQC backend (``quantcrypt``, ``oqs``, ``pqcrypto``) may be imported ONLY inside
``qvault/crypto/providers/``. If application, service, model, or blueprint code imported a
backend directly, the abstraction would leak and the runtime algorithm switch would no
longer be safe. This test greps the source tree to prove the boundary holds.
"""

from __future__ import annotations

import pathlib
import re

BACKEND_IMPORT = re.compile(r"^\s*(?:import|from)\s+(quantcrypt|oqs|pqcrypto)\b", re.MULTILINE)

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
QVAULT = PROJECT_ROOT / "qvault"
ALLOWED_DIR = QVAULT / "crypto" / "providers"


def test_no_backend_imports_outside_providers():
    offenders = []
    for path in QVAULT.rglob("*.py"):
        if ALLOWED_DIR in path.parents:
            continue
        text = path.read_text(encoding="utf-8")
        if BACKEND_IMPORT.search(text):
            offenders.append(str(path.relative_to(PROJECT_ROOT)))

    assert not offenders, (
        "PQC backend imported outside qvault/crypto/providers/: "
        + ", ".join(offenders)
        + ". Route through CryptoRegistry instead."
    )
