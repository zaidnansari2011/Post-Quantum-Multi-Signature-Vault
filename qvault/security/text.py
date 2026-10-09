"""Names people choose, kept to what a reader sees (plan R8 review, F6).

A display name, a vault's name and a workspace's name are shown to other people: on pages, in
emails and on lock screens. Unicode lets such a name carry characters that are not seen but change
what is seen: a right-to-left override that makes ``gnp.exe`` read as ``exe.png``, zero-width
characters that make two names look the same, controls that break a line. These are refused when
a name is typed (``invisible_in``) and removed wherever a stored name is written into an email or a
push (``visible``), so names stored before this check are cleaned on the way out too.
"""

from __future__ import annotations

import unicodedata

#: Format (bidi controls, zero-width characters), private use, surrogates and controls; and the
#: line and paragraph separators, which break a line like a newline does.
_HIDDEN = {"Cf", "Co", "Cs", "Cc", "Zl", "Zp"}

MESSAGE = "Remove the invisible or text-direction characters from it."


def invisible_in(text: str | None) -> bool:
    """Whether ``text`` holds a character that is not seen (or a control), apart from the ordinary
    spaces a person types."""
    return any(unicodedata.category(ch) in _HIDDEN for ch in (text or ""))


def visible(text: object) -> str:
    """``text`` with every hidden character dropped and controls and separators made spaces, then
    folded to one line."""
    out = []
    for ch in str(text):
        category = unicodedata.category(ch)
        if category in ("Cc", "Zl", "Zp"):
            out.append(" ")
        elif category not in _HIDDEN:
            out.append(ch)
    return " ".join("".join(out).split())
