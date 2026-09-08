"""WTForms form definitions (CSRF-protected via Flask-WTF)."""

from __future__ import annotations

from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import (
    BooleanField,
    DateTimeLocalField,
    IntegerField,
    PasswordField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Email, EqualTo, Length, NumberRange, Optional


class RegisterForm(FlaskForm):
    display_name = StringField("Full name", validators=[DataRequired(), Length(max=255)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8, max=1024)])
    confirm = PasswordField(
        "Confirm password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match")],
    )
    submit = SubmitField("Create account")


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField("Password", validators=[DataRequired()])
    # "Sign in" everywhere — the page title, the H1 and the landing link all said Sign in while
    # the button six inches below said Log in. An action keeps one name through a whole flow.
    submit = SubmitField("Sign in")


class VaultForm(FlaskForm):
    name = StringField("Vault name", validators=[DataRequired(), Length(max=255)])
    description = TextAreaField("Description", validators=[Optional(), Length(max=2000)])
    threshold_m = IntegerField(
        "Approval threshold (M signatures required)",
        validators=[DataRequired(), NumberRange(min=1, max=50)],
        default=2,
    )
    submit = SubmitField("Create vault")


class AddMemberForm(FlaskForm):
    email = StringField("Member email", validators=[DataRequired(), Email(), Length(max=255)])
    role = SelectField(
        "Role", choices=[("signer", "Signer"), ("viewer", "Viewer")], default="signer"
    )
    submit = SubmitField("Add member")


class MemberRoleForm(FlaskForm):
    user_id = IntegerField(validators=[DataRequired()])
    role = SelectField(choices=[("signer", "Can approve"), ("viewer", "View only")])
    submit = SubmitField("Save")


class RemoveMemberForm(FlaskForm):
    user_id = IntegerField(validators=[DataRequired()])
    submit = SubmitField("Remove")


class ThresholdForm(FlaskForm):
    threshold_m = IntegerField(
        "Approvals required", validators=[DataRequired(), NumberRange(min=1, max=50)]
    )
    submit = SubmitField("Save")


class ProfileForm(FlaskForm):
    display_name = StringField("Display name", validators=[DataRequired(), Length(max=255)])
    submit = SubmitField("Save")


class ChangePasswordForm(FlaskForm):
    """Changing a password re-encrypts the user's private keys, so the current one is required —
    it is the only thing that can unwrap them (see key_service.change_password)."""

    current_password = PasswordField("Current password", validators=[DataRequired()])
    new_password = PasswordField(
        "New password", validators=[DataRequired(), Length(min=8, max=1024)]
    )
    confirm = PasswordField(
        "Confirm new password",
        validators=[DataRequired(), EqualTo("new_password", message="Passwords must match")],
    )
    submit = SubmitField("Change password")


class ProposalForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired(), Length(max=255)])
    action_text = TextAreaField(
        "Action / description", validators=[DataRequired(), Length(max=4000)]
    )
    deadline = DateTimeLocalField(
        "Deadline (optional)", format="%Y-%m-%dT%H:%M", validators=[Optional()]
    )
    file = FileField("Attach a file (optional)")
    submit = SubmitField("Create proposal")


class VoteForm(FlaskForm):
    """Cast a signed approve/reject vote. The password unlocks the signer's PQC private key so
    the vote can be signed; it is used transiently and never stored."""

    password = PasswordField(
        "Your password (to unlock your signing key)", validators=[DataRequired()]
    )
    reason = StringField("Reason (optional)", validators=[Optional(), Length(max=255)])
    approve = SubmitField("Approve & sign")
    reject = SubmitField("Reject")


class LedgerTamperForm(FlaskForm):
    """Dev-only tamper demonstration controls (gated by ENABLE_TAMPER_DEMO at the route)."""

    target_seq = IntegerField(
        "Entry # to tamper", validators=[DataRequired(), NumberRange(min=1)], default=1
    )
    edit = SubmitField("Tamper: edit payload")
    rewrite = SubmitField("Tamper: full rewrite")


class LedgerRestoreForm(FlaskForm):
    restore = SubmitField("Restore ledger")


class TraceClearForm(FlaskForm):
    clear = SubmitField("Clear")


class ProposalTamperForm(FlaskForm):
    """Dev-only: rewrite an approved proposal's text behind its signatures' backs.

    Gated at the route by ``qvault.security.demo_gate.demo_enabled`` — the same predicate as the
    ledger tamper demo, so both destructive demonstrations share one switch.
    """

    tamper = SubmitField("Rewrite this proposal")


class ProposalRestoreForm(FlaskForm):
    restore = SubmitField("Restore original text")


class SwitchAlgorithmForm(FlaskForm):
    """Admin control to switch the active signature algorithm for NEW keys. ``choices`` are set
    from the registry in the route, so only registered algorithms can be selected.

    A switch that *lowers* the NIST security category additionally requires ticking
    ``confirm_downgrade`` and typing a reason. The service refuses it otherwise, so these fields
    are a prompt for deliberation rather than the security control itself.
    """

    algorithm = SelectField("Active signature algorithm", validators=[DataRequired()])
    confirm_downgrade = BooleanField("I intend to lower the security category")
    downgrade_reason = StringField("Reason", validators=[Optional(), Length(max=255)])
    submit = SubmitField("Switch algorithm")


class ReissueKeyForm(FlaskForm):
    """Re-issue the current user's signing key under the active algorithm (retire-but-retain)."""

    password = PasswordField("Confirm your password", validators=[DataRequired()])
    submit = SubmitField("Re-issue signing key")


class RunMaintenanceForm(FlaskForm):
    """Admin control to run the rotation + expiry jobs immediately (they also run on a schedule)."""

    submit = SubmitField("Run rotation + expiry now")


class ExpireKeysForm(FlaskForm):
    """Dev-only: bring every key's rotation deadline forward so rotation has work to do.

    Gated at the route by ``qvault.security.demo_gate.demo_enabled``, like the ledger and proposal
    demonstrations.
    """

    submit = SubmitField("Age all keys past their deadline")


class RunBenchmarkForm(FlaskForm):
    """Admin control for a small, indicative in-request benchmark.

    The iteration count is clamped again in the route against ``BENCHMARK_LIVE_MAX_ITERATIONS``:
    the field bound is a convenience, not the safety limit.
    """

    iterations = IntegerField(
        "Iterations", validators=[Optional(), NumberRange(min=1, max=25)], default=3
    )
    submit = SubmitField("Run live")


class PublishForm(FlaskForm):
    """Share a decided decision at a public URL.

    A form rather than a link because publishing is a state change on confidential data: it needs
    a POST and a CSRF token, and it is written to the audit log with the member who chose it as
    the actor (see ``qvault.services.publication_service``).
    """

    submit = SubmitField("Create public link")


class UnpublishForm(FlaskForm):
    """Stop serving a decision's public record.

    Deliberately not called "delete" or "recall". Any bundle already downloaded stays valid and
    verifiable forever -- that is the design, not a leak -- so the control withdraws this server's
    copy and the surrounding copy says exactly that.
    """

    submit = SubmitField("Revoke link")
