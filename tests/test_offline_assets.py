"""The interface must render with no network connection.

A demonstration happens in someone else's room on someone else's network. If Bootstrap is loaded
from a CDN and that request fails, the page does not degrade — it collapses into unstyled HTML at
the worst possible moment. So every asset is vendored, and this test stops that decision from
silently regressing the next time a template gains a `<script src="https://...">`.
"""

from __future__ import annotations

import pathlib
import re

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATES = PROJECT_ROOT / "qvault" / "templates"
STATIC = PROJECT_ROOT / "qvault" / "static"

# Any href=/src= pointing off-box. Deliberately catches protocol-relative "//cdn..." too.
EXTERNAL_ASSET = re.compile(r"""(?:href|src)\s*=\s*["'](https?:)?//""", re.IGNORECASE)


def _templates():
    return sorted(TEMPLATES.rglob("*.html"))


def test_there_are_templates_to_check():
    """Guard against the glob silently matching nothing and the suite passing vacuously."""
    assert len(_templates()) >= 10


@pytest.mark.parametrize("template", _templates(), ids=lambda p: p.name)
def test_no_template_loads_an_external_asset(template):
    offenders = [
        f"{template.relative_to(PROJECT_ROOT)}:{i}: {line.strip()}"
        for i, line in enumerate(template.read_text(encoding="utf-8").splitlines(), 1)
        if EXTERNAL_ASSET.search(line)
    ]
    assert not offenders, "Vendor it into qvault/static/vendor/ instead:\n" + "\n".join(offenders)


def test_no_stylesheet_fetches_a_remote_font():
    """A vendored CSS file that still points at fonts.gstatic.com would defeat the whole point."""
    offenders = []
    for css in sorted(STATIC.rglob("*.css")):
        text = css.read_text(encoding="utf-8")
        for match in re.finditer(r"url\(\s*['\"]?((?:https?:)?//[^)'\"]+)", text):
            offenders.append(f"{css.relative_to(PROJECT_ROOT)}: {match.group(1)}")
    assert not offenders, "Remote asset referenced from CSS:\n" + "\n".join(offenders)


def test_the_vendored_assets_are_actually_present():
    """The templates now depend on these paths; a missing file is a broken page, not a fallback."""
    required = [
        STATIC / "vendor" / "bootstrap.min.css",
        STATIC / "vendor" / "bootstrap.bundle.min.js",
        STATIC / "vendor" / "fonts.css",
    ]
    missing = [str(p.relative_to(PROJECT_ROOT)) for p in required if not p.is_file()]
    assert not missing, f"vendored assets missing: {missing}"

    fonts = list((STATIC / "vendor" / "fonts").glob("*.woff2"))
    assert len(fonts) >= 6, f"expected the Inter + JetBrains Mono weights, found {len(fonts)}"


def test_vendored_licences_are_recorded():
    """Redistributing MIT/OFL assets obliges us to keep the notices."""
    readme = (STATIC / "vendor" / "README.md").read_text(encoding="utf-8")
    assert "MIT" in readme and "SIL Open Font License" in readme


def test_every_vendored_font_is_reachable_over_http(client):
    """The CSS references these by relative path; prove Flask actually serves them."""
    for name in ("vendor/bootstrap.min.css", "vendor/fonts.css", "vendor/fonts/Inter-400.woff2"):
        resp = client.get(f"/static/{name}")
        assert resp.status_code == 200, f"/static/{name} -> {resp.status_code}"
        assert len(resp.get_data()) > 1000
