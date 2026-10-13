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


#: Characters that are assigned and not in a hidden category, yet draw nothing: the Hangul
#: fillers, the braille blank, the combining grapheme joiner, the Mongolian free variation
#: selectors and the variation selectors. Only U+FE0E and U+FE0F are left out, because they
#: choose how an emoji is drawn ("a heart" vs a red heart), which names legitimately use
#: (review of P4b, 2026-10-13: a name of one Hangul filler was stored and showed as blank).
_BLANK = frozenset(
    [0x034F, 0x115F, 0x1160, 0x180B, 0x180C, 0x180D, 0x180F, 0x2800, 0x3164, 0xFFA0]
    + list(range(0xFE00, 0xFE0E))
    + list(range(0xE0100, 0xE01F0))
)
#: More combining marks than this on one letter stack into a smear that hides what is under it.
_MAX_MARKS = 4


def _drawn_nothing(ch: str) -> bool:
    return unicodedata.category(ch) in _HIDDEN or unicodedata.category(ch) == "Cn" or ord(ch) in _BLANK


def invisible_in(text: str | None) -> bool:
    """Whether ``text`` holds a character that is not seen (or a control), apart from the ordinary
    spaces a person types: a hidden category, an unassigned code point, a character that draws
    nothing (``_BLANK``), or a pile of more than ``_MAX_MARKS`` combining marks."""
    run = 0
    for ch in text or "":
        if _drawn_nothing(ch):
            return True
        run = run + 1 if unicodedata.category(ch) in ("Mn", "Me") else 0
        if run > _MAX_MARKS:
            return True
    return False


def visible(text: object) -> str:
    """``text`` with every hidden character dropped and controls and separators made spaces, then
    folded to one line."""
    out = []
    for ch in str(text):
        category = unicodedata.category(ch)
        if category in ("Cc", "Zl", "Zp"):
            out.append(" ")
        elif not _drawn_nothing(ch):
            out.append(ch)
    return " ".join("".join(out).split())
