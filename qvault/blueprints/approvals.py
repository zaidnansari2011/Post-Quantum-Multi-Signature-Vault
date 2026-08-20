"""The approvals inbox — every decision across every vault, in one place.

The product's core loop is "something needs my signature". Before this existed a user had to open
each vault in turn to discover whether it wanted anything from them, which is a filing cabinet, not
a queue. All of the querying lives in ``inbox_service``; this module only turns a request into
filters and hands the result to a template.
"""

from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from qvault.services import inbox_service
from qvault.services.inbox_service import Filters

bp = Blueprint("approvals", __name__, url_prefix="/approvals")


@bp.get("/")
@login_required
def index():
    filters = Filters.from_request(request.args)
    page = inbox_service.search(current_user, filters)

    # A filtered view that lands past its last page is a dead end — a user who narrows a list and
    # sees "nothing here" cannot tell whether the filter matched nothing or the page simply ran
    # out. Send them back to the first page of the same filter instead.
    if filters.page > 1 and not page.items and page.total:
        return redirect(url_for("approvals.index", **filters.to_query(page=1)))

    signer_vaults = inbox_service.signer_vault_ids(current_user)
    return render_template(
        "approvals/index.html",
        rows=inbox_service.decorate(page.items, current_user, signer_vaults),
        page=page,
        filters=filters,
        counts=inbox_service.counts(current_user),
        vaults=inbox_service.vaults_for_filter(current_user),
    )
