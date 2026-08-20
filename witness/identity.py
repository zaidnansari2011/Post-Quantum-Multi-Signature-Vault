"""The witness's signing identity — its own keypair, in its own file.

Why the default algorithm differs from the log's
------------------------------------------------
Q-Vault signs its checkpoints with **ML-DSA-65**; this witness defaults to **ML-DSA-87**. Two
independent parties, each with its own key and its own choice of parameters, interoperating
through a shared statement encoding rather than a shared configuration — which is what
crypto-agility looks like once there is more than one party.

**This was going to be SLH-DSA-SHAKE-256f, and it is worth recording why it is not.** Hash-based
signatures rest on a different assumption from lattice-based ones, so a witness using one would
have produced evidence that survived a break of module-lattice hardness. Two things overruled it:

1. The offline verifier (``qvault/static/verifier.html``) checks signatures in the browser using
   the vendored ``@noble/post-quantum``, which implements **FIPS 205 SLH-DSA**. The backend's
   ``SLH-DSA-SHAKE-256f`` is PQClean's ``sphincs-shake-256f-simple`` — the **SPHINCS+ round-3
   submission**, which FIPS 205 is derived from but is *not byte-compatible with*. A witness
   signing with it would produce co-signatures no browser verifier could check. See
   ``qvault/crypto/providers/quantcrypt_signature.py`` for the measured evidence.
2. The benefit was smaller than it first appears. If module-lattice hardness fell, every *signer*
   signature in the system would fall with it, since those are ML-DSA too. A surviving
   co-signature would prove the log had been consistent, but not that anyone approved anything.

So: a verifier that works completely, over an assumption-diversity argument that only pays off in
a world where the decisions themselves are already unverifiable. ``--alg SLH-DSA-SHAKE-256f``
still selects the hash-based witness for anyone who wants that trade; the offline verifier reports
those co-signatures as un-checkable rather than pretending to check them.

Key storage
-----------
The secret key lives in a JSON file. In a deployment that mattered, this would be an HSM or at
minimum a key the process reads from a secret manager and never writes down; the file is a
project-scale stand-in and is not pretended to be more than that. What the file does buy is the
property that actually carries the argument: it is not in Q-Vault's database, so an adversary who
owns the vault does not thereby own the witness.
"""

from __future__ import annotations

import json
import os
import stat
from base64 import b64decode, b64encode
from dataclasses import dataclass
from pathlib import Path

from qvault.crypto import CryptoRegistry, sha256_hex

DEFAULT_WITNESS_ALG = "ML-DSA-87"


@dataclass(frozen=True)
class WitnessIdentity:
    name: str
    alg_id: str
    backend: str
    public_key: bytes
    secret_key: bytes

    def fingerprint(self) -> str:
        """The value a verifier pins. Published by the witness operator, checked out of band."""
        return sha256_hex(self.public_key)[:16]

    def public_dict(self) -> dict:
        return {
            "witness": self.name,
            "alg_id": self.alg_id,
            "backend": self.backend,
            "public_key_b64": b64encode(self.public_key).decode(),
            "fingerprint": self.fingerprint(),
        }


def load_or_create(
    path: str | Path,
    *,
    name: str,
    registry: CryptoRegistry,
    alg_id: str | None = None,
) -> WitnessIdentity:
    """Load the witness keypair from ``path``, generating one on first run.

    Regenerating is never automatic on a load failure. A witness whose key silently changed would
    keep answering requests while every previously-issued co-signature became unverifiable, and
    the failure would look like the *log* misbehaving. A corrupt key file is a stop.
    """
    path = Path(path)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        stored_alg = data["alg_id"]
        if alg_id is not None and alg_id != stored_alg:
            raise SystemExit(
                f"{path} holds a {stored_alg} key but --alg says {alg_id}. Refusing to run: "
                "changing algorithm means a new identity, so point --key at a new file."
            )
        if not registry.has_signature(stored_alg):
            raise SystemExit(f"{path} holds a {stored_alg} key, which this build cannot verify.")
        return WitnessIdentity(
            name=data.get("name", name),
            alg_id=stored_alg,
            backend=data.get("backend", "unknown"),
            public_key=b64decode(data["public_key_b64"]),
            secret_key=b64decode(data["secret_key_b64"]),
        )

    alg_id = alg_id or DEFAULT_WITNESS_ALG
    if not registry.has_signature(alg_id):
        available = ", ".join(registry.list_signature_algs())
        raise SystemExit(f"unknown signature algorithm {alg_id!r}. Available: {available}")

    provider = registry.signature(alg_id)
    keypair = provider.keygen()
    identity = WitnessIdentity(
        name=name,
        alg_id=alg_id,
        backend=provider.meta.backend,
        public_key=keypair.public_key,
        secret_key=keypair.secret_key,
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "name": identity.name,
                "alg_id": identity.alg_id,
                "backend": identity.backend,
                "public_key_b64": b64encode(identity.public_key).decode(),
                "secret_key_b64": b64encode(identity.secret_key).decode(),
                "fingerprint": identity.fingerprint(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    # Best effort: POSIX honours this, Windows largely ignores it. Attempted anyway so the
    # permission is right wherever it can be, and its absence is never silently assumed.
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:  # pragma: no cover - platform dependent
        pass
    return identity
