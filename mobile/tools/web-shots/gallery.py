"""Web screenshot harness ONLY: shoot the component gallery and audit every touch target.

Usage: python gallery.py <harness origin> <out dir> [page ...]

For each gallery page (all of them by default), in light and dark, at text sizes 1.0 and an
emulated 2.0 (phone-ux §8.1), it saves `gallery_<page>_<theme>_<scale>.png`, grown to the page's
full length. It then runs the target audit (§4.6, §10.1): react-native-web ignores hitSlop, so
`ui/Touchable` writes its effective target to `data-hit-w` / `data-hit-h`; the audit fails on any
visible target under 48 x 48, and on any target nested inside another (a screen reader cannot
reach the inner one). The audit's findings go to `audit.json` beside the shots, and the exit code
is non-zero when there are any.

The gallery needs no backend; any request that leaves the harness origin is aborted.
"""

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1].rstrip("/")
OUT = Path(sys.argv[2])
PAGES = sys.argv[3:] or [
    "buttons",
    "status",
    "rows",
    "values",
    "inputs",
    "messages",
    "structure",
    "sheet",
    "overlay",
]
OUT.mkdir(parents=True, exist_ok=True)
W, H = 390, 844
COMBOS = [("light", 1), ("dark", 1), ("light", 2), ("dark", 2)]

# Every visible touch target, its effective size, and whether another contains it.
AUDIT = """() => [...document.querySelectorAll('[data-hit-w]')]
  .filter((el) => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none';
  })
  .map((el) => ({
    w: Number(el.dataset.hitW),
    h: Number(el.dataset.hitH),
    visualW: Math.round(el.getBoundingClientRect().width),
    visualH: Math.round(el.getBoundingClientRect().height),
    label: el.getAttribute('aria-label') || (el.textContent || '').trim().slice(0, 40),
    nested: !!(el.parentElement && el.parentElement.closest('[data-hit-w]')),
  }))"""

GROW = """() => {
  const el = document.getElementById('gallery-scroll');
  return el ? el.scrollHeight - el.clientHeight : 0;
}"""


def main() -> int:
    findings = []
    counted = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for theme, scale in COMBOS:
            ctx = browser.new_context(
                viewport={"width": W, "height": H},
                device_scale_factor=2,
                color_scheme=theme,
            )
            page = ctx.new_page()
            page.route(
                "**/*",
                lambda r: r.continue_() if r.request.url.startswith(BASE) else r.abort(),
            )
            page.on("pageerror", lambda e: print("PAGEERROR", str(e)[:300]))
            for name in PAGES:
                page.set_viewport_size({"width": W, "height": H})
                page.goto(f"{BASE}/?gallery={name}&theme={theme}&fontScale={scale}")
                page.wait_for_selector("#gallery-scroll", timeout=60000)
                page.wait_for_timeout(2800 if name == "overlay" else 900)
                if name not in ("sheet", "overlay"):
                    extra = page.evaluate(GROW)
                    if extra > 0:
                        page.set_viewport_size({"width": W, "height": min(H + extra, 12000)})
                        page.wait_for_timeout(500)
                path = OUT / f"gallery_{name}_{theme}_{scale}x.png"
                page.screenshot(path=str(path))
                print("shot", path.name, flush=True)
                for t in page.evaluate(AUDIT):
                    counted += 1
                    if t["w"] < 48 or t["h"] < 48 or t["nested"]:
                        findings.append({"page": name, "theme": theme, "scale": scale, **t})
            ctx.close()
        browser.close()
    (OUT / "audit.json").write_text(
        json.dumps({"targets_checked": counted, "findings": findings}, indent=2),
        encoding="utf-8",
        newline="\n",
    )
    print(f"audit: {counted} targets checked, {len(findings)} findings")
    for f in findings:
        print("  ", f)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
