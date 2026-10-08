"""Vault routes: list/create vaults, view a vault, add members, create proposals, download files."""

from __future__ import annotations

from base64 import b64decode
from datetime import UTC, datetime, timedelta

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from sqlalchemy.orm import selectinload
from werkzeug.utils import secure_filename

from qvault import evidence
from qvault.chain.action import MAX_DEADLINE as PAYMENT_MAX_DEADLINE
from qvault.chain.action import ActionError, parse_eth_value
from qvault.chain.relayer import RelayerError
from qvault.chain.rpc import RpcError
from qvault.extensions import db
from qvault.forms import (
    AddMemberForm,
    MemberRoleForm,
    PaymentProposalForm,
    ProposalForm,
    ProposalRestoreForm,
    ProposalTamperForm,
    PublishForm,
    ReconfigurationApprovalForm,
    ReconfigureForm,
    RemoveMemberForm,
    ThresholdForm,
    UnpublishForm,
    VaultForm,
    VoteForm,
)
from qvault.models.proposal import Proposal
from qvault.models.reconfiguration import Reconfiguration
from qvault.models.vault import VaultMember
from qvault.security.decorators import get_membership_or_403
from qvault.security.demo_gate import demo_enabled
from qvault.services import (
    approval_service,
    eligibility,
    evidence_service,
    export_service,
    file_crypto_service,
    inbox_service,
    key_service,
    payout_service,
    proposal_service,
    publication_service,
    receipt_service,
    reconfiguration_service,
    treasury_jobs,
    treasury_service,
    vault_service,
    workspace_service,
)
from qvault.services.approval_service import ApprovalError
from qvault.services.file_crypto_service import CiphertextMissing, FileDecryptError
from qvault.services.key_service import KeyUnlockError
from qvault.services.proposal_service import PaymentRequest, ProposalError
from qvault.services.publication_service import PublicationError
from qvault.services.treasury_service import LinkRefused
from qvault.services.vault_service import MembershipError, PolicyError

bp = Blueprint("vaults", __name__, url_prefix="/vaults")

#: A due time this close takes the warning tone on the decision page (style tile, time rules).
DUE_SOON = timedelta(hours=24)


@bp.get("/")
@login_required
def list_vaults():
    memberships = VaultMember.query.filter_by(user_id=current_user.id).all()
    vaults = sorted((m.vault for m in memberships), key=lambda v: v.created_at, reverse=True)

    # Each row answers "is anything here waiting for me?". Both counts come from inbox_service so
    # they agree exactly with the Approvals inbox and, more importantly, with what cast_vote will
    # accept — an earlier version of this counted current vault membership, which promised votes
    # the server then refused for anyone added after a proposal opened.
    signer_vaults = inbox_service.signer_vault_ids(current_user)
    rows = []
    for vault in vaults:
        decorated = inbox_service.decorate(vault.proposals, current_user, signer_vaults)
        rows.append(
            {
                "vault": vault,
                "open": sum(1 for r in decorated if r["status"] == "open"),
                "needs_me": sum(1 for r in decorated if r["needs_me"]),
                "signers": len(vault.signer_ids()),
            }
        )
    return render_template(
        "vaults/list.html",
        rows=rows,
        awaiting_me=sum(r["needs_me"] for r in rows),
        can_create_vaults=workspace_service.can_create_vaults(current_user),
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_vault():
    # Auditors are read-only (plan S10). The service refuses too; this answers before the form.
    if not workspace_service.can_create_vaults(current_user):
        abort(403)
    form = VaultForm()
    if form.validate_on_submit():
        try:
            vault = vault_service.create_vault(
                current_user, form.name.data, form.description.data, form.threshold_m.data
            )
        except PolicyError as exc:
            flash(str(exc), "danger")
            return render_template("vaults/new.html", form=form)
        flash("Vault created — its ML-KEM keypair was generated.", "success")
        return redirect(url_for("vaults.vault_detail", vid=vault.id))
    return render_template("vaults/new.html", form=form)


class TreasuryForm(FlaskForm):
    """Nothing to fill in: the button is the whole form, and CSRF is the point."""


VAULT_TABS = ("decisions", "members", "files", "treasury", "settings")


@bp.get("/<int:vid>")
@login_required
def vault_detail(vid: int):
    vault = get_membership_or_403(vid)
    tab = request.args.get("tab", "decisions")
    if tab not in VAULT_TABS:
        tab = "decisions"

    proposals = (
        Proposal.query.filter_by(vault_id=vid)
        .options(
            selectinload(Proposal.signatures),
            selectinload(Proposal.file),
            selectinload(Proposal.action),
            selectinload(Proposal.creator),
        )
        .order_by(Proposal.created_at.desc())
        .all()
    )
    me = vault.member_for(current_user.id)
    is_owner = me.member_role == "owner"
    signer_vaults = inbox_service.signer_vault_ids(current_user)
    treasury = treasury_jobs.view(vault) if _treasuries_on() else None
    if tab == "treasury" and treasury is None:
        # Switched off, the tab is not offered; a link to it must not reach a panel with nothing
        # to show (it raised a 500 for an owner).
        tab = "decisions"
    linked = treasury_service.linked_treasury(vault) if treasury is not None else None
    change = reconfiguration_service.view(vault, current_user) if linked is not None else None
    return render_template(
        "vaults/detail.html",
        vault=vault,
        tab=tab,
        me=me,
        rows=inbox_service.decorate(proposals, current_user, signer_vaults),
        # Who is in the vault, how each signs and when they last did (rework R2).
        members=vault_service.member_overview(vault) if tab == "members" else None,
        linked=linked,
        files=[p for p in proposals if p.file is not None],
        is_owner=is_owner,
        # New decision and New payment are drawn only for someone the route will let through.
        can_propose=proposal_service.may_propose(vault, current_user),
        member_form=AddMemberForm(),
        role_form=MemberRoleForm(),
        remove_form=RemoveMemberForm(),
        threshold_form=ThresholdForm(threshold_m=vault.policy.threshold_m),
        n_signers=len(vault.signer_ids()),
        treasury=treasury,
        treasury_status=(
            payout_service.treasury_status(linked, current_app.extensions.get("relayer"))
            if linked is not None
            else None
        ),
        change=change,
        treasury_form=TreasuryForm(),
        reconfigure_form=ReconfigureForm(
            warnings_digest=change["warnings_digest"] if change is not None else None
        ),
        reconfiguration_approval_form=ReconfigurationApprovalForm(),
        my_key=treasury_service.key_choice(current_user) if _treasuries_on() else None,
    )


def _treasuries_on() -> bool:
    return bool(current_app.config.get("ONCHAIN_EXECUTION_ENABLED"))


@bp.post("/<int:vid>/treasury")
@login_required
def create_treasury(vid: int):
    """Ask for a treasury contract for this vault (plan D36). Nothing is sent from here: the
    scheduler does the chain work, and the page shows how it is going."""
    vault = get_membership_or_403(vid, roles=("owner",))
    if not _treasuries_on():
        abort(404)
    form = TreasuryForm()
    if not form.validate_on_submit():
        abort(400)
    relayer = current_app.extensions.get("relayer")
    if relayer is None:
        flash("This instance cannot do chain work: no relayer is configured.", "error")
        return redirect(url_for("vaults.vault_detail", vid=vid, tab="treasury"))
    try:
        treasury_jobs.request_link(vault, by=current_user, relayer=relayer)
        flash("Creating the treasury. This takes about fifteen minutes.", "success")
    except LinkRefused as exc:
        for problem in exc.problems:
            flash(f"{problem[:1].upper()}{problem[1:]}.", "error")
    except (RpcError, RelayerError):
        flash("The Ethereum endpoint is not answering. Try again shortly.", "error")
    return redirect(url_for("vaults.vault_detail", vid=vid, tab="treasury"))


@bp.post("/<int:vid>/treasury/stop")
@login_required
def stop_treasury_job(vid: int):
    """Stop the job creating this vault's treasury (review M-3)."""
    vault = get_membership_or_403(vid, roles=("owner",))
    if not _treasuries_on():
        abort(404)
    if not TreasuryForm().validate_on_submit():
        abort(400)
    job = treasury_jobs.open_job(vault)
    if job is None:
        flash("Nothing is being created for this vault.", "error")
    else:
        treasury_jobs.cancel(job, by=current_user)
        flash("Stopped. Anything already on chain is reused if you ask again.", "success")
    return redirect(url_for("vaults.vault_detail", vid=vid, tab="treasury"))


@bp.post("/<int:vid>/treasury/reconfigure")
@login_required
def reconfigure_treasury(vid: int):
    """Ask for the treasury to follow the vault (plan D45). Sends nothing: the scheduler registers
    any new key, and the treasury's current signers approve the change before it is submitted."""
    vault = get_membership_or_403(vid, roles=("owner",))
    if not _treasuries_on():
        abort(404)
    form = ReconfigureForm()
    if not form.validate_on_submit():
        abort(400)
    relayer = current_app.extensions.get("relayer")
    if relayer is None:
        flash("This instance cannot do chain work: no relayer is configured.", "error")
        return redirect(url_for("vaults.vault_detail", vid=vid, tab="treasury"))
    try:
        reconfiguration_service.request(
            vault,
            by=current_user,
            relayer=relayer,
            confirm=(form.warnings_digest.data or False) if form.confirm.data else False,
        )
        flash("Change requested. The treasury's signers are asked to approve it.", "success")
    except reconfiguration_service.NeedsConfirmation as exc:
        for warning in exc.warnings:
            flash(f"Confirm first: {warning}.", "error")
    except reconfiguration_service.ReconfigurationRefused as exc:
        for problem in exc.problems:
            flash(f"{problem[:1].upper()}{problem[1:]}.", "error")
    return redirect(url_for("vaults.vault_detail", vid=vid, tab="treasury"))


@bp.post("/<int:vid>/treasury/reconfigurations/<int:rid>/approve")
@login_required
def approve_reconfiguration(vid: int, rid: int):
    """Approve a treasury change with your password key (D46), which may be one just retired."""
    vault = get_membership_or_403(vid)
    if not _treasuries_on():
        abort(404)
    reconfiguration = db.session.get(Reconfiguration, rid)
    if reconfiguration is None or reconfiguration.vault_id != vault.id:
        abort(404)
    form = ReconfigurationApprovalForm()
    if not form.validate_on_submit():
        flash("Enter your password to approve.", "error")
        return redirect(url_for("vaults.vault_detail", vid=vid, tab="treasury"))
    try:
        reconfiguration_service.approve_with_password(
            reconfiguration, current_user, form.password.data
        )
        flash("Approved.", "success")
    except KeyUnlockError:
        flash("Incorrect password: your signing key could not be unlocked.", "error")
    except reconfiguration_service.ApprovalRefused as exc:
        message = str(exc)
        flash(f"{message[:1].upper()}{message[1:]}.", "error")
    return redirect(url_for("vaults.vault_detail", vid=vid, tab="treasury"))


@bp.post("/<int:vid>/members")
@login_required
def add_member(vid: int):
    vault = get_membership_or_403(vid, roles=("owner",))
    form = AddMemberForm()
    if form.validate_on_submit():
        try:
            vault_service.add_member(
                vault, form.email.data, form.role.data, actor_id=current_user.id
            )
            flash("Member added.", "success")
        except MembershipError as exc:
            flash(str(exc), "danger")
    else:
        flash("Please provide a valid email.", "danger")
    # Every outcome back to the members tab, where the new member, or the reason there is none,
    # can be seen. Without the tab this opened the decisions.
    return redirect(url_for("vaults.vault_detail", vid=vid, tab="members"))


@bp.post("/<int:vid>/members/role")
@login_required
def change_member_role(vid: int):
    vault = get_membership_or_403(vid, roles=("owner",))
    form = MemberRoleForm()
    if not form.validate_on_submit():
        flash("Choose a valid role.", "danger")
        return redirect(url_for("vaults.vault_detail", vid=vid, tab="members"))
    try:
        vault_service.change_member_role(
            vault, form.user_id.data, form.role.data, actor_id=current_user.id
        )
        flash("Role updated.", "success")
    except MembershipError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("vaults.vault_detail", vid=vid, tab="members"))


@bp.post("/<int:vid>/members/remove")
@login_required
def remove_member(vid: int):
    vault = get_membership_or_403(vid, roles=("owner",))
    form = RemoveMemberForm()
    if not form.validate_on_submit():
        abort(400)
    try:
        vault_service.remove_member(vault, form.user_id.data, actor_id=current_user.id)
        flash("Member removed.", "success")
    except MembershipError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("vaults.vault_detail", vid=vid, tab="members"))


@bp.post("/<int:vid>/settings/threshold")
@login_required
def set_threshold(vid: int):
    vault = get_membership_or_403(vid, roles=("owner",))
    form = ThresholdForm()
    if not form.validate_on_submit():
        flash("Enter a valid number of approvals.", "danger")
        return redirect(url_for("vaults.vault_detail", vid=vid, tab="settings"))
    try:
        vault_service.set_threshold(vault, form.threshold_m.data, actor_id=current_user.id)
        flash("Approval threshold updated.", "success")
    except PolicyError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("vaults.vault_detail", vid=vid, tab="settings"))


def _payments_possible(vault) -> bool:
    return _treasuries_on() and treasury_service.linked_treasury(vault) is not None


@bp.route("/<int:vid>/proposals/new", methods=["GET", "POST"])
@login_required
def new_proposal(vid: int):
    vault = get_membership_or_403(vid)
    if not proposal_service.may_propose(vault, current_user):
        # A viewer is read-only. The service refuses too; this keeps the form from being offered
        # and answers before the request is read, for either kind of decision.
        abort(403)
    if request.args.get("kind") == "payment":
        return _new_payment(vault)
    form = ProposalForm()
    if form.validate_on_submit():
        file_bytes = None
        filename = None
        upload = form.file.data
        if upload is not None and getattr(upload, "filename", ""):
            file_bytes = upload.read()
            filename = secure_filename(upload.filename)
        deadline = form.deadline.data
        if deadline is not None and deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)  # treat the entered time as UTC
        if deadline is not None and deadline <= datetime.now(UTC):
            # It would be expired the moment it was raised. Payments are refused the same way by
            # the D23 policy; a general decision had no check.
            flash("Choose a due time in the future.", "danger")
            return _new_decision_page(form, vault, "general")
        try:
            proposal = proposal_service.create_proposal(
                vault,
                current_user,
                form.title.data,
                form.action_text.data,
                deadline=deadline,
                file_bytes=file_bytes,
                filename=filename,
            )
        except ProposalError as exc:
            flash(str(exc), "danger")
            return _new_decision_page(form, vault, "general")
        flash("Proposal created.", "success")
        return redirect(url_for("vaults.proposal_detail", vid=vid, pid=proposal.proposal_uuid))
    return _new_decision_page(form, vault, "general")


def _new_decision_page(form, vault, kind: str):
    """New decision, either type, with the "who approves" preview (plan S14) beside the form."""
    payments = kind == "payment" or _payments_possible(vault)
    now = datetime.now(UTC)
    return render_template(
        "vaults/proposal_new.html",
        form=form,
        vault=vault,
        payments=payments,
        kind=kind,
        preview=proposal_service.who_approves(vault, current_user),
        treasury=treasury_service.linked_treasury(vault) if kind == "payment" else None,
        # The date field's range: from now, and for a payment at most 30 days out (D23).
        due_min=now,
        due_max=now + PAYMENT_MAX_DEADLINE if kind == "payment" else None,
    )


def _new_payment(vault):
    """A payment decision (plan Phase 8): recipient and amount; the server writes the rest."""
    if not _payments_possible(vault):
        abort(404)
    form = PaymentProposalForm()
    if form.validate_on_submit():
        deadline = form.deadline.data
        if deadline is not None and deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)  # treat the entered time as UTC
        try:
            value = parse_eth_value(form.amount.data)
            proposal = proposal_service.create_proposal(
                vault,
                current_user,
                form.title.data,
                "",
                deadline=deadline,
                payment=PaymentRequest(to=form.to.data.strip(), value_wei=value),
            )
        except (ProposalError, ActionError) as exc:
            flash(f"{str(exc)[:1].upper()}{str(exc)[1:]}.", "danger")
        else:
            flash("Payment decision created.", "success")
            return redirect(
                url_for("vaults.proposal_detail", vid=vault.id, pid=proposal.proposal_uuid)
            )
    return _new_decision_page(form, vault, "payment")


@bp.get("/<int:vid>/proposals/<pid>")
@login_required
def proposal_detail(vid: int, pid: str):
    vault = get_membership_or_403(vid)
    proposal = Proposal.query.filter_by(vault_id=vid, proposal_uuid=pid).first_or_404()

    # Lazily flip to EXPIRED on view if its deadline has passed (Phase 7 makes this scheduled).
    # Kept non-fatal: a page view must never 500 because a read-time expiry write raced/failed.
    try:
        approval_service.refresh_expiry(proposal)
    except Exception:  # noqa: BLE001 - best-effort; fall back to the last committed state
        db.session.rollback()

    approvals, rejections = approval_service.tally(proposal)
    votes = [
        {"sig": s, "verified": approval_service.verify_signature(s, proposal)}
        for s in proposal.signatures
    ]
    # Which signatures were made by a key this server never held. ADR-0016's whole claim is
    # visible here or nowhere: without it a device-held signature is indistinguishable on screen
    # from one the server unwrapped, and the distinction is the point of the system.
    device_signed = sum(1 for s in proposal.signatures if s.custody == "device")

    my_vote = approval_service.vote_of(proposal, current_user.id)
    # An approver of THIS decision: whoever the vote gate would let sign it (its frozen signer
    # set, an approver of the vault now, in good standing in the workspace). Someone added after
    # it was raised, or demoted or suspended since, is neither offered a vote nor told it needs
    # them (rework R2, the personal status; owner decision 2026-10-08).
    eligible = eligibility.eligible_ids(proposal)
    is_signer = current_user.id in eligible
    can_vote = proposal.status == "open" and is_signer and my_vote is None
    # Who can still approve, and whether they are enough to decide it (``eligibility``).
    outlook = eligibility.outlook(
        proposal,
        approvals=approvals,
        voted=[s.signer_id for s in proposal.signatures],
        eligible=eligible,
    )
    binding = approval_service.verify_proposal_binding(proposal)
    # Approving a payment signs what the treasury will pay, built from the stored payment; when
    # that no longer matches what was signed, offering Approve would invite a signature over a
    # payment nobody proposed. The service refuses it too; this keeps the button from lying.
    # Reject stays: objecting authorises nothing.
    can_approve = can_vote and (proposal.action is None or binding.ok)
    payout = payout_service.view(proposal) if _treasuries_on() else None

    # Presentation only (rework R2): which tab, the viewer's status word, what signing would do,
    # and the evidence layers, each built from the checks above or run fresh in evidence_service.
    tab = request.args.get("tab")
    tab = tab if tab in ("evidence", "technical") else "overview"
    status_key, status_n = evidence.personal_status(
        # Effective, not stored: a passed deadline reads Expired before the sweep runs (S20).
        inbox_service.effective_status(proposal),
        can_vote=can_vote,
        approvals=approvals,
        required_m=proposal.required_m,
        payout_state=payout["state"] if payout else None,
    )
    proof = evidence_service.decision_evidence(
        proposal, binding=binding, votes=votes, viewer_id=current_user.id, payout=payout
    )
    amount = proof.payment["amount"] if proof.payment else None
    due = evidence.parse_stamp(proposal.expires_at)
    now = datetime.now(UTC)

    return render_template(
        "vaults/proposal_detail.html",
        vault=vault,
        proposal=proposal,
        tab=tab,
        status_key=status_key,
        status_n=status_n,
        ev=proof,
        approver_ids=evidence_service.approver_ids(proposal),
        still_ids=list(outlook.still),
        cannot_pass=proposal.status == "open" and not outlook.reachable,
        needed=outlook.needed,
        was_signer=not is_signer and current_user.id in evidence_service.approver_ids(proposal),
        due_soon=proposal.status == "open" and due is not None and due - now <= DUE_SOON,
        approve_lines=evidence.approve_consequence(
            approvals=approvals, required_m=proposal.required_m, payment=amount
        ),
        reject_lines=evidence.reject_consequence(
            rejections=rejections,
            required_m=proposal.required_m,
            required_n=proposal.required_n,
        ),
        my_key=key_service.active_signing_key(current_user) if is_signer else None,
        votes=votes,
        device_signed=device_signed,
        approvals=approvals,
        rejections=rejections,
        binding=binding,
        transparency=export_service.transparency_status(proposal),
        my_vote=my_vote,
        is_signer=is_signer,
        can_vote=can_vote,
        can_approve=can_approve,
        payout=payout,
        vote_form=VoteForm(),
        # Present only immediately after this member signed (or when someone follows a receipt
        # link). Scoped to this proposal inside the service, which is the authorisation check.
        receipt=receipt_service.for_signature_id(proposal, request.args.get("receipt")),
        publication=publication_service.publication_state(proposal),
        publish_form=PublishForm(),
        unpublish_form=UnpublishForm(),
        demo_enabled=demo_enabled(),
        tampered=proposal_service.demo_proposal_is_tampered(proposal),
        tamper_form=ProposalTamperForm(),
        restore_form=ProposalRestoreForm(),
    )


@bp.get("/<int:vid>/proposals/<pid>/export")
@login_required
def export_proposal(vid: int, pid: str):
    """Download this decision as a bundle anyone can verify without an account.

    Membership is required to *download* — the decision's contents are confidential until someone
    chooses to share them. Nothing about the bundle requires membership to *check*, which is the
    whole point: the person you send it to needs no relationship with this system at all.
    """
    get_membership_or_403(vid)
    proposal = Proposal.query.filter_by(vault_id=vid, proposal_uuid=pid).first_or_404()

    bundle = export_service.build_decision_bundle(proposal)

    # Three formats, one per audience, and the default is the one a person receives:
    #
    #   (default)  .html  a self-verifying decision record — readable, printable, and it re-checks
    #                     its own signatures on open with no extraction step and nothing installed
    #   ?format=json      the bare bundle: what the verifier consumes and what tooling should fetch
    #   ?format=zip       the same three files loose, for anyone who wants them separately
    fmt = request.args.get("format")

    if fmt == "json":
        return Response(
            export_service.bundle_bytes(bundle),
            mimetype="application/json",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{export_service.bundle_filename(proposal)}"'
                )
            },
        )

    if fmt != "zip":
        return Response(
            export_service.build_decision_document(bundle),
            # Bare "text/html": Flask appends the charset itself, and spelling it out here yields
            # a doubled "charset=utf-8; charset=utf-8".
            mimetype="text/html",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{export_service.document_filename(proposal)}"'
                )
            },
        )

    approvals, _ = approval_service.tally(proposal)
    certificate = render_template(
        "export/certificate.html",
        bundle=bundle,
        approvals=approvals,
        device_signed=sum(1 for s in bundle["signatures"] if s.get("custody") == "device"),
        # Derived from the bundle rather than the ORM so the rows line up with it exactly.
        signature_sizes=[len(b64decode(s["signature_b64"])) for s in bundle["signatures"]],
    )
    return Response(
        export_service.build_decision_package(bundle, certificate_html=certificate),
        mimetype="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{export_service.package_filename(proposal)}"'
            )
        },
    )


@bp.post("/<int:vid>/proposals/<pid>/publish")
@login_required
def publish_proposal(vid: int, pid: str):
    """Create the public link for a decided decision.

    Membership is required to *publish* for the same reason it is required to export: until a
    member chooses otherwise, a decision's contents are confidential. What publication changes is
    who may read it, never what it says — the record served publicly is built from the same rows,
    by the same code, as the one a member downloads.
    """
    get_membership_or_403(vid)
    proposal = Proposal.query.filter_by(vault_id=vid, proposal_uuid=pid).first_or_404()
    if not PublishForm().validate_on_submit():
        abort(400)
    try:
        publication_service.publish(proposal, current_user)
    except PublicationError as exc:
        flash(str(exc), "danger")
    else:
        flash(
            "Public link created. Anyone with the link can now read and verify this decision.",
            "success",
        )
    return redirect(url_for("vaults.proposal_detail", vid=vid, pid=pid))


@bp.post("/<int:vid>/proposals/<pid>/unpublish")
@login_required
def unpublish_proposal(vid: int, pid: str):
    """Withdraw the public link.

    The flash says "stops serving", not "revoked" or "deleted", because a bundle somebody already
    downloaded remains valid forever and this cannot reach it. Overstating what this button does
    would be the one kind of dishonesty this whole system exists to make impossible.
    """
    get_membership_or_403(vid)
    proposal = Proposal.query.filter_by(vault_id=vid, proposal_uuid=pid).first_or_404()
    if not UnpublishForm().validate_on_submit():
        abort(400)
    try:
        publication_service.unpublish(proposal, current_user)
    except PublicationError as exc:
        flash(str(exc), "danger")
    else:
        flash(
            "This server has stopped serving the public record. Copies already downloaded stay "
            "valid and verifiable — that is by design.",
            "success",
        )
    return redirect(url_for("vaults.proposal_detail", vid=vid, pid=pid))


@bp.post("/<int:vid>/proposals/<pid>/demo/tamper")
@login_required
def demo_tamper_proposal(vid: int, pid: str):
    """Dev-only: rewrite this proposal's text without touching a single signature byte.

    Deliberately requires vault membership rather than admin: the point of the demonstration is
    that even a legitimate insider — someone who is *supposed* to see this proposal — cannot
    alter it undetectably.
    """
    if not demo_enabled():
        abort(404)
    get_membership_or_403(vid)
    proposal = Proposal.query.filter_by(vault_id=vid, proposal_uuid=pid).first_or_404()
    if not ProposalTamperForm().validate_on_submit():
        abort(400)

    proposal_service.demo_tamper_proposal(proposal)
    flash(
        "Proposal text rewritten directly in the database. Every signature is byte-for-byte "
        "intact and still verifies — but the binding check below now refuses to count them.",
        "warning",
    )
    return redirect(url_for("vaults.proposal_detail", vid=vid, pid=pid))


@bp.post("/<int:vid>/proposals/<pid>/demo/restore")
@login_required
def demo_restore_proposal(vid: int, pid: str):
    if not demo_enabled():
        abort(404)
    get_membership_or_403(vid)
    proposal = Proposal.query.filter_by(vault_id=vid, proposal_uuid=pid).first_or_404()
    if not ProposalRestoreForm().validate_on_submit():
        abort(400)

    if proposal_service.demo_restore_proposal(proposal):
        flash("Original proposal text restored — the binding verifies again.", "success")
    else:
        flash("Nothing to restore for this proposal.", "info")
    return redirect(url_for("vaults.proposal_detail", vid=vid, pid=pid))


@bp.post("/<int:vid>/proposals/<pid>/vote")
@login_required
def vote(vid: int, pid: str):
    get_membership_or_403(vid)  # authorises the caller; the proposal carries its own vault_id
    proposal = Proposal.query.filter_by(vault_id=vid, proposal_uuid=pid).first_or_404()
    form = VoteForm()
    if not form.validate_on_submit():
        flash("Please enter your password to sign.", "danger")
        return redirect(url_for("vaults.proposal_detail", vid=vid, pid=pid))

    # Require exactly one explicit decision: never default an ambiguous submit to "approve".
    approve, reject = bool(form.approve.data), bool(form.reject.data)
    if approve == reject:
        flash("Please choose either Approve or Reject.", "danger")
        return redirect(url_for("vaults.proposal_detail", vid=vid, pid=pid))
    decision = "approve" if approve else "reject"
    try:
        signature = approval_service.cast_vote(
            proposal, current_user, form.password.data, decision, reason=form.reason.data
        )
    except KeyUnlockError:
        flash("Incorrect password — your signing key could not be unlocked.", "danger")
    except ApprovalError as exc:
        flash(str(exc), "danger")
    else:
        # Carry the new signature's id through the redirect so the detail page can render its
        # receipt. A query parameter rather than the session: it survives a refresh and can be
        # linked to, and there is nothing secret in a receipt for a signature already listed on
        # the page it appears on. No flash here — the receipt states the outcome in far more
        # detail than a one-line banner could, and two announcements of one event read as noise.
        return redirect(url_for("vaults.proposal_detail", vid=vid, pid=pid, receipt=signature.id))
    return redirect(url_for("vaults.proposal_detail", vid=vid, pid=pid))


@bp.get("/<int:vid>/proposals/<pid>/file")
@login_required
def download_file(vid: int, pid: str):
    vault = get_membership_or_403(vid)
    proposal = Proposal.query.filter_by(vault_id=vid, proposal_uuid=pid).first_or_404()
    if proposal.file is None:
        abort(404)
    try:
        plaintext = file_crypto_service.decrypt(vault, proposal.file)
    except CiphertextMissing:
        # Ordered before FileDecryptError: CiphertextMissing is a subclass, and the two need
        # different words. Nothing failed to authenticate here — the bytes are absent.
        current_app.logger.error(
            "ciphertext missing for file id=%s path=%s",
            proposal.file.id,
            proposal.file.ciphertext_path,
        )
        flash(
            "This attachment's encrypted data is missing from server storage, so it cannot be "
            "downloaded. The record and its signatures are unaffected.",
            "danger",
        )
        return redirect(url_for("vaults.proposal_detail", vid=vid, pid=pid))
    except FileDecryptError:
        flash("Integrity check failed — the stored file could not be authenticated.", "danger")
        return redirect(url_for("vaults.proposal_detail", vid=vid, pid=pid))
    return Response(
        plaintext,
        mimetype="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{proposal.file.filename}"'},
    )
