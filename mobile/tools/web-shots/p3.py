"""Web screenshot harness ONLY: the P3 and P4 screens (phone-ux §6.1, §6.2, §6.12 to §6.18, §6.21).

Usage: python p3.py <harness origin> <out dir> <state dir> [theme] [font scale] [only,names]

Run from the repository root's `mobile/` with the venv's Python (it imports qvault.chain.digest to
make an honest treasury change). Like states.py, most states are one real record whose reply is
rewritten in the browser: only UNSIGNED fields change, so the phone's own checks still pass; the
tampered states change a signed field on purpose and must show the failure. The few records that
must exist for real (a Production access decision, a second phone of Ada's) are made through the
API on the disposable backend. Any request that is not to the harness origin is aborted.
"""

from __future__ import annotations

import copy
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from qvault.chain.digest import reconfigure_digest  # noqa: E402

BASE = sys.argv[1].rstrip("/")
OUT = Path(sys.argv[2])
STATE = Path(sys.argv[3])
THEME = sys.argv[4] if len(sys.argv) > 4 else "light"
SCALE = sys.argv[5] if len(sys.argv) > 5 else "1"
ONLY = set(sys.argv[6].split(",")) if len(sys.argv) > 6 and sys.argv[6] else None
QUERY = f"?theme={THEME}&fontScale={SCALE}"
OUT.mkdir(parents=True, exist_ok=True)
STATE.mkdir(parents=True, exist_ok=True)

W, H = 390, 844
PASSWORD = "demo-password-2026"
NOW = datetime.now(UTC)
taken: list[str] = []
audit = {"checked": 0, "findings": []}
errors: list[str] = []

TREASURY_VAULT = 1
TREASURY = "0xD49174b703d6FBC5088b0f01C6E71B5Ef467f3D0"
ADA, BRIJ, CHEN = (1, "Ada Okafor"), (2, "Brij Mehta"), (3, "Chen Wei")
GENERAL = "Payroll adjustment schedule"  # Treasury vault, 2 of 3
ACCESS_TITLE = "Temporary production read for incident 2214"

AUDIT = """() => [...document.querySelectorAll('[data-hit-w]')]
  .filter((el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; })
  .map((el) => ({
    w: Number(el.dataset.hitW), h: Number(el.dataset.hitH),
    label: el.getAttribute('aria-label') || (el.textContent || '').trim().slice(0, 40),
    nested: !!(el.parentElement && el.parentElement.closest('[data-hit-w]')),
  }))"""


def iso(delta: timedelta) -> str:
    return (NOW + delta).isoformat()


# -- plumbing (as states.py) -------------------------------------------------------------------


def new_page(browser, state=None, auth=None, init=None):
    ctx = browser.new_context(
        viewport={"width": W, "height": H},
        device_scale_factor=2,
        storage_state=str(state) if state and Path(state).exists() else None,
    )
    page = ctx.new_page()
    inflight = {"n": 0}

    def guard(route):
        if route.request.url.startswith(BASE):
            return route.fallback()
        return route.abort()

    page.route("**/*", guard)
    page.on("request", lambda r: inflight.__setitem__("n", inflight["n"] + 1) if "/api/" in r.url else None)
    for ev in ("requestfinished", "requestfailed"):
        page.on(ev, lambda r: inflight.__setitem__("n", max(0, inflight["n"] - 1)) if "/api/" in r.url else None)
    page.on("pageerror", lambda e: errors.append(str(e)[:300]) or print("PAGEERROR", str(e)[:300]))
    if auth:
        page.add_init_script(f"localStorage.setItem('webshots.auth', {json.dumps(auth)});")
    for script in init or []:
        page.add_init_script(script)
    page._inflight = inflight
    return ctx, page


def quiet(page, settle_ms=700, timeout_s=90):
    t0, since = time.time(), None
    while time.time() - t0 < timeout_s:
        if page._inflight["n"] == 0:
            since = since or time.time()
            if (time.time() - since) * 1000 >= settle_ms:
                return
        else:
            since = None
        page.wait_for_timeout(100)


def shot(page, name, wait_ms=600):
    if ONLY and name not in ONLY:
        return
    page.wait_for_timeout(wait_ms)
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path))
    taken.append(path.name)
    print("shot", path.name, flush=True)
    for target in page.evaluate(AUDIT):
        audit["checked"] += 1
        if target["w"] < 48 or target["h"] < 48 or target["nested"]:
            audit["findings"].append({"screen": name, **target})


def button(page, name):
    return page.get_by_role("button", name=re.compile("^" + re.escape(name) + r"($|\.|,)")).first


def tab(page, name):
    page.get_by_role("tab", name=re.compile("^" + re.escape(name) + "(,|$)")).first.click()
    quiet(page)


def close_sheet(page):
    page.mouse.click(W / 2, 8)
    page.wait_for_timeout(700)


def local(state_file, suffix):
    s = json.loads(Path(state_file).read_text(encoding="utf-8"))
    for origin in s["origins"]:
        for kv in origin["localStorage"]:
            if kv["name"].endswith(suffix):
                return kv["value"]
    raise SystemExit(f"no {suffix} in {state_file}")


def api(state_file, path, body=None):
    req = urllib.request.Request(
        BASE + path,
        data=None if body is None else json.dumps(body).encode(),
        method="GET" if body is None else "POST",
        headers={
            "Authorization": "Bearer " + local(state_file, "qvault.device.token.v1"),
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-QVault-Capabilities": "payment-action-1",
        },
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)


def rewrite(pattern, change):
    """A route that fetches the real reply and rewrites it with `change(body)`."""

    def handle(route):
        resp = route.fetch()
        body = resp.json()
        change(body)
        route.fulfill(response=resp, json=body)

    return (pattern, handle)


def open_app(page, link=None):
    url = BASE + "/" + QUERY + (f"&link={urllib.parse.quote(link, safe='')}" if link else "")
    page.goto(url)
    page.get_by_role("tab", name=re.compile("^Account")).or_(button(page, "More options")).first.wait_for(
        timeout=90000
    )
    quiet(page)


def run(browser, state, name, steps, routes=(), auth=None, init=None, link=None):
    """One screen or flow; one failing must not hide the others."""
    if ONLY and not any(n.startswith(name) for n in ONLY):
        return
    ctx, page = new_page(browser, state, auth=auth, init=init)
    try:
        for pattern, handler in routes:
            page.route(re.compile(pattern), handler)
        if steps is not None:
            steps(page, link)
    except Exception as exc:
        errors.append(f"{name}: {exc}")
        print("FAILED", name, exc)
    finally:
        ctx.close()


# -- onboarding (§6.2) -------------------------------------------------------------------------


def sign_in(page, email, password):
    page.get_by_placeholder("you@example.com").fill(email)
    page.get_by_placeholder("Your Q-Vault password").fill(password)
    button(page, "Continue").click()


def enrol(browser, email, state_file, shots=False):
    """Set a phone up the way a person does; the first run shoots the two steps on the way."""
    if Path(state_file).exists():
        return
    ctx, page = new_page(browser)
    page.goto(BASE + "/" + QUERY)
    page.get_by_placeholder("you@example.com").wait_for(timeout=90000)
    sign_in(page, email, PASSWORD)
    page.get_by_text("This phone gets its own key").wait_for(timeout=90000)
    quiet(page)
    if shots:
        shot(page, "o06_this_phones_key")
    button(page, "Create key on this phone").click()
    page.get_by_text("Key created").wait_for(timeout=90000)
    if shots:
        shot(page, "o07_key_created", wait_ms=100)
    page.get_by_role("tab", name=re.compile("^Account")).wait_for(timeout=90000)
    quiet(page)
    if shots:
        shot(page, "o09_first_visit_workspace_line")
    ctx.storage_state(path=str(state_file))
    ctx.close()


def onboarding(browser):
    def steps(page, _link):
        page.goto(BASE + "/" + QUERY)
        page.get_by_placeholder("you@example.com").wait_for(timeout=90000)
        shot(page, "o01_sign_in")
        button(page, "Continue").click()
        page.wait_for_timeout(400)
        shot(page, "o02_sign_in_missing")
        sign_in(page, "ada@qvault.demo", "not-the-password")
        page.get_by_text("Email or password is incorrect.").wait_for(timeout=90000)
        shot(page, "o03_sign_in_wrong_password")
        button(page, "Forgot password?").click()
        page.wait_for_timeout(900)
        shot(page, "o05_forgot_password")

    run(browser, None, "o0", steps)

    limited = (
        r".*/api/v1/devices/challenge$",
        lambda r: r.fulfill(
            status=429,
            headers={"Retry-After": "540"},
            json={"ok": False, "code": "rate_limited", "error": "Too many attempts.", "retry_after": 540},
        ),
    )

    def rate_limited(page, _link):
        page.goto(BASE + "/" + QUERY)
        page.get_by_placeholder("you@example.com").wait_for(timeout=90000)
        sign_in(page, "ada@qvault.demo", PASSWORD)
        page.get_by_text("Too many attempts").wait_for(timeout=60000)
        shot(page, "o04_sign_in_rate_limited")

    run(browser, None, "o04", rate_limited, routes=[limited])

    def no_lock(page, _link):
        page.goto(BASE + "/" + QUERY)
        page.get_by_placeholder("you@example.com").wait_for(timeout=90000)
        sign_in(page, "ada@qvault.demo", PASSWORD)
        page.get_by_text("Set a screen lock to use Q-Vault").wait_for(timeout=90000)
        shot(page, "o08_no_screen_lock")

    run(browser, None, "o08", no_lock, auth="nolock")


# -- records the shots need ----------------------------------------------------------------------


def until_utc(days: int) -> str:
    local_ = (datetime.now().astimezone() + timedelta(days=days)).replace(hour=17, minute=0, second=0, microsecond=0)
    return local_.astimezone(UTC).strftime("%Y-%m-%d %H:%M")


def access_decision(ada):
    everything = api(ada, "/api/v1/proposals?state=all")["proposals"]
    for p in everything:
        if p["title"] == ACCESS_TITLE and p["status"] == "open" and p.get("decision_type") == "access":
            return p
    body = {
        "title": ACCESS_TITLE,
        "decision_type": "access",
        "fields": {
            "person": "Elif Demir",
            "system": "prod-db",
            "level": "read",
            "until": until_utc(3),
            "reason": "Investigate incident 2214.",
            "reference": "INC-2214",
        },
        "expires_in_hours": 72,
    }
    return api(ada, "/api/v1/vaults/3/proposals", body)["proposal"]


def honest_change(fp, **over):
    valid_until = int((NOW + timedelta(days=2)).timestamp())
    inputs = {
        "chain_id": 11155111,
        "treasury": TREASURY,
        "config_nonce": 3,
        "add": ["0x" + "11" * 124],
        "remove": ["0x" + "22" * 124],
        "threshold": 2,
        "valid_until": valid_until,
    }
    digest = reconfigure_digest(
        chain_id=inputs["chain_id"],
        treasury=inputs["treasury"],
        config_nonce=inputs["config_nonce"],
        add=[bytes.fromhex(h[2:]) for h in inputs["add"]],
        remove=[bytes.fromhex(h[2:]) for h in inputs["remove"]],
        threshold=inputs["threshold"],
        valid_until=inputs["valid_until"],
    ).hex()
    change = {
        "id": 41,
        "state": "collecting_approvals",
        "reason": None,
        "requested_at": iso(timedelta(hours=-2)),
        "valid_until": datetime.fromtimestamp(valid_until, UTC).isoformat(),
        "threshold": 2,
        "approvals": 1,
        "needed": 2,
        "approved_by_me": False,
        "approval_problem": None,
        "my_custody": "device",
        "seat_fingerprint": fp,
        "signing_inputs": inputs,
        "digest": digest,
        "confirmed_warnings": [],
        "tx_hash": None,
        "people": {
            "add": [{"user_id": 2, "name": "Brij Mehta", "key_fingerprint": "a1b2c3d4e5f60718"}],
            "remove": [{"user_id": 2, "name": "Brij Mehta", "key_fingerprint": "0f1e2d3c4b5a6978"}],
        },
    }
    change.update(over)
    return change


def with_change(change):
    def put(body):
        body["change"] = {
            "pending_change": None,
            "may_request": False,
            "problems": [],
            "warnings": [],
            "warnings_digest": None,
            "reconfiguration": change,
        }

    return rewrite(rf".*/api/v1/vaults/{TREASURY_VAULT}/treasury$", put)


# -- the rest of the tour ------------------------------------------------------------------------


def main_tour(browser, ada, fp):
    everything = api(ada, "/api/v1/proposals?state=all")["proposals"]
    by_title = {p["title"]: p for p in everything}
    general = by_title[GENERAL]

    # Approvals with a treasury change in the queue (§6.15 "Row in Approvals").
    def approvals(page, _link):
        open_app(page)
        shot(page, "a10_approvals_with_treasury_change")

    run(browser, ada, "a10", approvals, routes=[with_change(honest_change(fp))])

    # Waiting on others: one you raised (Remind beside it), one that can't pass.
    def waiting_list(body):
        base = copy.deepcopy(general)
        mine = dict(base, proposal_uuid="11111111-1111-4111-8111-111111111111", title="Rotate the on-call paging credentials",
                    status="open", expires_at=iso(timedelta(hours=30)), signed_by_me=False, can_sign=False, approvals=1,
                    raised_by={"id": ADA[0], "name": ADA[1]}, can_still_approve=[BRIJ[0], CHEN[0]], can_still_pass=True,
                    signers=[{"user_id": i, "name": n} for i, n in (ADA, BRIJ, CHEN)])
        stuck = dict(base, proposal_uuid="22222222-2222-4222-8222-222222222222", title="Raise the API rate limit for Northwind",
                     status="open", expires_at=iso(timedelta(days=3)), signed_by_me=True, can_sign=False, approvals=1,
                     can_still_approve=[], can_still_pass=False,
                     cannot_pass_why=["Chen Wei was removed from the vault, so too few approvers are left to reach 2."],
                     signers=[{"user_id": i, "name": n} for i, n in (ADA, BRIJ, CHEN)])
        body["proposals"] = [mine, stuck]

    def waiting(page, _link):
        open_app(page)
        button(page, "Waiting on others").click()
        page.wait_for_timeout(900)
        quiet(page)
        shot(page, "a11_waiting_remind_and_cant_pass")
        page.get_by_role("button", name=re.compile("^Remind the approvers")).first.click()
        page.wait_for_timeout(600)
        shot(page, "a11b_waiting_reminded", wait_ms=200)

    run(
        browser,
        ada,
        "a11",
        waiting,
        routes=[
            rewrite(r".*/api/v1/proposals\?state=all.*", waiting_list),
            (r".*/api/v1/proposals/[0-9a-f-]+/remind$", lambda r: r.fulfill(json={"ok": True, "reminded": 2})),
        ],
    )

    # An auditor: no plus on Approvals, no Create a vault.
    def auditor(page, _link):
        open_app(page)
        shot(page, "a12_approvals_auditor")
        tab(page, "Vaults")
        shot(page, "v06_vaults_auditor")

    run(
        browser,
        ada,
        "a12",
        auditor,
        routes=[rewrite(r".*/api/v1/me$", lambda b: b["workspace"].update(role="auditor", role_name="Auditor"))],
    )

    # Vaults and a vault (§6.13, §6.14), with a rule change and separation of duties.
    def vault_detail(body):
        v = body["vault"]
        v["separation_of_duties"] = True
        v["rule_changes"] = [
            {"event": "vault_threshold_changed", "who": "Ada Okafor", "when": iso(timedelta(days=-7)),
             "label": "Approvals needed", "before": "1", "after": "2"},
        ]
        for m in v["members"]:
            if m["user_id"] == CHEN[0]:
                m["has_key"] = False

    def vaults(page, _link):
        open_app(page)
        tab(page, "Vaults")
        shot(page, "v01_vaults")
        button(page, "Treasury").click()
        page.get_by_text("Members", exact=True).first.wait_for(timeout=60000)
        quiet(page, settle_ms=1200)
        shot(page, "v02_vault")
        button(page, "Members").click()
        page.wait_for_timeout(900)
        shot(page, "v03_vault_members")
        close_sheet(page)
        button(page, "Treasury").click()
        page.wait_for_timeout(900)
        shot(page, "v04_vault_treasury")
        close_sheet(page)
        button(page, "History").click()
        page.wait_for_timeout(900)
        quiet(page)
        shot(page, "v05_vault_history")

    run(
        browser,
        ada,
        "v0",
        vaults,
        routes=[
            rewrite(rf".*/api/v1/vaults/{TREASURY_VAULT}$", vault_detail),
            with_change(honest_change(fp)),
        ],
    )

    # The treasury change, in its states (§6.15).
    link = f"qvault://vault/{TREASURY_VAULT}/treasury-change/41"
    for name, change in (
        ("t02_change_needs_you", honest_change(fp)),
        ("t01_change_tampered", honest_change(fp, digest="ab" * 32)),
        ("t03_change_password_key", honest_change(fp, my_custody="password", seat_fingerprint="0123456789abcdef")),
        ("t04_change_you_approved", honest_change(fp, approved_by_me=True)),
        ("t06_change_registering", honest_change(fp, state="registering_keys", signing_inputs=None, digest=None)),
        ("t07_change_applying", honest_change(fp, state="finalizing", approvals=2)),
        ("t09_change_voided", honest_change(fp, state="voided")),
    ):

        def steps(page, lk, name=name):
            open_app(page, lk)
            button(page, "More options").wait_for(timeout=60000)
            quiet(page)
            shot(page, name)
            if name == "t02_change_needs_you":
                button(page, "Approve change").click()
                page.wait_for_timeout(1000)
                shot(page, "t02b_change_approve_sheet")
                button(page, "Cancel").click()
                page.wait_for_timeout(700)
                button(page, "Checked on this phone").click()
                page.wait_for_timeout(900)
                shot(page, "t02c_change_checked")

        run(browser, ada, name[:3], lambda page, lk, steps=steps: steps(page, link), routes=[with_change(change)])

    # New decision (§6.16): from the queue's plus, every type, the payment review, discard.
    def new_decision(page, _link):
        open_app(page)
        button(page, "New decision").click()
        page.get_by_text("Choose a vault").first.wait_for(timeout=60000)
        quiet(page)
        shot(page, "n01_new_decision")
        button(page, "Choose a vault").click()
        page.wait_for_timeout(900)
        shot(page, "n02_vault_picker")
        button(page, "Treasury").click()
        page.wait_for_timeout(900)
        quiet(page)
        button(page, "Raise decision").click()
        page.wait_for_timeout(500)
        shot(page, "n03_general_missing")
        page.get_by_role("tab", name="Payment", exact=True).or_(page.get_by_role("radio", name="Payment", exact=True)).first.click()
        page.wait_for_timeout(500)
        page.get_by_placeholder("0.25").fill("0.0025")
        page.get_by_placeholder("0x…").fill("0x8ba1f109551bD432803012645Ac136ddd64DBA72")
        page.get_by_placeholder("0.25").focus()
        page.wait_for_timeout(400)
        shot(page, "n04_payment")
        button(page, "Review payment").click()
        page.wait_for_timeout(1000)
        shot(page, "n05_payment_review")
        button(page, "Edit").click()
        page.wait_for_timeout(700)
        page.get_by_role("tab", name="Access", exact=True).or_(page.get_by_role("radio", name="Access", exact=True)).first.click()
        page.wait_for_timeout(500)
        page.get_by_placeholder("Elif Kaya").fill("Elif Demir")
        page.get_by_placeholder("prod-db").fill("prod-db")
        page.get_by_placeholder("Investigate incident 2214.").fill("Investigate incident 2214.")
        page.wait_for_timeout(300)
        shot(page, "n06_access")
        button(page, "Close").click()
        page.wait_for_timeout(900)
        shot(page, "n07_discard")

    run(browser, ada, "n0", new_decision)

    # I-5: a decision raised here, as stored; and one the server stored differently.
    def raise_general(page, title, text):
        open_app(page)
        tab(page, "Vaults")
        button(page, "Incident response").click()
        page.get_by_text("Members", exact=True).first.wait_for(timeout=60000)
        quiet(page)
        button(page, "New decision in this vault").click()
        page.get_by_placeholder("Rotate the on-call paging credentials").wait_for(timeout=60000)
        quiet(page)
        page.get_by_placeholder("Rotate the on-call paging credentials").fill(title)
        page.get_by_placeholder("Say exactly what approving authorises.").fill(text)
        button(page, "Raise decision").click()
        button(page, "Details").wait_for(timeout=90000)
        quiet(page)

    def raised_ok(page, _link):
        raise_general(page, "Rotate the staging paging credentials", "Rotate the staging paging integration keys tonight.")
        shot(page, "n09_raised_as_entered")

    run(browser, ada, "n09", raised_ok)

    def doctored(route):
        body = json.loads(route.request.post_data or "{}")
        if "action_text" in body:
            body["action_text"] = body["action_text"].replace("staging", "production")
        route.continue_(post_data=json.dumps(body))

    def raised_bad(page, _link):
        raise_general(page, "Rotate the staging paging credentials (2)", "Rotate the staging paging integration keys tonight.")
        shot(page, "n10_raised_not_as_entered")

    run(browser, ada, "n10", raised_bad, routes=[(r".*/api/v1/vaults/2/proposals$", doctored)])

    # New vault (§6.17).
    def new_vault(page, _link):
        open_app(page)
        tab(page, "Vaults")
        button(page, "Create a vault").click()
        page.get_by_placeholder("Board approvals").wait_for(timeout=60000)
        quiet(page)
        shot(page, "nv01_new_vault")
        page.get_by_placeholder("Board approvals").fill("Release sign-off")
        button(page, "Add approvers").click()
        page.get_by_role("checkbox", name="Brij Mehta", exact=True).wait_for(timeout=60000)
        page.wait_for_timeout(500)
        page.get_by_role("checkbox", name="Brij Mehta", exact=True).click()
        page.wait_for_timeout(300)
        shot(page, "nv02_add_approvers")
        button(page, "Done, 1 added").click()
        page.wait_for_timeout(700)
        page.get_by_role("radio", name="All 2", exact=True).click()
        page.wait_for_timeout(300)
        shot(page, "nv03_rule_cannot_pass")
        button(page, "Check and create").click()
        page.wait_for_timeout(1000)
        shot(page, "nv04_review")

    run(browser, ada, "nv", new_vault)

    # Activity (§6.12).
    def activity(page, _link):
        open_app(page)
        tab(page, "Activity")
        shot(page, "ac01_your_decisions")
        page.get_by_role("radio", name="Decided", exact=True).click()
        page.wait_for_timeout(500)
        shot(page, "ac02_decided")
        button(page, "Search your decisions").click()
        page.wait_for_timeout(400)
        page.get_by_placeholder("deployer").fill("deployer")
        page.wait_for_timeout(400)
        shot(page, "ac03_search_nothing")

    run(browser, ada, "ac0", activity)

    # Account and its pages (§6.18).
    def account(page, _link):
        open_app(page)
        tab(page, "Account")
        shot(page, "acc01_account")
        button(page, "This phone").click()
        page.wait_for_timeout(900)
        quiet(page)
        shot(page, "acc02_this_phone")
        button(page, "Key details").click()
        page.wait_for_timeout(900)
        shot(page, "acc03_key_details")
        close_sheet(page)
        page.get_by_role("button", name="Go back", exact=True).first.click()
        page.wait_for_timeout(700)
        if button(page, "Other devices").count():
            button(page, "Other devices").click()
            page.wait_for_timeout(900)
            quiet(page)
            shot(page, "acc04_other_devices")
            page.get_by_role("button", name=re.compile("^Ada.s second phone")).first.click()
            page.wait_for_timeout(900)
            shot(page, "acc05_device_sheet")
            button(page, "Remove this device").click()
            page.wait_for_timeout(1000)
            shot(page, "acc06_remove_other_device")
            close_sheet(page)
            page.get_by_role("button", name="Go back", exact=True).first.click()
            page.wait_for_timeout(700)
        if button(page, "Treasury approvals").count():
            button(page, "Treasury approvals").click()
            page.wait_for_timeout(900)
            quiet(page)
            shot(page, "acc07_treasury_approvals")
            page.get_by_role("button", name="Go back", exact=True).first.click()
            page.wait_for_timeout(700)
        button(page, "Notifications").click()
        page.wait_for_timeout(800)
        shot(page, "acc08_notifications")
        page.get_by_role("button", name="Go back", exact=True).first.click()
        page.wait_for_timeout(700)
        button(page, "Help and about").click()
        page.wait_for_timeout(800)
        shot(page, "acc09_help")

    run(browser, ada, "acc", account)

    # App lock (§6.1): on, and the prompt cancelled, so the lock screen stays.
    def locked(page, _link):
        page.goto(BASE + "/" + QUERY)
        page.get_by_text("Q-Vault is locked").wait_for(timeout=90000)
        page.wait_for_timeout(900)
        shot(page, "l01_locked")

    run(
        browser,
        ada,
        "l01",
        locked,
        auth="cancel",
        init=["localStorage.setItem('webshots.securestore.qvault.device.applock.v1', 'on');"],
    )

    # P4 on the decision (§6.21): a typed card, a tampered field, withdraw, remind, discussion,
    # can't pass.
    access = access_decision(ada)
    alink = f"qvault://decision/{access['proposal_uuid']}"

    def typed(page, lk):
        open_app(page, lk)
        button(page, "Details").wait_for(timeout=60000)
        quiet(page)
        shot(page, "d20_typed_card")
        button(page, "Show the signed text").click()
        page.wait_for_timeout(400)
        shot(page, "d20b_typed_signed_text")
        button(page, "More options").click()
        page.wait_for_timeout(900)
        shot(page, "d22_more_with_withdraw")
        button(page, "Withdraw decision").click()
        page.wait_for_timeout(1000)
        shot(page, "d22b_withdraw_sheet")

    run(browser, ada, "d20", lambda p_, _l: typed(p_, alink))

    def tamper_field(body):
        p = body.get("proposal") or {}
        if p.get("fields"):
            p["fields"]["level"] = "admin"

    def typed_tampered(page, lk):
        open_app(page, lk)
        button(page, "Details").wait_for(timeout=60000)
        quiet(page)
        shot(page, "d21_typed_field_tampered")

    run(
        browser,
        ada,
        "d21",
        lambda p_, _l: typed_tampered(p_, alink),
        routes=[rewrite(r".*/api/v1/proposals/" + access["proposal_uuid"] + r"$", tamper_field)],
    )

    glink = f"qvault://decision/{general['proposal_uuid']}"

    def open_now(d, hours=5):
        d.update(status="open", expires_at=iso(timedelta(hours=hours)), approvals=0, rejections=0)
        d.update(signed_by_me=False, can_sign=True, votes=[])

    def as_raiser(body):
        d = body.get("proposal") or {}
        open_now(d)
        d.update(raised_by={"id": ADA[0], "name": ADA[1]}, separation_of_duties=True, can_sign=False,
                 signers=[{"user_id": i, "name": n} for i, n in (ADA, BRIJ, CHEN)], can_withdraw=True)

    def remind(page, lk):
        open_app(page, lk)
        button(page, "Details").wait_for(timeout=60000)
        quiet(page)
        shot(page, "d23_raised_it_remind")
        button(page, "Remind").click()
        page.wait_for_timeout(500)
        shot(page, "d23b_reminded", wait_ms=200)

    run(
        browser,
        ada,
        "d23",
        lambda p_, _l: remind(p_, glink),
        routes=[
            rewrite(r".*/api/v1/proposals/" + general["proposal_uuid"] + r"$", as_raiser),
            (r".*/api/v1/proposals/[0-9a-f-]+/remind$", lambda r: r.fulfill(json={"ok": True, "reminded": 2})),
        ],
    )

    comments = {
        "ok": True,
        "signed": False,
        "can_post": True,
        "comments": [
            {"id": 1, "author": {"id": 2, "name": "Brij Mehta"}, "created_at": iso(timedelta(hours=-3)),
             "deleted": False, "mine": False, "body": "Does this include the March back pay?",
             "segments": [{"text": "Does this include the March back pay?", "mention": None}]},
            {"id": 2, "author": {"id": 1, "name": "Ada Okafor"}, "created_at": iso(timedelta(hours=-2)),
             "deleted": False, "mine": True, "body": "@Brij Mehta yes, it is in line 4. The real address is 0x41Ed00000000000000000000000000000000008A19.",
             "segments": [{"text": "@Brij Mehta", "mention": {"user_id": 2}},
                          {"text": " yes, it is in line 4. The real address is 0x41Ed00000000000000000000000000000000008A19.", "mention": None}]},
            {"id": 3, "author": {"id": 3, "name": "Chen Wei"}, "created_at": iso(timedelta(hours=-1)),
             "deleted": True, "mine": False, "body": "", "segments": []},
        ],
        "next_after": None,
    }

    def needs(body):
        d = body.get("proposal") or {}
        open_now(d)
        d["signers"] = [{"user_id": i, "name": n} for i, n in (ADA, BRIJ, CHEN)]

    def discussion(page, lk):
        open_app(page, lk)
        button(page, "Details").wait_for(timeout=60000)
        quiet(page)
        page.get_by_role("button", name=re.compile("^Discussion")).first.scroll_into_view_if_needed()
        page.wait_for_timeout(400)
        shot(page, "d24_discussion_row")
        page.get_by_role("button", name=re.compile("^Discussion")).first.click()
        page.wait_for_timeout(1000)
        quiet(page)
        shot(page, "d25_discussion")

    run(
        browser,
        ada,
        "d24",
        lambda p_, _l: discussion(p_, glink),
        routes=[
            rewrite(r".*/api/v1/proposals/" + general["proposal_uuid"] + r"$", needs),
            (r".*/api/v1/proposals/[0-9a-f-]+/comments.*", lambda r: r.fulfill(json=comments)),
        ],
    )

    def cant_pass(body):
        d = body.get("proposal") or {}
        open_now(d)
        d.update(can_sign=False, can_still_pass=False, signers=[{"user_id": i, "name": n} for i, n in (ADA, BRIJ, CHEN)],
                 cannot_pass_why=["Brij Mehta and Chen Wei can no longer approve in this vault, so it can't reach 2 approvals."])
        d["signing_inputs"]  # unchanged: the signed set still lists Ada, so row 8 applies

    def cant(page, lk):
        open_app(page, lk)
        button(page, "Details").wait_for(timeout=60000)
        quiet(page)
        shot(page, "d26_cant_pass")

    run(
        browser,
        ada,
        "d26",
        lambda p_, _l: cant(p_, glink),
        routes=[rewrite(r".*/api/v1/proposals/" + general["proposal_uuid"] + r"$", cant_pass)],
    )


with sync_playwright() as p:
    browser = p.chromium.launch()
    ada, ada2 = STATE / "ada.json", STATE / "ada2.json"
    if not ONLY or any(n.startswith("o") for n in ONLY):
        onboarding(browser)
    enrol(browser, "ada@qvault.demo", ada, shots=True)
    if not ada2.exists():
        # A second phone of Ada's, so Other devices has one to remove.
        ctx, page = new_page(browser)
        page.goto(BASE + "/" + QUERY)
        page.get_by_placeholder("you@example.com").wait_for(timeout=90000)
        sign_in(page, "ada@qvault.demo", PASSWORD)
        page.get_by_text("This phone gets its own key").wait_for(timeout=90000)
        button(page, "Name").click()
        page.get_by_label("Name").fill("Ada's second phone")
        page.keyboard.press("Tab")
        button(page, "Create key on this phone").click()
        page.get_by_role("tab", name=re.compile("^Account")).wait_for(timeout=90000)
        ctx.storage_state(path=str(ada2))
        ctx.close()
    fp = json.loads(local(ada, "qvault.device.identity.v1"))["fingerprint"]
    main_tour(browser, ada, fp)
    browser.close()

(OUT / "audit_p3.json").write_text(json.dumps({**audit, "errors": errors}, indent=2), encoding="utf-8", newline="\n")
print(f"audit: {audit['checked']} targets checked, {len(audit['findings'])} findings")
for finding in audit["findings"]:
    print("  ", finding)
for e in errors:
    print("ERROR", e)
