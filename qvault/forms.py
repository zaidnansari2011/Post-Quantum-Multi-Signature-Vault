"""WTForms form definitions (CSRF-protected via Flask-WTF)."""

from __future__ import annotations

from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import (
    BooleanField,
    DateTimeLocalField,
    HiddenField,
    IntegerField,
    PasswordField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import (
    DataRequired,
    Email,
    EqualTo,
    InputRequired,
    Length,
    NumberRange,
    Optional,
    ValidationError,
)

from qvault.security import text


def _visible_only(form, field) -> None:
    """A name other people see may not hide characters (plan R8 review, F6)."""
    if text.invisible_in(field.data):
        raise ValidationError(text.MESSAGE)


class _PasswordStep(FlaskForm):
    """The honest password step (plan S21), shared by both ways to create an account.

    The password is also what unwraps the signing key, so nobody, including the operator, can
    reset it without losing that key. The person must say they understand before an account is
    made; ``templates/_password_step.html`` draws it.
    """

    password = PasswordField("Password", validators=[DataRequired(), Length(min=8, max=1024)])
    confirm = PasswordField(
        "Confirm password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match")],
    )
    understood = BooleanField(
        "I understand that if I forget this password, Q-Vault can't reset it for me.",
        validators=[DataRequired(message="Tick the box to confirm you've read this.")],
    )


class RegisterForm(_PasswordStep):
    """Create your workspace: a new account and a new workspace it owns
    (``auth_service.sign_up``). It never joins an existing workspace; an invitation link does."""

    display_name = StringField(
        "Full name", validators=[DataRequired(), Length(max=255), _visible_only]
    )
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    workspace_name = StringField(
        "Workspace name",
        validators=[DataRequired(message="Name your workspace."), Length(max=120), _visible_only],
    )
    submit = SubmitField("Create workspace")


class InviteRegisterForm(_PasswordStep):
    """Creating an account from an invitation link. No email field: the account's address is the
    one the invitation was sent to (workspace_service.register_through_invitation)."""

    display_name = StringField(
        "Full name", validators=[DataRequired(), Length(max=255), _visible_only]
    )
    submit = SubmitField("Create account and join")


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField("Password", validators=[DataRequired()])
    # "Sign in" everywhere — the page title, the H1 and the landing link all said Sign in while
    # the button six inches below said Log in. An action keeps one name through a whole flow.
    submit = SubmitField("Sign in")


class VaultForm(FlaskForm):
    name = StringField("Vault name", validators=[DataRequired(), Length(max=255), _visible_only])
    description = TextAreaField("Description", validators=[Optional(), Length(max=2000)])
    # InputRequired, not DataRequired: a 0 is an answer (and out of range), not a missing one.
    threshold_m = IntegerField(
        "Approvals required",
        validators=[
            InputRequired(message="Say how many approvals a decision needs."),
            NumberRange(min=1, max=50, message="Choose a number from 1 to 50."),
        ],
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


class VaultRuleForm(FlaskForm):
    """Plan S15: "The person who raises a decision can also approve it". Unchecked is off."""

    requester_can_approve = BooleanField("The person who raises a decision can also approve it")
    submit = SubmitField("Save")


class VaultRulesForm(FlaskForm):
    """The vault's Approval rule card: the threshold and plan S15 together, under one Save."""

    threshold_m = IntegerField(
        "Approvals required", validators=[DataRequired(), NumberRange(min=1, max=50)]
    )
    requester_can_approve = BooleanField("The person who raises a decision can also approve it")


class ProfileForm(FlaskForm):
    display_name = StringField(
        "Display name", validators=[DataRequired(), Length(max=255), _visible_only]
    )
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


#: A due time as the browser's datetime-local control posts it, and as a person types it into the
#: styled date field (rework R2), which shows "2026-10-13 17:00". Both are read as UTC.
DEADLINE_FORMATS = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"]


class ProposalForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired(), Length(max=255)])
    action_text = TextAreaField(
        "Action / description", validators=[DataRequired(), Length(max=4000)]
    )
    deadline = DateTimeLocalField(
        "Deadline (optional)", format=DEADLINE_FORMATS, validators=[Optional()]
    )
    file = FileField("Attach a file (optional)")
    #: Plan S16, "Raise again": the closed decision this replaces. Checked by the service.
    raised_again_from = HiddenField()
    submit = SubmitField("Create proposal")


class PaymentProposalForm(FlaskForm):
    """Ask the vault's treasury to pay (plan Phase 8). Only the recipient and the amount come from
    the proposer; the decision's text is generated from the payment (D24)."""

    title = StringField("Title", validators=[DataRequired(), Length(max=255)])
    to = StringField("Recipient", validators=[DataRequired(), Length(max=42)])
    amount = StringField("Amount (ETH)", validators=[DataRequired(), Length(max=100)])
    deadline = DateTimeLocalField(
        "Deadline (optional)", format=DEADLINE_FORMATS, validators=[Optional()]
    )
    raised_again_from = HiddenField()
    submit = SubmitField("Create payment decision")


class AccessProposalForm(FlaskForm):
    """A Production access decision (plan S13). The fields write the decision text, so their rules
    are ``qvault.services.decision_types``'s, the phone's too; the lengths here only stop an
    absurd post early."""

    title = StringField("Title", validators=[DataRequired(), Length(max=255)])
    person = StringField("Who gets access", validators=[Length(max=400)])
    system = StringField("System", validators=[Length(max=400)])
    level = StringField("Access", validators=[Length(max=40)])
    until = StringField("Until", validators=[Length(max=40)])
    reason = StringField("Reason", validators=[Length(max=1200)])
    reference = StringField("Ticket or reference", validators=[Length(max=400)])
    deadline = DateTimeLocalField(
        "Deadline (optional)", format=DEADLINE_FORMATS, validators=[Optional()]
    )
    raised_again_from = HiddenField()
    submit = SubmitField("Create access decision")


class ContractProposalForm(FlaskForm):
    """A Contract decision (plan S13): who with, what for, and optionally its value and term."""

    title = StringField("Title", validators=[DataRequired(), Length(max=255)])
    counterparty = StringField("Counterparty", validators=[Length(max=600)])
    subject = StringField("What it's for", validators=[Length(max=1200)])
    amount = StringField("Value", validators=[Length(max=100)])
    currency = StringField("Currency", validators=[Length(max=20)])
    starts = StringField("Starts", validators=[Length(max=40)])
    ends = StringField("Ends", validators=[Length(max=40)])
    reference = StringField("Contract reference", validators=[Length(max=400)])
    deadline = DateTimeLocalField(
        "Deadline (optional)", format=DEADLINE_FORMATS, validators=[Optional()]
    )
    file = FileField("Attach the contract (optional)")
    raised_again_from = HiddenField()
    submit = SubmitField("Create contract decision")


class VoteForm(FlaskForm):
    """Cast a signed approve/reject vote. The password unlocks the signer's PQC private key so
    the vote can be signed; it is used transiently and never stored."""

    password = PasswordField(
        "Your password (to unlock your signing key)", validators=[DataRequired()]
    )
    # Required for a rejection (plan S16); the service enforces it, as the route cannot know
    # which button was pressed before the form validates.
    reason = StringField("Reason", validators=[Optional(), Length(max=255)])
    approve = SubmitField("Approve & sign")
    reject = SubmitField("Reject")


class ReconfigureForm(FlaskForm):
    """Ask for the treasury to follow the vault (plan D45). ``confirm`` must be ticked when the
    change takes away someone's power to approve; the service refuses without it."""

    confirm = BooleanField("I understand")
    #: ``warnings_digest`` of the warnings the page showed, so a tick confirms exactly those.
    warnings_digest = HiddenField()


class ReconfigurationApprovalForm(FlaskForm):
    """Approve a treasury change with the password key the treasury holds for you (D46)."""

    password = PasswordField("Your password", validators=[DataRequired()])


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


class WithdrawForm(FlaskForm):
    """Withdraw an open decision you raised (plan S16). A POST with a CSRF token: it ends the
    decision for everyone."""

    submit = SubmitField("Withdraw")


class CommentForm(FlaskForm):
    """Post to a decision's discussion. The limits are ``discussion_service``'s, checked there."""

    body = TextAreaField("Comment")
    submit = SubmitField("Post comment")


class DeleteCommentForm(FlaskForm):
    """Delete your own comment. A POST with a CSRF token."""

    submit = SubmitField("Delete")


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


class RunAttackLabForm(FlaskForm):
    """Admin control for an in-request adversary-lab run (ADR-0021).

    No fields: the run takes no parameters, and everything that could be tuned (which attacks,
    which seed) belongs to ``scripts/run_attack_lab.py``, where the result is a committed artefact
    rather than a page. The form exists for its CSRF token and its submit button.
    """
