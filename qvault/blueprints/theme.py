"""The colour theme: System, Light or Dark (rework decision S25).

S25 asks for the choice to be stored per user. A choice made signed in is stored on the person
(``user_settings``, revision 0004), so it follows them to every browser, and in a cookie, so this
browser keeps it after they sign out; signed out, or before they have ever chosen, the cookie
decides. Both are read on the same request that renders the page, so ``<html>`` carries
``data-theme`` before the first paint and the page never flashes the wrong theme. "System" draws no
attribute, and the stylesheet follows ``prefers-color-scheme``; signed in it is stored as
``"system"``, so it overrides a cookie left by an earlier choice.

Setting it is a form post that sends the reader back where they were, to a path on this site only.
It is exempt from the app's CSRF token on purpose. The picker is on every page, signed out ones
included, and asking for a token there would start a session on every page, including the public
record, which promises to write nothing. Instead the endpoint refuses a request the browser marks
as cross-site (``Sec-Fetch-Site``, or ``Origin`` where that is all an older browser sends). The
worst a forged post could do is change someone's colours, so this is proportionate.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from flask import Blueprint, abort, current_app, redirect, request, url_for
from flask_login import current_user
from werkzeug.exceptions import HTTPException
from werkzeug.routing import RequestRedirect

from qvault.extensions import csrf, db
from qvault.models import UserSetting
from qvault.security.redirects import safe_next

bp = Blueprint("theme", __name__)

COOKIE = "qv_theme"
#: What the form may send. "system" clears the cookie rather than storing a third value.
CHOICES = ("system", "light", "dark")
#: What the cookie may hold; anything else is ignored as if there were no cookie.
STORED = ("light", "dark")
ONE_YEAR = 365 * 24 * 60 * 60


def _stored_theme(user_id: int) -> str | None:
    setting = db.session.get(UserSetting, user_id)
    return setting.theme if setting is not None else None


def current_theme() -> str | None:
    """``"light"`` or ``"dark"`` when the reader chose one, ``None`` for System.

    A signed-in person's own choice wins; without one, the cookie. An error page is drawn with this
    too, and a 500 may come from the database itself: if the person cannot be read, the cookie
    decides rather than the error page failing as well.
    """
    try:
        own = _stored_theme(current_user.id) if current_user.is_authenticated else None
    except Exception:  # noqa: BLE001 - only ever the page's colours; see the docstring
        own = None
    if own is not None:
        return own if own in STORED else None
    value = request.cookies.get(COOKIE)
    return value if value in STORED else None


def same_site_path(target: str | None) -> str | None:
    """``target`` if it is a path on this site, else ``None``: the one check every redirect to a
    handed-in address uses (``qvault.security.redirects.safe_next``), so a fix to it covers this
    one too."""
    return safe_next(target)


def is_cross_site() -> bool:
    """Whether the browser says this request was sent from another site.

    ``Sec-Fetch-Site`` is set by the browser and cannot be forged by a page, so when it is present
    it decides: only ``same-origin``, or ``none`` (typed or bookmarked), is ours. A browser too old
    to send it still sends ``Origin`` on a cross-site form post, so its host must be this host.
    With neither there is nothing to judge by (a very old browser, or a tool such as curl), so the
    request is allowed rather than locking those readers out of the choice.
    """
    site = request.headers.get("Sec-Fetch-Site")
    if site is not None:
        return site not in ("same-origin", "none")
    origin = request.headers.get("Origin")
    if origin is not None:
        # "null" (a sandboxed frame, a file) has no host, so it never matches.
        return urlsplit(origin).netloc.lower() != request.host.lower()
    return False


def _answers_get(path: str) -> bool:
    """Whether a GET of ``path`` reaches a page here, rather than a 404 or a 405."""
    adapter = current_app.url_map.bind(request.host)
    try:
        adapter.match(urlsplit(path).path, method="GET")
    except RequestRedirect:
        return True  # a trailing-slash redirect still lands on the page
    except HTTPException:
        return False
    return True


def _return_path() -> str:
    """Where to send the reader once the choice is stored.

    The form names the page as ``next`` only when that page was a GET; a page drawn in answer to a
    POST (a benchmark result) cannot be fetched again, and returning to its URL would be a 405. So
    with no ``next``, the referring page on this site is used if a GET of it works, else Home.
    """
    target = same_site_path(request.form.get("next"))
    if target:
        return target
    referrer = request.referrer
    if referrer:
        parts = urlsplit(referrer)
        if parts.netloc.lower() == request.host.lower():
            path = same_site_path(parts.path + (f"?{parts.query}" if parts.query else ""))
            if path and _answers_get(path):
                return path
    return url_for("core.index")


@bp.post("/theme")
@csrf.exempt  # see the module docstring: refused cross-site instead, so no session is needed
def set_theme():
    if is_cross_site():
        abort(403)
    choice = request.form.get("theme", "")
    if choice not in CHOICES:
        abort(400)
    if current_user.is_authenticated:
        setting = db.session.get(UserSetting, current_user.id)
        if setting is None:
            setting = UserSetting(user_id=current_user.id)
            db.session.add(setting)
        setting.theme = choice
        db.session.commit()
    response = redirect(_return_path(), 303)
    # Behind a proxy that ends TLS (the Azure deployment), request.is_secure is False even though
    # the reader is on HTTPS, so the cookie follows the session cookie's switch as well.
    secure = request.is_secure or bool(current_app.config.get("SESSION_COOKIE_SECURE", False))
    if choice == "system":
        response.delete_cookie(COOKIE, path="/", samesite="Lax", httponly=True, secure=secure)
    else:
        response.set_cookie(
            COOKIE,
            choice,
            max_age=ONE_YEAR,
            path="/",
            samesite="Lax",
            httponly=True,
            secure=secure,
        )
    return response


@bp.app_context_processor
def _inject_theme():
    """Every page, signed in or out, renders ``<html>`` with the reader's theme."""
    return {"theme": current_theme(), "theme_choices": CHOICES}
