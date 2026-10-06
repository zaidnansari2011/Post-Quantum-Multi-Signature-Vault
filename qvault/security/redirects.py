"""Where a ``?next=`` or a form's ``next`` may send someone: a path on this site, and nothing else.

One helper for every route that redirects to an address it was handed, so a fix to one is a fix
to all of them.
"""

from __future__ import annotations

from urllib.parse import urlsplit


def safe_next(target: str | None) -> str | None:
    """``target`` if it is a path on this site, otherwise None.

    Each refusal closes a way a browser could end up somewhere else:

    * a control character (a tab, a newline, DEL): browsers and Werkzeug drop tabs and newlines
      from a URL, so ``"/\\t/evil.com"`` arrives as the protocol-relative ``"//evil.com"``, and a
      CR or LF can also break the Location header itself;
    * a backslash: browsers read ``"\\"`` as ``"/"``, so ``"/\\evil.com"`` is ``"//evil.com"``;
    * a scheme or a host (``"https://evil.com"``, ``"//evil.com"``, ``"http:/evil"``);
    * anything that does not start with a single ``"/"``.

    Percent-encoded characters are left alone: ``"/%09/evil.com"`` stays a path on this site,
    because neither a browser nor Werkzeug decodes a Location header before following it.
    """
    if not target:
        return None
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in target) or "\\" in target:
        return None
    parts = urlsplit(target)
    if parts.scheme or parts.netloc:
        return None
    if not target.startswith("/") or target.startswith("//"):
        return None
    return target
