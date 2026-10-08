"""Web screenshot harness ONLY: the freshness step (phone-ux §2.6): the offline bar, the cold-start
hint, the queue painted from the encrypted summary cache, a decision not yet fetched while offline,
"Checking…" before a sheet over an old copy, and signed content that changed while open (I-16).

Usage: python fresh.py <harness origin> <out dir> <state dir> [theme] [font scale] [only,names]

Like states.py, the decision is one real decision whose reply is rewritten in the browser (UNSIGNED
fields only, except the I-16 state, which changes the signed text on its second fetch on purpose).
"Offline" is every /api/ request aborted in the browser, which is what a phone without a connection
sees. Time is moved on with Playwright's clock (the 20 s poll, the minute the gate allows), never by
a hook in the app. Enrols its own device in the state folder (ada.json), and makes warm.json: the
same browser state after a run of the app, so it holds the encrypted summary cache.
"""

import copy
import json
import re
import sys
import time
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

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
audit = {"checked": 0, "findings": []}
errors: list[str] = []

GENERAL = "Payroll adjustment schedule"  # Treasury vault, 2 of 3, signers Ada, Brij, Chen
LONG = "Decommission legacy reporting host"
BRIJ, ADA, CHEN = (2, "Brij Mehta"), (1, "Ada Okafor"), (3, "Chen Wei")
NOW = datetime.now(UTC)
API = re.compile(r".*/api/v1/.*")

AUDIT = """() => [...document.querySelectorAll('[data-hit-w]')]
  .filter((el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; })
  .map((el) => ({
    w: Number(el.dataset.hitW), h: Number(el.dataset.hitH),
    label: el.getAttribute('aria-label') || (el.textContent || '').trim().slice(0, 40),
    nested: !!(el.parentElement && el.parentElement.closest('[data-hit-w]')),
  }))"""


def iso(delta: timedelta) -> str:
    return (NOW + delta).isoformat()


# -- plumbing (as states.py) ------------------------------------------------------------------


def new_page(browser, state=None, clock=False):
    ctx = browser.new_context(
        viewport={"width": W, "height": H},
        device_scale_factor=2,
        storage_state=str(state) if state and Path(state).exists() else None,
    )
    page = ctx.new_page()
    if clock:
        page.clock.install()
    inflight = {"n": 0}

    def guard(route):
        if route.request.url.startswith(BASE):
            if re.search(r"/api/v1/devices/\d+/revoke", route.request.url):
                return route.abort()
            return route.fallback()
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
    page.on("pageerror", lambda e: errors.append(str(e)[:300]) or print("PAGEERROR", str(e)[:300]))
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


def shot(page, name, wait_ms=700):
    page.wait_for_timeout(wait_ms)
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path))
    print("shot", path.name, flush=True)
    for target in page.evaluate(AUDIT):
        audit["checked"] += 1
        if target["w"] < 48 or target["h"] < 48 or target["nested"]:
            audit["findings"].append({"screen": name, **target})


def button(page, name):
    return page.get_by_role("button", name=re.compile("^" + re.escape(name) + r"($|\.|,)")).first


def local(state_file, suffix):
    s = json.loads(Path(state_file).read_text(encoding="utf-8"))
    for origin in s["origins"]:
        for kv in origin["localStorage"]:
            if kv["name"].endswith(suffix):
                return kv["value"]
    raise SystemExit(f"no {suffix} in {state_file}")


def api_get(state_file, path):
    req = urllib.request.Request(
        BASE + path,
        headers={
            "Authorization": "Bearer " + local(state_file, "qvault.device.token.v1"),
            "Accept": "application/json",
            "X-QVault-Capabilities": "payment-action-1",
        },
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)


def enrol(browser, email, state_file):
    if Path(state_file).exists():
        return
    ctx, page = new_page(browser)
    page.goto(BASE + "/" + QUERY)
    page.get_by_placeholder("you@example.com").fill(email)
    page.get_by_placeholder("Your Q-Vault password").fill(PASSWORD)
    button(page, "Enrol this device").click()
    page.get_by_role("tab", name=re.compile("^Account")).wait_for(timeout=90000)
    quiet(page)
    ctx.storage_state(path=str(state_file))
    ctx.close()


def tabs_up(page):
    page.get_by_role("tab", name=re.compile("^Account")).wait_for(timeout=90000)


def go_offline(page):
    """Every request from now on never reaches Q-Vault, as on a phone with no connection."""
    page.route(API, lambda r: r.abort())


# -- rewrites ---------------------------------------------------------------------------------


def needs(d):
    """Open, needs Ada: unsigned fields only."""
    d.update(status="open", expires_at=iso(timedelta(hours=5)), approvals=1, rejections=0)
    d.update(signed_by_me=False, can_sign=True)
    d["votes"] = [
        {
            "signer_id": BRIJ[0],
            "signer_name": BRIJ[1],
            "decision": "approve",
            "custody": "server",
            "alg_id": "ML-DSA-65",
            "reason": None,
            "signed_at": iso(timedelta(minutes=-40)),
        }
    ]
    d["signers"] = [{"user_id": i, "name": n} for i, n in (ADA, BRIJ, CHEN)]


def summary(p, hours, **extra):
    s = copy.deepcopy(p)
    s.update(status="open", signed_by_me=False, can_sign=True, approvals=0, rejections=0)
    s["expires_at"] = iso(timedelta(hours=hours))
    s.update(extra)
    return s


# -- the run ----------------------------------------------------------------------------------


def run(name, fn):
    if ONLY and name not in ONLY:
        return
    try:
        fn(name)
    except Exception as exc:  # one state failing must not hide the others
        errors.append(f"{name}: {exc}")
        print("FAILED", name, exc)


with sync_playwright() as p:
    browser = p.chromium.launch()
    ada = STATE / "ada.json"
    warm = STATE / "warm.json"
    enrol(browser, "ada@qvault.demo", ada)
    everything = api_get(ada, "/api/v1/proposals?state=all")["proposals"]
    by_title = {x["title"]: x for x in everything}
    general, long_ = by_title[GENERAL], by_title[LONG]
    queue = [summary(general, 3, approvals=1), summary(long_, 30)]
    uuid = general["proposal_uuid"]
    detail_url = re.compile(r".*/api/v1/proposals/" + uuid + r"$")

    def fixed_lists(page):
        page.route(
            re.compile(r".*/api/v1/proposals\?state=awaiting.*"),
            lambda r: r.fulfill(json={"ok": True, "state": "awaiting", "proposals": queue}),
        )
        page.route(
            re.compile(r".*/api/v1/proposals\?state=all.*"),
            lambda r: r.fulfill(json={"ok": True, "state": "all", "proposals": queue}),
        )

    def rewritten(route, change=None):
        resp = route.fetch()
        body = resp.json()
        needs(body["proposal"])
        if change:
            change(body["proposal"])
        route.fulfill(response=resp, json=body)

    # A run of the app that leaves the encrypted summary cache behind (saved a second after the
    # lists arrive), kept as warm.json.
    ctx, page = new_page(browser, ada)
    fixed_lists(page)
    page.goto(BASE + "/" + QUERY)
    tabs_up(page)
    quiet(page)
    page.wait_for_timeout(2500)
    ctx.storage_state(path=str(warm))
    ctx.close()
    if "qvault-summaries" not in warm.read_text(encoding="utf-8"):
        errors.append("warm.json holds no summary cache")

    def approvals_offline(name):
        # Loaded, then the connection goes: the next poll (60 s) fails, and its one retry (2 s).
        ctx, page = new_page(browser, ada, clock=True)
        fixed_lists(page)
        page.goto(BASE + "/" + QUERY)
        tabs_up(page)
        quiet(page)
        go_offline(page)
        page.clock.fast_forward(61_000)
        page.wait_for_timeout(500)
        page.clock.fast_forward(3_000)
        page.get_by_text(re.compile(r"^Offline\.")).first.wait_for(timeout=30000)
        shot(page, name)
        ctx.close()

    def approvals_cold_start(name):
        # A first run with no cache, and an answer that does not come.
        ctx, page = new_page(browser, ada)
        page.add_init_script("localStorage.removeItem('qvault-summaries.v1')")
        page.route(API, lambda r: None if "/proposals" in r.request.url else r.fallback())
        page.goto(BASE + "/" + QUERY)
        tabs_up(page)
        page.get_by_text(re.compile(r"^Still connecting")).first.wait_for(timeout=15000)
        shot(page, name + "a_hint")
        button(page, "Try again").wait_for(timeout=25000)
        shot(page, name + "b_try_again")
        ctx.close()

    def approvals_restored_offline(name):
        # A restart with no connection: the queue paints from the encrypted cache with its own
        # headline, and the offline bar says when what is shown was fetched (§6.3).
        ctx, page = new_page(browser, warm)
        go_offline(page)
        page.goto(BASE + "/" + QUERY)
        tabs_up(page)
        # After the one retry, two seconds on.
        page.get_by_text(re.compile("^Offline. Showing what was here")).first.wait_for(timeout=30000)
        page.wait_for_timeout(2500)
        shot(page, name)
        ctx.close()

    def decision_offline(name):
        # Open and fresh, then the connection goes: the 20 s poll fails, and the bar says why
        # signing is not offered.
        ctx, page = new_page(browser, ada, clock=True)
        fixed_lists(page)
        page.route(detail_url, lambda r: rewritten(r))
        page.goto(BASE + "/" + QUERY)
        tabs_up(page)
        quiet(page)
        button(page, GENERAL).click()
        button(page, "Details").wait_for(timeout=60000)
        quiet(page)
        go_offline(page)
        page.clock.fast_forward(21_000)
        page.wait_for_timeout(500)
        page.clock.fast_forward(3_000)
        page.get_by_text(re.compile(r"^Signing needs a connection")).wait_for(timeout=30000)
        shot(page, name)
        ctx.close()

    def decision_summary_offline(name):
        # A restart with no connection, opening a decision from the cached queue: its summary,
        # and the full decision when back online (D5).
        ctx, page = new_page(browser, warm)
        go_offline(page)
        page.goto(BASE + "/" + QUERY)
        tabs_up(page)
        page.wait_for_timeout(1500)
        button(page, GENERAL).click()
        page.get_by_text(re.compile(r"^The full decision opens")).wait_for(timeout=30000)
        shot(page, name)
        ctx.close()

    def decision_checking(name):
        # The copy on the page is over a minute old (every fetch after the first hangs), so
        # Approve fetches again first: "Checking…".
        ctx, page = new_page(browser, ada, clock=True)
        fixed_lists(page)
        seen = {"n": 0}

        def detail(route):
            seen["n"] += 1
            if seen["n"] == 1:
                return rewritten(route)
            return None  # never answered

        page.route(detail_url, detail)
        page.goto(BASE + "/" + QUERY)
        tabs_up(page)
        quiet(page)
        button(page, GENERAL).click()
        button(page, "Details").wait_for(timeout=60000)
        page.wait_for_timeout(800)
        page.clock.fast_forward(61_000)
        page.wait_for_timeout(500)
        page.get_by_role("button", name=re.compile(r"^Approve")).last.click()
        page.get_by_text("Checking…").first.wait_for(timeout=15000)
        shot(page, name)
        ctx.close()

    def decision_changed(name):
        # I-16: the second fetch carries different signed text. The page says so, and shows
        # neither version as the decision.
        ctx, page = new_page(browser, ada, clock=True)
        fixed_lists(page)
        seen = {"n": 0}

        def swap(d):
            text = d["signing_inputs"]["action_text"] + " Also pay the contractors early."
            d["signing_inputs"]["action_text"] = text
            d["action_text"] = text

        def detail(route):
            seen["n"] += 1
            return rewritten(route, None if seen["n"] == 1 else swap)

        page.route(detail_url, detail)
        page.goto(BASE + "/" + QUERY)
        tabs_up(page)
        quiet(page)
        button(page, GENERAL).click()
        button(page, "Details").wait_for(timeout=60000)
        quiet(page)
        page.clock.fast_forward(21_000)
        page.get_by_text("The text changed while you were reading it.").first.wait_for(
            timeout=30000
        )
        quiet(page)
        shot(page, name)
        ctx.close()

    run("f01_approvals_offline", approvals_offline)
    run("f02_approvals_cold_start_", approvals_cold_start)
    run("f03_approvals_restored_offline", approvals_restored_offline)
    run("f04_decision_offline", decision_offline)
    run("f05_decision_summary_offline", decision_summary_offline)
    run("f06_decision_checking", decision_checking)
    run("f07_decision_changed", decision_changed)
    browser.close()

(OUT / "audit_fresh.json").write_text(
    json.dumps({**audit, "errors": errors}, indent=2), encoding="utf-8", newline="\n"
)
print(f"audit: {audit['checked']} targets checked, {len(audit['findings'])} findings")
for finding in audit["findings"]:
    print("  ", finding)
for e in errors:
    print("ERROR", e)
