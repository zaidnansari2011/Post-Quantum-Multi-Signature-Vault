"""Read the code that just ran, from the object that ran it.

The whole difficulty with "show the user your source code" is that a page can print anything. A
snippet pasted into a template proves nothing at all -- it is a claim about the code, sitting one
careless edit away from being false, and an examiner is right to dismiss it.

So nothing here stores or copies source. :func:`capture` calls :func:`inspect.getsource` on the
live function object the caller is about to invoke, which reads the file the interpreter loaded
this function from and reports its real path and line numbers. The text on screen is the text that
executed, by construction rather than by promise -- and ``tests/test_glassbox_source.py`` pins
that property by checking captured text against the file on disk.

The limit is worth stating as plainly as the guarantee, because it is the first thing a sceptical
reader should ask: this shows Python we wrote. It cannot show the interior of ML-DSA or SLH-DSA,
which are compiled PQClean binaries called through the provider. For those the trace shows the
call and its arguments -- message, key, signature, verdict, timing -- and the page says so rather
than implying a visibility it does not have.
"""

from __future__ import annotations

import inspect
import pathlib
from dataclasses import dataclass

#: Beyond this many lines a function stops being readable on screen and becomes wallpaper. The
#: excerpt is marked truncated rather than silently cut, because a reader comparing it with the
#: repository must be able to tell the difference between "this is all of it" and "there is more".
MAX_LINES = 130

#: Everything above this directory is repository-relative. Anchoring on the package's parent means
#: a captured path reads ``qvault/services/signing.py`` on any machine, which is what a reader
#: needs in order to go and look at it themselves.
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

_CACHE: dict[str, "Source"] = {}


@dataclass(frozen=True)
class Source:
    """An excerpt of real source, with the coordinates needed to find it in the repository."""

    path: str
    qualname: str
    first_line: int
    last_line: int
    text: str
    truncated: bool

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "qualname": self.qualname,
            "first_line": self.first_line,
            "last_line": self.last_line,
            "text": self.text,
            "truncated": self.truncated,
        }


def _relative(path: str) -> str:
    try:
        return pathlib.Path(path).resolve().relative_to(_REPO_ROOT).as_posix()
    except (ValueError, OSError):  # outside the repo (a stdlib or site-packages function)
        return pathlib.Path(path).name


def capture(fn: object) -> Source | None:
    """Return the source of ``fn``, or ``None`` if it cannot be read.

    ``None`` is a normal outcome, not an error: a C function, a lambda defined in a REPL, or a
    module compiled without its source present all reach here legitimately. The trace loses a
    panel; nothing else changes.
    """
    if fn is None:
        return None

    # See through @wraps decorators to the function whose body actually contains the logic --
    # otherwise every decorated service function would display the decorator's three-line wrapper.
    target = inspect.unwrap(fn) if callable(fn) else fn
    key = f"{getattr(target, '__module__', '?')}.{getattr(target, '__qualname__', repr(target))}"
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    try:
        lines, first_line = inspect.getsourcelines(target)
        file_path = inspect.getsourcefile(target) or inspect.getfile(target)
    except (OSError, TypeError):
        return None

    truncated = len(lines) > MAX_LINES
    shown = lines[:MAX_LINES]
    # Drop trailing blank lines *before* computing the line range. Trimming them afterwards
    # (or letting the text be rstripped on the way out) leaves the panel's "lines 48-50" header
    # naming a line the panel is not showing -- a small lie on the one page whose entire claim is
    # that what it displays is exactly what is in the file.
    while shown and not shown[-1].strip():
        shown.pop()

    source = Source(
        path=_relative(file_path),
        qualname=getattr(target, "__qualname__", key),
        first_line=first_line,
        last_line=first_line + len(shown) - 1,
        text="".join(shown).rstrip("\n"),
        truncated=truncated,
    )
    _CACHE[key] = source
    return source
