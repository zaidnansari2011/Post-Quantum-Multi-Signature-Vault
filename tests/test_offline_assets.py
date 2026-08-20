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
        STATIC / "vendor" / "fonts.css",
        STATIC / "vendor" / "fonts" / "Archivo-var.woff2",
        STATIC / "qvault.css",
    ]
    missing = [str(p.relative_to(PROJECT_ROOT)) for p in required if not p.is_file()]
    assert not missing, f"vendored assets missing: {missing}"

    fonts = list((STATIC / "vendor" / "fonts").glob("*.woff2"))
    assert len(fonts) >= 6, f"expected the Archivo + Inter + JetBrains Mono weights, found {len(fonts)}"


def test_no_bootstrap_class_survives_in_a_template():
    """Bootstrap was dropped for the project's own design system. A stray `col-lg-6` or `btn-primary`
    left in a template is now dead markup that silently renders as an unstyled block — which looks
    like a bug in the design rather than the leftover it is."""
    # (?![-\w]) rather than \b: \b would match inside this design system's own `row-flex` and
    # `card`-free names, because a hyphen is a word boundary.
    dead = re.compile(
        r'class="[^"]*\b(?:'
        r"col-(?:sm|md|lg|xl)-\d+|row|btn-(?:primary|secondary|success|danger|outline-\w+)"
        r"|card(?:-body|-header)?|d-flex|text-muted|form-control-sm|input-group"
        r")(?![-\w])"
    )
    offenders = [
        f"{t.relative_to(PROJECT_ROOT)}:{i}: {line.strip()[:90]}"
        for t in _templates()
        for i, line in enumerate(t.read_text(encoding="utf-8").splitlines(), 1)
        if dead.search(line)
    ]
    assert not offenders, "Bootstrap classes no longer do anything:\n" + "\n".join(offenders)


def test_vendored_licences_are_recorded():
    """Redistributing third-party code and fonts obliges us to keep the notices.

    Everything is derived from what is actually on disk rather than hard-coded, so vendoring a new
    asset without recording its licence fails here instead of shipping quietly. That is the whole
    point — a licence table maintained by hand is a licence table that goes stale.
    """
    readme = (STATIC / "vendor" / "README.md").read_text(encoding="utf-8")
    assert "SIL Open Font License" in readme

    families = {p.stem.split("-")[0] for p in (STATIC / "vendor" / "fonts").glob("*.woff2")}
    assert families, "no vendored fonts found — the glob is wrong or the fonts are missing"
    unrecorded = sorted(f for f in families if f not in readme)
    assert not unrecorded, f"vendored without a licence notice: {unrecorded}"

    # Anything else in vendor/ — scripts, stylesheets — must be named too. Fonts are covered by
    # family above; README.md documents itself.
    others = sorted(
        p.name
        for p in (STATIC / "vendor").iterdir()
        if p.is_file() and p.name != "README.md" and p.suffix != ".woff2"
    )
    missing = [name for name in others if name not in readme]
    assert not missing, f"vendored without a licence notice: {missing}"


def test_the_vendored_pqc_bundle_is_a_plain_script():
    """The offline verifier inlines this into a single file opened from ``file://``.

    An ES module or anything needing a loader would work when served over HTTP and fail silently
    from a USB stick — which is the one environment the verifier exists for.
    """
    bundle = (STATIC / "vendor" / "pqc.js").read_text(encoding="utf-8")
    assert "globalThis.PQC" in bundle or "global.PQC" in bundle
    assert not re.search(r"^\s*(?:import|export)\s", bundle, re.MULTILINE)
    assert "</script" not in bundle.lower(), "would terminate the inlining script tag early"


def test_every_vendored_font_is_reachable_over_http(client):
    """The CSS references these by relative path; prove Flask actually serves them."""
    for name in (
        "qvault.css",
        "vendor/fonts.css",
        "vendor/fonts/Inter-400.woff2",
        "vendor/fonts/Archivo-var.woff2",
    ):
        resp = client.get(f"/static/{name}")
        assert resp.status_code == 200, f"/static/{name} -> {resp.status_code}"
        assert len(resp.get_data()) > 1000
