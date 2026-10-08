"""The phone's icons are the style tile's, outlined into a font (rework phone-ux §2.2).

``mobile/tools/icons_from_tile.ts`` reads the tile's sprite and the phone's additions, outlines
each 1.5 stroke into filled contours, and writes ``assets/fonts/QVaultIcons.ttf`` with its glyph map
``src/theme/icons.generated.ts``. This regenerates both into a temporary folder and fails if the
committed copies differ, so an icon changed on the tile cannot silently skip the phone; and it
checks that every glyph the four tabs need, outline and filled, is in the map.
"""

from __future__ import annotations

import re
import subprocess

import pytest
from test_mobile_canonical import MOBILE_DIR, _node_available

GENERATOR = MOBILE_DIR / "tools" / "icons_from_tile.ts"
FONT = MOBILE_DIR / "assets" / "fonts" / "QVaultIcons.ttf"
GLYPHS = MOBILE_DIR / "src" / "theme" / "icons.generated.ts"

pytestmark = pytest.mark.skipif(
    not _node_available() or not GENERATOR.exists(),
    reason="Node and mobile/ are required; run pnpm install in mobile/.",
)


@pytest.fixture(scope="module")
def fresh(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("icons")
    font, glyphs = tmp / "icons.ttf", tmp / "icons.generated.ts"
    run = subprocess.run(
        ["node", str(GENERATOR), str(font), str(glyphs)],
        cwd=str(MOBILE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if run.returncode != 0:
        pytest.fail(f"icons_from_tile.ts failed:\n{run.stdout}\n{run.stderr}")
    return font.read_bytes(), glyphs.read_bytes()


def test_the_committed_font_matches_a_fresh_build(fresh):
    assert FONT.read_bytes() == fresh[0], "run `node tools/icons_from_tile.ts` in mobile/"


def test_the_committed_glyph_map_matches_a_fresh_build(fresh):
    assert GLYPHS.read_bytes() == fresh[1], "run `node tools/icons_from_tile.ts` in mobile/"


def test_the_tabs_have_outline_and_filled_glyphs():
    names = set(re.findall(r"^  '([a-z0-9-]+)':", GLYPHS.read_text(encoding="utf-8"), re.M))
    for tab in ("inbox", "pulse", "vault", "user"):
        assert {tab, f"{tab}-fill"} <= names
    # The platform glyphs §2.7 names, and the ones the components draw.
    assert {"chevron-left", "arrow-left", "more", "more-vertical", "chevron-right"} <= names
    assert {"alert", "clock", "check-circle", "info", "copy", "eye", "eye-off", "plus"} <= names


def test_the_app_draws_only_glyphs_the_font_has():
    names = set(re.findall(r"^  '([a-z0-9-]+)':", GLYPHS.read_text(encoding="utf-8"), re.M))
    used = set()
    for path in (MOBILE_DIR / "src").rglob("*.tsx"):
        used |= set(re.findall(r"""\bicon=["']([a-z0-9-]+)["']""", path.read_text("utf-8")))
        used |= set(re.findall(r"""<Icon\s+name=["']([a-z0-9-]+)["']""", path.read_text("utf-8")))
    assert used, "no icons found; the pattern above has drifted from the components"
    assert used <= names, sorted(used - names)
