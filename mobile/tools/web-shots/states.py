"""Web screenshot harness ONLY: every state of the Approvals tab and the decision screen (phone-ux
§6.3 to §6.7, §10.1 P2's "harness screens for all 17 decision states").

Usage: python states.py <harness origin> <out dir> <state dir> [theme] [font scale]

The demo database cannot hold every state at once, so each one is produced by intercepting the
API in the browser and rewriting the reply for one real decision. Only UNSIGNED fields are changed
(status, deadlines, votes, counts, `can_sign`, payout, the treasury's seat, the planned A1/R5
fields), so the phone's own integrity check still passes on every state that is meant to be
genuine. The tampered states change a signed field on purpose, the way a compromised server or
proxy would, and must show the failure. The database itself is never written.

Like shoot.py, any request that is not to the harness origin is aborted, and enrolled devices are
kept in the state folder (ada.json; dara.json, a viewer who is in no signed signer set).
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
QUERY = f"?theme={THEME}&fontScale={SCALE}"
OUT.mkdir(parents=True, exist_ok=True)
STATE.mkdir(parents=True, exist_ok=True)

W, H = 390, 844
PASSWORD = "demo-password-2026"
taken: list[str] = []
audit = {"checked": 0, "findings": []}
errors: list[str] = []

# Real decisions in the demo database (titles are unique there).
GENERAL = "Payroll adjustment schedule"  # Treasury vault, 2 of 3, signers Ada, Brij, Chen
LONG = "Decommission legacy reporting host"  # Production access, 3 of 5
PAYMENT = "Return 0.0001 ETH to the relayer"  # Treasury vault, a payment
OVER_180 = "Calderwood insurance renewal, 2027"  # Contracts, 2 of 4: signed text of 284 characters
EXTRA = ["Q4 cloud commitment", "Force password reset, finance group"]

ADA, BRIJ, CHEN = (1, "Ada Okafor"), (2, "Brij Mehta"), (3, "Chen Wei")
NOW = datetime.now(UTC)


def iso(delta: timedelta) -> str:
    return (NOW + delta).isoformat()


def later_today() -> timedelta:
    """Ahead of now, before local midnight: "due today" (the Waiting row's caption, §6.3 item 4)."""
    local = datetime.now().astimezone()
    midnight = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    left = midnight - local
    return max(min(timedelta(hours=4), left - timedelta(minutes=20)), timedelta(minutes=5))


AUDIT = """() => [...document.querySelectorAll('[data-hit-w]')]
  .filter((el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; })
  .map((el) => ({
    w: Number(el.dataset.hitW), h: Number(el.dataset.hitH),
    label: el.getAttribute('aria-label') || (el.textContent || '').trim().slice(0, 40),
    nested: !!(el.parentElement && el.parentElement.closest('[data-hit-w]')),
  }))"""

SCROLL_EXTRA = """() => {
  let el = document.elementFromPoint(innerWidth / 2, innerHeight / 2), extra = 0;
  for (; el; el = el.parentElement) {
    if (/(auto|scroll)/.test(getComputedStyle(el).overflowY)) {
      extra = Math.max(extra, el.scrollHeight - el.clientHeight);
    }
  }
  return extra;
}"""


# -- plumbing (as shoot.py) -------------------------------------------------------------------


def new_page(browser, state=None):
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


def shot(page, name, tall=False, wait_ms=500):
    page.wait_for_timeout(wait_ms)
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path))
    taken.append(path.name)
    print("shot", path.name, flush=True)
    for target in page.evaluate(AUDIT):
        audit["checked"] += 1
        if target["w"] < 48 or target["h"] < 48 or target["nested"]:
            audit["findings"].append({"screen": name, **target})
    if tall:
        height = H
        for _ in range(4):
            extra = page.evaluate(SCROLL_EXTRA)
            if extra <= 4:
                break
            height = min(height + extra, 9000)
            page.set_viewport_size({"width": W, "height": height})
            page.wait_for_timeout(700)
        if height > H:
            path = OUT / f"{name}_full.png"
            page.screenshot(path=str(path))
            taken.append(path.name)
            print("shot", path.name, f"({height}px)", flush=True)
        page.set_viewport_size({"width": W, "height": H})
        page.wait_for_timeout(400)


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


# -- the rewrites -----------------------------------------------------------------------------


def vote(who, decision, minutes_ago, custody="device", reason=None):
    return {
        "signer_id": who[0],
        "signer_name": who[1],
        "decision": decision,
        "custody": custody,
        "alg_id": "ML-DSA-65",
        "reason": reason,
        "signed_at": iso(timedelta(minutes=-minutes_ago)),
    }


def open_now(d, hours=5):
    """Open, before its deadline: unsigned fields only."""
    d.update(status="open", expires_at=iso(timedelta(hours=hours)), approvals=0, rejections=0)
    d.update(signed_by_me=False, can_sign=True, votes=[])
    if d.get("payout") is not None:
        d["payout"].update(
            state="awaiting_approvals",
            reason=None,
            tx_hash=None,
            block_number=None,
            gas_used=None,
            finished_at=None,
            execution_signatures=0,
        )


def with_votes(d, votes):
    d["votes"] = votes
    d["approvals"] = sum(v["decision"] == "approve" for v in votes)
    d["rejections"] = sum(v["decision"] == "reject" for v in votes)
    d["signed_by_me"] = any(v["signer_id"] == ADA[0] for v in votes)


def closed(d, status, votes):
    with_votes(d, votes)
    d.update(status=status, expires_at=iso(timedelta(days=1)), decided_at=iso(timedelta(hours=-2)))


def payout(d, state, **extra):
    d["payout"] = {
        "state": state,
        "reason": None,
        "tx_hash": None,
        "block_number": None,
        "gas_used": None,
        "execution_signatures": 2,
        "needed": 2,
        "finished_at": None,
        **extra,
    }


def summary_of(d):
    """A list summary carrying the same unsigned facts as the rewritten detail."""
    keys = (
        "proposal_uuid",
        "title",
        "vault_id",
        "vault_name",
        "status",
        "required_m",
        "required_n",
        "approvals",
        "rejections",
        "expires_at",
        "signed_by_me",
        "can_sign",
        "is_payment",
    )
    return {k: d.get(k) for k in keys}


# name -> (who, target title, rewrite(detail, ctx) or None, list rewrite or None)
def states(fp, other_fp):
    s = {}

    def needs(d, _):
        open_now(d)
        with_votes(d, [vote(BRIJ, "approve", 40, custody="server")])

    s["d01a_tampered_hash"] = (
        "ada",
        GENERAL,
        lambda d, _: (
            open_now(d),
            d["signing_inputs"].update(
                action_text=d["signing_inputs"]["action_text"].replace("adjustment", "bonus")
            ),
            d.update(action_text=d["signing_inputs"]["action_text"]),
        ),
    )
    s["d01b_tampered_display_text"] = (
        "ada",
        GENERAL,
        lambda d, _: (
            open_now(d),
            d.update(action_text=d["action_text"] + " Also pay the contractors early."),
        ),
    )
    s["d01c_tampered_policy"] = ("ada", GENERAL, lambda d, _: (open_now(d), d.update(required_m=1)))
    s["d02_needs_you"] = ("ada", GENERAL, needs)
    s["d02b_needs_you_long_text"] = ("ada", LONG, lambda d, _: open_now(d, hours=50))
    s["d02d_needs_you_text_over_180"] = (
        "ada",
        OVER_180,
        lambda d, _: (open_now(d, hours=50), with_votes(d, [vote(BRIJ, "approve", 90)])),
    )
    s["d02c_needs_you_payment"] = (
        "ada",
        PAYMENT,
        lambda d, _: (
            open_now(d),
            with_votes(d, [vote(BRIJ, "approve", 30)]),
            d["execution"].update(seat_fingerprint=fp),
        ),
    )
    s["d03_raised_it_separation"] = (
        "ada",
        GENERAL,
        lambda d, _: (
            open_now(d),
            d.update(raised_by={"id": ADA[0], "name": ADA[1]}, separation_of_duties=True),
        ),
    )
    s["d04_you_approved"] = (
        "ada",
        GENERAL,
        lambda d, _: (
            open_now(d),
            with_votes(d, [vote(ADA, "approve", 12)]),
            d.update(signers=[{"user_id": i, "name": n} for i, n in (ADA, BRIJ, CHEN)]),
        ),
    )
    s["d05_you_rejected"] = (
        "ada",
        GENERAL,
        lambda d, _: (
            open_now(d),
            with_votes(
                d,
                [
                    vote(
                        ADA,
                        "reject",
                        8,
                        reason="The schedule skips the March back pay; add it and raise it again.",
                    )
                ],
            ),
        ),
    )
    s["d06_not_an_approver"] = (
        "dara",
        GENERAL,
        lambda d, _: (
            open_now(d),
            with_votes(d, [vote(BRIJ, "approve", 40)]),
            d.update(can_sign=False),
        ),
    )
    s["d07a_payment_password_key"] = (
        "ada",
        PAYMENT,
        lambda d, _: (
            open_now(d),
            d["execution"].update(seat_fingerprint="0123456789abcdef"),
        ),
    )
    if other_fp:
        s["d07b_payment_other_phone"] = (
            "ada",
            PAYMENT,
            lambda d, _: (
                open_now(d),
                d["execution"].update(seat_fingerprint=other_fp),
            ),
        )
    s["d08_signer_but_server_says_no"] = (
        "ada",
        GENERAL,
        lambda d, _: (open_now(d), d.update(can_sign=False)),
    )
    s["d09_approved"] = (
        "ada",
        GENERAL,
        lambda d, _: closed(
            d,
            "approved",
            [vote(BRIJ, "approve", 300, custody="server"), vote(ADA, "approve", 130)],
        ),
    )
    s["d10a_payment_queued"] = (
        "ada",
        PAYMENT,
        lambda d, _: (
            closed(d, "approved", [vote(BRIJ, "approve", 30), vote(ADA, "approve", 3)]),
            payout(d, "queued"),
        ),
    )
    s["d10b_payment_submitting"] = (
        "ada",
        PAYMENT,
        lambda d, _: (
            closed(d, "approved", [vote(BRIJ, "approve", 30), vote(ADA, "approve", 3)]),
            payout(d, "submitting"),
        ),
    )
    s["d11_payment_paid"] = (
        "ada",
        PAYMENT,
        lambda d, _: (
            closed(d, "approved", [vote(BRIJ, "approve", 90), vote(ADA, "approve", 60)]),
            payout(
                d,
                "confirmed",
                tx_hash="0x" + "7c" * 32,
                block_number=9183301,
                gas_used=61234,
                finished_at=iso(timedelta(minutes=-55)),
            ),
        ),
    )
    s["d12a_payment_failed_balance"] = (
        "ada",
        PAYMENT,
        lambda d, _: (
            closed(d, "approved", [vote(BRIJ, "approve", 90), vote(ADA, "approve", 60)]),
            payout(d, "failed", reason="insufficient balance in treasury"),
        ),
    )
    s["d12b_payment_voided"] = (
        "ada",
        PAYMENT,
        lambda d, _: (
            closed(d, "approved", [vote(BRIJ, "approve", 90), vote(ADA, "approve", 60)]),
            payout(d, "voided", reason="config nonce moved"),
        ),
    )
    s["d13_rejected"] = (
        "ada",
        GENERAL,
        lambda d, _: closed(
            d,
            "rejected",
            [
                vote(BRIJ, "reject", 200, reason="Not agreed with payroll yet."),
                vote(
                    CHEN,
                    "reject",
                    150,
                    custody="server",
                    reason=(
                        "Needs more detail on the March figures, and the back pay schedule "
                        "should be attached before anyone signs this."
                    ),
                ),
            ],
        ),
    )
    s["d14_expired"] = (
        "ada",
        GENERAL,
        lambda d, _: (
            with_votes(d, [vote(ADA, "approve", 60 * 30)]),
            d.update(
                status="expired",
                expires_at=iso(timedelta(days=-1)),
                decided_at=iso(timedelta(days=-1)),
            ),
        ),
    )
    s["d15_withdrawn"] = (
        "ada",
        GENERAL,
        lambda d, _: (
            closed(d, "withdrawn", [vote(ADA, "approve", 200)]),
            d.update(
                withdrawn_by={"id": BRIJ[0], "name": BRIJ[1]}, withdrawn_at=iso(timedelta(hours=-1))
            ),
        ),
    )
    # Row 16: the queue still shows it open; the decision itself has closed.
    s["d16_closed_while_away"] = (
        "ada",
        GENERAL,
        lambda d, _: closed(
            d,
            "approved",
            [vote(BRIJ, "approve", 20), vote(CHEN, "approve", 4)],
        ),
    )
    s["d17_unknown_type"] = (
        "ada",
        GENERAL,
        lambda d, _: (
            needs(d, _),
            d.update(decision_type="board_resolution", template_version=7, type_fields={"x": 1}),
        ),
    )
    s["d18_unknown_status"] = (
        "ada",
        GENERAL,
        lambda d, _: (d.update(status="frozen", expires_at=iso(timedelta(days=1))),),
    )
    s["d19_many_voters"] = (
        "ada",
        LONG,
        lambda d, _: (
            open_now(d, hours=30),
            with_votes(
                d,
                [
                    vote((5, "Elif Demir"), "approve", 300),
                    vote(
                        (6, "Femi Adeyemi"),
                        "reject",
                        200,
                        reason="Keep it until the archive export is verified.",
                    ),
                    vote(BRIJ, "approve", 100, custody="server"),
                    vote(CHEN, "reject", 50, reason="Same as Femi."),
                ],
            ),
        ),
    )
    # More than four voters (a 3 of 5 rule can only have five once decided): three lines and
    # "See all 5" (§6.5 item 8), scrolled into view.
    s["d19b_who_decided_see_all"] = (
        "ada",
        LONG,
        lambda d, _: closed(
            d,
            "rejected",
            [
                vote((5, "Elif Demir"), "approve", 300),
                vote((6, "Femi Adeyemi"), "reject", 200, reason="Keep it until the export is verified."),
                vote(BRIJ, "approve", 100, custody="server"),
                vote(CHEN, "reject", 50, reason="Same as Femi."),
                vote((8, "Hassan Idris"), "reject", 10, reason="Not before the audit."),
            ],
        ),
    )
    return s


def detail_route(rewrite):
    def handle(route):
        resp = route.fetch()
        body = resp.json()
        prop = body.get("proposal")
        if prop is not None and rewrite is not None:
            rewrite(prop, "detail")
        route.fulfill(response=resp, json=body)

    return handle


# States that are closed when they are opened, which a person reaches from Activity, not the queue:
# opened from the queue, a closed decision is row 16 ("before you opened this") by design.
FROM_ACTIVITY = re.compile(r"^d(09|1[0-5]|19b)[a-z]?_")


def run_state(browser, name, state_file, title, rewrite, extra_sheet=None):
    target = None
    ctx, page = new_page(browser, state_file)
    all_list = api_get(state_file, "/api/v1/proposals?state=all")["proposals"]
    for p in all_list:
        if p["title"] == title:
            target = p
    if target is None:
        print("MISSING", title)
        ctx.close()
        return

    def awaiting(route):
        # The row must show in the queue, so the list says open; the decision's own reply says what
        # the state needs (for row 16, that it has closed since).
        summary = copy.deepcopy(target)
        summary.update(status="open", signed_by_me=False, can_sign=True, approvals=0, rejections=0)
        summary["expires_at"] = iso(timedelta(hours=5))
        route.fulfill(json={"ok": True, "state": "awaiting", "proposals": [summary]})

    page.route(re.compile(r".*/api/v1/proposals\?state=awaiting.*"), awaiting)
    if FROM_ACTIVITY.match(name):
        # Activity lists only this decision, so its row is the first.
        page.route(
            re.compile(r".*/api/v1/proposals\?state=all.*"),
            lambda r: r.fulfill(json={"ok": True, "state": "all", "proposals": [target]}),
        )
    page.route(
        re.compile(r".*/api/v1/proposals/" + target["proposal_uuid"] + r"$"), detail_route(rewrite)
    )
    page.goto(BASE + "/" + QUERY)
    page.get_by_role("tab", name=re.compile("^Account")).wait_for(timeout=90000)
    quiet(page)
    if FROM_ACTIVITY.match(name):
        page.get_by_role("tab", name=re.compile("^Activity")).first.click()
        quiet(page)
    button(page, title).click()
    button(page, "Details").wait_for(timeout=60000)
    quiet(page)
    if name.startswith("d19b_"):
        # First screen only, with the collapsed list and its "See all" in view.
        page.get_by_role("button", name=re.compile("^See all")).first.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
    shot(page, name)
    if extra_sheet:
        extra_sheet(page, name)
    ctx.close()


def evidence_sheets(page, name):
    button(page, "Checked on this phone").click()
    page.wait_for_timeout(900)
    shot(page, f"{name}__evidence_checks")
    page.get_by_role("tab", name="Hashes", exact=True).or_(
        page.get_by_role("radio", name="Hashes", exact=True)
    ).first.click()
    page.wait_for_timeout(500)
    shot(page, f"{name}__evidence_hashes")
    page.keyboard.press("Escape")
    page.mouse.click(W / 2, 8)
    page.wait_for_timeout(700)


def details_and_more(page, name):
    button(page, "Details").click()
    page.wait_for_timeout(900)
    shot(page, f"{name}__details")
    page.mouse.click(W / 2, 8)
    page.wait_for_timeout(700)
    button(page, "More options").click()
    page.wait_for_timeout(900)
    shot(page, f"{name}__more")
    page.mouse.click(W / 2, 8)
    page.wait_for_timeout(700)


def tampered_hashes(page, name):
    button(page, "More options").click()
    page.wait_for_timeout(900)
    button(page, "Technical details").click()
    page.wait_for_timeout(900)
    shot(page, f"{name}__evidence_hashes")


# -- the Approvals tab ------------------------------------------------------------------------


def approvals_states(browser, ada, fp):
    all_list = api_get(ada, "/api/v1/proposals?state=all")["proposals"]
    by_title = {p["title"]: p for p in all_list}
    pay = by_title[PAYMENT]

    def summary(title, hours, **extra):
        s = copy.deepcopy(by_title[title])
        s.update(status="open", signed_by_me=False, can_sign=True, approvals=0, rejections=0)
        s["expires_at"] = iso(timedelta(hours=hours)) if hours is not None else None
        s.update(extra)
        return s

    queue = [
        summary(GENERAL, 3, approvals=1),
        summary(LONG, 30),
        summary(EXTRA[0], 52),
        summary(EXTRA[1], None),
    ]
    web_pay = summary(PAYMENT, 20)
    waiting = [
        summary(
            "Aperture Media retainer",
            later_today().total_seconds() / 3600,
            signed_by_me=True,
            approvals=1,
        ),
        summary("Raise the API rate limit for Northwind", 70, signed_by_me=True, approvals=2),
    ]
    all_rewritten = queue + [web_pay] + waiting

    def seat_detail(seat):
        def rw(d, _ctx):
            open_now(d, hours=20)
            d["execution"]["seat_fingerprint"] = seat

        return rw

    def go(name, awaiting, all_props, seat=fp, tall=False, after=None, me_rewrite=None, fail=None):
        ctx, page = new_page(browser, ada)
        if fail == "abort":
            page.route(re.compile(r".*/api/v1/proposals\?state=.*"), lambda r: r.abort())
        elif fail == "hang":
            page.route(re.compile(r".*/api/v1/proposals\?state=.*"), lambda r: None)
        else:
            page.route(
                re.compile(r".*/api/v1/proposals\?state=awaiting.*"),
                lambda r: r.fulfill(json={"ok": True, "state": "awaiting", "proposals": awaiting}),
            )
            page.route(
                re.compile(r".*/api/v1/proposals\?state=all.*"),
                lambda r: r.fulfill(json={"ok": True, "state": "all", "proposals": all_props}),
            )
        page.route(
            re.compile(r".*/api/v1/proposals/" + pay["proposal_uuid"] + r"$"),
            detail_route(seat_detail(seat)),
        )
        if me_rewrite:

            def me(route):
                resp = route.fetch()
                body = resp.json()
                me_rewrite(body)
                route.fulfill(response=resp, json=body)

            page.route(re.compile(r".*/api/v1/me$"), me)
        page.goto(BASE + "/" + QUERY)
        page.get_by_role("tab", name=re.compile("^Account")).wait_for(timeout=90000)
        quiet(page)
        if fail == "abort":
            # Transport failures are retried before the page gives up.
            page.get_by_text("Can't check your approvals").wait_for(timeout=60000)
        page.wait_for_timeout(600 if fail != "hang" else 400)
        shot(page, name, tall=tall)
        if after:
            after(page)
        ctx.close()

    def open_waiting(page):
        button(page, "Waiting on others").click()
        page.wait_for_timeout(900)
        quiet(page)
        shot(page, "a07_waiting_on_others")

    go(
        "a01_approvals_with_web_group",
        queue + [web_pay],
        all_rewritten,
        seat="0123456789abcdef",
        after=open_waiting,
    )
    go("a02_approvals_payment_signable_here", queue[:2] + [web_pay], all_rewritten, seat=fp)
    go("a03_approvals_nothing_needs_you", [], waiting)
    go("a04_approvals_only_web", [web_pay], [web_pay], seat="0123456789abcdef")
    go("a05_approvals_failed", [], [], fail="abort")
    go("a06_approvals_loading", [], [], fail="hang", tall=False)
    go(
        "a08_approvals_removed_from_workspace",
        [],
        [],
        me_rewrite=lambda b: b.update(workspace=None),
    )


def decision_errors(browser, ada):
    all_list = api_get(ada, "/api/v1/proposals?state=all")["proposals"]
    target = next(p for p in all_list if p["title"] == GENERAL)
    summary = copy.deepcopy(target)
    summary.update(
        status="open", signed_by_me=False, can_sign=True, expires_at=iso(timedelta(hours=5))
    )
    for name, handler in (
        (
            "e01_decision_gone",
            lambda r: r.fulfill(
                status=404,
                json={"ok": False, "code": "unknown_proposal", "error": "No such proposal."},
            ),
        ),
        ("e02_decision_load_failed", lambda r: r.abort()),
        ("e03_decision_loading", lambda r: None),
    ):
        ctx, page = new_page(browser, ada)
        page.route(
            re.compile(r".*/api/v1/proposals\?state=awaiting.*"),
            lambda r: r.fulfill(json={"ok": True, "state": "awaiting", "proposals": [summary]}),
        )
        page.route(re.compile(r".*/api/v1/proposals/" + target["proposal_uuid"] + r"$"), handler)
        page.goto(BASE + "/" + QUERY)
        page.get_by_role("tab", name=re.compile("^Account")).wait_for(timeout=90000)
        quiet(page)
        button(page, GENERAL).click()
        if name == "e02_decision_load_failed":
            # Its list summary is in the queue, so the page shows it with the offline line (D5);
            # with no summary it is the "Can't load" banner.
            page.get_by_text("Can't load this decision.").or_(
                page.get_by_text("The full decision opens when you're back online.")
            ).first.wait_for(timeout=60000)
        page.wait_for_timeout(1200)
        shot(page, name)
        ctx.close()


# -- the run ----------------------------------------------------------------------------------

with sync_playwright() as p:
    browser = p.chromium.launch()
    ada, dara = STATE / "ada.json", STATE / "dara.json"
    enrol(browser, "ada@qvault.demo", ada)
    enrol(browser, "dara@qvault.demo", dara)
    fp = json.loads(local(ada, "qvault.device.identity.v1"))["fingerprint"]
    devices = api_get(ada, "/api/v1/devices")["devices"]
    other = next(
        (
            d["fingerprint"]
            for d in devices
            if not d["is_current"] and d["fingerprint"] and not d["revoked_at"]
        ),
        None,
    )

    only = set(sys.argv[6].split(",")) if len(sys.argv) > 6 else None
    extras = {
        "d02_needs_you": lambda page, name: (
            evidence_sheets(page, name),
            details_and_more(page, name),
        ),
        "d01a_tampered_hash": tampered_hashes,
        "d01c_tampered_policy": tampered_hashes,
        "d11_payment_paid": evidence_sheets,
    }
    for name, (who, title, rewrite) in states(fp, other).items():
        if only and name not in only:
            continue
        try:
            run_state(
                browser, name, ada if who == "ada" else dara, title, rewrite, extras.get(name)
            )
        except Exception as exc:  # one state failing must not hide the others
            errors.append(f"{name}: {exc}")
            print("FAILED", name, exc)
    if not only or "approvals" in only:
        approvals_states(browser, ada, fp)
    if not only or "errors" in only:
        decision_errors(browser, ada)
    browser.close()

(OUT / "audit.json").write_text(
    json.dumps({**audit, "errors": errors}, indent=2), encoding="utf-8", newline="\n"
)
print(f"audit: {audit['checked']} targets checked, {len(audit['findings'])} findings")
for finding in audit["findings"]:
    print("  ", finding)
for e in errors:
    print("ERROR", e)
