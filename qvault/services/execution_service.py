"""Execution signatures: what a treasury checks before it pays (plan Phase 6a).

Approving a payment decision produces two signatures from one password. The first is the vote —
this server verifies it, and a person is held to it. The second is this one: a signature over
``QVaultTreasury.executionDigest``, the 32 bytes the *contract* checks on chain before it moves
any ETH. The server's opinion of it is worth nothing; the only verifier that matters is Ethereum.

That makes the pairing rules strict. A treasury counts keys, not people (``TreasurySigner``), so
an approval is useless unless it was made with the exact key registered for that signer. A
rotated key, a phone chosen where a password key is registered, or a treasury that has been
unlinked are all refused *before* the password is spent, with the remedy named — because a vote
recorded without the signature that lets it execute is a decision nobody can carry out.

**What this module cannot know is whether the payment row is the payment that was signed.** The
digest is built from ``proposal_actions``, and the contract checks nothing else, so a row edited
before anyone approves would be signed faithfully by every honest approver. Only the decision's
binding check can rule that out; ``approval_service`` makes it before asking for a digest.
"""

from __future__ import annotations

import json

from flask import current_app

from qvault import glassbox
from qvault.chain import action as chain_action
from qvault.chain import digest as chain_digest
from qvault.extensions import db
from qvault.models import ExecutionSignature, TreasurySigner
from qvault.services.treasury_service import ALGORITHM


class ExecutionSignatureError(Exception):
    """An execution signature could not be produced, or is not one the contract would accept."""


def is_payment(proposal) -> bool:
    """Whether this decision authorises a payment, and so needs an execution signature."""
    return proposal.action is not None


def digest_for(proposal) -> bytes:
    """The 32 bytes an approver signs for ``proposal``'s payment.

    Recomputed from the stored action every time, never cached: the signature is only meaningful
    against bytes derived from what the database says *now*, which is exactly what makes a
    tampered action row show up as signatures that no longer verify.

    The row is read through the same strict D22 parser a signed payload passes, so a field edited
    into another shape (call data without its ``0x``, a lower-case address) is refused rather
    than coerced into a payment nobody signed.
    """
    stored = proposal.action
    if stored is None:
        raise ExecutionSignatureError("this decision authorises no payment")
    signed = stored.canonical()
    with glassbox.step(
        "Build what the treasury will check", code=chain_digest.execution_digest
    ) as trace:
        trace.annotate(
            "The contract computes these same 32 bytes from the transaction it is asked to make. "
            "An approver's signature is over this digest, so the chain, not this server, decides "
            "whether the payment it authorises is the payment being executed."
        )
        trace.input("payment", glassbox.Text(json.dumps(signed, sort_keys=True).encode()))
        trace.input("proposal payload hash", glassbox.Digest(proposal.payload_hash))
        try:
            computed = chain_action.parse(signed).execution_digest(proposal.payload_hash)
        except ValueError as exc:  # ActionError and ChainValueError are both ValueErrors
            # A row edited at the database level: say so plainly rather than raising something the
            # vote path would report as an internal error.
            raise ExecutionSignatureError(
                f"this decision's payment cannot be read ({exc})"
            ) from None
        trace.output("execution digest", glassbox.Hex(computed))
    return computed


def approval_problem(proposal, signer, key) -> str | None:
    """Why ``signer`` cannot approve this payment with ``key``, in words they can act on.

    Returns ``None`` when the contract would accept an approval made with this key.
    """
    return _seat(proposal, signer, key)[1]


def _seat(proposal, signer, key) -> tuple[TreasurySigner | None, str | None]:
    """The treasury's row for ``signer``, and why ``key`` cannot approve through it, if it can't."""
    action = proposal.action
    if action is None:
        return None, None
    treasury = action.treasury
    if (
        treasury is None
        or not treasury.is_linked
        or treasury.vault_id != proposal.vault_id
        or treasury.chain_id != action.chain_id
        or treasury.address != action.treasury_address
    ):
        return None, (
            "This vault is no longer linked to the treasury this payment names, so the payment "
            "could not be executed. Raise the decision again once a treasury is linked."
        )

    registered = TreasurySigner.query.filter_by(
        treasury_id=treasury.id, user_id=signer.id
    ).one_or_none()
    if registered is None:
        return None, (
            "None of your keys is registered on this vault's treasury, so the contract would not "
            "count your approval. The treasury must be reconfigured to register one."
        )
    if registered.key_id != key.id:
        return registered, _wrong_key(registered.key, key)
    if key.alg_id != ALGORITHM:
        return registered, (
            f"A treasury verifies {ALGORITHM} signatures only, and your registered key is "
            f"{key.alg_id}. The treasury must be reconfigured before you can approve a payment."
        )
    return registered, None


def _wrong_key(held, key) -> str:
    """Why ``key`` is not the key the treasury holds for this signer (``held``), and what fixes it.

    Sending someone to a key that can no longer sign would name a remedy they cannot use: a phone
    that has been revoked stays registered on the treasury until a reconfiguration replaces it.
    """
    reconfigure = "The treasury must be reconfigured to register your current key."
    held_on_device = held is not None and held.wrap_domain == "device"
    if held is None or held.status != "active" or not held.can_sign:
        what = "a phone" if held_on_device else "an earlier key of yours"
        return (
            f"This vault's treasury holds {what} that can no longer sign, so the contract would "
            f"not count your approval. {reconfigure}"
        )
    if held_on_device:
        return (
            "This vault's treasury holds your phone's key, so this payment must be approved on "
            "your phone."
            if key.wrap_domain != "device"
            else "This vault's treasury holds the key of another of your phones, so this payment "
            "must be approved on that phone."
        )
    if key.wrap_domain == "device":
        return (
            "This vault's treasury holds your password key, so this payment must be approved in "
            "the web app."
        )
    return (
        "This vault's treasury holds an earlier key of yours, not the one you sign with now, so "
        f"the contract would not count your approval. {reconfigure}"
    )


def record(proposal, signer, key, digest: bytes, signature: bytes) -> ExecutionSignature:
    """Check ``signature`` is one the treasury would count, and add the row to the caller's
    transaction.

    Everything is checked here, whoever produced the signature and whatever the caller checked
    before: that ``key`` is the signer's, that it is still the key the treasury holds for them (a
    treasury can be unlinked while a password is being checked), and that the signature verifies.
    On the web path this server signed it moments ago and has already verified it (ADR-0010), so
    this is defence in depth; on the phone path it is the first and only check made before bytes
    from a client are stored as an authorisation to move money. The same code has to be right for
    both.

    ``digest`` must come from ``digest_for`` on a decision whose binding was checked first: a
    digest over a tampered row verifies here exactly as well as an honest one.
    """
    if proposal.action is None:
        raise ExecutionSignatureError(
            "This decision authorises no payment, so it takes no execution signature."
        )
    if key.owner_id != signer.id:
        raise ExecutionSignatureError("That key does not belong to you.")
    registered, problem = _seat(proposal, signer, key)
    if problem is not None:
        raise ExecutionSignatureError(problem)

    provider = current_app.extensions["crypto"].signature(key.alg_id)
    expected = provider.meta.sizes["signature"]
    if len(signature) != expected:
        raise ExecutionSignatureError(
            f"An execution signature under {key.alg_id} must be {expected} bytes, "
            f"got {len(signature)}."
        )
    with glassbox.step(
        "Verify the execution signature under the registered key", code=provider.verify
    ) as trace:
        trace.annotate(
            "The treasury will make this same check on chain. It is made here first so that an "
            "approval the contract would refuse is never recorded as one it would accept."
        )
        trace.input("public key", glassbox.Hex(key.public_key))
        trace.input("execution digest", glassbox.Hex(digest))
        trace.input("signature", glassbox.Hex(signature))
        accepted = provider.verify(key.public_key, digest, signature)
        trace.output("accepted", glassbox.Label(accepted))
    if not accepted:
        raise ExecutionSignatureError(
            "The execution signature did not verify under your registered key; nothing recorded."
        )

    row = ExecutionSignature(
        proposal_id=proposal.id,
        signer_id=signer.id,
        key_id=key.id,
        alg_id=key.alg_id,
        backend=key.backend,
        public_key=key.public_key,
        digest=digest,
        signature=signature,
        identity_hex=registered.identity_hex,
    )
    db.session.add(row)
    return row


def signatures_for(proposal) -> list[ExecutionSignature]:
    """Every execution signature stored for ``proposal``, oldest first."""
    return (
        ExecutionSignature.query.filter_by(proposal_id=proposal.id)
        .order_by(ExecutionSignature.id)
        .all()
    )
