"""The phone's native surface stays what the installed APK was built with (ADR-0018).

The app's runtime version is static: an over-the-air update is offered to every install at the
same ``runtimeVersion``. An update that imports a native module the installed APK lacks crashes on
launch ("Cannot find native module"), and no later update can reach that install to fix it. So a
native dependency may change only together with a bump of ``runtimeVersion``; these pin the native
modules built into runtime "2", and the rework APK's "rework-1".

The rework APK's shell (phone-ux §10.2) is pinned here too: every module it adds is loaded only
behind a check that the binary has it, its update channel comes from the build profile, its server
address from the build (staging) with the live domain as the default, its App Links, backup and
permission settings, and the brand's colours on the icon and splash.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import pytest
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
# already links through Reanimated and the rework declares at that same version (§5.9), and
# expo-file-system, which every APK already links through `expo` itself (expo 57.0.15 depends on
# expo-file-system ~57.0.5, the version the rework declares for the encrypted summary cache, §2.6;
# src/persist.ts also loads it lazily and writes nothing if the module is missing).
#
# R8 adds expo-notifications (N12, push through FCM), which brings expo-application with it. No APK
# has been built at "rework-1" yet, so the rework APK is the first to carry it.
#
# The rework APK is built once and everything after it ships over the air (phone-ux §10.2), so it
# carries every native module the rework's remaining work needs, each at the version Expo SDK 57
# pairs with it (`expo install`):
#   N5   expo-splash-screen                     the splash, light and dark (§6.1)
#   N6   @react-native-community/netinfo        the offline bar at once (§2.6)
#   N8   expo-device                            the phone's real name at enrolment (§6.2)
#   N10  expo-screen-capture                    Android's app-switcher cover with app lock (§6.1)
#   N11  expo-clipboard                         Copy, where Share stood in
#   N14  expo-sharing                           attachments (§6.5), with expo-file-system above
#   N15  expo-camera                            QR pairing and address scan (P4), unused until then
#   N16  @react-native-community/datetimepicker "Pick a day…" on New decision (§6.16)
# Not here, on purpose: N7 AsyncStorage (the encrypted summary cache is a file through
# expo-file-system, src/persist.ts) and N17 react-native-svg (the tile's icon font holds up).
NATIVE_AT_REWORK_1 = NATIVE_AT_RUNTIME_2 | {
    "react-native-worklets",
    "expo-file-system",
    "expo-notifications",
    "expo-splash-screen",
    "@react-native-community/netinfo",
    "expo-device",
    "expo-screen-capture",
    "expo-clipboard",
    "expo-sharing",
    "expo-camera",
    "@react-native-community/datetimepicker",
}
PINNED = {RUNTIME_VERSION: NATIVE_AT_RUNTIME_2, "rework-1": NATIVE_AT_REWORK_1}

# The modules no APK before the rework's carries. Only src/native/ may load them, after checking the
# binary has them (src/native/optional.ts); push.ts and persist.ts load their own, the same way.
APK_ONLY = {
    "expo-splash-screen": "src/native/",
    "@react-native-community/netinfo": "src/native/",
    "expo-device": "src/native/",
    "expo-screen-capture": "src/native/",
    "expo-clipboard": "src/native/",
    "expo-sharing": "src/native/",
    "expo-camera": "src/native/",
    "@react-native-community/datetimepicker": "src/native/",
    "expo-notifications": "src/push.ts",
}

# react-native-web is the browser renderer: it ships no native code. The community scopes hold
# native modules too (NetInfo, the date picker).
NATIVE = re.compile(
    r"^(expo|expo-.+|react-native|react-native-(?!web$).+|@react-native/.+"
    r"|@react-native-community/.+|@react-native-async-storage/.+)$"
)


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


def test_the_rework_declares_file_system_at_the_range_expo_links():
    """§2.6: the summary cache uses expo-file-system, which `expo` already depends on and links."""
    package = json.loads((MOBILE_DIR / "package.json").read_text(encoding="utf-8"))
    declared = package["dependencies"].get("expo-file-system")
    expo_package = MOBILE_DIR / "node_modules" / "expo" / "package.json"
    if declared is None or not expo_package.exists():
        return
    expo = json.loads(expo_package.read_text(encoding="utf-8"))
    assert declared == expo["dependencies"]["expo-file-system"]


def test_the_app_imports_no_clipboard_module_at_runtime_2():
    # The treasury address's Copy once imported expo-clipboard from the component file every
    # screen loads; at runtime 2 it uses React Native's own Share instead.
    if _runtime_version() != RUNTIME_VERSION:
        return
    sources = [p for p in (MOBILE_DIR / "src").rglob("*.ts*") if p.is_file()]
    assert sources
    for path in sources:
        assert "expo-clipboard" not in path.read_text(encoding="utf-8"), path


# -- The rework APK's shell (phone-ux §10.2) -----------------------------------------------------

STAGING = "https://qvault-staging.livelybeach-69506dc5.centralindia.azurecontainerapps.io"
LIVE = "https://project4.zaidansari.tech"
PROBE = MOBILE_DIR / "tools" / "native_probe.ts"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is required")


def _app() -> dict:
    return json.loads((MOBILE_DIR / "app.json").read_text(encoding="utf-8"))["expo"]


def _plugin(name: str) -> dict:
    (plugin,) = [p for p in _app()["plugins"] if isinstance(p, list) and p[0] == name]
    return plugin[1]


def _sources() -> dict:
    return {
        p.relative_to(MOBILE_DIR).as_posix(): p.read_text(encoding="utf-8")
        for p in [MOBILE_DIR / "App.tsx", *(MOBILE_DIR / "src").rglob("*.ts*")]
        if p.is_file()
    }


def test_apk_only_modules_are_loaded_only_behind_a_check_that_the_binary_has_them():
    """Expo Go, older builds and the web harness take the fallback instead of crashing on load."""
    sources = _sources()
    for module, home in APK_ONLY.items():
        for path, text in sources.items():
            static = re.search(rf"^import (?!type )[^;]*from '{re.escape(module)}'", text, re.M)
            assert static is None, (path, module)
            if f"require('{module}')" in text:
                assert path.startswith(home), (path, module)
    native = [path for path in sources if path.startswith("src/native/")]
    assert len(native) >= 6
    for path in native:
        if path == "src/native/optional.ts":
            continue
        text = sources[path]
        assert "optional<" in text, path
        assert "hasExpoModule(" in text or "hasReactNativeModule(" in text, path


def test_the_rework_apk_keeps_the_phone_s_data_on_the_phone_and_records_no_sound():
    android = _app()["android"]
    assert android["allowBackup"] is False  # N18: the summary cache never leaves in a backup
    assert android["predictiveBackGestureEnabled"] is True  # N9
    blocked = set(android["blockedPermissions"])
    # The camera scans; it never records sound. Screenshot detection and media reads are unused.
    assert {
        "android.permission.RECORD_AUDIO",
        "android.permission.READ_MEDIA_IMAGES",
        "android.permission.DETECT_SCREEN_CAPTURE",
    } <= blocked
    camera = _plugin("expo-camera")
    assert camera["recordAudioAndroid"] is False and camera["microphonePermission"] is False


def test_the_rework_apk_takes_its_update_channel_from_the_build_profile():
    """§10.2: no channel is hard-coded, so the `rework` profile's channel is the one it asks for."""
    app = _app()
    assert app["runtimeVersion"] == "rework-1"
    assert "requestHeaders" not in app["updates"]
    eas = json.loads((MOBILE_DIR / "eas.json").read_text(encoding="utf-8"))
    rework = eas["build"]["rework"]
    assert rework["channel"] == "rework"
    assert rework["distribution"] == "internal"
    assert rework["android"]["buildType"] == "apk"
    assert rework["env"]["QVAULT_API_BASE_URL"] == STAGING
    # The environment the GOOGLE_SERVICES_JSON file variable lives in (OWNER-ACTIONS §2.12).
    assert rework["environment"] == "preview"


def _config(env: dict) -> dict:
    script = (
        "const app = require('./app.json');"
        "const out = require('./app.config.js')({ config: app.expo });"
        "process.stdout.write(JSON.stringify({ api: out.extra.apiBaseUrl,"
        " gs: out.android.googleServicesFile ?? null, eas: out.extra.eas }));"
    )
    unset = ("QVAULT_API_BASE_URL", "GOOGLE_SERVICES_JSON")
    clean = {k: v for k, v in os.environ.items() if k not in unset}
    run = subprocess.run(
        ["node", "-e", script],
        cwd=str(MOBILE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**clean, **env},
        timeout=60,
    )
    if run.returncode != 0:
        return {"error": run.stderr}
    return json.loads(run.stdout)


@needs_node
def test_the_server_address_comes_from_the_build_and_defaults_to_the_live_domain():
    assert _config({})["api"] == LIVE
    staged = _config({"QVAULT_API_BASE_URL": STAGING + "/"})
    assert staged["api"] == STAGING
    assert staged["eas"]["projectId"]  # the rest of `extra` is kept
    assert _config({"GOOGLE_SERVICES_JSON": "/tmp/gs.json"})["gs"] == "/tmp/gs.json"
    for bad in (
        "http://project4.zaidansari.tech",
        "https://example.com/api",
        "project4.zaidansari.tech",
    ):
        refused = _config({"QVAULT_API_BASE_URL": bad}).get("error", "")
        assert "must be an https origin" in refused, bad


def test_app_links_cover_the_decision_page_on_both_servers_and_nothing_else():
    """N13: a decision link opens the app; an invitation link still opens the web, its handler."""
    hosts = set()
    for f in _app()["android"]["intentFilters"]:
        assert f["autoVerify"] is True and f["action"] == "VIEW"
        assert set(f["category"]) == {"BROWSABLE", "DEFAULT"}
        for d in f["data"]:
            assert d["scheme"] == "https"
            assert d["pathPattern"] == "/vaults/.*/proposals/.*"
            hosts.add(d["host"])
    assert hosts == {STAGING.removeprefix("https://"), LIVE.removeprefix("https://")}


def test_the_icon_and_splash_use_the_brand_s_colours():
    app = _app()
    assert app["android"]["adaptiveIcon"]["backgroundColor"] == "#0E1729"  # --chrome-bg
    tokens = (MOBILE_DIR / "src" / "theme" / "tokens.generated.ts").read_text(encoding="utf-8")
    light_bg, dark_bg = re.findall(r"^  bg: '(#[0-9A-F]{6})',$", tokens, re.M)[:2]
    splash = _plugin("expo-splash-screen")
    assert splash["backgroundColor"] == light_bg
    assert splash["dark"]["backgroundColor"] == dark_bg
    for path in (
        app["icon"],
        app["android"]["adaptiveIcon"]["foregroundImage"],
        app["android"]["adaptiveIcon"]["monochromeImage"],
        splash["image"],
        splash["dark"]["image"],
        _plugin("expo-notifications")["icon"],
    ):
        assert (MOBILE_DIR / path).exists(), path


@needs_node
def test_the_phone_is_named_for_real_and_offline_means_definitely_not_connected(tmp_path):
    cases = {
        "names": [
            {"platform": "android", "deviceName": "Zaid's Pixel 8", "modelName": "Pixel 8"},
            {"platform": "android", "deviceName": "  ", "modelName": "Pixel 8"},
            {"platform": "android", "deviceName": None, "modelName": None},
            {"platform": "ios"},
            {"platform": "android", "deviceName": "x" * 70 + " phone"},
        ],
        "network": [{"isConnected": True}, {"isConnected": False}, {"isConnected": None}],
    }
    source, out = tmp_path / "in.json", tmp_path / "out.json"
    source.write_text(json.dumps(cases), encoding="utf-8")
    run = subprocess.run(
        ["node", str(PROBE), str(source), str(out)],
        cwd=str(MOBILE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["names"] == ["Zaid's Pixel 8", "Pixel 8", "Android phone", "iPhone", "x" * 64]
    assert result["network"] == [True, False, True]
