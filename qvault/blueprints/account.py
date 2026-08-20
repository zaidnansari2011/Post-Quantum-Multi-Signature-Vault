"""Account settings — profile, password, and this user's signing keys.

The password form is the reason this module is careful. Changing a password re-encrypts the
private key material it protects (``key_service.change_password``), so a failure here is not a
failed form submission — it is a user who can still log in and can no longer sign anything. Every
path below either completes that operation or leaves the account exactly as it was.
"""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user, login_required, logout_user

from qvault.forms import ChangePasswordForm, ProfileForm
from qvault.models.config_models import AlgorithmConfig
from qvault.services import auth_service, key_service
from qvault.services.key_service import KeyUnlockError

bp = Blueprint("account", __name__, url_prefix="/account")


def _render(profile_form=None, password_form=None):
    key = key_service.active_signing_key(current_user)
    return render_template(
        "account/index.html",
        profile_form=profile_form or ProfileForm(display_name=current_user.display_name),
        password_form=password_form or ChangePasswordForm(),
        key=key,
        retired_keys=key_service.retired_signing_keys(current_user),
        active_alg=AlgorithmConfig.current().active_signature_alg,
    )


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
