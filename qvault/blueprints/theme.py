"""The colour theme: System, Light or Dark (rework decision S25).

The choice is a cookie for now. An account column would follow the person from device to device,
but it needs a schema change, which belongs to the workspace work; a cookie needs none and is read
on the same request that renders the page, so ``<html>`` carries ``data-theme`` before the first
paint and the page never flashes the wrong theme. "System" is the absence of a choice: no cookie,
no attribute, and the stylesheet follows ``prefers-color-scheme``.

Setting it is an ordinary CSRF-protected form post (the app enables CSRF globally) that sends the
reader back where they were, to a path on this site only.
"""

from __future__ import annotations

from flask import Blueprint, abort, redirect, request, url_for

bp = Blueprint("theme", __name__)

COOKIE = "qv_theme"
#: What the form may send. "system" clears the cookie rather than storing a third value.
CHOICES = ("system", "light", "dark")
#: What the cookie may hold; anything else is ignored as if there were no cookie.
STORED = ("light", "dark")
ONE_YEAR = 365 * 24 * 60 * 60


def current_theme() -> str | None:
    """``"light"`` or ``"dark"`` when the reader chose one, ``None`` for System."""
    value = request.cookies.get(COOKIE)
    return value if value in STORED else None


def same_site_path(target: str | None) -> str | None:
    """``target`` if it is a path on this site, else ``None``.

    A browser drops tabs and newlines from a URL before parsing it and reads a backslash as a
    slash, so a path of slash, tab, slash or of slash, backslash becomes ``//evil.example``: another
    site. Only a printable path that starts with exactly one ``/`` is let through.
    """
    if not target or not target.startswith("/") or target.startswith("//"):
        return None
    if "\\" in target or any(ord(c) < 0x21 or ord(c) == 0x7F for c in target):
        return None
    return target


@bp.post("/theme")
def set_theme():
    choice = request.form.get("theme", "")
    if choice not in CHOICES:
        abort(400)
    response = redirect(same_site_path(request.form.get("next")) or url_for("core.index"), 303)
    if choice == "system":
        response.delete_cookie(COOKIE, path="/", samesite="Lax", httponly=True)
    else:
        response.set_cookie(
            COOKIE,
            choice,
            max_age=ONE_YEAR,
            path="/",
            samesite="Lax",
            httponly=True,
            secure=request.is_secure,
        )
    return response


@bp.app_context_processor
def _inject_theme():
    """Every page, signed in or out, renders ``<html>`` with the reader's theme."""
    return {"theme": current_theme(), "theme_choices": CHOICES}
