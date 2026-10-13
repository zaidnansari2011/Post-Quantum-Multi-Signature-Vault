"""Web screenshot harness ONLY: the P4b screens (phone-ux §6.3 item 5, §6.4, §6.12, §6.14, §6.18,
§6.19, §6.21; A12, A20, A21).

Usage: python p4b.py <harness origin> <out dir> <state dir> [theme] [font scale] [only,names]

Run from `mobile/` with the venv's Python, after (or instead of) p3.py with the same state dir: it
enrols Ada's two phones the same way when they are not there. The inbox is answered in the browser
(unsigned server copy, as notification_copy writes it), with its read state kept for the run; the
other states rewrite only UNSIGNED fields of real replies (`remind`, `my_key`, a treasury seat's
fingerprint, `push`). The one write that reaches the server is a rename it refuses (a hidden
character), so nothing is renamed. Any request that is not to the harness origin is aborted. The
same touch-target and overflow audits as p3.py run on every shot, and the run fails on any finding.
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
audit = {"checked": 0, "findings": [], "overflow": []}
errors: list[str] = []

TREASURY_VAULT = 1  # renamed "Operations" in the disposable copy (review B7), as is the workspace
TREASURY = "0xD49174b703d6FBC5088b0f01C6E71B5Ef467f3D0"
ADA, BRIJ, CHEN = (1, "Ada Okafor"), (2, "Brij Mehta"), (3, "Chen Wei")
GENERAL = "Payroll adjustment schedule"  # Treasury vault, 2 of 3
ACCESS_TITLE = "Temporary production read for incident 2214"

# Horizontal overflow (review B1): anything on screen that runs past either edge of the viewport,
# unless a scrolling or clipping container that itself fits holds it (a chip row that scrolls).
OVERFLOW = """() => {
  const W = innerWidth, H = innerHeight, out = [];
  if (document.scrollingElement.scrollWidth > W + 1) out.push({ what: 'page', width: document.scrollingElement.scrollWidth });
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0 || r.bottom <= 0 || r.top >= H) continue;
    if (r.right <= W + 1 && r.left >= -1) continue;
    let held = false;
    for (let p = el.parentElement; p; p = p.parentElement) {
      const cs = getComputedStyle(p), pr = p.getBoundingClientRect();
      if (/(auto|scroll|hidden|clip)/.test(cs.overflowX) && pr.right <= W + 1 && pr.left >= -1) { held = true; break; }
    }
    if (!held) out.push({ what: (el.textContent || el.tagName).trim().slice(0, 40), left: Math.round(r.left), right: Math.round(r.right) });
  }
  // A layout container whose content is wider than it: the browser scrolls it sideways when a field
  // inside is focused, shifting the whole form (what 2.0 text did to New decision).
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    // Not a field (its own text scrolls) and not text cut on purpose (an ellipsis, a line clamp).
    if (/^(INPUT|TEXTAREA)$/.test(el.tagName) || cs.textOverflow === 'ellipsis' || (cs.webkitLineClamp && cs.webkitLineClamp !== 'none')) continue;
    if (el.clientWidth >= 200 && !/(auto|scroll)/.test(cs.overflowX) && el.scrollWidth > el.clientWidth + 1) {
      const r = el.getBoundingClientRect();
      if (r.bottom > 0 && r.top < H) out.push({ what: 'container ' + (el.textContent || '').trim().slice(0, 30), scrollWidth: el.scrollWidth, clientWidth: el.clientWidth });
    }
  }
  return out.slice(0, 8);
}"""

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
    for over in page.evaluate(OVERFLOW):
        audit["overflow"].append({"screen": name, **over})


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
    page.get_by_role("tab", name=re.compile("^Account")).or_(
        button(page, "More options")
    ).first.wait_for(timeout=90000)
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


# -- P4b: the inbox, Remind's next time, rename, the treasury a key is on, last signed ----------

UPDATES = "/api/v1/notifications?section=updates"


def inbox_items(ada2_id, general_uuid):
    """For you as a person would find it after a morning away: a security alert, three unread
    updates, and older ones read. Unsigned server copy, written as notification_copy writes it."""

    def item(nid, kind, title, body, hours, **over):
        base = {
            "id": nid,
            "kind": kind,
            "section": "updates",
            "title": title,
            "body": body,
            "path": "/",
            "actionable": False,
            "security": kind in ("device_enrolled", "password_changed"),
            "unread": False,
            "created_at": iso(timedelta(hours=-hours)),
            "read_at": None,
            "archived_at": None,
            "actor": None,
            "vault": None,
            "proposal_uuid": None,
            "device_id": None,
        }
        base["archivable"] = not base["security"]
        base.update(over)
        return base

    ops = {"id": 1, "name": "Operations"}
    return [
        item(
            901,
            "device_enrolled",
            "A new device can sign for you",
            "Ada's second phone was enrolled today. If this wasn't you, change your password now.",
            0.4,
            unread=True,
            actor={"id": ADA[0], "display_name": ADA[1]},
            device_id=ada2_id,
        ),
        item(
            902,
            "decision_approved",
            "Your decision was approved",
            f"{GENERAL}, in Operations.",
            0.7,
            unread=True,
            actor={"id": BRIJ[0], "display_name": BRIJ[1]},
            vault=ops,
            proposal_uuid=general_uuid,
        ),
        item(
            903,
            "decision_rejected",
            "A decision you voted on was rejected",
            "Rotate the staging signing keys, in Incident response. Reason from Chen Wei: The "
            "window clashes with the release freeze.",
            1.5,
            unread=True,
            actor={"id": CHEN[0], "display_name": CHEN[1]},
            vault={"id": 2, "name": "Incident response"},
            proposal_uuid=general_uuid,
        ),
        item(
            904,
            "decision_mentioned",
            "Brij Mehta mentioned you",
            f"{GENERAL}, in Operations. In its discussion, which isn't part of what is signed.",
            26,
            actor={"id": BRIJ[0], "display_name": BRIJ[1]},
            vault=ops,
            proposal_uuid=general_uuid,
        ),
        item(
            905,
            "vault_member_added",
            "Ada Okafor added you to Release approvals",
            "You can approve decisions raised from now on. Any 2 of 3 approvers decide.",
            74,
            actor={"id": ADA[0], "display_name": ADA[1]},
            vault={"id": 6, "name": "Release approvals"},
        ),
        item(
            906,
            "vault_rule_changed",
            "The treasury for Operations was updated",
            "It now matches the vault: payments need any 2 of 3 approvers.",
            200,
            vault=ops,
        ),
        item(
            907,
            "password_changed",
            "Your password was changed",
            "Your signing keys now open with the new password only.",
            260,
            actor={"id": ADA[0], "display_name": ADA[1]},
        ),
    ]


def inbox_routes(items, failing=False):
    """The inbox answered in the browser, with its read state kept for the run: reading, archiving
    and marking all read change what the next fetch returns, as the server would."""
    state = {i["id"]: dict(i) for i in items}

    def counts():
        n = sum(1 for i in state.values() if i["unread"] and i["archived_at"] is None)
        return {"needs_you": 0, "updates": n, "total": n}

    def listing(route):
        if failing:
            return route.fulfill(
                status=500, json={"ok": False, "code": "server_error", "error": "Server error."}
            )
        shown = [i for i in state.values() if i["archived_at"] is None]
        return route.fulfill(
            json={
                "ok": True,
                "section": "updates",
                "page": 1,
                "per_page": 100,
                "total": len(shown),
                "has_more": False,
                "notifications": shown,
                "unread": counts(),
            }
        )

    def unread(route):
        route.fulfill(json={"ok": True, "unread": counts()})

    def one(route):
        nid = int(re.search(r"/notifications/(\d+)/", route.request.url).group(1))
        i = state[nid]
        if route.request.url.endswith("/archive") and i["security"]:
            # As the server does: a security notice stays in the inbox.
            return route.fulfill(
                status=409,
                json={
                    "ok": False,
                    "code": "not_archivable",
                    "error": "Security notices stay in your inbox.",
                },
            )
        i["unread"] = False
        if route.request.url.endswith("/archive"):
            i["archived_at"] = iso(timedelta(0))
            i["section"] = "archived"
        route.fulfill(json={"ok": True, "notification": i, "unread": counts()})

    def read_all(route):
        marked = 0
        for i in state.values():
            if i["unread"]:
                i["unread"] = False
                marked += 1
        route.fulfill(json={"ok": True, "marked": marked, "unread": counts()})

    return [
        (r".*/api/v1/notifications\?section=updates.*", listing),
        (r".*/api/v1/notifications/unread$", unread),
        (r".*/api/v1/notifications/\d+/(read|archive)$", one),
        (r".*/api/v1/notifications/read-all$", read_all),
    ]


def seat_for(fingerprint, custody="device"):
    """Operations' treasury holds `fingerprint` for Ada (A20/A21); every other vault has none."""

    def handle(route):
        resp = route.fetch()
        body = resp.json()
        if f"/vaults/{TREASURY_VAULT}/" in route.request.url:
            t = body.get("treasury") or {
                "address": TREASURY,
                "chain_id": 11155111,
                "threshold_m": 2,
                "signer_count": 3,
                "linked_at": iso(timedelta(days=-3)),
                "signers": [],
            }
            t["signers"] = [
                {
                    "user_id": ADA[0],
                    "custody": custody,
                    "key_active": True,
                    "key_fingerprint": fingerprint,
                }
            ] + [dict(s, key_fingerprint=None) for s in t["signers"] if s["user_id"] != ADA[0]]
            body["treasury"] = t
        else:
            body["treasury"] = None
        route.fulfill(response=resp, json=body)

    return (r".*/api/v1/vaults/\d+/treasury$", handle)


def segment(page, name):
    page.get_by_role("tab", name=name, exact=True).or_(
        page.get_by_role("radio", name=name, exact=True)
    ).first.click()
    page.wait_for_timeout(500)
    quiet(page)


def p4b_tour(browser, ada, ada2_id, ada2_fp, ada_fp):
    everything = api(ada, "/api/v1/proposals?state=all")["proposals"]
    general = {p["title"]: p for p in everything}[GENERAL]
    items = inbox_items(ada2_id, general["proposal_uuid"])

    # Activity, For you (§6.12).
    def for_you(page, _link):
        open_app(page)
        tab(page, "Activity")
        page.get_by_text("A new device can sign for you").first.wait_for(timeout=60000)
        quiet(page)
        shot(page, "ac10_for_you")
        # The swipe (Mark read, Archive) is not shot: react-native-web turns a mouse drag into a
        # press, so the row opens. It is a handset check (OWNER-ACTIONS 3.5); the same actions are
        # the row's accessibility actions.
        button(page, "Mark all read").click()
        page.wait_for_timeout(500)
        shot(page, "ac12_marked_all_read", wait_ms=150)
        segment(page, "Yours")
        # Past the toast from "Mark all read", which would cover a row.
        page.get_by_text("All marked read").wait_for(state="hidden", timeout=15000)
        shot(page, "ac16_yours_with_your_vote")

    run(browser, ada, "ac1", for_you, routes=inbox_routes(items) + [seat_for(ada2_fp)])

    # "Not you? Remove that device": Other devices, with that device's remove sheet open, naming
    # the treasury that holds its key.
    def not_you(page, _link):
        open_app(page)
        tab(page, "Activity")
        page.get_by_text("A new device can sign for you").first.wait_for(timeout=60000)
        quiet(page)
        button(page, "Not you? Remove that device").click()
        page.get_by_text("Its key stops signing at once").first.wait_for(timeout=60000)
        quiet(page, settle_ms=1200)
        shot(page, "ac15_not_you_remove_sheet")

    run(browser, ada, "ac15", not_you, routes=inbox_routes(items) + [seat_for(ada2_fp)])

    def empty(page, _link):
        open_app(page)
        tab(page, "Activity")
        page.get_by_text("You're up to date.").first.wait_for(timeout=60000)
        shot(page, "ac13_for_you_empty")

    run(browser, ada, "ac13", empty, routes=inbox_routes([]))

    def failed(page, _link):
        open_app(page)
        tab(page, "Activity")
        page.get_by_text("Can't load your updates").first.wait_for(timeout=60000)
        shot(page, "ac14_for_you_failed")

    run(browser, ada, "ac14", failed, routes=inbox_routes(items, failing=True))

    # Approvals: notifications are off (§6.3 item 5), linking to Account, Notifications.
    def off(page, _link):
        open_app(page)
        line = page.get_by_text("Notifications are off").first
        line.wait_for(timeout=60000)
        line.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
        shot(page, "a13_approvals_notifications_off")
        button(page, "Turn on notifications").click()
        page.wait_for_timeout(900)
        quiet(page)
        shot(page, "a13b_turn_on_leads_to_notifications")

    run(
        browser,
        ada,
        "a13",
        off,
        routes=[
            rewrite(
                r".*/api/v1/me$",
                lambda b: b.update(push={"available": True, "registered": False}),
            ),
            rewrite(
                r".*/api/v1/me/notification-settings$",
                lambda b: b["push"].update(available=True, registered=False),
            ),
        ],
        init=[
            "localStorage.setItem('webshots.securestore.qvault.harness.push.permission', 'denied');"
        ],
    )

    # Remind, sent: the row and the decision wait, and say when (§6.4, §6.21; A12).
    sent = {
        "offered": True,
        "allowed": False,
        "last_sent_at": iso(timedelta(hours=-2)),
        "next_allowed_at": iso(timedelta(hours=22)),
    }

    def waiting_list(body):
        base = copy.deepcopy(general)
        mine = dict(
            base,
            proposal_uuid="11111111-1111-4111-8111-111111111111",
            title="Rotate the on-call paging credentials",
            status="open",
            expires_at=iso(timedelta(hours=30)),
            signed_by_me=False,
            can_sign=False,
            approvals=1,
            raised_by={"id": ADA[0], "name": ADA[1]},
            can_still_approve=[BRIJ[0], CHEN[0]],
            can_still_pass=True,
            signers=[{"user_id": i, "name": n} for i, n in (ADA, BRIJ, CHEN)],
            remind=sent,
        )
        body["proposals"] = [mine]

    def waiting(page, _link):
        open_app(page)
        button(page, "Waiting on others").click()
        page.wait_for_timeout(900)
        quiet(page)
        shot(page, "a14_waiting_reminded_next_time")

    run(
        browser,
        ada,
        "a14",
        waiting,
        routes=[rewrite(r".*/api/v1/proposals\?state=all.*", waiting_list)],
    )

    def as_raiser(body):
        d = body.get("proposal") or {}
        d.update(status="open", expires_at=iso(timedelta(hours=5)), approvals=0, rejections=0)
        d.update(signed_by_me=False, can_sign=False, votes=[], my_vote=None)
        d.update(
            raised_by={"id": ADA[0], "name": ADA[1]},
            separation_of_duties=True,
            signers=[{"user_id": i, "name": n} for i, n in (ADA, BRIJ, CHEN)],
            can_withdraw=True,
            remind=sent,
        )

    def remind_waits(page, _link):
        open_app(page, f"qvault://decision/{general['proposal_uuid']}")
        button(page, "Details").wait_for(timeout=60000)
        quiet(page)
        shot(page, "d27_remind_waits_until_tomorrow")

    run(
        browser,
        ada,
        "d27",
        remind_waits,
        routes=[rewrite(r".*/api/v1/proposals/" + general["proposal_uuid"] + r"$", as_raiser)],
    )

    # This phone: the name with Change; the rename sheet; a hidden character refused by the
    # server in its own words (§6.18, A21). Nothing is renamed: the one name sent is refused.
    hidden = "Ada" + chr(0x202E) + "s phone"

    def rename(page, _link):
        open_app(page)
        tab(page, "Account")
        button(page, "This phone").click()
        page.wait_for_timeout(900)
        quiet(page)
        shot(page, "acc10_this_phone_with_change")
        button(page, "Change this phone's name").click()
        page.wait_for_timeout(900)
        shot(page, "acc11_rename_sheet")
        page.get_by_role("textbox", name="Name").fill(hidden)
        button(page, "Save name").click()
        page.get_by_text("hidden characters").first.wait_for(timeout=60000)
        page.wait_for_timeout(400)
        shot(page, "acc12_rename_refused_hidden_character")

    run(browser, ada, "acc1", rename)

    # Other devices: a device's sheet with Rename; Remove this phone naming the treasury that
    # holds this phone's key (§6.19), matched by its fingerprint.
    def devices(page, _link):
        open_app(page)
        tab(page, "Account")
        button(page, "Other devices").click()
        page.wait_for_timeout(900)
        quiet(page)
        page.get_by_role("button", name=re.compile("^Ada.s second phone")).first.click()
        page.wait_for_timeout(900)
        shot(page, "acc13_device_sheet_with_rename")

    run(browser, ada, "acc13", devices)

    def remove_this(page, _link):
        open_app(page)
        tab(page, "Account")
        button(page, "This phone").click()
        page.wait_for_timeout(900)
        quiet(page)
        button(page, "Remove this phone").click()
        page.get_by_text("holds this phone's key").first.wait_for(timeout=60000)
        page.wait_for_timeout(600)
        shot(page, "acc14_remove_this_phone_names_treasury")

    run(
        browser,
        ada,
        "acc14",
        remove_this,
        routes=[
            rewrite(
                r".*/api/v1/me$",
                lambda b: b.update(my_key={"custody": "device", "key_id": 1, "usable": True}),
            ),
            seat_for(ada_fp),
        ],
    )

    # The members sheet with "Last signed" from the server (A21), real votes in the demo data.
    def members(page, _link):
        open_app(page)
        tab(page, "Vaults")
        button(page, "Operations").click()
        page.get_by_text("Members", exact=True).first.wait_for(timeout=60000)
        quiet(page, settle_ms=1200)
        button(page, "Members").click()
        page.wait_for_timeout(900)
        shot(page, "v07_members_last_signed")

    run(browser, ada, "v07", members)


with sync_playwright() as p:
    browser = p.chromium.launch()
    ada, ada2 = STATE / "ada.json", STATE / "ada2.json"
    enrol(browser, "ada@qvault.demo", ada)
    if not ada2.exists():
        # A second phone of Ada's, so Other devices has one to remove and rename.
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
    ada_fp = json.loads(local(ada, "qvault.device.identity.v1"))["fingerprint"]
    ada2_fp = json.loads(local(ada2, "qvault.device.identity.v1"))["fingerprint"]
    second = next(d for d in api(ada, "/api/v1/devices")["devices"] if d["fingerprint"] == ada2_fp)
    p4b_tour(browser, ada, second["id"], ada2_fp, ada_fp)
    browser.close()

(OUT / "audit_p4b.json").write_text(
    json.dumps({**audit, "errors": errors}, indent=2), encoding="utf-8", newline="\n"
)
print(
    f"audit: {audit['checked']} targets checked, {len(audit['findings'])} findings, {len(audit['overflow'])} overflowing"
)
for over in audit["overflow"]:
    print("   OVERFLOW", over)
for finding in audit["findings"]:
    print("  ", finding)
for e in errors:
    print("ERROR", e)
if audit["findings"] or audit["overflow"] or errors:
    sys.exit(1)
