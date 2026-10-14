"""Account settings: Profile, Notifications (``notifications.preferences``) and Security.

The password form is the reason this module is careful. Changing a password re-encrypts the
private key material it protects (``key_service.change_password``), so a failure here is not a
failed form submission — it is a user who can still log in and can no longer sign anything. Every
path below either completes that operation or leaves the account exactly as it was.
"""

from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required, logout_user
from flask_wtf import FlaskForm
from markupsafe import Markup

from qvault.extensions import db
from qvault.forms import ChangePasswordForm, IssueKitForm, ProfileForm
from qvault.models.config_models import AlgorithmConfig
from qvault.models.device import Device
from qvault.services import (
    auth_service,
    key_service,
    recovery_kit,
    recovery_service,
    treasury_service,
)
from qvault.services.key_service import KeyUnlockError, PasswordLockedError
from qvault.services.treasury_service import LinkRefused


class SigningChoiceForm(FlaskForm):
    """The choice itself is a radio in the template; this carries the CSRF token."""


bp = Blueprint("account", __name__, url_prefix="/account")


def _render(profile_form=None, password_form=None, tab="profile"):
    key = key_service.active_signing_key(current_user)
    on_chain = bool(current_app.config.get("ONCHAIN_EXECUTION_ENABLED"))
    phones = []
    if on_chain:
        for device_key in key_service.device_signing_keys(current_user):
            phone = Device.query.filter_by(key_id=device_key.id).one_or_none()
            if phone is not None and phone.is_usable():
                phones.append((phone, device_key))
    return render_template(
        "account/security.html" if tab == "security" else "account/index.html",
        tab=tab,
        profile_form=profile_form or ProfileForm(display_name=current_user.display_name),
        password_form=password_form or ChangePasswordForm(),
        key=key,
        retired_keys=key_service.retired_signing_keys(current_user),
        active_alg=AlgorithmConfig.current().active_signature_alg,
        treasuries_on=on_chain,
        key_choice=treasury_service.key_choice(current_user) if on_chain else None,
        phones=phones,
        # Every phone this account has paired, usable or not, for the Security tab's list.
        devices=Device.query.filter_by(owner_id=current_user.id)
        .order_by(Device.created_at.desc())
        .all(),
        choice_form=SigningChoiceForm(),
        # The Recovery Kit (plan R9): what there is, and the form that makes or replaces one.
        kit_state=recovery_service.kit_state(current_user),
        kit_short_id=recovery_kit.short_id,
        kit_form=IssueKitForm(),
        open_recoveries=recovery_service.banners_for(current_user),
        **_phone_facts(),
    )


@bp.post("/signing-choice")
@login_required
def set_signing_choice():
    """Choose which of your keys a treasury registers for you (plan D37).

    It changes nothing already on chain: a treasury holds the key it was given until its signers
    approve a reconfiguration.
    """
    form = SigningChoiceForm()
    if not form.validate_on_submit():
        flash("That form had expired. Try again.", "error")
        return redirect(url_for("account.security"))
    choice = (request.form.get("choice") or "").strip()
    device_key = None
    custody = "password"
    if choice.startswith("device:"):
        custody = "device"
        wanted = choice.split(":", 1)[1]
        device_key = (
            key_service.device_key_of(current_user, int(wanted)) if wanted.isdigit() else None
        )
    try:
        treasury_service.set_key_choice(current_user, custody=custody, device_key=device_key)
        flash("Saved. It applies the next time a treasury is created or changed.", "success")
    except LinkRefused as exc:
        for problem in exc.problems:
            flash(f"{problem[:1].upper()}{problem[1:]}.", "error")
    return redirect(url_for("account.security"))


@bp.get("/")
@login_required
def index():
    return _render()


@bp.get("/security")
@login_required
def security():
    """Keys, phones, the treasury key choice, the password and what recovery there is (R2)."""
    return _render(tab="security")


@bp.post("/profile")
@login_required
def update_profile():
    form = ProfileForm()
    if not form.validate_on_submit():
        return _render(profile_form=form)
    auth_service.update_display_name(current_user, form.display_name.data)
    flash("Profile updated.", "success")
    return redirect(url_for("account.index"))


@bp.post("/password")
@login_required
def change_password():
    form = ChangePasswordForm()
    if not form.validate_on_submit():
        return _render(password_form=form, tab="security")

    try:
        count = key_service.change_password(
            current_user, form.current_password.data, form.new_password.data
        )
    except PasswordLockedError as exc:
        form.current_password.errors.append(str(exc))
        return _render(password_form=form, tab="security")
    except KeyUnlockError:
        # Deliberately attached to the field rather than flashed: this is a form error about one
        # input, and the page should come back with the rest of what they typed intact.
        form.current_password.errors.append("That is not your current password.")
        return _render(password_form=form, tab="security")

    # Log them out. The session was established under the old password and this is the moment a
    # user expects to re-authenticate; leaving it live would also mean a stolen session survives
    # the exact action taken to recover from a compromise.
    logout_user()
    flash(
        f"Password changed and {count} key{'' if count == 1 else 's'} re-encrypted. "
        "Please sign in again.",
        "success",
    )
    return redirect(url_for("auth.login"))


# -- phones: pairing by a code, and removing one (A10, pairing-design §3.3, §3.7) -----------------


def _phone_facts() -> dict:
    """What the Phones panel needs beyond the list (A10): whether pairing by code is set up here,
    whether anyone else would be told of a new phone, which phone's Remove form to open, and the
    treasuries each phone's key holds a seat on."""
    from qvault.models.treasury import Treasury, TreasurySigner
    from qvault.services import delivery_service, pairing_service

    devices = Device.query.filter_by(owner_id=current_user.id).all()
    usable = [d for d in devices if d.is_usable()]
    seats: dict[int, list[str]] = {}
    for d in usable:
        rows = (
            Treasury.query.join(TreasurySigner, TreasurySigner.treasury_id == Treasury.id)
            .filter(TreasurySigner.key_id == d.key_id, Treasury.status == "linked")
            .all()
        )
        if rows:
            seats[d.id] = sorted({row.vault.name for row in rows})
    return {
        "pairing_available": pairing_service.available(),
        "nobody_else_told": not delivery_service.channel_ready("email") and not usable,
        "open_remove": request.args.get("remove", type=int),
        "device_seats": seats,
    }


def _no_store(response):
    """A page that draws a pairing code must never be cached, by the browser or anything between."""
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.post("/devices/pair")
@login_required
def pair_start():
    """Show a new pairing code for this web session (cancels this account's previous one)."""
    from qvault.services import pairing_service
    from qvault.services.pairing_service import PairingError

    try:
        pairing = pairing_service.create(current_user)
    except PairingError as exc:
        flash(exc.message, "error")
        return redirect(url_for("account.security"))
    return redirect(url_for("account.pair_page", pairing_uuid=pairing.uuid))


def _pairing_or_404(pairing_uuid: str):
    from qvault.services import pairing_service

    pairing = pairing_service.for_session(current_user, pairing_uuid)
    if pairing is None:
        abort(404)
    return pairing


@bp.get("/devices/pair/<pairing_uuid>")
@login_required
def pair_page(pairing_uuid: str):
    """The code while it waits for a phone, the confirm card once one has claimed it, and the
    outcome after. Only the web session that showed the code can see it."""
    from qvault.services import pairing_service

    pairing = _pairing_or_404(pairing_uuid)
    view = pairing_service.view(pairing)
    if request.accept_mimetypes.best == "application/json":
        return _no_store(jsonify(view))
    svg = pairing_service.qr_svg(pairing) if view["state"] == "open" else None
    response = make_response(
        render_template(
            "account/pair.html",
            pairing=pairing,
            view=view,
            qr_svg=Markup(svg) if svg else None,
        )
    )
    return _no_store(response)


@bp.post("/devices/pair/<pairing_uuid>/confirm")
@login_required
def pair_confirm(pairing_uuid: str):
    """Add the phone: the key shown, the code from that phone, and the password (§3.5)."""
    from qvault.services import pairing_service
    from qvault.services.pairing_service import PairingError

    pairing = _pairing_or_404(pairing_uuid)
    try:
        device = pairing_service.confirm(
            current_user,
            pairing,
            public_key_sha256=request.form.get("public_key_sha256"),
            check_code=request.form.get("check_code"),
            password=request.form.get("password"),
        )
    except PasswordLockedError as exc:
        flash(str(exc), "error")
        return redirect(url_for("account.pair_page", pairing_uuid=pairing_uuid))
    except PairingError as exc:
        flash(exc.message, "error")
        return redirect(url_for("account.pair_page", pairing_uuid=pairing_uuid))
    flash(f"{device.name} was added. It can approve for you from now on.", "success")
    return redirect(url_for("account.security"))


@bp.post("/devices/pair/<pairing_uuid>/decline")
@login_required
def pair_decline(pairing_uuid: str):
    """"My phone didn't scan this": nothing is added, and it is logged and told (⚑9)."""
    from qvault.services import pairing_service
    from qvault.services.pairing_service import PairingError

    pairing = _pairing_or_404(pairing_uuid)
    try:
        pairing_service.decline(current_user, pairing)
    except PairingError as exc:
        flash(exc.message, "error")
    return redirect(url_for("account.pair_page", pairing_uuid=pairing_uuid))


@bp.post("/devices/pair/<pairing_uuid>/cancel")
@login_required
def pair_cancel(pairing_uuid: str):
    from qvault.services import pairing_service

    pairing_service.cancel(_pairing_or_404(pairing_uuid))
    flash("The pairing code was cancelled. Nothing was added.", "info")
    return redirect(url_for("account.security"))


@bp.post("/devices/<int:device_id>/remove")
@login_required
def remove_device(device_id: int):
    """Remove a phone from the web, with the password (⚑4; limited and a password proof, §3.7)."""
    from qvault.services import device_service
    from qvault.services.device_service import DeviceError

    device = db.session.get(Device, device_id)
    try:
        removed = device_service.remove_with_password(
            current_user, device, request.form.get("password") or ""
        )
    except LookupError:
        abort(404)
    except DeviceError as exc:
        flash(exc.message, "error")
        return redirect(url_for("account.security"))
    except PasswordLockedError as exc:
        flash(str(exc), "error")
        return redirect(url_for("account.security", remove=device_id))
    except KeyUnlockError:
        db.session.rollback()
        flash("That isn't your password. Nothing was removed.", "error")
        return redirect(url_for("account.security", remove=device_id))
    flash(f"{removed.name} was removed. It can no longer approve for you.", "success")
    return redirect(url_for("account.security"))
