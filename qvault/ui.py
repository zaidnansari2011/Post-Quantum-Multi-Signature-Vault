"""The facts the component macros in ``templates/ui/`` need from Python (rework S6, S7).

Kept out of the templates because each one is a rule that must hold on every screen: the closed
status vocabulary, how a time is written for a machine and for a person, and how a hash is cut
down without losing either end. ``register`` puts them on the Jinja environment.
"""

from __future__ import annotations

from datetime import UTC, datetime

#: The closed status vocabulary (plan S6): one word per state, and the tone it always takes. A
#: badge outside this table is refused rather than invented on the spot.
STATUS: dict[str, tuple[str, str]] = {
    "needs_you": ("Needs your signature", "warning"),
    "waiting": ("Waiting on {n}", "info"),
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


def absolute_time(moment: datetime) -> str:
    """The time a person reads when precision matters: ``Sun 4 Oct 2026, 09:58 UTC``."""
    moment = _utc(moment)
    return f"{moment:%a} {moment.day} {moment:%b %Y, %H:%M} UTC"


def middle_truncate(value: str, head: int = 8, tail: int = 6) -> str:
    """``value`` with its middle replaced by an ellipsis, keeping both ends to compare by eye."""
    value = str(value)
    if len(value) <= head + tail + 1:
        return value
    return f"{value[:head]}…{value[-tail:]}"


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
        ui_truncate=middle_truncate,
        ui_initials=initials,
    )
