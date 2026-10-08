"""The design tokens hold the promises the rework makes about colour, type and dark mode.

``qvault/static/tokens.css`` is a verbatim copy of the style tile's token file (rework R1.1), so a
re-sync is a file copy. These tests read it the way a browser would (light values on ``:root``,
dark values layered over them) and check what the plan commits to in section 6 and decisions S2,
S24 and S25:

* every colour has a dark value, and the two dark blocks (the system preference and the manual
  choice) say exactly the same thing;
* every colour pair a component relies on meets WCAG contrast in both themes;
* the type scale sits on a 4px line-height grid;
* no stylesheet of ours names a colour of its own, so nothing can ignore the theme.
"""

from __future__ import annotations

import pathlib
import re

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
STATIC = PROJECT_ROOT / "qvault" / "static"
TEMPLATES = PROJECT_ROOT / "qvault" / "templates"
TOKENS = STATIC / "tokens.css"
#: Our stylesheets, in load order after the fonts. Vendor files are third-party and excepted.
OUR_CSS = [
    STATIC / name
    for name in (
        "tokens.css",
        "base.css",
        "components.css",
        "evidence.css",
        "screens.css",
        "qvault.css",
        "utilities.css",
    )
]

TEXT = 4.5  # WCAG 1.4.3, normal text
UI = 3.0  # WCAG 1.4.11: controls, focus indicators, meaningful graphics

# ------------------------------------------------------------------------------- reading tokens.css

LIGHT_SELECTOR = ":root"
DARK_MEDIA_SELECTOR = '@media(prefers-color-scheme:dark)>>:root:not([data-theme="light"])'
DARK_ATTR_SELECTOR = ':root[data-theme="dark"]'


def strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def rule_blocks(css: str) -> list[tuple[str, str]]:
    """Top-level rules as (selector, body); a rule inside @media is prefixed by its prelude."""
    out: list[tuple[str, str]] = []
    i, n = 0, len(css)
    while i < n:
        j = css.find("{", i)
        if j < 0:
            break
        selector = "".join(css[i:j].split()).replace("'", '"')
        depth, k = 1, j + 1
        while k < n and depth:
            depth += {"{": 1, "}": -1}.get(css[k], 0)
            k += 1
        body = css[j + 1 : k - 1]
        if selector.startswith("@media"):
            out.extend((f"{selector}>>{s}", b) for s, b in rule_blocks(body))
        else:
            out.append((selector, body))
        i = k
    return out


def declarations(body: str) -> dict[str, str]:
    return {
        m.group(1): " ".join(m.group(2).split())
        for m in re.finditer(r"(--[\w-]+|color-scheme)\s*:\s*([^;]+);", body)
    }


def load_tokens() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    light = dark_media = dark_attr = None
    for selector, body in rule_blocks(strip_comments(TOKENS.read_text(encoding="utf-8"))):
        if selector == LIGHT_SELECTOR:
            assert light is None, "tokens.css has more than one plain :root block"
            light = declarations(body)
        elif selector == DARK_MEDIA_SELECTOR:
            dark_media = declarations(body)
        elif selector == DARK_ATTR_SELECTOR:
            dark_attr = declarations(body)
        else:
            raise AssertionError(
                f"tokens.css: unexpected block {selector!r}; the theming shape is fixed"
            )
    assert light and dark_media and dark_attr, "tokens.css must have :root and both dark blocks"
    return light, dark_media, dark_attr


LIGHT, DARK_MEDIA, DARK_ATTR = load_tokens()
THEMES = {"light": LIGHT, "dark": {**LIGHT, **DARK_ATTR}}

VAR = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^)]*))?\)")
COLOUR_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch)\(")


def resolve(name: str, tokens: dict[str, str], trail: tuple[str, ...] = ()) -> str:
    assert name not in trail, f"circular reference: {' -> '.join(trail + (name,))}"
    assert name in tokens, f"{trail[-1] if trail else name} references undefined {name}"

    def sub(m: re.Match) -> str:
        if m.group(1) in tokens:
            return resolve(m.group(1), tokens, trail + (name,))
        assert m.group(2) is not None, f"{name} references undefined {m.group(1)}"
        return m.group(2).strip()

    return VAR.sub(sub, tokens[name])


def rgb(value: str) -> tuple[float, float, float]:
    v = value.strip()
    assert re.fullmatch(
        r"#(?:[0-9a-fA-F]{3}){1,2}", v
    ), f"measured pairs must be opaque hex, got {v!r}"
    v = v[1:]
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    return tuple(int(v[i : i + 2], 16) / 255 for i in (0, 2, 4))


def luminance(colour: tuple[float, float, float]) -> float:
    def linear(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(c) for c in colour)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg: str, bg: str) -> float:
    a, b = luminance(rgb(fg)), luminance(rgb(bg))
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def is_colour_token(name: str) -> bool:
    """A token whose light value is, or resolves to, a colour (shadows count: they carry one)."""
    return bool(COLOUR_LITERAL.search(resolve(name, LIGHT)))


# ------------------------------------------------------------------------------- dark mode (S25)


def test_the_two_dark_blocks_say_exactly_the_same_thing():
    """The system preference and the manual Dark choice must never drift into two dark themes."""
    only_media = sorted(set(DARK_MEDIA) - set(DARK_ATTR))
    only_attr = sorted(set(DARK_ATTR) - set(DARK_MEDIA))
    differ = sorted(k for k in set(DARK_MEDIA) & set(DARK_ATTR) if DARK_MEDIA[k] != DARK_ATTR[k])
    assert not (only_media or only_attr or differ), (
        f"only in the media block: {only_media}; only in [data-theme=dark]: {only_attr}; "
        f"different values: {differ}"
    )


def test_both_dark_blocks_switch_the_browser_to_dark_and_root_to_light():
    """color-scheme is what turns native controls, scrollbars and the canvas dark too."""
    assert LIGHT.get("color-scheme") == "light"
    assert DARK_MEDIA.get("color-scheme") == "dark"
    assert DARK_ATTR.get("color-scheme") == "dark"


def test_every_colour_token_has_a_dark_value():
    """A colour set only on :root would stay light in dark mode.

    A token written as a colour must be redefined in the dark block. A token that aliases others
    (``--text: var(--neutral-12)``) has a dark value when everything it points at does.
    """

    def has_dark_value(name: str) -> bool:
        if name in DARK_ATTR:
            return True
        refs = VAR.findall(LIGHT[name])
        if not refs or COLOUR_LITERAL.search(VAR.sub("", LIGHT[name])):
            return False
        return all(has_dark_value(ref) for ref, _ in refs)

    colours = [name for name in LIGHT if name.startswith("--") and is_colour_token(name)]
    assert (
        len(colours) > 60
    ), "the colour tokens were not found; the parser is reading the wrong file"
    light_only = sorted(name for name in colours if not has_dark_value(name))
    assert not light_only, f"colour tokens with no dark value: {light_only}"


def test_the_dark_blocks_only_redefine_tokens_root_declares():
    unknown = sorted(set(DARK_ATTR) - set(LIGHT))
    assert not unknown, f"dark sets tokens :root never defines: {unknown}"


@pytest.mark.parametrize("theme", THEMES)
def test_every_token_resolves(theme):
    tokens = THEMES[theme]
    for name in tokens:
        resolve(name, tokens)


# ------------------------------------------------------------------------------- contrast (S24)
#
# The pairs the components rely on, from the style tile's measurement script
# (docs/plans/saas-rework/style-tile/tools/contrast.py), which writes contrast.md. Each foreground
# is checked on every background it can sit on, in both themes.

TEXT_BACKGROUNDS = [
    "--bg",
    "--bg-subtle",
    "--surface",
    "--surface-raised",
    "--fill",
    "--fill-hover",
    "--accent-subtle",
]
STATUS_TONES = ("neutral", "info", "success", "warning", "critical")

PAIRS: list[tuple[str, list[str], float, str]] = [
    ("--text", TEXT_BACKGROUNDS, TEXT, "body text, titles, the decision text"),
    ("--text-muted", TEXT_BACKGROUNDS, TEXT, "secondary text, labels in key-value panels"),
    ("--text-subtle", TEXT_BACKGROUNDS, TEXT, "meta, timestamps, captions, placeholders"),
    ("--selection-text", ["--selection"], TEXT, "selected text"),
    ("--accent-text", ["--accent", "--accent-hover"], TEXT, "the label on the primary button"),
    (
        "--accent-fg",
        ["--accent-subtle", "--accent-subtle-hover", "--bg", "--bg-subtle", "--surface"],
        TEXT,
        "the active navigation item and tab",
    ),
    (
        "--link",
        ["--bg", "--bg-subtle", "--surface", "--surface-raised", "--fill-hover", "--accent-subtle"],
        TEXT,
        "links in text, rows and menus",
    ),
    (
        "--link-hover",
        ["--bg", "--bg-subtle", "--surface", "--surface-raised", "--fill-hover"],
        TEXT,
        "a hovered link",
    ),
    (
        "--focus",
        ["--bg", "--bg-subtle", "--surface", "--surface-raised", "--accent-subtle", "--fill-hover"],
        UI,
        "the 2px focus ring, 2px off the element",
    ),
    (
        "--border-strong",
        ["--bg", "--bg-subtle", "--surface", "--surface-raised", "--fill-hover", "--accent-subtle"],
        UI,
        "input, select, checkbox and radio borders",
    ),
    (
        "--accent",
        ["--bg", "--bg-subtle", "--surface", "--surface-raised"],
        UI,
        "a checked checkbox, radio or switch; the primary button's edge",
    ),
    (
        "--mark-filled",
        ["--bg", "--surface", "--surface-raised", "--fill-hover"],
        UI,
        "a signature in the quorum seal",
    ),
    (
        "--mark-empty",
        ["--bg", "--surface", "--surface-raised", "--fill-hover"],
        UI,
        "a signature still needed",
    ),
    ("--danger-text", ["--danger", "--danger-hover"], TEXT, "the label on a destructive button"),
    ("--danger", ["--surface", "--surface-raised"], UI, "a destructive button's edge"),
    *[
        (
            f"--status-{t}-fg",
            [f"--status-{t}-bg", "--bg", "--surface", "--surface-raised", "--fill-hover"],
            TEXT,
            f"{t} badge text, and the {t} word as coloured text in a row",
        )
        for t in STATUS_TONES
    ],
    *[
        (("--text"), [f"--status-{t}-bg"], TEXT, f"body text inside a {t} banner")
        for t in STATUS_TONES[1:]
    ],
    (
        "--chrome-text",
        ["--chrome-bg", "--chrome-bg-raised"],
        TEXT,
        "text on the chrome: receipts, code, tooltips",
    ),
    (
        "--chrome-text-muted",
        ["--chrome-bg", "--chrome-bg-raised"],
        TEXT,
        "secondary text on the chrome",
    ),
]


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize(
    ("fg", "backgrounds", "target", "where"),
    PAIRS,
    ids=[f"{fg}-on-{len(bgs)}-backgrounds-{where.split(',')[0]}" for fg, bgs, _, where in PAIRS],
)
def test_colour_pairs_meet_wcag_contrast(theme, fg, backgrounds, target, where):
    tokens = THEMES[theme]
    failures = []
    for bg in backgrounds:
        ratio = contrast(resolve(fg, tokens), resolve(bg, tokens))
        if ratio < target:
            failures.append(f"{fg} on {bg}: {ratio:.3f} (needs {target}) for {where}")
    assert not failures, f"{theme} theme:\n" + "\n".join(failures)


def test_the_contrast_check_would_catch_a_failing_pair():
    """The arithmetic is right: the WCAG reference values, and a pair that must fail."""
    assert contrast("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert contrast("#777777", "#FFFFFF") == pytest.approx(4.48, abs=0.01)  # the classic near miss
    assert contrast("#767676", "#FFFFFF") >= TEXT


# ------------------------------------------------------------------------------- type (S2)

SIZE = re.compile(r"--text-([\w-]+?)-size$")


def _px(value: str) -> float:
    m = re.fullmatch(r"([\d.]+)(rem|px)", value.strip())
    assert m, f"type tokens are rem or px, got {value!r}"
    return float(m.group(1)) * (16 if m.group(2) == "rem" else 1)


def test_every_line_height_in_the_scale_is_on_the_4px_grid():
    lines = {
        name: _px(value)
        for name, value in LIGHT.items()
        if re.fullmatch(r"--text-[\w-]+-line", name)
    }
    assert len(lines) >= 8, f"the type scale's line heights were not found: {sorted(lines)}"
    off_grid = {name: px for name, px in lines.items() if px % 4}
    assert not off_grid, f"line heights off the 4px grid (in px): {off_grid}"


def test_every_size_in_the_scale_has_a_line_height():
    sizes = [name for name in LIGHT if SIZE.match(name)]
    assert sizes, "no --text-*-size tokens found"
    # The touch size is a floor for inputs below 768px (so iOS does not zoom); it borrows the
    # input's own line height.
    missing = [
        name
        for name in sizes
        if name != "--text-input-size-touch" and name.replace("-size", "-line") not in LIGHT
    ]
    assert not missing, f"sizes with no matching line height: {missing}"


def test_line_heights_are_at_least_the_size_they_set():
    for name in LIGHT:
        if SIZE.match(name) and (line := name.replace("-size", "-line")) in LIGHT:
            assert _px(LIGHT[line]) >= _px(LIGHT[name]), f"{line} is tighter than {name}"


# ------------------------------------------------------------------------------- our stylesheets


def _our_css_without_tokens() -> list[pathlib.Path]:
    return [p for p in OUR_CSS if p.name != "tokens.css"]


def test_our_stylesheets_exist():
    missing = [p.name for p in OUR_CSS if not p.is_file()]
    assert not missing, f"missing stylesheets: {missing}"


NAMED_COLOUR = re.compile(
    r"(?<![\w-])(?:white|black|red|green|blue|gray|grey|orange|yellow|purple|pink|brown|silver|navy|maroon"
    r"|teal|olive|lime|aqua|fuchsia)(?![\w-])",
    re.IGNORECASE,
)


@pytest.mark.parametrize("sheet", _our_css_without_tokens(), ids=lambda p: p.name)
def test_no_stylesheet_but_the_tokens_names_a_colour(sheet):
    """A literal colour outside tokens.css is a colour that ignores the theme."""
    offenders = []
    for number, line in enumerate(
        strip_comments(sheet.read_text(encoding="utf-8")).splitlines(), 1
    ):
        values = " ".join(re.findall(r":\s*([^;{}]+)", line))
        if COLOUR_LITERAL.search(values) or NAMED_COLOUR.search(values):
            offenders.append(f"{sheet.name}:{number}: {line.strip()}")
    assert not offenders, "Use a token from tokens.css instead:\n" + "\n".join(offenders)


def test_the_colour_check_catches_every_way_of_writing_a_colour():
    for value in (
        "#fff",
        "#16233A",
        "#16233a80",
        "rgb(0 0 0 / .1)",
        "rgba(0,0,0,.1)",
        "hsl(220 10% 50%)",
        "oklch(0.5 0.1 260)",
    ):
        assert COLOUR_LITERAL.search(value), value
    assert NAMED_COLOUR.search("color: white")
    for value in (
        "var(--text)",
        "transparent",
        "currentColor",
        "inherit",
        "color-mix(in oklab, var(--a) 50%, var(--b))",
    ):
        assert not (COLOUR_LITERAL.search(value) or NAMED_COLOUR.search(value)), value
    # A class or token name that merely contains a colour word is not a colour.
    assert not NAMED_COLOUR.search("var(--status-warning-fg) .btn--sealed-greyed")


@pytest.mark.parametrize("sheet", _our_css_without_tokens(), ids=lambda p: p.name)
def test_every_font_size_is_a_step_of_the_type_scale(sheet):
    """Twenty-four font sizes is how the old stylesheet happened (plan S2)."""
    offenders = []
    for number, line in enumerate(
        strip_comments(sheet.read_text(encoding="utf-8")).splitlines(), 1
    ):
        for value in re.findall(r"font-size\s*:\s*([^;}]+)", line):
            value = value.strip()
            token = re.fullmatch(r"var\((--text-[\w-]*size[\w-]*)\)", value)
            if value != "inherit" and not (token and token.group(1) in LIGHT):
                offenders.append(f"{sheet.name}:{number}: font-size: {value}")
    assert not offenders, "Use a --text-*-size token:\n" + "\n".join(offenders)


def test_every_custom_property_our_stylesheets_use_is_defined():
    """A misspelt token is silently ignored by the browser, which then draws nothing at all."""
    defined: set[str] = set()
    used: list[tuple[str, str]] = []
    for sheet in OUR_CSS:
        css = strip_comments(sheet.read_text(encoding="utf-8"))
        defined.update(re.findall(r"(--[\w-]+)\s*:", css))
        used.extend((sheet.name, name) for name, fallback in VAR.findall(css) if not fallback)
    undefined = sorted({f"{sheet}: {name}" for sheet, name in used if name not in defined})
    assert not undefined, f"var() names nothing: {undefined}"


def test_templates_do_not_paint_colours_of_their_own():
    """Inline styles must use tokens too, or that element stays light in dark mode.

    The exported certificate is exempt: it is a self-contained file opened outside the app, with
    its own palette, and the export format does not change in this rework (S9).
    """
    offenders = []
    for template in sorted(TEMPLATES.rglob("*.html")):
        if template.parts[-2:] == ("export", "certificate.html"):
            continue
        text = template.read_text(encoding="utf-8")
        inline = re.findall(r'style="([^"]*)"', text) + re.findall(
            r"<style[^>]*>(.*?)</style>", text, re.S
        )
        for css in inline:
            if COLOUR_LITERAL.search(css) or NAMED_COLOUR.search(
                " ".join(re.findall(r":\s*([^;]+)", css))
            ):
                offenders.append(f"{template.relative_to(PROJECT_ROOT)}: {css.strip()[:80]}")
    assert not offenders, "Inline colour that ignores the theme:\n" + "\n".join(offenders)


# ------------------------------------------------------------------------------- the faces (S1)

FONTS_CSS = STATIC / "vendor" / "fonts.css"


def _font_faces() -> list[dict[str, str]]:
    faces = []
    for selector, body in rule_blocks(strip_comments(FONTS_CSS.read_text(encoding="utf-8"))):
        assert (
            selector == "@font-face"
        ), f"fonts.css should hold only @font-face rules, found {selector!r}"
        faces.append(
            {m.group(1): m.group(2).strip() for m in re.finditer(r"([\w-]+)\s*:\s*([^;]+);", body)}
        )
    return faces


def test_every_vendored_font_file_is_declared_and_every_declared_file_exists():
    declared = {
        src
        for face in _font_faces()
        for src in re.findall(r"url\(\s*['\"]?fonts/([^'\")]+)", face["src"])
    }
    on_disk = {p.name for p in (STATIC / "vendor" / "fonts").glob("*.woff2")}
    assert (
        declared == on_disk
    ), f"declared but missing: {declared - on_disk}; on disk but unused: {on_disk - declared}"


def test_every_face_swaps_in_rather_than_hiding_text():
    assert all(face.get("font-display") == "swap" for face in _font_faces())


@pytest.mark.parametrize("role", ["--font-sans", "--font-serif", "--font-mono"])
def test_each_role_leads_with_a_vendored_face_and_falls_back_to_a_generic_family(role):
    families = [f.strip().strip("\"'") for f in LIGHT[role].split(",")]
    declared = {face["font-family"].strip("\"'") for face in _font_faces()}
    assert (
        families[0] in declared
    ), f"{role} starts with {families[0]!r}, which fonts.css does not declare"
    assert families[-1] in {"sans-serif", "serif", "monospace"}, f"{role} has no generic fallback"
    assert len(families) >= 4, f"{role} should name real system fallbacks before the generic family"
