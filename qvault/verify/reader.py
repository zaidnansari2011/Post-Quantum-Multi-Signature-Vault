"""Read a decision bundle out of whatever the export actually handed someone.

The export produces three artefacts for three audiences — a self-verifying ``.html`` record, a
``.zip`` package, and the bare ``.qvault.json`` — and this module is the single place that turns
any of them back into a bundle dict.

It exists because the alternative kept producing the same bug. The export changed shape twice, and
each time a verification path was left behind: ``/verify`` once advertised ``accept=".json"`` while
the download was a ``.zip``, so the one file a user had was the one file the page appeared to
refuse; the CLI printed in that page's own footer could not read it either. A rule that has to be
remembered in three call sites is a rule that will be forgotten in one of them, so the rule lives
here and the call sites ask.

Detection is by **content, not filename**. A browser that appends ``.txt``, a user who renames a
download, an upload arriving with no name at all — none of those change what the bytes are, and
refusing them would be refusing evidence over a label.

No Flask, no database, no network: ``tests/test_verifier_purity.py`` enforces that boundary for
this whole package, and this module is reached from the offline CLI.
"""

from __future__ import annotations

import io
import json
import re
import zipfile

#: The element ``export_service.build_decision_document`` fills. Matched with a tolerant pattern
#: rather than an exact string because the document is HTML someone may have opened, saved from a
#: browser, or reformatted; the id is the stable part.
_SLOT = re.compile(
    rb"<script[^>]*id=[\"']qvault-decision[\"'][^>]*>(.*?)</script\s*>",
    re.DOTALL | re.IGNORECASE,
)

_ZIP_MAGIC = b"PK\x03\x04"


class BundleFormatError(ValueError):
    """The input could not be read as a decision bundle, with a reason a person can act on."""


def _from_zip(raw: bytes) -> bytes:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = [n for n in archive.namelist() if n.endswith("decision.json")]
            if not names:
                raise BundleFormatError("that package contains no decision.json")
            return archive.read(names[0])
    except zipfile.BadZipFile as exc:
        raise BundleFormatError(f"that package could not be opened: {exc}") from exc


def _from_document(raw: bytes) -> bytes | None:
    """Return the embedded bundle from a self-verifying decision record, if this is one."""
    match = _SLOT.search(raw)
    if match is None:
        return None
    payload = match.group(1).strip()
    if not payload:
        # The generic verifier ships with this slot deliberately empty. That is not an error to
        # report as a corrupt document -- it simply carries no decision.
        raise BundleFormatError(
            "that file is the blank Q-Vault verifier, which carries no decision of its own. "
            "Export a decision, or load one into that page."
        )
    return payload


def load_bundle(raw: bytes) -> dict:
    """Return the bundle dict from a ``.html`` record, a ``.zip`` package, or bare JSON bytes."""
    if not raw or not raw.strip():
        raise BundleFormatError("that file is empty")

    if raw[:4] == _ZIP_MAGIC:
        raw = _from_zip(raw)
    else:
        embedded = _from_document(raw)
        if embedded is not None:
            raw = embedded

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BundleFormatError(f"that file is not text: {exc}") from exc

    try:
        bundle = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BundleFormatError(f"that is not valid JSON: {exc}") from exc

    if not isinstance(bundle, dict):
        raise BundleFormatError("a decision bundle must be a JSON object")
    return bundle
