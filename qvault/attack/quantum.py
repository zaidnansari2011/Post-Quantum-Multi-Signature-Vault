"""The contrast attacks: what a quantum adversary does to RSA, and cannot do to us (ADR-0021).

Each attack here is ``kind="contrast"``. The real run targets a classical algorithm and is
*expected to succeed* — a run that came back "blocked" would mean the demonstration had broken, not
that RSA had held. The control run points the identical pipeline at the post-quantum algorithm and
must come back blocked. Neither result alone says anything; the pair is the evidence.

Every signature forged here is over Q-Vault's **real** canonical vote payload
(``qvault.services.signing.vote_signing_bytes``), and every forgery is judged by the **real**
provider's ``verify``. Nothing in this module decides its own success.
"""

from __future__ import annotations

import hashlib
import json
import os
import random

from ..crypto import build_registry
from ..crypto.symmetric import AESGCMProvider
from ..services import signing
from . import cost, shor, toy_rsa
from .harness import CONTRAST, Attack, Run, blocked, succeeded

# The decision the attacker wants to manufacture. A realistic payload hash and signer id, run
# through the same function the application uses, so the bytes under attack are the bytes at risk.
VICTIM_SIGNER_ID = 7
VICTIM_PAYLOAD_HASH = hashlib.sha256(b"proposal: release 250,000 from the treasury").hexdigest()
FORGED_DECISION = "approve"

# How many blind forgery attempts the fallback attack makes when there is no structure to exploit.
# Kept small on purpose: at ~0.6 ms per ML-DSA verification, 20,000 attempts would dominate the
# whole lab's runtime, and the count is not what carries the argument. The expected number of
# successes (attempts / 2^signature_bits) is reported next to the observed zero, and no achievable
# number of attempts would change that arithmetic.
BLIND_FORGERY_ATTEMPTS = 2_000


def _victim_message() -> bytes:
    return signing.vote_signing_bytes(
        proposal_payload_hash=VICTIM_PAYLOAD_HASH,
        decision=FORGED_DECISION,
        signer_id=VICTIM_SIGNER_ID,
    )


# --- attack 1: recover a private key by factoring, then forge ------------------------------------


def shor_breaks_rsa(rng: random.Random) -> Run:
    """Factor an RSA modulus with simulated Shor, recover ``d``, forge an approval.

    The attacker is given only what the world is given: the victim's public key. Everything else is
    derived. The forged signature is then handed to the provider's own ``verify``.
    """
    run = succeeded()
    provider = toy_rsa.ToyRSASignatureProvider(toy_rsa.DEFAULT_BITS, rng=rng)
    keypair = provider.keygen()
    public = json.loads(keypair.public_key)
    message = _victim_message()

    run.step(
        "Victim publishes a signing key",
        f"RSA at a scaled {public['bits']}-bit modulus (see toy_rsa.py for exactly how this "
        "differs from RSA-2048)",
        f"n={public['n']}, e={public['e']}",
    )
    run.step(
        "Attacker's starting knowledge",
        "the public key, and nothing else - no secret, no side channel, no implementation flaw",
        f"n={public['n']}, e={public['e']}",
    )

    result = shor.shor_factor(public["n"], rng=rng)
    if not result.succeeded:
        # Shor is probabilistic; a run can legitimately exhaust its rounds. That is not a defence.
        return Run(
            verdict="error",
            steps=run.steps,
            note="the simulated order-finding exhausted its rounds; re-run",
        )
    p, q = result.factors
    last = result.order_runs[-1] if result.order_runs else None
    if last is not None:
        run.step(
            "Quantum order-finding",
            f"{last.mode} simulation over a {last.t}-qubit control register; the textbook circuit "
            f"for this modulus needs {last.qubits} qubits in total",
            f"{last.amplitudes_held:,} amplitudes held, measured k={last.measured_k}, "
            f"phase={last.phase}, order r={last.candidate_r} in {last.attempts} shot(s)",
        )
    if result.redrawn_lucky_bases:
        run.step(
            "Bases discarded to keep the demonstration honest",
            "a base sharing a factor with N would let the attack finish classically. That happens "
            "only at toy sizes (about 2^-1013 for RSA-2048), so those draws are thrown away "
            "instead of being counted as a win",
            result.redrawn_lucky_bases,
        )
    rounds = len(result.order_runs)
    round_note = (
        f"{rounds} order-finding round(s), {result.elapsed_ms:.0f} ms on this CPU"
    )
    if rounds > 3:
        # Worth naming: a reader who knows Shor will wonder why it took so many attempts.
        round_note += (
            ". A round is wasted when the order comes back odd or when a^(r/2) = -1 mod N, and "
            "small multiplicative groups produce those far more often than large ones - another "
            "artefact of the scaled modulus, not a property of the algorithm"
        )
    run.step("Modulus factored", round_note, f"{public['n']} = {p} x {q}")

    recovered_d = shor.recover_rsa_exponent(public["e"], p, q)
    run.step(
        "Private exponent recovered",
        "a single modular inverse once the factors are known - no brute force, and nothing the key "
        "owner can do about it",
        f"d={recovered_d}",
    )

    representative = toy_rsa.digest_to_int(message, public["n"])
    forged = pow(representative, recovered_d, public["n"]).to_bytes(
        (public["n"].bit_length() + 7) // 8, "big"
    )
    accepted = provider.verify(keypair.public_key, message, forged)
    run.step(
        "Forged approval submitted to the real verifier",
        f"the canonical vote payload for decision={FORGED_DECISION!r} by signer "
        f"{VICTIM_SIGNER_ID}, signed with the recovered key",
        f"verify() returned {accepted}",
    )
    if not accepted:  # pragma: no cover - would mean the recovery was wrong
        return blocked("the recovered key did not produce an accepted signature")

    projection = cost.classical_projection(2048)
    run.step(
        "What this does and does not show",
        "the algorithm ran to completion at a scaled parameter. At 2048 bits the same algorithm "
        f"needs {cost.shor_resources(2048)['logical_qubits']:,} logical qubits and cubic gate "
        f"count, against {projection['core_years_human']} core-years classically",
        f"{projection['gnfs_ratio_to_anchor']:.1e}x the work of RSA-250, the largest modulus ever "
        "factored",
    )
    run.note = (
        "The victim's key is a scale model; the attack is not. Key recovery defeats any padding, "
        "so the textbook signing in toy_rsa.py is not what lost."
    )
    return run


def shor_has_no_target_in_mldsa(rng: random.Random) -> Run:
    """Point the same pipeline at ML-DSA-65 and report where it stops.

    Written to avoid the cheap version of this demonstration. It would be easy, and dishonest, to
    "run Shor against ML-DSA" and print a failure: there is no way to hand an ML-DSA key to a
    factoring algorithm, so such a run would be theatre. Instead the pipeline is attempted step by
    step, the step that cannot be performed is named, and the attacker then falls back to the best
    thing actually available to them — blind forgery — whose measured success rate is the result.
    """
    run = blocked()
    registry = build_registry(classical=False)
    provider = registry.signature("ML-DSA-65")
    keypair = provider.keygen()
    message = _victim_message()

    run.step(
        "Victim publishes a signing key",
        "ML-DSA-65, FIPS 204 - the project's default",
        f"public key {len(keypair.public_key)} bytes",
    )
    run.step(
        "Step 1 of the pipeline: obtain a modulus to factor",
        "an ML-DSA public key is (rho, t1): a 32-byte seed and a vector of packed polynomial "
        "coefficients. There is no integer modulus, no group element, and no order to find",
        "no input available",
    )
    analogue = shor.no_quantum_analogue("ML-DSA-65")
    run.step(
        "Why the attack has no formulation rather than merely failing",
        analogue["why"],
        f"{len(analogue['requires'])} preconditions required, "
        f"{len(analogue['present'])} present",
    )

    # The fallback: the attacker has no structure to exploit, so they guess.
    accepted = 0
    signature_bits = provider.meta.sizes["signature"] * 8
    for _ in range(BLIND_FORGERY_ATTEMPTS):
        candidate = os.urandom(provider.meta.sizes["signature"])
        if provider.verify(keypair.public_key, message, candidate):  # pragma: no cover
            accepted += 1
    run.step(
        "Fallback: blind forgery, the best attack actually available",
        f"{BLIND_FORGERY_ATTEMPTS:,} random signatures of the correct length submitted to the real "
        f"verifier. The signature space is 2^{signature_bits}, so the expected number of "
        f"successes is {BLIND_FORGERY_ATTEMPTS} / 2^{signature_bits}",
        f"{accepted} accepted",
    )
    if accepted:  # pragma: no cover - would be a finding of historic proportions
        return succeeded("a random signature verified; stop everything and re-check the provider")
    run.step(
        "Best known quantum improvement",
        analogue["best_known_quantum"],
        "still exponential",
    )
    run.note = analogue["honest_caveat"]
    return run


# --- attack 2: harvest now, decrypt later --------------------------------------------------------

_SECRET_FILE = (
    b"BOARD MINUTES - CONFIDENTIAL\nAcquisition of Northwind Ltd approved at 41.2M.\n"
    b"Do not disclose before completion.\n"
)


def _wrap_file(kem, provider_label: str) -> dict:
    """Encrypt the file exactly as Q-Vault does: AES-256-GCM under a KEM-wrapped key."""
    aes = AESGCMProvider()
    keypair = kem.keygen()
    kem_ciphertext, shared_secret = kem.encapsulate(keypair.public_key)
    nonce, blob = aes.encrypt(shared_secret, _SECRET_FILE)
    return {
        "label": provider_label,
        "public_key": keypair.public_key,
        "kem_ciphertext": kem_ciphertext,
        "nonce": nonce,
        "blob": blob,
        "aes": aes,
    }


def harvest_now_decrypt_later_rsa(rng: random.Random) -> Run:
    """Record a wrapped ciphertext today; factor the key years later; read the file.

    The intercepted material is exactly what an adversary who copies a backup or taps a link gets:
    the public key, the wrapped data-encryption key, and the AES blob. No private key, no password.
    """
    run = succeeded()
    kem = toy_rsa.ToyRSAKEMProvider(toy_rsa.DEFAULT_BITS, rng=rng)
    captured = _wrap_file(kem, kem.meta.alg_id)
    public = json.loads(captured["public_key"])

    run.step(
        "2026: attacker records the traffic",
        "public key, RSA-wrapped data-encryption key, and the AES-256-GCM blob. The AES layer is "
        "at full strength and is never attacked",
        f"n={public['n']}, wrapped DEK {len(captured['kem_ciphertext'])} B "
        f"(scaled modulus; RSA-2048 would be 256 B), ciphertext {len(captured['blob'])} B",
    )
    run.step(
        "2026: attacker tries to read it",
        "AES-256-GCM with an unknown key - nothing to do but store the capture and wait",
        "no plaintext",
    )

    result = shor.shor_factor(public["n"], rng=rng)
    if not result.succeeded:
        return Run(verdict="error", steps=run.steps, note="order-finding exhausted its rounds")
    p, q = result.factors
    recovered_d = shor.recover_rsa_exponent(public["e"], p, q)
    run.step(
        "Years later: a quantum computer exists",
        "the recorded capture is still valid. Rotating the key in the meantime would not have "
        "helped - the ciphertext was already taken",
        f"{public['n']} = {p} x {q}, d={recovered_d}",
    )

    z = pow(int.from_bytes(captured["kem_ciphertext"], "big"), recovered_d, public["n"])
    recovered_secret = toy_rsa.ToyRSAKEMProvider.kdf(z)
    plaintext = captured["aes"].decrypt(recovered_secret, captured["nonce"], captured["blob"])
    run.step(
        "Data-encryption key unwrapped, file decrypted",
        "the AES-256-GCM tag verifies, because this is the genuine key",
        f"{len(plaintext)} bytes recovered: {plaintext.splitlines()[0].decode()!r}",
    )
    if plaintext != _SECRET_FILE:  # pragma: no cover
        return blocked("recovered plaintext did not match")
    run.note = (
        "This is why confidentiality cannot wait for a quantum computer to appear. A signature "
        "forged in 2035 is an attack on 2035; a file recorded in 2026 is an attack on 2026, "
        "carried out later."
    )
    return run


def harvest_now_decrypt_later_mlkem(rng: random.Random) -> Run:
    """The same capture, wrapped with ML-KEM-768. The attacker holds it and has nowhere to go."""
    run = blocked()
    registry = build_registry(classical=False)
    kem = registry.kem("ML-KEM-768")
    captured = _wrap_file(kem, "ML-KEM-768")

    run.step(
        "2026: attacker records the traffic",
        "the identical capture - public key, wrapped data-encryption key, AES-256-GCM blob",
        f"public key {len(captured['public_key'])} B, wrapped DEK "
        f"{len(captured['kem_ciphertext'])} B",
    )
    run.step(
        "Attempt the pipeline that worked against RSA",
        "step 1 needs an integer modulus to factor. An ML-KEM public key is a seed plus packed "
        "polynomial coefficients over a module lattice; there is nothing to factor",
        "no input available",
    )

    # The only thing left: guess the wrapped key. One attempt, to make the cost concrete.
    guess = os.urandom(32)
    try:
        captured["aes"].decrypt(guess, captured["nonce"], captured["blob"])
        leaked = True  # pragma: no cover - would break AES-GCM, not ML-KEM
    except Exception:  # noqa: BLE001 - any authentication failure is the expected outcome
        leaked = False
    run.step(
        "Fallback: guess the 256-bit data-encryption key",
        "the AES-256-GCM authentication tag rejects a wrong key. The search space is 2^256, and "
        "Grover's algorithm reduces that to about 2^128 operations - still out of reach, and the "
        "reason ML-KEM-768 targets NIST category 3",
        f"1 attempt, accepted={leaked}",
    )
    if leaked:  # pragma: no cover
        return succeeded("a random 256-bit key authenticated")
    run.note = (
        "The capture stays a capture. Note what is *not* claimed: ML-KEM is not proven unbreakable, "
        "only that no published attack applies. The system's answer to that residual risk is "
        "agility - the ability to change algorithm without losing the data."
    )
    return run


# --- the attacks, as the harness sees them -------------------------------------------------------


def attacks(rng: random.Random | None = None) -> list[Attack]:
    rng = rng or random.Random()
    return [
        Attack(
            id="shor-key-recovery",
            title="Recover a signing key by factoring, then forge an approval",
            question="Can you actually break RSA, or are you just citing a paper?",
            capability="The victim's public key. Nothing else - no secret, no side channel.",
            goal="Forge an approval that the real verifier accepts",
            defence="None available to RSA. Key recovery defeats every padding scheme.",
            defence_ref="qvault/attack/shor.py",
            real=lambda: shor_breaks_rsa(rng),
            control=lambda: shor_has_no_target_in_mldsa(rng),
            control_note="the identical pipeline pointed at ML-DSA-65",
            kind=CONTRAST,
            standard="Shor 1994; Gidney 2025 (arXiv:2505.15917) for the 2048-bit estimate",
        ),
        Attack(
            id="harvest-now-decrypt-later",
            title="Record an encrypted file now, decrypt it after the quantum computer arrives",
            question="Why migrate today if no quantum computer exists today?",
            capability="A recorded copy of the wrapped key and the ciphertext - a stolen backup.",
            goal="Read a file that was encrypted years before the attack",
            defence="ML-KEM-768 wrapping: the recording gives the attacker no factoring target.",
            defence_ref="qvault/crypto/providers/quantcrypt_kem.py",
            real=lambda: harvest_now_decrypt_later_rsa(rng),
            control=lambda: harvest_now_decrypt_later_mlkem(rng),
            control_note="the identical capture wrapped with ML-KEM-768 instead of RSA",
            kind=CONTRAST,
            standard="NIST IR 8547 ipd - the migration timeline this threat drives",
        ),
    ]
