"""Vault routes: list/create vaults, view a vault, add members, create proposals, download files."""

from __future__ import annotations

from datetime import UTC

from flask import Blueprint, Response, abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from qvault.forms import AddMemberForm, ProposalForm, VaultForm
from qvault.models.proposal import Proposal
from qvault.models.vault import VaultMember
from qvault.security.decorators import get_membership_or_403
from qvault.services import file_crypto_service, proposal_service, vault_service
from qvault.services.file_crypto_service import FileDecryptError
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
    return render_template("vaults/proposal_detail.html", vault=vault, proposal=proposal)


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
