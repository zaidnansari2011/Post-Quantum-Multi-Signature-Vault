"""How a traced value is allowed to appear on screen.

The glass box shows real bytes from a running security system, which makes this module the one
place where a mistake is not cosmetic. The design rule is therefore inverted from the obvious one:

    **Visibility is opt-in. Anything not explicitly wrapped is opaque.**

A denylist ("hide anything called password") fails the moment somebody adds a traced value and
forgets to name it in the list, and in a project whose subject is key custody that failure would
be a genuine vulnerability rather than an untidy page. So :func:`present` coerces every unwrapped
value to :class:`Opaque`, which renders a size and a digest and never the content. To show a value
you must say so at the call site, in the same line of code a reviewer reads.

``strict`` turns the coercion into an exception instead. It is on under TESTING so the suite fails
on an unwrapped value, and off in every other configuration because a trace is a courtesy on top
of an operation that has already happened: a presentation bug must never turn a recorded vote into
a 500.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

#: Raw bytes shown in a hex preview before elision. 64 bytes is two full lines of hex at the
#: page's column width, and enough that a reader sees genuine high-entropy material rather than a
#: label claiming it exists.
MAX_HEX_BYTES = 64

#: Characters of decoded text shown before elision.
MAX_TEXT_CHARS = 900

#: Inputs at or below this size get a copy-pasteable shell command that recomputes their digest.
#: Beyond it the command would be a screenful of hex that nobody will actually run, so the offer
#: is withdrawn rather than made uselessly.
CHECK_MAX_BYTES = 4096


class RedactionError(TypeError):
    """A value reached the recorder without declaring how it may be shown."""


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _check_command(data: bytes) -> str | None:
    """A shell one-liner that reproduces ``sha256(data)`` on the reader's own machine.

    Hex in, ``xxd -r`` back to bytes: the alternative -- quoting the literal text into ``printf``
    -- silently mangles the moment the canonical JSON contains a quote or a non-ASCII character,
    which is precisely when a reader most wants to check it.
    """
    if len(data) > CHECK_MAX_BYTES:
        return None
    return "echo -n " + data.hex() + " | xxd -r -p | sha256sum"


@dataclass(frozen=True)
class Rendered:
    """The only shape the recorder stores. No presenter hands out the original object."""

    kind: str
    display: str
    detail: str | None = None
    size_bytes: int | None = None
    fingerprint: str | None = None
    check: str | None = None
    truncated: bool = False

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "display": self.display,
            "detail": self.detail,
            "size_bytes": self.size_bytes,
            "fingerprint": self.fingerprint,
            "check": self.check,
            "truncated": self.truncated,
        }


class Value:
    """Base class for the presenters. Subclasses decide what a reader is allowed to see."""

    def render(self) -> Rendered:  # pragma: no cover - abstract
        raise NotImplementedError


class Withheld(Value):
    """Nothing at all: not the content, not the length, not a digest.

    For material where *any* function of the value is a disclosure. A password is the clear case:
    ``sha256(password)`` is an offline-crackable hash, and even its length narrows a search. This
    is the correct presenter for the password itself and for the KEK derived from it.
    """

    def __init__(self, reason: str):
        self._reason = reason

    def render(self) -> Rendered:
        return Rendered(kind="withheld", display="withheld", detail=self._reason)


class Opaque(Value):
    """Size only -- never content. The default for anything unwrapped.

    Used deliberately for secret material whose *length* is already public knowledge: an unwrapped
    ML-DSA private key is 4,032 bytes for everyone, so stating it discloses nothing while making
    the page substantially more informative.

    The digest is **opt-in** and off by default. A digest of a secret is a commitment to it, which
    lets anyone who can guess the value confirm the guess -- so it is available for long
    non-secret values where identity matters, and must be requested explicitly.
    """

    def __init__(self, data: object, *, why: str | None = None, fingerprint: bool = False):
        self._raw = data if isinstance(data, (bytes, bytearray)) else repr(data).encode("utf-8")
        self._why = why
        self._fingerprint = fingerprint

    def render(self) -> Rendered:
        raw = bytes(self._raw)
        return Rendered(
            kind="opaque",
            display=f"{len(raw):,} bytes withheld",
            detail=self._why,
            size_bytes=len(raw),
            fingerprint=_digest(raw) if self._fingerprint else None,
        )


class Hex(Value):
    """Bytes as hex. For material that is public by construction: signatures, public keys,
    ciphertexts, nonces, Merkle nodes."""

    def __init__(self, data: bytes, *, note: str | None = None, full: bool = False):
        self._raw = bytes(data)
        self._note = note
        self._full = full

    def render(self) -> Rendered:
        raw = self._raw
        shown = raw if self._full else raw[:MAX_HEX_BYTES]
        return Rendered(
            kind="hex",
            display=shown.hex(),
            detail=self._note,
            size_bytes=len(raw),
            fingerprint=_digest(raw),
            check=_check_command(raw),
            truncated=len(shown) < len(raw),
        )


class Text(Value):
    """Bytes (or a string) shown as text. For the canonical payloads that get signed and hashed --
    the one place where a reader can see, in full, exactly what a signature commits to."""

    def __init__(self, data: bytes | str, *, note: str | None = None):
        self._raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        self._note = note

    def render(self) -> Rendered:
        raw = self._raw
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            # Not text after all. Fall back to hex rather than mangling it with replacement
            # characters, which would show a value that hashes to something else entirely.
            return Hex(raw, note=self._note).render()
        shown = text[:MAX_TEXT_CHARS]
        return Rendered(
            kind="text",
            display=shown,
            detail=self._note,
            size_bytes=len(raw),
            fingerprint=_digest(raw),
            check=_check_command(raw),
            truncated=len(shown) < len(text),
        )


class Digest(Value):
    """A hash, shown in full. Never truncated: a half-printed digest cannot be compared against
    anything, which defeats the only reason to show it."""

    def __init__(self, value: bytes | str, *, note: str | None = None):
        self._hex = value.hex() if isinstance(value, (bytes, bytearray)) else str(value)
        self._note = note

    def render(self) -> Rendered:
        return Rendered(kind="digest", display=self._hex, detail=self._note)


class Json(Value):
    """A structure, shown as the canonical bytes it will actually become.

    Rendering it with ``sort_keys``/no-whitespace rather than pretty-printing is the point: the
    reader sees the exact serialization that gets hashed, so their own ``sha256`` matches.
    """

    def __init__(self, obj: object, *, note: str | None = None):
        self._obj = obj
        self._note = note

    def render(self) -> Rendered:
        try:
            raw = json.dumps(
                self._obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
        except (TypeError, ValueError):
            return Opaque(self._obj, why="not serialisable").render()
        return Text(raw, note=self._note).render()


class Label(Value):
    """A short caption: an algorithm id, a decision, a status. Carries no byte semantics."""

    def __init__(self, value: object, *, note: str | None = None):
        self._value = value
        self._note = note

    def render(self) -> Rendered:
        return Rendered(kind="label", display=str(self._value), detail=self._note)


class Number(Value):
    """A count, a size, a duration."""

    def __init__(self, value: float | int, *, unit: str | None = None, note: str | None = None):
        self._value = value
        self._unit = unit
        self._note = note

    def render(self) -> Rendered:
        text = f"{self._value:,}" if isinstance(self._value, int) else f"{self._value:.3f}"
        return Rendered(
            kind="number",
            display=f"{text} {self._unit}" if self._unit else text,
            detail=self._note,
        )


def present(value: object, *, strict: bool = False) -> Rendered:
    """Render ``value``, coercing anything undeclared to :class:`Opaque`.

    This function is the enforcement point for the module's rule, which is why the coercion lives
    here rather than at each call site: there is exactly one path from a traced value to the
    screen, and it fails closed.
    """
    if isinstance(value, Value):
        return value.render()
    if strict:
        raise RedactionError(
            f"{type(value).__name__} was traced without a presenter. Wrap it in Hex/Text/Digest/"
            "Json/Label/Number to show it, or Opaque(...) to withhold it deliberately."
        )
    return Opaque(value, why="traced without a presenter").render()
