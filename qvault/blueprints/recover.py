"""Account recovery pages (plan R9, docs/plans/saas-rework/recovery-design.md): Phase 1, the kit.

- ``/recover``: email, kit code and a new password. The one address the kit says it may be typed
  at. Signed in or out, rate limited per address (``rate_limit``, bucket ``recover``).
- ``/recover/status``: the browser that started a request sees when it takes effect, and can
  cancel it, through an HttpOnly, SameSite=Strict cookie scoped to ``/recover``.
- ``/recover/requests/<uuid>/cancel``: Cancel on Home's banner, for the person and for the people
  watching over them (``recovery_service.watchers``); anyone else gets a 404.
- The kit's own page (``kit_page``), drawn in answer to the POST that made the kit: at sign-up,
  or on the Security page. It is never stored and cannot be fetched again; ``/account/recovery-kit``
  confirms the last group typed back, or takes "Do this later".

Every form posts with its CSRF token; nothing here redirects to a place the request names.
"""

from __future__ import annotations

import hmac
from datetime import UTC, datetime

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from qvault.crypto import kit_code
from qvault.extensions import db
from qvault.forms import IssueKitForm, KitConfirmForm, KitLaterForm, RecoverKitForm
from qvault.models.recovery import RecoveryKit
from qvault.security import master_key
from qvault.services import delivery_service, recovery_kit, recovery_service
from qvault.services.key_service import KeyUnlockError, PasswordLockedError
from qvault.services.recovery_service import RecoveryRefused

bp = Blueprint("recover", __name__)

#: Never cached, never in a referrer, never indexed: these pages carry a code or a request's state.
_PRIVATE = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex",
}


def _private(response):
    for name, value in _PRIVATE.items():
        response.headers[name] = value
    return response


def site_address() -> str:
    """The address the kit prints: the configured public address, or this request's own."""
    base = delivery_service.public_base_url()
    if base is not None:
        return base + url_for("recover.kit")
    return url_for("recover.kit", _external=True)


# --------------------------------------------------------------------------------------------
# Using a kit


@bp.route("/recover", methods=["GET", "POST"])
def kit():
    form = RecoverKitForm()
    refusal = None
    status = 200
    if request.method == "POST":
        status = 400
        if form.validate_on_submit():
            try:
                started = recovery_service.start_with_kit(
                    form.email.data, form.code.data, form.password.data
                )
            except kit_code.KitCodeError as exc:
                form.code.errors = [*form.code.errors, str(exc)]
            except RecoveryRefused as exc:
                refusal = exc.message
            else:
                response = redirect(url_for("recover.status"))
                response.set_cookie(
                    recovery_service.STATUS_COOKIE,
                    started.status_token,
                    max_age=int(recovery_service.KIT_WAIT.total_seconds()) + 30 * 24 * 3600,
                    path=recovery_service.STATUS_PATH,
                    # As the theme cookie: behind a proxy that ends TLS, is_secure reads False.
                    secure=request.is_secure
                    or bool(current_app.config.get("SESSION_COOKIE_SECURE", False)),
                    httponly=True,
                    samesite="Strict",
                )
                return _private(response)
    # The code is never written back into the page, whatever happened to it.
    form.code.data = ""
    body = render_template("recover/kit.html", form=form, refusal=refusal, address=site_address())
    return _private(make_response(body, status))


def _status_token() -> str | None:
    return request.cookies.get(recovery_service.STATUS_COOKIE)


@bp.get("/recover/status")
def status():
    """What became of the request this browser started. Completes it, if its time has come."""
    found = recovery_service.request_for_status_token(_status_token())
    if found is not None:
        found = recovery_service.settle(found)
    body = render_template(
        "recover/status.html",
        req=found,
        now=datetime.now(UTC),
    )
    return _private(make_response(body))


@bp.post("/recover/status/cancel")
def status_cancel():
    if not _csrf_ok():
        abort(400)
    try:
        recovery_service.cancel_by_status_token(_status_token())
    except LookupError:
        abort(404)
    except RecoveryRefused as exc:
        flash(exc.message, "error")
    return _private(redirect(url_for("recover.status")))


def _csrf_ok() -> bool:
    """A Cancel button posts its CSRF token and nothing else."""
    if not current_app.config.get("WTF_CSRF_ENABLED", True):
        return True
    from flask_wtf.csrf import ValidationError, validate_csrf

    try:
        validate_csrf(request.form.get("csrf_token"))
    except ValidationError:
        return False
    return True


@bp.post("/recover/requests/<request_uuid>/cancel")
@login_required
def cancel(request_uuid: str):
    """Cancel on Home: the person (which burns the kit), an owner or admin of their workspace, or
    a fellow approver (which does not). A request anyone else names does not exist for them."""
    if not _csrf_ok():
        abort(400)
    try:
        ended = recovery_service.cancel_as(current_user, request_uuid)
    except LookupError:
        abort(404)
    except RecoveryRefused as exc:
        flash(exc.message, "error")
    else:
        if ended.user_id == current_user.id:
            flash(
                "Recovery cancelled. Your Recovery Kit no longer works, because someone else had "
                "it: make a new one on the Security page.",
                "persist",
            )
        else:
            flash(
                f"Recovery cancelled. Nothing about {ended.user.display_name}'s account changed.",
                "success",
            )
    return redirect(url_for("core.index"))


# --------------------------------------------------------------------------------------------
# Showing a kit, once


def kit_page(issued: recovery_kit.IssuedKit, *, after_signup: bool, status: int = 200):
    """The kit, drawn in answer to the request that made it (design §5.4). The code exists only
    in this response: ``no-store``, no referrer, and nothing that could fetch it again."""
    kit = issued.kit
    groups = kit_code.groups(issued.code)
    body = render_template(
        "recover/kit_issued.html",
        kit=kit,
        groups=groups,
        short_id=recovery_kit.short_id(kit),
        address=site_address(),
        email=kit.user.email,
        made=kit.created_at,
        confirm_form=KitConfirmForm(
            kit_uuid=kit.kit_uuid,
            tag=master_key.kit_confirm_tag(kit.kit_uuid, groups[-1]).hex(),
        ),
        later_form=KitLaterForm(kit_uuid=kit.kit_uuid),
        after_signup=after_signup,
        treasury_signer=bool(recovery_kit.seat_key_ids(kit.user)),
    )
    return _private(make_response(body, status))


def _own_unconfirmed_kit(kit_uuid: str | None) -> RecoveryKit | None:
    if not kit_uuid or len(kit_uuid) > 36:
        return None
    return RecoveryKit.query.filter_by(
        kit_uuid=kit_uuid, user_id=current_user.id, state="active", confirmed_at=None
    ).one_or_none()


@bp.post("/account/recovery-kit")
@login_required
def issue():
    """Make a kit from the Security page, or replace the one there is (password re-entered)."""
    form = IssueKitForm()
    if not form.validate_on_submit():
        flash("Enter your password to make a Recovery Kit.", "error")
        return redirect(url_for("account.security") + "#recovery")
    try:
        issued = recovery_kit.issue(current_user, form.password.data)
    except PasswordLockedError as exc:
        flash(str(exc), "error")
    except KeyUnlockError:
        flash("That is not your password, so no Recovery Kit was made.", "error")
    except recovery_kit.KitError as exc:
        flash(f"No Recovery Kit was made: {exc}.", "error")
    else:
        return kit_page(issued, after_signup=False)
    return redirect(url_for("account.security") + "#recovery")


def _normalise_group(typed: str | None) -> str:
    cleaned = []
    for ch in (typed or "").upper():
        if ch in " -":
            continue
        cleaned.append({"I": "1", "L": "1", "O": "0"}.get(ch, ch))
    return "".join(cleaned)


@bp.post("/account/recovery-kit/confirm")
@login_required
def confirm():
    """The last group typed back. Checked against the tag the kit page carried, so the server
    neither sees the code again nor keeps anything made from it."""
    form = KitConfirmForm()
    after = url_for("core.index")
    if not form.validate_on_submit():
        flash("Type the last group of your Recovery Kit's code.", "error")
        return redirect(after)
    kit = _own_unconfirmed_kit(form.kit_uuid.data)
    typed = _normalise_group(form.last_group.data)
    try:
        tag = bytes.fromhex(form.tag.data or "")
    except ValueError:
        tag = b""
    if kit is None:
        flash("That Recovery Kit is no longer the one to confirm.", "error")
        return redirect(after)
    if (
        len(typed) != kit_code.GROUP
        or not all(ch in kit_code.ALPHABET for ch in typed)
        or not hmac.compare_digest(master_key.kit_confirm_tag(kit.kit_uuid, typed), tag)
    ):
        flash(
            "That isn't the last group of your Recovery Kit, so it isn't marked as saved. If you "
            "didn't keep the kit, make a new one on the Security page.",
            "error",
        )
        return redirect(url_for("account.security") + "#recovery")
    kit.confirmed_at = datetime.now(UTC)
    db.session.commit()
    flash("Recovery Kit saved. Keep it where you keep your passport.", "success")
    return redirect(after)


@bp.post("/account/recovery-kit/later")
@login_required
def later():
    """ "Do this later": the kit just shown stops working (it may have been seen, and may not have
    been kept), and Home and Security keep asking for one."""
    form = KitLaterForm()
    if not form.validate_on_submit():
        abort(400)
    kit = _own_unconfirmed_kit(form.kit_uuid.data)
    if kit is not None:
        recovery_kit.revoke(kit, "not_saved")
        db.session.commit()
    flash(
        "No Recovery Kit for now. Make one on the Security page: without it, a forgotten "
        "password can't give you back this signing key.",
        "persist",
    )
    return redirect(url_for("core.index"))
