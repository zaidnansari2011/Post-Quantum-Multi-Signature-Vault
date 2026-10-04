"""Web screenshot harness ONLY: drive the phone app's web build like a user; capture every screen.

Usage: python shoot.py <harness origin> <out dir> <state dir>
  harness origin  where serve.py is serving the web export, e.g. http://127.0.0.1:8099
  out dir         PNGs land here as app_<NN>_<screen>.png
  state dir       enrolled-device browser state (ada.json, brij.json) so a re-run reuses the same
                  enrolled devices instead of enrolling new ones

Phone viewport: 390x844 CSS px at deviceScaleFactor 2. Any request that is not to the harness
origin is aborted, so nothing can reach a production host. Raising decisions is idempotent by title.
"""

import json
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1].rstrip("/")
OUT = Path(sys.argv[2])
STATE = Path(sys.argv[3])
OUT.mkdir(parents=True, exist_ok=True)
STATE.mkdir(parents=True, exist_ok=True)

W, H = 390, 844
PASSWORD = "demo-password-2026"
counter = {"n": 0}
taken = []


# -- plumbing ---------------------------------------------------------------------------------


def new_page(browser, state=None):
    ctx = browser.new_context(
        viewport={"width": W, "height": H},
        device_scale_factor=2,
        is_mobile=False,  # desktop Chromium rendering; the viewport is what makes it a phone
        storage_state=str(state) if state and Path(state).exists() else None,
    )
    page = ctx.new_page()
    inflight = {"n": 0}

    def guard(route):
        if route.request.url.startswith(BASE):
            return route.continue_()
        print("BLOCKED", route.request.url)
        return route.abort()

    page.route("**/*", guard)
    page.on(
        "request",
        lambda r: inflight.__setitem__("n", inflight["n"] + 1) if "/api/" in r.url else None,
    )
    for ev in ("requestfinished", "requestfailed"):
        page.on(
            ev,
            lambda r: (
                inflight.__setitem__("n", max(0, inflight["n"] - 1)) if "/api/" in r.url else None
            ),
        )
    page.on("pageerror", lambda e: print("PAGEERROR", str(e)[:300]))
    page._inflight = inflight
    return ctx, page


def quiet(page, settle_ms=700, timeout_s=90):
    """Wait until no API request has been in flight for `settle_ms`, then let animations finish."""
    t0, since = time.time(), None
    while time.time() - t0 < timeout_s:
        if page._inflight["n"] == 0:
            since = since or time.time()
            if (time.time() - since) * 1000 >= settle_ms:
                return
        else:
            since = None
        page.wait_for_timeout(100)


# How far the screen in front can scroll. Measured from the element under the middle of the screen
# upwards, because inactive tabs stay mounted (hidden by pointer-events, not display) and their
# lists would otherwise be measured instead.
SCROLL_EXTRA = """() => {
  let el = document.elementFromPoint(innerWidth / 2, innerHeight / 2), extra = 0;
  for (; el; el = el.parentElement) {
    if (/(auto|scroll)/.test(getComputedStyle(el).overflowY)) {
      extra = Math.max(extra, el.scrollHeight - el.clientHeight);
    }
  }
  return extra;
}"""


def shot(page, name, tall=False, wait_ms=500):
    """Viewport screenshot; with tall=True also a full-length one (viewport grown to content)."""
    page.wait_for_timeout(wait_ms)
    counter["n"] += 1
    path = OUT / f"app_{counter['n']:02d}_{name}.png"
    page.screenshot(path=str(path))
    taken.append(path.name)
    print("shot", path.name, flush=True)
    if tall:
        height = H
        for _ in range(4):  # a list may render more rows once the viewport grows
            extra = page.evaluate(SCROLL_EXTRA)
            if extra <= 4:
                break
            height = min(height + extra, 9000)
            page.set_viewport_size({"width": W, "height": height})
            page.wait_for_timeout(700)
        if height > H:
            counter["n"] += 1
            path = OUT / f"app_{counter['n']:02d}_{name}_full.png"
            page.screenshot(path=str(path))
            taken.append(path.name)
            print("shot", path.name, f"({height}px)", flush=True)
        page.set_viewport_size({"width": W, "height": H})
        page.wait_for_timeout(400)


def button(page, name):
    return page.get_by_role("button", name=name, exact=True).first


def tab(page, name):
    page.get_by_role("tab", name=name, exact=True).first.click()
    quiet(page)


def back(page):
    page.get_by_role("button", name="Go back", exact=True).first.click()
    quiet(page)


def open_card(page, title):
    button(page, title).click()
    page.get_by_text("Verified on this device").or_(
        page.get_by_text("does not match")
    ).first.wait_for(timeout=60000)
    quiet(page)


def token_of(state_file):
    s = json.loads(Path(state_file).read_text(encoding="utf-8"))
    for origin in s["origins"]:
        for kv in origin["localStorage"]:
            if kv["name"].endswith("qvault.device.token.v1"):
                return kv["value"]
    raise SystemExit(f"no token in {state_file}")


def titles(state_file):
    req = urllib.request.Request(
        BASE + "/api/v1/proposals?state=all",
        headers={"Authorization": "Bearer " + token_of(state_file), "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return {p["title"] for p in json.load(r)["proposals"]}


def enrol(browser, email, state_file):
    """Enrol a device the way a person does, once; later runs reuse its stored state."""
    if Path(state_file).exists():
        return
    ctx, page = new_page(browser)
    page.goto(BASE + "/")
    page.get_by_placeholder("you@example.com").fill(email)
    page.get_by_placeholder("Your Q-Vault password").fill(PASSWORD)
    button(page, "Enrol this device").click()
    page.get_by_role("tab", name="Account", exact=True).wait_for(timeout=90000)
    quiet(page)
    ctx.storage_state(path=str(state_file))
    ctx.close()


# The decisions raised from the phone, so the queue holds live work with real deadlines (the demo
# database's own open decisions are all past their deadlines on today's date).
RAISE = [
    dict(
        vault="Incident response",
        title="Rotate the on-call paging credentials",
        deadline="Today",
        text="Rotate the paging integration keys for every production service, and revoke the "
        "previous set once the new keys are confirmed working.",
    ),
    dict(
        vault="Contracts",
        title="Calderwood insurance renewal, 2027",
        deadline="In 3 days",
        text="Renew the Calderwood Mutual commercial liability policy for the 2027 calendar "
        "year at the quoted annual premium of GBP 48,200, with cover unchanged from 2026. "
        "Authorises the finance team to sign the renewal schedule and to pay the first "
        "quarterly instalment on receipt of the invoice.",
    ),
    dict(
        vault="Production access",
        title="Temporary production read for incident 2214",
        deadline="In a week",
        text="Grant Elif Demir read-only access to the production database for 48 hours to "
        "investigate incident 2214. Access expires automatically.",
    ),
]
TREASURY_RAISE = dict(
    title="Q4 cloud commitment",
    deadline="Tomorrow",
    text="Commit to the Q4 reserved-capacity plan with our cloud provider for the "
    "three production regions, replacing on-demand billing from 1 November.",
)


def fill_decision(page, d):
    page.get_by_placeholder("Authorise the Q4 drawdown").fill(d["title"])
    page.get_by_placeholder("Describe exactly what approval authorises", exact=False).fill(
        d["text"]
    )
    page.get_by_role("radio", name=d["deadline"], exact=True).click()


def submit_decision(page):
    button(page, "Raise decision").click()
    page.get_by_text("Verified on this device").first.wait_for(timeout=60000)
    quiet(page)


def sign(page, verb, overlay_name, after_name):
    """Approve or reject from the decision screen: sheet, sign, acknowledgement, the page after."""
    button(page, verb).click()
    page.wait_for_timeout(900)
    button(page, "Sign approval" if verb == "Approve" else "Sign rejection").click()
    button(page, "Done").wait_for(timeout=90000)
    shot(page, overlay_name, wait_ms=2600)  # let the tick/cross finish drawing
    button(page, "Done").click()
    page.wait_for_timeout(800)
    quiet(page)
    shot(page, after_name, tall=True)


# -- the run ----------------------------------------------------------------------------------

with sync_playwright() as p:
    browser = p.chromium.launch()
    ada_state, brij_state = STATE / "ada.json", STATE / "brij.json"

    # 1. Enrolment, as someone meeting the app for the first time.
    ctx, page = new_page(browser)
    page.goto(BASE + "/")
    page.get_by_placeholder("you@example.com").wait_for(timeout=60000)
    shot(page, "enrol")
    page.get_by_placeholder("you@example.com").fill("ada@qvault.demo")
    page.get_by_placeholder("Your Q-Vault password").fill("not-the-password")
    shot(page, "enrol_filled")
    button(page, "Enrol this device").click()
    page.get_by_text("Email or password is incorrect.").wait_for(timeout=60000)
    shot(page, "enrol_error")
    ctx.close()

    enrol(browser, "ada@qvault.demo", ada_state)
    enrol(browser, "brij@qvault.demo", brij_state)

    # 2. Loading and failure states of the queue (API delayed, then refused).
    ctx, page = new_page(browser, ada_state)
    page.route("**/api/v1/proposals*", lambda r: None)  # left pending: the queue stays loading
    page.goto(BASE + "/")
    page.get_by_role("tab", name="Account", exact=True).wait_for(timeout=60000)
    shot(page, "home_loading", wait_ms=600)
    ctx.close()
    ctx, page = new_page(browser, ada_state)
    page.route("**/api/v1/proposals*", lambda r: r.abort())
    page.goto(BASE + "/")
    page.get_by_text("Could not load your approvals.").wait_for(timeout=60000)
    shot(page, "home_error")
    ctx.close()

    # 3. Raising decisions (Ada).
    ctx, page = new_page(browser, ada_state)
    page.goto(BASE + "/")
    page.get_by_role("tab", name="Account", exact=True).wait_for(timeout=60000)
    quiet(page)
    existing = titles(ada_state)

    for i, d in enumerate(RAISE):
        button(page, "Raise a decision").click()
        page.get_by_text("Which vault is this decision for?").wait_for(timeout=30000)
        quiet(page)
        if i == 0:
            shot(page, "new_decision_pick_vault")
        button(page, d["vault"]).click()
        page.get_by_placeholder("Authorise the Q4 drawdown").wait_for(timeout=30000)
        quiet(page)
        if i == 0:
            shot(page, "new_decision_empty")
        fill_decision(page, d)
        if i == 0:
            shot(page, "new_decision_filled")
        if d["title"] in existing:
            back(page)
            continue
        submit_decision(page)
        back(page)

    # Treasury: raised from inside the vault, where the treasury offers a payment as well.
    tab(page, "Vaults")
    button(page, "Treasury").click()
    page.get_by_text(" members", exact=False).first.wait_for(timeout=90000)
    quiet(page, settle_ms=1500)
    button(page, "Raise a decision").click()
    page.get_by_role("radio", name="Payment", exact=True).wait_for(timeout=60000)
    quiet(page)
    shot(page, "new_decision_in_treasury")
    page.get_by_role("radio", name="Payment", exact=True).click()
    page.get_by_placeholder("Authorise the Q4 drawdown").fill("Refund the Northwind deposit")
    page.get_by_placeholder("0x…").fill("0x8ba1f109551bD432803012645Ac136ddd64DBA72")
    page.get_by_placeholder("0.0001").fill("0.0025")
    shot(page, "new_payment_filled")  # not submitted: a payment queues on-chain work
    page.get_by_role("radio", name="Decision", exact=True).click()
    fill_decision(page, TREASURY_RAISE)
    if TREASURY_RAISE["title"] in existing:
        back(page)
    else:
        submit_decision(page)
        back(page)
    back(page)  # vault -> vault list
    tab(page, "Approvals")
    ctx.storage_state(path=str(ada_state))
    ctx.close()

    # 4. A second signer (Brij, on his own phone) approves one, so Ada's signature completes it.
    ctx, page = new_page(browser, brij_state)
    page.goto(BASE + "/")
    page.get_by_role("tab", name="Account", exact=True).wait_for(timeout=60000)
    quiet(page)
    brij_target = page.get_by_role("button", name=RAISE[0]["title"], exact=True)
    if brij_target.count():
        open_card(page, RAISE[0]["title"])
        if button(page, "Approve").count():
            button(page, "Approve").click()
            page.wait_for_timeout(900)
            button(page, "Sign approval").click()
            button(page, "Done").wait_for(timeout=90000)
            button(page, "Done").click()
            quiet(page)
    ctx.close()

    # 5. The main tour (Ada).
    ctx, page = new_page(browser, ada_state)
    page.goto(BASE + "/")
    page.get_by_role("tab", name="Account", exact=True).wait_for(timeout=60000)
    quiet(page)
    shot(page, "home", tall=True)

    tab(page, "Vaults")
    shot(page, "vaults", tall=True)

    button(page, "Treasury").click()
    page.get_by_text(" members", exact=False).first.wait_for(timeout=90000)
    quiet(page, settle_ms=1500)
    shot(page, "vault_treasury", tall=True)
    if page.get_by_text("Address", exact=True).count():
        page.get_by_text("Address", exact=True).first.scroll_into_view_if_needed()
        page.evaluate("""() => { for (const el of document.querySelectorAll('div')) {
            const cs = getComputedStyle(el);
            if (el.getClientRects().length && /(auto|scroll)/.test(cs.overflowY)
                && el.scrollHeight > el.clientHeight)
              el.scrollTop = Math.max(0, el.scrollTop - 60); } }""")
        shot(page, "vault_treasury_card")

    for title, name in [
        (TREASURY_RAISE["title"], "decision_open"),
        ("Q3 supplier settlement", "decision_approved"),
        ("Duplicate invoice payment", "decision_rejected"),
        ("Emergency hardware purchase", "decision_expired"),
        ("Office lease deposit", "decision_open_past_deadline"),
        ("Return 0.0001 ETH to the relayer", "decision_payment_paid"),
        ("Tamper demonstration", "decision_payment_failed"),
    ]:
        if not page.get_by_role("button", name=title, exact=True).count():
            print("MISSING card", title)
            continue
        open_card(page, title)
        shot(page, name, tall=True)
        if name == "decision_open":
            button(page, "Verified on this device. Show the signing detail.").click()
            page.wait_for_timeout(800)
            shot(page, "decision_open_signing_detail", tall=True)
            if button(page, "Approve").count():  # absent on a re-run: already signed
                button(page, "Approve").click()
                shot(page, "sheet_approve", wait_ms=1000)
                button(page, "Cancel").click()
                page.wait_for_timeout(700)
                button(page, "Reject").click()
                shot(page, "sheet_reject", wait_ms=1000)
                button(page, "Cancel").click()
                page.wait_for_timeout(700)
        back(page)
    back(page)  # vault -> vault list

    # 6. Activity, each filter.
    tab(page, "Activity")
    shot(page, "activity_all", tall=True)
    for f in ("Open", "Approved", "Declined"):
        page.get_by_role("tab", name=f, exact=True).click()
        page.wait_for_timeout(500)
        shot(page, f"activity_{f.lower()}")
    page.get_by_role("tab", name="All", exact=True).click()

    # 7. Account and its two endings (both cancelled).
    tab(page, "Account")
    shot(page, "account", tall=True)
    button(page, "Sign out").click()
    shot(page, "sheet_sign_out", wait_ms=1000)
    button(page, "Cancel").click()
    page.wait_for_timeout(700)
    button(page, "Revoke this device").click()
    shot(page, "sheet_revoke", wait_ms=1000)
    button(page, "Cancel").click()
    page.wait_for_timeout(700)

    # 7b. The integrity-failure screen. Nothing in the data is tampered with, so the harness
    # rewrites one decision's text in the server's reply (both the shown and the signed copy), the
    # way a compromised server or proxy would. The database is untouched.
    TAMPER_TITLE = RAISE[2]["title"]

    def tamper(route):
        resp = route.fetch()
        body = resp.json()
        prop = body.get("proposal") or {}
        if prop.get("title") == TAMPER_TITLE:
            for holder in (prop, prop.get("signing_inputs") or {}):
                holder["action_text"] = holder["action_text"].replace("48 hours", "30 days")
        route.fulfill(response=resp, json=body)

    tctx, tpage = new_page(browser, ada_state)
    tpage.route("**/api/v1/proposals/*", tamper)
    tpage.goto(BASE + "/")
    tpage.get_by_role("tab", name="Account", exact=True).wait_for(timeout=60000)
    quiet(tpage)
    if tpage.get_by_role("button", name=TAMPER_TITLE, exact=True).count():
        open_card(tpage, TAMPER_TITLE)
        shot(tpage, "decision_integrity_failure_simulated", tall=True)
    tctx.close()

    # 8. Signing, three ways. From the queue, as an approver would.
    tab(page, "Approvals")
    if page.get_by_role("button", name=TREASURY_RAISE["title"], exact=True).count():
        open_card(page, TREASURY_RAISE["title"])
        if button(page, "Approve").count():
            sign(page, "Approve", "signed_overlay", "decision_after_signing")
        back(page)
    if page.get_by_role("button", name=RAISE[0]["title"], exact=True).count():
        open_card(page, RAISE[0]["title"])
        shot(page, "decision_open_one_more_needed", tall=True)
        if button(page, "Approve").count():
            sign(page, "Approve", "signed_overlay_threshold_met", "decision_after_threshold_met")
        back(page)
    if page.get_by_role("button", name=RAISE[1]["title"], exact=True).count():
        open_card(page, RAISE[1]["title"])
        shot(page, "decision_open_long_text", tall=True)
        if button(page, "Reject").count():
            sign(page, "Reject", "rejected_overlay", "decision_after_rejecting")
        back(page)
    quiet(page)
    shot(page, "home_after_signing", tall=True)

    # 9. A new vault, created from the vault list.
    tab(page, "Vaults")
    vault_name = "Board approvals"
    exists = page.get_by_role("button", name=vault_name, exact=True).count() > 0
    button(page, "Create a vault").click()
    page.get_by_placeholder("Payments above the delegated limit").wait_for(timeout=30000)
    shot(page, "new_vault_empty")
    page.get_by_placeholder("Treasury").fill(vault_name)
    page.get_by_placeholder("Payments above the delegated limit").fill(
        "Resolutions that need the board's sign-off."
    )
    button(page, "Choose signers").click()
    page.get_by_role("checkbox", name="Brij Mehta", exact=True).wait_for(timeout=30000)
    page.wait_for_timeout(600)
    shot(page, "sheet_choose_signers")
    for person in ("Brij Mehta", "Chen Wei"):
        page.get_by_role("checkbox", name=person, exact=True).click()
    page.wait_for_timeout(300)
    shot(page, "sheet_choose_signers_picked")
    button(page, "Done, 2 signers added").click()
    page.wait_for_timeout(700)
    page.get_by_role("radio", name="2 of 3", exact=True).click()
    shot(page, "new_vault_filled")
    if exists:
        back(page)
        button(page, vault_name).click()
    else:
        button(page, "Create vault").click()
    page.get_by_text("Nothing is open in this vault.").wait_for(timeout=60000)
    quiet(page)
    shot(page, "vault_new_empty", tall=True)

    ctx.close()
    browser.close()

print("\n".join(taken))
