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

from flask import Blueprint, g, jsonify, request

from qvault.crypto import sha256_hex
from qvault.extensions import db
from qvault.models.proposal import Proposal
from qvault.models.vault import VaultMember
from qvault.security.decorators import device_token_required
from qvault.services import (
    approval_service,
    auth_service,
    device_service,
    key_service,
)
from qvault.services.approval_service import ApprovalError
from qvault.services.device_service import DeviceError
from qvault.services.signing import signing_bytes_for

bp = Blueprint("api", __name__, url_prefix="/api/v1")

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

    approval_service.refresh_expiry(proposal)
    detail = _proposal_summary(proposal, user)
    file_sha = proposal.file.content_sha256 if proposal.file is not None else None
    detail.update(
        {
            "action_text": proposal.action_text,
            # The complete canonical inputs, so the device can recompute payload_hash itself and
            # refuse to sign if this server's answer disagrees. Do not trim this to the hash.
            "signing_inputs": {
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
            },
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
