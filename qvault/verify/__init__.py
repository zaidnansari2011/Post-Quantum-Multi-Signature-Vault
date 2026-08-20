"""Zero-trust verification of an exported Q-Vault decision.

Everything here runs on a stranger's laptop against a file they were emailed. It has no database,
no Flask, no configuration and no network: the only inputs are the bundle and, optionally, the key
fingerprints the reader was told to expect. If this package ever needs the server to answer a
question, the export has failed at its purpose.

``tests/test_verifier_purity.py`` enforces the import boundary mechanically, because this is the
kind of constraint that erodes one convenient import at a time.
"""

from __future__ import annotations

from .core import BUNDLE_FORMAT, Check, Report, verify_bundle
from .reader import BundleFormatError, load_bundle

__all__ = [
    "BUNDLE_FORMAT",
    "BundleFormatError",
    "Check",
    "Report",
    "load_bundle",
    "verify_bundle",
]
