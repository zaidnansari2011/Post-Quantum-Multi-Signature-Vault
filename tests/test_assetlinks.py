"""Android App Links (rework phone-ux §10.2, N13): /.well-known/assetlinks.json.

Android opens a decision link (``https://<host>/vaults/<id>/proposals/<uuid>``) in the phone app
only when this server names the app's package and the SHA-256 fingerprint of the certificate that
signs it. The file must be public JSON at exactly that path, never a redirect; it comes from
configuration (ANDROID_APP_PACKAGE, ANDROID_CERT_SHA256), with the owner's EAS keystore as the
default, and turns off cleanly.
"""

from __future__ import annotations

import json

from config import ANDROID_APP_PACKAGE_DEFAULT, ANDROID_CERT_SHA256_DEFAULT

PATH = "/.well-known/assetlinks.json"
EAS_KEYSTORE = (
    "CE:E1:24:CB:27:03:84:3B:F6:D9:5D:56:36:76:FE:1C:"
    "28:23:40:0D:5A:4A:D8:D7:F6:E0:F4:94:EE:08:EB:AC"
)
OTHER = ":".join(["AB"] * 32)


def _statement(resp) -> dict:
    (statement,) = json.loads(resp.get_data(as_text=True))
    return statement


def test_the_default_vouches_for_the_phone_app_signed_with_the_eas_keystore(client):
    assert ANDROID_APP_PACKAGE_DEFAULT == "com.qvault.approvals"
    assert ANDROID_CERT_SHA256_DEFAULT == EAS_KEYSTORE
    resp = client.get(PATH)
    assert resp.status_code == 200
    assert resp.mimetype == "application/json"
    statement = _statement(resp)
    assert statement["relation"] == ["delegate_permission/common.handle_all_urls"]
    assert statement["target"] == {
        "namespace": "android_app",
        "package_name": "com.qvault.approvals",
        "sha256_cert_fingerprints": [EAS_KEYSTORE],
    }


def test_it_needs_no_account_and_never_redirects(client):
    # Signed out (the client fixture has no session), straight to the file: Android follows no
    # redirect and sends no cookie.
    resp = client.get(PATH, follow_redirects=False)
    assert resp.status_code == 200
    assert "Location" not in resp.headers
    assert "Set-Cookie" not in resp.headers


def test_the_fingerprints_and_package_come_from_configuration(app, client):
    app.config["ANDROID_CERT_SHA256"] = f" {EAS_KEYSTORE.lower()} , {OTHER} "
    app.config["ANDROID_APP_PACKAGE"] = "com.example.other"
    target = _statement(client.get(PATH))["target"]
    assert target["package_name"] == "com.example.other"
    assert target["sha256_cert_fingerprints"] == [EAS_KEYSTORE, OTHER]


def test_a_malformed_fingerprint_is_left_out_and_none_left_means_no_file(app, client):
    app.config["ANDROID_CERT_SHA256"] = f"not-a-fingerprint,{OTHER[:-3]},{EAS_KEYSTORE}"
    assert _statement(client.get(PATH))["target"]["sha256_cert_fingerprints"] == [EAS_KEYSTORE]
    app.config["ANDROID_CERT_SHA256"] = "not-a-fingerprint"
    assert client.get(PATH).status_code == 404


def test_an_empty_setting_turns_the_file_off(app, client):
    app.config["ANDROID_CERT_SHA256"] = ""
    assert client.get(PATH).status_code == 404
    app.config["ANDROID_CERT_SHA256"] = EAS_KEYSTORE
    app.config["ANDROID_APP_PACKAGE"] = "not a package"
    assert client.get(PATH).status_code == 404


def test_only_get_is_answered(client):
    assert client.post(PATH).status_code == 405
