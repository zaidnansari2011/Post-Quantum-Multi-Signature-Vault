"""Server master key custody.

Vault ML-KEM private keys and (later) the SYSTEM ledger-anchor key are wrapped under a single
server master key so they can be used unattended (no user password), while user *signing* keys
stay password-bound. The master key is loaded from ``SERVER_MASTER_KEY`` (64 hex chars = 32
bytes). Production refuses to start without it (see config); dev/test derive a deterministic
fallback from ``SECRET_KEY`` so wrapped material survives restarts.

This env-var master key is an explicit HSM/KMS *surrogate* — a documented non-goal to harden.
"""

from __future__ import annotations

import hashlib
import hmac

from flask import current_app

_MASTER_AAD = b"qvault:master-wrap:v1"
_MAC_DS = b"qvault:system-pubkey-mac:v1"
# Deliberately NOT _MAC_DS. That tag authenticates the SYSTEM anchor public key — the root of the
# ledger's trust. A challenge MAC is issued freely to anyone who can type a password, so sharing a
# tag would let an attacker who could steer bytes into one verifier obtain a token the other
# accepts. One tag, one meaning.
_CHALLENGE_DS = b"qvault:device-enrol-challenge:v1"


def _parse_hex_key(raw: str) -> bytes | None:
    raw = raw.strip()
    if len(raw) == 64:
        try:
            return bytes.fromhex(raw)
        except ValueError:
            return None
    return None


def get_master_key() -> bytes:
    """Return the 32-byte server master key, or raise if it cannot be resolved."""
    raw = current_app.config.get("SERVER_MASTER_KEY")
    if raw:
        key = _parse_hex_key(raw)
        if key is None:
            raise RuntimeError("SERVER_MASTER_KEY must be 64 hex characters (32 bytes).")
        return key
    if current_app.config.get("DEBUG") or current_app.config.get("TESTING"):
        secret = current_app.config["SECRET_KEY"].encode("utf-8")
        return hashlib.sha256(b"qvault-dev-master:" + secret).digest()
    raise RuntimeError("SERVER_MASTER_KEY is required outside development.")


def _symmetric():
    return current_app.extensions["crypto"].symmetric("AES-256-GCM")


def wrap_secret(plaintext: bytes) -> tuple[bytes, bytes]:
    """Encrypt ``plaintext`` under the master key; return ``(nonce, ciphertext)``."""
    return _symmetric().encrypt(get_master_key(), plaintext, _MASTER_AAD)


def unwrap_secret(nonce: bytes, ciphertext: bytes) -> bytes:
    """Decrypt master-key-wrapped material; raises on a wrong key / tampering."""
    return _symmetric().decrypt(get_master_key(), nonce, ciphertext, _MASTER_AAD)


def mac(data: bytes) -> bytes:
    """HMAC-SHA256 over ``data`` keyed by the master key — authenticates non-secret material
    (e.g. the SYSTEM public key) against the out-of-band trust root."""
    return hmac.new(get_master_key(), _MAC_DS + data, hashlib.sha256).digest()


def verify_mac(data: bytes, tag: bytes | None) -> bool:
    """Constant-time check that ``tag`` is a valid master-key MAC over ``data``."""
    if not tag:
        return False
    return hmac.compare_digest(mac(data), tag)


def challenge_mac(data: bytes) -> bytes:
    """HMAC-SHA256 over a device-enrolment challenge, under a domain tag of its own.

    Lets an enrolment challenge carry its own expiry and be handed back to the server as evidence,
    with no table to write and no sweep to expire it: the MAC proves *we* minted it and the
    embedded deadline proves *when*. Keyed by the master key because the challenge is server-issued
    state that must survive a restart without being stored.
    """
    return hmac.new(get_master_key(), _CHALLENGE_DS + data, hashlib.sha256).digest()


def verify_challenge_mac(data: bytes, tag: bytes | None) -> bool:
    """Constant-time check that ``tag`` is a valid challenge MAC over ``data``.

    Authenticity only — the caller must still enforce the expiry encoded in ``data``.
    """
    if not tag:
        return False
    return hmac.compare_digest(challenge_mac(data), tag)


# -- Recovery Kit (R9, design section 5.1) ---------------------------------------------------------
# Three more tags, each with one meaning. None of them is _MAC_DS: a kit's MAC must never be
# accepted as the SYSTEM key's, nor the other way round.
_KIT_PEPPER_DS = b"qvault:kit-pepper:v1|"
_KIT_PK_DS = b"qvault:recovery-kit-pk:v1|"
_KIT_CONFIRM_DS = b"qvault:kit-confirm:v1|"


def kit_pepper(kit_uuid: str) -> bytes:
    """The secret only the live server can add to a kit's key: HMAC-SHA256(master key,
    ``qvault:kit-pepper:v1|`` + kit uuid). Mixed into the kit KEK, so a stolen database and a
    stolen kit, without ``SERVER_MASTER_KEY``, open nothing (review M2). Never stored."""
    return hmac.new(
        get_master_key(), _KIT_PEPPER_DS + kit_uuid.encode("ascii"), hashlib.sha256
    ).digest()


def kit_pk_mac(data: bytes) -> bytes:
    """HMAC-SHA256 over a kit's public-key record (``recovery_kit.pk_mac_input``): its owner, its
    uuid, its KEM algorithm, its Argon2id parameters and salt, when it was made and the public
    key. A database writer cannot swap in a key of their own, relabel the algorithm, or weaken
    the derivation, without the master key (review L5)."""
    return hmac.new(get_master_key(), _KIT_PK_DS + data, hashlib.sha256).digest()


def verify_kit_pk_mac(data: bytes, tag: bytes | None) -> bool:
    if not tag:
        return False
    return hmac.compare_digest(kit_pk_mac(data), tag)


def kit_confirm_tag(kit_uuid: str, last_group: str) -> bytes:
    """A tag the kit page carries so the server can check the last group typed back without
    seeing the code again or storing anything from it. It is sent only to the browser that is
    showing the whole code, and is never stored."""
    data = kit_uuid.encode("ascii") + b"|" + last_group.encode("ascii")
    return hmac.new(get_master_key(), _KIT_CONFIRM_DS + data, hashlib.sha256).digest()
