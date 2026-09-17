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

from qvault.chain.action import NETWORKS, format_wei
from qvault.crypto import sha256_hex
from qvault.extensions import db
from qvault.models.proposal import Proposal
from qvault.models.user import User
from qvault.models.vault import Vault, VaultMember
from qvault.security.decorators import device_token_required
from qvault.services import (
    approval_service,
    auth_service,
    device_service,
    key_service,
    proposal_service,
    vault_service,
)
from qvault.services.approval_service import ApprovalError
from qvault.services.device_service import DeviceError
from qvault.services.proposal_service import PaymentRequest, ProposalError
from qvault.services.signing import signing_bytes_for
from qvault.services.vault_service import MembershipError, PolicyError

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
    try:
        return base64.b64decode(raw or "", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise DeviceError("bad_request", f"{field} must be valid base64.") from exc


def _body() -> dict:
    return request.get_json(silent=True) or {}


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


@bp.get("/me")
@device_token_required
def whoami():
    user = g.api_user
    return jsonify(
        ok=True,
        user={"id": user.id, "email": user.email, "display_name": user.display_name},
        device=_device_json(g.api_device, current_id=g.api_device.id),
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
    for p in vault.proposals:
        if p.status != "open":
            continue
        if approval_service.vote_of(p, user.id) is not None:
            continue
        if user.id in set(json.loads(p.authorized_signers_snapshot)):
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

    Names are still personal data, so the set is kept to what building a vault needs: the caller is
    excluded, since they are already its owner and first signer.

    If this ever becomes multi-tenant, SCOPE THIS BEFORE THAT HAPPENS -- an unscoped directory
    would show one customer's staff to another. There is no tenant concept to scope by today, so
    the check cannot be written yet and is recorded here rather than left to be rediscovered.
    """
    user = g.api_user
    people = (
        User.query.filter(User.id != user.id).order_by(User.display_name.asc()).limit(500).all()
    )
    return jsonify(
        ok=True,
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
    for raw_id in body.get("member_ids") or []:
        try:
            person = db.session.get(User, int(raw_id))
        except (TypeError, ValueError):
            return _error("bad_member", "member_ids must be whole numbers.", 422)
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
    detail["members"] = [
        {
            "user_id": m.user_id,
            "name": m.user.display_name if m.user else None,
            "email": m.user.email if m.user else None,
            "role": m.member_role,
            "is_me": m.user_id == user.id,
        }
        for m in vault.members
    ]
    recent = sorted(vault.proposals, key=lambda p: p.id, reverse=True)[:50]
    detail["proposals"] = [_proposal_summary(p, user) for p in recent]
    return jsonify(ok=True, vault=detail)


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

    body = _body()
    title = (body.get("title") or "").strip()
    action_text = (body.get("action_text") or "").strip()
    payment = body.get("payment")
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
    if payment is None and not action_text:
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

    try:
        proposal = proposal_service.create_proposal(
            vault, user, title, action_text, deadline=deadline, payment=payment_request
        )
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
    return {
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
        "can_sign": user.id in _authorized_ids(proposal),
        # Safe for an old app to receive: summaries are parsed leniently, and it lets the inbox
        # say "payment" before the detail refuses with upgrade_required.
        "is_payment": proposal.action is not None,
    }


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
    detail.update(
        {
            "action_text": proposal.action_text,
            # The complete canonical inputs, so the device can recompute payload_hash itself and
            # refuse to sign if this server's answer disagrees. Do not trim this to the hash.
            "signing_inputs": signing_inputs,
            "payload_hash": proposal.payload_hash,
            "signing_bytes_sha256": sha256_hex(signing_bytes_for(proposal)),
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
    except DeviceError as exc:
        return _error(exc.code, exc.message, 400)

    # The key comes from the authenticated device, never from the request body. That is an
    # authorisation property, not a convenience: a token can only ever vote with its own key.
    try:
        sig = approval_service.record_device_vote(
            proposal,
            user,
            device.key,
            body.get("decision", ""),
            sig_bytes,
            reason=body.get("reason"),
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
    "proposal_closed": 422,
    "signature_invalid": 422,
    "device_key_not_active": 422,
    "decision_invalid": 422,
    "bad_signature_size": 422,
}


def _vote_code(message: str) -> str:
    """Map a service message to a stable code a client can branch on without parsing English."""
    lowered = message.lower()
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
