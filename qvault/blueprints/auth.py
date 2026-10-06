"""Authentication routes: register, login, logout, and the user dashboard."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from qvault.forms import LoginForm, RegisterForm, ReissueKeyForm
from qvault.security.redirects import safe_next
from qvault.services import auth_service, key_service
from qvault.services.auth_service import EmailTakenError
from qvault.services.key_service import KeyUnlockError

bp = Blueprint("auth", __name__)


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("auth.dashboard"))
    form = RegisterForm()
    if form.validate_on_submit():
        try:
            user = auth_service.register_user(
                form.email.data, form.display_name.data, form.password.data
            )
        except EmailTakenError:
            flash("That email is already registered.", "danger")
            return render_template("register.html", form=form)
        login_user(user)
        flash("Account created — your post-quantum signing keypair has been generated.", "success")
        return redirect(url_for("auth.dashboard"))
    return render_template("register.html", form=form)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("auth.dashboard"))
    form = LoginForm()
    if form.validate_on_submit():
        user = auth_service.authenticate(form.email.data, form.password.data)
        if user is None:
            flash("Invalid email or password.", "danger")
            return render_template("login.html", form=form)
        login_user(user)
        return redirect(safe_next(request.args.get("next")) or url_for("auth.dashboard"))
    return render_template("login.html", form=form)


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    # An invitation for another address offers to sign out and come back to it.
    return redirect(safe_next(request.form.get("next")) or url_for("core.index"))


@bp.get("/dashboard")
@login_required
def dashboard():
    """Kept as a redirect. "Dashboard" was a page about the reader's own signing key, which is an
    account setting; the name now belongs to Home, which is a work queue. Old links and bookmarks
    still land somewhere sensible."""
    return redirect(url_for("account.index"))


@bp.post("/keys/reissue")
@login_required
def reissue_key():
    form = ReissueKeyForm()
    if not form.validate_on_submit():
        flash("Enter your password to re-issue your signing key.", "danger")
        return redirect(url_for("auth.dashboard"))
    try:
        key = key_service.reissue_signing_key(current_user, form.password.data)
    except KeyUnlockError:
        flash("Incorrect password — your signing key was not re-issued.", "danger")
    else:
        # "persist": which algorithm the new key uses, and what became of the old one, are worth
        # more than the few seconds a toast stays up.
        flash(
            f"Signing key re-issued under {key.alg_id}. Your previous key is retired but still "
            "verifies every signature it made.",
            "persist",
        )
    return redirect(url_for("auth.dashboard"))
