"""Vault routes: list/create vaults, view a vault, add members, create proposals, download files."""

from __future__ import annotations

from datetime import UTC

from flask import Blueprint, Response, abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from qvault.extensions import db
from qvault.forms import (
    AddMemberForm,
    ProposalForm,
    ProposalRestoreForm,
    ProposalTamperForm,
    VaultForm,
    VoteForm,
)
from qvault.models.proposal import Proposal
from qvault.models.vault import VaultMember
from qvault.security.decorators import get_membership_or_403
from qvault.security.demo_gate import demo_enabled
from qvault.services import (
    approval_service,
    file_crypto_service,
    proposal_service,
    vault_service,
)
from qvault.services.approval_service import ApprovalError
from qvault.services.file_crypto_service import FileDecryptError
from qvault.services.key_service import KeyUnlockError
from qvault.services.proposal_service import ProposalError
from qvault.services.vault_service import MembershipError, PolicyError

bp = Blueprint("vaults", __name__, url_prefix="/vaults")


@bp.get("/")
@login_required
def list_vaults():
    memberships = VaultMember.query.filter_by(user_id=current_user.id).all()
    vaults = sorted((m.vault for m in memberships), key=lambda v: v.created_at, reverse=True)
    return render_template("vaults/list.html", vaults=vaults)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_vault():
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


@bp.get("/<int:vid>")
@login_required
def vault_detail(vid: int):
    vault = get_membership_or_403(vid)
    proposals = Proposal.query.filter_by(vault_id=vid).order_by(Proposal.created_at.desc()).all()
    is_owner = vault.member_for(current_user.id).member_role == "owner"
    return render_template(
        "vaults/detail.html",
        vault=vault,
        proposals=proposals,
        is_owner=is_owner,
        member_form=AddMemberForm(),
        n_signers=len(vault.signer_ids()),
    )


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
    return redirect(url_for("vaults.vault_detail", vid=vid))


@bp.route("/<int:vid>/proposals/new", methods=["GET", "POST"])
@login_required
def new_proposal(vid: int):
    vault = get_membership_or_403(vid)
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
            return render_template("vaults/proposal_new.html", form=form, vault=vault)
        flash("Proposal created.", "success")
        return redirect(url_for("vaults.proposal_detail", vid=vid, pid=proposal.proposal_uuid))
    return render_template("vaults/proposal_new.html", form=form, vault=vault)


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
    my_vote = approval_service.vote_of(proposal, current_user.id)
    is_signer = current_user.id in {m.user_id for m in vault.signer_members()}
    can_vote = proposal.status == "open" and is_signer and my_vote is None

    return render_template(
        "vaults/proposal_detail.html",
        vault=vault,
        proposal=proposal,
        votes=votes,
        approvals=approvals,
        rejections=rejections,
        binding=approval_service.verify_proposal_binding(proposal),
        my_vote=my_vote,
        is_signer=is_signer,
        can_vote=can_vote,
        vote_form=VoteForm(),
        demo_enabled=demo_enabled(),
        tampered=proposal_service.demo_proposal_is_tampered(proposal),
        tamper_form=ProposalTamperForm(),
        restore_form=ProposalRestoreForm(),
    )


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
        approval_service.cast_vote(
            proposal, current_user, form.password.data, decision, reason=form.reason.data
        )
    except KeyUnlockError:
        flash("Incorrect password — your signing key could not be unlocked.", "danger")
    except ApprovalError as exc:
        flash(str(exc), "danger")
    else:
        verb = "Approval" if decision == "approve" else "Rejection"
        flash(f"{verb} signed and recorded. Proposal is now {proposal.status}.", "success")
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
    except FileDecryptError:
        flash("Integrity check failed — the stored file could not be authenticated.", "danger")
        return redirect(url_for("vaults.proposal_detail", vid=vid, pid=pid))
    return Response(
        plaintext,
        mimetype="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{proposal.file.filename}"'},
    )
