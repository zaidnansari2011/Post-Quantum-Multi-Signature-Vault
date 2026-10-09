"""Accessibility guard (rework S24): every page the fixtures can reach, checked as rendered.

A cheap structural check, not a substitute for a screen reader (docs/OWNER-ACTIONS.md has the
human run): it reads each page's HTML and reports what a parser can see for certain. The language
attribute and the title; one main landmark, and a name on each navigation landmark when there are
several; exactly one h1, and no heading that skips a level on the way down; a name on every input,
select, textarea, button, link and menu trigger; alt on every image; a hidden or named SVG; no
repeated id, and no reference (label for, aria-labelledby, aria-describedby, aria-controls) to an
id that is not there; nothing focusable inside aria-hidden; tables with a caption and scoped
headers; link text that says where it goes ("here" does not); and no description that only repeats
the name it describes (a caption inside its own label is read twice).

The names are computed the way a browser would for these cases (aria-labelledby, aria-label, a
label, a fieldset's legend, the text, an image's alt, the title), skipping anything aria-hidden or
hidden. Visually hidden text counts: a screen reader reads it.

Pages are drawn as an administrator, as a member and as an auditor, signed out, and in the states
a refused form comes back in (each with its field marked invalid), and as every error page.

The decision page, New decision and the vault page are another stream's (R5) while this one runs.
Their problems are not fixed here; they are listed in R5_KNOWN below, so the guard still reports
them and the list says what is left to fix at integration. The comparison is exact, so an entry
that R5 fixes fails the test until it is removed: the list cannot go stale.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

import pytest

from qvault.services import (
    approval_service,
    auth_service,
    checkpoint_service,
    export_service,
    proposal_service,
    publication_service,
    vault_service,
    workspace_service,
)

PW = "password-123"

VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source",
    "track", "wbr",
}  # fmt: skip
#: Link text that says nothing on its own (WCAG 2.4.4): a screen reader's list of links reads it
#: with no sentence around it.
VAGUE_LINKS = {
    "here", "click here", "more", "read more", "learn more", "link", "this", "this page", "go",
    "open", "view", "change", "edit", "details",
}  # fmt: skip

# ------------------------------------------------------------------------------ the R5 screens

#: Problems on the screens R5 owns (vaults/detail.html, vaults/proposal_new.html,
#: vaults/proposal_detail.html), reported but not fixed by this stream. Each entry is
#: (page, problem). Fix the template at integration, then delete its line here.
R5_KNOWN: set[tuple[str, str]] = {
    # detail.html, Treasury tab, "Your key: ... — change": name it "Change your key" (or link
    # the whole phrase).
    ("vault treasury", 'link text "change" does not say where it goes: <a href="/account/">'),
}


# ------------------------------------------------------------------------------ the parser


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = attrs
        self.children: list = []
        self.parent = parent

    def get(self, name, default=None):
        return self.attrs.get(name, default)

    def walk(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.walk()

    def ancestors(self):
        node = self.parent
        while node is not None:
            yield node
            node = node.parent


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {}, None)
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: (v if v is not None else "") for k, v in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = Node(tag, {k: (v if v is not None else "") for k, v in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def parse(html: str) -> Node:
    tree = _Tree()
    tree.feed(html)
    tree.close()
    return tree.root


def _hidden(node: Node) -> bool:
    # The hidden attribute takes an element out of the accessibility tree exactly as
    # aria-hidden does (display: none), so neither gives a name its words.
    return (
        node.get("aria-hidden") == "true"
        or "hidden" in node.attrs
        or node.tag in ("script", "style", "template")
    )


def text_of(node: Node, by_id: dict) -> str:
    """The text a screen reader would take from this subtree for a name."""
    parts = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
        elif not _hidden(child):
            if child.tag == "img":
                parts.append(child.get("alt") or "")
            elif child.tag == "svg" and child.get("role") == "img":
                parts.append(child.get("aria-label") or "")
            elif child.tag == "input" and child.get("type") in ("submit", "button", "reset"):
                parts.append(child.get("value") or "")
            elif child.tag in ("input", "select", "textarea"):
                continue
            else:
                parts.append(text_of(child, by_id))
    return " ".join(" ".join(parts).split())


def name_of(node: Node, by_id: dict, label_for: dict) -> str:
    """The accessible name, for the cases these templates use."""
    if node.get("aria-labelledby"):
        return " ".join(
            text_of(by_id[i], by_id) for i in node.get("aria-labelledby").split() if i in by_id
        ).strip()
    if (node.get("aria-label") or "").strip():
        return node.get("aria-label").strip()
    if node.tag in ("input", "select", "textarea"):
        if node.get("type") in ("submit", "button", "reset"):
            return (node.get("value") or "").strip()
        labels = [text_of(lab, by_id) for lab in label_for.get(node.get("id"), [])]
        labels += [text_of(a, by_id) for a in node.ancestors() if a.tag == "label"]
        name = " ".join(x for x in labels if x).strip()
        return name or (node.get("title") or "").strip()
    if node.tag == "img":
        return (node.get("alt") or "").strip()
    if node.tag == "fieldset":
        legend = next((c for c in node.children if isinstance(c, Node) and c.tag == "legend"), None)
        return text_of(legend, by_id) if legend is not None else ""
    return text_of(node, by_id) or (node.get("title") or "").strip()


def _describe(node: Node) -> str:
    """A stable description of an element: its tag and the attributes that identify it."""
    bits = [node.tag]
    for key in ("type", "name", "class", "href"):
        value = node.get(key)
        if value:
            if key == "href":
                value = re.sub(r"https?://[^/]+", "", value)
                value = re.sub(r"[0-9a-f]{8}-[0-9a-f-]{27}", "<uuid>", value)
                value = re.sub(r"/\d+(?=[/?]|$)", "/<id>", value)
            bits.append(f'{key}="{value[:40]}"')
    return "<" + " ".join(bits) + ">"


def _focusable(node: Node) -> bool:
    if node.get("tabindex") is not None:
        return node.get("tabindex") != "-1"
    if node.tag == "a":
        return node.get("href") is not None
    if node.tag == "input":
        return node.get("type") != "hidden" and "disabled" not in node.attrs
    if node.tag in ("button", "select", "textarea"):
        return "disabled" not in node.attrs
    return node.tag == "summary"


def problems(html: str) -> list[str]:
    root = parse(html)
    nodes = list(root.walk())
    found: list[str] = []

    ids: dict[str, Node] = {}
    for node in nodes:
        i = node.get("id")
        if i is None:
            continue
        if i in ids:
            found.append(f'duplicate id "{i}"')
        ids.setdefault(i, node)
    label_for: dict[str, list[Node]] = {}
    for node in nodes:
        if node.tag == "label" and node.get("for"):
            label_for.setdefault(node.get("for"), []).append(node)

    # The document: language, title, one main.
    html_el = next((n for n in nodes if n.tag == "html"), None)
    if html_el is None or not (html_el.get("lang") or "").strip():
        found.append("no lang on <html>")
    title = next((n for n in nodes if n.tag == "title"), None)
    if title is None or not text_of(title, ids):
        found.append("no <title>")
    mains = [n for n in nodes if n.tag == "main" or n.get("role") == "main"]
    if len(mains) != 1:
        found.append(f"{len(mains)} main landmarks")
    navs = [n for n in nodes if n.tag == "nav" or n.get("role") == "navigation"]
    if len(navs) > 1:
        for nav in navs:
            if not (nav.get("aria-label") or nav.get("aria-labelledby")):
                found.append(f"unnamed navigation landmark {_describe(nav)}")
        names = [name_of(n, ids, label_for) if n.get("aria-labelledby") else n.get("aria-label")
                 for n in navs]  # fmt: skip
        for repeated in sorted({n for n in names if n and names.count(n) > 1}):
            found.append(f'two navigation landmarks named "{repeated}"')

    # Headings: one h1, and none skipping a level on the way down.
    levels = []
    for node in nodes:
        if re.fullmatch(r"h[1-6]", node.tag):
            levels.append((int(node.tag[1]), text_of(node, ids)))
        elif node.get("role") == "heading":
            levels.append((int(node.get("aria-level") or 2), text_of(node, ids)))
    h1s = [t for level, t in levels if level == 1]
    if len(h1s) != 1:
        found.append(f"{len(h1s)} h1 headings")
    previous = 0
    for level, text in levels:
        if level > previous + 1:
            found.append(f'heading skips from h{previous} to h{level}: "{text[:40]}"')
        if not text:
            found.append(f"empty h{level}")
        previous = level

    # References to ids that are not there.
    for node in nodes:
        for attr in ("aria-labelledby", "aria-describedby", "aria-controls"):
            for ref in (node.get(attr) or "").split():
                if ref not in ids:
                    found.append(f'{attr}="{ref}" on {_describe(node)} names no element')
    for target in label_for:
        if target not in ids:
            found.append(f'<label for="{target}"> names no element')

    for node in nodes:
        tag = node.tag
        # Controls, buttons, links and menu triggers need a name.
        if tag in ("input", "select", "textarea") and node.get("type") != "hidden":
            if not name_of(node, ids, label_for):
                found.append(f"no accessible name: {_describe(node)}")
        elif tag in ("button", "summary") or (tag == "a" and node.get("href") is not None):
            name = name_of(node, ids, label_for)
            if not name:
                found.append(f"no accessible name: {_describe(node)}")
            elif tag == "a" and name.lower().strip(" .") in VAGUE_LINKS:
                found.append(f'link text "{name}" does not say where it goes: {_describe(node)}')
        # Images.
        elif tag == "img" and "alt" not in node.attrs:
            found.append(f"image without alt: {_describe(node)}")
        elif tag == "svg" and node.get("aria-hidden") != "true":
            if not (node.get("role") == "img" and (node.get("aria-label") or "").strip()):
                if not any(a.get("aria-hidden") == "true" for a in node.ancestors()):
                    found.append(f"svg neither hidden nor named: {_describe(node)}")
        # Tables: a caption and scoped headers.
        elif tag == "table" and node.get("role") not in ("presentation", "none"):
            cells = list(node.walk())
            if not any(c.tag == "caption" for c in cells) and not (
                node.get("aria-label") or node.get("aria-labelledby")
            ):
                found.append(f"table without a caption: {_describe(node)}")
            heads = [c for c in cells if c.tag == "th"]
            if not heads:
                found.append(f"table without header cells: {_describe(node)}")
            for th in heads:
                if th.get("scope") not in ("col", "row", "colgroup", "rowgroup"):
                    found.append(f'th without scope: "{text_of(th, ids)[:30]}"')
            # A cell outside a row is a broken table (a mangled <thead> reads as a <th>): a screen
            # reader's table navigation then lands on the wrong headers.
            for cell in cells:
                if cell.tag in ("th", "td") and cell.parent.tag != "tr":
                    found.append(f"{cell.tag} outside a row: {_describe(cell)}")
        # A description that repeats the name: read once as the name and again after it.
        if tag in ("input", "select", "textarea", "button", "a", "fieldset"):
            name = name_of(node, ids, label_for)
            for ref in (node.get("aria-describedby") or "").split():
                said = text_of(ids[ref], ids) if ref in ids else ""
                if said and name and said in name:
                    found.append(
                        f'description repeated in the name: "{said[:40]}" on {_describe(node)}'
                    )
        # Nothing focusable where a screen reader is told there is nothing.
        if node.get("aria-hidden") == "true":
            for inner in [node, *node.walk()]:
                if _focusable(inner):
                    found.append(f"focusable inside aria-hidden: {_describe(inner)}")
    return found


# ------------------------------------------------------------------------------ the pages


def _register(email, name):
    return auth_service.register_user(email, name, PW)


def _login(client, email):
    r = client.post("/login", data={"email": email, "password": PW})
    assert r.status_code == 302, "sign-in failed"


@pytest.fixture()
def world(app):
    """A workspace with enough in it to draw every screen in each of its common states: an
    administrator (Ada) and a signer (Cleo) in a 2-of-2 vault with an open, an approved (and
    shared) and a rejected decision, a checkpointed log, notifications, and an invitation."""
    app.config["ONCHAIN_EXECUTION_ENABLED"] = True
    ada = _register("ada@e.com", "Ada Lovelace")
    cleo = _register("cleo@e.com", "Cleo Ng")
    vault = vault_service.create_vault(ada, "Treasury", "Payments", 2)
    vault_service.add_member(vault, cleo.email, "signer", actor_id=ada.id)
    open_ = proposal_service.create_proposal(vault, ada, "Renew the lease", "Renew for 2 years.")
    approved = proposal_service.create_proposal(vault, ada, "Wire to escrow", "Wire 250 EUR.")
    rejected = proposal_service.create_proposal(vault, cleo, "Buy a boat", "One boat.")
    for signer in (ada, cleo):
        approval_service.cast_vote(approved, signer, PW, "approve")
    approval_service.cast_vote(rejected, ada, PW, "reject", reason="Not needed.")
    publication_service.publish(approved, ada)
    checkpoint_service.maybe_checkpoint()
    workspace = workspace_service.current_workspace(ada)
    _, token = workspace_service.create_invitation(workspace, ada, "sam@e.com", "member", ())
    # Cleo registered second, so she is a Member of the workspace; Ida is made its Auditor.
    ida = _register("ida@e.com", "Ida Bauer")
    workspace_service.change_role(workspace, ida.id, "auditor", actor=ada)
    return {
        "ada": ada,
        "vault": vault,
        "open": open_,
        "approved": approved,
        "rejected": rejected,
        "cleo": cleo,
        "token": token,
    }


def _decision(p) -> str:
    return f"/vaults/{p.vault_id}/proposals/{p.proposal_uuid}"


def _docs(client) -> list[str]:
    index = client.get("/docs/").get_data(as_text=True)
    return sorted(set(re.findall(r'href="(/docs/[a-z-]+)"', index)))


def signed_out_pages(client, w) -> dict[str, tuple[str, int]]:
    pages = {
        "landing": "/",
        "sign in": "/login",
        "register": "/register",
        "verify": "/verify/",
        "not found": "/no-such-page",
        "docs": "/docs/",
        "invitation, unknown": "/invite/not-a-real-invitation",
        "invitation, sign up": f"/invite/{w['token']}",
        "public record": f"/d/{w['approved'].proposal_uuid}",
    }
    for path in _docs(client):
        pages[f"docs {path.rsplit('/', 1)[1]}"] = path
    return pages


def signed_in_pages(client, w) -> dict[str, str]:
    vid = w["vault"].id
    pages = {
        "home": "/",
        "approvals": "/approvals/",
        "approvals, filtered empty": "/approvals/?q=nothing-matches-this",
        "vaults": "/vaults/",
        "new vault": "/vaults/new",
        "audit": "/ledger/",
        "transparency": "/ledger/transparency",
        "verify": "/verify/",
        "security, algorithms": "/admin/crypto",
        "security, performance": "/admin/benchmark",
        "security, keys": "/admin/rotation",
        "adversary lab": "/admin/attack",
        "chain": "/admin/chain",
        "account": "/account/",
        "account security": "/account/security",
        "notification preferences": "/account/notifications",
        "notifications": "/notifications/",
        "docs": "/docs/",
        "trace": "/trace/",
        "members": "/workspace/members",
        "invite": "/workspace/invite",
        "workspace settings": "/workspace/settings",
        "remove member": f"/workspace/members/{w['cleo'].id}/remove",
        "invitation, wrong account": f"/invite/{w['token']}",
        "not found": "/no-such-page",
        # R5's screens: checked, and their problems listed in R5_KNOWN.
        "vault": f"/vaults/{vid}",
        "vault members": f"/vaults/{vid}?tab=members",
        "vault files": f"/vaults/{vid}?tab=files",
        "vault treasury": f"/vaults/{vid}?tab=treasury",
        "vault settings": f"/vaults/{vid}?tab=settings",
        "new decision": f"/vaults/{vid}/proposals/new",
        "decision, open": _decision(w["open"]),
        "decision, approved": _decision(w["approved"]),
        "decision, rejected": _decision(w["rejected"]),
    }
    for path in _docs(client):
        pages[f"docs {path.rsplit('/', 1)[1]}"] = path
    return pages


def _render(client, pages: dict[str, str]) -> dict[str, str]:
    out = {}
    for key, path in pages.items():
        r = client.get(path)
        assert r.status_code in (200, 404), f"{key}: {path} answered {r.status_code}"
        if key == "not found" or key.startswith("invitation, unknown"):
            assert r.status_code == 404, key
        else:
            assert r.status_code == 200, f"{key}: {path} answered {r.status_code}"
        out[key] = r.get_data(as_text=True)
    return out


def _posted(client, w) -> dict[str, str]:
    """The pages drawn in answer to a form: an invitation's link, and Verify's two results."""
    bundle = export_service.bundle_bytes(
        export_service.build_decision_bundle(w["approved"], sync_witness=False)
    ).decode("utf-8")
    sent = {
        "invitation link": client.post(
            "/workspace/invite", data={"email": "tom@e.com", "role": "member"}
        ),
        "verify, a result": client.post("/verify/", data={"bundle_text": bundle}),
        "verify, unreadable": client.post("/verify/", data={"bundle_text": "not a bundle"}),
    }
    for key, r in sent.items():
        assert r.status_code in (200, 400), f"{key} answered {r.status_code}"
    return {key: r.get_data(as_text=True) for key, r in sent.items()}


def _refused_signed_out(client) -> dict[str, str]:
    """The signed-out forms, sent back refused."""
    sent = {
        "sign in, refused": client.post(
            "/login", data={"email": "ada@e.com", "password": "not-the-password"}
        ),
        "sign in, unreadable": client.post("/login", data={"email": "ada", "password": ""}),
        "register, refused": client.post(
            "/register",
            data={"display_name": "", "email": "ada", "password": "short", "confirm": "other"},
        ),
        "register, taken": client.post(
            "/register",
            data={"display_name": "Ada", "email": "ada@e.com", "password": PW, "confirm": PW},
        ),
    }
    for key, r in sent.items():
        assert r.status_code in (200, 400), f"{key} answered {r.status_code}"
    return {key: r.get_data(as_text=True) for key, r in sent.items()}


def _refused_signed_in(client) -> dict[str, str]:
    """The administrator's forms, sent back refused, and a filter holding a day that is not one."""
    sent = {
        "new vault, refused": client.post("/vaults/new", data={"name": "", "threshold_m": "0"}),
        "invite, refused": client.post("/workspace/invite", data={"email": "x", "role": "member"}),
        "invite, already a member": client.post(
            "/workspace/invite", data={"email": "cleo@e.com", "role": "member"}
        ),
        "workspace settings, refused": client.post(
            "/workspace/settings/general", data={"name": "  "}
        ),
        "audit, a day that does not exist": client.get("/ledger/?from=2026-13-40"),
    }
    for key, r in sent.items():
        assert r.status_code in (200, 400), f"{key} answered {r.status_code}"
    return {key: r.get_data(as_text=True) for key, r in sent.items()}


def _error_pages(app, client, user=None) -> dict[str, str]:
    """Every error page the HTML surface draws: 403 (as a member), 404 elsewhere, and these."""
    from flask_login import login_user
    from flask_wtf.csrf import CSRFError
    from werkzeug.exceptions import InternalServerError

    from qvault.errors import render_error_page

    pages = {"error 405": client.get("/workspace/settings/general")}
    limit = app.config["MAX_CONTENT_LENGTH"]
    app.config["MAX_CONTENT_LENGTH"] = 1024
    pages["error 413"] = client.post("/verify/", data={"bundle_text": "x" * 4096})
    app.config["MAX_CONTENT_LENGTH"] = limit
    app.config["WTF_CSRF_ENABLED"] = True
    pages["error, form expired"] = client.post("/login", data={"email": "ada@e.com"})
    app.config["WTF_CSRF_ENABLED"] = False
    out = {}
    for key, r in pages.items():
        expected = {"error 405": 405, "error 413": 413, "error, form expired": 400}[key]
        assert r.status_code == expected, f"{key} answered {r.status_code}"
        out[key] = r.get_data(as_text=True)
    # A 500 and the CSRF page drawn directly: nothing in the app fails on purpose.
    for key, exc in (("error 500", InternalServerError()), ("error, csrf", CSRFError())):
        with app.test_request_context("/"):
            if user is not None:
                login_user(user)
            out[key] = render_error_page(exc).get_data(as_text=True)
    return out


def _marked(rendered: dict[str, str], *, banner_only=()) -> list[str]:
    """Each refused form says what is wrong where it is wrong: a field marked aria-invalid (tied
    to its message by aria-describedby, and focused by qvault.js). A refusal that must not say
    which field (wrong credentials) is an alert banner instead."""
    missing = []
    for key, html in rendered.items():
        if key in banner_only:
            if 'role="alert"' not in html:
                missing.append(f"{key}: no alert")
        elif 'aria-invalid="true"' not in html:
            missing.append(f"{key}: no field marked invalid")
    return missing


def _report(rendered: dict[str, str]) -> set[tuple[str, str]]:
    return {(key, p) for key, html in rendered.items() for p in problems(html)}


# ------------------------------------------------------------------------------ the guard


def test_every_signed_out_page_passes_the_structural_checks(app, client, world):
    rendered = _render(client, signed_out_pages(client, world))
    refused = _refused_signed_out(client)
    rendered.update(refused)
    rendered.update(_error_pages(app, client))
    assert sorted(_report(rendered)) == []
    assert _marked(refused, banner_only=("sign in, refused",)) == []


def test_every_signed_in_page_passes_the_structural_checks_but_r5s_known_ones(app, client, world):
    _login(client, "ada@e.com")
    rendered = _render(client, signed_in_pages(client, world))
    rendered.update(_posted(client, world))
    refused = _refused_signed_in(client)
    rendered.update(refused)
    rendered.update(_error_pages(app, client, world["ada"]))
    found = _report(rendered)
    assert sorted(found - R5_KNOWN) == [], "new problems"
    assert sorted(R5_KNOWN - found) == [], "fixed: delete these from R5_KNOWN"
    assert _marked(refused) == []


@pytest.mark.parametrize("email", ["cleo@e.com", "ida@e.com"], ids=["member", "auditor"])
def test_a_member_and_an_auditor_see_pages_that_pass_too(app, client, world, email):
    """The same screens drawn for someone who is not an administrator: other branches of the
    templates (read-only settings, no invite button, Security refused with a 403)."""
    _login(client, email)
    rendered = {}
    for key, path in signed_in_pages(client, world).items():
        r = client.get(path)
        assert r.status_code in (200, 403, 404), f"{key}: {path} answered {r.status_code}"
        rendered[key] = r.get_data(as_text=True)
    assert "have access to this page" in rendered["security, algorithms"]
    assert sorted(_report(rendered) - R5_KNOWN) == []


def test_signed_in_page_titles_are_unique_and_name_the_screen(app, client, world):
    """A title is what a screen reader says first and what a tab or a history entry shows. The
    tabs of one screen may share it; two different screens may not."""
    _login(client, "ada@e.com")
    rendered = _render(client, signed_in_pages(client, world))
    titles: dict[str, list[str]] = {}
    for key, html in rendered.items():
        title = " ".join(re.search(r"<title>(.*?)</title>", html, re.S).group(1).split())
        assert title != "Q-Vault" and title.endswith("Q-Vault"), f"{key}: {title}"
        screen = key.split(",")[0].split(" ")[0] if key.startswith("vault") else key
        titles.setdefault(title, []).append(screen.split(",")[0])
    shared = {t: keys for t, keys in titles.items() if len(set(keys)) > 1}
    assert shared == {}


# ------------------------------------------------------------------------------ the guard itself


@pytest.mark.parametrize(
    "html, expected",
    [
        ("<html><body><main><h1>A</h1><h3>B</h3></main>", "heading skips from h1 to h3"),
        ("<html lang=en><main><h1>A</h1><h1>B</h1></main>", "2 h1 headings"),
        ("<html><main><h1>A</h1></main>", "no lang on <html>"),
        ('<html lang=en><main><h1>A</h1><input name="q"></main>', "no accessible name"),
        ('<html lang=en><main><h1>A</h1><img src="x.png"></main>', "image without alt"),
        ('<html lang=en><main><h1>A</h1><p id="x"></p><p id="x"></p></main>', "duplicate id"),
        ("<html lang=en><main><h1>A</h1><button><svg aria-hidden=true></svg></button></main>",
         "no accessible name: <button>"),  # fmt: skip
        ('<html lang=en><main><h1>A</h1><a href="/x">here</a></main>', "does not say where"),
        ('<html lang=en><main><h1>A</h1><div aria-hidden="true"><a href="/">Home</a></div></main>',
         "focusable inside aria-hidden"),  # fmt: skip
        ("<html lang=en><main><h1>A</h1><table><tr><td>1</td></tr></table></main>",
         "table without header cells"),  # fmt: skip
        ('<html lang=en><main><h1>A</h1><table><caption>T</caption><th scope="col"ead><tr>'
         '<th scope="col">A</th></tr></table></main>', "th outside a row"),  # fmt: skip
        (
            '<html lang=en><main><h1>A</h1><input aria-describedby="gone"></main>',
            "names no element",
        ),
        # A caption inside its own label: the name already says it, the description repeats it.
        ('<html lang=en><main><h1>A</h1><input type="checkbox" id="c" aria-describedby="c-cap">'
         '<label for="c">Agree<span id="c-cap">It cannot be undone.</span></label></main>',
         "description repeated in the name"),  # fmt: skip
        # A hidden element gives no name, exactly like an aria-hidden one.
        ("<html lang=en><main><h1>A</h1><button><span hidden>Close</span></button></main>",
         "no accessible name: <button>"),  # fmt: skip
    ],
)
def test_the_guard_catches_each_kind_of_problem(html, expected):
    assert any(expected in p for p in problems(html)), problems(html)


def test_the_guard_accepts_a_well_formed_page():
    html = (
        '<html lang="en"><head><title>Members — Q-Vault</title></head><body>'
        '<nav aria-label="Main"><a href="/">Home</a></nav><main><h1>Members</h1>'
        '<label for="f-q">Search</label><input id="f-q" name="q">'
        '<button aria-label="Close"><svg aria-hidden="true"></svg></button>'
        '<table><caption>People</caption><thead><tr><th scope="col">Name</th></tr></thead>'
        "<tbody><tr><td>Ada</td></tr></tbody></table>"
        '<h2>More</h2><img src="a.png" alt=""></main></body></html>'
    )
    assert problems(html) == []
