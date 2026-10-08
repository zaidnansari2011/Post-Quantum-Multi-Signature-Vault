"""Web screenshot harness ONLY: the signing step (phone-ux §6.8 to §6.11, §6.19, §6.20, §2.4).

Usage: python signing.py <harness origin> <out dir> <state dir> [theme] [font scale] [only,names]

Like states.py, each state is one real decision whose reply is rewritten in the browser, changing
only UNSIGNED fields, so the phone's own checks pass. Signing is real up to the network: the app
derives the hash, prompts (the harness shim passes), signs with ML-DSA and verifies its own
signature; the vote POST is then answered here, never by the server, with the digest of the
signature the app actually sent, so the database is never written. A revoke request is always
aborted, so "Remove this phone" can never remove the enrolled harness device.

Uses the devices states.py enrolled (ada.json in the state folder).
"""

import base64
import copy
import hashlib
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

W, H = 390, 844
audit = {"checked": 0, "findings": []}
errors: list[str] = []

GENERAL = "Payroll adjustment schedule"  # Treasury vault, 2 of 3, signers Ada, Brij, Chen
LONG = "Decommission legacy reporting host"
PAYMENT = "Return 0.0001 ETH to the relayer"
ADA, BRIJ, CHEN = (1, "Ada Okafor"), (2, "Brij Mehta"), (3, "Chen Wei")
NOW = datetime.now(UTC)
PASSWORD_KEY = "0123456789abcdef"

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


def new_page(browser, state):
    ctx = browser.new_context(
        viewport={"width": W, "height": H}, device_scale_factor=2, storage_state=str(state)
    )
    page = ctx.new_page()
    inflight = {"n": 0}

    def guard(route):
        if route.request.url.startswith(BASE):
            # Never let the harness remove its own enrolled device from the database copy.
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
    return page.get_by_role("button", name=re.compile("^" + re.escape(name) + r"($|\.|,)")).last


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


# -- rewrites of unsigned fields (as states.py) -----------------------------------------------


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
    d.update(status="open", expires_at=iso(timedelta(hours=hours)), approvals=0, rejections=0)
    d.update(signed_by_me=False, can_sign=True, votes=[])
    if d.get("payout") is not None:
        d["payout"].update(state="awaiting_approvals", reason=None, tx_hash=None, finished_at=None)


def with_votes(d, votes):
    d["votes"] = votes
    d["approvals"] = sum(v["decision"] == "approve" for v in votes)
    d["rejections"] = sum(v["decision"] == "reject" for v in votes)
    d["signed_by_me"] = any(v["signer_id"] == ADA[0] for v in votes)


def summary(p, hours=5, **extra):
    s = copy.deepcopy(p)
    s.update(status="open", signed_by_me=False, can_sign=True, approvals=0, rejections=0)
    s["expires_at"] = iso(timedelta(hours=hours))
    s.update(extra)
    return s


def detail_route(rewrite):
    def handle(route):
        resp = route.fetch()
        body = resp.json()
        if body.get("proposal") is not None:
            rewrite(body["proposal"])
        route.fulfill(response=resp, json=body)

    return handle


def vote_answer(result):
    """Answer the vote POST here, with the digests of what the app really sent."""

    def handle(route):
        if route.request.method != "POST":
            return route.fallback()
        if result == "abort":
            return route.abort()
        body = json.loads(route.request.post_data or "{}")
        if isinstance(result, tuple) and result[0] == "error":
            _, status, code = result
            return route.fulfill(status=status, json={"ok": False, "code": code, "error": "x"})
        sig = base64.b64decode(body["signature_b64"])
        ex = body.get("execution_signature_b64")
        status, approvals, rejections = result(body["decision"])
        route.fulfill(
            json={
                "ok": True,
                "vote": {
                    "id": 1,
                    "decision": body["decision"],
                    "custody": "device",
                    "alg_id": "ML-DSA-65",
                    "signature_sha256": hashlib.sha256(sig).hexdigest(),
                    "execution_signature_sha256": (
                        hashlib.sha256(base64.b64decode(ex)).hexdigest() if ex else None
                    ),
                    "signed_at": iso(timedelta()),
                },
                "proposal": {"status": status, "approvals": approvals, "rejections": rejections},
            }
        )

    return handle


# -- the run ----------------------------------------------------------------------------------


def go(
    browser,
    ada,
    name,
    target,
    rewrite,
    steps,
    awaiting=None,
    link=None,
    extra_routes=None,
    auth=None,
    drop_seed=False,
):
    """`auth`: the harness prompt's answer ('cancel', 'lockout', 'nolock'); `drop_seed`: the
    keystore has lost the seed (§6.20's key missing). Both set before the app's scripts run."""
    if ONLY and name not in ONLY:
        return
    ctx, page = new_page(browser, ada)
    try:
        if auth:
            page.add_init_script(f"localStorage.setItem('webshots.auth', {json.dumps(auth)});")
        if drop_seed:
            page.add_init_script(
                "localStorage.removeItem('webshots.securestore.qvault.device.seed.v1');"
            )
        queue = awaiting if awaiting is not None else [summary(target)]
        page.route(
            re.compile(r".*/api/v1/proposals\?state=awaiting.*"),
            lambda r: r.fulfill(json={"ok": True, "state": "awaiting", "proposals": queue}),
        )
        page.route(
            re.compile(r".*/api/v1/proposals/" + target["proposal_uuid"] + r"$"),
            detail_route(rewrite),
        )
        for pattern, handler in extra_routes or []:
            page.route(re.compile(pattern), handler)
        url = BASE + "/" + QUERY + (f"&link={link}" if link else "")
        page.goto(url)
        # The tabs; or, when a link opened a decision over them, the decision; or Session ended.
        page.get_by_role("tab", name=re.compile("^Account")).or_(
            page.get_by_text("Set up this phone again")
        ).or_(button(page, "Details")).first.wait_for(timeout=90000)
        quiet(page)
        steps(page)
    except Exception as exc:  # one state failing must not hide the others
        errors.append(f"{name}: {exc}")
        print("FAILED", name, exc)
    finally:
        ctx.close()


with sync_playwright() as p:
    browser = p.chromium.launch()
    ada = STATE / "ada.json"
    fp = json.loads(local(ada, "qvault.device.identity.v1"))["fingerprint"]
    everything = api_get(ada, "/api/v1/proposals?state=all")["proposals"]
    by_title = {x["title"]: x for x in everything}
    general, payment, long_ = by_title[GENERAL], by_title[PAYMENT], by_title[LONG]
    vault_ids = {x["vault_id"] for x in everything}

    def needs(d):
        open_now(d)
        with_votes(d, [vote(BRIJ, "approve", 40, custody="server")])
        d["signers"] = [{"user_id": i, "name": n} for i, n in (ADA, BRIJ, CHEN)]

    def fresh(d):
        open_now(d)
        d["signers"] = [{"user_id": i, "name": n} for i, n in (ADA, BRIJ, CHEN)]

    def pay(seat):
        def rw(d):
            open_now(d)
            with_votes(d, [vote(BRIJ, "approve", 30)])
            d["execution"]["seat_fingerprint"] = seat
            d["raised_by"] = {"id": CHEN[0], "name": CHEN[1]}

        return rw

    def open_decision(page, title):
        button(page, title).click()
        button(page, "Details").wait_for(timeout=60000)
        quiet(page)

    def sign(page, label):
        page.get_by_role("button", name=re.compile(r"^" + re.escape(label))).last.click()

    queue_two = [summary(general, 3), summary(long_, 30)]

    # The approve sheet: general, with its code page; a payment; the web handoff.
    def s01(page):
        open_decision(page, GENERAL)
        button(page, "Approve").click()
        shot(page, "s01_approve_sheet")
        button(page, "About the decision code").click()
        shot(page, "s01b_code_about")

    go(browser, ada, "s01_approve_sheet", general, needs, s01)

    def s02(page):
        open_decision(page, PAYMENT)
        button(page, "Approve").click()
        shot(page, "s02_approve_sheet_payment")

    go(browser, ada, "s02_approve_sheet_payment", payment, pay(fp), s02)

    def s03(page):
        button(page, "Details").wait_for(timeout=60000)
        quiet(page)
        button(page, "Approve").click()
        shot(page, "s03_approve_sheet_web_handoff")

    go(
        browser,
        ada,
        "s03_approve_sheet_web_handoff",
        general,
        needs,
        s03,
        link=f"qvault://decision/{general['proposal_uuid']}?via=web",
    )

    # The reject sheet: a payment (its reason missing on submit), and a general decision with a chip.
    def s04(page):
        open_decision(page, PAYMENT)
        button(page, "Reject").click()
        shot(page, "s04_reject_sheet_payment")
        sign(page, "Sign rejection")
        shot(page, "s04b_reject_reason_missing")

    go(browser, ada, "s04_reject_sheet_payment", payment, pay(PASSWORD_KEY), s04)

    def s05(page):
        open_decision(page, GENERAL)
        button(page, "Reject").click()
        page.get_by_role("radio", name="Not agreed").click()
        shot(page, "s05_reject_sheet_chip")

    go(browser, ada, "s05_reject_sheet_chip", general, fresh, s05)

    # The acknowledgement, from a real signature answered here.
    def signs(label, sheet_button, name, chip=None):
        def run(page):
            open_decision(page, GENERAL)
            button(page, label).click()
            page.wait_for_timeout(700)
            if chip:
                page.get_by_role("radio", name=chip).click()
            sign(page, sheet_button)
            page.wait_for_timeout(2500)
            quiet(page)
            shot(page, name, wait_ms=1500)

        return run

    go(
        browser,
        ada,
        "s06_ack_approval_signed_next",
        general,
        fresh,
        signs("Approve", "Sign with", "s06_ack_approval_signed_next"),
        awaiting=queue_two,
        extra_routes=[(r".*/vote$", vote_answer(lambda _d: ("open", 1, 0)))],
    )
    go(
        browser,
        ada,
        "s07_ack_decision_approved",
        general,
        needs,
        signs("Approve", "Sign with", "s07_ack_decision_approved"),
        extra_routes=[(r".*/vote$", vote_answer(lambda _d: ("approved", 2, 0)))],
    )
    go(
        browser,
        ada,
        "s08_ack_rejection_signed",
        general,
        fresh,
        signs("Reject", "Sign rejection", "s08_ack_rejection_signed", chip="Not agreed"),
        extra_routes=[(r".*/vote$", vote_answer(lambda _d: ("open", 0, 1)))],
    )

    # Failures. The vote is sent and no answer comes back: the sheet says Q-Vault may have it and
    # asks again (held here, to shoot "Checking…"), then says what Q-Vault's own record shows.
    sent = {"voted": False, "held": []}

    def vote_lost(route):
        if route.request.method != "POST":
            return route.fallback()
        sent["voted"] = True
        route.abort()

    def detail_after_vote(route):
        if not sent["voted"]:
            return route.fallback()
        sent["held"].append(route)

    def transport(page):
        open_decision(page, GENERAL)
        button(page, "Approve").click()
        page.wait_for_timeout(700)
        sign(page, "Sign with")
        page.wait_for_timeout(1500)
        shot(page, "s09a_sign_unanswered_checking", wait_ms=300)
        for route in sent["held"]:
            resp = route.fetch()
            body = resp.json()
            needs(body["proposal"])
            route.fulfill(response=resp, json=body)
        sent["held"].clear()
        sent["voted"] = False
        page.wait_for_timeout(1200)
        quiet(page)
        shot(page, "s09_sign_failed_transport")

    go(
        browser,
        ada,
        "s09_sign_failed_transport",
        general,
        needs,
        transport,
        extra_routes=[
            (r".*/vote$", vote_lost),
            (r".*/api/v1/proposals/" + general["proposal_uuid"] + "$", detail_after_vote),
        ],
    )

    # The prompt cancelled; locked out; no screen lock at all; then the server's refusals.
    def fails(name, label="Approve", sheet_button="Sign"):
        def run(page):
            open_decision(page, GENERAL)
            button(page, label).click()
            page.wait_for_timeout(700)
            sign(page, sheet_button)
            page.wait_for_timeout(2000)
            quiet(page)
            shot(page, name, wait_ms=800)

        return run

    for name, auth in (
        ("x01_biometric_cancelled", "cancel"),
        ("x02_biometric_locked", "lockout"),
        ("x03_no_screen_lock", "nolock"),
    ):
        go(browser, ada, name, general, needs, fails(name), auth=auth)
    for name, answer in (
        ("x04_chain_unavailable", ("error", 503, "chain_unavailable")),
        ("x05_not_a_signer", ("error", 403, "not_a_signer")),
        ("x06_key_cant_sign_banner", ("error", 403, "device_key_not_active")),
    ):
        go(
            browser,
            ada,
            name,
            general,
            needs,
            fails(name),
            extra_routes=[(r".*/vote$", vote_answer(answer))],
        )

    # The banner's "Set up this phone again": the ended screen for a key the server refused.
    def key_unusable(page):
        open_decision(page, GENERAL)
        button(page, "Approve").click()
        page.wait_for_timeout(700)
        sign(page, "Sign")
        page.get_by_role("button", name="Set up this phone again").first.wait_for(timeout=60000)
        page.get_by_role("button", name="Set up this phone again").first.click()
        page.get_by_text("Q-Vault didn't accept a signature from it").wait_for(timeout=30000)
        shot(page, "x07_ended_key_unusable")

    go(
        browser,
        ada,
        "x07_ended_key_unusable",
        general,
        needs,
        key_unusable,
        extra_routes=[(r".*/vote$", vote_answer(("error", 403, "device_key_not_active")))],
    )

    closed_now = {"closed": False}

    def maybe_closed(d):
        needs(d)
        if closed_now["closed"]:
            with_votes(d, [vote(BRIJ, "approve", 40), vote(CHEN, "approve", 1)])
            d.update(status="approved", decided_at=iso(timedelta(minutes=-1)))

    def closing_vote(route):
        if route.request.method != "POST":
            return route.fallback()
        closed_now["closed"] = True
        route.fulfill(status=409, json={"ok": False, "code": "proposal_closed", "error": "x"})

    go(
        browser,
        ada,
        "s10_closed_before_signature",
        general,
        maybe_closed,
        signs("Approve", "Sign with", "s10_closed_before_signature"),
        extra_routes=[(r".*/vote$", closing_vote)],
    )

    # Approvals: payments this phone can't sign, grouped by where they can be approved.
    pay_password = summary(payment, 20)
    pay_none = summary(payment, 26, proposal_uuid="00000000-0000-4000-8000-00000000a002")
    pay_none["title"] = "Refund the hosting deposit"

    def clone_payment(uuid, seat):
        def handle(route):
            real = api_get(ada, f"/api/v1/proposals/{payment['proposal_uuid']}")
            d = real["proposal"]
            open_now(d, hours=26)
            d["proposal_uuid"] = uuid
            d["title"] = "Refund the hosting deposit"
            d["execution"]["seat_fingerprint"] = seat
            route.fulfill(json=real)

        return handle

    def approvals_groups(page):
        page.wait_for_timeout(1500)
        quiet(page)
        shot(page, "a09_approvals_cant_sign_here")

    go(
        browser,
        ada,
        "a09_approvals_cant_sign_here",
        payment,
        pay(PASSWORD_KEY),
        approvals_groups,
        awaiting=[summary(general, 3), pay_password, pay_none],
        extra_routes=[(r".*/api/v1/proposals/" + pay_none["proposal_uuid"] + "$", clone_payment(pay_none["proposal_uuid"], None))],
    )

    # Session ended: every request answered 401, as the server does for an expired token.
    def ended(page):
        page.get_by_text("Set up this phone again").first.wait_for(timeout=60000)
        shot(page, "s11_session_ended")

    go(
        browser,
        ada,
        "s11_session_ended",
        general,
        needs,
        ended,
        extra_routes=[
            (
                r".*/api/v1/(me|devices|vaults|proposals).*",
                lambda r: r.fulfill(status=401, json={"ok": False, "code": "token_invalid", "error": "x"}),
            )
        ],
    )

    # The other endings (§6.20): a removal the server names (A9's device_revoked, answered here),
    # and a keystore that lost the seed while the phone stayed enrolled.
    def ended_as(name):
        def run(page):
            page.get_by_text("Set up this phone again").first.wait_for(timeout=60000)
            shot(page, name)

        return run

    go(
        browser,
        ada,
        "x08_ended_revoked",
        general,
        needs,
        ended_as("x08_ended_revoked"),
        extra_routes=[
            (
                r".*/api/v1/(me|devices|vaults|proposals).*",
                lambda r: r.fulfill(status=401, json={"ok": False, "code": "device_revoked", "error": "x"}),
            )
        ],
    )
    go(browser, ada, "x09_ended_key_missing", general, needs, ended_as("x09_ended_key_missing"), drop_seed=True)

    # Remove this phone: a treasury holds this phone's key; then the server can't be reached.
    def me_device(route):
        resp = route.fetch()
        body = resp.json()
        body["my_key"] = {"custody": "device", "key_id": 1, "usable": True}
        route.fulfill(response=resp, json=body)

    def treasury_with_me(route):
        resp = route.fetch()
        body = resp.json()
        if "/vaults/" + str(payment["vault_id"]) + "/" in route.request.url:
            t = body.get("treasury") or {
                "address": "0xD49174b703d6FBC5088b0f01C6E71B5Ef467f3D0",
                "chain_id": 11155111,
                "threshold_m": 2,
                "signer_count": 3,
                "linked_at": iso(timedelta(days=-3)),
                "signers": [],
            }
            t["signers"] = [{"user_id": 1, "custody": "device", "key_active": True}] + [
                s for s in t["signers"] if s["user_id"] != 1
            ]
            body["treasury"] = t
        else:
            body["treasury"] = None
        route.fulfill(response=resp, json=body)

    def remove(page):
        page.get_by_role("tab", name=re.compile("^Account")).first.click()
        page.wait_for_timeout(800)
        quiet(page)
        button(page, "Remove this phone").click()
        page.wait_for_timeout(1500)
        quiet(page)
        shot(page, "s12_remove_this_phone")
        # Pressed before ticking: the button is live and says why nothing happened.
        page.get_by_role("button", name="Remove this phone").last.click()
        page.wait_for_timeout(700)
        shot(page, "s12b_remove_needs_the_tick")
        page.get_by_role("checkbox", name=re.compile("I understand")).or_(
            page.get_by_text("I understand")
        ).first.click()
        page.get_by_role("button", name="Remove this phone").last.click()
        page.wait_for_timeout(1500)
        shot(page, "s13_remove_failed_offline")

    revoke_401 = {"on": False}

    def revoke_unauthorised(route):
        if not revoke_401["on"]:
            return route.fallback()
        route.fulfill(status=401, json={"ok": False, "code": "token_invalid", "error": "x"})

    go(
        browser,
        ada,
        "s12_remove_this_phone",
        general,
        needs,
        remove,
        extra_routes=[
            (r".*/api/v1/me$", me_device),
            (r".*/api/v1/vaults/\d+/treasury$", treasury_with_me),
        ],
    )
    # The same, with the server answering the removal 401 (session expired, or already removed on
    # the web): the sheet explains and offers "Remove from this phone only". Answered here, never
    # by the server, so the harness device is never removed.
    revoke_401["on"] = True

    def remove_401(page):
        page.get_by_role("tab", name=re.compile("^Account")).first.click()
        page.wait_for_timeout(800)
        quiet(page)
        button(page, "Remove this phone").click()
        page.wait_for_timeout(1500)
        quiet(page)
        page.get_by_role("checkbox", name=re.compile("I understand")).or_(
            page.get_by_text("I understand")
        ).first.click()
        page.get_by_role("button", name="Remove this phone").last.click()
        page.wait_for_timeout(1500)
        shot(page, "s14_remove_session_gone")

    go(
        browser,
        ada,
        "s14_remove_session_gone",
        general,
        needs,
        remove_401,
        extra_routes=[
            (r".*/api/v1/me$", me_device),
            (r".*/api/v1/vaults/\d+/treasury$", treasury_with_me),
            (r".*/api/v1/devices/\d+/revoke$", revoke_unauthorised),
        ],
    )
    browser.close()

(OUT / "audit_signing.json").write_text(
    json.dumps({**audit, "errors": errors}, indent=2), encoding="utf-8", newline="\n"
)
print(f"audit: {audit['checked']} targets checked, {len(audit['findings'])} findings")
for finding in audit["findings"]:
    print("  ", finding)
for e in errors:
    print("ERROR", e)
