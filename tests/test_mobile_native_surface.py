"""The phone's native surface stays what the installed APK was built with (ADR-0018).

The app's runtime version is static: an over-the-air update is offered to every install at the
same ``runtimeVersion``. An update that imports a native module the installed APK lacks crashes on
launch ("Cannot find native module"), and no later update can reach that install to fix it. So a
native dependency may change only together with a bump of ``runtimeVersion``; these pin the native
modules built into runtime "2".
"""

from __future__ import annotations

import json
import re

from test_mobile_canonical import MOBILE_DIR

RUNTIME_VERSION = "2"

# The modules with native code in the runtime-2 APK. Changing this set needs a new
# runtimeVersion in app.json and a new APK, in the same change.
NATIVE_AT_RUNTIME_2 = {
    "expo",
    "expo-constants",
    "expo-crypto",
    "expo-font",
    "expo-haptics",
    "expo-local-authentication",
    "expo-secure-store",
    "expo-status-bar",
    "expo-system-ui",
    "expo-updates",
    "react-native",
    "react-native-gesture-handler",
    "react-native-reanimated",
    "react-native-safe-area-context",
    "react-native-screens",
}

# The rework's runtime (phone-ux §10.2, N2): its own runtimeVersion, so neither branch's
# over-the-air update can land on the other's APK. Until the rework APK's native additions land
# (N5 to N18), it carries runtime 2's modules plus react-native-worklets, which the runtime-2 APK
# already links through Reanimated and the rework declares at that same version (§5.9).
NATIVE_AT_REWORK_1 = NATIVE_AT_RUNTIME_2 | {"react-native-worklets"}
PINNED = {RUNTIME_VERSION: NATIVE_AT_RUNTIME_2, "rework-1": NATIVE_AT_REWORK_1}

# react-native-web is the browser renderer: it ships no native code.
NATIVE = re.compile(r"^(expo|expo-.+|react-native|react-native-(?!web$).+|@react-native/.+)$")


def _native_dependencies() -> set[str]:
    package = json.loads((MOBILE_DIR / "package.json").read_text(encoding="utf-8"))
    return {name for name in package["dependencies"] if NATIVE.match(name)}


def _runtime_version() -> str:
    app = json.loads((MOBILE_DIR / "app.json").read_text(encoding="utf-8"))
    return app["expo"]["runtimeVersion"]


def test_a_native_module_is_added_or_removed_only_with_a_new_runtime_version():
    runtime = _runtime_version()
    if runtime not in PINNED:
        return  # A bump: the new APK carries whatever native surface ships with it.
    assert _native_dependencies() == PINNED[runtime]


def test_the_rework_declares_worklets_at_the_version_the_apk_links():
    """§5.9: declared at the exact version the runtime-2 APK already contains (0.10.4)."""
    package = json.loads((MOBILE_DIR / "package.json").read_text(encoding="utf-8"))
    if "react-native-worklets" in package["dependencies"]:
        assert package["dependencies"]["react-native-worklets"] == "0.10.4"


def test_the_app_imports_no_clipboard_module_at_runtime_2():
    # The treasury address's Copy once imported expo-clipboard from the component file every
    # screen loads; it uses React Native's own Share instead.
    sources = [p for p in (MOBILE_DIR / "src").rglob("*.ts*") if p.is_file()]
    assert sources
    for path in sources:
        assert "expo-clipboard" not in path.read_text(encoding="utf-8"), path
