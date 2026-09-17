"""Account settings — profile, password, and this user's signing keys.

The password form is the reason this module is careful. Changing a password re-encrypts the
private key material it protects (``key_service.change_password``), so a failure here is not a
failed form submission — it is a user who can still log in and can no longer sign anything. Every
path below either completes that operation or leaves the account exactly as it was.
"""

from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, logout_user
from flask_wtf import FlaskForm

from qvault.forms import ChangePasswordForm, ProfileForm
from qvault.models.config_models import AlgorithmConfig
from qvault.models.device import Device
from qvault.services import auth_service, key_service, treasury_service
from qvault.services.key_service import KeyUnlockError
from qvault.services.treasury_service import LinkRefused


class SigningChoiceForm(FlaskForm):
    """The choice itself is a radio in the template; this carries the CSRF token."""


bp = Blueprint("account", __name__, url_prefix="/account")


def _render(profile_form=None, password_form=None):
    key = key_service.active_signing_key(current_user)
    on_chain = bool(current_app.config.get("ONCHAIN_EXECUTION_ENABLED"))
    phones = []
    if on_chain:
        for device_key in key_service.device_signing_keys(current_user):
            phone = Device.query.filter_by(key_id=device_key.id).one_or_none()
            if phone is not None and phone.is_usable():
                phones.append((phone, device_key))
    return render_template(
        "account/index.html",
        profile_form=profile_form or ProfileForm(display_name=current_user.display_name),
        password_form=password_form or ChangePasswordForm(),
        key=key,
        retired_keys=key_service.retired_signing_keys(current_user),
        active_alg=AlgorithmConfig.current().active_signature_alg,
        treasuries_on=on_chain,
        key_choice=treasury_service.key_choice(current_user) if on_chain else None,
        phones=phones,
        choice_form=SigningChoiceForm(),
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
        return redirect(url_for("account.index"))
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
    return redirect(url_for("account.index"))


@bp.get("/")
@login_required
def index():
    return _render()


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
        return _render(password_form=form)

    try:
        count = key_service.change_password(
            current_user, form.current_password.data, form.new_password.data
        )
    except KeyUnlockError:
        # Deliberately attached to the field rather than flashed: this is a form error about one
        # input, and the page should come back with the rest of what they typed intact.
        form.current_password.errors.append("That is not your current password.")
        return _render(password_form=form)

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
