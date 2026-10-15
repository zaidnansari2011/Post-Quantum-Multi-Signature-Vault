"""RSA at scaled-down parameters — the victim the Shor demonstration can actually finish (ADR-0021).

Read this header before quoting anything this module produces.

``qvault/crypto/providers/classical_signature.py`` holds **real** RSA-2048, at full strength, and
that is what the benchmark measures and what the application would use if an admin ever downgraded
to it. This module is different: it is RSA with a modulus of 9-11 bits, which the simulated Shor
routine can factor in front of an audience. Nothing here is registered in the application's
``CryptoRegistry`` and nothing in the application can reach it.

**Three ways this is weaker than real RSA, stated so nobody has to find them:**

1. *The modulus is tiny.* 9 bits against 2048. This is the only difference that the attack
   depends on, and it is the honest content of the demonstration: the algorithm is the same one,
   its cost is polynomial, and the parameter is the only thing standing between a simulation and a
   break. The cost curve in ``qvault/attack/cost.py`` is what connects the two.
2. *The padding is textbook.* Signing is ``(SHA-256(m) mod n)^d mod n`` with no PSS, because PSS's
   salted encoding does not fit in a 9-bit modulus. Textbook RSA has forgery attacks of its own
   that have nothing to do with quantum computing, so the lab never uses this module to argue RSA
   is *badly designed* — only to argue that factoring N ends it. The attack demonstrated is
   key recovery, which defeats any padding.
3. *The primes are small and found by trial division.* Real RSA keygen uses probabilistic primality
   testing over hundreds of bits.

What it shares with real RSA is the only thing that matters here: the private exponent is
recoverable from the public modulus by factoring, and both of this module's providers implement the
same interfaces as the production ones, so the attack runs through the same seam the application
uses rather than against a special case written to lose.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass

from ..crypto.interfaces import AlgMeta, KEMProvider, KeyPair, SignatureProvider

DEFAULT_BITS = 9  # N in [256, 511]: the largest modulus the *state-vector* simulator handles
#                 in about a second, so the headline demonstration never falls back to the
#                 closed-form distribution. Wider moduli still work via mode="analytic".
PUBLIC_EXPONENT_CANDIDATES = (17, 13, 11, 7, 5, 3)  # 65537 cannot be coprime to a small lambda
MAX_PRIME_RATIO = 3  # keep the modulus balanced; see generate()


@dataclass(frozen=True)
class ToyRSAKey:
    """A scaled RSA keypair, with the factors kept so tests can check the attack found the truth."""

    n: int
    e: int
    d: int
    p: int
    q: int
    bits: int

    def public_bytes(self) -> bytes:
        """The public key as the application would store it: no factors, no private exponent."""
        return json.dumps({"n": self.n, "e": self.e, "bits": self.bits}, sort_keys=True).encode()

    def secret_bytes(self) -> bytes:
        return json.dumps(
            {"n": self.n, "e": self.e, "d": self.d, "bits": self.bits}, sort_keys=True
        ).encode()


def _primes_in(low: int, high: int) -> list[int]:
    """Primes in [low, high) by trial division. Fine at these sizes; absurd at real ones."""
    out = []
    for candidate in range(max(3, low | 1), high, 2):
        if all(candidate % f for f in range(3, int(math.isqrt(candidate)) + 1, 2)):
            out.append(candidate)
    return out


def generate(bits: int = DEFAULT_BITS, *, rng: random.Random | None = None) -> ToyRSAKey:
    """Generate a scaled RSA key whose modulus has exactly ``bits`` bits.

    The two primes are constrained to within a factor of ``MAX_PRIME_RATIO`` of each other, which
    is the balanced case and the hardest shape for classical factoring — an unbalanced modulus
    would fall to trial division on its small factor and the attack would prove less. Exact balance
    is impossible at odd widths (a 9-bit product needs a 4-bit and a 5-bit prime), so the
    constraint is "within a small factor", not "equal".
    """
    rng = rng or random.Random()
    if not 6 <= bits <= 22:
        raise ValueError(f"toy RSA is for scaled demonstrations only; bits={bits} is out of range")

    half = bits // 2
    low, high = 1 << (half - 1), 1 << (half + 1)
    pool = _primes_in(low, high)
    for _ in range(4000):
        p, q = rng.sample(pool, 2)
        n = p * q
        if n.bit_length() != bits or max(p, q) > MAX_PRIME_RATIO * min(p, q):
            continue
        lam = (p - 1) * (q - 1) // math.gcd(p - 1, q - 1)
        for e in PUBLIC_EXPONENT_CANDIDATES:
            if e < lam and math.gcd(e, lam) == 1:
                return ToyRSAKey(n=n, e=e, d=pow(e, -1, lam), p=p, q=q, bits=bits)
    raise RuntimeError(f"no {bits}-bit toy RSA modulus found; try a different width")


def digest_to_int(message: bytes, n: int) -> int:
    """Textbook RSA's message representative: SHA-256, reduced mod n.

    Reducing a 256-bit digest into a 9-bit modulus throws away almost all of it, which is a real
    weakness of this scaled construction and not of RSA. It is irrelevant to the attack being
    demonstrated — recovering ``d`` forges signatures on *any* message regardless of how the
    representative is formed — but it must not be described as how RSA works.
    """
    return int.from_bytes(hashlib.sha256(message).digest(), "big") % n


class ToyRSASignatureProvider(SignatureProvider):
    """Textbook RSA signatures at a scaled modulus, behind the real ``SignatureProvider`` interface.

    Implementing the production interface is deliberate: the forged signature the lab produces is
    handed to ``verify`` on this same provider, so the acceptance is decided by the ordinary
    verification path rather than by the attack asserting its own success.
    """

    def __init__(self, bits: int = DEFAULT_BITS, *, rng: random.Random | None = None) -> None:
        self.bits = bits
        self._rng = rng or random.Random()
        self.meta = AlgMeta(
            alg_id=f"RSA-TOY-{bits}",
            family="RSA",
            human_name=f"Textbook RSA, {bits}-bit modulus (SCALED DEMONSTRATION ONLY)",
            nist_standard="none - a deliberately breakable scale model, not a standard",
            security_category=0,
            backend="qvault.attack.toy_rsa",
            sizes={"public_key": 0, "secret_key": 0, "signature": (bits + 7) // 8},
            quantum_vulnerable=True,
            broken_by="Shor's algorithm - and at this modulus size, trial division too",
        )

    def keygen(self) -> KeyPair:
        key = generate(self.bits, rng=self._rng)
        return KeyPair(
            public_key=key.public_bytes(), secret_key=key.secret_bytes(), alg_id=self.meta.alg_id
        )

    def sign(self, secret_key: bytes, message: bytes) -> bytes:
        k = json.loads(secret_key)
        representative = digest_to_int(message, k["n"])
        signature = pow(representative, k["d"], k["n"])
        return signature.to_bytes((k["n"].bit_length() + 7) // 8, "big")

    def verify(self, public_key: bytes, message: bytes, signature: bytes) -> bool:
        try:
            k = json.loads(public_key)
            recovered = pow(int.from_bytes(signature, "big"), k["e"], k["n"])
            return recovered == digest_to_int(message, k["n"])
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            return False


class ToyRSAKEMProvider(KEMProvider):
    """RSA key transport at a scaled modulus, presented as a KEM — the harvest-now target.

    The construction follows RFC 5990's RSA-KEM rather than OAEP: draw a random integer ``z`` below
    the modulus, transmit ``z^e mod n``, and derive the shared secret as ``SHA-256(z)``. That is
    genuinely how RSA-KEM is specified, and it is the only form that survives being scaled down —
    OAEP needs a modulus wider than its hash. So the scaled model stays a real construction rather
    than becoming a cartoon of one.

    The shared secret is a full 32 bytes, so the AES-256-GCM layer above it is untouched and at
    full strength. The attack recovers the file anyway, because it recovers ``z``: the wrapping is
    what fails, not the symmetric cipher. That is exactly the shape of the real threat.
    """

    def __init__(self, bits: int = DEFAULT_BITS, *, rng: random.Random | None = None) -> None:
        self.bits = bits
        self._rng = rng or random.Random()
        self.meta = AlgMeta(
            alg_id=f"RSA-KEM-TOY-{bits}",
            family="RSA",
            human_name=f"Textbook RSA-KEM, {bits}-bit modulus (SCALED DEMONSTRATION ONLY)",
            nist_standard="RFC 5990 construction at a deliberately breakable modulus",
            security_category=0,
            backend="qvault.attack.toy_rsa",
            sizes={
                "public_key": 0,
                "secret_key": 0,
                "ciphertext": (bits + 7) // 8,
                "shared_secret": 32,
            },
            quantum_vulnerable=True,
            broken_by="Shor's algorithm - factoring N recovers every past shared secret",
        )

    def keygen(self) -> KeyPair:
        key = generate(self.bits, rng=self._rng)
        return KeyPair(
            public_key=key.public_bytes(), secret_key=key.secret_bytes(), alg_id=self.meta.alg_id
        )

    def encapsulate(self, public_key: bytes) -> tuple[bytes, bytes]:
        k = json.loads(public_key)
        z = self._rng.randrange(2, k["n"])
        ciphertext = pow(z, k["e"], k["n"])
        width = (k["n"].bit_length() + 7) // 8
        return ciphertext.to_bytes(width, "big"), self.kdf(z)

    def decapsulate(self, secret_key: bytes, ciphertext: bytes) -> bytes:
        k = json.loads(secret_key)
        z = pow(int.from_bytes(ciphertext, "big"), k["d"], k["n"])
        return self.kdf(z)

    @staticmethod
    def kdf(z: int) -> bytes:
        """Derive the 32-byte shared secret from the transported integer (RFC 5990's KDF step)."""
        return hashlib.sha256(b"QVAULT-RSA-KEM-TOY-v1" + str(z).encode()).digest()
