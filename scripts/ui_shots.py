"""Screenshot every web screen at desktop and phone widths, for the rework's visual review.

The rework plan (docs/plans/saas-rework.md, section 8) makes screenshot review the acceptance test
for visual work: each phase re-takes this set and compares it with the baseline in
docs/plans/saas-rework/baseline/. Run it against a local server over the demo dataset::

    python scripts/seed_demo.py                      # once, into a scratch database
    flask --app wsgi run --port 5055                 # in another terminal
    python scripts/ui_shots.py http://127.0.0.1:5055 shots/ --theme both

Decision pages are found by following the links on each vault's page, one per status (open,
approved, rejected, expired, paid), so the set does not depend on the demo's random ids. The
treasury screens (new payment, the chain page, a paid decision) exist only with
``ONCHAIN_EXECUTION_ENABLED=true``; without it they answer 404 and are shot as such. The public
record is found through a decision's public link, so it is shot only when one decision has been
shared; ``--every-phone`` adds every screen at phone width, not only the ones in PHONE. Needs
Playwright with Chromium (``pip install playwright && playwright install chromium``).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ANON = [
    ("01_landing", "/"),
    ("02_login", "/login"),
    ("03_register", "/register"),
    ("04_verify_anon", "/verify/"),
    ("05_not_found", "/no-such-page"),
    ("06_docs_page_anon", "/docs/approvals"),
    ("07_invite_unknown", "/invite/not-a-real-invitation"),
    ("08_forgot_password", "/forgot-password"),
    ("50_security", "/security"),
    ("51_pricing", "/pricing"),
    ("52_changelog", "/changelog"),
    ("53_status", "/status"),
]
AUTHED = [
    ("10_home", "/"),
    ("11_approvals", "/approvals/"),
    ("12_vaults", "/vaults/"),
    ("23_new_decision", "/vaults/{vault}/proposals/new"),
    ("23_new_access", "/vaults/{vault}/proposals/new?kind=access"),
    ("24_new_payment", "/vaults/{vault}/proposals/new?kind=payment"),
    ("25_new_vault", "/vaults/new"),
    ("26_audit", "/ledger/"),
    ("27_transparency", "/ledger/transparency"),
    ("28_verify", "/verify/"),
    ("29_security_crypto", "/admin/crypto"),
    ("30_security_benchmark", "/admin/benchmark"),
    ("31_security_rotation", "/admin/rotation"),
    ("32_security_attack", "/admin/attack"),
    ("33_admin_chain", "/admin/chain"),
    ("34_account", "/account/"),
    ("35_docs", "/docs/"),
    ("36_trace", "/trace/"),
    ("37_docs_page", "/docs/verifying"),
    ("38_members", "/workspace/members"),
    ("39_invite", "/workspace/invite"),
    ("40_workspace_settings", "/workspace/settings"),
    ("41_notifications", "/notifications/"),
    ("42_notification_prefs", "/account/notifications"),
    ("43_account_security", "/account/security"),
]
#: Screens whose address is found on another page: the first link matching the pattern.
FOUND = [
    ("44_remove_member", "/workspace/members", r"^/workspace/members/\d+/remove$"),
    ("45_public_record", None, r"^(?:https?://[^/]+)?/d/[0-9a-f-]{36}$"),
]
VAULT_TABS = [
    ("13_vault_decisions", ""),
    ("14_vault_members", "?tab=members"),
    ("15_vault_files", "?tab=files"),
    ("16_vault_treasury", "?tab=treasury"),
    ("17_vault_settings", "?tab=settings"),
]
STATUSES = ("open", "approved", "rejected", "expired", "paid")
#: How a row says each status. Since rework R2 an open decision reads "Needs your signature" or
#: "Waiting on N" (plan S6), never "Open", so each status is matched by its own words.
STATUS_WORDS = {
    "open": r"\bopen\b|needs your signature|waiting on \d",
    "approved": r"\bapproved\b",
    "rejected": r"\brejected\b",
    "expired": r"\bexpired\b",
    "paid": r"\bpaid\b",
}
#: The screens worth checking at phone width; the rest are admin pages used at a desk.
PHONE = ("01", "02", "05", "10", "11", "13", "18", "26", "34")

PROPOSAL_LINK = re.compile(r"^/vaults/(\d+)/proposals/[0-9a-f-]{36}$")
#: Each decision link, with the text of the row it sits in (where its status is written).
ROW_TEXT = (
    "els => els.map(e => [e.getAttribute('href'), (e.closest('tr, li, article') || e).innerText])"
)


def first_link(page: Page, base: str, pages: list[str], pattern: str) -> str | None:
    """The first link on these pages whose href matches pattern, as a path on this server."""
    for path in pages:
        page.goto(base + path, wait_until="networkidle")
        for href in page.eval_on_selector_all(
            "a[href], input[readonly][value]",
            "els => els.map(e => e.getAttribute('href') || e.getAttribute('value'))",
        ):
            if href and re.match(pattern, href):
                return re.sub(r"^https?://[^/]+", "", href)
    return None


def discover(page: Page, base: str) -> tuple[int, dict[str, str]]:
    """The first vault, and one decision page per status, found from the vaults' own pages."""
    page.goto(base + "/vaults/", wait_until="networkidle")
    vaults = sorted(
        {
            int(m.group(1))
            for href in page.eval_on_selector_all(
                "a[href]", "els => els.map(e => e.getAttribute('href'))"
            )
            if (m := re.match(r"^/vaults/(\d+)$", href or ""))
        }
    )
    if not vaults:
        sys.exit("No vaults are visible to this account; seed the demo dataset first.")
    found: dict[str, str] = {}
    for vid in vaults:
        page.goto(f"{base}/vaults/{vid}", wait_until="networkidle")
        rows = page.eval_on_selector_all("a[href*='/proposals/']", ROW_TEXT)
        for href, text in rows:
            if not PROPOSAL_LINK.match(href or ""):
                continue
            words = text.lower()
            for status in STATUSES:
                if status not in found and re.search(STATUS_WORDS[status], words):
                    found[status] = href
                    break
        if len(found) == len(STATUSES):
            break
    return vaults[0], found


def take(page: Page, base: str, out: Path, shot: str, path: str, full_page: bool = True) -> None:
    """One screenshot, named ``<width>_<screen><theme>.png``: the full page, or the first screen."""
    resp = page.goto(base + path, wait_until="networkidle")
    page.screenshot(path=str(out / f"{shot}.png"), full_page=full_page)
    print(shot, resp.status if resp else "-")


def shoot(
    base: str,
    out: Path,
    email: str,
    password: str,
    themes: list[str],
    only: tuple[str, ...] = (),
    full_page: bool = True,
    every_phone: bool = False,
) -> None:
    out.mkdir(parents=True, exist_ok=True)

    def at_phone(name: str) -> bool:
        return every_phone or name.startswith(PHONE)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for theme in themes:
            suffix = "" if themes == ["light"] else f"_{theme}"
            for label, width, height in (("desk", 1440, 900), ("phone", 390, 844)):
                ctx = browser.new_context(
                    viewport={"width": width, "height": height}, color_scheme=theme
                )
                page = ctx.new_page()
                screens = list(ANON)
                for name, path in screens:
                    if (label == "desk" or at_phone(name)) and _wanted(name, only):
                        take(page, base, out, f"{label}_{name}{suffix}", path, full_page)
                page.goto(base + "/login", wait_until="networkidle")
                page.fill('input[name="email"]', email)
                page.fill('input[name="password"]', password)
                page.locator('form:has(input[name="password"]) [type="submit"]').first.click()
                page.wait_for_load_state("networkidle")

                vault, decisions = discover(page, base)
                screens = [(name, path.format(vault=vault)) for name, path in AUTHED]
                screens += [(name, f"/vaults/{vault}{query}") for name, query in VAULT_TABS]
                for i, status in enumerate(STATUSES):
                    if status in decisions:
                        screens.append((f"{18 + i}_decision_{status}", decisions[status]))
                    else:
                        print(f"{label}{suffix}: no {status} decision found; skipped")
                for name, where, pattern in FOUND:
                    if not _wanted(name, only):
                        continue
                    pages = [where] if where else list(decisions.values())
                    found = first_link(page, base, pages, pattern)
                    if found:
                        screens.append((name, found))
                    else:
                        print(f"{label}{suffix}: no link for {name}; skipped")
                for name, path in screens:
                    if (label == "desk" or at_phone(name)) and _wanted(name, only):
                        take(page, base, out, f"{label}_{name}{suffix}", path, full_page)
                ctx.close()
        browser.close()


def _wanted(name: str, only: tuple[str, ...]) -> bool:
    return not only or name.startswith(only)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("base", help="the server's base URL, e.g. http://127.0.0.1:5055")
    parser.add_argument("out", type=Path, help="directory for the PNGs")
    parser.add_argument("--email", default="ada@qvault.demo")
    parser.add_argument("--password", default="demo-password-2026")
    parser.add_argument(
        "--theme",
        choices=("light", "dark", "both"),
        default="light",
        help="emulated colour scheme; 'both' adds a _dark copy of every shot",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        default=(),
        metavar="PREFIX",
        help="shoot only the screens whose names start with these, e.g. --only 10 11 13",
    )
    parser.add_argument(
        "--first-screen",
        action="store_true",
        help="capture the viewport only, not the full page (smaller files for a review set)",
    )
    parser.add_argument(
        "--every-phone",
        action="store_true",
        help="shoot every screen at phone width too, not only the ones in PHONE",
    )
    args = parser.parse_args()
    themes = ["light", "dark"] if args.theme == "both" else [args.theme]
    shoot(
        args.base.rstrip("/"),
        args.out,
        args.email,
        args.password,
        themes,
        only=tuple(args.only),
        full_page=not args.first_screen,
        every_phone=args.every_phone,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
