"""Screenshot the R1.1 style tile at desktop and phone width, light and dark.

style-tile.html is an artifact fragment (no doctype, html, head or body; the publisher adds them).
This wraps it in the same minimal document the publisher uses, loads it from a file:// URL in
Chromium, waits for the web fonts, and writes:

    shots/desktop-1440-light.png        full page
    shots/desktop-1440-dark.png         full page, prefers-color-scheme: dark
    shots/phone-400-light.png           full page
    shots/phone-400-dark.png            full page, prefers-color-scheme: dark
    shots/desktop-1440-light-first.png  the first screenful only (1440 x 900)

It also reports what a reviewer would otherwise have to spot by eye: horizontal overflow of the
page body, elements that stick out past the viewport (outside the containers meant to scroll),
console errors, and whether the three faces actually loaded.

With --sections DIR it also writes one crop per page section, per shot, for close reading.

Run with the project interpreter, which has Playwright and Chromium:
    q-vault/.venv/Scripts/python.exe docs/plans/saas-rework/style-tile/tools/shoot.py [--sections DIR]
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import tempfile

from playwright.sync_api import sync_playwright

TILE = pathlib.Path(__file__).resolve().parents[1]
SRC = TILE / "style-tile.html"
OUT = TILE / "shots"

WRAP = ('<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"></head>'
        '<body style="margin:0">{}</body></html>')

SHOTS = [
    # name, width, height, colour scheme, full page
    ("desktop-1440-light", 1440, 900, "light", True),
    ("desktop-1440-dark", 1440, 900, "dark", True),
    ("phone-400-light", 400, 860, "light", True),
    ("phone-400-dark", 400, 860, "dark", True),
    ("desktop-1440-light-first", 1440, 900, "light", False),
]

FONTS_JS = """() => ({
  sans: document.fonts.check('600 14px "Public Sans"'),
  sansCaption: document.fonts.check('450 12px "Public Sans"'),
  serif: document.fonts.check('400 22px "Source Serif 4"'),
  mono: document.fonts.check('400 13px "JetBrains Mono"'),
})"""

OVERFLOW_JS = """() => {
  const vw = document.documentElement.clientWidth;
  const out = [];
  const scrollers = '.frame__scroll, .mx-wrap, .mini-wrap, .pairs-wrap, .tabs, .phone__sc, dialog, .bar';
  for (const el of document.querySelectorAll('body *')) {
    if (el.closest(scrollers)) continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    if (r.right > vw + 0.5 || r.left < -0.5) {
      out.push(`${el.tagName.toLowerCase()}.${String(el.className).split(' ').join('.')} [${Math.round(r.left)}, ${Math.round(r.right)}]`);
    }
  }
  return {
    bodyScrolls: document.documentElement.scrollWidth > vw,
    scrollWidth: document.documentElement.scrollWidth,
    viewport: vw,
    offenders: out.slice(0, 12),
    height: document.documentElement.scrollHeight,
  };
}"""


# With the clipboard refused (as inside an embedded frame), every visible copy button must leave the
# whole value selected, never the shortened text with its ellipsis.
COPY_FALLBACK_JS = """async () => {
  navigator.clipboard.writeText = () => Promise.reject(new Error('blocked'));
  const bad = [];
  const seen = new Set();
  let n = 0;
  const tabs = [null, ...document.querySelectorAll('#decision [role="tab"]')];
  for (const tab of tabs) {
    if (tab) tab.click();
    for (const btn of document.querySelectorAll('.copy[data-copy]')) {
      if (seen.has(btn) || !btn.getClientRects().length || btn.closest('[inert], dialog:not([open])')) continue;
      seen.add(btn);
      n += 1;
      btn.click();
      await new Promise(r => setTimeout(r, 20));
      const got = String(getSelection()).replace(/\\s+/g, '');
      if (got !== btn.dataset.copy) bad.push(`${btn.getAttribute('aria-label')}: selected "${got.slice(0, 24)}"`);
    }
  }
  getSelection().removeAllRanges();
  return { n, bad };
}"""

# S24: every interactive element in the phone frames is at least 44 x 44, counting a ::before hit area.
TOUCH_JS = """() => {
  const small = [];
  const sel = 'a[href], button, summary, input, select, textarea, [tabindex]:not([tabindex="-1"])';
  for (const el of document.querySelectorAll('.phone ' + sel.split(', ').join(', .phone '))) {
    if (el.classList.contains('phone__sc') || el.closest('[inert]') || !el.getClientRects().length) continue;
    if (el.closest('[hidden]')) continue;
    const r = el.getBoundingClientRect();
    let w = r.width, h = r.height;
    const b = getComputedStyle(el, '::before');
    if (b.content !== 'none' && b.position === 'absolute') {
      w = Math.max(w, parseFloat(b.width) || 0);
      h = Math.max(h, parseFloat(b.height) || 0);
    }
    if (w < 43.5 || h < 43.5) small.push(`${el.tagName.toLowerCase()} "${(el.getAttribute('aria-label') || el.textContent).trim().slice(0, 30)}" ${Math.round(w)}x${Math.round(h)}`);
  }
  return small;
}"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sections", type=pathlib.Path, help="also write one crop per page section into this folder")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="qvault-tile-"))
    doc = tmp / "style-tile.html"
    doc.write_text(WRAP.format(SRC.read_text(encoding="utf-8")), encoding="utf-8")
    url = doc.as_uri()
    problems = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for name, w, h, scheme, full in SHOTS:
            ctx = browser.new_context(viewport={"width": w, "height": h}, color_scheme=scheme,
                                      device_scale_factor=1, reduced_motion="no-preference")
            page = ctx.new_page()
            errors: list[str] = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url, wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            page.wait_for_timeout(400)
            fonts = page.evaluate(FONTS_JS)
            report = page.evaluate(OVERFLOW_JS)
            target = OUT / f"{name}.png"
            page.screenshot(path=str(target), full_page=full)
            print(f"{name}: {target.name}, page {report['viewport']} x {report['height']}")
            missing = [k for k, ok in fonts.items() if not ok]
            if missing:
                problems += 1
                print(f"  fonts not loaded: {missing}")
            if report["bodyScrolls"]:
                problems += 1
                print(f"  BODY SCROLLS SIDEWAYS: scrollWidth {report['scrollWidth']} > {report['viewport']}")
            for o in report["offenders"]:
                print(f"  sticks out: {o}")
            problems += bool(report["offenders"])
            if name == "desktop-1440-light-first":
                small = page.evaluate(TOUCH_JS)
                for s in small:
                    print(f"  touch target under 44 px: {s}")
                problems += bool(small)
                copy = page.evaluate(COPY_FALLBACK_JS)
                print(f"  copy fallback: {copy['n']} visible copy buttons, {len(copy['bad'])} selected the wrong text")
                for s in copy["bad"]:
                    print(f"    {s}")
                problems += bool(copy["bad"])
            for e in errors:
                problems += 1
                print(f"  console: {e}")
            if args.sections and full:
                args.sections.mkdir(parents=True, exist_ok=True)
                sections = page.locator("section.sec, section.intro")
                for i in range(sections.count()):
                    sec = sections.nth(i)
                    sid = sec.evaluate("el => (el.querySelector('h1, h2') || {}).id || 'section'")
                    sec.screenshot(path=str(args.sections / f"{name}-{i:02d}-{sid}.png"))
            ctx.close()
        browser.close()
    print("no problems found" if not problems else f"{problems} problem(s) reported above")
    return 0


if __name__ == "__main__":
    sys.exit(main())
