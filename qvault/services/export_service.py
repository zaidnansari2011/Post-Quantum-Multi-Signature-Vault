"""Build a self-contained, independently verifiable record of one decision.

The exported file is the point of the whole transparency layer. Everything else — the Merkle
tree, the checkpoints, the witness — exists so that this file can be checked by somebody with no
account, no network connection and no reason to believe us.

What goes in, and why each part is not optional
-----------------------------------------------
* **the decision's canonical fields**, so the verifier recomputes ``payload_hash`` rather than
  being told it;
* **every signature**, with the algorithm and public key pinned per signature, because a decision
  may legitimately carry signatures made under different algorithms — that is what crypto-agility
  looks like once it has been used;
* **the log's own entries** for the events, so the verifier can recompute their hashes;
* **the registration entries for each signer**, which is what binds "signer 3" to an email address
  in the log rather than in the exporter's cover letter;
* **an inclusion proof per entry**, ``log2(n)`` hashes each, which is why this is an email
  attachment and not a database dump;
* **the signed checkpoint** those proofs are against;
* **every witness co-signature** on that checkpoint, which is the only part an adversary who owns
  this server cannot manufacture.

Choosing the checkpoint
-----------------------
The *oldest* checkpoint that covers the entries, not the newest. A proof against a checkpoint that
a witness co-signed an hour ago is worth more than one against a checkpoint minted during this
request that nothing outside this process has ever seen.
"""

from __future__ import annotations

import io
import json
import pathlib
import zipfile
from base64 import b64encode
from datetime import UTC, datetime

from sqlalchemy import or_, select

from qvault.extensions import db
from qvault.models.ledger import LedgerEntry
from qvault.models.proposal import Proposal
from qvault.services import checkpoint_service
from qvault.verify import BUNDLE_FORMAT


def _entries_for(proposal: Proposal, signer_ids: list[int]) -> list[LedgerEntry]:
    """Every ledger entry a verifier needs: this decision's events, plus each signer's
    registration so identities are bound by the log and not by this file's own labelling."""
    return list(
        db.session.execute(
            select(LedgerEntry)
            .where(
                or_(
                    (LedgerEntry.ref_type == "proposal")
                    & (LedgerEntry.ref_id == proposal.proposal_uuid),
                    (LedgerEntry.event_type == "user_registered")
                    & (LedgerEntry.ref_id.in_([str(i) for i in signer_ids])),
                )
            )
            .order_by(LedgerEntry.seq)
        )
        .scalars()
        .all()
    )


def build_decision_bundle(proposal: Proposal, *, sync_witness: bool = True) -> dict:
    """Assemble the bundle. Creates a checkpoint on demand if the newest events are not yet in one."""
    signatures = sorted(proposal.signatures, key=lambda s: s.created_at)
    signer_ids = [s.signer_id for s in signatures]
    entries = _entries_for(proposal, signer_ids)
    if not entries:
        raise checkpoint_service.LogError(
            f"no ledger entries found for proposal {proposal.proposal_uuid}"
        )

    highest = max(e.seq for e in entries)
    checkpoint = checkpoint_service.checkpoint_covering(highest)
    if checkpoint is None:
        # The events are newer than every checkpoint. Commit to them now — an export is exactly
        # the moment the log is being asked to stand behind these entries.
        checkpoint = checkpoint_service.create_checkpoint()

    if sync_witness and not checkpoint.cosignatures:
        # Offer the log's CURRENT head, never this particular checkpoint. The witness only moves
        # forward, so handing it an older checkpoint is at best refused and at worst recorded as a
        # `shrank` violation — a false accusation raised by entirely honest behaviour. Getting the
        # head witnessed and then re-resolving is the same thing done in the right order.
        #
        # Best effort, never fatal: an export from a log whose witness is unreachable is still a
        # valid export. It simply carries one fewer independent signature, and says so.
        checkpoint_service.sync_witness()
        db.session.expire_all()
        checkpoint = checkpoint_service.checkpoint_covering(highest) or checkpoint

    vault = proposal.vault
    file_sha = proposal.file.content_sha256 if proposal.file is not None else None

    return {
        "format": BUNDLE_FORMAT,
        "exported_at": datetime.now(UTC).isoformat(),
        "origin": checkpoint.origin,
        "decision": {
            "proposal_uuid": proposal.proposal_uuid,
            "title": proposal.title,
            "vault_id": proposal.vault_id,
            "vault_name": vault.name if vault else None,
            "action_text": proposal.action_text,
            "file_sha256": file_sha,
            "required_m": proposal.required_m,
            "required_n": proposal.required_n,
            "authorized_signers": json.loads(proposal.authorized_signers_snapshot),
            "nonce_hex": proposal.nonce.hex(),
            "created_at_iso": proposal.created_at_iso,
            "payload_hash": proposal.payload_hash,
            "status": proposal.status,
        },
        "signatures": [
            {
                "signer_id": s.signer_id,
                "signer_email": s.signer.email if s.signer else None,
                "signer_name": s.signer.display_name if s.signer else None,
                "decision": s.decision,
                "reason": s.reason,
                # Which half of ADR-0016 produced this. Additive and ignored by older
                # verifiers, which read the bundle with .get() rather than a strict schema.
                "custody": s.custody,
                "alg_id": s.alg_id,
                "backend": s.backend,
                "public_key_b64": b64encode(s.public_key).decode(),
                "signature_b64": b64encode(s.signature).decode(),
                "signed_payload_hash": s.signed_payload_hash,
                "signed_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in signatures
        ],
        "log": {
            "origin": checkpoint.origin,
            "checkpoint": checkpoint.statement(),
            "checkpoint_signature": {
                "alg_id": checkpoint.alg_id,
                "backend": checkpoint.backend,
                "public_key_b64": b64encode(checkpoint.key.public_key).decode(),
                "signature_b64": b64encode(checkpoint.signature).decode(),
            },
            "witnesses": [
                {
                    "witness": c.witness_name,
                    "alg_id": c.alg_id,
                    "backend": c.backend,
                    "public_key_b64": b64encode(c.public_key).decode(),
                    "signature_b64": b64encode(c.signature).decode(),
                }
                for c in checkpoint.cosignatures
            ],
            "entries": [
                {
                    "seq": e.seq,
                    "timestamp": e.timestamp,
                    "event_type": e.event_type,
                    "actor": e.actor,
                    "actor_id": e.actor_id,
                    "vault_id": e.vault_id,
                    "ref_type": e.ref_type,
                    "ref_id": e.ref_id,
                    "payload_json": e.payload_json,
                    "payload_hash": e.payload_hash,
                    "prev_hash": e.prev_hash,
                    "entry_hash": e.entry_hash,
                    "inclusion_proof": checkpoint_service.inclusion_proof_for(e.seq, checkpoint),
                }
                for e in entries
                if e.seq < checkpoint.tree_size
            ],
        },
    }


def transparency_status(proposal: Proposal) -> dict:
    """Where this decision stands in the log, for display beside it.

    Cheap on purpose — two queries, no proofs built — because this runs on every view of a
    decision page, while :func:`build_decision_bundle` runs only when someone exports.
    """
    highest = db.session.execute(
        select(db.func.max(LedgerEntry.seq)).where(
            LedgerEntry.ref_type == "proposal",
            LedgerEntry.ref_id == proposal.proposal_uuid,
        )
    ).scalar_one_or_none()
    if highest is None:
        return {"logged": False, "checkpoint": None, "witnesses": []}

    checkpoint = checkpoint_service.checkpoint_covering(highest)
    return {
        "logged": True,
        "seq": highest,
        "checkpoint": checkpoint,
        "witnesses": list(checkpoint.cosignatures) if checkpoint else [],
    }


def bundle_bytes(bundle: dict) -> bytes:
    """Serialise for download.

    Indented rather than canonical on purpose: nothing in verification depends on this file's
    byte layout — every hash and signature is checked against a form the verifier recomputes for
    itself — so the export may as well be legible to a human opening it in a text editor.
    """
    return json.dumps(bundle, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")


def bundle_filename(proposal: Proposal) -> str:
    stem = proposal.proposal_uuid.split("-")[0]
    return f"decision-{stem}.qvault.json"


# -- the downloadable package ---------------------------------------------------------------------

_README = """Q-Vault decision package
========================

  {title}
  {vault}
  Exported {exported}

This folder contains everything needed to check that the people named in this decision really
approved this exact text -- WITHOUT trusting the server that produced it, and without an account.

  certificate.html   The decision in readable form. Open it in any browser; print it to PDF.
  decision.json      The machine-checkable record: the decision, every signature, the public keys
                     needed to check them, and the transparency-log entries that place it in time.
  verifier.html      A self-contained verifier. No internet, no install, no npm.

TO VERIFY

  1. Open verifier.html in a browser.
  2. Load decision.json into it.

It re-derives the payload hash from the decision's own contents and checks every signature against
the public keys in the file. Change one character of the action text in decision.json and the
signatures stop matching -- which is the entire point.

The certificate is for reading. decision.json is the evidence.
"""


def build_decision_package(bundle: dict, *, certificate_html: str) -> bytes:
    """A single downloadable file that a person can read AND a machine can check.

    A bare .json is the honest artefact -- it is what the verifier consumes and what every
    signature is checked against -- but handed to somebody it reads as a debugging dump rather
    than a record of a decision. So the package leads with a certificate a human can open and
    print, keeps the JSON alongside as the thing that actually carries the proof, and includes the
    offline verifier so checking it needs nothing but a browser.

    Takes an already-built ``bundle`` rather than a proposal: ``build_decision_bundle`` can create
    a checkpoint and sync the witness, so calling it a second time here would mean one download
    committing the log twice.

    ``certificate_html`` is rendered by the caller: templates belong to the view layer, and this
    service must stay importable by the offline verifier's purity test.
    """
    verifier = pathlib.Path(__file__).resolve().parent.parent / "static" / "verifier.html"

    buffer = io.BytesIO()
    # Deflate rather than stored: verifier.html carries an inlined PQC bundle and compresses well.
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("certificate.html", certificate_html)
        archive.writestr("decision.json", bundle_bytes(bundle))
        if verifier.exists():
            archive.writestr("verifier.html", verifier.read_text(encoding="utf-8"))
        archive.writestr(
            "README.txt",
            _README.format(
                title=bundle["decision"]["title"],
                vault=bundle["decision"]["vault_name"] or f"Vault {bundle['decision']['vault_id']}",
                exported=bundle["exported_at"],
            ),
        )
    return buffer.getvalue()


def package_filename(proposal: Proposal) -> str:
    stem = proposal.proposal_uuid.split("-")[0]
    return f"decision-{stem}.qvault.zip"
