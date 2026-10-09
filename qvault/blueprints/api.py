"""JSON API for enrolled devices (ADR-0016) — the surface the mobile client talks to.

Thin, like every blueprint here: parse the request, call exactly one service, serialise. All
governance, custody and crypto decisions live in ``services/``.

**The proposal detail endpoint is security-critical in its shape.** It returns the complete
canonical inputs to ``proposal_signing_bytes`` — vault id, uuid, action text, file hash, M/N, the
frozen signer set, nonce and creation timestamp — and not merely the ``payload_hash``. The device
recomputes that hash itself and refuses to sign if it disagrees. This is not belt-and-braces: if
the device signed a hash the server handed it, the server could make the device consent to
anything, and the entire non-repudiation gain from keeping the private key off this server would
evaporate. The client MUST recompute. The server offers the hash only so the client can compare.

Authentication is a bearer token, never a session cookie. ``_require_bearer`` below enforces that
mechanically, which is what makes the blueprint's CSRF exemption sound: a request carrying only a
cookie can never reach a view body here, so there is no ambient authority for a forged cross-site
POST to ride on.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
from datetime import UTC, datetime, timedelta

from flask import Blueprint, current_app, g, jsonify, request

from qvault import evidence
from qvault.chain.action import NETWORKS, format_wei
from qvault.chain.relayer import RelayerError
from qvault.chain.rpc import RpcError
from qvault.crypto import sha256_hex
from qvault.extensions import db
from qvault.models.key import Key
from qvault.models.proposal import Proposal
from qvault.models.reconfiguration import Reconfiguration
from qvault.models.treasury import TreasurySigner
from qvault.models.user import User
from qvault.models.vault import Vault, VaultMember
from qvault.security.decorators import device_token_required
from qvault.services import (
    approval_service,
    audit_service,
    auth_service,
    decision_types,
    device_service,
    discussion_service,
    eligibility,
    evidence_service,
    execution_service,
    inbox_service,
    key_service,
    notification_service,
    payout_service,
    proposal_service,
    reconfiguration_service,
    treasury_jobs,
    treasury_service,
    vault_service,
    workspace_service,
)
from qvault.services.approval_service import ApprovalError
from qvault.services.device_service import DeviceError
from qvault.services.proposal_service import (
    FieldsRefused,
    PaymentRequest,
    ProposalError,
    TypedRequest,
)
from qvault.services.signing import signing_bytes_for
from qvault.services.treasury_service import LinkRefused
from qvault.services.vault_service import MembershipError, PolicyError
from qvault.ui import status_of

bp = Blueprint("api", __name__, url_prefix="/api/v1")

# A decision deadline beyond this is refused rather than passed to timedelta, which overflows.
MAX_DEADLINE_HOURS = 24 * 366 * 10

# The only two endpoints reachable without a bearer token. Both authenticate with email+password
# and read no session, so neither depends on ambient browser authority.
_UNAUTHENTICATED = {"api.request_challenge", "api.enrol_device"}


@bp.before_request
def _require_bearer():
    """No API view may be reachable by session cookie.

    ``csrf.exempt(api_bp)`` in the app factory is only safe because of this. Enforced here rather
    than left to per-view discipline, so adding a view without a decorator fails closed.
    """
    if request.endpoint in _UNAUTHENTICATED:
        return None
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        return jsonify(ok=False, code="token_missing", error="Bearer token required."), 401
    return None


def _error(code: str, message: str, status: int):
    return jsonify(ok=False, code=code, error=message), status


# A payment decision's signing inputs carry an ``action`` that an app built before on-chain
# execution cannot hash (plan D25). Apps declare what they can do in this header; a payment
# decision is shown to, and can be voted on by, only an app that declares the payment capability.
CAPABILITIES_HEADER = "X-QVault-Capabilities"
PAYMENT_CAPABILITY = "payment-action-1"


def _handles_payments() -> bool:
    declared = request.headers.get(CAPABILITIES_HEADER, "")
    return PAYMENT_CAPABILITY in {part.strip() for part in declared.split(",")}


def _upgrade_required():
    return _error(
        "upgrade_required",
        "This decision is a payment. Update the Q-Vault app to review and sign it.",
        426,
    )


def _b64(raw: str, field: str) -> bytes:
    if raw is not None and not isinstance(raw, str):
        raise DeviceError("bad_request", f"{field} must be valid base64.")
    try:
        return base64.b64decode(raw or "", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise DeviceError("bad_request", f"{field} must be valid base64.") from exc


def _body() -> dict:
    # A JSON body that is not an object (a list, a string) is treated as empty, not a 500.
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _device_json(device, *, current_id: int | None = None) -> dict:
    key = device.key
    return {
        "id": device.id,
        "name": device.name,
        "alg_id": key.alg_id if key else None,
        "fingerprint": key.public_fingerprint() if key else None,
        "created_at": device.created_at.isoformat() if device.created_at else None,
        "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
        "expires_at": device.expires_at.isoformat() if device.expires_at else None,
        "revoked_at": device.revoked_at.isoformat() if device.revoked_at else None,
        "is_current": current_id is not None and device.id == current_id,
    }


# -- enrolment (unauthenticated: email + password) ------------------------------------------------


@bp.post("/devices/challenge")
def request_challenge():
    body = _body()
    user = auth_service.authenticate(body.get("email", ""), body.get("password", ""))
    if user is None:
        return _error("invalid_credentials", "Email or password is incorrect.", 401)

    challenge, expires_at = device_service.issue_challenge(user)
    return jsonify(
        ok=True,
        user_id=user.id,
        display_name=user.display_name,
        workspace=_workspace_json(user),
        challenge=challenge,
        expires_at=expires_at.isoformat(),
        eligible_algorithms=list(key_service.DEVICE_ELIGIBLE_SIG_ALGS),
        default_algorithm=key_service.DEVICE_ELIGIBLE_SIG_ALGS[0],
    )


@bp.post("/devices")
def enrol_device():
    body = _body()
    user = auth_service.authenticate(body.get("email", ""), body.get("password", ""))
    if user is None:
        return _error("invalid_credentials", "Email or password is incorrect.", 401)

    try:
        device, token = device_service.enrol(
            user,
            device_name=body.get("device_name", ""),
            alg_id=body.get("alg_id", ""),
            public_key_b64=body.get("public_key_b64", ""),
            challenge=body.get("challenge", ""),
            pop_signature_b64=body.get("pop_signature_b64", ""),
        )
    except DeviceError as exc:
        return _error(exc.code, exc.message, _ENROL_STATUS.get(exc.code, 400))

    return (
        jsonify(
            ok=True,
            # Returned exactly once — only its digest is stored, so it can never be re-displayed.
            token=token,
            expires_at=device.expires_at.isoformat() if device.expires_at else None,
            device=_device_json(device, current_id=device.id),
        ),
        201,
    )


_ENROL_STATUS = {
    "challenge_invalid": 401,
    "challenge_expired": 401,
    "public_key_already_enrolled": 409,
    "pop_invalid": 422,
}


# -- session --------------------------------------------------------------------------------------


def _workspace_json(user) -> dict | None:
    """The workspace this person works in and their role there (plan S10), or None when they
    belong to none, which can happen after an admin removes them. Additive for the phone: its
    schemas ignore fields they do not name."""
    member = workspace_service.current_membership(user)
    if member is None:
        return None
    return {
        "id": member.workspace_id,
        "name": member.workspace.name,
        "role": member.role,
        "role_name": workspace_service.role_name(member.role),
        # Plan S15: whether a vault created now stops whoever raises a decision from approving it,
        # so the phone's New vault can say what a single-approver vault will be unable to do.
        "separation_of_duties_default": bool(member.workspace.sod_default),
    }


@bp.get("/me")
@device_token_required
def whoami():
    user = g.api_user
    return jsonify(
        ok=True,
        user={"id": user.id, "email": user.email, "display_name": user.display_name},
        # The workspace this person works in, and their role there (plan S10). Null when they
        # belong to none, which can happen after an admin removes them.
        workspace=_workspace_json(user),
        device=_device_json(g.api_device, current_id=g.api_device.id),
        # Which key treasuries register for this person (D37), when this instance has treasuries.
        my_key=(
            treasury_service.key_choice(user)
            if current_app.config.get("ONCHAIN_EXECUTION_ENABLED")
            else None
        ),
    )


@bp.get("/devices")
@device_token_required
def list_devices():
    devices = device_service.devices_for(g.api_user)
    return jsonify(ok=True, devices=[_device_json(d, current_id=g.api_device.id) for d in devices])


@bp.post("/devices/<int:device_id>/revoke")
@device_token_required
def revoke_device(device_id: int):
    from qvault.models.device import Device

    device = db.session.get(Device, device_id)
    # 404 rather than 403 when it belongs to someone else: a caller must not be able to probe
    # which device ids exist, mirroring get_membership_or_403's asymmetry for vaults.
    if device is None or device.owner_id != g.api_user.id:
        return _error("unknown_device", "No such device.", 404)
    try:
        device_service.revoke(device, actor_id=g.api_user.id)
    except DeviceError as exc:
        return _error(exc.code, exc.message, 409)
    return jsonify(ok=True, device=_device_json(device, current_id=g.api_device.id))


# -- vaults ---------------------------------------------------------------------------------------


def _member_of(user, vid: int) -> Vault | None:
    """The vault, if this user is a member of it. Membership is checked here rather than trusted
    from a client-supplied id: every vault view below is reachable with any integer."""
    vault = db.session.get(Vault, vid)
    if vault is None or not vault.is_member(user.id):
        return None
    return vault


def _vault_summary(vault: Vault, user) -> dict:
    """What a list row needs, and nothing that costs a query per vault to produce.

    ``open_count`` is the number of decisions in this vault still awaiting *this* signer, not the
    number open overall -- a list that says "4 open" next to a vault where none of the four needs
    you is a number that trains people to ignore it.
    """
    signers = vault.signer_ids()
    member = vault.member_for(user.id)
    awaiting = 0
    # Who may sign here now (the vote gate's rule), once for the vault rather than per decision.
    signing_here = user.id in eligibility.current_signer_ids(vault)
    for p in vault.proposals:
        # The effective status, not the stored one: a deadline that passed before the sweep ran
        # leaves the count at once (rework S20), as it leaves every other needs-you queue.
        if inbox_service.effective_status(p) != "open":
            continue
        if approval_service.vote_of(p, user.id) is not None:
            continue
        if (
            signing_here
            and user.id in set(json.loads(p.authorized_signers_snapshot))
            and not eligibility.own_decision_blocked(p, user.id)
        ):
            awaiting += 1
    return {
        "vault_id": vault.id,
        "name": vault.name,
        "description": vault.description,
        "role": member.member_role if member else None,
        "threshold_m": vault.policy.threshold_m if vault.policy else None,
        "signer_count": len(signers),
        "member_count": len(vault.members),
        "awaiting_me": awaiting,
        "kem_alg_id": vault.kem_alg_id,
    }


@bp.get("/people")
@device_token_required
def list_people():
    """The names a vault can be built from. Names only -- never addresses.

    A vault needs people, and a handset cannot type an email address reliably. Without a picker the
    only way to add a signer is to recall their address exactly and have the server reject it if
    you are one character out.

    **The obvious version of this endpoint returns everyone's email, and it must not.** An address
    is a login identifier here, so publishing the directory to every enrolled device would hand any
    one of them the username half of every account on the instance, to solve a problem that is
    really about typing. So the client receives a display name and an opaque id, picks a name, and
    sends the id back; the server resolves it to a user. Nothing the device holds afterwards is
    usable as a credential or reachable off the platform.

    Names are still personal data, so the set is kept to what building a vault needs: the active
    members of the caller's own workspace (plan S10), without the caller, since they are already
    the vault's owner and first signer. Nobody in another workspace is ever listed.
    """
    people = workspace_service.colleagues(g.api_user, limit=500)
    workspace = _workspace_json(g.api_user)
    return jsonify(
        ok=True,
        # Which workspace the list is drawn from, so a picker can say whose people these are.
        workspace=None if workspace is None else {"id": workspace["id"], "name": workspace["name"]},
        people=[{"user_id": p.id, "name": p.display_name} for p in people],
    )


@bp.post("/vaults")
@device_token_required
def create_vault():
    """Create a vault, optionally with its signers, in one call.

    Members are accepted here rather than only through a follow-up call because a vault with one
    member is a vault that cannot do anything: ``create_proposal`` refuses when M exceeds the
    number of signers, so a 3-of-N vault created alone would reject every decision raised in it
    until somebody remembered the second step. One round trip also means the handset cannot leave
    a half-built vault behind when the network drops between two requests.

    An email that does not belong to a registered user is reported rather than skipped. Silently
    dropping it would produce a vault whose policy the owner believes is 3-of-4 and which is
    actually 3-of-3 -- a governance difference they did not agree to.
    """
    user = g.api_user
    body = _body()
    if not workspace_service.can_create_vaults(user):
        return _error(
            "not_allowed",
            "Auditors are read-only, so they can't create vaults. Ask a workspace owner or admin "
            "to change your role.",
            403,
        )

    name = (body.get("name") or "").strip()
    if not name:
        return _error("name_required", "Give the vault a name.", 422)
    if len(name) > 120:
        return _error("name_too_long", "Vault names are limited to 120 characters.", 422)

    try:
        threshold_m = int(body.get("threshold_m", 1))
    except (TypeError, ValueError):
        return _error("bad_threshold", "threshold_m must be a whole number.", 422)

    # Two ways in. `member_ids` is what the handset sends, because its picker only ever received
    # names and opaque ids from /people -- the address is resolved here, server-side, so the device
    # never has to hold one. `member_emails` stays for anything driving the API directly.
    emails = [e.strip().lower() for e in (body.get("member_emails") or []) if str(e).strip()]
    workspace = workspace_service.current_workspace(user)
    for raw_id in body.get("member_ids") or []:
        try:
            person_id = int(raw_id)
        except (TypeError, ValueError):
            return _error("bad_member", "member_ids must be whole numbers.", 422)
        # Resolved inside the caller's workspace only: an id from anywhere else is answered
        # exactly as one that does not exist, so ids cannot be used to find other customers' staff.
        person = workspace_service.find_member_user(workspace, user_id=person_id)
        if person is None:
            return _error("unknown_member", "One of the people chosen no longer exists.", 422)
        # Skipping the caller is not a silent drop: they are the owner and already a signer, so
        # adding them again would fail as a duplicate membership.
        if person.id != user.id and person.email not in emails:
            emails.append(person.email)
    # The owner is a signer, so N is the invited signers plus one. Checked before anything is
    # written, so a policy that can never be met does not leave a vault behind.
    if threshold_m > len(emails) + 1:
        return _error(
            "threshold_too_high",
            f"{threshold_m} signatures cannot be required from {len(emails) + 1} signer(s).",
            422,
        )

    try:
        vault = vault_service.create_vault(
            user, name, (body.get("description") or "").strip(), threshold_m, commit=False
        )
        db.session.flush()
        for email in emails:
            vault_service.add_member(vault, email, "signer", actor_id=user.id, commit=False)
        db.session.commit()
    except (PolicyError, MembershipError) as exc:
        db.session.rollback()
        return _error("vault_error", str(exc), 422)

    return jsonify(ok=True, vault=_vault_summary(vault, user)), 201


@bp.post("/vaults/<int:vid>/members")
@device_token_required
def add_vault_member(vid: int):
    """Add a signer or viewer to an existing vault.

    Only the owner may do this. Membership decides who can approve, so letting any member widen the
    signer set would let a signer recruit their own quorum.
    """
    user = g.api_user
    vault = _member_of(user, vid)
    if vault is None:
        return _error("unknown_vault", "No such vault.", 404)
    if vault.owner_id != user.id:
        return _error("not_the_owner", "Only the vault owner can change its members.", 403)

    body = _body()
    email = (body.get("email") or "").strip().lower()
    role = (body.get("role") or "signer").strip().lower()
    if not email:
        return _error("email_required", "An email address is required.", 422)

    try:
        vault_service.add_member(vault, email, role, actor_id=user.id)
    except MembershipError as exc:
        return _error("membership_error", str(exc), 422)

    return jsonify(ok=True, vault=_vault_summary(vault, user)), 201


@bp.get("/vaults/<int:vid>/treasury")
@device_token_required
def vault_treasury(vid: int):
    """The vault's treasury, the work in progress on it, and what this device may do (D36, D40)."""
    user = g.api_user
    vault = _member_of(user, vid)
    if vault is None:
        return _error("unknown_vault", "No such vault.", 404)
    view = treasury_jobs.view(vault)
    view["may_create"] = treasury_jobs.may_request(vault, user)
    view["my_key"] = treasury_service.key_choice(user)
    # Changing a linked treasury (Phase 7b): what differs, and any change being approved.
    view["change"] = (
        reconfiguration_service.view(vault, user) if view["treasury"] is not None else None
    )
    linked = treasury_service.linked_treasury(vault) if view["treasury"] is not None else None
    view["status"] = (
        payout_service.treasury_status(linked, current_app.extensions.get("relayer"))
        if linked is not None
        else None
    )
    return jsonify(ok=True, **view)


@bp.post("/vaults/<int:vid>/treasury/reconfigure")
@device_token_required
def request_reconfiguration(vid: int):
    """Ask for the treasury to follow the vault (D45). A change that takes away someone's power
    to approve is refused with ``needs_confirmation`` until it is sent again with ``confirm``."""
    if not _handles_payments():
        return _upgrade_required()
    user = g.api_user
    vault = _member_of(user, vid)
    if vault is None:
        return _error("unknown_vault", "No such vault.", 404)
    if not treasury_jobs.may_request(vault, user):
        # Before anything else, so a member who is not the owner learns nothing of the relayer.
        return _error("not_owner", "Only the vault's owner changes its treasury.", 403)
    relayer = current_app.extensions.get("relayer")
    if relayer is None:
        return _error("no_relayer", "This instance cannot do chain work.", 503)
    confirm = _body().get("confirm")
    try:
        reconfiguration_service.request(
            vault,
            by=user,
            relayer=relayer,
            # The digest of the warnings the app showed (D45), never a bare yes: a change that
            # grew a new warning since is asked about again.
            confirm=confirm if isinstance(confirm, str) else False,
        )
    except reconfiguration_service.NeedsConfirmation as exc:
        return (
            jsonify(
                ok=False,
                code="needs_confirmation",
                error="Confirm what this change takes away.",
                warnings=exc.warnings,
                warnings_digest=reconfiguration_service.warnings_digest(exc.warnings),
            ),
            409,
        )
    except reconfiguration_service.ReconfigurationRefused as exc:
        return _error("reconfiguration_refused", " ".join(f"{p}." for p in exc.problems), 422)
    return (
        jsonify(
            ok=True,
            reconfiguration=reconfiguration_service.view(vault, user)["reconfiguration"],
        ),
        202,
    )


@bp.post("/vaults/<int:vid>/treasury/reconfigurations/<int:rid>/approve")
@device_token_required
def approve_reconfiguration(vid: int, rid: int):
    """Admit a current signer's approval of a treasury change, made on this phone (D46)."""
    if not _handles_payments():
        return _upgrade_required()
    user, device = g.api_user, g.api_device
    vault = _member_of(user, vid)
    reconfiguration = db.session.get(Reconfiguration, rid)
    if vault is None or reconfiguration is None or reconfiguration.vault_id != vault.id:
        return _error("unknown_reconfiguration", "No such change.", 404)
    try:
        signature = _b64(_body().get("signature_b64", ""), "signature_b64")
    except DeviceError as exc:
        return _error(exc.code, exc.message, 400)
    try:
        # The key is the authenticated device's, never one named in the body.
        row = reconfiguration_service.record_device_approval(
            reconfiguration, user, device.key, signature
        )
    except reconfiguration_service.ApprovalRefused as exc:
        message = str(exc)
        if "could not be asked" in message:
            return _error("chain_unavailable", message, 503)
        if "already approved" in message:
            return _error("already_approved", message, 409)
        return _error("approval_refused", message, 422)
    return (
        jsonify(
            ok=True,
            approval={
                "signature_sha256": sha256_hex(row.signature),
                "signed_at": row.created_at.isoformat() if row.created_at else None,
            },
            reconfiguration={
                "state": reconfiguration.state,
                "approvals": len(reconfiguration.signatures),
                "needed": reconfiguration.treasury.threshold_m,
            },
        ),
        201,
    )


@bp.post("/vaults/<int:vid>/treasury")
@device_token_required
def create_vault_treasury(vid: int):
    """Ask for a treasury for this vault. Sends nothing now: the server does the work (D36)."""
    if not _handles_payments():
        return _upgrade_required()
    user = g.api_user
    vault = _member_of(user, vid)
    if vault is None:
        return _error("unknown_vault", "No such vault.", 404)
    relayer = current_app.extensions.get("relayer")
    if relayer is None:
        return _error("no_relayer", "This instance cannot do chain work.", 503)
    try:
        job = treasury_jobs.request_link(vault, by=user, relayer=relayer)
    except LinkRefused as exc:
        return _error("treasury_refused", " ".join(f"{p}." for p in exc.problems), 422)
    except (RpcError, RelayerError):
        # The chain, not the request: an endpoint that will not answer is not a bad request.
        return _error("chain_unavailable", "The Ethereum endpoint is not answering.", 503)
    return jsonify(ok=True, job={"id": job.id, "state": job.state, "reason": job.reason}), 202


@bp.post("/vaults/<int:vid>/treasury/stop")
@device_token_required
def stop_vault_treasury_job(vid: int):
    """Stop the job creating this vault's treasury (D36). Whatever is on chain is reused next
    time; a job that cannot finish would otherwise hold the vault for ever (review M-3)."""
    user = g.api_user
    vault = _member_of(user, vid)
    if vault is None:
        return _error("unknown_vault", "No such vault.", 404)
    job = treasury_jobs.open_job(vault)
    if job is None:
        return _error("no_job", "Nothing is being created for this vault.", 404)
    try:
        treasury_jobs.cancel(job, by=user)
    except LinkRefused as exc:
        return _error("stop_refused", " ".join(f"{p}." for p in exc.problems), 422)
    return jsonify(ok=True, job={"id": job.id, "state": job.state, "reason": job.reason})


@bp.put("/me/signing-choice")
@device_token_required
def set_signing_choice():
    """Choose whether treasuries register this phone's key or the password key (D37)."""
    if not current_app.config.get("ONCHAIN_EXECUTION_ENABLED"):
        return _error("treasuries_off", "This instance has no treasuries.", 404)
    user = g.api_user
    custody = (_body().get("custody") or "").strip().lower()
    device_key = g.api_device.key if custody == "device" else None
    try:
        treasury_service.set_key_choice(user, custody=custody, device_key=device_key)
    except LinkRefused as exc:
        return _error("choice_refused", " ".join(f"{p}." for p in exc.problems), 422)
    return jsonify(ok=True, my_key=treasury_service.key_choice(user))


@bp.get("/vaults")
@device_token_required
def list_vaults():
    user = g.api_user
    vault_ids = _visible_vault_ids(user)
    if not vault_ids:
        return jsonify(ok=True, vaults=[])
    vaults = Vault.query.filter(Vault.id.in_(vault_ids)).order_by(Vault.name.asc()).all()
    return jsonify(ok=True, vaults=[_vault_summary(v, user) for v in vaults])


@bp.get("/vaults/<int:vid>")
@device_token_required
def vault_detail(vid: int):
    user = g.api_user
    vault = _member_of(user, vid)
    if vault is None:
        # 404 rather than 403, so the endpoint does not confirm that a vault exists to someone who
        # cannot see it.
        return _error("unknown_vault", "No such vault.", 404)

    detail = _vault_summary(vault, user)
    member_ids = [m.user_id for m in vault.members]
    keyed = _keyed(member_ids)
    detail["members"] = [
        {
            "user_id": m.user_id,
            "name": m.user.display_name if m.user else None,
            "email": m.user.email if m.user else None,
            "role": m.member_role,
            "is_me": m.user_id == user.id,
            # Additive (phone-ux §6.14): an approver without an active key can't sign yet, which
            # is why a quorum can be out of reach.
            "has_key": m.user_id in keyed,
        }
        for m in vault.members
    ]
    recent = sorted(vault.proposals, key=lambda p: p.id, reverse=True)[:50]
    detail["proposals"] = [_proposal_summary(p, user) for p in recent]
    # Additive (plan S15, R5; phone-ux §6.14, §6.16): the vault's rule as it stands, and its latest
    # changes as before and after, for the rule line and the New decision preview.
    detail["separation_of_duties"] = not eligibility.vault_allows_requester(vault)
    detail["rule_changes"] = [
        {
            "event": change["event"],
            "who": change["who"],
            "when": change["when"].isoformat() if change["when"] else None,
            "label": change["diff"]["label"],
            "before": change["diff"]["before"],
            "after": change["diff"]["after"],
        }
        for change in audit_service.rule_changes(vault, limit=5)
    ]
    return jsonify(ok=True, vault=detail)


def _keyed(user_ids: list[int]) -> set[int]:
    """Which of ``user_ids`` hold an active signing key, password-held or on a phone."""
    if not user_ids:
        return set()
    return set(
        db.session.scalars(
            db.select(Key.owner_id).where(
                Key.owner_id.in_(user_ids),
                Key.role == "sig",
                Key.status == "active",
                Key.can_sign.is_(True),
            )
        )
    )


@bp.post("/vaults/<int:vid>/proposals")
@device_token_required
def create_proposal(vid: int):
    """Raise a decision from the handset.

    No attachment. The canonical signing payload binds the SHA-256 of an attached file, so
    supporting uploads means getting multipart, a plaintext hash and at-rest encryption right on
    this path too -- and a half-done version that accepted a file without binding it would produce
    decisions whose signatures did not cover the document they are about. The web client keeps
    that job until this path is built to the same standard; ``file_sha256`` stays null here, which
    is the same shape the device already handles for an attachment-free decision.
    """
    user = g.api_user
    vault = _member_of(user, vid)
    if vault is None:
        return _error("unknown_vault", "No such vault.", 404)
    refusal = proposal_service.why_cannot_propose(vault, user)
    if refusal is not None:
        # A viewer is read-only, and so is a suspended member or an auditor. Answered before the
        # body is read, as the owner-only routes do; the service refuses too, since every path to
        # a decision goes through it.
        return _error("view_only", refusal, 403)

    body = _body()
    title = (body.get("title") or "").strip()
    action_text = (body.get("action_text") or "").strip()
    payment = body.get("payment")
    # Plan S13 (A13): a Production access or Contract decision, its text written from `fields`.
    # `type` is the name phone-ux gives it; `decision_type` matches what the detail returns. Sent
    # under both names they must agree, null included: {"type": "access", "decision_type": null}
    # is a contradiction, not a General decision.
    if "type" in body and "decision_type" in body and body["type"] != body["decision_type"]:
        return _error("bad_request", "Send the type once, as decision_type.", 422)
    decision_type = body["decision_type"] if "decision_type" in body else body.get("type")
    if "action" in body:
        # The signed action is built by the server from `payment` (plan D23); a client never
        # supplies it. Accepting and ignoring it would create a text-only decision that reads like
        # a payment (review L4).
        return _error(
            "action_not_accepted",
            "Send the recipient and amount as 'payment'; the signed action is built by the server.",
            422,
        )
    if not title:
        return _error("title_required", "A title is required.", 422)
    typed = None
    if decision_type in (None, "general") and body.get("fields") is not None:
        # A General decision is the words its requester wrote: fields would be ignored, and a
        # client that sent them meant something else.
        return _error(
            "unknown_field",
            "Only a Production access or Contract decision takes fields.",
            422,
        )
    if decision_type not in (None, "general"):
        if decision_type == "payment":
            return _error(
                "payment_invalid", "Send a payment's recipient and amount as 'payment'.", 422
            )
        if decision_type not in decision_types.STORED_TYPES:
            return _error("unknown_type", decision_types.MESSAGES["unknown_type"], 422)
        if payment is not None:
            return _error("bad_request", "A payment has no other type.", 422)
        if action_text:
            return _error(
                "typed_text_generated",
                "This decision's text is written from its fields; omit action_text.",
                422,
            )
        typed = TypedRequest(decision_type, body.get("fields"))
    if payment is None and typed is None and not action_text:
        return _error("action_required", "Describe what is being decided.", 422)
    if len(title) > 255:
        return _error("title_too_long", "Titles are limited to 255 characters.", 422)

    payment_request = None
    if payment is not None:
        # A payment decision: the text is generated from the payment (plan D24), so none may be
        # supplied, and only an app that can then show and sign it may raise one (D25).
        if not current_app.config.get("ONCHAIN_EXECUTION_ENABLED"):
            return _error("payments_disabled", "Payment decisions are not enabled.", 403)
        if not _handles_payments():
            return _upgrade_required()
        if action_text:
            return _error(
                "payment_text_generated",
                "A payment decision's text is written from the payment; omit action_text.",
                422,
            )
        value = payment.get("value_wei") if isinstance(payment, dict) else None
        to = payment.get("to") if isinstance(payment, dict) else None
        # Wei travels as a decimal string: a JSON number cannot carry 10^18 exactly (plan D13).
        if (
            not isinstance(to, str)
            or not isinstance(value, str)
            or not value.isascii()
            or not value.isdigit()
            # 2^256 wei is 78 digits; longer is never an amount, and past 4,300 digits int() itself
            # raises (review L2).
            or len(value) > 78
        ):
            return _error(
                "payment_invalid",
                "payment needs 'to' (an address) and 'value_wei' (a decimal string).",
                422,
            )
        payment_request = PaymentRequest(to=to, value_wei=int(value))

    deadline = None
    hours = body.get("expires_in_hours")
    if hours is not None:
        try:
            hours = float(hours)
        except (TypeError, ValueError):
            return _error("bad_deadline", "expires_in_hours must be a number.", 422)
        if not math.isfinite(hours) or hours > MAX_DEADLINE_HOURS:
            # NaN, infinity or an absurd horizon made timedelta raise and the request 500.
            return _error("bad_deadline", "That deadline is too far away.", 422)
        if hours <= 0:
            return _error("bad_deadline", "A deadline must be in the future.", 422)
        deadline = datetime.now(UTC) + timedelta(hours=hours)

    again = body.get("raised_again_from")
    if again is not None and not isinstance(again, str):
        return _error("bad_request", "raised_again_from must be a decision id.", 422)
    try:
        proposal = proposal_service.create_proposal(
            vault,
            user,
            title,
            action_text,
            deadline=deadline,
            payment=payment_request,
            typed=typed,
            raised_again_from=again or None,
        )
    except FieldsRefused as exc:
        # Which field, so the phone can mark it; the words are the web form's.
        refusal = {"ok": False, "code": "fields_invalid", "error": str(exc), "field": exc.field}
        return jsonify(refusal), 422
    except ProposalError as exc:
        # The commonest case is a policy that needs more signatures than the vault has signers,
        # which is a governance answer rather than a malformed request.
        code = "payment_invalid" if payment_request is not None else "policy_error"
        return _error(code, str(exc), 422)

    return jsonify(ok=True, proposal=_proposal_summary(proposal, user)), 201


# -- proposals ------------------------------------------------------------------------------------


def _visible_vault_ids(user) -> list[int]:
    """Vault ids ``user`` belongs to. Queried rather than read off a relationship: ``User`` has
    no ``memberships`` backref, and a silent empty list would present as "you have no decisions"
    rather than as an error."""
    return [m.vault_id for m in VaultMember.query.filter_by(user_id=user.id).all()]


def _authorized_ids(proposal) -> set[int]:
    """The FROZEN signer snapshot taken when the proposal was created, not current membership."""
    return set(json.loads(proposal.authorized_signers_snapshot))


def _proposal_summary(proposal, user) -> dict:
    approvals, rejections = approval_service.tally(proposal)
    eligible = eligibility.eligible_ids(proposal)
    outlook = eligibility.outlook(
        proposal,
        approvals=approvals,
        voted=[s.signer_id for s in proposal.signatures],
        eligible=eligible,
    )
    can_still_pass = inbox_service.effective_status(proposal) != "open" or outlook.reachable
    return {
        **_summary_facts(
            proposal, user, approvals, rejections, eligible=eligible, can_still_pass=can_still_pass
        ),
        "proposal_uuid": proposal.proposal_uuid,
        "title": proposal.title,
        "vault_id": proposal.vault_id,
        "vault_name": proposal.vault.name if proposal.vault else None,
        "status": proposal.status,
        "required_m": proposal.required_m,
        "required_n": proposal.required_n,
        "approvals": approvals,
        "rejections": rejections,
        "expires_at": proposal.expires_at.isoformat() if proposal.expires_at else None,
        "signed_by_me": approval_service.vote_of(proposal, user.id) is not None,
        # Whether the vote endpoint would let this user sign: the frozen signer set AND an
        # approver of the vault now, in good standing (``eligibility``, owner decision 2026-10-08).
        "can_sign": user.id in eligible,
        # Additive (R5): who can still approve it, and whether they are enough to decide it. An
        # open decision whose approvers were demoted, removed or suspended can stop being able to
        # pass; it stays open until its deadline rather than being rejected for them.
        "can_still_approve": list(outlook.still),
        "can_still_pass": can_still_pass,
        # Why it can't, one sentence per cause that holds now, as the web's banner says it
        # (eligibility.shortfall); empty while it can still pass.
        "cannot_pass_why": (
            []
            if can_still_pass
            else evidence.shortfall_lines(
                eligibility.shortfall(proposal), evidence_service.names_for(proposal), user.id
            )
        ),
        # A1 and plan S15, for the phone's personal status (mobile/src/logic/personalStatus.ts).
        "raised_by": {
            "id": proposal.creator_id,
            "name": proposal.creator.display_name if proposal.creator else None,
        },
        "separation_of_duties": not eligibility.requester_may_approve(proposal),
        # Plan S16 (A11): who may withdraw it, and who did and when (personalStatus row 15).
        "can_withdraw": approval_service.why_cannot_withdraw(proposal, user) is None,
        **_lifecycle_view(proposal),
        # Safe for an old app to receive: summaries are parsed leniently, and it lets the inbox
        # say "payment" before the detail refuses with upgrade_required.
        "is_payment": proposal.action is not None,
        # Plan S13: the type its signed text bears out (``decision_types.typed_view``), as the
        # web's rows show it, so a row edited behind the decision's back lists as General. The
        # detail sends the stored type and fields, for the phone to check against the signed text.
        "decision_type": decision_types.typed_view(proposal).type,
        # A3: everyone in its signed signer set, by id, with a name and whether they hold a key.
        "signers": _signers_view(proposal),
        # A4: when it was decided (approved, rejected, withdrawn or expired); null while open.
        "decided_at": _decided_at(proposal),
        **(_payment_summary(proposal, user) if proposal.action is not None else {}),
    }


def _type_facts(proposal) -> tuple[str, dict | None, int | None]:
    """Its type, stored fields and template version, as stored (plan S13). Unsigned: a payment's
    fields are its signed ``action``, and a typed decision's are for the phone to check against
    its signed text (``mobile/src/logic/decisionTypes.ts``), never the other way round."""
    if proposal.action is not None:
        return "payment", None, None
    stored = proposal.typed
    if stored is None:
        return "general", None, None
    return stored.decision_type, stored.fields(), stored.template_version


def _signers_view(proposal) -> list[dict]:
    """A3: the frozen signer set with names (unsigned) and ``has_key``: whether each holds an
    active key that can sign now, password-held or on a phone."""
    ids = sorted(_authorized_ids(proposal))
    if not ids:
        return []
    people = {u.id: u for u in User.query.filter(User.id.in_(ids)).all()}
    keyed = set(
        db.session.scalars(
            db.select(Key.owner_id).where(
                Key.owner_id.in_(ids),
                Key.role == "sig",
                Key.status == "active",
                Key.can_sign.is_(True),
            )
        )
    )
    return [
        {
            "user_id": uid,
            "name": people[uid].display_name if uid in people else None,
            "has_key": uid in keyed,
        }
        for uid in ids
    ]


def _decided_at(proposal) -> str | None:
    """When it stopped being open, by its effective status; None while it is open."""
    lifecycle = proposal.lifecycle
    when = {
        "approved": proposal.approved_at,
        "rejected": proposal.rejected_at,
        "withdrawn": lifecycle.withdrawn_at if lifecycle is not None else None,
        "expired": proposal.expires_at,
    }.get(inbox_service.effective_status(proposal))
    return when.isoformat() if when is not None else None


def _payment_summary(proposal, user) -> dict:
    """A2 and A17 for a payment's row: its amount for display, and which of the caller's keys
    the treasury holds (``seat``), so a row can say where it can be approved before the detail is
    opened. The detail's ``execution.seat_fingerprint`` is the claim the phone checks."""
    value = proposal.action.value_wei
    readable = isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 78
    return {
        "amount": format_wei(int(value)) if readable else None,
        "seat": _seat(proposal, user),
    }


def _seat(proposal, user) -> str | None:
    """``this_device``, ``password``, ``other_device``, or None when the treasury holds no key
    for ``user``."""
    treasury = proposal.action.treasury
    if treasury is None:
        return None
    seat = TreasurySigner.query.filter_by(treasury_id=treasury.id, user_id=user.id).one_or_none()
    if seat is None or seat.key is None:
        return None
    device = getattr(g, "api_device", None)
    if device is not None and seat.key.id == device.key_id:
        return "this_device"
    return "password" if seat.key.wrap_domain == "password" else "other_device"


def _lifecycle_view(proposal) -> dict:
    """How it was withdrawn and raised again (plan S16); unsigned, shown only."""
    lifecycle = proposal.lifecycle
    withdrawn_by = lifecycle.withdrawn_by if lifecycle is not None else None
    source = lifecycle.raised_again_from if lifecycle is not None else None
    return {
        # A11: "Raised again from" and the forward links, each a decision in the same vault.
        "raised_again_from": (
            {"proposal_uuid": source.proposal_uuid, "title": source.title}
            if source is not None
            else None
        ),
        "raised_again_as": [
            {"proposal_uuid": p.proposal_uuid, "title": p.title}
            for p in proposal_service.raised_again_as(proposal)
        ],
        "withdrawn_by": (
            {"id": withdrawn_by.id, "name": withdrawn_by.display_name}
            if withdrawn_by is not None
            else None
        ),
        "withdrawn_at": (
            lifecycle.withdrawn_at.isoformat()
            if lifecycle is not None and lifecycle.withdrawn_at
            else None
        ),
    }


def _summary_facts(
    proposal,
    user,
    approvals: int,
    rejections: int,
    *,
    eligible: set[int] | None = None,
    can_still_pass: bool = True,
) -> dict:
    """The status as every web list says it (rework S6): ``display_status`` is the key of the
    closed vocabulary with its word and tone, from the same ``inbox_service.status_key`` the Home
    lists and the inbox use. Additive: ``status`` stays the stored value the app already reads,
    and the app may show this word instead of working one out."""
    status = inbox_service.effective_status(proposal)
    # The same test as this API's awaiting list (may sign it now, not yet voted), so a row in it
    # never says Waiting on N; it is the vote route's own rule (``eligibility``).
    if eligible is None:
        eligible = eligibility.eligible_ids(proposal)
    needs_me = (
        status == "open"
        and user.id in eligible
        and approval_service.vote_of(proposal, user.id) is None
    )
    payout = payout_service.payout_of(proposal) if proposal.action is not None else None
    key, n = inbox_service.status_key(
        status,
        needs_me=needs_me,
        approvals=approvals,
        required_m=proposal.required_m,
        payment=proposal.action is not None,
        payout_state=payout.state if payout is not None else None,
        treasuries_on=bool(current_app.config.get("ONCHAIN_EXECUTION_ENABLED")),
        can_still_pass=can_still_pass,
    )
    word, tone = status_of(key, n)
    return {"display_status": {"key": key, "word": word, "tone": tone}}


def _payment_view(stored) -> dict:
    """How a payment decision's payment is shown. The signed values are in ``signing_inputs``.

    Built from the same canonical form that is hashed, and defensive about a row edited at the
    database level: a tampered value shows as unreadable rather than turning the request into a
    500 (review L6). The binding check is what reports the tampering.
    """
    signed = stored.canonical()
    value = signed["value_wei"]
    readable = isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 78
    try:
        until = datetime.fromtimestamp(signed["valid_until"], UTC).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        until = None
    return {
        "kind": signed["kind"],
        "to": signed["to"],
        "value_wei": value,
        "amount": format_wei(int(value)) if readable else None,
        "treasury": signed["treasury"],
        "chain_id": signed["chain_id"],
        "network": (
            NETWORKS.get(signed["chain_id"]) if isinstance(signed["chain_id"], int) else None
        ),
        "call_gas": signed["call_gas"],
        "valid_until": until,
    }


def _execution_view(proposal, user) -> dict:
    """What the phone checks before it signs a payment's execution digest (plan Phase 6b).

    ``digest`` is this server's digest, which the phone recomputes from ``signing_inputs`` and
    refuses to sign if they differ; ``seat_fingerprint`` is the fingerprint of the key the
    treasury holds for this user, so the phone can tell before any prompt whether an approval made
    on it would count. Both are claims the phone checks, never inputs it signs.
    """
    try:
        digest = execution_service.digest_for(proposal).hex()
    except execution_service.ExecutionSignatureError:
        digest = None  # an unreadable row; the binding check and the vote say why
    action = proposal.action
    seat = None
    if action.treasury is not None:
        seat = TreasurySigner.query.filter_by(
            treasury_id=action.treasury.id, user_id=user.id
        ).one_or_none()
    return {
        "digest": digest,
        "seat_fingerprint": (
            seat.key.public_fingerprint() if seat is not None and seat.key is not None else None
        ),
    }


@bp.get("/proposals")
@device_token_required
def list_proposals():
    user = g.api_user
    state = request.args.get("state", "awaiting")
    vault_ids = _visible_vault_ids(user)
    if not vault_ids:
        return jsonify(ok=True, proposals=[], state=state)

    query = Proposal.query.filter(Proposal.vault_id.in_(vault_ids))
    if state == "awaiting":
        query = query.filter(Proposal.status == "open")
    proposals = query.order_by(Proposal.id.desc()).limit(200).all()

    out = []
    for p in proposals:
        summary = _proposal_summary(p, user)
        if state == "awaiting" and (summary["signed_by_me"] or not summary["can_sign"]):
            continue
        if state == "awaiting" and inbox_service.effective_status(p) != "open":
            # Its deadline passed and the sweep has not run yet: it can no longer take a
            # signature, so it is not awaiting one (rework S20).
            continue
        out.append(summary)
    return jsonify(ok=True, proposals=out, state=state)


@bp.get("/proposals/<uuid>")
@device_token_required
def proposal_detail(uuid: str):
    user = g.api_user
    proposal = Proposal.query.filter_by(proposal_uuid=uuid).first()
    if proposal is None or proposal.vault_id not in _visible_vault_ids(user):
        return _error("unknown_proposal", "No such proposal.", 404)
    if proposal.action is not None and not _handles_payments():
        return _upgrade_required()

    approval_service.refresh_expiry(proposal)
    detail = _proposal_summary(proposal, user)
    file_sha = proposal.file.content_sha256 if proposal.file is not None else None
    signing_inputs = {
        "vault_id": proposal.vault_id,
        "proposal_id": proposal.proposal_uuid,
        "action_text": proposal.action_text,
        "file_sha256": file_sha,
        "policy": {
            "M": proposal.required_m,
            "N": proposal.required_n,
            "signers": sorted(_authorized_ids(proposal)),
        },
        "nonce": proposal.nonce.hex(),
        "created_at": proposal.created_at_iso,
    }
    if proposal.action is not None:
        # Present only for payments, so every other decision's inputs keep their exact key set.
        signing_inputs["action"] = proposal.action.canonical()
        detail["payment"] = _payment_view(proposal.action)
        detail["execution"] = _execution_view(proposal, user)
        # How the payout stands (Phase 8): shown, never signed.
        detail["payout"] = payout_service.view(proposal)
    _type, fields, version = _type_facts(proposal)
    detail.update(
        {
            # Plan S13 (A13): a typed decision's stored type, its fields and the template version
            # that wrote its text. Unsigned; fields are null for General and Payment (a payment's
            # are signing_inputs.action). As stored, unlike the summary's type: the phone writes
            # the text again from them and refuses when it differs (``type_text``).
            "decision_type": _type,
            "fields": fields,
            "template_version": version,
            "action_text": proposal.action_text,
            # The complete canonical inputs, so the device can recompute payload_hash itself and
            # refuse to sign if this server's answer disagrees. Do not trim this to the hash.
            "signing_inputs": signing_inputs,
            "payload_hash": proposal.payload_hash,
            "signing_bytes_sha256": sha256_hex(signing_bytes_for(proposal)),
            # A16 (plan S16): a rejection must carry a reason; the vote endpoint refuses one
            # without (``reason_required``). The reason is shown, never signed.
            "reject_reason_required": True,
            "votes": [
                {
                    "signer_id": s.signer_id,
                    "signer_name": s.signer.display_name if s.signer else None,
                    "decision": s.decision,
                    "custody": s.custody,
                    "alg_id": s.alg_id,
                    "reason": s.reason,
                    "signed_at": s.created_at.isoformat() if s.created_at else None,
                }
                for s in proposal.signatures
            ],
        }
    )
    return jsonify(ok=True, proposal=detail)


@bp.post("/proposals/<uuid>/vote")
@device_token_required
def cast_vote(uuid: str):
    user, device = g.api_user, g.api_device
    proposal = Proposal.query.filter_by(proposal_uuid=uuid).first()
    if proposal is None or proposal.vault_id not in _visible_vault_ids(user):
        return _error("unknown_proposal", "No such proposal.", 404)
    if proposal.action is not None and not _handles_payments():
        # An app that cannot show the payment must not be able to approve it (plan D25).
        return _upgrade_required()

    body = _body()
    try:
        sig_bytes = _b64(body.get("signature_b64", ""), "signature_b64")
        # Approving a payment carries the signature over the execution digest (plan Phase 6b);
        # record_device_vote decides whether this vote must, or must not, carry one.
        raw_execution = body.get("execution_signature_b64")
        execution = (
            None
            if raw_execution is None
            else (
                _b64(raw_execution, "execution_signature_b64")
                if isinstance(raw_execution, str)
                # Not a string: decoded as empty, so the length check refuses it with a reason.
                else b""
            )
        )
    except DeviceError as exc:
        return _error(exc.code, exc.message, 400)
    reason = body.get("reason")
    if reason is not None and not isinstance(reason, str):
        return _error("reason_required", approval_service.REASON_NOT_TEXT, 422)

    # The key comes from the authenticated device, never from the request body. That is an
    # authorisation property, not a convenience: a token can only ever vote with its own key.
    try:
        sig = approval_service.record_device_vote(
            proposal,
            user,
            device.key,
            body.get("decision", ""),
            sig_bytes,
            reason=reason,
            execution=execution,
        )
    except ApprovalError as exc:
        return _error(_vote_code(str(exc)), str(exc), _VOTE_STATUS.get(_vote_code(str(exc)), 422))

    approvals, rejections = approval_service.tally(proposal)
    return (
        jsonify(
            ok=True,
            vote={
                "id": sig.id,
                "decision": sig.decision,
                "custody": sig.custody,
                "alg_id": sig.alg_id,
                "signature_sha256": sha256_hex(sig.signature),
                # What was stored as the authorisation to pay, for the phone to compare with what
                # it sent, as it does the vote's.
                "execution_signature_sha256": (
                    sha256_hex(execution) if execution is not None else None
                ),
                "signed_at": sig.created_at.isoformat() if sig.created_at else None,
            },
            proposal={
                "status": proposal.status,
                "approvals": approvals,
                "rejections": rejections,
            },
        ),
        201,
    )


_VOTE_STATUS = {
    "already_voted": 409,
    "not_a_signer": 403,
    "own_decision": 403,
    "reason_required": 422,
    "proposal_closed": 422,
    "signature_invalid": 422,
    "device_key_not_active": 422,
    "decision_invalid": 422,
    "bad_signature_size": 422,
    "execution_signature_required": 422,
    # D43: the treasury's nonce could not be read. Nothing was stored; the phone offers a retry.
    "chain_unavailable": 503,
}


def _vote_code(message: str) -> str:
    """Map a service message to a stable code a client can branch on without parsing English."""
    lowered = message.lower()
    # First: an app that declared the payment capability and still sent a bare approval is told so
    # in a form it can act on (plan D25), whatever else the sentence happens to contain.
    if "signature the treasury checks" in lowered:
        return "execution_signature_required"
    if "could not be asked" in lowered:
        return "chain_unavailable"
    # Plan S15, before the generic "approve ... reject" test below, which its sentence would match.
    if "you raised this" in lowered:
        return "own_decision"
    # Plan S16 (A16): a rejection without a reason, or with one too long.
    if "add a reason" in lowered or "keep the reason" in lowered:
        return "reason_required"
    if "already voted" in lowered:
        return "already_voted"
    if "not an authorised signer" in lowered:
        return "not_a_signer"
    if "no further votes" in lowered:
        return "proposal_closed"
    if "did not verify" in lowered:
        return "signature_invalid"
    if "revoked" in lowered or "not device-custodied" in lowered or "does not belong" in lowered:
        return "device_key_not_active"
    if "must be" in lowered and "bytes" in lowered:
        return "bad_signature_size"
    if "approve" in lowered and "reject" in lowered:
        return "decision_invalid"
    return "vote_rejected"


# -- notifications (plan R4) ----------------------------------------------------------------------
#
# The phone's inbox. Every query is by recipient, so an id that belongs to someone else is a 404
# like an id that does not exist. Nothing here approves anything: a notification is a link to a
# decision, and the vote endpoint above is the only way to sign (S12).


def _whole(name: str, default: int, low: int, high: int) -> int | None:
    """A whole-number query parameter in [low, high], or None when it is not one."""
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if low <= value <= high else None


@bp.get("/notifications")
@device_token_required
def list_notifications():
    """One section of the inbox, newest first: ``needs_you``, ``updates`` or ``archived``."""
    section = request.args.get("section", "needs_you")
    if section not in notification_service.SECTIONS:
        return _error(
            "bad_request",
            f"section must be one of {', '.join(notification_service.SECTIONS)}.",
            400,
        )
    page = _whole("page", 1, 1, notification_service.MAX_PAGE)
    per_page = _whole(
        "per_page", notification_service.PER_PAGE, 1, notification_service.MAX_PER_PAGE
    )
    if page is None or per_page is None:
        return _error(
            "bad_request",
            f"page must be 1 or more and per_page 1 to {notification_service.MAX_PER_PAGE}.",
            400,
        )
    result = notification_service.inbox(g.api_user, section, page=page, per_page=per_page)
    return jsonify(
        ok=True,
        section=result.section,
        page=result.page,
        per_page=result.per_page,
        total=result.total,
        has_more=result.has_more,
        notifications=result.items,
        unread=notification_service.unread_counts(g.api_user),
    )


@bp.get("/notifications/unread")
@device_token_required
def unread_notifications():
    """The badge: unread in Needs you, in Updates, and both."""
    return jsonify(ok=True, unread=notification_service.unread_counts(g.api_user))


@bp.post("/notifications/<int:nid>/read")
@device_token_required
def read_notification(nid: int):
    item = notification_service.mark_read(g.api_user, nid)
    if item is None:
        return _error("unknown_notification", "No such notification.", 404)
    return jsonify(
        ok=True, notification=item, unread=notification_service.unread_counts(g.api_user)
    )


@bp.post("/notifications/read-all")
@device_token_required
def read_all_notifications():
    """Mark every unread notification read, or only one section's (``{"section": ...}``)."""
    section = _body().get("section")
    if section is not None and section not in ("needs_you", "updates"):
        return _error("bad_request", "section must be needs_you or updates.", 400)
    marked = notification_service.mark_all_read(g.api_user, section=section)
    return jsonify(ok=True, marked=marked, unread=notification_service.unread_counts(g.api_user))


@bp.post("/notifications/<int:nid>/archive")
@device_token_required
def archive_notification(nid: int):
    item = notification_service.archive(g.api_user, nid)
    if item is None:
        return _error("unknown_notification", "No such notification.", 404)
    return jsonify(
        ok=True, notification=item, unread=notification_service.unread_counts(g.api_user)
    )


@bp.post("/proposals/<uuid>/withdraw")
@device_token_required
def withdraw_proposal(uuid: str):
    """The person who raised an open decision withdraws it (plan S16, A11). Nothing is signed: it
    ends the decision, and the phone's own check of who raised it is only a display."""
    user = g.api_user
    proposal = Proposal.query.filter_by(proposal_uuid=uuid).first()
    if proposal is None or proposal.vault_id not in _visible_vault_ids(user):
        return _error("unknown_proposal", "No such proposal.", 404)
    try:
        approval_service.withdraw(proposal, user)
    except ApprovalError as exc:
        message = str(exc)
        if message == approval_service.NOT_YOURS_TO_WITHDRAW:
            return _error("not_requester", message, 403)
        if "can't be withdrawn" in message:
            return _error("proposal_closed", message, 409)
        return _error("withdraw_refused", message, 403)
    return jsonify(ok=True, proposal=_proposal_summary(proposal, user))


@bp.get("/proposals/<uuid>/comments")
@device_token_required
def list_comments(uuid: str):
    """A decision's discussion, oldest first, for the phone (rework R5). Read only.

    The same people who can open the decision can read it. Comments are unsigned and the
    response says so; ``segments`` gives each comment as runs of text and resolved mentions, so a
    client draws a mention only where the server resolved one. Paged by comment id: ``after`` is
    the last id the client has, ``limit`` at most 100.
    """
    user = g.api_user
    proposal = Proposal.query.filter_by(proposal_uuid=uuid).first()
    if proposal is None or proposal.vault_id not in _visible_vault_ids(user):
        return _error("unknown_proposal", "No such proposal.", 404)
    limit = _whole("limit", 50, 1, 100)
    after = _whole("after", 0, 0, 2**31 - 1)
    if limit is None or after is None:
        return _error("bad_request", "limit and after must be whole numbers.", 400)
    rows = discussion_service.thread(proposal, user, after=after or None, limit=limit + 1)
    more = len(rows) > limit
    rows = rows[:limit]
    return jsonify(
        ok=True,
        signed=False,
        note=discussion_service.UNSIGNED_NOTE,
        can_post=discussion_service.why_cannot_post(proposal, user) is None,
        comments=[
            {
                "id": c["id"],
                "author": {"id": c["author_id"], "name": c["author"]},
                "created_at": c["created_at"].isoformat() if c["created_at"] else None,
                "deleted": c["deleted"],
                "mine": c["mine"],
                "body": "".join(part["text"] for part in c["segments"]),
                "segments": [
                    {"text": part["text"], "mention": part.get("mention")} for part in c["segments"]
                ],
            }
            for c in rows
        ],
        next_after=rows[-1]["id"] if more and rows else None,
    )


@bp.post("/proposals/<uuid>/remind")
@device_token_required
def remind_approvers(uuid: str):
    """The requester reminds the approvers who have not voted; at most once a day per decision."""
    user = g.api_user
    proposal = Proposal.query.filter_by(proposal_uuid=uuid).first()
    if proposal is None or proposal.vault_id not in _visible_vault_ids(user):
        return _error("unknown_proposal", "No such proposal.", 404)
    try:
        reminded = notification_service.remind(proposal, user)
    except notification_service.RemindRefused as exc:
        return _error("remind_refused", str(exc), 409)
    return jsonify(ok=True, reminded=reminded)
