"""Error pages for the HTML surface (rework R1): what went wrong, in plain words, and what next.

/api/ keeps its JSON errors (see ``create_app``); this module is only reached for everything else.
Signed in, the page is drawn inside the shell, so the navigation is still there to leave by;
signed out, it has the public header.
"""

from __future__ import annotations

from urllib.parse import urlsplit

#: Title and one plain sentence per status. The sentence says what the reader can do about it.
PAGES: dict[int, tuple[str, str]] = {
    400: (
        "That request could not be read",
        "Something in it was missing or malformed, so nothing was changed. Go back and try again.",
    ),
    403: (
        "You don't have access to this page",
        "It belongs to a vault or a setting you are not part of. Ask the vault's owner or an "
        "administrator if you need it.",
    ),
    404: (
        "Page not found",
        "The link may be out of date, or the page may have moved or been removed.",
    ),
    405: (
        "That action isn't available here",
        "This address doesn't accept that kind of request, so nothing was changed. Go back and use "
        "the page's own buttons.",
    ),
    413: (
        "That file is too large",
        "Nothing was uploaded. Files can be up to {limit}.",
    ),
    500: (
        "Something went wrong on our side",
        "The error has been logged. Try again in a moment, and if it keeps happening, tell your "
        "administrator.",
    ),
}

CSRF_PAGE = (
    "This form has expired",
    "The page was open too long, or you signed in or out in another tab, so the form was not "
    "sent and nothing was changed. Reload the page and try again.",
)

GENERIC = ("Something went wrong", "The request could not be completed. Go back and try again.")


def _limit(app) -> str:
    size = app.config.get("MAX_CONTENT_LENGTH") or 0
    if size >= 1024 * 1024:
        return f"{size // (1024 * 1024)} MB"
    return f"{max(size // 1024, 1)} KB"


def _back_path(request) -> str | None:
    """The page the reader came from, if it was on this site and is not this page."""
    from .blueprints.theme import same_site_path

    referrer = request.referrer
    if not referrer:
        return None
    parts = urlsplit(referrer)
    if parts.netloc != request.host:
        return None
    path = parts.path + (f"?{parts.query}" if parts.query else "")
    if parts.path == request.path:
        return None
    return same_site_path(path)


def page_for(exc) -> tuple[str, str]:
    from flask import current_app
    from flask_wtf.csrf import CSRFError

    if isinstance(exc, CSRFError):
        return CSRF_PAGE
    title, text = PAGES.get(exc.code, GENERIC)
    return title, text.format(limit=_limit(current_app))


def render_error_page(exc):
    """The response for an HTTP error outside /api/, or ``exc`` when there is no page to draw."""
    from flask import current_app, make_response, render_template, request

    code = getattr(exc, "code", None)
    if code is None or code < 400 or getattr(exc, "response", None) is not None:
        return exc

    if code >= 500:
        # A failed request can leave the session mid-transaction; the shell queries the database
        # (the Approvals count), so start clean before drawing it.
        from .extensions import db

        try:
            db.session.rollback()
        except Exception:  # noqa: BLE001 - the page must still be attempted
            pass

    title, text = page_for(exc)
    try:
        body = render_template(
            "errors.html",
            code=code,
            error_title=title,
            error_text=text,
            back_path=_back_path(request),
        )
    except Exception:  # noqa: BLE001 - an error page that fails must not hide the original error
        current_app.logger.exception("the %s page could not be drawn", code)
        return exc

    response = make_response(body, code)
    # Keep what the exception says about itself, such as the Allow header on a 405.
    for name, value in exc.get_headers():
        if name.lower() != "content-type":
            response.headers[name] = value
    return response
