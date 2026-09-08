"""Documentation.

Every explanatory word in this product lives here and nowhere else. The working screens describe
nothing: a tool that stops to teach you on each page reads as a tutorial rather than as software,
and the cryptographic vocabulary that a first-time reader needs is exactly the vocabulary that gets
in a daily user's way. So it is all in one place, reachable, and never in the way.

Pages are a static, ordered list rather than files on disk: there are a handful of them, they are
part of the product's voice, and rendering them as templates keeps them under the same review as
everything else.
"""

from __future__ import annotations

from flask import Blueprint, abort, current_app, render_template

bp = Blueprint("docs", __name__, url_prefix="/docs")

#: Pages that describe a surface which may not exist in this deployment. Listing one when the
#: thing it documents is switched off sends a reader to a 404 from our own table of contents, so
#: the gate is applied to the page list rather than only to the feature.
GATED = {"trace": "GLASSBOX_ENABLED"}

# (slug, title, one-line summary) in reading order.
PAGES = [
    ("approvals", "How approvals work", "Proposing a decision, signing it, and what a threshold means."),
    ("vaults", "Vaults and members", "Grouping people, setting how many must agree, and who can do what."),
    ("audit", "The audit record", "What is recorded, why it cannot be quietly edited, and how to read it."),
    ("verifying", "Verifying a decision yourself", "Exporting a decision and checking it without trusting this server."),
    ("keys", "Keys and custody", "What your signing key is, where it lives, and who can open it."),
    ("algorithms", "Post-quantum algorithms", "The three standards in use, what they cost, and why they can be swapped."),
    ("trace", "The live trace", "Watching the cryptography run, and checking its values yourself."),
]

_TITLES = {slug: title for slug, title, _ in PAGES}


def _visible_pages() -> list[tuple[str, str, str]]:
    return [p for p in PAGES if p[0] not in GATED or current_app.config.get(GATED[p[0]])]


@bp.get("/")
def index():
    return render_template("docs/index.html", pages=_visible_pages())


@bp.get("/<slug>")
def page(slug: str):
    if slug not in _TITLES:
        abort(404)
    if slug in GATED and not current_app.config.get(GATED[slug]):
        abort(404)
    return render_template(
        f"docs/{slug}.html", pages=_visible_pages(), slug=slug, title=_TITLES[slug]
    )
