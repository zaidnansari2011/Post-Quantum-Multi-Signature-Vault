"""Authentication routes: register, login, logout, and the user dashboard."""

from __future__ import annotations

from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from qvault.forms import LoginForm, RegisterForm, ReissueKeyForm
from qvault.models.config_models import AlgorithmConfig
from qvault.services import auth_service, key_service
from qvault.services.auth_service import EmailTakenError
from qvault.services.key_service import KeyUnlockError, active_signing_key

bp = Blueprint("auth", __name__)


def _safe_next(target: str | None) -> str | None:
    """Only allow same-site relative redirects (prevents open-redirect via ?next=)."""
    if not target or "\\" in target:
        # Reject backslashes: browsers normalise "\" to "/" in a Location header, so
        # "/\evil.com" would become the protocol-relative "//evil.com" (off-site).
        return None
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith("/") or target.startswith("//"):
        return None
    return target


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
        return redirect(_safe_next(request.args.get("next")) or url_for("auth.dashboard"))
    return render_template("login.html", form=form)


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("core.index"))


@bp.get("/dashboard")
@login_required
def dashboard():
    key = active_signing_key(current_user)
    active_alg = AlgorithmConfig.current().active_signature_alg
    return render_template(
        "dashboard.html", key=key, active_alg=active_alg, reissue_form=ReissueKeyForm()
    )


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
        flash(
            f"Signing key re-issued under {key.alg_id}. Your previous key is retired but still "
            "verifies every signature it made.",
            "success",
        )
    return redirect(url_for("auth.dashboard"))
