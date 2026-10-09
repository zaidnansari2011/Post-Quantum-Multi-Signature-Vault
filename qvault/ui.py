"""The facts the component macros in ``templates/ui/`` need from Python (rework S6, S7).

Kept out of the templates because each one is a rule that must hold on every screen: the closed
status vocabulary, how a time is written for a machine and for a person, and how a hash is cut
down without losing either end. ``register`` puts them on the Jinja environment.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

#: The closed status vocabulary (plan S6): one word per state, and the tone it always takes. A
#: badge outside this table is refused rather than invented on the spot.
STATUS: dict[str, tuple[str, str]] = {
    "needs_you": ("Needs your signature", "warning"),
    # Neutral, not info (S6 tone map, after the R1.1 critique): pending, but nothing for the viewer
    # to do, so it must not draw the eye the way "Needs your signature" does.
    "waiting": ("Waiting on {n}", "neutral"),
    # Derived, never stored (R5): an open decision too few people can still approve to pass. Shown
    # in place of "Waiting on N"; its lifecycle status stays open and nothing signed changes.
    "cannot_pass": ("Can’t pass", "warning"),
    "approved": ("Approved", "success"),
    "rejected": ("Rejected", "critical"),
    "expired": ("Expired", "neutral"),
    "withdrawn": ("Withdrawn", "neutral"),
    "queued": ("Queued", "info"),
    "paid": ("Paid", "success"),
    "failed": ("Failed", "critical"),
}

#: The five tones; anything else would be a colour with no agreed meaning.
TONES = ("neutral", "info", "success", "warning", "critical")


def status_of(key: str, n: int | None = None) -> tuple[str, str]:
    """The word and tone for ``key``. ``waiting`` needs ``n``, the approvals still needed."""
    try:
        word, tone = STATUS[key]
    except KeyError:
        raise ValueError(f"{key!r} is not in the status vocabulary") from None
    if "{n}" in word:
        if n is None:
            raise ValueError(f"the {key!r} status needs a count")
        word = word.format(n=n)
    return word, tone


def tone_of(tone: str) -> str:
    if tone not in TONES:
        raise ValueError(f"{tone!r} is not one of the five tones")
    return tone


def _utc(moment: datetime) -> datetime:
    # SQLite hands back naive datetimes even for timezone-aware columns; every time this app
    # stores is UTC, so a naive one is read as UTC rather than as the server's local time.
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def iso_utc(moment: datetime) -> str:
    """The machine-readable time for a ``datetime`` attribute, always with its zone."""
    return _utc(moment).isoformat(timespec="seconds").replace("+00:00", "Z")


def _moment(value: datetime | str | None) -> datetime | None:
    # A bundle or a recorded run carries its times as ISO text; read it back to a datetime.
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    return _utc(value) if isinstance(value, datetime) else None


def absolute_time(moment: datetime | str | None) -> str:
    """The time a person reads when precision matters: ``Sun 4 Oct 2026, 09:58 UTC``. ISO text
    is accepted too; nothing (or text that is not a time) reads as an empty string."""
    moment = _moment(moment)
    if moment is None:
        return ""
    return f"{moment:%a} {moment.day} {moment:%b %Y, %H:%M} UTC"


def day(moment: datetime | str | None) -> str:
    """A day alone, when the time of day says nothing (joined, created): ``4 Oct 2026``."""
    moment = _moment(moment)
    return "" if moment is None else f"{moment.day} {moment:%b %Y}"


def due(moment: datetime | None, now: datetime | None = None) -> dict | None:
    """A due time as lists and forms show it (screens.md, "Time and number rules").

    ``text`` is absolute, without the zone ("Tue 6 Oct, 17:00", "Today, 18:00"); the zone is
    ``zone``, for the places that name it. ``relative`` is the caption ("in 7 hours", "in 2 days",
    "3 days ago"): hours below two days, whole days above, always rounded down, so "in 2 days"
    never arrives early. ``soon`` is within the next 24 hours (the warning tone and clock icon);
    ``past`` is a deadline already gone. None when there is no deadline.
    """
    if moment is None:
        return None
    moment = _utc(moment)
    now = _utc(now) if now is not None else datetime.now(UTC)
    days = (moment.date() - now.date()).days
    clock = f"{moment:%H:%M}"
    if days == 0:
        text = f"Today, {clock}"
    elif days == 1:
        text = f"Tomorrow, {clock}"
    elif days == -1:
        text = f"Yesterday, {clock}"
    elif moment.year == now.year:
        text = f"{moment:%a} {moment.day} {moment:%b}, {clock}"
    else:
        text = f"{moment:%a} {moment.day} {moment:%b %Y}, {clock}"
    delta = moment - now
    left = abs(delta)
    if left < timedelta(hours=1):
        amount = max(1, int(left.total_seconds() // 60))
        unit = "minute"
    elif left < timedelta(hours=48):
        amount, unit = int(left.total_seconds() // 3600), "hour"
    else:
        amount, unit = left.days, "day"
    span = f"{amount} {unit}{'' if amount == 1 else 's'}"
    past = delta.total_seconds() <= 0
    return {
        "text": text,
        "zone": "UTC",
        "relative": f"{span} ago" if past else f"in {span}",
        "soon": not past and delta <= timedelta(hours=24),
        "past": past,
        "iso": iso_utc(moment),
        "full": absolute_time(moment),
    }


def decision_code(payload_hash: str) -> str:
    """The decision code (S17): the payload hash's first 8 hex characters, grouped ``7F3A-91C2``.

    A display of a hash both the web and the phone already compute, so nothing new is trusted.
    """
    head = str(payload_hash)[:8].upper()
    return f"{head[:4]}-{head[4:]}"


#: Small counts in a sentence are words, as the phone app writes them ("Three decisions need you");
#: counts in badges and tables stay numerals.
_COUNT_WORDS = ("No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine")


def count_word(n: int, *, capital: bool = True) -> str:
    """``n`` as a word up to nine, then as a numeral: ``Three``, ``12``."""
    if 0 <= n < len(_COUNT_WORDS):
        word = _COUNT_WORDS[n]
        return word if capital else word.lower()
    return str(n)


def first_name(name: str | None) -> str:
    """The name people are called by in lists and sentences (screens.md: first names only)."""
    name = (name or "").strip()
    if "@" in name and " " not in name:
        return name.split("@", 1)[0]
    return name.split(" ", 1)[0] if name else "Someone"


def name_list(names: list[str], *, conjunction: str = "and", limit: int = 4) -> str:
    """``Ada, Brij and Chen``; past ``limit`` names, ``Ada, Brij, Chen and 3 others``."""
    names = [n for n in names if n]
    if len(names) > limit:
        rest = len(names) - (limit - 1)
        names = names[: limit - 1] + [f"{rest} others"]
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} {conjunction} {names[-1]}"


def middle_truncate(value: str, head: int = 8, tail: int = 6) -> str:
    """``value`` with its middle replaced by an ellipsis, keeping both ends to compare by eye."""
    value = str(value)
    if len(value) <= head + tail + 1:
        return value
    # value[-0:] is the whole string, so a cut that keeps no tail must say so explicitly.
    return f"{value[:head]}…{value[-tail:] if tail else ''}"


_SUPERSCRIPT = str.maketrans("0123456789-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻")


def figures(text: str | None, *, dashes: bool = True) -> str:
    """Numbers in recorded prose written as a person would set them: ``2^128`` as 2¹²⁸,
    ``O(n^3)`` as O(n³), ``6.3e14`` as 6.3 × 10¹⁴, ``45589x`` as 45,589×, and a spaced hyphen
    used as a dash as an en dash. ``dashes=False`` for a value quoted as it was recovered."""
    if not text:
        return text or ""
    out = str(text)
    out = re.sub(r"\b(\d{5,})(?=x\b)", lambda m: f"{int(m[1]):,}", out)
    out = re.sub(r"(?<=\d)x\b", "×", out)
    out = re.sub(
        r"\b(\d+(?:\.\d+)?)e\+?(-?\d+)\b",
        lambda m: f"{m[1]} × 10{str(int(m[2])).translate(_SUPERSCRIPT)}",
        out,
    )
    out = re.sub(r"(?<=[\w)])\^(-?\d+)", lambda m: m[1].translate(_SUPERSCRIPT), out)
    # "2.3 × 10¹¹×" would read as a second multiplication.
    out = re.sub(r"(?<=[⁰¹²³⁴⁵⁶⁷⁸⁹])×", " times", out)
    if dashes:
        out = out.replace(" - ", " – ")
    return out


def standard_note(text: str | None) -> tuple[str, str]:
    """A provider's standard split from its remark: ``"FIPS 186-5 - classical, NOT post-quantum"``
    reads as ``("FIPS 186-5", "Classical, not post-quantum")``, in sentence case."""
    head, _, note = (text or "").partition(" - ")
    note = note.strip().replace("NOT ", "not ")
    return head.strip(), note[:1].upper() + note[1:]


def initials(name: str | None) -> str:
    """One letter for an avatar: the first letter of the name, or ``?`` when there is none."""
    name = (name or "").strip()
    return name[:1].upper() if name else "?"


def register(app) -> None:
    app.jinja_env.globals.update(
        ui_status=status_of,
        ui_tone=tone_of,
        ui_iso=iso_utc,
        ui_absolute=absolute_time,
        ui_day=day,
        ui_figures=figures,
        ui_standard=standard_note,
        ui_truncate=middle_truncate,
        ui_initials=initials,
        ui_due=due,
        ui_code=decision_code,
        ui_count_word=count_word,
        ui_first_name=first_name,
        ui_names=name_list,
    )
