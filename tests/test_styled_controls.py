"""Styled controls (rework R1, research 05 section 3): no screen draws a bare native control.

Every date, file, select, number, radio and checkbox the inventory listed is now one of the design
system's controls (ui/forms.html). What a screen relies on, checked here on the rendered pages:
each control carries its styled class, has a label a screen reader can find, and posts the same
name and value the route reads, so the conversion changed how it looks and nothing it sends.
"""

from __future__ import annotations

import json
import pathlib
import re
from html.parser import HTMLParser

import pytest

from qvault.blueprints.verify import MAX_BUNDLE_BYTES
from qvault.services import auth_service, vault_service, workspace_service

PW = "password-123"
ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "qvault" / "templates"

# The styled class each kind of control must carry.
STYLED = {
    "checkbox": {"q-cb", "q-sw"},
    "radio": {"q-rd"},
    "number": {"q-num__in"},
    "file": {"q-drop__in"},
    "select": {"q-select"},
}
# Native pickers the design system replaces outright (its calendar posts the same text).
NATIVE_PICKERS = {"date", "datetime-local", "month", "week", "time"}

WTFORMS_CONTROLS = {
    "form.iterations",
    "form.threshold_m",
    "threshold_form.threshold_m",
    "tamper_form.target_seq",
    "form.algorithm",
    "form.confirm_downgrade",
    "reconfigure_form.confirm",
    "form.role",
    "form.file",
    "form.deadline",
}


class _Controls(HTMLParser):
    """Collects the form controls and the labels of a page."""

    def __init__(self):
        super().__init__()
        self.controls: list[dict] = []
        self.label_for: set[str] = set()
        self.ids: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.append(a["id"])
        if tag == "label" and a.get("for"):
            self.label_for.add(a["for"])
        if tag == "select":
            self.controls.append({"kind": "select", **a})
        if tag == "input":
            kind = (a.get("type") or "text").lower()
            if kind in STYLED or kind in NATIVE_PICKERS:
                self.controls.append({"kind": kind, **a})


def _controls(html: str) -> _Controls:
    parser = _Controls()
    parser.feed(html)
    return parser


def _problems(html: str) -> list[str]:
    page = _controls(html)
    found = []
    for c in page.controls:
        name = c.get("name") or c.get("id") or "?"
        if c["kind"] in NATIVE_PICKERS:
            found.append(f"{name}: a native {c['kind']} picker")
            continue
        classes = set((c.get("class") or "").split())
        if not classes & STYLED[c["kind"]]:
            found.append(f"{name}: a bare {c['kind']}")
        labelled = c.get("id") in page.label_for or c.get("aria-label") or c.get("aria-labelledby")
        if not labelled:
            found.append(f"{name}: no label")
    return found


def _register(email, name):
    return auth_service.register_user(email, name, PW)


def _login(client, email):
    r = client.post("/login", data={"email": email, "password": PW})
    assert r.status_code == 302, "sign-in failed"


@pytest.fixture()
def team(app):
    """An administrator who owns the workspace and a vault, and a colleague whose role they can
    change: enough for every converted control to be drawn."""
    ada = _register("ada@e.com", "Ada")  # the first account is the administrator and owner
    cleo = _register("cleo@e.com", "Cleo")
    vault = vault_service.create_vault(ada, "Treasury", "", 1)
    return workspace_service.current_workspace(ada), ada, cleo, vault


CONVERTED = [
    "/account/security",
    "/account/notifications",
    "/admin/benchmark",
    "/admin/crypto",
    "/approvals/",
    "/ledger/",
    "/vaults/new",
    "/verify/",
    "/workspace/invite",
    "/workspace/members",
    "/workspace/settings",
]


@pytest.mark.parametrize("url", CONVERTED)
def test_every_control_on_a_converted_screen_is_styled_and_labelled(app, client, team, url):
    app.config["ONCHAIN_EXECUTION_ENABLED"] = True  # draws the treasury key choice
    _login(client, "ada@e.com")
    r = client.get(url)
    assert r.status_code == 200, url
    html = r.get_data(as_text=True)
    assert _controls(html).controls, f"{url} drew no controls to check"
    assert _problems(html) == []


@pytest.mark.parametrize("url", CONVERTED)
def test_no_converted_screen_repeats_an_id(app, client, team, url):
    """The macros default an id from the name ("f-role"), so a control drawn once per row must be
    given its own, or every row's label points at the first row."""
    app.config["ONCHAIN_EXECUTION_ENABLED"] = True
    _login(client, "ada@e.com")
    ids = _controls(client.get(url).get_data(as_text=True)).ids
    assert sorted({i for i in ids if ids.count(i) > 1}) == []


def test_no_template_draws_a_bare_native_control():
    """The rendered-page test sees only the states its data draws; this reads every template, so
    a control behind a condition (a flag, an empty list) is caught too."""
    tag = re.compile(r"<(input|select)\b[^>]*>", re.S)
    bare = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        rel = path.relative_to(TEMPLATES).as_posix()
        if rel.startswith("ui/"):
            continue
        source = path.read_text(encoding="utf-8")
        for m in tag.finditer(source):
            text = m.group(0)
            kind = "select" if m.group(1) == "select" else None
            t = re.search(r'type="([a-z-]+)"', text)
            if kind is None and t:
                kind = t.group(1)
            if kind in NATIVE_PICKERS:
                bare.append(f"{rel}: {text[:80]}")
            elif kind in STYLED and not set(re.findall(r"q-[a-z_-]+", text)) & STYLED[kind]:
                bare.append(f"{rel}: {text[:80]}")
        # A WTForms field called bare draws its own native control (forms.py: the Integer,
        # Select, Boolean, File and DateTime fields, by the name each template gives its form).
        for call in re.findall(r"\{\{\s*(\w*form\.\w+)\(", source):
            if call in WTFORMS_CONTROLS:
                bare.append(f"{rel}: {call}()")
    assert bare == []


# ------------------------------------------------------------------ the same values posted


def test_the_date_filters_are_text_inputs_that_post_an_iso_day(app, client, team):
    _login(client, "ada@e.com")
    html = client.get("/ledger/?from=2026-01-02&to=not-a-date").get_data(as_text=True)
    start = re.search(r'<input[^>]*id="f-from"[^>]*>', html).group(0)
    assert 'name="from"' in start and 'type="text"' in start and 'value="2026-01-02"' in start
    assert r'pattern="\d{4}-\d{2}-\d{2}"' in start
    # The route drops a value that is not a date, and the field shows it back as refused (not
    # silently emptied), so the person sees the log is not filtered by it.
    end = re.search(r'<input[^>]*id="f-to"[^>]*>', html).group(0)
    assert 'value="not-a-date"' in end and 'aria-invalid="true"' in end
    assert re.search(r'id="f-to-bad" data-due-read>Type it as 2026-10-13\.</p>', html)
    assert 'data-mode="date"' in html and "data-autosubmit" in html


def test_a_day_that_does_not_exist_is_refused_not_applied(app, client, team):
    """ "2026-13-40" fits the pattern, and compared as text it would quietly filter the log."""
    from qvault.services.audit_service import Filters

    assert Filters.from_request({"from": "2026-13-40"}).date_from == ""
    assert Filters.from_request({"to": "2026-02-30"}).date_to == ""
    _login(client, "ada@e.com")
    html = client.get("/ledger/?from=2026-13-40").get_data(as_text=True)
    start = re.search(r'<input[^>]*id="f-from"[^>]*>', html).group(0)
    assert 'value="2026-13-40"' in start and 'aria-invalid="true"' in start
    assert "entries match these filters" not in html
    # A good day is shown plainly.
    html = client.get("/ledger/?from=2026-02-28").get_data(as_text=True)
    start = re.search(r'<input[^>]*id="f-from"[^>]*>', html).group(0)
    assert 'value="2026-02-28"' in start and "aria-invalid" not in start


def test_the_verify_file_drop_knows_the_routes_limit_and_formats(app, client):
    html = client.get("/verify/").get_data(as_text=True)
    tag = re.search(r'<input[^>]*name="bundle"[^>]*>', html, re.S).group(0)
    assert 'type="file"' in tag and 'class="q-drop__in"' in tag
    assert f'data-max-bytes="{MAX_BUNDLE_BYTES}"' in tag
    assert 'accept=".html,.zip,.json' in tag
    assert 'enctype="multipart/form-data"' in html


def test_the_separation_of_duties_box_still_posts_on(app, client, team):
    workspace, *_ = team
    _login(client, "ada@e.com")
    html = client.get("/workspace/settings").get_data(as_text=True)
    assert re.search(r'name="sod_default" value="on"', html)
    client.post("/workspace/settings/vaults", data={"sod_default": "on"})
    assert workspace.sod_default is True


def test_the_downgrade_box_posts_what_the_boolean_field_reads(app, client, team):
    _login(client, "ada@e.com")
    html = client.get("/admin/crypto").get_data(as_text=True)
    assert re.search(r'id="confirm_downgrade" name="confirm_downgrade" value="y"', html)
    assert re.search(r'<select class="q-select" id="algorithm" name="algorithm"', html)
    assert re.search(r'<option value="[^"]+" selected>', html), "the active algorithm is chosen"


def test_number_inputs_keep_their_name_value_and_bounds(app, client, team):
    _login(client, "ada@e.com")
    new = client.get("/vaults/new").get_data(as_text=True)
    tag = re.search(r'<input[^>]*name="threshold_m"[^>]*>', new, re.S).group(0)
    assert 'type="number"' in tag and 'value="2"' in tag and 'min="1"' in tag
    assert 'max="50"' in tag and "required" in tag
    bench = client.get("/admin/benchmark").get_data(as_text=True)
    tag = re.search(r'<input[^>]*name="iterations"[^>]*>', bench, re.S).group(0)
    assert 'type="number"' in tag and 'value="3"' in tag and 'min="1"' in tag
    assert '<label class="visually-hidden" for="iterations">Iterations</label>' in bench


def test_the_tamper_entry_is_still_required_as_its_form_declared(app, client, team):
    """WTForms' DataRequired drew `required` on the bare field; the stepper must keep it."""
    app.config["ENABLE_TAMPER_DEMO"] = True
    _login(client, "ada@e.com")
    html = client.get("/ledger/").get_data(as_text=True)
    tag = re.search(r'<input[^>]*name="target_seq"[^>]*>', html, re.S).group(0)
    assert 'type="number"' in tag and 'min="1"' in tag and "required" in tag


def test_a_threshold_of_zero_says_what_is_wrong_not_that_it_is_missing(app, client, team):
    _login(client, "ada@e.com")
    html = client.post("/vaults/new", data={"name": "Ops", "threshold_m": "0"}).get_data(
        as_text=True
    )
    assert "Choose a number from 1 to 50." in html and "This field is required." not in html
    html = client.post("/vaults/new", data={"name": "Ops", "threshold_m": ""}).get_data(
        as_text=True
    )
    assert "Say how many approvals a decision needs." in html


def test_a_new_vault_still_posts_its_threshold(app, client, team):
    _login(client, "ada@e.com")
    r = client.post("/vaults/new", data={"name": "Payroll", "threshold_m": "1"})
    assert r.status_code == 302


def test_the_invitation_role_and_vault_choices_post_as_before(app, client, team):
    *_, vault = team
    _login(client, "ada@e.com")
    html = client.get("/workspace/invite").get_data(as_text=True)
    assert "<legend>Workspace role</legend>" in html
    assert re.search(r'class="q-rd" type="radio" id="f-role-\d" name="role" value="member"', html)
    assert f'<select class="q-select" id="vault_{vault.id}" name="vault_{vault.id}"' in html
    assert f'<label class="q-field__label" for="vault_{vault.id}">Treasury</label>' in html
    r = client.post(
        "/workspace/invite",
        data={"email": "new@e.com", "role": "member", f"vault_{vault.id}": "viewer"},
    )
    assert r.status_code in (200, 302)
    from qvault.models.workspace import Invitation

    invitation = Invitation.query.filter_by(email="new@e.com").one()
    assert invitation.role == "member"
    grants = json.loads(invitation.vault_grants)
    assert [(g["vault_id"], g["role"]) for g in grants] == [(vault.id, "viewer")]


def test_each_members_role_select_has_its_own_label(app, client, team):
    _, _, cleo, _ = team
    _login(client, "ada@e.com")
    html = client.get("/workspace/members").get_data(as_text=True)
    assert f'<label class="visually-hidden" for="role-{cleo.id}">Role for Cleo</label>' in html
    assert re.search(rf'id="role-{cleo.id}" name="role"', html)


def test_the_treasury_key_choice_is_a_radio_group_with_password_chosen(app, client, team):
    app.config["ONCHAIN_EXECUTION_ENABLED"] = True
    _login(client, "ada@e.com")
    html = client.get("/account/security").get_data(as_text=True)
    assert "<legend>The key a treasury registers for you</legend>" in html
    assert re.search(r'name="choice" value="password"\s+checked', html)


# ------------------------------------------------------------------ refusals on their fields


def test_a_refused_invitation_marks_the_field_it_is_about(app, client, team):
    _login(client, "ada@e.com")
    r = client.post("/workspace/invite", data={"email": "cleo@e.com", "role": "member"})
    html = r.get_data(as_text=True)
    assert r.status_code == 400
    tag = re.search(r'<input[^>]*id="email"[^>]*>', html).group(0)
    assert 'aria-invalid="true"' in tag and 'aria-describedby="email-cap email-err"' in tag
    assert re.search(r'id="email-err">.*?cleo@e\.com is already a member', html, re.S)
    assert 'value="cleo@e.com"' in tag


def test_a_refused_workspace_name_comes_back_on_its_field(app, client, team):
    workspace, *_ = team
    _login(client, "ada@e.com")
    r = client.post("/workspace/settings/general", data={"name": "   "})
    html = r.get_data(as_text=True)
    assert r.status_code == 400
    tag = re.search(r'<input[^>]*id="name"[^>]*>', html).group(0)
    assert 'aria-invalid="true"' in tag and "Give the workspace a name." in html
    assert workspace.name != ""


def test_an_email_already_registered_is_said_on_the_email_field(app, client, team):
    r = client.post(
        "/register",
        data={
            "display_name": "A",
            "email": "ada@e.com",
            "workspace_name": "A Co",
            "password": PW,
            "confirm": PW,
            "understood": "y",
        },
    )
    html = r.get_data(as_text=True)
    tag = re.search(r'<input[^>]*id="email"[^>]*>', html).group(0)
    assert 'aria-invalid="true"' in tag and "That email is already registered." in html
