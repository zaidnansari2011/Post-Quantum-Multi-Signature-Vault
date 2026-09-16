"""The live attack demonstration must not break between rehearsal and the room (ADR-0021).

``scripts/demo_attack.py`` is performed in front of people, on an arbitrary message they type. It
therefore has exactly the failure mode ADR-0011 was written about: a demonstration aid that breaks
on stage, or worse, one that keeps running while quietly no longer demonstrating anything.

So the things pinned here are the ones a rehearsal would not catch:

- every act runs to completion on an **arbitrary** message, including awkward input;
- the forgery in act 1 is genuinely accepted by the real verifier, and the recovered private
  exponent is the signer's actual one;
- act 3 really does submit its blind forgeries and really does have none accepted;
- the RSA private exponent *is* printed, deliberately — recovering it is the whole point — but
  the real ML-DSA secret key generated in act 3 must never reach the screen.
"""

from __future__ import annotations

import random
import re
import runpy
import sys

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from scripts import demo_attack  # noqa: E402

MESSAGES = [
    "Approve payment of 250,000 to the escrow account",
    "x",  # minimal
    'Release funds; "urgent" & <flagged> 100% — now',  # punctuation, quotes, an em dash
    "承認する — 支払い 250,000",  # non-latin, to catch an encoding assumption
    "A" * 500,  # long
]


@pytest.fixture()
def out():
    """The demo's console object with pauses removed and colour off."""
    return demo_attack.Out(colour=False, pause=0.0)


@pytest.mark.parametrize("message", MESSAGES)
def test_act_one_forges_any_message(out, message, capsys):
    """The attack must work on whatever the audience types, not on a prepared sentence."""
    demo_attack.act_one_forge(out, message, random.Random())
    printed = capsys.readouterr().out
    assert "FACTORED:" in printed
    assert "provider.verify(...) ->" in printed
    assert "True" in printed
    assert "FORGED. The system just accepted a decision that nobody approved." in printed
    assert "match: True" in printed  # the recovered d is the signer's real d


def test_act_one_really_uses_the_real_verifier(out, capsys, monkeypatch):
    """If the demo asserted its own success, the whole performance would be theatre.

    Proved by sabotage: force the provider's ``verify`` to reject everything, and the demo must
    report failure rather than printing its success line anyway.
    """
    real_verify = demo_attack.toy_rsa.ToyRSASignatureProvider.verify
    monkeypatch.setattr(
        demo_attack.toy_rsa.ToyRSASignatureProvider, "verify", lambda *a, **k: False
    )
    demo_attack.act_one_forge(out, "Approve it", random.Random())
    printed = capsys.readouterr().out
    assert "FORGED. The system just accepted" not in printed
    assert "the recovery failed" in printed
    assert demo_attack.toy_rsa.ToyRSASignatureProvider.verify is not real_verify  # sanity


def test_act_two_factors_real_numbers_and_cites_its_projection(out, capsys):
    demo_attack.act_two_scale(out, random.Random())
    printed = capsys.readouterr().out
    assert "rho steps" in printed
    assert "RSA-250" in printed  # the anchor is named, not hidden
    assert "core-years" in printed
    assert "arXiv" in printed  # the quantum estimate is attributed
    assert "2035" in printed  # the regulatory deadline


def test_act_three_has_no_input_and_no_accepted_forgery(out, capsys):
    demo_attack.act_three_pqc(out, "Approve payment of 250,000", random.Random())
    printed = capsys.readouterr().out
    assert "NO INPUT AVAILABLE" in printed
    assert "not present" in printed
    assert "accepted:" in printed
    assert "0 accepted" in printed
    # The limits of the claim must travel with it, on stage most of all.
    assert "NOT being claimed" in printed


def test_the_demo_never_reveals_the_pqc_secret_key(out, capsys):
    """Act 3 generates a real ML-DSA keypair; none of its secret must reach the screen.

    Sampled from ``secret_key[32:]`` because ML-DSA's public and private keys share their first
    32 bytes (the seed rho), so a prefix check would report a leak that is not one.
    """
    registry = demo_attack.build_registry(classical=False)
    provider = registry.signature("ML-DSA-65")
    keypair = provider.keygen()
    demo_attack.act_three_pqc(out, "Approve it", random.Random())
    printed = capsys.readouterr().out
    for offset in (32, 64, 128, 1024):
        assert keypair.secret_key[offset : offset + 12].hex() not in printed


def test_the_message_prompt_falls_back_when_there_is_no_input(out, monkeypatch):
    """Run non-interactively (CI, a piped shell) and the demo must still have something to forge."""
    monkeypatch.setattr("builtins.input", lambda *_: (_ for _ in ()).throw(EOFError))
    assert demo_attack.ask_for_message(out) == demo_attack.DEFAULT_MESSAGE
    monkeypatch.setattr("builtins.input", lambda *_: "   ")
    assert demo_attack.ask_for_message(out) == demo_attack.DEFAULT_MESSAGE


@pytest.mark.parametrize("act", [1, 2, 3])
def test_each_act_runs_from_the_command_line(act, capsys):
    """The documented invocations must work, since these are what gets typed on stage."""
    code = demo_attack.main(["Approve the payment", "--act", str(act), "--fast", "--no-colour"])
    assert code == 0
    assert f"ACT {act}" in capsys.readouterr().out


def test_the_whole_demo_runs_end_to_end(capsys):
    """All three acts, one invocation, no prompt. The rehearsal this file exists to replace."""
    assert demo_attack.main(["Approve the payment", "--fast", "--no-colour"]) == 0
    printed = capsys.readouterr().out
    for act in ("ACT 1", "ACT 2", "ACT 3"):
        assert act in printed
    assert "FORGED." in printed
    assert "NO INPUT AVAILABLE" in printed


def test_the_seed_makes_a_run_reproducible(capsys):
    """A seeded run replays identically, so a figure quoted in the write-up can be regenerated."""
    demo_attack.main(["Approve", "--act", "1", "--fast", "--no-colour", "--seed", "5"])
    first = capsys.readouterr().out
    demo_attack.main(["Approve", "--act", "1", "--fast", "--no-colour", "--seed", "5"])
    second = capsys.readouterr().out
    # Timings differ between runs; the cryptographic values must not.
    assert _values_only(first) == _values_only(second)


def _values_only(text: str) -> list[str]:
    """The cryptographic values from a run, with wall-clock timings stripped out.

    The timings are what a second run is *expected* to differ on, so leaving them in would make
    this test assert that the machine is deterministic rather than that the run is.
    """
    keep = ("public modulus", "public exponent", "FACTORED", "recovered d", "forged signature")
    lines = [line.strip() for line in text.splitlines() if any(k in line for k in keep)]
    return [re.sub(r",\s*\d+(\.\d+)?\s*ms", ", <time>", line) for line in lines]


def test_the_script_is_runnable_as_a_file():
    """``python scripts/demo_attack.py`` must work, not just the imported module."""
    sys.argv = ["demo_attack.py", "Approve", "--act", "1", "--fast", "--no-colour"]
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(str(__import__("pathlib").Path(demo_attack.__file__)), run_name="__main__")
    assert exit_info.value.code == 0


def test_the_pace_is_controllable_and_fast_means_no_pauses():
    """The default pace is tuned for narration, so tests and CI must be able to switch it off.

    Guards a specific footgun: the demonstration's default pause is 1.2 s a step, and without
    ``--fast`` the suite would spend minutes sleeping. It also checks ``--pace`` is honoured, since
    that is what gets used in a large room.
    """
    import time

    started = time.perf_counter()
    assert demo_attack.main(["Approve", "--act", "1", "--fast", "--no-colour"]) == 0
    fast_seconds = time.perf_counter() - started
    assert fast_seconds < 15, "the --fast path is sleeping when it should not be"

    assert demo_attack.Out(pause=0.0).pause == 0.0
    assert demo_attack.Out().pause == demo_attack.PAUSE
    assert demo_attack.PAUSE > 0, "a zero default would make the demonstration unreadable"


def test_a_negative_pace_cannot_crash_the_demonstration(capsys):
    """A mistyped flag on stage must not raise; it should simply mean no pause."""
    assert demo_attack.main(["Approve", "--act", "1", "--pace", "-5", "--no-colour"]) == 0
    assert "FORGED." in capsys.readouterr().out
