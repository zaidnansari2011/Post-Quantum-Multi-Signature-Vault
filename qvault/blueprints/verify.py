"""Public verification: check an exported decision without an account.

Deliberately reachable by anyone, with no login and no CSRF token, because the people this page
is for are outside the organisation — an auditor, a counterparty, a regulator. Requiring them to
register would reintroduce exactly the dependency on us that the export exists to remove.

Two honesty constraints shape the page:

* **This server is not a trusted verifier of its own exports.** It runs the same code a stranger
  would, but a compromised deployment could return "Verified" for anything. The page says so and
  points at the offline verifier and the CLI, which is where the claim actually lives.
* **The log fingerprint published here is not a trust root.** Taking the expected key from the
  same server that produced the bundle proves nothing. It is shown so a reader can compare it
  against a value obtained elsewhere, and the page says that rather than implying otherwise.

There is no CSRF token because there is no state to protect: nothing here reads a session or
writes anything. A side effect worth having is that ``curl -F bundle=@decision.json .../verify``
works, so this doubles as an API.
"""

from __future__ import annotations

from flask import Blueprint, current_app, render_template, request

from qvault.verify import BundleFormatError, load_bundle, verify_bundle

bp = Blueprint("verify", __name__, url_prefix="/verify")

MAX_BUNDLE_BYTES = 4 * 1024 * 1024


def _read_submission() -> tuple[object | None, str | None]:
    """Return ``(bundle, error)`` from either an upload or a paste.

    Every artefact the export produces is accepted -- the self-verifying .html record, the .zip
    package, and the bare .json. The reasoning, and the history of getting this wrong, lives in
    ``qvault.verify.reader``: whatever the product hands somebody has to be what this page takes.
    """
    upload = request.files.get("bundle")
    if upload is not None and upload.filename:
        raw = upload.read(MAX_BUNDLE_BYTES + 1)
        if len(raw) > MAX_BUNDLE_BYTES:
            return None, f"That file is larger than {MAX_BUNDLE_BYTES // 1024 // 1024} MB."
    else:
        raw = (request.form.get("bundle_text") or "").strip().encode("utf-8")

    if not raw.strip():
        return None, "Choose an exported decision file, or paste its contents."

    try:
        return load_bundle(raw), None
    except BundleFormatError as exc:
        # The reader already phrases these for a person; this only sentence-cases them.
        message = str(exc)
        return None, message[:1].upper() + message[1:].rstrip(".") + "."


def _wants_json() -> bool:
    return (
        request.args.get("format") == "json" or request.accept_mimetypes.best == "application/json"
    )


@bp.route("/", methods=["GET", "POST"])
def index():
    report = None
    error = None

    if request.method == "POST":
        bundle, error = _read_submission()
        if bundle is not None:
            report = verify_bundle(
                bundle,
                registry=current_app.extensions["crypto"],
                expect_log=(request.form.get("expect_log") or "").strip() or None,
                expect_witness=(request.form.get("expect_witness") or "").strip() or None,
            )

    if _wants_json():
        from flask import jsonify

        if error:
            return jsonify({"ok": False, "error": error}), 400
        return jsonify(report.as_dict() if report else {"ok": False, "error": "no bundle"}), (
            200 if report and report.ok else 400
        )

    return render_template(
        "verify/index.html",
        report=report,
        error=error,
        expect_log=request.form.get("expect_log", ""),
        expect_witness=request.form.get("expect_witness", ""),
    )
