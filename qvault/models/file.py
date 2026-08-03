"""VaultFile model — a file stored encrypted at rest (AES-256-GCM + ML-KEM-wrapped key).

Only ciphertext touches the disk. The AES Data-Encryption-Key (DEK) is never stored in the
clear: it is wrapped using a key derived from an ML-KEM encapsulation to the vault's public
key. Decryption requires the vault's KEM private key (server-custodied). See §4.9.
"""

from __future__ import annotations

from datetime import UTC, datetime

from qvault.extensions import db


def _utcnow() -> datetime:
    return datetime.now(UTC)


class VaultFile(db.Model):
    __tablename__ = "files"

    id = db.Column(db.Integer, primary_key=True)
    proposal_id = db.Column(
        db.Integer, db.ForeignKey("proposals.id"), unique=True, nullable=False, index=True
    )

    filename = db.Column(db.String(255), nullable=False)
    content_sha256 = db.Column(
        db.String(64), nullable=False
    )  # hex of PLAINTEXT (bound in signature)
    ciphertext_path = db.Column(db.String(512), nullable=False)  # relative to the storage dir
    size_bytes = db.Column(db.Integer, nullable=False)

    aes_nonce = db.Column(db.LargeBinary(12), nullable=False)

    # ML-KEM key-wrap of the DEK. ``kem_key_id`` pins WHICH vault KEM key encapsulated this DEK,
    # so a rotated (retired-but-retained) key can still decrypt files uploaded before the rotation.
    kem_alg_id = db.Column(db.String(64), nullable=False)
    kem_key_id = db.Column(db.Integer, db.ForeignKey("keys.id"), nullable=False)
    kem_ciphertext = db.Column(db.LargeBinary, nullable=False)
    wrapped_dek = db.Column(db.LargeBinary, nullable=False)
    dek_wrap_nonce = db.Column(db.LargeBinary(12), nullable=False)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)

    proposal = db.relationship("Proposal", back_populates="file")
