"""The phone's colours are the web's, in both themes (rework phone-ux §3.2, §8.4).

``mobile/src/theme/tokens.generated.ts`` is written by ``mobile/tools/tokens_from_css.ts`` from the
web's ``qvault/static/tokens.css``. This regenerates it into a temporary file and fails if the
committed copy differs, so a colour changed on the web cannot silently skip the phone. It then
measures the pairs only the phone uses (the tab badge, the unread dot, the inactive tab label, the
seal's empty mark on the raised surfaces) and the core pairs every phone component relies on, in
both themes, against WCAG 2.2 AA.
"""

from __future__ import annotations

import json
import re
import subprocess

import pytest
from test_mobile_canonical import MOBILE_DIR, _node_available

GENERATOR = MOBILE_DIR / "tools" / "tokens_from_css.ts"
COMMITTED = MOBILE_DIR / "src" / "theme" / "tokens.generated.ts"
SOURCE = MOBILE_DIR.parent / "qvault" / "static" / "tokens.css"

pytestmark = pytest.mark.skipif(
    not _node_available() or not GENERATOR.exists(),
    reason="Node and mobile/ are required; run pnpm install in mobile/.",
)

HEX = re.compile(r"^#[0-9A-F]{6}([0-9A-F]{2})?$")


@pytest.fixture(scope="module")
def generated(tmp_path_factory) -> dict:
    tmp = tmp_path_factory.mktemp("tokens")
    out_ts, out_json = tmp / "tokens.generated.ts", tmp / "tokens.json"
    run = subprocess.run(
        ["node", str(GENERATOR), str(SOURCE), str(out_ts), "--json", str(out_json)],
        cwd=str(MOBILE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if run.returncode != 0:
        pytest.fail(f"tokens_from_css.ts failed:\n{run.stdout}\n{run.stderr}")
    return {
        "ts": out_ts.read_bytes(),
        "json": json.loads(out_json.read_text(encoding="utf-8")),
    }


def test_the_committed_tokens_match_a_fresh_generation(generated):
    assert COMMITTED.read_bytes() == generated["ts"], (
        "mobile/src/theme/tokens.generated.ts is out of date with qvault/static/tokens.css; "
        "run `node tools/tokens_from_css.ts` in mobile/"
    )


def _leaves(tree: dict, prefix: str = "") -> dict[str, str]:
    out = {}
    for key, value in tree.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(_leaves(value, name + "."))
        else:
            out[name] = value
    return out


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_every_token_is_a_colour_in_both_themes(generated, scheme):
    light = _leaves(generated["json"]["light"])
    tokens = _leaves(generated["json"][scheme])
    assert set(tokens) == set(light), "both themes define the same tokens"
    for name, value in tokens.items():
        assert HEX.match(value), f"{scheme}.{name} = {value!r}"


def test_the_dark_theme_really_is_dark(generated):
    light, dark = generated["json"]["light"], generated["json"]["dark"]
    assert _luminance(dark["bg"]) < 0.02 < _luminance(light["bg"])
    assert _luminance(dark["text"]) > 0.7 > _luminance(light["text"])
    # Surfaces step lighter in dark instead of casting shadows (S25).
    assert _luminance(dark["surfaceRaised"]) > _luminance(dark["surface"]) >= _luminance(dark["bg"])


def test_motion_is_the_webs(generated):
    motion = generated["json"]["motion"]
    assert (motion["press"], motion["popover"], motion["dialog"], motion["dialogExit"]) == (
        100,
        150,
        220,
        160,
    )
    assert motion["seal"] == 620
    assert len(motion["easeSeal"]) == 4


def _luminance(hex_colour: str) -> float:
    rgb = [int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(fg: str, bg: str) -> float:
    a, b = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def _get(tree: dict, path: str) -> str:
    node = tree
    for key in path.split("."):
        node = node[key]
    return node


# (foreground, background, minimum): text 4.5, non-text UI 3.0 (WCAG 1.4.3, 1.4.11).
PAIRS = [
    # The phone's own pairs (§3.4, §8.4).
    ("chrome.badgeText", "chrome.badgeBg", 4.5),
    ("chrome.badgeBg", "chrome.bg", 3.0),
    ("chrome.dot", "chrome.bg", 3.0),
    ("chrome.textMuted", "chrome.bg", 4.5),
    ("chrome.text", "chrome.bg", 4.5),
    ("textSubtle", "fill", 4.5),
    ("markEmpty", "surface", 3.0),
    ("markEmpty", "surfaceRaised", 3.0),
    ("markFilled", "surface", 3.0),
    ("markFilled", "surfaceRaised", 3.0),
    # What every phone screen leans on.
    ("text", "bg", 4.5),
    ("textMuted", "bg", 4.5),
    ("textSubtle", "bg", 4.5),
    ("textMuted", "surface", 4.5),
    ("textSubtle", "surface", 4.5),
    ("textMuted", "surfaceRaised", 4.5),
    ("textSubtle", "surfaceRaised", 4.5),
    ("textMuted", "fill", 4.5),
    ("accentText", "accent", 4.5),
    ("accentText", "accentPressed", 4.5),
    ("dangerText", "danger", 4.5),
    ("dangerText", "dangerPressed", 4.5),
    # `danger` is a FILL (Sign rejection, Remove this phone), measured as a shape against the page.
    # Text in the danger tone on a surface (the Reject label in the action bar) uses
    # status.critical.fg instead: dark --danger on a dark surface is only 3.4:1.
    ("danger", "surface", 3.0),
    ("danger", "bg", 3.0),
    ("link", "bg", 4.5),
    ("link", "surface", 4.5),
    ("accentFg", "accentSubtle", 4.5),
    ("borderStrong", "surface", 3.0),
    ("borderStrong", "surfaceRaised", 3.0),
    ("borderStrong", "bg", 3.0),
    ("accent", "surface", 3.0),
] + [
    (f"status.{tone}.fg", where, 4.5)
    for tone in ("success", "warning", "critical", "info", "neutral")
    for where in (f"status.{tone}.bg", "surface", "bg")
]


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("fg,bg,minimum", PAIRS, ids=[f"{f}-on-{b}" for f, b, _ in PAIRS])
def test_contrast(generated, scheme, fg, bg, minimum):
    palette = generated["json"][scheme]
    ratio = _contrast(_get(palette, fg)[:7], _get(palette, bg)[:7])
    assert ratio >= minimum, f"{scheme}: {fg} on {bg} is {ratio:.2f}:1, needs {minimum}:1"
