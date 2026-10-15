"""Attacks at the algorithm and interface level — no database, no web request (ADR-0021).

These are ``kind="defence"``: the real run must be **blocked**, and the control run — the same
attack against a variant with the named mechanism removed — must **succeed**. The control is what
makes each result attributable. "The signature did not verify" is weak evidence; "the signature did
not verify, and it *did* verify against a build with this one check removed" identifies the check.

Where a control models a well-known real-world mistake, it is named: the token-length verifier, the
attacker-chosen algorithm (JWT's ``alg`` confusion), the unbound payload, the fast password hash.
None of these controls are strawmen invented to lose — each is a design that has shipped.
"""

from __future__ import annotations

import hashlib
import random
import time

from ..crypto import build_registry
from ..crypto.kdf import DEFAULT_PARAMS, derive_kek, new_salt
from ..services import signing
from . import toy_rsa
from .harness import Attack, Run, blocked, succeeded

PAYLOAD_HASH = hashlib.sha256(b"proposal: release 250,000 from the treasury").hexdigest()
OTHER_PAYLOAD_HASH = hashlib.sha256(b"proposal: buy new laptops for the team").hexdigest()
SIGNER_ID = 7
DEFAULT_ALG = "ML-DSA-65"


def _registry():
    """A post-quantum-only registry: these attacks are about Q-Vault's real configuration."""
    return build_registry(classical=False)


def _vote(payload_hash: str = PAYLOAD_HASH, decision: str = "approve", signer: int = SIGNER_ID):
    return signing.vote_signing_bytes(
        proposal_payload_hash=payload_hash, decision=decision, signer_id=signer
    )


# --- attack 3: tamper with a signature ----------------------------------------------------------


def flip_one_bit_real(_: random.Random) -> Run:
    """Flip a single bit of a genuine ML-DSA signature and submit it."""
    run = blocked()
    provider = _registry().signature(DEFAULT_ALG)
    keypair = provider.keygen()
    message = _vote()
    signature = provider.sign(keypair.secret_key, message)

    corrupted = bytearray(signature)
    corrupted[0] ^= 0x01
    run.step(
        "Genuine approval signed",
        f"{DEFAULT_ALG} over the canonical vote payload",
        f"signature {len(signature)} bytes, sha256 {hashlib.sha256(signature).hexdigest()[:32]}",
    )
    run.step(
        "One bit flipped",
        "the least significant bit of byte 0 - the smallest possible change",
        f"sha256 {hashlib.sha256(bytes(corrupted)).hexdigest()[:32]}",
    )
    accepted = provider.verify(keypair.public_key, message, bytes(corrupted))
    run.step("Submitted to the real verifier", "", f"verify() returned {accepted}")
    return succeeded("a corrupted signature verified") if accepted else run


def flip_one_bit_control(_: random.Random) -> Run:
    """The same flip against a verifier that treats the signature as an opaque bearer token.

    Not a strawman: checking that a credential is present and well-formed, without verifying it, is
    one of the most frequently shipped authentication bugs there is.
    """
    run = succeeded()
    provider = _registry().signature(DEFAULT_ALG)
    keypair = provider.keygen()
    message = _vote()
    signature = provider.sign(keypair.secret_key, message)
    corrupted = bytearray(signature)
    corrupted[0] ^= 0x01

    expected_length = provider.meta.sizes["signature"]
    accepted = len(corrupted) == expected_length
    run.step(
        "Verifier replaced with a length check",
        f"accept any {expected_length}-byte blob - the 'signature as opaque token' mistake",
        f"accepted={accepted}",
    )
    return run if accepted else blocked("even the weakened verifier rejected it")


# --- attack 4: choose the verification algorithm -------------------------------------------------


def algorithm_confusion_real(rng: random.Random) -> Run:
    """Submit a forged signature while *claiming* it is a different algorithm.

    This is JWT ``alg`` confusion in Q-Vault's setting. The attacker forges under an algorithm they
    can break (scaled RSA, where they hold the private key because they generated it), then asks the
    system to verify it as that algorithm.

    Q-Vault refuses because the algorithm is not the attacker's to choose: every ``Signature`` row
    pins ``alg_id``, ``backend`` and ``public_key`` to the signer's registered ``Key`` when the vote
    is cast, and verification resolves the provider from the *pinned* value. The claim travelling
    with the attack is simply not read.
    """
    run = blocked()
    registry = _registry()
    message = _vote()

    # What the victim actually registered — the pinned truth.
    victim_provider = registry.signature(DEFAULT_ALG)
    victim_key = victim_provider.keygen()
    pinned = {"alg_id": DEFAULT_ALG, "public_key": victim_key.public_key}
    run.step(
        "Victim's registered key",
        "alg_id and public key are pinned to the signer's Key row at the moment of signing",
        f"pinned alg_id={pinned['alg_id']}",
    )

    # The attacker's forgery, under an algorithm they control completely.
    attacker_provider = toy_rsa.ToyRSASignatureProvider(toy_rsa.DEFAULT_BITS, rng=rng)
    attacker_key = attacker_provider.keygen()
    forged = attacker_provider.sign(attacker_key.secret_key, message)
    claim = {"alg_id": attacker_provider.meta.alg_id, "public_key": attacker_key.public_key}
    run.step(
        "Attacker forges under an algorithm they own",
        f"a valid {claim['alg_id']} signature over the identical payload, made with a key they "
        "generated themselves",
        f"claimed alg_id={claim['alg_id']}, signature {len(forged)} bytes",
    )

    # Verification as the application performs it: the pinned alg_id and pinned public key decide.
    provider = registry.signature(pinned["alg_id"])
    accepted = provider.verify(pinned["public_key"], message, forged)
    run.step(
        "Verification resolves the provider from the PINNED alg_id",
        "the attacker's claim is never consulted, so the forgery is checked as ML-DSA against the "
        "victim's real public key",
        f"verify() returned {accepted}",
    )
    return succeeded("the attacker's claimed algorithm was honoured") if accepted else run


def algorithm_confusion_control(rng: random.Random) -> Run:
    """The same forgery against a verifier that trusts the attacker's ``alg_id``."""
    run = succeeded()
    message = _vote()
    attacker_provider = toy_rsa.ToyRSASignatureProvider(toy_rsa.DEFAULT_BITS, rng=rng)
    attacker_key = attacker_provider.keygen()
    forged = attacker_provider.sign(attacker_key.secret_key, message)

    # The weakened rule: resolve the algorithm and the key from the submitted artefact.
    lookup = {attacker_provider.meta.alg_id: attacker_provider}
    provider = lookup[attacker_provider.meta.alg_id]
    accepted = provider.verify(attacker_key.public_key, message, forged)
    run.step(
        "Verifier resolves alg_id from the submitted artefact",
        "the attacker names the algorithm and supplies the matching public key - the same shape as "
        "JWT alg confusion",
        f"accepted={accepted} under {attacker_provider.meta.alg_id}",
    )
    return run if accepted else blocked("the weakened verifier still refused")


# --- attack 5: replay a valid signature in another context ---------------------------------------

_REPLAYS = (
    ("flip the decision to reject", lambda: _vote(decision="reject")),
    ("move the vote to another proposal", lambda: _vote(payload_hash=OTHER_PAYLOAD_HASH)),
    ("attribute the vote to another signer", lambda: _vote(signer=SIGNER_ID + 1)),
    (
        # The cross-*protocol* case, and the most interesting of the four: a vote signature
        # presented as the enrolment of an attacker-controlled device. Different domain tag
        # (DS_DEVICE_ENROL rather than DS_VOTE), which is precisely what domain separation is for.
        "reuse it to enrol an attacker-controlled device",
        lambda: signing.device_enrolment_bytes(
            user_id=SIGNER_ID,
            alg_id=DEFAULT_ALG,
            public_key_b64="QUFBQQ==",
            challenge="attacker-supplied-challenge",
        ),
    ),
)


def replay_across_contexts_real(_: random.Random) -> Run:
    """Take one genuine approval and try to make it mean something else.

    The signature is never altered. Only the context it is presented in changes — which is the
    entire attack, and the reason a signing payload has to bind every field that matters.
    """
    run = blocked()
    provider = _registry().signature(DEFAULT_ALG)
    keypair = provider.keygen()
    genuine_message = _vote()
    signature = provider.sign(keypair.secret_key, genuine_message)
    run.step(
        "One genuine approval, signed once",
        "decision=approve on proposal A by signer 7",
        f"signature sha256 {hashlib.sha256(signature).hexdigest()[:32]}",
    )

    for label, build in _REPLAYS:
        # Deliberately unguarded. An earlier version caught TypeError here and moved on, which
        # meant a replay silently stopped being attempted when a payload helper's signature
        # changed -- the exact vacuity this lab exists to prevent, reproduced inside it. A broken
        # replay must now surface as an ERROR outcome.
        target = build()
        accepted = provider.verify(keypair.public_key, target, signature)
        run.step(
            f"Replay: {label}",
            "the same signature bytes, presented against a different canonical payload",
            f"verify() returned {accepted}",
        )
        if accepted:
            return succeeded(f"the signature was accepted out of context: {label}")
    run.note = (
        "Every field the decision depends on is inside the signed bytes, behind the DS_VOTE domain "
        "tag, so there is no context the signature can be moved to."
    )
    return run


def replay_across_contexts_control(_: random.Random) -> Run:
    """The same replays against a payload that signs only the decision word.

    The design being modelled — sign the user's answer, track what it referred to in the database —
    is a common and entirely natural mistake.
    """
    run = succeeded()
    provider = _registry().signature(DEFAULT_ALG)
    keypair = provider.keygen()
    weak_payload = b"approve"  # no domain tag, no proposal, no signer
    signature = provider.sign(keypair.secret_key, weak_payload)
    run.step(
        "Weakened payload: the decision word alone",
        "no domain separation, no proposal binding, no signer binding",
        f"signed bytes = {weak_payload!r}",
    )
    accepted = provider.verify(keypair.public_key, weak_payload, signature)
    run.step(
        "Replay onto any other proposal",
        "the bytes carry nothing that identifies which proposal was approved, so the same "
        "signature is a valid approval of every proposal in the system",
        f"accepted={accepted}",
    )
    return run if accepted else blocked("the weakened payload still refused the replay")


# --- attack 6: offline password guessing against a stolen database --------------------------------

# A dictionary attack the attacker can definitely win on a fast hash. The password is in the list.
_DICTIONARY = [f"password{i}" for i in range(1, 400)] + ["correct-horse-battery-staple"]
_TARGET_PASSWORD = "correct-horse-battery-staple"
_GUESS_BUDGET_S = 2.0


def password_guessing_real(_: random.Random) -> Run:
    """Run a dictionary attack against Argon2id at the application's real parameters.

    The attacker has the whole database: salts, wrapped keys, everything but the passwords. The only
    defence is the cost of a single guess, which is why the KDF parameters are a security control
    and not a performance setting.
    """
    run = blocked()
    salt = new_salt()
    target = derive_kek(_TARGET_PASSWORD, salt)
    run.step(
        "Stolen database",
        f"Argon2id at the application's parameters: t={DEFAULT_PARAMS['time_cost']}, "
        f"m={DEFAULT_PARAMS['memory_cost'] // 1024} MiB, p={DEFAULT_PARAMS['parallelism']}",
        f"salt {len(salt)} bytes, {len(_DICTIONARY)} candidate passwords",
    )

    started = time.perf_counter()
    tried = 0
    found = None
    for candidate in _DICTIONARY:
        if time.perf_counter() - started > _GUESS_BUDGET_S:
            break
        tried += 1
        if derive_kek(candidate, salt) == target:
            found = candidate
            break
    elapsed = time.perf_counter() - started
    rate = tried / elapsed if elapsed else 0.0
    run.step(
        f"Dictionary attack, {_GUESS_BUDGET_S:.0f}-second budget",
        "each guess must pay the full Argon2id cost; there is no shortcut and no precomputation, "
        "because the salt is unique per user",
        f"{tried} of {len(_DICTIONARY)} candidates tried, {rate:.1f} guesses/sec",
    )
    if found:
        return succeeded(f"the password was recovered within the budget: {found!r}")
    run.step(
        "Extrapolated cost",
        (
            "at the measured rate, an eight-character lowercase-alphanumeric space "
            "(36^8) would take "
            f"{36 ** 8 / rate / 31_557_600:,.0f} years of one machine's time"
            if rate
            else "rate too low"
        ),
        f"{rate:.1f} guesses/sec",
    )
    return run


def password_guessing_control(_: random.Random) -> Run:
    """The same dictionary against a single unsalted SHA-256 — the store Argon2id replaced."""
    run = succeeded()
    target = hashlib.sha256(_TARGET_PASSWORD.encode()).digest()
    started = time.perf_counter()
    tried = 0
    found = None
    for candidate in _DICTIONARY:
        tried += 1
        if hashlib.sha256(candidate.encode()).digest() == target:
            found = candidate
            break
    elapsed = time.perf_counter() - started
    rate = tried / elapsed if elapsed else 0.0
    run.step(
        "Password store weakened to one SHA-256 pass",
        "no salt, no iteration count - a design still found in production systems",
        f"{tried} candidates in {elapsed * 1000:.2f} ms ({rate:,.0f} guesses/sec)",
    )
    run.step(
        "Result",
        "the same dictionary, the same machine, the same budget",
        f"recovered {found!r}" if found else "not found",
    )
    return run if found else blocked("the weakened store resisted, which should be impossible")


# --- the attacks, as the harness sees them -------------------------------------------------------


def attacks(rng: random.Random | None = None) -> list[Attack]:
    rng = rng or random.Random()
    return [
        Attack(
            id="signature-bit-flip",
            title="Alter an approved decision by one bit",
            question="What happens if someone edits a signed approval?",
            capability="Write access to the signature bytes in transit or at rest.",
            goal="Have a modified approval accepted as genuine",
            defence="ML-DSA verification over the exact canonical bytes (ADR-0010).",
            defence_ref="qvault/crypto/providers/quantcrypt_signature.py",
            real=lambda: flip_one_bit_real(rng),
            control=lambda: flip_one_bit_control(rng),
            control_note="the verifier reduced to a signature-length check",
            standard="FIPS 204",
        ),
        Attack(
            id="algorithm-confusion",
            title="Forge under an algorithm you control, then name it in the request",
            question="Your system supports several algorithms - can I pick the weak one?",
            capability="Full control of the submitted artefact, including its algorithm label.",
            goal="Have the system verify a forgery under an attacker-chosen algorithm",
            defence="alg_id, backend and public_key are pinned to the signer's Key row (ADR-0001).",
            defence_ref="qvault/models/signature.py",
            real=lambda: algorithm_confusion_real(rng),
            control=lambda: algorithm_confusion_control(rng),
            control_note="the verifier resolving alg_id from the attacker's own claim",
            standard="the JWT 'alg' confusion class (CVE-2015-9235 and successors)",
        ),
        Attack(
            id="cross-context-replay",
            title="Reuse one genuine approval somewhere it was never given",
            question="Could an approval of one thing be replayed as approval of another?",
            capability="A copy of one valid signature - no key, no forgery needed.",
            goal="Make a genuine signature authorise a different decision, proposal or signer",
            defence="Domain-separated canonical payloads: DS_VOTE binds every deciding field.",
            defence_ref="qvault/services/signing.py",
            real=lambda: replay_across_contexts_real(rng),
            control=lambda: replay_across_contexts_control(rng),
            control_note="a payload that signs only the decision word",
            standard="domain separation, NIST SP 800-185",
        ),
        Attack(
            id="offline-password-guessing",
            title="Guess passwords offline against a stolen database",
            question="If the database leaks, how long do the signing keys last?",
            capability=(
                "The entire database: salts, wrapped private keys, everything but passwords."
            ),
            goal="Recover a password and unwrap the signing key it protects",
            defence="Argon2id at memory-hard parameters, with a unique salt per user.",
            defence_ref="qvault/crypto/kdf.py",
            real=lambda: password_guessing_real(rng),
            control=lambda: password_guessing_control(rng),
            control_note="the password store weakened to a single unsalted SHA-256",
            standard="OWASP password storage; RFC 9106 (Argon2)",
        ),
    ]
