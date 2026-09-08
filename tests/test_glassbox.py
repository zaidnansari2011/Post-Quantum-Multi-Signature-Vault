"""The glass box's own guarantees (ADR-0020).

Three things are worth pinning here, and they are not the rendering:

1. **Redaction fails closed.** An unwrapped value must never reach the page. This is the only
   part of the feature that could turn a demonstration surface into a disclosure, so it is tested
   from the direction an attacker would come: pass a secret in, assert it is not in the output.
2. **The code shown is the code that ran.** The entire argument for the page rests on this. If
   captured source could drift from the file on disk, the panel would be decoration.
3. **Tracing cannot change behaviour.** The instrumentation sits on the live signing path, so a
   traced vote and an untraced vote must be identical, and a broken presenter must not be able to
   fail an operation that has already succeeded.
"""

from __future__ import annotations

import inspect
import pathlib

import pytest

from qvault import glassbox
from qvault.glassbox import recorder, redaction, source
from qvault.services import signing


# ------------------------------------------------------------------------------------------
# 1. Redaction
# ------------------------------------------------------------------------------------------


def test_unwrapped_value_is_withheld_not_shown():
    """The default for anything the call site did not classify is opacity, not display."""
    rendered = redaction.present(b"correct horse battery staple")
    assert rendered.kind == "opaque"
    assert "horse" not in rendered.display
    assert rendered.fingerprint is None  # a digest of an unknown value is still a disclosure


def test_strict_mode_refuses_an_unwrapped_value():
    with pytest.raises(redaction.RedactionError):
        redaction.present(b"secret", strict=True)


def test_withheld_leaks_neither_content_nor_length():
    """A password's *length* narrows a search, and sha256(password) is offline-crackable."""
    rendered = redaction.present(redaction.Withheld("it is a password"))
    assert rendered.display == "withheld"
    assert rendered.size_bytes is None
    assert rendered.fingerprint is None


def test_opaque_states_length_but_never_content_or_digest():
    rendered = redaction.present(redaction.Opaque(b"\x01" * 4032, why="private key"))
    assert rendered.size_bytes == 4032
    assert "4,032" in rendered.display
    assert rendered.fingerprint is None
    assert "\x01" not in rendered.display


def test_check_command_reproduces_the_digest_that_is_displayed():
    """The 'check this yourself' affordance must actually be checkable.

    The command is hex piped through ``xxd -r``; if the hex in it were not exactly the bytes that
    were hashed, the page would be inviting readers to disprove a true claim.
    """
    import hashlib
    import re

    payload = 'a"quote"and-a-é'.encode()
    rendered = redaction.present(redaction.Text(payload))
    hex_in_command = re.search(r"echo -n ([0-9a-f]+)", rendered.check).group(1)
    assert bytes.fromhex(hex_in_command) == payload
    assert hashlib.sha256(bytes.fromhex(hex_in_command)).hexdigest() == rendered.fingerprint


def test_oversized_value_gets_no_check_command_rather_than_a_useless_one():
    rendered = redaction.present(redaction.Hex(b"\x00" * (redaction.CHECK_MAX_BYTES + 1)))
    assert rendered.check is None


def test_a_digest_is_never_truncated():
    """Half a hash cannot be compared against anything."""
    full = "ab" * 32
    assert redaction.present(redaction.Digest(full)).display == full


def test_json_presenter_shows_the_canonical_form_that_gets_hashed():
    rendered = redaction.present(redaction.Json({"b": 2, "a": 1}))
    assert rendered.display == '{"a":1,"b":2}'


# ------------------------------------------------------------------------------------------
# 2. Source capture -- the property the whole page rests on
# ------------------------------------------------------------------------------------------


def test_captured_source_matches_the_file_on_disk():
    """Captured text must be a verbatim slice of the repository file at the reported lines.

    This is the test that makes the code panel evidence rather than decoration. It reads the file
    independently of :mod:`inspect` and compares, so a capture that had been cached, rewritten or
    served from anywhere other than the loaded module would fail here.
    """
    captured = source.capture(signing.vote_signing_bytes)
    assert captured is not None

    repo_root = pathlib.Path(__file__).resolve().parents[1]
    on_disk = (repo_root / captured.path).read_text(encoding="utf-8").splitlines()
    expected = "\n".join(on_disk[captured.first_line - 1 : captured.last_line])

    assert captured.text == expected.rstrip("\n")
    assert captured.path == "qvault/services/signing.py"
    assert "def vote_signing_bytes" in captured.text


def test_capture_reports_a_repository_relative_path():
    """A reader is being invited to go and look at the file, so the path has to be findable."""
    captured = source.capture(signing.proposal_signing_bytes)
    assert not pathlib.Path(captured.path).is_absolute()
    assert captured.path.startswith("qvault/")


def test_capture_sees_through_decorators():
    from functools import wraps

    def decorate(fn):
        @wraps(fn)
        def wrapper(*a, **k):  # pragma: no cover - never called
            return fn(*a, **k)

        return wrapper

    @decorate
    def underlying_function():
        return "the body a reader should see"

    captured = source.capture(underlying_function)
    assert "the body a reader should see" in captured.text
    assert "wrapper" not in captured.text


def test_capture_returns_none_for_a_builtin_rather_than_raising():
    """A C function has no source. That is normal, and costs a panel, not a request."""
    assert source.capture(len) is None


def test_long_source_is_marked_truncated_rather_than_silently_cut(monkeypatch):
    monkeypatch.setattr(source, "MAX_LINES", 3)
    source._CACHE.clear()
    try:
        captured = source.capture(signing.vote_signing_bytes)
        assert captured.truncated is True
        assert len(captured.text.splitlines()) <= 3
        # The header renders this range, so it must describe the text actually shown -- including
        # when the cut lands on a blank line and the excerpt is trimmed back off it.
        assert captured.last_line - captured.first_line + 1 == len(captured.text.splitlines())
    finally:
        source._CACHE.clear()


# ------------------------------------------------------------------------------------------
# 3. The recorder
# ------------------------------------------------------------------------------------------


@pytest.fixture
def buffer():
    recorder.clear()
    recorder.configure(enabled=True, strict=True)
    yield
    recorder.clear()
    recorder.configure(enabled=False, strict=False)


def test_a_step_outside_an_operation_is_discarded(buffer):
    """``ledger_service.append`` runs in background jobs too; those must not reach the page."""
    with glassbox.step("orphan") as s:
        s.output("x", glassbox.Label(1))
    assert recorder.since(0)["operations"] == []


def test_an_operation_with_no_steps_is_discarded(buffer):
    """Every request opens one. Only the ones that did cryptographic work should survive."""
    with glassbox.operation("GET /favicon.ico"):
        pass
    assert recorder.since(0)["operations"] == []


def test_steps_are_recorded_in_order_with_their_values(buffer):
    with glassbox.operation("Cast vote", kind="sign"):
        with glassbox.step("First", code=signing.vote_signing_bytes) as s:
            s.input("decision", glassbox.Label("approve"))
            s.output("hash", glassbox.Digest("ab" * 32))
        with glassbox.step("Second") as s:
            s.output("n", glassbox.Number(3, unit="entries"))

    ops = recorder.since(0)["operations"]
    assert len(ops) == 1
    assert ops[0]["title"] == "Cast vote"
    assert ops[0]["status"] == "ok"
    assert [s["label"] for s in ops[0]["steps"]] == ["First", "Second"]
    assert ops[0]["steps"][0]["source"]["path"] == "qvault/services/signing.py"
    assert ops[0]["steps"][0]["inputs"][0]["display"] == "approve"
    assert ops[0]["steps"][0]["duration_ms"] >= 0


def test_a_failing_step_is_marked_and_the_exception_still_propagates(buffer):
    """Swallowing here would turn a rejected signature into a silent success."""
    with pytest.raises(ValueError):
        with glassbox.operation("Cast vote"):
            with glassbox.step("Verify") as s:
                s.input("sig", glassbox.Hex(b"\x00"))
                raise ValueError("did not verify")

    op = recorder.since(0)["operations"][0]
    assert op["status"] == "failed"
    assert op["steps"][0]["status"] == "failed"
    assert "did not verify" in op["steps"][0]["error"]


def test_describe_renames_the_open_operation(buffer):
    with glassbox.operation("vaults.vote", kind="request"):
        glassbox.describe(title="Cast an approve vote", subject="prop-1")
        with glassbox.step("s") as s:
            s.output("x", glassbox.Label(1))
    op = recorder.since(0)["operations"][0]
    assert op["title"] == "Cast an approve vote"
    assert op["subject"] == "prop-1"


def test_a_running_operation_with_no_steps_is_not_emitted(buffer):
    """It would be drawn as a permanent "running…" row.

    `close_operation` discards an operation that recorded nothing, so once emitted while empty it
    can never be superseded by a later poll -- the client has no way to learn it went away. Every
    poll of the events endpoint used to leave one of these behind on the page.
    """
    handle = recorder.open_operation("GET /trace/events")
    assert recorder.since(0)["operations"] == []

    with glassbox.step("something real") as s:
        s.output("x", glassbox.Label(1))
    assert len(recorder.since(0)["operations"]) == 1  # now it has something to say

    recorder.close_operation(handle)


def test_cursor_does_not_advance_past_a_running_operation(buffer):
    """Otherwise the client would never re-fetch it, and a slow operation would appear on screen
    frozen at whichever step it had reached when it was first polled."""
    handle = recorder.open_operation("Slow")
    with glassbox.step("Argon2id") as s:
        s.output("kek", glassbox.Withheld("secret"))

    first = recorder.since(0)
    assert first["operations"][0]["status"] == "running"
    assert first["cursor"] == handle.operation.seq - 1

    again = recorder.since(first["cursor"])
    assert [op["seq"] for op in again["operations"]] == [handle.operation.seq]

    recorder.close_operation(handle)
    assert recorder.since(first["cursor"])["cursor"] == handle.operation.seq


def test_the_buffer_is_bounded(buffer):
    for i in range(recorder.MAX_OPERATIONS + 15):
        with glassbox.operation(f"op {i}"):
            with glassbox.step("s") as s:
                s.output("x", glassbox.Label(i))
    assert len(recorder.since(0)["operations"]) == recorder.MAX_OPERATIONS


def test_disabled_recorder_records_nothing_and_still_yields(buffer):
    recorder.configure(enabled=False, strict=False)
    with glassbox.operation("Cast vote") as op:
        assert op is None
        with glassbox.step("Sign", code=signing.vote_signing_bytes) as s:
            s.input("x", glassbox.Label(1))  # must be accepted and ignored
    assert recorder.since(0)["operations"] == []


def test_a_broken_presenter_cannot_fail_the_operation(buffer):
    """A trace is a courtesy on top of work that already happened."""
    recorder.configure(enabled=True, strict=False)

    class Exploding(glassbox.Value):
        def render(self):
            raise RuntimeError("presenter is broken")

    with glassbox.operation("Cast vote"):
        with glassbox.step("Sign") as s:
            s.output("signature", Exploding())

    op = recorder.since(0)["operations"][0]
    assert op["status"] == "ok"
    assert op["steps"][0]["outputs"][0]["kind"] == "opaque"


def test_nested_contexts_do_not_leak_between_operations(buffer):
    with glassbox.operation("First"):
        with glassbox.step("a") as s:
            s.output("x", glassbox.Label(1))
    with glassbox.operation("Second"):
        with glassbox.step("b") as s:
            s.output("x", glassbox.Label(2))

    ops = recorder.since(0)["operations"]
    assert [len(op["steps"]) for op in ops] == [1, 1]
    assert [op["steps"][0]["label"] for op in ops] == ["a", "b"]


def test_every_public_presenter_is_exported():
    """A call site that cannot reach a presenter will reach for a raw value instead."""
    for name in ("Digest", "Hex", "Json", "Label", "Number", "Opaque", "Text", "Withheld"):
        assert hasattr(glassbox, name), name
        assert issubclass(getattr(glassbox, name), redaction.Value)


def test_recorder_does_not_import_flask_at_module_level():
    """``_flags`` imports Flask lazily so the recorder stays usable from scripts and the
    scheduler. Pinning it prevents a future edit hoisting the import to the top."""
    tree = inspect.getsource(recorder)
    header = tree.split("def _now_iso")[0]
    assert "import flask" not in header
    assert "from flask" not in header
