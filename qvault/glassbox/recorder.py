"""The trace buffer: what ran, in what order, on what bytes.

A recorded operation is a tree exactly one level deep -- an *operation* a person triggered ("Cast
vote"), containing the *steps* the machine took to carry it out. That shape is deliberate. A full
call tree would be honest and unreadable; a flat list would lose the thing the page exists to
show, which is that one human action decomposes into a specific, finite, inspectable sequence of
cryptographic operations.

Three properties the rest of the system depends on:

* **A step outside an operation is discarded.** ``ledger_service.append`` is called from a dozen
  places, most of them background jobs; instrumenting it must not fill the page with events nobody
  asked about. Steps attach to the operation open in the current context, and vanish if there is
  none.
* **Nothing here can fail an operation.** Every entry point swallows its own exceptions. The vote
  is already cast by the time a step renders; a presentation bug that rolled it back would be a
  far worse defect than a missing panel.
* **The context is a :mod:`contextvars` variable, not a global.** The scheduler runs jobs on its
  own threads while requests are being served, and a global "current operation" would file a
  rotation job's steps under whichever vote happened to be in flight.

The buffer itself *is* process-global, and bounded. It holds recent operations for a page that
polls, not a record of anything -- the record is the ledger, which is signed. Losing the oldest
trace to the ring buffer costs nothing.
"""

from __future__ import annotations

import contextvars
import itertools
import threading
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import perf_counter_ns

from qvault.glassbox import source as source_module
from qvault.glassbox.redaction import Rendered, present

#: Operations retained in the ring buffer. Enough for a demo session to scroll back through the
#: whole story it just told, small enough that the buffer can never become a memory concern.
MAX_OPERATIONS = 60

_lock = threading.Lock()
_operations: deque["Operation"] = deque(maxlen=MAX_OPERATIONS)
_seq = itertools.count(1)

#: The operation open in this context, if any. Set by :func:`operation`, read by :func:`step`.
_current: contextvars.ContextVar["Operation | None"] = contextvars.ContextVar(
    "glassbox_current_operation", default=None
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class Step:
    """One machine action inside an operation."""

    label: str
    index: int
    started_at: str
    note: str | None = None
    source: source_module.Source | None = None
    inputs: list[tuple[str, Rendered]] = field(default_factory=list)
    outputs: list[tuple[str, Rendered]] = field(default_factory=list)
    duration_ms: float | None = None
    status: str = "ok"
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "label": self.label,
            "index": self.index,
            "started_at": self.started_at,
            "note": self.note,
            "source": self.source.as_dict() if self.source is not None else None,
            "inputs": [{"name": n, **v.as_dict()} for n, v in self.inputs],
            "outputs": [{"name": n, **v.as_dict()} for n, v in self.outputs],
            "duration_ms": self.duration_ms,
            "status": self.status,
            "error": self.error,
        }


@dataclass
class Operation:
    """One human-triggered action, and every step it took."""

    seq: int
    title: str
    kind: str
    started_at: str
    actor: str | None = None
    subject: str | None = None
    steps: list[Step] = field(default_factory=list)
    duration_ms: float | None = None
    status: str = "running"

    def as_dict(self) -> dict:
        return {
            "seq": self.seq,
            "title": self.title,
            "kind": self.kind,
            "started_at": self.started_at,
            "actor": self.actor,
            "subject": self.subject,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "steps": [s.as_dict() for s in self.steps],
        }


# --- enablement -----------------------------------------------------------------------------

#: Used only when there is no application context (unit tests of this package, and nothing else).
_fallback = {"enabled": False, "strict": False}


def configure(*, enabled: bool, strict: bool = False) -> None:
    """Set the out-of-app-context defaults. Tests use this; the application does not."""
    _fallback["enabled"] = enabled
    _fallback["strict"] = strict


def _flags() -> tuple[bool, bool]:
    """``(enabled, strict)`` for the current context.

    Read from ``current_app.config`` on every call rather than cached at startup, so a test that
    flips ``GLASSBOX_ENABLED`` on an app fixture takes effect without re-importing anything, and
    so two apps in one process cannot inherit each other's setting.
    """
    try:
        from flask import current_app, has_app_context

        if not has_app_context():
            return _fallback["enabled"], _fallback["strict"]
        return (
            bool(current_app.config.get("GLASSBOX_ENABLED", False)),
            bool(current_app.config.get("GLASSBOX_STRICT")),
        )
    except Exception:  # noqa: BLE001 - never let enablement checking raise into a request
        return False, False


def enabled() -> bool:
    return _flags()[0]


# --- recording ------------------------------------------------------------------------------


class _NullStep:
    """What :func:`step` yields when tracing is off: every method is a no-op.

    Call sites therefore cost one attribute lookup and one function call each when the glass box
    is disabled, which is what lets the instrumentation live on the real signing path without
    being an asterisk on the benchmark figures.
    """

    def input(self, *_args, **_kwargs) -> None:
        return None

    def output(self, *_args, **_kwargs) -> None:
        return None

    def annotate(self, *_args, **_kwargs) -> None:
        return None

    def code(self, *_args, **_kwargs) -> None:
        return None


_NULL_STEP = _NullStep()


class _LiveStep:
    """A recording step. Values are rendered on arrival, so the recorder never retains a reference
    to a secret -- only to the :class:`~qvault.glassbox.redaction.Rendered` view of it."""

    def __init__(self, step: Step, strict: bool):
        self._step = step
        self._strict = strict

    def _render(self, value: object) -> Rendered:
        try:
            return present(value, strict=self._strict)
        except Exception:
            if self._strict:
                raise
            return present(None)

    def input(self, name: str, value: object) -> None:
        self._step.inputs.append((name, self._render(value)))

    def output(self, name: str, value: object) -> None:
        self._step.outputs.append((name, self._render(value)))

    def annotate(self, note: str) -> None:
        self._step.note = note

    def code(self, fn: object) -> None:
        self._step.source = source_module.capture(fn)


@dataclass
class _Handle:
    """What :func:`open_operation` hands back so :func:`close_operation` can finish the job."""

    operation: Operation
    token: object
    started_ns: int


def open_operation(
    title: str, *, kind: str = "", actor: str | None = None, subject: str | None = None
) -> _Handle | None:
    """Begin recording. Returns a handle to pass to :func:`close_operation`, or ``None``.

    Deliberately *not* a context manager, because the span this needs to cover is a Flask request
    -- ``before_request`` to ``teardown_request`` -- and those are two separate callbacks with no
    block between them to wrap.

    Scoping an operation to the request rather than to a service call is what makes the trace
    complete. The Merkle checkpoint and the ledger head anchor are re-computed in an
    ``after_request`` hook, long after ``cast_vote`` has returned; an operation that closed with
    the service call would end just before the most interesting step in it.
    """
    if not _flags()[0]:
        return None
    op = Operation(
        seq=next(_seq), title=title, kind=kind, started_at=_now_iso(), actor=actor, subject=subject
    )
    with _lock:
        _operations.append(op)
    return _Handle(operation=op, token=_current.set(op), started_ns=perf_counter_ns())


def close_operation(handle: _Handle | None, *, failed: bool = False) -> None:
    """Finish an operation, and **discard it if it recorded nothing**.

    Every request opens one of these, because there is no way to know in advance whether a request
    will do any cryptography. Almost none of them do -- loading a page, fetching the trace itself.
    Dropping the empty ones here is what keeps the page a record of meaningful work instead of an
    access log, and it means instrumentation can be added anywhere without anyone having to
    maintain a list of which endpoints are interesting.
    """
    if handle is None:
        return
    op = handle.operation
    try:
        op.duration_ms = (perf_counter_ns() - handle.started_ns) / 1e6
        op.status = "failed" if failed else "ok"
        if not op.steps:
            with _lock:
                try:
                    _operations.remove(op)
                except ValueError:  # already pushed out of the ring buffer
                    pass
    finally:
        # Reset unconditionally. Server threads are pooled and reused, so a token left set here
        # would file the next request's steps under this request's operation.
        try:
            _current.reset(handle.token)
        except ValueError:  # pragma: no cover - token from a different context
            _current.set(None)


def describe(
    *, title: str | None = None, kind: str | None = None, subject: str | None = None
) -> None:
    """Name the operation currently open, from inside the code that knows what it is doing.

    The request hooks can only title an operation after its URL rule ("POST vaults.vote"), which
    is how the machine sees it. The service knows it as "Cast vote", which is how a person does.
    """
    op = _current.get()
    if op is None:
        return
    if title is not None:
        op.title = title
    if kind is not None:
        op.kind = kind
    if subject is not None:
        op.subject = subject


@contextmanager
def operation(title: str, *, kind: str = "", actor: str | None = None, subject: str | None = None):
    """Block-scoped operation, for work that is not a request: scheduler jobs, scripts, tests."""
    handle = open_operation(title, kind=kind, actor=actor, subject=subject)
    if handle is None:
        yield None
        return
    try:
        yield handle.operation
    except BaseException:
        close_operation(handle, failed=True)
        raise
    close_operation(handle)


@contextmanager
def step(label: str, *, code: object = None, note: str | None = None):
    """Record one step of the operation currently open in this context.

    The block's exceptions propagate untouched -- the step is marked failed and re-raised. A step
    that swallowed an error would turn a rejected signature into a silent success, which in this
    application is the exact failure the whole page exists to make impossible.
    """
    is_enabled, strict = _flags()
    op = _current.get()
    if not is_enabled or op is None:
        yield _NULL_STEP
        return

    record = Step(
        label=label,
        index=len(op.steps),
        started_at=_now_iso(),
        note=note,
        source=source_module.capture(code) if code is not None else None,
    )
    op.steps.append(record)
    live = _LiveStep(record, strict)
    started = perf_counter_ns()
    try:
        yield live
    except BaseException as exc:
        record.status = "failed"
        record.error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        record.duration_ms = (perf_counter_ns() - started) / 1e6


# --- reading --------------------------------------------------------------------------------


def since(after: int = 0) -> dict:
    """Operations newer than ``after``, oldest first, with the cursor to ask with next time.

    Returning a *running* operation is the point -- a slow one (Argon2id at ~80 ms, then a
    signature) should appear while it is still happening, which is the difference between a live
    trace and a report. But a running operation is also incomplete, so the cursor must not advance
    past it: it is ``min(seq of anything still running) - 1``, which makes the next poll re-fetch
    that operation and any that finished after it.

    A naive "highest seq I have seen" cursor instead freezes the first render of a running
    operation on screen forever -- the client would never ask for it again, and a vote would be
    permanently displayed as having stopped at Argon2id.

    The client keys operations by ``seq`` and replaces, so re-sending one costs a repaint.
    """
    with _lock:
        snapshot = list(_operations)

    # An operation with no steps yet has nothing to say, and emitting one is worse than useless:
    # the client would draw a "running…" row for it, and when it closes having recorded nothing,
    # `close_operation` discards it server-side — so no later poll ever returns it, and the empty
    # row stays on screen forever. Every poll of this very endpoint left one behind.
    fresh = [op for op in snapshot if op.seq > after and op.steps]
    running = [op.seq for op in snapshot if op.status == "running"]
    highest = snapshot[-1].seq if snapshot else after
    cursor = min(running) - 1 if running else highest
    return {
        "operations": [op.as_dict() for op in fresh],
        # Floor at zero: sequences start at 1, so the first operation being the running one gives
        # min(running) - 1 == 0, which is already the "send me everything" cursor.
        "cursor": max(cursor, 0),
        "enabled": True,
    }


def clear() -> None:
    """Empty the buffer. The demo needs a clean page between takes."""
    with _lock:
        _operations.clear()
