"""The phone's design-system rules, as greps over ``mobile/src`` (rework phone-ux §3.1, §4, §10.1).

There is no JS test runner, so the structural rules the P1 wave sets are checked as text:

* no hex colour outside ``src/theme/`` (every colour comes from the generated tokens);
* no ``fontSize`` outside the phone's type scale, and none written outside the theme and
  ``ui/Text`` (every piece of text goes through a role);
* no ``Text``, ``TextInput``, ``Pressable`` or ``Touchable*`` imported from React Native outside
  ``ui/``, and inside ``ui/`` only where each belongs (``Text`` in ``ui/Text`` and ``ui/Icon``,
  ``TextInput`` in ``ui/inputs``, ``Pressable`` in ``ui/Touchable``), so every tappable is a
  ``ui/Touchable`` with a 48-point target and every text sets a family from the scale;
* no text is made tappable on its own (``<Text onPress>``), which would bypass ``ui/Touchable``;
* the old theme module and its names are gone.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from test_mobile_canonical import MOBILE_DIR

SRC = MOBILE_DIR / "src"
THEME = SRC / "theme"
UI = SRC / "ui"

# The phone's type scale (phone-ux §4.1): caption 13, label 12, body 16, titleSm 17, title 24,
# figure 28, decisionHero 22, decision 18, code 14.
SCALE = {12, 13, 14, 16, 17, 18, 22, 24, 28}

HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
FONT_SIZE = re.compile(r"\bfontSize\s*:\s*([0-9.]+)")
RN_IMPORT = re.compile(
    r"import\s*(?:type\s*)?\{([^}]*)\}\s*from\s*['\"](react-native|react-native-gesture-handler)['\"]",
    re.S,
)
TAPPABLE_OR_TEXT = {
    "Text",
    "TextInput",
    "Pressable",
    "TouchableOpacity",
    "TouchableHighlight",
    "TouchableWithoutFeedback",
    "TouchableNativeFeedback",
}
# Inside ui/, where each primitive may come from React Native.
ALLOWED_IN_UI = {
    "Text": {"Text.tsx", "Icon.tsx"},
    "TextInput": {"inputs.tsx"},
    "Pressable": {"Touchable.tsx"},
}


def _sources() -> list[Path]:
    files = [p for p in SRC.rglob("*.ts*") if p.is_file()]
    assert files, "mobile/src is empty"
    return files + [MOBILE_DIR / "App.tsx"]


def _imported(text: str) -> set[str]:
    names = set()
    for group, _module in RN_IMPORT.findall(text):
        for part in group.split(","):
            part = part.strip()
            # A type-only import (a ref's type) renders nothing, so it cannot bypass ui/.
            if not part or part.startswith("type "):
                continue
            names.add(part.split(" as ")[0].strip())
    return names


def test_no_hex_colour_outside_the_theme():
    offenders = []
    for path in _sources():
        if THEME in path.parents:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if HEX.search(line):
                offenders.append(f"{path.relative_to(MOBILE_DIR)}:{n}: {line.strip()}")
    assert not offenders, "colours belong in the theme:\n" + "\n".join(offenders)


def test_every_font_size_is_on_the_scale():
    for path in _sources():
        for value in FONT_SIZE.findall(path.read_text(encoding="utf-8")):
            assert float(value) in SCALE, f"{path.relative_to(MOBILE_DIR)}: fontSize {value}"


def test_font_sizes_are_set_only_by_the_theme_and_ui_text():
    allowed = {THEME / "scale.ts", UI / "Text.tsx", UI / "Icon.tsx"}
    offenders = [
        str(p.relative_to(MOBILE_DIR))
        for p in _sources()
        if p not in allowed and re.search(r"\bfontSize\b", p.read_text(encoding="utf-8"))
    ]
    assert not offenders, "set a type role on ui/Text instead: " + ", ".join(offenders)


def test_text_and_tappables_come_only_from_ui():
    offenders = []
    for path in _sources():
        names = _imported(path.read_text(encoding="utf-8")) & TAPPABLE_OR_TEXT
        if not names:
            continue
        if UI not in path.parents:
            offenders.append(f"{path.relative_to(MOBILE_DIR)} imports {sorted(names)}")
            continue
        for name in names:
            if path.name not in ALLOWED_IN_UI.get(name, set()):
                offenders.append(f"{path.relative_to(MOBILE_DIR)} imports {name}")
    assert not offenders, "\n".join(offenders)


def test_react_native_is_never_imported_whole():
    """``import * as RN`` or a default import would reach ``RN.Text`` past the check above."""
    pattern = re.compile(
        r"import\s+(?:\*\s+as\s+\w+|\w+)\s*(?:,\s*\{[^}]*\})?\s*from\s*['\"]react-native['\"]"
    )
    for path in _sources():
        assert not pattern.search(path.read_text(encoding="utf-8")), path


def test_no_text_is_made_tappable_on_its_own():
    """A ``<Text onPress>`` is a target with no 48-point area and no audit attributes."""
    pattern = re.compile(r"<Text\b[^>]*\bonPress=", re.S)
    for path in _sources():
        assert not pattern.search(path.read_text(encoding="utf-8")), path


def test_reanimated_text_is_not_a_way_around_ui_text():
    for path in _sources():
        assert "Animated.Text" not in path.read_text(encoding="utf-8"), path


def test_the_old_theme_is_gone():
    assert not (SRC / "theme.ts").exists()
    for path in _sources():
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"from ['\"][./]+theme\.ts['\"]", text), path
        for old in ("color.paper", "color.ink", "color.sealed", "color.broken", "color.waiting"):
            assert old not in text, (path, old)


@pytest.mark.parametrize("name", ["Feather", "@expo/vector-icons"])
def test_the_stock_icon_family_is_gone(name):
    """The tile's own icon set replaces Feather (§2.2)."""
    for path in _sources():
        assert name not in path.read_text(encoding="utf-8"), path


def test_every_screen_and_component_styles_through_make_styles():
    """No module-level StyleSheet: styles are built per theme, so dark mode reaches all of them."""
    for path in _sources():
        text = path.read_text(encoding="utf-8")
        if THEME in path.parents:
            continue
        assert "StyleSheet.create(" not in text, path


def test_no_native_alert_anywhere():
    """Every confirmation is a sheet (phone-ux §2.3, §6.15): no `Alert.alert`, no `Alert` import."""
    for path in _sources():
        text = path.read_text(encoding="utf-8")
        assert "Alert.alert" not in text, path
        assert "Alert" not in _imported(text), path
