"""Authentication routes: sign-up, sign-in, sign-out, the forgot-password page, and old links.

**Signing up creates a workspace** (plan S21). ``/register`` makes a new account and a new
workspace it owns, through ``auth_service.sign_up``, and reads nothing from the request about
which workspace or role: the way into someone else's workspace is their invitation link
(``/invite/<token>``, in ``blueprints/workspace.py``).

**The forgot-password page resets nothing.** The password also unwraps the signing key, so a
reset would lose that key (plan S18). The page says what cannot be done and what can, and has no
form: there is no route here that pretends to recover an account.
"""

from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from qvault.forms import LoginForm, RegisterForm, ReissueKeyForm
from qvault.security.redirects import safe_next
from qvault.services import auth_service, key_service, workspace_service
from qvault.services.auth_service import EmailTakenError
from qvault.services.key_service import KeyUnlockError
from qvault.services.workspace_service import WorkspaceError

bp = Blueprint("auth", __name__)


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("auth.dashboard"))
    form = RegisterForm()
    if form.validate_on_submit():
        try:
            user = auth_service.sign_up(
                form.email.data,
                form.display_name.data,
                form.password.data,
                form.workspace_name.data,
            )
        except EmailTakenError:
            # On the field, not in a banner: it is marked invalid, described, and takes the focus.
            # The same words as before workspaces: sign-up reveals no more than it always did.
            form.email.errors = [*form.email.errors, "That email is already registered."]
            return render_template("register.html", form=form)
        except WorkspaceError as exc:
            form.workspace_name.errors = [*form.workspace_name.errors, exc.message]
            return render_template("register.html", form=form), 400
        login_user(user)
        workspace = workspace_service.current_workspace(user)
        flash(
            f"{workspace.name} is ready. Your account and its signing key were created.",
            "success",
        )
        # Home, where a new workspace's owner finds the getting-started checklist.
        return redirect(url_for("core.index"))
    return render_template("register.html", form=form), 400 if request.method == "POST" else 200


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


@bp.get("/forgot-password")
def forgot_password():
    """What can and cannot be done about a forgotten password (plan S18). Read-only, signed in or
    out; R9 builds the recovery routes it says are coming."""
    return render_template(
        "forgot_password.html",
        device_days=int(current_app.config.get("DEVICE_TOKEN_MAX_AGE_DAYS", 90)),
    )


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
        return redirect(url_for("account.security"))
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
    return redirect(url_for("account.security"))
