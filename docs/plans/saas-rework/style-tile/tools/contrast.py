#!/usr/bin/env python3
"""Measure every colour pair the Q-Vault components rely on, in both themes.

Reads ../tokens.css, resolves var() chains for the light theme (:root) and the dark theme (:root plus
the dark overrides), computes WCAG 2.x contrast for each pair below, and writes ../contrast.md.

Also checks the token file's own consistency:
  * the two dark blocks (the prefers-color-scheme one and [data-theme="dark"]) are identical;
  * every colour literal set in :root is redefined for dark (or the token is an alias that resolves
    through tokens that are), so no colour is accidentally light-only;
  * every var() reference resolves.

Standard library only. Exit status 1 if a required pair misses its target or a consistency check
fails, so it can run as a test.

    python tools/contrast.py [--css PATH] [--out PATH]
"""
from __future__ import annotations

import argparse
import hashlib
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_CSS = HERE.parent / "tokens.css"
DEFAULT_OUT = HERE.parent / "contrast.md"

TEXT = 4.5      # WCAG 1.4.3, normal text
UI = 3.0        # WCAG 1.4.11 (controls, focus, meaningful graphics) and 1.4.3 large text
INFO = None     # decorative: reported, no requirement
EXEMPT = "exempt"

# --------------------------------------------------------------------------- the pairs that matter
#
# (foreground, [backgrounds], target, where it happens). Each row is checked in both themes.

# Every background ordinary text can sit on. Text selection is not here: ::selection sets its own text
# colour (--selection-text), so selected subtle text is drawn in --selection-text, measured below.
BACKGROUNDS_TEXT = ["--bg", "--bg-subtle", "--surface", "--surface-raised", "--fill", "--fill-hover",
                    "--accent-subtle"]

GROUPS: list[tuple[str, list[tuple[str, list[str], object, str]]]] = [
    ("Text", [
        ("--text", BACKGROUNDS_TEXT, TEXT, "body text, titles, the decision text"),
        ("--text-muted", BACKGROUNDS_TEXT, TEXT, "secondary text, labels in key-value panels"),
        ("--text-subtle", BACKGROUNDS_TEXT, TEXT, "meta, timestamps, captions, placeholders"),
        ("--selection-text", ["--selection"], TEXT, "selected text (::selection sets both colours)"),
        ("--text", ["--fill-raised-hover"], TEXT, "a hovered menu item, or a hovered row in a popover"),
        ("--text-muted", ["--fill-raised-hover"], TEXT, "muted text in a hovered notification"),
        ("--status-critical-fg", ["--fill-raised-hover"], TEXT, "a hovered destructive menu item"),
    ]),
    ("Accent, links and focus", [
        ("--accent-text", ["--accent", "--accent-hover"], TEXT, "label on the primary button"),
        ("--accent-fg", ["--accent-subtle", "--accent-subtle-hover", "--bg", "--bg-subtle", "--surface"], TEXT,
         "active nav item, selected tab, accent label on a tint"),
        ("--link", ["--bg", "--bg-subtle", "--surface", "--surface-raised", "--fill-hover", "--accent-subtle"],
         TEXT, "links in text, in rows, in menus"),
        ("--link-hover", ["--bg", "--bg-subtle", "--surface", "--surface-raised", "--fill-hover"], TEXT,
         "hovered link"),
        ("--focus", ["--bg", "--bg-subtle", "--surface", "--surface-raised", "--accent-subtle", "--fill-hover"],
         UI, "2px focus ring, 2px off the element"),
    ]),
    ("Controls and the quorum seal", [
        ("--border-strong", ["--bg", "--bg-subtle", "--surface", "--surface-raised", "--fill-hover",
                             "--accent-subtle"], UI, "input, select, checkbox and radio borders"),
        ("--accent", ["--bg", "--bg-subtle", "--surface", "--surface-raised"], UI,
         "checked checkbox, radio, switch; primary button edge"),
        ("--accent-fg", ["--surface", "--surface-raised", "--accent-subtle"], UI,
         "the 1px edge of a checked segment (Appearance, Fit), also in the account menu"),
        ("--mark-filled", ["--bg", "--surface", "--surface-raised", "--fill-hover"], UI, "a signature in the seal"),
        ("--mark-empty", ["--bg", "--surface", "--surface-raised", "--fill-hover"], UI, "a signature still needed"),
        ("--danger-text", ["--danger", "--danger-hover"], TEXT, "label on a destructive button"),
        ("--danger", ["--surface", "--surface-raised"], UI, "destructive button edge, in a dialog"),
    ]),
    ("Status", [
        *[(f"--status-{t}-fg", [f"--status-{t}-bg", "--bg", "--surface", "--surface-raised", "--fill-hover"], TEXT,
           f"{t} badge text; {t} word as coloured text in a row")
          for t in ("neutral", "info", "success", "warning", "critical")],
        *[("--text", [f"--status-{t}-bg"], TEXT, f"body text inside a {t} banner")
          for t in ("info", "success", "warning", "critical")],
    ]),
    ("Chrome (phone tab bar, tooltips)", [
        ("--chrome-text", ["--chrome-bg", "--chrome-bg-raised"], TEXT, "active tab, tooltip text"),
        ("--chrome-text-muted", ["--chrome-bg", "--chrome-bg-raised"], TEXT, "inactive tab label"),
    ]),
    ("Decorative and exempt (reported, no target)", [
        ("--border", ["--surface", "--bg"], INFO, "hairline around flat cards and tables"),
        ("--border-hover", ["--surface"], INFO, "card or secondary button on hover"),
        *[(f"--status-{t}-border", ["--surface", f"--status-{t}-bg"], INFO, f"{t} badge outline")
          for t in ("neutral", "info", "success", "warning", "critical")],
        ("--chrome-border", ["--chrome-bg"], INFO, "tab bar top rule"),
        ("--text-disabled", ["--surface", "--fill-disabled"], EXEMPT, "disabled label (WCAG 1.4.3 exempt)"),
        ("--border-disabled", ["--surface"], EXEMPT, "disabled input border"),
    ]),
]

# Ramp roles, for the ramp table.
NEUTRAL_ROLES = {
    1: "app background", 2: "subtle background", 3: "component background", 4: "hover", 5: "active",
    6: "hairline border", 7: "hover border", 8: "input border (>= 3:1)", 9: "solid",
    10: "subtle text (>= 4.5:1)", 11: "muted text", 12: "text",
}
ACCENT_ROLES = {
    1: "", 2: "", 3: "subtle (selected, active nav)", 4: "subtle hover", 5: "subtle active",
    6: "subtle border", 7: "border", 8: "strong border", 9: "solid", 10: "solid hover",
    11: "text on tint", 12: "high-contrast text",
}

# --------------------------------------------------------------------------- CSS parsing


def strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def blocks(css: str) -> list[tuple[str, str]]:
    """Top-level rules as (selector, body). Nested @media bodies are returned as their own rules,
    with the selector prefixed by the media prelude."""
    out: list[tuple[str, str]] = []
    i, n = 0, len(css)
    while i < n:
        j = css.find("{", i)
        if j < 0:
            break
        selector = " ".join(css[i:j].split())
        depth, k = 1, j + 1
        while k < n and depth:
            if css[k] == "{":
                depth += 1
            elif css[k] == "}":
                depth -= 1
            k += 1
        body = css[j + 1:k - 1]
        if selector.startswith("@media"):
            out.extend((f"{selector} >> {s}", b) for s, b in blocks(body))
        else:
            out.append((selector, body))
        i = k
    return out


def declarations(body: str) -> dict[str, str]:
    decls = {}
    for m in re.finditer(r"(--[\w-]+|color-scheme)\s*:\s*([^;]+);", body):
        decls[m.group(1)] = " ".join(m.group(2).split())
    return decls


def norm(selector: str) -> str:
    return selector.replace("'", '"').replace(" ", "")


def load(css_text: str):
    css = strip_comments(css_text)
    light = dark_media = dark_attr = None
    for selector, body in blocks(css):
        s = norm(selector)
        if s == ":root":
            if light is not None:
                raise SystemExit("tokens.css: more than one plain :root block")
            light = declarations(body)
        elif s == '@media(prefers-color-scheme:dark)>>:root:not([data-theme="light"])':
            dark_media = declarations(body)
        elif s == ':root[data-theme="dark"]':
            dark_attr = declarations(body)
        else:
            raise SystemExit(f"tokens.css: unexpected block {selector!r}; the theming shape is fixed")
    for name, block in (("':root'", light), ("the prefers-color-scheme dark block", dark_media),
                        ("':root[data-theme=\"dark\"]'", dark_attr)):
        if block is None:
            raise SystemExit(f"tokens.css: missing {name}")
    return light, dark_media, dark_attr


VAR = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^)]*))?\)")


def resolve(name: str, tokens: dict[str, str], trail: tuple[str, ...] = ()) -> str:
    if name in trail:
        raise ValueError(f"circular reference: {' -> '.join(trail + (name,))}")
    if name not in tokens:
        raise KeyError(name)
    value = tokens[name]

    def sub(m: re.Match) -> str:
        ref, fallback = m.group(1), m.group(2)
        if ref in tokens:
            return resolve(ref, tokens, trail + (name,))
        if fallback is not None:
            return fallback.strip()
        raise KeyError(f"{name} references undefined {ref}")

    return VAR.sub(sub, value)


HEX = re.compile(r"#(?:[0-9a-fA-F]{3}){1,2}\b")
COLOUR_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(|\boklab\(")


def parse_hex(value: str) -> tuple[float, float, float] | None:
    v = value.strip()
    if not re.fullmatch(r"#(?:[0-9a-fA-F]{3}){1,2}", v):
        return None
    v = v[1:]
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    return tuple(int(v[i:i + 2], 16) / 255 for i in (0, 2, 4))


# --------------------------------------------------------------------------- colour maths


def linear(c: float) -> float:
    # sRGB transfer; 0.04045 is the IEC value WCAG 2.2 now cites (0.03928 in older text; no hex differs).
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb) -> float:
    r, g, b = (linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a, b) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def oklch(rgb) -> tuple[float, float, float]:
    r, g, b = (linear(c) for c in rgb)
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l, m, s = (math.copysign(abs(x) ** (1 / 3), x) for x in (l, m, s))
    L = 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s
    A = 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s
    B = 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s
    C = math.hypot(A, B)
    H = math.degrees(math.atan2(B, A)) % 360 if C > 0.002 else float("nan")
    return L, C, H


def floor2(x: float) -> str:
    """Truncate, never round up: 4.497 must not print as a passing 4.50."""
    if math.isnan(x):
        return "?"
    return f"{math.floor(x * 100) / 100:.2f}"


# --------------------------------------------------------------------------- checks


def consistency(light, dark_media, dark_attr) -> list[str]:
    problems = []
    if dark_media != dark_attr:
        only_m = sorted(set(dark_media) - set(dark_attr))
        only_a = sorted(set(dark_attr) - set(dark_media))
        differ = sorted(k for k in set(dark_media) & set(dark_attr) if dark_media[k] != dark_attr[k])
        if only_m:
            problems.append(f"only in the prefers-color-scheme dark block: {', '.join(only_m)}")
        if only_a:
            problems.append(f"only in [data-theme=\"dark\"]: {', '.join(only_a)}")
        for k in differ:
            problems.append(f"{k} differs between the dark blocks: {dark_media[k]!r} vs {dark_attr[k]!r}")
    if dark_media.get("color-scheme") != "dark" or dark_attr.get("color-scheme") != "dark":
        problems.append("a dark block does not set color-scheme: dark")
    unknown = sorted(set(dark_attr) - set(light))
    if unknown:
        problems.append(f"dark sets tokens :root never defines: {', '.join(unknown)}")
    # Every colour literal in :root must have a dark value, directly or through its references.
    light_only = [k for k, v in light.items()
                  if k.startswith("--") and COLOUR_LITERAL.search(v) and k not in dark_attr]
    if light_only:
        problems.append(f"colour tokens with no dark value: {', '.join(sorted(light_only))}")
    for theme_name, tokens in (("light", light), ("dark", {**light, **dark_attr})):
        for k in tokens:
            try:
                resolve(k, tokens)
            except (KeyError, ValueError) as e:
                problems.append(f"{theme_name}: {k}: {e}")
    return problems


def measure(tokens: dict[str, str], fg: str, bg: str):
    f, b = resolve(fg, tokens), resolve(bg, tokens)
    rf, rb = parse_hex(f), parse_hex(b)
    if rf is None or rb is None:
        raise SystemExit(f"{fg} on {bg}: not a hex colour ({f!r} / {b!r}); measured pairs must be opaque hex")
    return f.upper(), b.upper(), ratio(rf, rb)


def verdict(value: float, target) -> str:
    if target is INFO:
        return "info"
    if target == EXEMPT:
        return "exempt"
    return "pass" if value >= target else "FAIL"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--css", type=Path, default=DEFAULT_CSS)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    raw = args.css.read_text(encoding="utf-8")
    light, dark_media, dark_attr = load(raw)
    themes = {"light": light, "dark": {**light, **dark_attr}}
    problems = consistency(light, dark_media, dark_attr)

    rows = []          # (group, fg, bg, use, target, {theme: (fhex, bhex, ratio, verdict)})
    failures = []
    for group, pairs in GROUPS:
        for fg, bgs, target, use in pairs:
            for bg in bgs:
                result = {}
                for theme, tokens in themes.items():
                    try:
                        fh, bh, r = measure(tokens, fg, bg)
                    except (KeyError, ValueError) as e:
                        # Already listed by consistency(); record the pair as unmeasurable and go on.
                        result[theme] = ("?", "?", float("nan"), "ERROR")
                        failures.append(f"{theme}: {fg} on {bg} could not be resolved ({e})")
                        continue
                    v = verdict(r, target)
                    result[theme] = (fh, bh, r, v)
                    if v == "FAIL":
                        failures.append(f"{theme}: {fg} on {bg} = {floor2(r)} (needs {target})")
                rows.append((group, fg, bg, use, target, result))

    required = [r for r in rows if r[4] not in (INFO, EXEMPT)]
    lines = []
    w = lines.append
    w("# Colour contrast, measured")
    w("")
    w("Generated by `tools/contrast.py` from `tokens.css` "
      f"(sha256 `{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:12]}`). Do not edit by hand; "
      "change the tokens and run the script again.")
    w("")
    w("WCAG 2.x contrast ratio, truncated (never rounded up) to two decimals. Targets: **4.5** for "
      "text (1.4.3), **3.0** for controls, focus rings and meaningful graphics such as the quorum marks "
      "(1.4.11). *info* rows are decorative and have no requirement; *exempt* rows are disabled states.")
    w("")
    n_req = len(required) * 2
    n_fail = len(failures)
    w(f"**Result: {n_req - n_fail} of {n_req} required pairs pass "
      f"({len(required)} pairs x 2 themes).** "
      + ("No failures." if not n_fail else f"{n_fail} failing."))
    w("")
    w("Token-file checks: " + ("the two dark blocks are identical; every colour token has a dark value; "
                               "every `var()` resolves." if not problems else "**problems found** (below)."))
    w("")
    if failures:
        w("## Failures")
        w("")
        for f in failures:
            w(f"- {f}")
        w("")
    if problems:
        w("## Token-file problems")
        w("")
        for p in problems:
            w(f"- {p}")
        w("")

    def lowest(theme, fg_filter=None):
        vals = [r[5][theme][2] for r in required
                if (fg_filter is None or r[1] == fg_filter) and not math.isnan(r[5][theme][2])]
        return min(vals) if vals else float("nan")

    w("## Headroom")
    w("")
    w("The weakest required pair per foreground, both themes. This is where a future tweak would break first.")
    w("")
    w("| Foreground | Target | Lowest, light | Lowest, dark |")
    w("| --- | --- | --- | --- |")
    seen = []
    for r in required:
        if r[1] not in seen:
            seen.append(r[1])
    for fg in seen:
        tgt = next(r[4] for r in required if r[1] == fg)
        w(f"| `{fg}` | {tgt} | {floor2(lowest('light', fg))} | {floor2(lowest('dark', fg))} |")
    w("")

    current = None
    for group, fg, bg, use, target, result in rows:
        if group != current:
            current = group
            w(f"## {group}")
            w("")
            w("| Foreground | Background | Where | Target | Light | | Dark | |")
            w("| --- | --- | --- | --- | --- | --- | --- | --- |")
        tgt = "-" if target is INFO else ("exempt" if target == EXEMPT else f"{target}")
        lf, lb, lr, lv = result["light"]
        df, db, dr, dv = result["dark"]
        w(f"| `{fg}` | `{bg}` | {use} | {tgt} | {floor2(lr)} `{lf}` on `{lb}` | {lv} "
          f"| {floor2(dr)} `{df}` on `{db}` | {dv} |")
    w("")

    w("## The ramps")
    w("")
    w("OKLCH lightness, chroma and hue for every step. The neutrals and the accent hold the ink's hue "
      "(the ink, `#16233A`, is OKLCH 0.257 / 0.047 / 261). Contrast is against step 1 of the same theme.")
    w("")
    for ramp, roles in (("neutral", NEUTRAL_ROLES), ("accent", ACCENT_ROLES)):
        w(f"### {ramp.capitalize()}")
        w("")
        w("| Step | Role | Light | L / C / H | vs step 1 | Dark | L / C / H | vs step 1 |")
        w("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for i in range(1, 13):
            cells = []
            for theme in ("light", "dark"):
                t = themes[theme]
                h = resolve(f"--{ramp}-{i}", t).upper()
                base = parse_hex(resolve(f"--{ramp}-1", t))
                L, C, H = oklch(parse_hex(h))
                hue = "-" if math.isnan(H) else f"{H:.0f}"
                cells += [f"`{h}`", f"{L:.3f} / {C:.3f} / {hue}", floor2(ratio(parse_hex(h), base))]
            w(f"| {i} | {roles[i]} | " + " | ".join(cells) + " |")
        w("")

    w("## Status tones")
    w("")
    w("| Tone | Light fg / bg / border | Dark fg / bg / border |")
    w("| --- | --- | --- |")
    for t in ("neutral", "info", "success", "warning", "critical"):
        cells = []
        for theme in ("light", "dark"):
            tk = themes[theme]
            cells.append(" / ".join(f"`{resolve(f'--status-{t}-{p}', tk).upper()}`" for p in ("fg", "bg", "border")))
        w(f"| {t} | {cells[0]} | {cells[1]} |")
    w("")

    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    print(f"{n_req - n_fail}/{n_req} required pairs pass; {len(problems)} token-file problem(s). Wrote {args.out}")
    for f in failures:
        print("  FAIL", f)
    for p in problems:
        print("  PROBLEM", p)
    return 1 if failures or problems else 0


if __name__ == "__main__":
    sys.exit(main())
