"""The live attack demonstration — performed in a terminal, on a message the audience chooses.

    .venv\\Scripts\\python scripts\\demo_attack.py
    .venv\\Scripts\\python scripts\\demo_attack.py "Approve the transfer of 250,000"
    .venv\\Scripts\\python scripts\\demo_attack.py --act 1        # just the forgery
    .venv\\Scripts\\python scripts\\demo_attack.py --no-colour    # for a projector

Why this exists alongside ``run_attack_lab.py`` and the ``/admin/attack`` page: those produce a
*report*, and a report is something you read. This is something you **do**, in front of someone,
on **their** input. The difference matters more than it sounds — an examiner watching a page of
green results is being asked to trust the page, whereas an examiner who types their own sentence
and watches it get forged has verified the claim themselves.

Three acts, each answering the objection the previous one creates:

1. **The attack that works.** They choose a decision. We are shown only the public key. Shor's
   algorithm factors it, we recover the private key, sign their text, and the application's **real
   verifier** accepts it.
2. **"So what, that key was tiny."** Correct, and here is what size does: real semiprimes factored
   live at increasing widths with timings, then the projection to 2048 bits — measured where it can
   be measured, cited where it cannot.
3. **The same attack against the post-quantum key.** Not "it fails" — it has no input. Then the
   best attack that actually exists against ML-DSA, run, and its measured success rate.

Nothing here is a mock. Every provider is the one the application resolves through, every
verification is the real ``verify``, and the private key is never handed to the attacker.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import random
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from qvault.attack import cost, shor, toy_rsa  # noqa: E402
from qvault.crypto import build_registry  # noqa: E402
from qvault.services import signing  # noqa: E402

DEFAULT_MESSAGE = "Approve the transfer of 250,000 to the escrow account"

# A beat between steps, tuned for being *narrated* rather than read. The computation itself is
# fast -- the whole demonstration takes about 20 seconds of actual work -- and that is too quick
# to talk over: the output scrolls past before an audience has read a line. At 1.2 s a step, all
# three acts run to roughly a minute, which is about the pace of someone explaining them.
# Override with --pace, or --fast for no pauses at all.
PAUSE = 1.2


class Out:
    """Console output with optional colour. ASCII only: projectors and cp1252 consoles vary."""

    def __init__(self, colour: bool = True, pause: float = PAUSE) -> None:
        self.colour = colour
        self.pause = pause

    def _c(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.colour else text

    def act(self, number: int, title: str) -> None:
        bar = "=" * 74
        print(f"\n{self._c('1;36', bar)}")
        print(self._c("1;36", f"  ACT {number}  -  {title.upper()}"))
        print(self._c("1;36", bar))

    def step(self, label: str, detail: str = "") -> None:
        print(f"\n{self._c('1', label)}")
        if detail:
            for line in detail.splitlines():
                print(f"  {line}")
        time.sleep(self.pause)

    def value(self, label: str, value: object) -> None:
        print(f"  {label:<34}{self._c('1;33', str(value))}")
        time.sleep(self.pause * 0.5)

    def good(self, text: str) -> None:
        print(f"\n  {self._c('1;32', text)}")
        time.sleep(self.pause)

    def bad(self, text: str) -> None:
        print(f"\n  {self._c('1;31', text)}")
        time.sleep(self.pause)

    def note(self, text: str) -> None:
        for line in text.splitlines():
            print(f"  {self._c('2', line)}")
        time.sleep(self.pause * 0.5)

    def say(self, text: str) -> None:
        """A line for the presenter to say out loud. Printed so it cannot be forgotten on stage."""
        print(f"\n  {self._c('1;35', 'SAY:')} {self._c('3', text)}")
        time.sleep(self.pause)


def ask_for_message(out: Out) -> str:
    """Get the decision to forge from the audience. Their input is the whole point."""
    print()
    out.note(
        "Hand the keyboard over. Whatever is typed here is what the attacker will forge --\n"
        "it is chosen after the keys exist, so nothing can have been prepared for it."
    )
    try:
        typed = input(f"\n  {'Decision to forge:':<34}").strip()
    except (EOFError, KeyboardInterrupt):
        typed = ""
    return typed or DEFAULT_MESSAGE


def act_one_forge(out: Out, message: str, rng: random.Random) -> None:
    """Recover an RSA private key from its public key, and forge an approval of ``message``."""
    out.act(1, "the attack that works")

    provider = toy_rsa.ToyRSASignatureProvider(toy_rsa.DEFAULT_BITS, rng=rng)
    keypair = provider.keygen()
    public = json.loads(keypair.public_key)
    # The canonical bytes Q-Vault actually signs for a vote, over the audience's text.
    signed_bytes = signing.vote_signing_bytes(
        proposal_payload_hash=hashlib.sha256(message.encode()).hexdigest(),
        decision="approve",
        signer_id=7,
    )

    out.step(
        "A signer registers an RSA signing key.",
        "The vault stores it and publishes the public half, exactly as any PKI does.",
    )
    out.value("public modulus  n =", public["n"])
    out.value("public exponent e =", public["e"])
    out.note(
        "RSA at a deliberately scaled 9-bit modulus. Act 2 is about exactly that, and it is\n"
        "the honest weakness of this demonstration -- do not skip it."
    )

    out.step(
        "The attacker's starting position.",
        "The two numbers above. No private key, no password, no side channel, no bug.",
    )
    out.value("decision being targeted:", f'"{message}"')
    out.value("canonical bytes to sign:", f"{len(signed_bytes)} B (DS_VOTE || canonical JSON)")

    out.step("Running Shor's algorithm to factor the modulus.")
    started = time.perf_counter()
    result = shor.shor_factor(public["n"], rng=rng)
    elapsed = (time.perf_counter() - started) * 1000
    if not result.succeeded:  # pragma: no cover - probabilistic; re-run
        out.bad("The simulated order-finding exhausted its rounds. Re-run -- Shor is probabilistic.")
        return
    last = result.order_runs[-1]
    out.value("simulation mode:", last.mode)
    out.value("control register:", f"{last.t} qubits, {last.amplitudes_held:,} complex amplitudes")
    out.value("circuit would need:", f"{last.qubits} qubits in total")
    out.value("measured k:", f"{last.measured_k}  (phase {last.phase})")
    out.value("order r recovered:", f"{last.candidate_r}  in {last.attempts} shot(s)")
    if result.redrawn_lucky_bases:
        out.note(
            f"{result.redrawn_lucky_bases} random base(s) discarded for sharing a factor with N.\n"
            "That shortcut exists only at toy sizes (~2^-1013 at 2048 bits), so the lab throws\n"
            "those draws away rather than counting a win it could not have at real scale."
        )
    p, q = result.factors
    out.good(f"FACTORED:  {public['n']} = {p} x {q}    ({len(result.order_runs)} round(s), {elapsed:.0f} ms)")

    out.step(
        "Recovering the private exponent.",
        "One modular inverse. Once the factors are known there is no brute force left to do,\n"
        "and nothing the key's owner can do about it.",
    )
    recovered_d = shor.recover_rsa_exponent(public["e"], p, q)
    true_d = json.loads(keypair.secret_key)["d"]
    out.value("recovered d =", recovered_d)
    out.value("the signer's real d =", f"{true_d}   (match: {recovered_d == true_d})")

    out.step("Signing the audience's decision with the recovered key.")
    representative = toy_rsa.digest_to_int(signed_bytes, public["n"])
    forged = pow(representative, recovered_d, public["n"]).to_bytes(
        (public["n"].bit_length() + 7) // 8, "big"
    )
    out.value("forged signature:", "0x" + forged.hex())

    out.step(
        "Handing the forgery to the application's real verifier.",
        "This is the same provider.verify() the vault calls when tallying a vote. Not a mock,\n"
        "not a reimplementation, and it is not told that anything unusual has happened.",
    )
    accepted = provider.verify(keypair.public_key, signed_bytes, forged)
    out.value("provider.verify(...) ->", accepted)
    if accepted:
        out.bad("FORGED. The system just accepted a decision that nobody approved.")
        out.say(
            "I never had the private key. I had the public key, and that was enough -- "
            "because factoring the modulus is the same thing as holding the private key."
        )
    else:  # pragma: no cover - would mean the recovery was wrong
        out.good("The forgery was rejected, which means the recovery failed. Re-run.")


def act_two_scale(out: Out, rng: random.Random) -> None:
    """Answer the obvious objection: the modulus was tiny. Show what size actually costs."""
    out.act(2, "yes, that key was tiny - here is what size costs")

    out.say(
        "The obvious objection is that I factored a 9-bit key, not a 2048-bit one. That is "
        "correct, and it is the right question. So let me show you the shape of the curve."
    )

    out.step(
        "Factoring real balanced semiprimes, classically, at increasing widths.",
        "Pollard's rho. Balanced factors, which is the hardest shape, so it is the fair one.",
    )
    print()
    print(f"  {'bits':>5}  {'modulus':>22}  {'rho steps':>12}  {'time':>10}")
    print(f"  {'-'*5}  {'-'*22}  {'-'*12}  {'-'*10}")
    for sample in cost.classical_factoring_curve(rng=rng, budget_s=25.0):
        print(
            f"  {sample.bits:>5}  {sample.n:>22}  {sample.iterations:>12,}  "
            f"{sample.seconds*1000:>8.1f}ms"
        )
        time.sleep(out.pause * 0.4)

    out.step(
        "Now the part that cannot be measured on a laptop, so it is cited instead.",
        "The projection is anchored on a published factorisation, not extrapolated from the\n"
        "timings above -- Pollard's rho is O(N^1/4) and the number field sieve is\n"
        "sub-exponential, so extrapolating those rows would badly overstate the difficulty.",
    )
    classical = cost.classical_projection(2048)
    quantum = cost.shor_resources(2048)
    latest = quantum["physical_estimates"][-1]
    out.value("anchor:", classical["anchor"])
    out.value("RSA-2048 / RSA-250 work:", f"{classical['gnfs_ratio_to_anchor']:.1e}x")
    out.value("RSA-2048 classically:", f"{classical['core_years_human']} core-years")
    out.value("  = times age of universe:", f"{classical['times_age_of_universe']:,.0f}x (one core)")
    out.value("RSA-2048 with Shor:", f"{latest['wall_clock']}, {latest['physical_qubits']:,} qubits")
    out.value("  source:", latest["source"])
    out.value("Shor's scaling:", quantum["scaling"])

    out.good(
        "Classical cost grows super-polynomially. Shor's grows as the cube of the key size."
    )
    out.say(
        "So the algorithm you just watched is the one that runs in a week on a machine "
        "people are building. The only thing I scaled down is the key, because I simulated "
        "the quantum part on this laptop."
    )
    regulatory = cost.summary()["regulatory"]
    out.note(
        f"And the deadline is not a prediction: {regulatory['source']} deprecates these\n"
        f"signatures after {regulatory['deprecated_after']} and disallows them after "
        f"{regulatory['disallowed_after']}."
    )


def act_three_pqc(out: Out, message: str, rng: random.Random) -> None:
    """Point the identical attack at ML-DSA-65 and show that it has no input."""
    out.act(3, "the same attack, against what we actually use")

    registry = build_registry(classical=False)
    provider = registry.signature("ML-DSA-65")
    keypair = provider.keygen()
    signed_bytes = signing.vote_signing_bytes(
        proposal_payload_hash=hashlib.sha256(message.encode()).hexdigest(),
        decision="approve",
        signer_id=7,
    )

    out.step(
        "The same signer, now with the algorithm this project actually uses.",
        "ML-DSA-65, FIPS 204. Same vault, same code path, same canonical payload.",
    )
    out.value("public key:", f"{len(keypair.public_key)} bytes")
    out.value("decision being targeted:", f'"{message}"')

    out.step(
        "Step 1 of the attack you just watched: obtain a modulus to factor.",
        "An ML-DSA public key is (rho, t1): a 32-byte seed and a vector of packed polynomial\n"
        "coefficients over a module lattice. There is no integer modulus in it.",
    )
    out.bad("NO INPUT AVAILABLE. The attack cannot be started, let alone fail.")
    analogue = shor.no_quantum_analogue("ML-DSA-65")
    print()
    for requirement in analogue["requires"]:
        print(f"    Shor needs:  {requirement}")
        print(f"    ML-DSA has:  {out._c('1;31', 'not present')}")
        time.sleep(out.pause * 0.5)

    out.say(
        "This is the part worth being precise about. Shor's algorithm does not fail against "
        "ML-DSA. It has no input to be given. The speed-up comes from finding a period in a "
        "finite group, and there is no group element here whose order is the secret."
    )

    attempts = 2000
    width = provider.meta.sizes["signature"]
    out.step(
        "So the attacker falls back to the best attack that does exist: guessing.",
        f"{attempts:,} random signatures of the correct length, each handed to the real verifier.",
    )
    accepted = 0
    started = time.perf_counter()
    for _ in range(attempts):
        if provider.verify(keypair.public_key, signed_bytes, os.urandom(width)):  # pragma: no cover
            accepted += 1
    out.value("attempts:", f"{attempts:,} in {(time.perf_counter()-started):.1f} s")
    out.value("accepted:", accepted)
    out.value("signature space:", f"2^{width*8:,}")
    out.value("expected successes:", f"{attempts} / 2^{width*8:,}")
    out.good("0 accepted, and the arithmetic says why: there is nothing to aim at.")

    out.note(
        "What is NOT being claimed: that ML-DSA is proven secure. No experiment can show that,\n"
        "and no lower bound on quantum lattice algorithms is known. What is shown is that the\n"
        "attack which ends RSA has no formulation here -- and the project's answer to the\n"
        "residual risk is agility: the ability to change algorithm without losing the data."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Perform the Q-Vault attack demonstration.")
    parser.add_argument("message", nargs="?", default=None, help="the decision to forge")
    parser.add_argument("--act", type=int, choices=(1, 2, 3), default=None, help="run one act only")
    parser.add_argument("--no-colour", action="store_true", help="plain text, for a projector")
    parser.add_argument("--fast", action="store_true", help="no pauses between steps")
    parser.add_argument(
        "--pace", type=float, default=None, help=f"seconds between steps (default {PAUSE})"
    )
    parser.add_argument("--seed", type=int, default=None, help="reproducible run")
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - older consoles; ASCII output survives regardless
        pass

    pace = 0.0 if args.fast else (args.pace if args.pace is not None else PAUSE)
    out = Out(colour=not args.no_colour, pause=max(0.0, pace))
    rng = random.Random(args.seed)

    print()
    print(out._c("1;36", "  Q-VAULT  -  LIVE ATTACK DEMONSTRATION"))
    out.note(
        "Three acts: an attack that works, the honest objection to it, and the same attack\n"
        "against the algorithm this project uses. Roughly four minutes."
    )

    message = args.message
    if message is None and args.act != 2:
        message = ask_for_message(out)
    message = message or DEFAULT_MESSAGE

    if args.act in (None, 1):
        act_one_forge(out, message, rng)
    if args.act in (None, 2):
        act_two_scale(out, rng)
    if args.act in (None, 3):
        act_three_pqc(out, message, rng)

    if args.act is None:
        print(f"\n{out._c('1;36', '=' * 74)}")
        out.say(
            "One sentence: the algorithm that breaks RSA ran here, to completion, on the "
            "decision you chose -- and against the algorithm we use, it has nothing to run on."
        )
        out.note(
            "The systematic version of this -- ten attacks, each with a control that must\n"
            "succeed for the result to count -- is at /admin/attack and in\n"
            "docs/attack-lab/latest.md. See docs/adr/0021-adversary-lab.md for the method."
        )
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
