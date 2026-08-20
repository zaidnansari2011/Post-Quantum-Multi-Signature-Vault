"""Inline the vendored PQC bundle into the offline verifier, producing one self-contained file.

    python scripts/build_verifier.py

Reads ``qvault/static/verifier.src.html`` and ``qvault/static/vendor/pqc.js``, writes
``qvault/static/verifier.html``. The generated file is committed, the way vendored assets are:
someone checking a decision in five years should not need this repository, a package registry, or
a working npm.

``tests/test_offline_verifier.py`` regenerates and compares, so a change to the source or the
vendor bundle that was never rebuilt fails the suite rather than shipping a stale verifier.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / "qvault" / "static" / "verifier.src.html"
BUNDLE = ROOT / "qvault" / "static" / "vendor" / "pqc.js"
OUTPUT = ROOT / "qvault" / "static" / "verifier.html"
PLACEHOLDER = "/*__PQC_BUNDLE__*/"


def render() -> str:
    source = SOURCE.read_text(encoding="utf-8")
    if PLACEHOLDER not in source:
        raise SystemExit(f"{SOURCE} no longer contains {PLACEHOLDER}")
    bundle = BUNDLE.read_text(encoding="utf-8")
    # A literal </script> anywhere in the payload would close the tag early. Noble contains none,
    # but the check is cheap and its absence would be an XSS-shaped failure in a security tool.
    if "</script" in bundle.lower():
        raise SystemExit("the vendor bundle contains a </script sequence and cannot be inlined")
    return source.replace(PLACEHOLDER, bundle)


def main() -> int:
    rendered = render()
    if OUTPUT.exists() and OUTPUT.read_text(encoding="utf-8") == rendered:
        print(f"{OUTPUT.relative_to(ROOT)} is already up to date ({len(rendered):,} bytes)")
        return 0
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)}  {len(rendered.encode('utf-8')):,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
