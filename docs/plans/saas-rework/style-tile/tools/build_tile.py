"""Build the R1.1 style tile: docs/plans/saas-rework/style-tile/style-tile.html.

The page is an artifact fragment (no doctype, html, head or body): a <title>, the Google Fonts
link, one <style>, the markup, one <script>. Everything it shows is assembled from files in this
folder so the tile cannot drift from them:

  - tokens.css is pasted verbatim at the top of the <style> (light, and both dark blocks);
  - every contrast figure comes from contrast.md (written by tools/contrast.py);
  - the logo marks are the SVG paths in mark/;
  - the screen content follows screens.md.

Stdlib only. Run with Python 3.12 or later (the q-vault .venv has 3.13):
    python docs/plans/saas-rework/style-tile/tools/build_tile.py
"""

from __future__ import annotations

import hashlib
import html
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
TILE = HERE.parent
OUT = TILE / "style-tile.html"

TOKENS = (TILE / "tokens.css").read_text(encoding="utf-8")
CSS = (HERE / "tile" / "tile.css").read_text(encoding="utf-8")
JS = (HERE / "tile" / "tile.js").read_text(encoding="utf-8")
CONTRAST_MD = (TILE / "contrast.md").read_text(encoding="utf-8")


def esc(s: str) -> str:
    return html.escape(s, quote=True)


# ----------------------------------------------------------------------------------------- data

DECISION_TEXT = ("Pay 0.25 ETH from this vault's treasury 0xD49174b703d6FBC5088b0f01C6E71B5Ef467f3D0 "
                 "to 0x41Ed514Be43c437C8b458e3B7491A674b6A78A19 on Sepolia.")
RECIPIENT = "0x41Ed514Be43c437C8b458e3B7491A674b6A78A19"
TREASURY = "0xD49174b703d6FBC5088b0f01C6E71B5Ef467f3D0"
PAYLOAD_HASH = "a39771f851e8de6291cd6d64c90e9c61227f64892bafdeb24bef4bd38a5127bf"
CODE = "A397-71F8"
DECISION_ID = "4d530c73-bcb0-4f10-ad62-ec7fe6fee8ab"
NONCE = "b56d90669a3e4336059ba6ecb2b0bf9e"
DIGEST = "0x4a1a064f15dd1ccd453fd59511fd5ed9044f900896932a72a442b491df4adb0c"
LINK = "https://project4.zaidansari.tech/vaults/1/proposals/" + DECISION_ID
RAW = ('QVAULT-SIG-v1:PROPOSAL|{"action":{"call_gas":100000,"chain_id":11155111,"config_nonce":0,'
       '"data":"0x","kind":"eth_transfer","to":"0x41Ed514Be43c437C8b458e3B7491A674b6A78A19",'
       '"treasury":"0xD49174b703d6FBC5088b0f01C6E71B5Ef467f3D0","valid_until":1791561600,'
       '"value_wei":"250000000000000000"},"action_text":"Pay 0.25 ETH from this vault\'s treasury '
       '0xD49174b703d6FBC5088b0f01C6E71B5Ef467f3D0 to 0x41Ed514Be43c437C8b458e3B7491A674b6A78A19 on '
       'Sepolia.","created_at":"2026-10-04T08:41:17.304551+00:00","file_sha256":null,'
       '"nonce":"b56d90669a3e4336059ba6ecb2b0bf9e","policy":{"M":2,"N":4,"signers":[1,2,3,4]},'
       '"proposal_id":"4d530c73-bcb0-4f10-ad62-ec7fe6fee8ab","vault_id":1}')


def illustrative(head: str, tail: str, label: str, length: int = 64) -> str:
    """screens.md gives some illustrative hashes only as head…tail. Fill the middle deterministically
    so a copy button copies a whole value of the right length."""
    mid = hashlib.sha256(label.encode()).hexdigest() * 2
    return head + mid[: length - len(head) - len(tail)] + tail


SIG_H = illustrative("185e117f", "e8979dd2", "sig hassan")
TSIG_H = illustrative("d1f48027", "4fd61254", "treasury sig hassan")
SIG_Z = illustrative("6c0e93b1", "7a2f05d4", "sig zaid")
TSIG_Z = illustrative("90b2d7e5", "1c44a9e8", "treasury sig zaid")
ENTRY_1284 = illustrative("363c02a0", "4e01599b", "entry 1284")
ENTRY_1285 = illustrative("f7d479b5", "33a15df6", "entry 1285")
LEAF_1285 = illustrative("1cf3fcaa", "b8a220b3", "leaf 1285")
ROOT_1286 = illustrative("c94c7be9", "37d2aa50", "root 1286")


# ----------------------------------------------------------------------------------------- contrast.md

def parse_contrast(md: str):
    pairs: dict[tuple[str, str], tuple[str, str]] = {}
    ramps: dict[str, dict[int, dict]] = {"neutral": {}, "accent": {}}
    section = None
    pair_re = re.compile(r"^\| `(--[\w-]+)` \| `(--[\w-]+)` \| [^|]+\| [^|]+\| ([\d.]+) `#\w+` on `#\w+` \| \w+ \| ([\d.]+) `")
    ramp_re = re.compile(r"^\| (\d+) \| ([^|]*)\| `(#\w+)` \| [^|]+\| ([\d.]+) \| `(#\w+)` \| [^|]+\| ([\d.]+) \|")
    headline = None
    for line in md.splitlines():
        if line.startswith("**Result:"):
            headline = line
        if line.startswith("### Neutral"):
            section = "neutral"
        elif line.startswith("### Accent"):
            section = "accent"
        elif line.startswith("## Status tones"):
            section = None
        m = pair_re.match(line)
        if m:
            pairs[(m[1], m[2])] = (m[3], m[4])
        if section:
            m = ramp_re.match(line)
            if m:
                ramps[section][int(m[1])] = dict(role=m[2].strip(), light=m[3], lr=m[4], dark=m[5], dr=m[6])
    return pairs, ramps, headline


PAIRS, RAMPS, HEADLINE = parse_contrast(CONTRAST_MD)
assert len(RAMPS["neutral"]) == 12 and len(RAMPS["accent"]) == 12, "contrast.md ramps not found"
_m = re.search(r"Result: (\d+) of (\d+) required pairs pass \((\d+) pairs", HEADLINE or "")
assert _m and _m[1] == _m[2], HEADLINE
PAIRS_PASS, PAIRS_TOTAL, PAIRS_PER_THEME = _m[1], _m[2], _m[3]


def ratio(fg: str, bg: str) -> str:
    light, dark = PAIRS[(fg, bg)]
    return f'<span class="only-light">{light}</span><span class="only-dark">{dark}</span>'


# ----------------------------------------------------------------------------------------- tokens.css

def token_values(css: str):
    def block(start: str) -> str:
        i = css.index(start)
        j = css.index("{", i)
        depth, k = 0, j
        while True:
            if css[k] == "{":
                depth += 1
            elif css[k] == "}":
                depth -= 1
                if depth == 0:
                    return css[j + 1:k]
            k += 1

    def decls(body: str) -> dict[str, str]:
        body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
        return {m[1]: " ".join(m[2].split()) for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;]+);", body)}

    light = decls(block(":root {"))
    dark = dict(light)
    dark.update(decls(block(':root[data-theme="dark"] {')))

    def resolve(d, name, seen=()):
        v = d[name]
        m = re.fullmatch(r"var\((--[\w-]+)\)", v)
        if m and m[1] not in seen:
            return resolve(d, m[1], seen + (name,))
        return v

    return (lambda n: resolve(light, n).upper()), (lambda n: resolve(dark, n).upper())


LIGHT, DARK = token_values(TOKENS)


def hexes(token: str) -> str:
    """Live hex: JS replaces the text with the computed value for the current theme."""
    return f'<span class="swt__hex" data-hex="{token}">{LIGHT(token)}</span>'


# ----------------------------------------------------------------------------------------- marks

def svg_paths(name: str) -> tuple[str, str]:
    src = (TILE / "mark" / name).read_text(encoding="utf-8")
    vb = re.search(r'viewBox="([^"]+)"', src)[1]
    paths = "".join(re.findall(r"<path [^>]+/>", src))
    return vb, paths


CLOSING_VB, CLOSING = svg_paths("closing.svg")
LOCKUP_VB, LOCKUP = svg_paths("closing-lockup.svg")
CANDIDATES = {n: svg_paths(f"{n}.svg") for n in ("round-robin", "two-of-four", "seal-row")}
RING_PATH = re.findall(r"<path [^>]+/>", CLOSING)[0]
DISC_REST = '<path d="M20 25A5 5 0 1 1 30 25A5 5 0 1 1 20 25Z"/>'
DISC_FAR = '<path d="M23.435 28.435A5 5 0 1 1 33.435 28.435A5 5 0 1 1 23.435 28.435Z"/>'


def mark_svg(size: int, label: str | None = "Q-Vault") -> str:
    a = f'role="img" aria-label="{esc(label)}"' if label else 'aria-hidden="true" focusable="false"'
    return f'<svg width="{size}" height="{size}" viewBox="{CLOSING_VB}" fill="currentColor" {a}>{CLOSING}</svg>'


def lockup_svg(height: float, label: str | None = "Q-Vault") -> str:
    x0, y0, w, h = (float(v) for v in LOCKUP_VB.split())
    width = round(w / h * height, 2)
    a = f'role="img" aria-label="{esc(label)}"' if label else 'aria-hidden="true" focusable="false"'
    return (f'<svg width="{width}" height="{height}" viewBox="{LOCKUP_VB}" fill="currentColor" '
            f'{a}>{LOCKUP}</svg>')


# ----------------------------------------------------------------------------------------- icons

ICONS = {
    "home": '<path d="M2.75 6.9 8 2.5l5.25 4.4V13a.75.75 0 0 1-.75.75H10.25V10.5a.75.75 0 0 0-.75-.75h-3a.75.75 0 0 0-.75.75v3.25H3.5a.75.75 0 0 1-.75-.75Z"/>',
    "inbox": '<path d="M2.25 9.25h3.1l.9 1.75h3.5l.9-1.75h3.1"/><path d="M4.1 3.25h7.8a.75.75 0 0 1 .7.5l1.15 3.4a.8.8 0 0 1 .05.26v4.84a.75.75 0 0 1-.75.75H3a.75.75 0 0 1-.75-.75V7.4a.8.8 0 0 1 .05-.26l1.15-3.4a.75.75 0 0 1 .65-.49Z"/>',
    "vault": '<rect x="2.25" y="2.75" width="11.5" height="10" rx="1.5"/><circle cx="7.25" cy="7.75" r="2.25"/><path d="M11.25 6.5v2.5M4.5 12.75v1M11.5 12.75v1"/>',
    "audit": '<path d="M4 2.25h5.5L12.75 5.5v7.75a.75.75 0 0 1-.75.75H4a.75.75 0 0 1-.75-.75V3A.75.75 0 0 1 4 2.25Z"/><path d="M5.75 7.75h4.5M5.75 10.25h4.5M5.75 5.25H8"/>',
    "members": '<circle cx="6" cy="5.25" r="2.25"/><path d="M1.75 13.25c.4-2.3 2.05-3.6 4.25-3.6s3.85 1.3 4.25 3.6"/><path d="M10.4 3.15a2.25 2.25 0 0 1 0 4.2M11.6 9.95c1.35.45 2.3 1.55 2.6 3.3"/>',
    "settings": '<path d="M2.5 4.5h5.25M11.1 4.5h2.4M2.5 11.5h2.4M8.25 11.5h5.25"/><circle cx="9.45" cy="4.5" r="1.7"/><circle cx="6.6" cy="11.5" r="1.7"/>',
    "docs": '<path d="M12.75 11.25V2.25H4.5A1.75 1.75 0 0 0 2.75 4v8.25"/><path d="M12.75 11.25H4.5a1.75 1.75 0 0 0 0 3.5h8.25Z"/>',
    "search": '<circle cx="7" cy="7" r="4.25"/><path d="m10.25 10.25 3.25 3.25"/>',
    "bell": '<path d="M4 10.75V7a4 4 0 1 1 8 0v3.75l1.25 1.5H2.75Z"/><path d="M6.4 13.75a1.65 1.65 0 0 0 3.2 0"/>',
    "help": '<circle cx="8" cy="8" r="6.25"/><path d="M6.25 6.3a1.8 1.8 0 1 1 2.6 1.6c-.5.25-.85.6-.85 1.15v.3"/><circle cx="8" cy="11.25" r=".85" fill="currentColor" stroke="none"/>',
    "chevron-down": '<path d="m4.5 6.25 3.5 3.5 3.5-3.5"/>',
    "chevron-right": '<path d="m6.25 4.5 3.5 3.5-3.5 3.5"/>',
    "chevron-left": '<path d="m9.75 4.5-3.5 3.5 3.5 3.5"/>',
    "chevrons": '<path d="m5.5 6.25 2.5-2.5 2.5 2.5M5.5 9.75l2.5 2.5 2.5-2.5"/>',
    "plus": '<path d="M8 3.25v9.5M3.25 8h9.5"/>',
    "copy": '<rect x="5.25" y="5.25" width="8.5" height="8.5" rx="1.5"/><path d="M10.75 5.25V3.75a1.5 1.5 0 0 0-1.5-1.5h-5.5a1.5 1.5 0 0 0-1.5 1.5v5.5a1.5 1.5 0 0 0 1.5 1.5h1.5"/>',
    "check": '<path d="m3.25 8.25 3 3 6.5-6.5"/>',
    "check-circle": '<circle cx="8" cy="8" r="6.25"/><path d="m5.4 8.2 1.85 1.85 3.35-3.6"/>',
    "x": '<path d="m4.25 4.25 7.5 7.5M11.75 4.25l-7.5 7.5"/>',
    "x-circle": '<circle cx="8" cy="8" r="6.25"/><path d="m5.9 5.9 4.2 4.2M10.1 5.9l-4.2 4.2"/>',
    "minus-circle": '<circle cx="8" cy="8" r="6.25"/><path d="M5.25 8h5.5"/>',
    "external": '<path d="M9.25 2.75h4v4M13.25 2.75 7.5 8.5"/><path d="M11.75 9.5v2.75a1 1 0 0 1-1 1h-7a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1H6.5"/>',
    "more": '<circle cx="3.5" cy="8" r="1.15" fill="currentColor" stroke="none"/><circle cx="8" cy="8" r="1.15" fill="currentColor" stroke="none"/><circle cx="12.5" cy="8" r="1.15" fill="currentColor" stroke="none"/>',
    "clip": '<path d="m12.6 7.4-4.95 4.95a2.75 2.75 0 0 1-3.9-3.9l5.3-5.3a1.85 1.85 0 0 1 2.6 2.6l-5.25 5.25a.95.95 0 0 1-1.35-1.35l4.7-4.7"/>',
    "clock": '<circle cx="8" cy="8" r="6.25"/><path d="M8 4.75V8l2.1 1.4"/>',
    "menu": '<path d="M2.5 4.25h11M2.5 8h11M2.5 11.75h11"/>',
    "sidebar": '<rect x="2.25" y="2.75" width="11.5" height="10.5" rx="1.5"/><path d="M6 2.75v10.5M10.5 6.25 8.75 8l1.75 1.75"/>',
    "info": '<circle cx="8" cy="8" r="6.25"/><path d="M8 7.25v3.75"/><circle cx="8" cy="5" r=".9" fill="currentColor" stroke="none"/>',
    "warning": '<path d="M7.13 2.75a1 1 0 0 1 1.74 0l5.2 9.25a1 1 0 0 1-.87 1.5H2.8a1 1 0 0 1-.87-1.5Z"/><path d="M8 6.25v3"/><circle cx="8" cy="11.25" r=".9" fill="currentColor" stroke="none"/>',
    "alert": '<circle cx="8" cy="8" r="6.25"/><path d="M8 4.75v3.75"/><circle cx="8" cy="10.9" r=".9" fill="currentColor" stroke="none"/>',
    "download": '<path d="M8 2.75v7.5M4.75 7.25 8 10.5l3.25-3.25M2.75 13.25h10.5"/>',
    "user-plus": '<circle cx="6.25" cy="5.25" r="2.25"/><path d="M2 13.25c.4-2.3 2.05-3.6 4.25-3.6 1.1 0 2.05.3 2.8.9M12 9v4.5M9.75 11.25h4.5"/>',
    "shield": '<path d="M8 2.25 3.25 4v3.75c0 2.9 2 5 4.75 6 2.75-1 4.75-3.1 4.75-6V4Z"/>',
    "signout": '<path d="M9.5 3.25H3.75v9.5H9.5M7 8h6.75M11.25 5.5 13.75 8l-2.5 2.5"/>',
    "user": '<circle cx="8" cy="5.5" r="2.75"/><path d="M2.75 13.75c.5-2.6 2.6-4 5.25-4s4.75 1.4 5.25 4"/>',
    "link": '<path d="M6.75 9.25a2.75 2.75 0 0 0 3.9 0l2.1-2.1a2.75 2.75 0 0 0-3.9-3.9l-.6.6"/><path d="M9.25 6.75a2.75 2.75 0 0 0-3.9 0l-2.1 2.1a2.75 2.75 0 0 0 3.9 3.9l.6-.6"/>',
    "trash": '<path d="M2.75 4.25h10.5M6.25 4.25V2.75h3.5v1.5M4.25 4.25l.6 8.6a.75.75 0 0 0 .75.65h4.8a.75.75 0 0 0 .75-.65l.6-8.6"/>',
    "keyboard": '<rect x="1.75" y="4" width="12.5" height="8" rx="1.5"/><path d="M4.25 6.5h.5M7.75 6.5h.5M11.25 6.5h.5M5.5 9.5h5"/>',
    "sparkle": '<path d="M8 2.5v3M8 10.5v3M2.5 8h3M10.5 8h3M4.1 4.1l1.8 1.8M10.1 10.1l1.8 1.8M11.9 4.1l-1.8 1.8M5.9 10.1l-1.8 1.8"/>',
    "pulse": '<path d="M1.75 8.25h2.8l1.7-4 3 8 1.7-4h3.3"/>',
    "mail": '<rect x="2" y="3.25" width="12" height="9.5" rx="1.5"/><path d="m2.5 4.25 5.5 4.25 5.5-4.25"/>',
    "inbox-empty": '<path d="M2.25 9.25h3.1l.9 1.75h3.5l.9-1.75h3.1"/><path d="M4.1 3.25h7.8a.75.75 0 0 1 .7.5l1.15 3.4a.8.8 0 0 1 .05.26v4.84a.75.75 0 0 1-.75.75H3a.75.75 0 0 1-.75-.75V7.4a.8.8 0 0 1 .05-.26l1.15-3.4a.75.75 0 0 1 .65-.49Z"/>',
    "filter": '<path d="M2.5 3.75h11l-4.25 5v4l-2.5 1v-5Z"/>',
}

SPRITE = ('<svg width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false"><defs>'
          + "".join(f'<symbol id="i-{k}" viewBox="0 0 16 16">{v}</symbol>' for k, v in ICONS.items())
          + "</defs></svg>")


def icon(name: str, cls: str = "") -> str:
    assert name in ICONS, name
    c = ("icon " + cls).strip()
    return f'<svg class="{c}" aria-hidden="true" focusable="false"><use href="#i-{name}"/></svg>'


# Loading is three quorum marks filling in turn, never a rotating ring: the logo is a ring, and a ring
# that spins would teach people to read the logo as "loading".
SPINNER = '<span class="spin" aria-hidden="true" hidden><i></i><i></i><i></i></span>'
SPINNER_ON = SPINNER.replace(" hidden>", ">")


# ----------------------------------------------------------------------------------------- small parts

def av(letter: str, size: int = 20, entity: bool = False, name: str | None = None) -> str:
    cls = f"av av--{size}" + (" av--entity" if entity else "")
    a = f' role="img" aria-label="{esc(name)}"' if name else ' aria-hidden="true"'
    return f'<span class="{cls}"{a}>{letter}</span>'


NAMES = {"Z": "Zaid", "H": "Hassan", "G": "Gracian", "A": "Atharv"}


def avs(letters, size: int = 20, more: int = 0, pair: bool = False) -> str:
    inner = "".join(av(x, size, name=NAMES.get(x)) for x in letters)
    if more:
        inner += f'<span class="avs__more" role="img" aria-label="{more} more">+{more}</span>'
    cls = "avs avs--pair" if pair else "avs"
    return f'<span class="{cls}">{inner}</span>'


def marks(filled: int, required: int, size: str = "sm", closing_last: bool = False, ident: str = "",
          label: str | None = None) -> str:
    out = []
    for i in range(required):
        cls = "mark" + (" is-on" if i < filled else "")
        extra = " data-closing-mark" if (closing_last and i == required - 1) else ""
        out.append(f'<span class="{cls}"{extra}></span>')
    idattr = f' id="{ident}"' if ident else ""
    lab = label or f"{filled} of {required} approvals"
    return (f'<span class="marks marks--{size}"{idattr} role="img" '
            f'aria-label="{esc(lab)}">{"".join(out)}</span>')


def badge(text: str, tone: str) -> str:
    return f'<span class="badge badge--{tone}">{esc(text)}</span>'


def tag(text: str) -> str:
    return f'<span class="tag">{esc(text)}</span>'


def type_tag(ty: str) -> str:
    """The decision type as a tag, except General: the default type needs no label."""
    return "" if ty == "General" else tag(ty)


def copy_btn(value: str, label: str, tip: str | None = None) -> str:
    return (f'<button class="copy" type="button" data-copy="{esc(value)}" aria-label="{esc(label)}" '
            f'data-tip="{esc(tip or label)}">{icon("copy", "copy__i")}{icon("check", "copy__ok")}</button>'
            f'<span class="copy__msg" role="status" aria-live="polite"></span>')


def short(v: str, head: int, tail: int) -> str:
    return v[:head] + "…" + v[-tail:]


def hv(full: str, head: int, tail: int, label: str, expand: bool = False, more: str = "Show full",
       less: str = "Show less", text: bool = False, full_html: str | None = None) -> str:
    """A hash, key, address or ID: mono, cut in the middle, with copy. Every truncated value also
    carries its full form ([data-full]), so the copy fallback selects the real value, never the cut one."""
    cls = "hv__v hv__v--text" if text else "hv__v"
    s = short(full, head, tail)
    fh = full_html if full_html is not None else esc(full)
    body = (f'<span class="{cls}" translate="no" data-short data-copy-target>{esc(s)}</span>'
            f'<span class="{cls}" translate="no" data-full hidden>{fh}</span>')
    tog = ""
    if expand:
        tog = (f'<button class="lbtn" type="button" data-expand aria-expanded="false" '
               f'data-more="{esc(more)}" data-less="{esc(less)}">{esc(more)}</button>')
    return f'<span class="hv" data-copy-scope>{body}{copy_btn(full, label)}{tog}</span>'


def mono_copy(value: str, label: str) -> str:
    return (f'<span class="hv" data-copy-scope><span class="hv__v" translate="no" data-copy-target>{esc(value)}</span>'
            f'{copy_btn(value, label)}</span>')


def addr_bold(a: str) -> str:
    h = a[2:]
    return f"0x<b>{h[:8]}</b>{h[8:-8]}<b>{h[-8:]}</b>"


ADDR_RE = re.compile(r"0x[0-9a-fA-F]{40}")


def addr_in_text(a: str) -> str:
    """An address inside the decision text: mono, first and last 4 bytes in semibold, and a <wbr>
    every 10 hex characters so a narrow screen breaks it only there. <wbr> adds no characters, so the
    text a person copies is byte-identical to what is signed."""
    h = a[2:]
    out = ["0x"]
    for i, ch in enumerate(h):
        if i and i % 10 == 0:
            out.append("<wbr>")
        if i in (0, 32):
            out.append("<b>")
        out.append(ch)
        if i in (7, 39):
            out.append("</b>")
    return f'<span class="dt-addr" translate="no">{"".join(out)}</span>'


def decision_html(text: str) -> str:
    """The decision text, escaped, with every address set in mono; the sentence stays serif."""
    parts, last = [], 0
    for m in ADDR_RE.finditer(text):
        parts.append(esc(text[last:m.start()]))
        parts.append(addr_in_text(m[0]))
        last = m.end()
    parts.append(esc(text[last:]))
    return "".join(parts)


S17 = "Check this code matches your phone."


def code_chip(label: str = "Decision code") -> str:
    lab = f'<span class="code__label">{esc(label)}</span>' if label else ""
    return (f'<span class="code" data-copy-scope>{lab}<span class="code__v" translate="no" data-copy-target>{CODE}</span>'
            f'{copy_btn(CODE, "Copy decision code", tip=S17)}</span>')


def tip_time(text: str, tip: str, dt: str, focusable: bool = True) -> str:
    """A relative time with its exact value. The exact value is in the accessible name as well as the
    tooltip, so assistive tech gets the precision too. In the touch frames it is not focusable."""
    exact = f'<span class="vh">, {esc(tip)}</span>'
    if not focusable:
        return f'<time datetime="{dt}">{esc(text)}{exact}</time>'
    return f'<time tabindex="0" datetime="{dt}" data-tip="{esc(tip)}">{esc(text)}{exact}</time>'


def kv(rows, cls: str = "kv", style: str = "") -> str:
    st = f' style="{style}"' if style else ""
    inner = "".join(f"<div{(' ' + extra) if extra else ''}><dt>{k}</dt><dd>{v}</dd></div>" for k, v, extra in rows)
    return f'<dl class="{cls}"{st}>{inner}</dl>'


def row(k, v, extra=""):
    return (k, v, extra)


# ----------------------------------------------------------------------------------------- the shell

def sidebar(p: str, active: str, live_count: bool = False) -> str:
    def item(icon_name, label, extra=""):
        cur = ' aria-current="page"' if label == active else ""
        return f'<a class="nav-i" href="#"{cur}>{icon(icon_name)}<span>{label}</span>{extra}</a>'

    # Only the decision exhibit's count follows the demo; Home is a separate, unchanging snapshot.
    live = " data-needs-count" if live_count else ""
    count = f'<span class="count" aria-label="3 need your signature"{live}>3</span>'
    return f'''<aside class="sb" aria-label="Sidebar"><div class="sb__in">
<div class="pop">
<button class="ws" type="button" aria-haspopup="menu" aria-expanded="false" data-pop="{p}-ws">{av("C", 24, entity=True)}<span class="ws__n">Calderwood Labs</span>{icon("chevrons")}</button>
<div class="pop__panel pop__panel--start menu" id="{p}-ws" role="menu" aria-label="Workspace" hidden>
<a class="menu__i" role="menuitemradio" aria-checked="true" tabindex="-1" href="#">{av("C", 20, entity=True)}Calderwood Labs{icon("check", "menu__check")}</a>
<div class="menu__sep" role="separator"></div>
<a class="menu__i" role="menuitem" tabindex="-1" href="#">{icon("settings")}Workspace settings</a>
<a class="menu__i" role="menuitem" tabindex="-1" href="#">{icon("user-plus")}Invite people</a>
<a class="menu__i" role="menuitem" tabindex="-1" href="#">{icon("plus")}Create workspace</a>
</div>
</div>
<nav class="nav" aria-label="Main">
{item("home", "Home")}
{item("inbox", "Approvals", count)}
{item("vault", "Vaults")}
{item("audit", "Audit")}
</nav>
<nav class="nav" aria-label="Workspace">
{item("members", "Members")}
{item("settings", "Settings")}
{item("docs", "Docs")}
</nav>
<div class="sb__foot"><button class="ib" type="button" aria-label="Collapse sidebar" data-tip="Collapse sidebar">{icon("sidebar")}</button></div>
</div></aside>'''


def appearance_seg(p: str, touch: bool = False) -> str:
    opts = []
    for v, lab in (("system", "System"), ("light", "Light"), ("dark", "Dark")):
        checked = " checked" if v == "system" else ""
        opts.append(f'<span class="seg__o"><input type="radio" name="{p}-theme" id="{p}-theme-{v}" value="{v}" '
                    f'data-theme-choice{checked}><label for="{p}-theme-{v}">{lab}</label></span>')
    cls = "seg seg--touch" if touch else "seg"
    return f'<div class="{cls}" role="radiogroup" aria-labelledby="{p}-theme-l">{"".join(opts)}</div>'


def topbar(p: str, crumbs_html: str) -> str:
    return f'''<header class="tb">
<nav class="crumbs" aria-label="Breadcrumb">{crumbs_html}</nav>
<div class="tb__end">
<button class="search" type="button" aria-label="Search or jump to, Ctrl K">{icon("search")}<span>Search or jump to…</span><kbd class="kbd">Ctrl K</kbd></button>
<div class="pop">
<button class="ib" type="button" aria-label="Notifications, 2 unread" aria-haspopup="dialog" aria-expanded="false" data-pop="{p}-bell">{icon("bell")}<span class="unread" aria-hidden="true"></span></button>
<div class="pop__panel notif" id="{p}-bell" role="dialog" aria-label="Notifications" hidden>
<div class="notif__hd"><p><b>Notifications</b> <span class="notif__n">2 unread</span></p><button class="lbtn lbtn--sm" type="button">Mark all as read</button></div>
<a class="notif__i" href="#">{av("H", 24, name="Hassan")}<div><p>Hassan approved <b>Top up the release deployer wallet</b>. It needs one more approval.</p><p class="notif__t">21 minutes ago</p></div></a>
<a class="notif__i" href="#">{av("A", 24, name="Atharv")}<div><p>Atharv asked for your approval on <b>Give Hassan write access to the production database</b>. Due today, 18:00 BST.</p><p class="notif__t">Today at 08:15</p></div></a>
<div class="notif__ft"><a class="lnk" href="#">Notification settings</a></div>
</div>
</div>
<div class="pop">
<button class="ib" type="button" aria-label="Help" aria-haspopup="menu" aria-expanded="false" data-pop="{p}-help">{icon("help")}</button>
<div class="pop__panel menu" id="{p}-help" role="menu" aria-label="Help" hidden>
<a class="menu__i" role="menuitem" tabindex="-1" href="#">{icon("docs")}Docs</a>
<a class="menu__i" role="menuitem" tabindex="-1" href="#">{icon("keyboard")}Keyboard shortcuts<kbd class="kbd">?</kbd></a>
<a class="menu__i" role="menuitem" tabindex="-1" href="#">{icon("sparkle")}What’s new</a>
<a class="menu__i" role="menuitem" tabindex="-1" href="#">{icon("pulse")}Status</a>
<a class="menu__i" role="menuitem" tabindex="-1" href="#">{icon("mail")}Contact</a>
</div>
</div>
<div class="pop">
<button class="avbtn" type="button" aria-label="Account, Zaid" aria-haspopup="dialog" aria-expanded="false" data-pop="{p}-acct">{av("Z", 24)}</button>
<div class="pop__panel menu" id="{p}-acct" role="dialog" aria-label="Account" hidden>
<div class="menu__head"><b>Zaid</b><span>Owner, Calderwood Labs</span></div>
<div class="menu__sep"></div>
<a class="menu__i" href="#">{icon("user")}Account</a>
<a class="menu__i" href="#">{icon("bell")}Notifications</a>
<a class="menu__i" href="#">{icon("shield")}Security</a>
<div class="menu__sep"></div>
<div class="menu__row"><span id="{p}-theme-l">Appearance</span>{appearance_seg(p)}</div>
<div class="menu__sep"></div>
<a class="menu__i" href="#">{icon("signout")}Sign out</a>
</div>
</div>
</div>
</header>'''


def crumbs(*parts: str) -> str:
    out = []
    for i, part in enumerate(parts):
        if i:
            out.append('<span class="crumbs__s" aria-hidden="true">/</span>')
        if i == len(parts) - 1:
            out.append(f'<span class="crumbs__c" aria-current="page">{esc(part)}</span>')
        else:
            out.append(f'<a href="#">{esc(part)}</a>')
    return "".join(out)


def screen(p: str, active: str, crumbs_html: str, content: str, label: str, live_count: bool = False) -> str:
    return f'''<div class="screen" role="group" aria-roledescription="screen" aria-label="{esc(label)}"><div class="app">
{sidebar(p, active, live_count)}
<div class="mainc">
{topbar(p, crumbs_html)}
<div class="content">{content}</div>
</div>
</div></div>'''


# ----------------------------------------------------------------------------------------- the decision page

def more_menu(p: str) -> str:
    return f'''<div class="pop">
<button class="btn btn--secondary btn--icon" type="button" aria-label="More actions" aria-haspopup="menu" aria-expanded="false" data-pop="{p}-more">{icon("more")}</button>
<div class="pop__panel menu" id="{p}-more" role="menu" aria-label="More actions" hidden>
<button class="menu__i" role="menuitem" tabindex="-1" type="button" data-action="evidence">{icon("download")}Export for verification</button>
<button class="menu__i" role="menuitem" tabindex="-1" type="button" data-action="copy-link" data-url="{LINK}">{icon("link")}Copy link</button>
<a class="menu__i" role="menuitem" tabindex="-1" href="#">{icon("audit")}View in audit log</a>
</div>
</div>'''


TIMES = {
    "raised": ("Today at 09:41 BST", "Sun 4 Oct 2026, 09:41:17 BST", "2026-10-04T09:41:17+01:00"),
    "hassan": ("Today at 09:58 BST", "Sun 4 Oct 2026, 09:58:42 BST", "2026-10-04T09:58:42+01:00"),
    "you": ("Today at 10:24 BST", "Sun 4 Oct 2026, 10:24:05 BST", "2026-10-04T10:24:05+01:00"),
}

ENTRY_1286_A = illustrative("5b0e7c21", "a9d3f6c0", "entry 1286 approve")
ENTRY_1286_R = illustrative("8e41d2b7", "06fc93a1", "entry 1286 reject")
ENTRY_1287 = illustrative("c2a7f90d", "71e5b348", "entry 1287 approved")
SIG_ZR = illustrative("4f8a2c6e", "b1d09e37", "sig zaid reject")
FP_LOG = "411c3ff255410215"
FP_WITNESS = "e071c110137b05b2"


def ttime(key: str, cls: str = "tl__time") -> str:
    t, tip, dt = TIMES[key]
    return (f'<time class="{cls}" tabindex="0" datetime="{dt}" data-tip="{esc(tip)}" data-tip-pos="end">'
            f'{esc(t)}<span class="vh">, {esc(tip)}</span></time>')


GLYPH_X = ('<svg class="tl__g tl__g--no" viewBox="0 0 10 10" aria-hidden="true" focusable="false">'
           '<path d="M3.4 3.4l3.2 3.2M6.6 3.4L3.4 6.6"/></svg>')


def glyph(kind: str) -> str:
    """The signer's state as a small badge on the avatar: one marker per row, never a second circle."""
    if kind == "no":
        return GLYPH_X
    return f'<span class="tl__g tl__g--{kind}" aria-hidden="true"></span>'


def timeline(compact: bool = False) -> str:
    def when(key):
        if not compact:
            return ttime(key)
        return ""

    def sub_time(key):
        if not compact:
            return ""
        t, tip, dt = TIMES[key]
        return f'<p class="tl__sub"><time datetime="{dt}">{esc(t)}</time></p>'

    you_glyph = (f'<span data-show="open">{glyph("wait")}</span><span data-show="approved" hidden>{glyph("ok")}</span>'
                 f'<span data-show="rejected" hidden>{glyph("no")}</span>')
    you_time = "" if compact else f'<span data-show="approved rejected" hidden>{ttime("you")}</span>'
    cls = "tl tl--compact" if compact else "tl"
    return f'''<ol class="{cls}" aria-label="Signatures in order">
<li class="tl__i"><span class="tl__who">{av("G", 24, name="Gracian")}</span><div class="tl__b"><p><b>Gracian</b> raised this payment</p>{sub_time("raised")}</div>{when("raised")}</li>
<li class="tl__i"><span class="tl__who">{av("H", 24, name="Hassan")}{glyph("ok")}</span><div class="tl__b"><p><b>Hassan</b> approved on his phone</p><p class="tl__sub">Signed 1 of 2</p>{sub_time("hassan")}</div>{when("hassan")}</li>
<li class="tl__i tl__i--you"><span class="tl__who">{av("Z", 24, name="Zaid")}{you_glyph}</span><div class="tl__b"><div data-show="open"><p><b>You</b></p><p class="tl__sub">Your approval completes this payment.</p></div><div data-show="approved" hidden><p><b>You</b> approved</p><p class="tl__sub">Signed 2 of 2</p>{sub_time("you")}</div><div data-show="rejected" hidden><p><b>You</b> rejected</p><p class="tl__q" data-reject-reason>“0.25 ETH is more than the deployer needs this month.”</p>{sub_time("you")}</div></div>{you_time}</li>
<li class="tl__i is-before-next" data-show="open rejected"><span class="tl__who">{avs("AG", 24, pair=True)}{glyph("wait")}</span><div class="tl__b"><p><b>Atharv</b> or <b>Gracian</b> can also approve</p></div></li>
<li class="tl__i tl__i--muted"><span class="tl__who">{av("O", 24, entity=True, name="Operations treasury")}</span><div class="tl__b"><div data-show="open rejected"><p>Then the treasury pays 0.25 ETH</p><p class="tl__sub">Usually within a few minutes of the second approval</p></div><div data-show="approved" hidden><p class="kv__line"><span class="tl__q">The treasury pays 0.25 ETH</span>{badge("Queued", "info")}</p><p class="tl__sub">The treasury pays at its next check, within a few minutes.</p></div></div></li>
</ol>'''


def check_li(title: str, desc: str, show: str = "") -> str:
    attr = f' data-show="{show}"' + ("" if "open" in show.split() else " hidden") if show else ""
    return (f'<li class="check"{attr}>{icon("check")}<div><p class="check__t">{esc(title)}</p>'
            f'<p class="check__d">{esc(desc)}</p></div></li>')


def checks_list() -> str:
    """Layer 2. The list follows the demo: after you sign, your signature is checked too, and the
    log and witness lines say exactly how far the witness has got."""
    return "".join([
        check_li("Contents match what was signed",
                 f"The text, amount, recipient and approval rule still produce code {CODE}, which every signature covers."),
        check_li("The text matches the payment",
                 "The decision text describes exactly the payment the treasury will make."),
        check_li("Recorded in the transparency log",
                 "Entry #1,284 recorded this decision with the same code. Hassan’s approval is entry #1,285.", "open"),
        check_li("Recorded in the transparency log",
                 "Entry #1,284 recorded this decision with the same code. Hassan’s approval is #1,285 and yours is #1,286.", "approved"),
        check_li("Recorded in the transparency log",
                 "Entry #1,284 recorded this decision with the same code. Hassan’s approval is #1,285 and your rejection is #1,286.", "rejected"),
        check_li("Hassan’s signature is valid", "Checked against the phone key registered to him."),
        check_li("Your signature is valid", "Checked against the password key the Operations treasury holds for you.", "approved"),
        check_li("Your rejection is valid", "Checked against your password key.", "rejected"),
        check_li("Witnessed", "An independent witness co-signed the log, including both entries, at 09:59 BST.", "open"),
        check_li("Witnessed", "The witness co-signed the log up to Hassan’s approval at 09:59 BST. Yours is added at its next check, within a minute.", "approved rejected"),
    ])


def checks_count() -> str:
    return ('<span data-show="open">5 checks passed</span>'
            '<span data-show="approved rejected" hidden>6 checks passed</span>')


def outcome() -> str:
    return ('<p class="outcome" data-show="open rejected"><b>Nothing has been paid.</b> This payment needs one more approval by Tue 6 Oct, 17:00 BST.</p>'
            '<p class="outcome" data-show="approved" hidden><b>Approved, not paid yet.</b> The treasury pays 0.25 ETH at its next check, within a few minutes.</p>')


def sig_record(who_html: str, sig: str, fp: str, entry: str, when: str, decision: str, signer: int,
               tsig: str | None = None, extra: str = "", note: str = "") -> str:
    msg = kv([
        row("Signed message", f'<span class="kv__line">“QVAULT-SIG-v1:VOTE” with payload hash {hv(PAYLOAD_HASH, 8, 8, "Copy payload hash")}</span>'
                              f'<span class="kv__line">decision “{decision}”, signer {signer}</span>'),
        *([row("Also signed", f'<span class="kv__line">Treasury digest {hv(DIGEST, 10, 8, "Copy treasury digest")}</span>'
                              f'<span class="kv__cap">Payment approvals sign the digest the treasury contract checks</span>'),
           row("Treasury signature SHA-256", hv(tsig, 8, 8, "Copy treasury signature hash"))] if tsig else []),
    ], style="--kv-label:200px")
    foot = f'<p class="sigrec__cap">{note}</p>' if note else ""
    return f'''<div class="panel"{extra}>
<div class="sigrec__hd">{who_html}<span class="pass">{icon("check-circle")}Valid</span></div>
<div class="sigrec__grid">
<div class="sigrec__c"><span class="sigrec__l">Algorithm</span><span>ML-DSA-65</span><span class="kv__cap">FIPS 204, category 3</span></div>
<div class="sigrec__c"><span class="sigrec__l">Signature size</span><span>3,309 bytes</span></div>
<div class="sigrec__c"><span class="sigrec__l">Public key</span><span>1,952 bytes</span></div>
<div class="sigrec__c"><span class="sigrec__l">Log entry</span><span>{entry}</span><span class="kv__cap">{when}</span></div>
<div class="sigrec__c"><span class="sigrec__l">Key fingerprint</span>{mono_copy(fp, "Copy key fingerprint")}</div>
<div class="sigrec__c"><span class="sigrec__l">Signature SHA-256</span>{hv(sig, 8, 8, "Copy signature hash")}</div>
</div>
<div class="sigrec__msg">{msg}</div>
{foot}
</div>'''


def to_value(etherscan: bool) -> str:
    to = hv(RECIPIENT, 6, 4, "Copy recipient address", expand=True, more="Show full address",
            less="Show less", full_html=addr_bold(RECIPIENT))
    link = f'<a class="lnk" href="#">View on Etherscan {icon("external")}</a>' if etherscan else ""
    return (f'<span class="kv__line">{to}{link}</span>'
            f'<span class="kv__cap">First payment from Operations to this address</span>')


def decision_content() -> str:
    p = "d"
    payment = kv([
        row("Amount", '<span class="amount">0.25 ETH</span>'),
        row("To", to_value(True)),
        row("From", f'<span class="kv__line"><span>Operations treasury</span>{hv(TREASURY, 6, 4, "Copy treasury address")}'
                    f'<a class="lnk" href="#">View on Etherscan {icon("external")}</a></span>'),
        row("Network", f'<span class="kv__line">Sepolia {tag("Testnet")}</span>'),
        row("Treasury balance", '1.8420 ETH<span class="kv__cap">1.5920 ETH after this payment</span>'),
        row("Payout", '<span data-show="open rejected">Starts after the second approval.</span>'
                      f'<span data-show="approved" hidden><span class="kv__line">{badge("Queued", "info")}<span>The treasury pays at its next check, within a few minutes.</span></span></span>'),
        row("Approvals valid until", 'Fri 9 Oct, 17:00 BST<span class="kv__cap">After this the treasury refuses the payment, even if it is approved.</span>'),
    ])
    # The aside holds only what the page does not already say: no amount, raiser, due time or code.
    details = kv([
        row("Vault", '<a class="lnk" href="#">Operations</a>'),
        row("Type", "Payment"),
        row("Rule when raised", 'Any 2 of 4<span class="kv__cap">Zaid, Hassan, Gracian, Atharv. Later changes to the vault’s rule don’t apply to this decision.</span>'),
        row("Raised", "Sun 4 Oct, 09:41 BST"),
        row("Decision ID", hv(DECISION_ID, 8, 6, "Copy decision ID")),
        row("You sign with", 'Password key<span class="kv__cap">The Operations treasury holds this key for you, so you approve its payments here. Your phone can still open this decision and show its code.</span>'),
        row("Public record", '<span class="muted" data-show="open rejected">Can be shared once this is decided.</span>'
                               '<span class="muted" data-show="approved" hidden>Can be shared now, from More actions.</span>'),
    ], cls="kv kv--plain")

    payload = kv([
        row("Payload hash", hv(PAYLOAD_HASH, 8, 8, "Copy payload hash", expand=True)),
        row("Recomputed now", f'<span class="pass">{icon("check")}Same as signed</span>'),
        row("In audit log entry #1,284", f'<span class="pass">{icon("check")}Same as signed</span>'),
        row("Decision code", f'{code_chip("")}<span class="kv__cap">The first 8 characters of the payload hash</span>'),
        row("Decision ID", hv(DECISION_ID, 8, 6, "Copy decision ID")),
        row("Nonce", hv(NONCE, 8, 8, "Copy nonce")),
        row("Raised at", "Sun 4 Oct 2026, 09:41:17 BST"),
        row("Approval rule", "2 of 4: Zaid, Hassan, Gracian, Atharv"),
        row("Attachment", "None"),
        row("Decision payload", '664 bytes, domain tag “QVAULT-SIG-v1:PROPOSAL”<span class="kv__cap">Its SHA-256 is the payload hash. Each signature covers the payload hash, not these bytes directly.</span>'),
        row("Payment in the payload", f'<span class="kv__line">Kind “eth_transfer” on chain 11155111, to {hv(RECIPIENT, 6, 4, "Copy recipient address", expand=True, more="Show full address", full_html=addr_bold(RECIPIENT))}</span>'
                                      '<span class="kv__cap">250000000000000000 wei, no call data, call gas 100,000, valid until 1791561600, treasury configuration 0</span>'),
        row("Treasury digest", hv(DIGEST, 10, 8, "Copy treasury digest")),
    ], style="--kv-label:200px")
    log = kv([
        row("Entry #1,284", f'<span class="kv__line">Decision raised. Entry hash {hv(ENTRY_1284, 8, 8, "Copy entry hash")}</span>'),
        row("Entry #1,285", f'<span class="kv__line">Hassan approved. Entry hash {hv(ENTRY_1285, 8, 8, "Copy entry hash")}</span>'
                            f'<span class="kv__line">Leaf hash {hv(LEAF_1285, 8, 8, "Copy leaf hash")}</span>'),
        row("Entry #1,286", f'<span class="kv__line">You approved. Entry hash {hv(ENTRY_1286_A, 8, 8, "Copy entry hash")}</span>', 'data-show="approved" hidden'),
        row("Entry #1,287", f'<span class="kv__line">Decision approved. Entry hash {hv(ENTRY_1287, 8, 8, "Copy entry hash")}</span>', 'data-show="approved" hidden'),
        row("Entry #1,286", f'<span class="kv__line">You rejected. Entry hash {hv(ENTRY_1286_R, 8, 8, "Copy entry hash")}</span>', 'data-show="rejected" hidden'),
        row("Checkpoint", f'<span class="kv__line">1,286 entries, root {hv(ROOT_1286, 8, 8, "Copy root hash")}</span>'
                          f'<span class="kv__cap kv__line">Signed by the log key, ML-DSA-65, fingerprint {mono_copy(FP_LOG, "Copy log key fingerprint")}</span>'),
        row("Witness", 'witness-1, ML-DSA-87 (FIPS 204, category 5)'
                       f'<span class="kv__cap kv__line">Key fingerprint {mono_copy(FP_WITNESS, "Copy witness key fingerprint")}</span>'
                       '<span class="kv__cap">Co-signed Sun 4 Oct 2026, 09:59:31 BST</span>'),
        row("Inclusion proof for #1,285", "4 hashes. Included in the export."),
        row("Log status", '<span data-show="open">1,286 entries. The witness has co-signed up to the newest, 0 entries behind.</span>'
                          '<span data-show="approved" hidden>1,288 entries. The witness is 2 entries behind; it checks every minute.</span>'
                          '<span data-show="rejected" hidden>1,287 entries. The witness is 1 entry behind; it checks every minute.</span>'),
    ], style="--kv-label:200px")

    hassan_who = f'{av("H", 24, name="Hassan")}<p><b>Hassan</b> approved with his phone key</p>'
    zaid_ok = f'{av("Z", 24, name="Zaid")}<p><b>You</b> approved with your password key</p>'
    zaid_no = f'{av("Z", 24, name="Zaid")}<p><b>You</b> rejected with your password key</p>'
    zaid_note = "Made by Q-Vault with your password key, which it stores encrypted and unlocks only with your password."
    you_when = "Sun 4 Oct 2026, 10:24:05 BST"

    return f'''<article class="dp" data-demo="decision" data-state="open">
<header class="ph">
<div class="ph__row">
<div class="ph__tw"><h1 class="ph__t" id="d-title" tabindex="-1">Top up the release deployer wallet</h1>
<span data-show="open">{badge("Needs your signature", "warning")}</span><span data-show="approved" hidden>{badge("Approved", "success")}</span><span data-show="rejected" hidden>{badge("Waiting on 1", "neutral")}</span></div>
<div class="ph__act">
<span data-show="open" class="ph__act"><button class="btn btn--secondary" type="button" data-open-dialog="reject">Reject</button><button class="btn btn--primary" type="button" data-open-dialog="approve">Approve</button></span>
<span data-show="approved" hidden class="ph__done">You approved this today at 10:24 BST.</span>
<span data-show="rejected" hidden class="ph__done">You rejected this today at 10:24 BST.</span>
{more_menu(p)}
</div>
</div>
<dl class="facts">
<div class="fact"><dt>Raised by</dt><dd>{av("G", 20, name="Gracian")}<span>Gracian, {tip_time("38 minutes ago", "Sun 4 Oct 2026, 09:41 BST", "2026-10-04T09:41:17+01:00")}</span></dd></div>
<div class="fact"><dt>Due</dt><dd>Tue 6 Oct, 17:00 BST</dd></div>
<div class="fact"><dt>Decision code</dt><dd>{code_chip("")}</dd></div>
</dl>
<p class="vh" role="status" aria-live="polite" id="d-live"></p>
</header>
<div class="tabs tabs--page" role="tablist" aria-label="Decision">
<button class="tab" role="tab" type="button" id="d-tab-overview" aria-controls="d-panel-overview" aria-selected="true"><span class="tab__l">Overview</span></button>
<button class="tab" role="tab" type="button" id="d-tab-evidence" aria-controls="d-panel-evidence" aria-selected="false" tabindex="-1"><span class="tab__l">Evidence</span></button>
<button class="tab" role="tab" type="button" id="d-tab-technical" aria-controls="d-panel-technical" aria-selected="false" tabindex="-1"><span class="tab__l">Technical</span></button>
</div>
<div class="detail">
<div class="dmain">
<div class="tabpanel" role="tabpanel" id="d-panel-overview" aria-labelledby="d-tab-overview" tabindex="0">
<div class="dstack">
<section class="dblk" aria-label="Decision text">
<p class="dtext">{decision_html(DECISION_TEXT)}</p>
<p class="dtext__cap">Generated from the payment below. This is the text every approver signs.</p>
</section>
<section class="dblk" aria-labelledby="d-sig-t">
<h2 class="dblk__t" id="d-sig-t">Signatures</h2>
<div class="seal-line">{marks(1, 2, "lg", closing_last=True, ident="d-seal")}<span class="seal-line__n"><span data-show="open rejected">1 of 2 approvals</span><span data-show="approved" hidden>2 of 2 approvals</span></span></div>
<p class="muted" data-show="open">One more approval pays this. Any 2 of Zaid, Hassan, Gracian and Atharv can approve.</p>
<p class="muted" data-show="approved" hidden>Approved. Your signature completed the quorum, so the treasury pays 0.25 ETH next.</p>
<p class="muted" data-show="rejected" hidden>One more approval pays this. It is rejected only if Gracian and Atharv reject it too.</p>
{timeline()}
</section>
<section class="dblk" aria-labelledby="d-pay-t">
<h2 class="dblk__t" id="d-pay-t">Payment</h2>
<div class="panel">{payment}</div>
<p class="dfoot">The treasury sends exactly 0.25 ETH. Q-Vault covers the network fee.</p>
</section>
</div>
</div>
<div class="tabpanel" role="tabpanel" id="d-panel-evidence" aria-labelledby="d-tab-evidence" tabindex="0" hidden>
<div class="stack">
{outcome()}
<div class="panel">
<div class="checks__hd">{icon("check-circle")}{checks_count()}</div>
<ul>{checks_list()}</ul>
</div>
<p><button class="lbtn" type="button" data-goto-tab="d-tab-technical">See the technical details</button></p>
</div>
</div>
<div class="tabpanel" role="tabpanel" id="d-panel-technical" aria-labelledby="d-tab-technical" tabindex="0" hidden>
<div class="tech">
{outcome()}
<section aria-labelledby="d-t-payload"><h3 class="tech__t" id="d-t-payload">Decision payload</h3>
<div class="panel">{payload}</div>
<p class="tech__note">The title, Top up the release deployer wallet, is a label for lists. It isn’t part of the payload, so no signature covers it.</p>
<details class="raw"><summary>{icon("chevron-right")}Raw decision payload <span class="subtle">664 bytes</span></summary><pre translate="no">{esc(RAW)}</pre></details>
</section>
<section aria-labelledby="d-t-sigs"><h3 class="tech__t" id="d-t-sigs">Signatures</h3>
<div class="stack">
{sig_record(hassan_who, SIG_H, "f019dc7ed40adbba", "#1,285", "Sun 4 Oct 2026, 09:58:42 BST", "approve", 2, tsig=TSIG_H, note="A phone key never leaves the phone that holds it, so Q-Vault could not have made Hassan’s signature.")}
{sig_record(zaid_ok, SIG_Z, "7879dce64eab4126", "#1,286", you_when, "approve", 1, tsig=TSIG_Z, extra=' data-show="approved" hidden', note=zaid_note)}
{sig_record(zaid_no, SIG_ZR, "7879dce64eab4126", "#1,286", you_when, "reject", 1, extra=' data-show="rejected" hidden', note=zaid_note + " A rejection carries no treasury signature.")}
</div>
</section>
<section aria-labelledby="d-t-log"><h3 class="tech__t" id="d-t-log">Transparency log</h3>
<div class="panel">{log}</div>
</section>
<section aria-labelledby="d-t-act"><h3 class="tech__t" id="d-t-act">Check it yourself</h3>
<div class="actrow"><button class="btn btn--secondary" type="button">{icon("download")}Export for verification</button><a class="lnk" href="#">Open the offline verifier</a></div>
<p class="tech__note">The export checks every signature, the log entry and the witness in your browser. Nothing is uploaded.</p>
</section>
</div>
</div>
</div>
<aside class="daside" aria-labelledby="d-det-t">
<h2 class="dblk__t" id="d-det-t">Details</h2>
{details}
</aside>
</div>
</article>'''


# ----------------------------------------------------------------------------------------- home

NEEDS = [
    dict(t="Give Hassan write access to the production database", v="Engineering access", ty="Production access",
         f=1, caps=["Gracian approved"], due="Today, 18:00 BST", rel="in 7 hours", soon=True, short="Today, 18:00"),
    dict(t="Top up the release deployer wallet", v="Operations", ty="Payment", amt="0.25 ETH", f=1,
         caps=["Hassan approved"], due="Tue 6 Oct, 17:00 BST", rel="in 2 days", href="#decision", short="Tue 6 Oct, 17:00"),
    dict(t="Move the weekly release to Thursdays from 15 October", v="Operations", ty="General", f=0, caps=[],
         due="Thu 8 Oct, 12:00 BST", rel="in 4 days", short="Thu 8 Oct, 12:00"),
]
DUE = [
    dict(t="Ship release 0.9 to production on Monday", v="Engineering access", ty="General", f=1,
         wait="Waiting on 1", caps=["Waiting on 1", "Gracian or Atharv"],
         due="Tomorrow, 09:00 BST", rel="in 22 hours", soon=True, short="Tomorrow, 09:00"),
    dict(t="Send 0.5 ETH to the staging gas wallet", v="Operations", ty="Payment", amt="0.5 ETH", f=0,
         wait="Waiting on 2", caps=["Waiting on 2", "You rejected. It’s rejected only if 3 of 4 reject."],
         due="Tomorrow, 17:00 BST", rel="in 30 hours", short="Tomorrow, 17:00"),
]
WAITING = [
    dict(t="Fund the QA wallet for the October test sprint", v="Operations", ty="Payment", amt="0.12 ETH", f=1,
         wait="Waiting on 1", caps=["Waiting on 1", "Hassan, Gracian or Atharv"],
         due="Fri 9 Oct, 17:00 BST", rel="in 5 days", short="Fri 9 Oct, 17:00"),
    dict(t="Turn off password sign-in for the staging dashboard", v="Engineering access", ty="General", f=1,
         wait="Waiting on 1", caps=["Waiting on 1", "Gracian or Atharv"],
         due="Mon 12 Oct, 12:00 BST", rel="in 8 days", short="Mon 12 Oct, 12:00"),
    dict(t="Renew the node provider plan for 12 months", v="Operations", ty="Contract", f=1,
         wait="Waiting on 1", caps=["Waiting on 1", "Hassan, Gracian or Atharv"],
         due="Wed 14 Oct, 12:00 BST", rel="in 10 days", clip="node-provider-renewal-2026.pdf", short="Wed 14 Oct, 12:00"),
]


def wl_row(d: dict) -> str:
    meta = f'<span>{esc(d["v"])}</span>{type_tag(d["ty"])}'
    if d.get("clip"):
        meta += f'<span class="kv__line" role="img" aria-label="Attachment: {esc(d["clip"])}">{icon("clip")}</span>'
    caps = "".join(f'<span class="wl__note">{esc(c)}</span>' for c in d.get("caps", []))
    soon = " is-soon" if d.get("soon") else ""
    clock = icon("clock") if d.get("soon") else ""
    href = d.get("href", "#")
    return f'''<li><a class="wl__row" href="{href}">
<span class="wl__dec"><span class="wl__t">{esc(d["t"])}</span><span class="wl__m">{meta}</span></span>
<span class="wl__amt">{esc(d.get("amt", ""))}</span>
<span class="wl__sig"><span class="wl__s1">{marks(d["f"], 2, "sm")}<span>{d["f"]} of 2</span></span>{caps}</span>
<span class="wl__due{soon}"><span class="wl__abs">{clock}{esc(d["due"])}</span><span class="wl__rel">{esc(d["rel"])}</span></span>
</a></li>'''


def wl(rows, foot: str) -> str:
    """All three Home lists share one column template, so the columns line up down the page."""
    return f'''<div class="wl">
<div class="wl__hd" aria-hidden="true"><span>Decision</span><span class="r">Amount</span><span>Signatures</span><span>Due</span></div>
<ul>{"".join(wl_row(r) for r in rows)}</ul>
<div class="wl__ft">{foot}</div>
</div>'''


ACTIVITY = [
    dict(av="H", s='Hassan approved <b>Top up the release deployer wallet</b>', t="21 minutes ago", tip="Sun 4 Oct 2026, 09:58 BST", dt="2026-10-04T09:58:42+01:00"),
    dict(av="G", s='Gracian approved <b>Give Hassan write access to the production database</b>', t="Today at 08:52", tip="Sun 4 Oct 2026, 08:52 BST", dt="2026-10-04T08:52:00+01:00"),
    dict(ent=("O", "Operations"), s='The Operations treasury paid 0.1 ETH for <b>Fund the load-test wallet</b>', t="Yesterday at 16:42", tip="Sat 3 Oct 2026, 16:42 BST", dt="2026-10-03T16:42:00+01:00", badge=("Paid", "success")),
    dict(av="H", s='Hassan raised <b>Move the weekly release to Thursdays from 15 October</b>', t="Yesterday at 16:10", tip="Sat 3 Oct 2026, 16:10 BST", dt="2026-10-03T16:10:00+01:00"),
    dict(pair="GA", s='Gracian and Atharv rejected <b>Give the contractor SSH access to the build server</b>. Gracian’s reason: <span class="act__q">“Use the bastion host instead.”</span>', t="Yesterday at 11:05", tip="Sat 3 Oct 2026, 11:05 BST", dt="2026-10-03T11:05:00+01:00", badge=("Rejected", "critical")),
    dict(ent=("E", "Engineering access"), s='<b>Require hardware keys for production sign-in</b> expired with 1 of 2 approvals', t="Yesterday at 09:00", tip="Sat 3 Oct 2026, 09:00 BST", dt="2026-10-03T09:00:00+01:00", badge=("Expired", "neutral")),
]


def act_item(d: dict, size: int = 24, focusable: bool = True) -> str:
    if d.get("pair"):
        who = avs(d["pair"], 20, pair=True)
    elif d.get("ent"):
        who = av(d["ent"][0], size, entity=True, name=d["ent"][1])
    else:
        who = av(d["av"], size, name=NAMES[d["av"]])
    b = badge(*d["badge"]) if d.get("badge") else ""
    return (f'<li class="act__i">{who}<div><p class="act__s">{d["s"]}</p>'
            f'<p class="act__meta">{tip_time(d["t"], d["tip"], d["dt"], focusable)}{b}</p></div></li>')


def home_content() -> str:
    return f'''<div class="hp">
<header class="hp__hd">
<div><h1 class="t-title">Three decisions need your signature</h1><p class="muted">One is due today.</p></div>
<button class="btn btn--primary" type="button">{icon("plus")}New decision</button>
</header>
<div class="hp__cols">
<div class="hp__work">
<section class="wsec" aria-labelledby="h-s1"><div class="wsec__hd"><h2 class="wsec__t" id="h-s1">Yours to sign</h2><span class="count">3</span></div>
{wl(NEEDS, '<a class="lnk" href="#">Open Approvals</a>')}
</section>
<section class="wsec" aria-labelledby="h-s2"><div class="wsec__hd"><h2 class="wsec__t" id="h-s2">Due soon</h2><span class="count">2</span><span class="wsec__n">Next 48 hours</span></div>
{wl(DUE, 'Nothing else is due in the next 48 hours.')}
</section>
<section class="wsec" aria-labelledby="h-s3"><div class="wsec__hd"><h2 class="wsec__t" id="h-s3">Waiting on others</h2><span class="count">3</span></div>
{wl(WAITING, '<a class="lnk" href="#">See all in Approvals</a>')}
</section>
</div>
<section class="act" aria-labelledby="h-act"><h2 class="wsec__t" id="h-act">Recent activity</h2>
<ol class="act__list">{"".join(act_item(d) for d in ACTIVITY)}</ol>
<p><a class="lnk" href="#">Open the audit log</a></p>
</section>
</div>
</div>'''


# ----------------------------------------------------------------------------------------- phone (mobile web)

def m_topbar_home(p: str) -> str:
    return f'''<header class="mtb">
<button class="ib ib--touch" type="button" aria-label="Open menu">{icon("menu")}</button>
<span class="mtb__t">Home</span>
<button class="ib" type="button" aria-label="Search">{icon("search")}</button>
<button class="ib" type="button" aria-label="Notifications, 2 unread">{icon("bell")}<span class="unread" aria-hidden="true"></span></button>
<button class="ib" type="button" aria-label="Account, Zaid">{av("Z", 24)}</button>
</header>'''


def m_row(d: dict) -> str:
    amt = f'<span>{esc(d["amt"])}</span>' if d.get("amt") else ""
    wait = f'<span class="mrow__w">{esc(d["wait"])}</span>' if d.get("wait") else ""
    soon = " is-soon" if d.get("soon") else ""
    clock = icon("clock") if d.get("soon") else ""
    clip = icon("clip") if d.get("clip") else ""
    return f'''<li><a class="mrow" href="#">
<span class="mrow__t">{esc(d["t"])}</span>
<span class="mrow__l"><span class="mrow__v">{esc(d["v"])} {type_tag(d["ty"])}{clip}</span>{amt}</span>
<span class="mrow__l"><span class="mrow__s">{marks(d["f"], 2, "sm")}<span>{d["f"]} of 2</span>{wait}</span><span class="mrow__due{soon}">{clock}{esc(d["short"])}</span></span>
</a></li>'''


def phone_home() -> str:
    return f'''<div class="phone" role="group" aria-roledescription="screen" aria-label="Home at 390 pixels wide"><div class="phone__sc" tabindex="0">
{m_topbar_home("p1")}
<div class="mc">
<header class="mhd">
<div class="mhd__row"><h1 class="t-title">Three decisions need your signature</h1><button class="btn btn--primary btn--touch" type="button">{icon("plus")}New</button></div>
<p class="muted">One is due today.</p>
</header>
<section class="msec" aria-labelledby="p1-s1"><div class="msec__hd"><h2 class="wsec__t" id="p1-s1">Yours to sign</h2><span class="count">3</span></div>
<ul class="ml">{"".join(m_row(d) for d in NEEDS)}</ul>
<a class="lnk mmore" href="#">Show all</a>
</section>
<section class="msec" aria-labelledby="p1-s2"><div class="msec__hd"><h2 class="wsec__t" id="p1-s2">Due soon</h2><span class="count">2</span><span class="wsec__n">Next 48 hours</span></div>
<ul class="ml">{"".join(m_row(d) for d in DUE)}</ul>
<p class="mnear">Nothing else is due in the next 48 hours.</p>
</section>
<section class="msec" aria-labelledby="p1-s3"><div class="msec__hd"><h2 class="wsec__t" id="p1-s3">Waiting on others</h2><span class="count">3</span></div>
<ul class="ml">{"".join(m_row(d) for d in WAITING)}</ul>
<a class="lnk mmore" href="#">Show all</a>
</section>
<section class="msec act" aria-labelledby="p1-act"><h2 class="wsec__t" id="p1-act">Recent activity</h2>
<ol class="act__list">{"".join(act_item(d, focusable=False) for d in ACTIVITY[:4])}</ol>
<a class="lnk mmore" href="#">Open the audit log</a>
</section>
</div>
</div></div>'''


def m_decision_body(p: str, live: bool) -> str:
    """The phone decision page. live=False renders a copy without ids for the frame behind the sheet."""
    def ident(x):
        return f' id="{p}-{x}"' if live else ""

    if not live:
        return f'''<div class="mdp">
<div class="mdp__top">{badge("Needs your signature", "warning")}{code_chip()}</div>
<h1 class="t-title">Top up the release deployer wallet</h1>
<div class="mdp__meta"><p>Raised by <b>Gracian, 38 minutes ago</b></p><p>Due <b>Tue 6 Oct, 17:00 BST</b></p></div>
<p class="dtext">{decision_html(DECISION_TEXT)}</p>
</div>'''
    payment = kv([
        row("Amount", '<span class="amount">0.25 ETH</span>'),
        row("To", to_value(False)),
        row("From", f'Operations treasury<span class="kv__line">{hv(TREASURY, 6, 4, "Copy treasury address")}</span>'),
        row("Network", f'<span class="kv__line">Sepolia {tag("Testnet")}</span>'),
        row("Treasury balance", '1.8420 ETH<span class="kv__cap">1.5920 ETH after this payment</span>'),
        row("Payout", '<span data-show="open rejected">Starts after the second approval.</span>'
                      f'<span data-show="approved" hidden>{badge("Queued", "info")}</span>'),
        row("Approvals valid until", 'Fri 9 Oct, 17:00 BST<span class="kv__cap">After this the treasury refuses the payment, even if it is approved.</span>'),
    ], style="--kv-label:120px")
    details = kv([
        row("Vault", '<a class="lnk" href="#">Operations</a>'),
        row("Type", "Payment"),
        row("Rule when raised", 'Any 2 of 4<span class="kv__cap">Later changes to the vault’s rule don’t apply to this decision.</span>'),
        row("Raised", "Sun 4 Oct, 09:41 BST"),
        row("Decision ID", hv(DECISION_ID, 8, 6, "Copy decision ID")),
        row("You sign with", 'Password key<span class="kv__cap">The Operations treasury holds this key for you.</span>'),
    ], cls="kv kv--plain")
    return f'''<div class="mdp">
<div class="mdp__top"><span data-show="open">{badge("Needs your signature", "warning")}</span><span data-show="approved" hidden>{badge("Approved", "success")}</span><span data-show="rejected" hidden>{badge("Waiting on 1", "neutral")}</span>{code_chip()}</div>
<h1 class="t-title">Top up the release deployer wallet</h1>
<div class="mdp__meta"><p>Raised by <b>Gracian, 38 minutes ago</b></p><p>Due <b>Tue 6 Oct, 17:00 BST</b></p></div>
<section class="dblk" aria-label="Decision text"><p class="dtext">{decision_html(DECISION_TEXT)}</p><p class="dtext__cap">Generated from the payment below. This is the text every approver signs.</p></section>
<section class="dblk" aria-labelledby="{p}-sig"><h2 class="dblk__t"{ident("sig")}>Signatures</h2>
<div class="seal-line">{marks(1, 2, "lg", closing_last=True)}<span class="seal-line__n"><span data-show="open rejected">1 of 2 approvals</span><span data-show="approved" hidden>2 of 2 approvals</span></span></div>
<p class="muted" data-show="open">One more approval pays this. Any 2 of Zaid, Hassan, Gracian and Atharv can approve.</p>
<p class="muted" data-show="approved" hidden>Approved. Your signature completed the quorum, so the treasury pays 0.25 ETH next.</p>
<p class="muted" data-show="rejected" hidden>One more approval pays this. It is rejected only if Gracian and Atharv reject it too.</p>
{timeline(compact=True)}
</section>
<section class="dblk" aria-labelledby="{p}-pay"><h2 class="dblk__t"{ident("pay")}>Payment</h2><div class="panel">{payment}</div><p class="dfoot">The treasury sends exactly 0.25 ETH. Q-Vault covers the network fee.</p></section>
<section class="dblk" aria-labelledby="{p}-chk"><h2 class="dblk__t"{ident("chk")}>Checks</h2>
{outcome()}
<details class="mdisc"><summary>{icon("check-circle")}{checks_count()}{icon("chevron-right")}</summary><ul>{checks_list()}</ul></details>
</section>
<section class="dblk" aria-labelledby="{p}-det"><h2 class="dblk__t"{ident("det")}>Details</h2>{details}</section>
<a class="mrowlink" href="#">{icon("audit")}<span>Technical details</span>{icon("chevron-right")}</a>
</div>'''


def phone_decision() -> str:
    p = "p2"
    return f'''<div class="phone" role="group" aria-roledescription="screen" aria-label="Decision page at 390 pixels wide"><div class="phone__sc" tabindex="0" data-demo="decision-phone">
<header class="mtb">
<a class="mtb__back" href="#">{icon("chevron-left")}Operations</a><span class="mtb__sp"></span>
<button class="ib" type="button" aria-label="More actions">{icon("more")}</button>
</header>
<div class="mc">{m_decision_body(p, True)}</div>
<div class="mbar">
<span data-show="open" style="display:grid;gap:var(--space-8)"><button class="btn btn--primary btn--touch btn--block" type="button" data-open-dialog="approve">Approve</button><button class="btn btn--secondary btn--touch btn--block" type="button" data-open-dialog="reject">Reject</button></span>
<p data-show="approved" hidden class="ph__done">You approved this today at 10:24 BST.</p>
<p data-show="rejected" hidden class="ph__done">You rejected this today at 10:24 BST.</p>
</div>
</div></div>'''


CODE_CAP = "Your phone works out this code on its own and shows the text it covers. If the code or the text differs, don’t sign."
CONSEQUENCE = ("Yours is the second approval. Once you sign, the treasury pays 0.25 ETH to the address above on "
               "Sepolia, usually within a few minutes. You can’t withdraw your signature, and a payment can’t be reversed.")


def approve_body(p: str, phone: bool = False) -> str:
    inp = "input input--touch" if phone else "input"
    return f'''<p class="dlg__text" id="{p}-text">{decision_html(DECISION_TEXT)}</p>
<div class="codeblock" data-copy-scope>
<span class="codeblock__label">Decision code</span>
<span class="codeblock__row"><span class="codeblock__v" translate="no" data-copy-target>{CODE}</span>{copy_btn(CODE, "Copy decision code")}</span>
<p class="codeblock__check">{S17}</p>
<p class="codeblock__cap">{esc(CODE_CAP)}</p>
</div>
<p>{esc(CONSEQUENCE)}</p>
<div class="field">
<label class="field__label" for="{p}-pw">Password</label>
<input class="{inp}" id="{p}-pw" name="password" type="password" autocomplete="off" value="calderwood-demo" aria-describedby="{p}-pw-cap {p}-pw-err" data-initial-focus>
<p class="field__cap" id="{p}-pw-cap">Unlocks your signing key for this signature only. It isn’t stored.</p>
<p class="field__err" id="{p}-pw-err" hidden>{icon("alert")}Enter the password that unlocks your signing key.</p>
</div>'''


def phone_sheet() -> str:
    p = "p3"
    return f'''<div class="phone" role="group" aria-roledescription="screen" aria-label="Approve sheet open at 390 pixels wide">
<div class="phone__sc" inert aria-hidden="true">
<header class="mtb"><span class="mtb__back">{icon("chevron-left")}Operations</span><span class="mtb__sp"></span><span class="ib">{icon("more")}</span></header>
<div class="mc">{m_decision_body(p, False)}</div>
</div>
<div class="scrim"></div>
<div class="sheet" role="dialog" aria-modal="false" aria-labelledby="{p}-t" aria-describedby="{p}-text">
<div class="sheet__h" aria-hidden="true"></div>
<div class="sheet__bd">
<h2 class="dlg__title" id="{p}-t">Approve this payment</h2>
{approve_body(p, phone=True)}
</div>
<div class="sheet__ft">
<button class="btn btn--primary btn--touch btn--block" type="button">Sign approval</button>
<button class="btn btn--secondary btn--touch btn--block" type="button">Cancel</button>
</div>
</div>
</div>'''


# ----------------------------------------------------------------------------------------- dialogs (real)

def dialogs() -> str:
    return f'''<dialog class="dialog" id="dlg-approve" aria-labelledby="dlg-approve-t" aria-describedby="dlg-approve-text">
<form class="dlg" method="dialog" novalidate>
<p class="vh" role="status" aria-live="polite" data-dlg-live></p>
<div class="dlg__hd"><h2 class="dlg__title" id="dlg-approve-t">Approve this payment</h2><button class="ib" type="button" data-close-dialog aria-label="Close">{icon("x")}</button></div>
<div class="dlg__bd">{approve_body("dlg-approve")}</div>
<div class="dlg__ft"><button class="btn btn--secondary" type="button" data-close-dialog>Cancel</button><button class="btn btn--primary" type="submit" name="approve" value="Approve &amp; sign">{SPINNER}Sign approval</button></div>
</form>
</dialog>
<dialog class="dialog" id="dlg-reject" aria-labelledby="dlg-reject-t" aria-describedby="dlg-reject-text">
<form class="dlg" method="dialog" novalidate>
<p class="vh" role="status" aria-live="polite" data-dlg-live></p>
<div class="dlg__hd"><h2 class="dlg__title" id="dlg-reject-t">Reject this payment</h2><button class="ib" type="button" data-close-dialog aria-label="Close">{icon("x")}</button></div>
<div class="dlg__bd">
<p class="dlg__text" id="dlg-reject-text">{decision_html(DECISION_TEXT)}</p>
<div class="field">
<label class="field__label" for="dlg-reject-reason">Reason</label>
<textarea class="input" id="dlg-reject-reason" name="reason" maxlength="255" rows="3" aria-describedby="dlg-reject-cap dlg-reject-reason-err" data-initial-focus></textarea>
<div class="field__caprow"><p class="field__cap" id="dlg-reject-cap">Everyone in Operations sees this next to your rejection. It isn’t part of what you sign. Up to 255 characters.</p><span class="field__cap" id="dlg-reject-count" aria-live="polite">0 / 255</span></div>
<p class="field__err" id="dlg-reject-reason-err" hidden>{icon("alert")}Add a reason so Gracian knows what to change.</p>
</div>
<p>Rejecting doesn’t stop this payment on its own. It is rejected only if Gracian and Atharv reject it too. If either of them approves, it’s paid. You can’t withdraw your rejection.</p>
<div class="field">
<label class="field__label" for="dlg-reject-pw">Password</label>
<input class="input" id="dlg-reject-pw" name="password" type="password" autocomplete="off" value="calderwood-demo" aria-describedby="dlg-reject-pw-cap dlg-reject-pw-err">
<p class="field__cap" id="dlg-reject-pw-cap">Unlocks your signing key for this signature only. It isn’t stored.</p>
<p class="field__err" id="dlg-reject-pw-err" hidden>{icon("alert")}Enter the password that unlocks your signing key.</p>
</div>
</div>
<div class="dlg__ft"><button class="btn btn--secondary" type="button" data-close-dialog>Cancel</button><button class="btn btn--danger" type="submit" name="reject" value="reject">{SPINNER}Sign rejection</button></div>
</form>
</dialog>
<div class="toast" id="toast" role="status" aria-live="polite" hidden>{icon("check")}<span class="toast__t">Link copied</span></div>'''


# ----------------------------------------------------------------------------------------- page: header

def bar() -> str:
    links = [("screens", "Screens"), ("phone", "Phone"), ("type", "Type"), ("colour", "Colour"),
             ("components", "Components"), ("mark", "Mark"), ("approve", "Approval")]
    toc = "".join(f'<a href="#{i}">{t}</a>' for i, t in links)
    return f'''<div class="sentinel" id="top-sentinel" aria-hidden="true"></div>
<header class="bar">
<div class="bar__in">
<a class="brand" href="#top" aria-label="Q-Vault style tile, back to top">{lockup_svg(20, None)}<span class="brand__sep" aria-hidden="true"></span><span class="brand__t">Style tile</span></a>
<nav class="toc" aria-label="On this page">{toc}</nav>
<div class="bar__end"><span class="bar__lbl" id="pg-theme-l">Theme</span>{appearance_seg("pg")}</div>
</div>
</header>'''


def intro() -> str:
    return '''<section class="intro" aria-labelledby="intro-t">
<h1 class="intro__t" id="intro-t">Style tile, R1.1, for review 4 Oct 2026</h1>
<p class="intro__p">This is the look every Q-Vault screen will be converted to, shown on the decision page and Home at desktop and phone width, with the type, colour, components and logo mark they are built from.</p>
<dl class="intro__facts"><div><dt>Workspace shown</dt><dd>Calderwood Labs, a fictional customer</dd></div><div><dt>Seen by</dt><dd>Zaid, Sunday 4 October, 10:20 BST</dd></div><div><dt>Direction</dt><dd>App-led, with dark mode built in</dd></div></dl>
</section>'''


# ----------------------------------------------------------------------------------------- page: screens

def fit_control() -> str:
    opts = []
    for v, lab in (("fit", "Fit to width"), ("actual", "Actual size")):
        checked = " checked" if v == "fit" else ""
        opts.append(f'<span class="seg__o"><input type="radio" name="fit" id="fit-{v}" value="{v}" data-fit{checked}>'
                    f'<label for="fit-{v}">{lab}</label></span>')
    return (f'<div class="ctl" data-fit-control><span class="muted" id="fit-l">Desktop screens</span>'
            f'<div class="seg" role="radiogroup" aria-labelledby="fit-l">{"".join(opts)}</div></div>')


def screens_section() -> str:
    dec = screen("d", "Vaults", crumbs("Vaults", "Operations", "Top up the release deployer wallet"),
                 decision_content(), "Decision page, desktop, 1440 pixels wide", live_count=True)
    home = screen("h", "Home", crumbs("Home"), home_content(), "Home, desktop, 1440 pixels wide")
    return f'''<section class="sec sec--first" aria-labelledby="screens">
<div class="sec__hd"><div><h2 class="sec__t" id="screens">Screens</h2>
<p class="sec__p">The decision page leads, because reading what you sign and signing it is the product’s core moment. Both screens are 1440 wide, scaled to fit unless you pick actual size.</p></div>
{fit_control()}</div>
<figure class="ex" id="decision">
<figcaption class="ex__cap"><div><h3 class="ex__t">Decision page, an open payment that needs Zaid</h3>
<p class="ex__d">Approve and Reject open the signing dialogs and complete the demo. The tabs, copy buttons and menus work, and times show their exact value on hover or focus.</p></div>
<div class="ex__tools"><button class="btn btn--secondary btn--sm" type="button" data-reset-demo hidden>Reset the demo</button></div></figcaption>
<div class="frame"><div class="frame__scroll" tabindex="0" role="region" aria-label="Decision page screen">{dec}</div></div>
</figure>
<figure class="ex" id="home">
<figcaption class="ex__cap"><div><h3 class="ex__t">Home, work first</h3>
<p class="ex__d">What needs Zaid comes first, then what is due, then what waits on others. The log figures that led the old Home move to Audit. The second row opens the decision above.</p></div></figcaption>
<div class="frame"><div class="frame__scroll" tabindex="0" role="region" aria-label="Home screen">{home}</div></div>
</figure>
</section>'''


def phone_section() -> str:
    return f'''<section class="sec" aria-labelledby="phone">
<div class="sec__hd"><div><h2 class="sec__t" id="phone">At phone width</h2>
<p class="sec__p">The same two screens in a phone browser at 390 wide, then the approve dialog as a bottom sheet. Targets are 44 px, inputs are 16 px, and the decision text stays the largest thing on the screen. Each frame scrolls.</p></div></div>
<div class="phones">
<figure class="pf"><figcaption><p class="pf__t">Home</p><p class="pf__d">Rows become list items; each section shows three, then Show all.</p></figcaption>{phone_home()}</figure>
<figure class="pf"><figcaption><p class="pf__t">Decision page</p><p class="pf__d">Approve and Reject stay pinned to the bottom, as in the app.</p></figcaption>{phone_decision()}</figure>
<figure class="pf"><figcaption><p class="pf__t">Approve, as a sheet</p><p class="pf__d">The code is readable without scrolling; Sign approval sits above Cancel.</p></figcaption>{phone_sheet()}</figure>
</div>
</section>'''


# ----------------------------------------------------------------------------------------- page: type

TYPE_ROWS = [
    ("text-figure", "24/32", "600, −0.015em, tabular", "Balances and totals on vault and treasury pages. Never on a page that shows decision text.",
     '<p class="t-figure">1.8420 ETH</p><p class="t-caption">Operations treasury balance</p>'),
    ("text-decision-hero", "22/32", "400, Source Serif 4", "The decision text when it is the page’s subject. Addresses inside it are set in mono.",
     f'<p class="t-decision-hero">{decision_html(DECISION_TEXT)}</p>'),
    ("text-title", "20/28", "600, −0.015em", "Page titles",
     '<p class="t-title">Three decisions need your signature</p>'),
    ("text-decision", "18/28", "400, Source Serif 4", "The decision text in dialogs, sheets and the app",
     '<p class="t-decision">Move the weekly release from Tuesdays to Thursdays, starting 15 October 2026.</p>'),
    ("text-title-sm", "16/24", "600", "Section and dialog titles",
     '<p class="t-title-sm">Approve this payment</p>'),
    ("text-body-strong", "14/20", "560", "Row titles, buttons, names in sentences",
     '<p class="t-strong">Top up the release deployer wallet</p>'),
    ("text-body", "14/20", "400", "Interface text, tables and forms",
     '<p class="t-body">One more approval pays this. Any 2 of Zaid, Hassan, Gracian and Atharv can approve.</p>'),
    ("text-code", "13/20", "400, JetBrains Mono", "Hashes, keys, addresses and IDs, never ordinary numbers. In a caption it drops to 12.",
     '<p class="t-code">a39771f8…8a5127bf</p><p class="t-code">0x41Ed514Be43c437C8b458e3B7491A674b6A78A19</p>'),
    ("text-caption", "12/16", "450; badge labels 500", "Helper text, badge labels, table meta",
     f'<p class="t-caption">Unlocks your signing key for this signature only. It isn’t stored.</p><p class="kv__line" style="margin-top:var(--space-8)">{badge("Needs your signature", "warning")}{badge("Approved", "success")}</p>'),
]

FACES = [
    ("Public Sans", "face--sans", "Every piece of interface: labels, buttons, tables, navigation. Weights 400 to 600, with 450 for captions and 560 for strong body text.",
     "Three decisions need your signature. One is due today."),
    ("Source Serif 4", "face--serif", "Only the decision text, the words people sign, so what is signed looks different from what describes it. 400, with optical sizes.",
     "Pay 0.25 ETH from this vault’s treasury to the release deployer wallet on Sepolia."),
    ("JetBrains Mono", "face--mono", "Only hashes, keys, addresses and IDs, where people compare characters one at a time. 400 and 500.",
     "A397-71F8  0x41Ed514Be43c437C8b458e3B7491A674b6A78A19"),
]


def type_section() -> str:
    rows = "".join(
        f'<div class="trow"><div class="trow__meta"><span class="trow__tok">{tok}</span>'
        f'<span class="trow__spec">{size}, weight {wt}</span><span class="trow__use">{use}</span></div>'
        f'<div class="trow__sample">{sample}</div></div>'
        for tok, size, wt, use, sample in TYPE_ROWS)
    faces = "".join(
        f'<div class="trow"><div class="trow__meta"><span class="trow__face">{name}</span><span class="trow__use">{job}</span></div>'
        f'<div class="trow__sample"><p class="{cls}">{esc(sample)}</p></div></div>'
        for name, cls, job, sample in FACES)
    rules = [
        "Sentence case everywhere. There are no uppercase labels and no tracked eyebrows.",
        "Every amount, count and time uses tabular figures, so columns line up without mono.",
        "Mono is only for hashes, keys, addresses and IDs. It is cut in the middle and has a copy button, except inside the decision text, where addresses are shown whole.",
        "Amounts appear exactly as signed: 0.25 ETH, never rounded. Balances use four decimals: 1.8420 ETH.",
        "Times are relative where people scan. Timelines, dialogs and due dates give the absolute time with its zone: Due Tue 6 Oct, 17:00 BST. Scanning feeds leave the zone off.",
        "Inputs are 16 px below 768 px wide, so phones don’t zoom into a field.",
    ]
    rl = "".join(f"<li>{r}</li>" for r in rules)
    return f'''<section class="sec" aria-labelledby="type">
<div class="sec__hd"><div><h2 class="sec__t" id="type">Type</h2>
<p class="sec__p">Three faces, each with one job, and nine styles on a 4 px line grid: the plan’s seven, with the decision text at two sizes and a 13 px mono step for hashes. Each specimen is a sentence the product actually says.</p></div></div>
<div class="typelist typelist--faces">{faces}</div>
<div class="typelist">{rows}</div>
<ul class="rules">{rl}</ul>
</section>'''


# ----------------------------------------------------------------------------------------- page: colour

def ramp(name: str) -> str:
    out = []
    for step in range(1, 13):
        r = RAMPS[name][step]
        tok = f"--{name}-{step}"
        role = r["role"].replace(">=", "≥") or "&nbsp;"
        ratio_html = f'<span class="only-light">{r["lr"]}</span><span class="only-dark">{r["dr"]}</span>'
        out.append(f'<div class="swt"><span class="swt__chip" style="background:var({tok})"></span>'
                   f'<span class="swt__n"><span>{step}</span><span class="swt__r">{ratio_html}</span></span>'
                   f'{hexes(tok)}<span class="swt__role">{role}</span></div>')
    return f'<div class="ramp">{"".join(out)}</div>'


PAIR_ROWS = [
    ("--text", "--bg", "Body text, titles and the decision text", "text", "4.5"),
    ("--text-muted", "--bg", "Secondary text, labels in key-value panels", "text", "4.5"),
    ("--text-subtle", "--fill-hover", "Captions and placeholders on a hovered row, the weakest text pair", "text", "4.5"),
    ("--text", "--fill-raised-hover", "A hovered menu item, inside a menu or dialog", "text", "4.5"),
    ("--accent-text", "--accent", "The label on the primary button", "text", "4.5"),
    ("--link", "--bg", "Links", "text", "4.5"),
    ("--danger-text", "--danger", "The label on a destructive button", "text", "4.5"),
    ("--focus", "--fill-hover", "The 2 px focus ring, on its weakest ground", "ring", "3.0"),
    ("--accent-fg", "--surface-raised", "The edge of a checked segment, in the account menu", "ring", "3.0"),
    ("--border-strong", "--surface", "Input, checkbox and radio borders", "ring", "3.0"),
    ("--mark-filled", "--surface", "A signature in the seal", "mark", "3.0"),
    ("--mark-empty", "--fill-hover", "A signature still needed, on its weakest ground", "ring-mark", "3.0"),
]


def pair_sample(fg: str, bg: str, kind: str) -> str:
    if kind == "text":
        return f'<span class="pair-sample" style="background:var({bg});color:var({fg})">Approve</span>'
    if kind == "mark":
        return (f'<span class="pair-sample" style="background:var({bg})"><span class="marks marks--md">'
                f'<span class="mark is-on"></span><span class="mark is-on"></span></span></span>')
    if kind == "ring-mark":
        return (f'<span class="pair-sample" style="background:var({bg})"><span class="marks marks--md">'
                f'<span class="mark"></span><span class="mark"></span></span></span>')
    return (f'<span class="pair-sample" style="background:var({bg})"><span class="pair-ring" '
            f'style="box-shadow:inset 0 0 0 2px var({fg})"></span></span>')


TONES = [
    ("Warning", "warning", ["Needs your signature"], "Open work that waits on you"),
    ("Info", "info", ["Queued"], "Handed to the treasury, not paid yet. Later also Scheduled"),
    ("Success", "success", ["Approved", "Paid"], "Done, as asked"),
    ("Critical", "critical", ["Rejected", "Failed"], "Stopped; Failed always says why"),
    ("Neutral", "neutral", ["Waiting on 2", "Expired", "Withdrawn"], "Pending on others, or closed without an outcome"),
]


def colour_section() -> str:
    head = (f'<div class="panel headline">{icon("check-circle")}<span><b>{PAIRS_PASS} of {PAIRS_TOTAL} required contrast pairs pass,</b> '
            f'{PAIRS_PER_THEME} in each theme.</span><span class="muted">WCAG 2.x ratios, truncated to two decimals and never rounded up. '
            f'The figures below are for the theme you are viewing.</span></div>')
    rows = []
    for fg, bg, where, kind, target in PAIR_ROWS:
        rows.append(f'<tr><td>{pair_sample(fg, bg, kind)}</td><td><code>{fg}</code> on <code>{bg}</code></td>'
                    f'<td class="muted">{where}</td><td class="r"><span class="ratio">{ratio(fg, bg)}</span></td>'
                    f'<td class="r subtle">{target}</td><td><span class="pass">{icon("check")}Pass</span></td></tr>')
    table = (f'<div class="panel pairs-wrap"><table class="pairs"><thead><tr><th>Sample</th><th>Pair</th><th>Where</th>'
             f'<th class="r">Contrast</th><th class="r">Target</th><th>Result</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')
    tones = []
    for name, key, words, use in TONES:
        chips = ""
        for part, lab in (("fg", "Text"), ("bg", "Tint"), ("border", "Line")):
            tok = f"--status-{key}-{part}"
            chips += (f'<span class="tone__chip"><i style="background:var({tok})"></i><span>{lab}</span>'
                      f'<code data-hex="{tok}">{LIGHT(tok)}</code></span>')
        bs = "".join(badge(w, key) for w in words)
        tones.append(f'<div class="panel tone"><div class="tone__hd"><b>{name}</b><span class="swt__r">text on tint '
                     f'<span class="ratio">{ratio(f"--status-{key}-fg", f"--status-{key}-bg")}</span></span></div>'
                     f'<div class="tone__badges">{bs}</div><div class="tone__chips">{chips}</div><p class="tone__use">{use}</p></div>')
    return f'''<section class="sec" aria-labelledby="colour">
<div class="sec__hd"><div><h2 class="sec__t" id="colour">Colour</h2>
<p class="sec__p">Cool neutrals tuned to the app’s navy ink, one accent and a closed set of five status tones. Every swatch reads the live token, so switching the theme above switches the whole section.</p></div></div>
{head}
<div class="sec__block"><h3 class="sec__sub">Neutral, 12 steps at the ink’s hue</h3>{ramp("neutral")}
<p class="ramp-note">The number by each step is its contrast against step 1. Steps 8 and 10 are the lightest greys that reach 3:1 for borders and 4.5:1 for text on every surface.</p></div>
<div class="sec__block"><h3 class="sec__sub">Accent, the ink made brighter</h3>{ramp("accent")}
<p class="ramp-note">Hue 262 against the ink’s 261, at chroma 0.165, below a stock framework blue. Step 9 fills the primary button, focus ring and checked controls; 10 is its hover; 11 is the darker step for accent text on a tint. Links use 9 in light and 11 in dark. The accent never marks a status or a value.</p></div>
<div class="sec__block"><h3 class="sec__sub">The pairs that carry the interface</h3>{table}</div>
<div class="sec__block"><h3 class="sec__sub">Status, five tones</h3><div class="tones">{"".join(tones)}</div>
<p class="ramp-note">Success, warning and critical are the app’s sealed, waiting and broken colours, unchanged in light. Info is a steel blue at half the accent’s chroma and 37 degrees away from it, kept for Queued so blue stays rare. Waiting on N is neutral: it is still open, but there is nothing for you to do. Every badge carries its word; colour is never the only signal.</p></div>
</section>'''


# ----------------------------------------------------------------------------------------- page: components

def cs(title: str, rule: str, body: str, span: str = "", bg: bool = False, ident: str = "") -> str:
    cls = f"cs cs--{span}" if span else "cs"
    idattr = f' id="{ident}"' if ident else ""
    bd = "cs__bd cs__bd--bg" if bg else "cs__bd"
    return (f'<section class="{cls}"{idattr} aria-label="{esc(title)}"><div class="cs__hd"><h3 class="cs__t">{title}</h3>'
            f'<p class="cs__r">{rule}</p></div><div class="{bd}">{body}</div></section>')


def st(label: str, inner: str, grow: bool = False) -> str:
    cls = "st st--grow" if grow else "st"
    return f'<div class="{cls}">{inner}<span class="st__l">{label}</span></div>'


def buttons_cs() -> str:
    variants = [("Primary", "btn--primary", "Approve"), ("Secondary", "btn--secondary", "Reject"),
                ("Ghost", "btn--ghost", "Export for verification"), ("Danger", "btn--danger", "Sign rejection")]
    states = [("Rest", ""), ("Hover", " is-hover"), ("Focus", " is-focus"), ("Pressed", " is-pressed"),
              ("Disabled", "disabled"), ("Loading", "loading")]
    head = "".join(f"<th scope=\"col\">{s}</th>" for s, _ in states)
    body = ""
    for vname, vcls, label in variants:
        cells = ""
        for sname, scls in states:
            if scls == "disabled":
                b = f'<button class="btn {vcls}" type="button" disabled>{label}</button>'
            elif scls == "loading":
                b = f'<button class="btn {vcls}" type="button" aria-busy="true">{SPINNER_ON}{label}</button>'
            else:
                b = f'<button class="btn {vcls}{scls}" type="button">{label}</button>'
            cells += f"<td>{b}</td>"
        body += f'<tr><th scope="row">{vname}</th>{cells}</tr>'
    sizes = (f'<div class="sizes">{st("Small, 28: toolbars", "<button class=\"btn btn--primary btn--sm\" type=\"button\">Approve</button>")}'
             f'{st("Default, 32", "<button class=\"btn btn--primary\" type=\"button\">Approve</button>")}'
             f'{st("Large, 40: sign-in screens", "<button class=\"btn btn--primary btn--lg\" type=\"button\">Sign in</button>")}'
             f'{st("Touch, 44: phones", "<button class=\"btn btn--primary btn--touch\" type=\"button\">Sign approval</button>")}'
             f'{st("Icon, with its name in a tooltip", "<button class=\"btn btn--secondary btn--icon\" type=\"button\" aria-label=\"More actions\" data-tip=\"More actions\">" + icon("more") + "</button>")}</div>')
    return cs("Button", "One primary per view, verb and noun in sentence case. Loading keeps its label and shows three quorum marks filling in turn, never a spinning ring; disabled is its own colours, never faded.",
              f'<div class="mx-wrap"><table class="mx"><thead><tr><th></th>{head}</tr></thead><tbody>{body}</tbody></table></div>{sizes}')


def fields_cs() -> str:
    amt_cap = "In ETH, on Sepolia. Up to 18 decimal places."

    def amount(ident, state, value="", invalid=False, disabled=False, focus=False):
        cls = "input" + (" is-focus" if focus else "")
        attrs = f' value="{value}"' if value else ""
        if invalid:
            attrs += ' aria-invalid="true"'
        if disabled:
            attrs += " disabled"
        err = (f'<p class="field__err" id="{ident}-err">{icon("alert")}Enter an amount above 0 ETH.</p>' if invalid else "")
        desc = f"{ident}-cap" + (f" {ident}-err" if invalid else "")
        sfx = "inwrap__sfx is-disabled" if disabled else "inwrap__sfx"
        return st(state, f'''<div class="field" style="width:100%"><label class="field__label" for="{ident}">Amount</label>
<div class="inwrap"><input class="{cls}" id="{ident}" type="text" inputmode="decimal"{attrs} aria-describedby="{desc}"><span class="{sfx}" aria-hidden="true">ETH</span></div>
<p class="field__cap" id="{ident}-cap">{amt_cap}</p>{err}</div>''', grow=True)

    grid = "".join([
        amount("c-amt-1", "Default"),
        amount("c-amt-2", "Focus", focus=True),
        amount("c-amt-3", "Filled", value="0.25"),
        amount("c-amt-4", "Error", value="0", invalid=True),
        amount("c-amt-5", "Disabled", value="0.25", disabled=True),
    ])
    rec = (st("Recipient, filled", f'''<div class="field" style="width:100%"><label class="field__label" for="c-rec-1">Recipient</label>
<input class="input input--mono" id="c-rec-1" type="text" spellcheck="false" value="{RECIPIENT}" aria-describedby="c-rec-1-cap">
<p class="field__cap" id="c-rec-1-cap">An Ethereum address on Sepolia, starting 0x.</p></div>''', grow=True)
           + st("Recipient, error", f'''<div class="field" style="width:100%"><label class="field__label" for="c-rec-2">Recipient</label>
<input class="input input--mono" id="c-rec-2" type="text" spellcheck="false" value="{RECIPIENT[:-1]}" aria-invalid="true" aria-describedby="c-rec-2-err">
<p class="field__err" id="c-rec-2-err">{icon("alert")}That isn’t a valid Ethereum address.</p></div>''', grow=True))
    return cs("Field", "Label above, caption below, error under the field in words. Borders reach 3:1. Guidance goes in captions; placeholders stay empty.",
              f'<div class="fieldgrid">{grid}</div><div class="fieldgrid fieldgrid--wide">{rec}</div>', span="8")


def select_cs() -> str:
    opts = (f'<a class="menu__i" role="option" aria-selected="true" href="#"><span class="menu__opt"><span>Operations</span><span class="selbtn__cap">Any 2 of 4</span></span>{icon("check", "menu__check")}</a>'
            f'<a class="menu__i is-hover" role="option" aria-selected="false" href="#"><span class="menu__opt"><span>Engineering access</span><span class="selbtn__cap">Any 2 of 3</span></span></a>')
    closed = st("Closed", f'<div class="field" style="width:100%"><label class="field__label" for="c-sel-1">Vault</label><button class="selbtn" id="c-sel-1" type="button" aria-haspopup="listbox"><span class="selbtn__ph">Choose a vault</span>{icon("chevron-down")}</button></div>', grow=True)
    opened = st("Open", f'<div class="field" style="width:100%"><label class="field__label" for="c-sel-2">Vault</label><button class="selbtn" id="c-sel-2" type="button" aria-haspopup="listbox" aria-expanded="true"><span class="selbtn__v"><span>Operations</span><span class="selbtn__cap">Any 2 of 4</span></span>{icon("chevron-down")}</button><div class="menu" role="listbox" aria-label="Vault">{opts}</div></div>', grow=True)
    picked = st("Selected", f'<div class="field" style="width:100%"><label class="field__label" for="c-sel-3">Vault</label><button class="selbtn" id="c-sel-3" type="button" aria-haspopup="listbox"><span class="selbtn__v"><span>Engineering access</span><span class="selbtn__cap">Any 2 of 3</span></span>{icon("chevron-down")}</button></div>', grow=True)
    return cs("Select", "A styled menu instead of the browser’s, with the rule beside each vault.",
              f'<div class="stack">{closed}{opened}{picked}</div>', span="4")


def choices_cs() -> str:
    label = "I understand Hassan will no longer be able to approve this treasury’s payments"

    def cb(ident, state, checked=False, disabled=False, focus=False):
        a = (" checked" if checked else "") + (" disabled" if disabled else "")
        cls = "cb" + (" is-focus" if focus else "")
        wrap = "choice choice--disabled" if disabled else "choice"
        return st(state, f'<div class="{wrap}"><input class="{cls}" type="checkbox" id="{ident}"{a}><label for="{ident}">{label}</label></div>', grow=True)

    boxes = "".join([cb("c-cb-1", "Unchecked"), cb("c-cb-2", "Checked", checked=True),
                     cb("c-cb-3", "Focus", focus=True), cb("c-cb-4", "Disabled", disabled=True)])
    radios = f'''<fieldset class="stack"><legend class="field__label" style="margin-bottom:var(--space-8)">Key for treasury approvals</legend>
<div class="choice"><input class="rd" type="radio" name="c-key" id="c-key-1" checked><label for="c-key-1">Password key on this account</label></div>
<div class="choice"><input class="rd" type="radio" name="c-key" id="c-key-2"><label for="c-key-2">Phone key on Zaid’s phone<span class="choice__cap">Added 12 Sep</span></label></div>
<p class="field__cap">A treasury only counts approvals made with the key it holds for you.</p>
</fieldset>'''
    return cs("Checkbox and radio", "16 px, the accent when on, borders at 3:1. The checkbox is the real reconfigure confirmation; the radio is Zaid’s real choice of treasury key.",
              f'<div class="fieldgrid">{boxes}</div>{st("Radio group, one selected", radios, grow=True)}', span="6")


def switch_cs() -> str:
    label = "The person who raises a decision can also approve it"

    def sw(ident, state, checked=False, disabled=False, focus=False, cap=""):
        a = (" checked" if checked else "") + (" disabled" if disabled else "")
        cls = "sw" + (" is-focus" if focus else "")
        wrap = "swrow swrow--disabled" if disabled else "swrow"
        capt = f'<span class="choice__cap">{cap}</span>' if cap else ""
        return st(state, f'<div class="{wrap}"><input class="{cls}" type="checkbox" role="switch" id="{ident}"{a}><label for="{ident}">{label}{capt}</label></div>', grow=True)

    body = "".join([sw("c-sw-1", "Off"), sw("c-sw-2", "On", checked=True), sw("c-sw-3", "Focus", focus=True),
                    sw("c-sw-4", "Disabled, with the reason", disabled=True, cap="Only a vault owner can change this.")])
    appearance = (f'<div class="st"><span class="field__label" id="c-theme-l">Appearance</span>{appearance_seg("c")}'
                  f'<span class="st__n">Live: this is the product’s own setting, and it switches this page.</span></div>')
    return cs("Switch and appearance", "A switch applies at once, so it suits settings; this one is the planned separation-of-duties setting (S15). The appearance control is System, Light or Dark, in the account menu.",
              f'<div class="fieldgrid">{body}</div>{appearance}', span="6")


def badges_cs() -> str:
    groups = [("warning", ["Needs your signature"]), ("info", ["Queued"]), ("success", ["Approved", "Paid"]),
              ("critical", ["Rejected", "Failed"]), ("neutral", ["Waiting on 2", "Expired", "Withdrawn"])]
    b = "".join(st(tone.capitalize(), '<span class="kv__line">' + "".join(badge(w, tone) for w in words) + "</span>") for tone, words in groups)
    tags = st("Tags, for type and network", '<span class="kv__line">' + "".join(tag(t) for t in ("Payment", "Production access", "Contract", "Testnet")) + "</span>")
    return cs("Badge and tag", "Nine status words in five tones, and nothing else. A badge is a tint with no line; a tag is metadata, a line with no fill. General, the default type, has no tag.",
              f'<div class="states">{b}</div>{tags}', span="6")


def avatars_cs() -> str:
    people = "".join(av(x, 32, name=NAMES[x]) for x in "ZHGA")
    sizes = st("People: 32, 24, 20", f'<span class="kv__line">{people}{av("Z", 24, name="Zaid")}{av("Z", 20, name="Zaid")}</span>')
    ents = st("Workspace and vault: square", f'<span class="kv__line">{av("C", 32, entity=True, name="Calderwood Labs")}{av("O", 24, entity=True, name="Operations")}{av("O", 20, entity=True, name="Operations")}</span>')
    stacks = st("Stacks: 2, 4, and overflow", f'<span class="kv__line">{avs("HG")}{avs("ZHGA")}{avs("ZHGA", more=1)}</span>')
    return cs("Avatar", "Initials on a neutral fill, never a colour: four different initials tell the team apart. People are round, entities square. Never beside the quorum marks, where a grey circle would read as one more mark.",
              f'<div class="states">{sizes}{ents}{stacks}</div>', span="6")


def marks_cs() -> str:
    cases = [(0, 2, ""), (1, 2, ""), (2, 2, "the closed seal"), (2, 3, ""), (3, 5, "")]
    rows = "".join(f'<div class="qrow">{marks(f, r, "md")}<span>{f} of {r} approvals'
                   f'{(",<span class=\"subtle\"> " + note + "</span>") if note else ""}</span></div>' for f, r, note in cases)
    demo = (f'<div class="stack"><span class="seal-line">{marks(2, 2, "lg", ident="c-seal-demo")}<span class="seal-line__n">2 of 2 approvals</span>'
            f'<button class="btn btn--ghost btn--sm" type="button" data-replay-seal="c-seal-demo">Replay the closing</button></span>'
            f'<p class="st__n">The one orchestrated motion. It plays once, for the person whose signature completed the quorum, and only fades under reduced motion.</p></div>')
    return cs("Quorum marks", "Discrete marks, one per required signature, never a progress bar. Filled is a valid approval; a ring is one still needed. 20 px on a decision page, as in the app; 12 and 10 in lists.",
              f'{st("States", "<div class=\"qlist\">" + rows + "</div>")}{st("Closing", demo)}', span="6")


def hash_cs() -> str:
    trunc = st("Truncated, with copy", hv(PAYLOAD_HASH, 8, 8, "Copy payload hash", expand=True))
    full = st("Expanded", f'<span class="hv"><span class="hv__v" style="max-width:300px">{PAYLOAD_HASH}</span></span>')
    copied = st("Copied", f'<span class="hv"><span class="hv__v">a39771f8…8a5127bf</span><button class="copy is-done" type="button" aria-label="Copied">{icon("copy", "copy__i")}{icon("check", "copy__ok")}</button><span class="copy__msg">Copied</span></span>')
    addr = st("Address, expanded: first and last 4 bytes in bold", f'<span class="hv"><span class="hv__v">{addr_bold(RECIPIENT)}</span></span>')
    code = st("Decision code", f'<div class="stack">{code_chip("")}<p class="muted">{S17}</p></div>')
    return cs("Hash, address and decision code", "Mono, cut in the middle so both ends stay comparable, with copy and Show full. If the browser blocks copying, the whole value is selected, never the shortened one. The code is the first 8 characters of the payload hash.",
              f'<div class="states">{trunc}{copied}{code}</div><div class="states">{full}{addr}</div>', span="6")


def tabs_cs() -> str:
    two = f'''<div class="tabs" role="tablist" aria-label="Decision, example">
<button class="tab" role="tab" type="button" id="c-tab-1" aria-selected="true"><span class="tab__l">Overview</span></button>
<button class="tab is-hover" role="tab" type="button" id="c-tab-2" aria-selected="false" tabindex="-1"><span class="tab__l">Evidence</span></button>
<button class="tab is-focus" role="tab" type="button" id="c-tab-3" aria-selected="false" tabindex="-1"><span class="tab__l">Technical</span></button>
</div>'''
    five = f'''<div class="tabs" role="tablist" aria-label="Vault, example">
<button class="tab" role="tab" type="button" id="c-tab-4" aria-selected="true"><span class="tab__l">Decisions<span class="count">12</span></span></button>
<button class="tab" role="tab" type="button" id="c-tab-5" aria-selected="false" tabindex="-1"><span class="tab__l">Members<span class="count">4</span></span></button>
<button class="tab" role="tab" type="button" id="c-tab-6" aria-selected="false" tabindex="-1"><span class="tab__l">Files</span></button>
<button class="tab" role="tab" type="button" id="c-tab-7" aria-selected="false" tabindex="-1"><span class="tab__l">Treasury</span></button>
<button class="tab" role="tab" type="button" id="c-tab-8" aria-selected="false" tabindex="-1"><span class="tab__l">Settings</span></button>
</div>'''
    return cs("Tabs", "Routed in the URL in the product, directly under the page header. The accent underline marks the selected tab; arrow keys move between tabs.",
              f'{st("Selected, hover, focus", two, grow=True)}{st("Five tabs with counts", five, grow=True)}', span="6")


def page_header_cs() -> str:
    with_actions = f'''<div class="vt"><div class="vt__hd"><div class="stack" style="gap:var(--space-2)"><p class="vt__t">Operations</p><p class="vt__m">Any 2 of 4 approve. You’re an approver.</p></div>
<span class="kv__line"><button class="btn btn--secondary" type="button">{icon("settings")}Vault settings</button><button class="btn btn--primary" type="button">{icon("plus")}New decision</button></span></div></div>'''
    without = '''<div class="vt"><p class="vt__t">Engineering access</p><p class="vt__m">Any 2 of 3 approve. You’re an approver.</p></div>'''
    return cs("Page header", "Title, a line of labelled facts, at most one primary action. Tabs sit under it when the page has them.",
              f'{st("With actions", with_actions, grow=True)}{st("Without actions", without, grow=True)}', bg=True)


def table_row_cs() -> str:
    hd = ('<div class="ar ar--hd" aria-hidden="true"><span>Decision</span><span>Code</span><span>Vault</span><span class="r">Amount</span>'
          '<span>Signatures</span><span>Status</span><span>Raised</span><span>Due</span></div>')

    def r(cls):
        return (f'<div class="ar {cls}"><span class="ar__t">Top up the release deployer wallet</span><span class="ar__code">{CODE}</span>'
                f'<span>Operations</span><span class="r">0.25 ETH</span>'
                f'<span class="wl__s1">{marks(1, 2)}<span>1 of 2</span></span>'
                f'<span>{badge("Needs your signature", "warning")}</span><span>Today at 09:41</span>'
                f'<span><time datetime="2026-10-06T17:00:00+01:00" title="in 2 days">Tue 6 Oct, 17:00 BST</time></span></div>')
    labels = ["Rest", "Hover", "Selected", "Focus"]
    cls = ["", "is-hover", "is-sel", "is-focus"]
    rows = "".join(f'<div class="rowstates"><span class="rowstates__l">{lab}</span><div>{r(c)}</div></div>' for lab, c in zip(labels, cls))
    body = f'<div class="mini-wrap"><div style="min-width:1040px"><div class="rowstates"><span></span><div class="mini-table">{hd}</div></div>{rows}</div></div>'
    return cs("Data table row", "An Approvals inbox row: one line, 40 px. The code has its own column, amounts are right-aligned, and the relative due time is in a tooltip. The whole row opens the decision; there is no bulk sign. Home’s lists use two-line rows, 56 px and up.", body)


def kv_cs() -> str:
    plain = kv([
        row("Type", "Payment"),
        row("Rule when raised", 'Any 2 of 4<span class="kv__cap">Later changes to the vault’s rule don’t apply to this decision.</span>'),
        row("Decision ID", hv(DECISION_ID, 8, 6, "Copy decision ID")),
    ], cls="kv kv--plain")
    side = kv([
        row("Amount", '<span class="amount">0.25 ETH</span>'),
        row("Network", f'<span class="kv__line">Sepolia {tag("Testnet")}</span>'),
        row("Decision code", code_chip("")),
    ])
    return cs("Key-value panel", "Labels muted, values in ink. Unboxed and stacked in the 320 px aside; a divided panel only for facts that really are a table, such as a payment.",
              f'{st("Stacked, in an aside", "<div style=\"width:100%\">" + plain + "</div>", grow=True)}'
              f'{st("Divided, in the main column", "<div class=\"panel\" style=\"width:100%\">" + side + "</div>", grow=True)}', span="5")


def timeline_cs() -> str:
    tl = f'''<ol class="tl" aria-label="Timeline example">
<li class="tl__i"><span class="tl__who">{av("G", 24, name="Gracian")}</span><div class="tl__b"><p><b>Gracian</b> raised this payment</p></div><time class="tl__time" datetime="2026-10-04T09:41:17+01:00">Today at 09:41 BST</time></li>
<li class="tl__i"><span class="tl__who">{av("H", 24, name="Hassan")}{glyph("ok")}</span><div class="tl__b"><p><b>Hassan</b> approved on his phone</p><p class="tl__sub">Signed 1 of 2</p></div><time class="tl__time" datetime="2026-10-04T09:58:42+01:00">Today at 09:58 BST</time></li>
<li class="tl__i"><span class="tl__who">{av("G", 24, name="Gracian")}{glyph("no")}</span><div class="tl__b"><p><b>Gracian</b> rejected</p><p class="tl__q">“Wait until the deployer’s balance drops below 0.05 ETH.”</p></div><time class="tl__time" datetime="2026-10-04T10:02:00+01:00">Today at 10:02 BST</time></li>
<li class="tl__i tl__i--you is-before-next"><span class="tl__who">{av("Z", 24, name="Zaid")}{glyph("wait")}</span><div class="tl__b"><p><b>You</b></p><p class="tl__sub">Your approval completes this payment.</p></div></li>
<li class="tl__i tl__i--muted"><span class="tl__who">{av("O", 24, entity=True, name="Operations treasury")}</span><div class="tl__b"><p>Then the treasury pays 0.25 ETH</p><p class="tl__sub">Usually within a few minutes of the second approval</p></div></li>
</ol>'''
    return cs("Timeline item", "Raised, approved, rejected with its reason, waiting, and what happens next. One marker per row: the avatar, with its state as a small badge. Every row says its status in words.", tl, span="7")


def banners_cs() -> str:
    b = (f'<div class="banner banner--info">{icon("info")}<p>Payments in this vault use the Sepolia testnet. Testnet ETH has no market value.</p></div>'
         f'<div class="banner banner--warning">{icon("warning")}<p>This vault’s treasury is being reconfigured. Raise payments once that is done.</p></div>'
         f'<div class="banner banner--critical">{icon("alert")}<p><b>Content altered since signing.</b> The signatures below are each valid but don’t authorise this text, so they aren’t counted.</p></div>')
    return cs("Banner", "Persistent, at the top of the section it concerns, with the next step in words. Info, warning and critical.",
              f'<div class="stack">{b}</div>', span="7")


def menu_toast_cs() -> str:
    menu = f'''<div class="menu" role="menu" aria-label="More actions, example">
<a class="menu__i" role="menuitem" tabindex="-1" href="#">{icon("download")}Export for verification</a>
<a class="menu__i is-hover" role="menuitem" tabindex="-1" href="#">{icon("link")}Copy link</a>
<a class="menu__i" role="menuitem" tabindex="-1" href="#">{icon("audit")}View in audit log</a>
<span class="menu__i" role="menuitem" aria-disabled="true">{icon("external")}Copy public link<span class="menu__cap">Available once decided</span></span>
<div class="menu__sep" role="separator"></div>
<a class="menu__i menu__i--danger" role="menuitem" tabindex="-1" href="#">{icon("trash")}Withdraw decision</a>
</div>'''
    toast = (f'<div class="stack" style="justify-items:start"><div class="toast toast--static">{icon("check")}<span>Link copied</span></div>'
             f'<button class="btn btn--secondary btn--sm" type="button" data-action="toast" data-text="Link copied">Show the toast</button></div>')
    return cs("Menu and toast", "Menus are dense, with a disabled item that says why and the destructive item last (Withdraw is planned, R5). A toast confirms a small action, bottom left, for 5 seconds, and never carries an error.",
              f'<div class="states">{st("Menu, open", menu)}{st("Toast", toast)}</div>', span="5")


def dialog_cs() -> str:
    open_dlg = f'''<div class="dlg--static" role="group" aria-label="Approve dialog, example"><div class="dlg">
<div class="dlg__hd"><p class="dlg__title">Approve this payment</p><span class="ib" aria-hidden="true">{icon("x")}</span></div>
<div class="dlg__bd">
<p class="dlg__text">{decision_html(DECISION_TEXT)}</p>
<div class="codeblock"><span class="codeblock__label">Decision code</span><span class="codeblock__row"><span class="codeblock__v">{CODE}</span></span><p class="codeblock__check">{S17}</p><p class="codeblock__cap">{esc(CODE_CAP)}</p></div>
<p>{esc(CONSEQUENCE)}</p>
<div class="field"><label class="field__label" for="c-dlg-pw">Password</label><input class="input" id="c-dlg-pw" type="password" autocomplete="off" value="calderwood-demo"><p class="field__cap">Unlocks your signing key for this signature only. It isn’t stored.</p></div>
</div>
<div class="dlg__ft"><button class="btn btn--secondary" type="button">Cancel</button><button class="btn btn--primary" type="button">Sign approval</button></div>
</div></div>'''
    signing = (f'<div class="dlg--static"><div class="dlg__ft" style="border-top:0"><button class="btn btn--secondary" type="button" disabled>Cancel</button>'
               f'<button class="btn btn--primary" type="button" aria-busy="true">{SPINNER_ON}Sign approval</button></div></div>'
               f'<p class="st__n">The label stays, both buttons wait, and Escape does nothing until signing ends.</p>')
    wrong = (f'<div class="dlg--static"><div class="dlg__bd"><div class="field"><label class="field__label" for="c-dlg-pw2">Password</label>'
             f'<input class="input" id="c-dlg-pw2" type="password" autocomplete="off" value="wrong-guess" aria-invalid="true" aria-describedby="c-dlg-pw2-e">'
             f'<p class="field__err" id="c-dlg-pw2-e">{icon("alert")}That password didn’t unlock your signing key. Nothing was signed.</p></div></div></div>')
    changed = (f'<div class="dlg--static"><div class="dlg__bd"><div class="banner banner--critical">{icon("alert")}<p>This vault’s treasury has been reconfigured since this payment was raised, so it would no longer accept approvals of it. Nothing was signed. Raise the payment again.</p></div></div>'
               f'<div class="dlg__ft"><button class="btn btn--secondary" type="button">Cancel</button><button class="btn btn--primary" type="button" disabled>Sign approval</button></div></div>')
    live = f'<button class="btn btn--primary self-start" type="button" data-open-dialog="approve">Open the real dialog</button>'
    return cs("Dialog", "480 wide, radius 12, the only place a shadow is this deep. The title names the decision and the button names the act. The text restates exactly what is signed, and on phones the dialog becomes a bottom sheet.",
              f'<div class="states">{st("Open", open_dlg, grow=True)}<div class="stack" style="flex:1 1 320px">{st("Signing", signing)}{st("Wrong password", wrong)}{st("Treasury changed: Sign approval unavailable", changed)}{live}</div></div>')


def checks_cs() -> str:
    rows = (f'<li class="check">{icon("check")}<div><p class="check__t">Witnessed</p><p class="check__d">An independent witness co-signed the log, including this decision and Hassan’s approval, at 09:59 BST.</p></div></li>'
            f'<li class="check check--fail">{icon("x-circle")}<div><p class="check__t">Not witnessed</p><p class="check__d">The witness hasn’t co-signed a checkpoint covering this decision.</p></div></li>'
            f'<li class="check check--na">{icon("minus-circle")}<div><p class="check__t">Checks unavailable</p><p class="check__d">Try again in a minute.</p></div></li>')
    return cs("Check row", "Evidence layer 2: a plain title and one line on what was checked. A check is passed, failed or unavailable, and says so in words; inside the technical panels the only result words are Valid and Same as signed. These are check results, never decision statuses.",
              f'<div class="panel"><ul>{rows}</ul></div>', span="6")


def empty_cs() -> str:
    hd = '<div class="wl__hd" aria-hidden="true"><span>Decision</span><span class="r">Amount</span><span>Signatures</span><span>Due</span></div>'
    nodata = (f'<div class="wl">{hd}<div class="empty"><p class="empty__t">Nothing needs your signature</p>'
              f'<p class="empty__c">Everything you can approve has been signed.</p><button class="btn btn--secondary" type="button">See what’s open</button></div></div>')
    nores = (f'<div class="wl">{hd}<div class="empty"><p class="empty__t">No decisions match “deployer”</p>'
             f'<p class="empty__c">Try another word, or clear the filters.</p><button class="btn btn--secondary" type="button">Clear filters</button></div></div>')
    sk = ('<div class="mini-wrap" style="width:100%"><div class="panel" aria-hidden="true" style="min-width:440px"><div style="display:grid;grid-template-columns:minmax(0,1fr) 56px 96px 112px;column-gap:12px;padding:12px 16px">'
          '<span class="stack" style="gap:8px"><span class="sk sk--t"></span><span class="sk sk--m"></span></span><span class="sk sk--n" style="justify-self:end;width:48px"></span>'
          '<span class="sk sk--s"></span><span class="stack" style="gap:8px"><span class="sk sk--s"></span><span class="sk" style="width:48px"></span></span></div></div></div>')
    return cs("Empty state and skeleton", "One sentence, one line and one action, left-aligned where the rows would be. No results reads differently from nothing yet. Skeletons match the row they stand in for and appear after 150 ms.",
              f'{st("No data", nodata, grow=True)}{st("No results", nores, grow=True)}{st("Skeleton, a Home row", sk, grow=True)}', span="6")


def components_section() -> str:
    parts = [buttons_cs(), fields_cs(), select_cs(), choices_cs(), switch_cs(), badges_cs(), avatars_cs(),
             marks_cs(), hash_cs(), tabs_cs(), page_header_cs(), table_row_cs(), kv_cs(), timeline_cs(),
             banners_cs(), menu_toast_cs(), dialog_cs(), checks_cs(), empty_cs()]
    return f'''<section class="sec" aria-labelledby="components">
<div class="sec__hd"><div><h2 class="sec__t" id="components">Components</h2>
<p class="sec__p">Every state the two screens need, built only from the tokens above, with real product copy. In R1 each becomes a Jinja macro with a documented contract, and a twin in the app.</p></div></div>
<div class="cgrid">{"".join(parts)}</div>
</section>'''


# ----------------------------------------------------------------------------------------- page: the mark

def browser_tabs() -> str:
    """The favicon at 16 px in a tab strip, beside a tab that is loading, so the mark can be judged
    against the one ring people already read as 'wait'."""
    loading = ('<svg class="btab__spin" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" focusable="false">'
               '<path d="M8 2a6 6 0 1 1-6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>')
    return (f'<div class="btabs" role="img" aria-label="A browser tab strip: the Q-Vault favicon beside a tab that is still loading">'
            f'<span class="btab btab--on">{mark_svg(16, None)}<span>Approvals</span></span>'
            f'<span class="btab">{loading}<span>Loading…</span></span>'
            f'<span class="btab">{mark_svg(16, None)}<span>Operations</span></span></div>')


def mark_section() -> str:
    def cand(name, title, idea, why):
        vb, paths = CANDIDATES[name]
        return (f'<div class="panel cand"><span class="cand__ic"><svg viewBox="{vb}" fill="currentColor" role="img" aria-label="{esc(title)}">{paths}</svg></span>'
                f'<div><p class="cand__t">{title}</p><p>{idea}</p><p class="cand__why">{why}</p></div></div>')

    frames = []
    for label, body in (("Waiting on 1", RING_PATH), ("Signing", RING_PATH + DISC_FAR), ("Approved", RING_PATH + DISC_REST)):
        frames.append(f'<figure><svg width="48" height="48" viewBox="-2 -2 36 36" fill="currentColor" aria-hidden="true" focusable="false">{body}</svg><figcaption>{label}</figcaption></figure>')
    play = (f'<svg width="64" height="64" viewBox="-2 -2 36 36" fill="currentColor" role="img" aria-label="The closing mark">'
            f'{RING_PATH}<g class="mk__arrive">{DISC_REST}</g></svg>')
    sizes = "".join(f'<figure class="mk__sz">{mark_svg(s)}<figcaption>{s} px</figcaption></figure>' for s in (32, 24, 16))
    return f'''<section class="sec" aria-labelledby="mark">
<div class="sec__hd"><div><h2 class="sec__t" id="mark">The mark</h2>
<p class="sec__p">Four candidates were drawn from the quorum seal and judged at real pixels on both grounds. The recommendation is the closing mark.</p></div></div>
<div class="mk">
<div class="panel mk__main">
<div class="stack" style="gap:var(--space-4)"><p class="kv__line"><b class="t-title-sm">The closing mark</b>{tag("Recommended")}</p>
<p class="muted" style="max-width:68ch">A decision is an open seal until the last required signature lands. The ring is the decision; the disc in its gap is the signature that closes it. Together they read as a Q, so the favicon and app icon carry the name without letters.</p></div>
<div class="mk__row">
<figure class="mk__sz mk__play is-playing" id="mk-play">{play}<figcaption>64 px</figcaption></figure>
{sizes}
<figure class="mk__sz"><span class="mk__icon">{mark_svg(40, None)}</span><figcaption>App icon</figcaption></figure>
<button class="btn btn--ghost btn--sm" type="button" data-play-mark="mk-play">Play the arrival</button>
</div>
<div class="stack" style="gap:var(--space-8)"><p class="t-strong">At 16 px, beside a loading tab</p>
{browser_tabs()}
<p class="muted" style="max-width:68ch">The filled disc closes the gap, so the favicon reads as a Q rather than an open arc. Inside the product nothing loads with a ring: buttons wait with three quorum marks filling in turn, so the mark never stands for loading.</p></div>
<div class="mk__row">
<figure class="mk__lock">{lockup_svg(30.8)}<figcaption>Lockup, cap height 22</figcaption></figure>
<figure class="mk__lock">{lockup_svg(15.4)}<figcaption>Lockup, cap height 11</figcaption></figure>
</div>
<div class="stack" style="gap:var(--space-8)"><p class="t-strong">Motion</p>
<div class="mk__frames">{"".join(frames)}</div>
<p class="muted" style="max-width:68ch">The app presses the last mark in and spreads a ring outward when a quorum completes. The mark is the app’s quorum-closing animation at rest, so a launch screen could animate it the same way, and nowhere else.</p></div>
</div>
<div class="mk__side">
{cand("round-robin", "Round robin", "Three places in a circle, two sealed: the rule is about who signs, never the order.", "At small sizes it reads as “therefore” or a share icon, and it permanently says “Waiting on 1”.")}
{cand("two-of-four", "Two of four", "The Operations rule as four places, two filled on the diagonal.", "The crispest at 16 px, but a domino, and it hard-codes one vault’s rule into the brand.")}
{cand("seal-row", "The seal row", "The quorum marks exactly as the app draws them: two sealed, one open.", "Honest but weakest: a thin strip as a favicon, and the logo would compete with the real marks.")}
<div class="panel" style="padding:var(--space-16)"><p class="t-strong">Before it is final</p>
<p class="muted">A ring with a separate tail is a known way to draw a Q. Its proportions and even gap are what make it distinctive. Run a trademark search in classes 9, 36 and 42. In the product the mark stays in the ink colour, so blue only ever marks something you can act on.</p></div>
</div>
</div>
</section>'''


# ----------------------------------------------------------------------------------------- page: approval

APPROVE_ITEMS = [
    ("Two faces and a mono, each with one job.",
     "Public Sans for all interface text. Source Serif 4 only for the decision text, the words people sign. JetBrains Mono only for hashes, keys, addresses and IDs, cut in the middle with a copy button, and for the addresses inside the decision text."),
    ("One accent: cobalt ink.",
     "The app’s navy made brighter, #2D60C3 in light. It marks only what you can act on: the primary button, links, focus, selection and the current page. Status never uses it."),
    ("Status in five tones and nine words.",
     "Needs your signature, Waiting on 2, Approved, Rejected, Expired, Withdrawn, Queued, Paid and Failed. The app’s green, amber and red stay exactly as they are; Waiting on N is neutral, and a new steel blue is kept for Queued."),
    ("Radius by role, shadows only for things that float.",
     "4 for badges, 6 for buttons and inputs, 8 for cards and menus, 12 for dialogs and sheets, round for avatars and marks. Cards are flat with a hairline."),
    ("Working density.",
     "14 px interface text on nine styles, 32 px controls, 40 px single-line table rows (Home’s two-line rows start at 56 px), and 44 px targets with 16 px inputs on phones."),
    ("Evidence in three layers, and a decision code.",
     "The decision page has three tabs: Overview, then Evidence (an outcome sentence and the checks in plain words), then Technical (the hashes, signatures and log). The code A397-71F8 appears on the web and the phone so you can match them before you sign."),
    ("Dark mode from the first token.",
     f"Every colour has a measured dark value; dark surfaces get lighter instead of casting shadows; System, Light or Dark sits in the account menu. All {PAIRS_TOTAL} required contrast pairs pass in both themes."),
    ("The closing mark as the logo.",
     "A ring closed by the signature that completes it, in the ink colour, used for the logo, favicon and app icon, subject to the trademark search. Nothing in the product loads with a ring."),
]


def approve_section() -> str:
    items = "".join(f'<li><span class="alist__n">{i}</span><div><p class="alist__t">{t}</p><p>{d}</p></div></li>'
                    for i, (t, d) in enumerate(APPROVE_ITEMS, 1))
    later = [
        "Search and the command palette (R1)",
        "Help menu pages: keyboard shortcuts, what’s new, status and contact (R1)",
        "Avatars, Due soon and times in your own zone (R2)",
        "The workspace, its switcher and Members (R3)",
        "Notifications and the bell (R4)",
        "Decision types beyond General and Payment, and a required reject reason (R5)",
        "Withdrawing a decision (R5)",
        "The recipient’s payment history, such as “First payment from Operations to this address” (R5)",
        "The setting that lets the person who raised a decision approve it (S15)",
        "The decision code on the web and the phone (S17)",
        "Dark mode in the phone app, which needs a new APK (R7)",
    ]
    ll = "".join(f"<li><span>{x}</span></li>" for x in later)
    return f'''<section class="sec" aria-labelledby="approve">
<div class="sec__hd"><div><h2 class="sec__t" id="approve">What you are approving</h2>
<p class="sec__p">Eight decisions. Reply with the numbers you approve and anything to change; nothing is converted until you do.</p></div></div>
<ol class="alist">{items}</ol>
<div class="next">
<div class="panel"><h3>What happens next</h3><p>R1 converts every screen to this. The tokens and components become the product’s CSS and Jinja macros, the shell gets the sidebar, top bar and menus shown here, error pages and styled controls replace the browser’s, and every baseline screen gets an after twin at desktop and phone width, in both themes, for your review. The phone app takes the same tokens in R7.</p></div>
<div class="panel"><h3>Shown here, built in later phases</h3><ul>{ll}</ul></div>
</div>
<p class="foot">Built from tokens.css, contrast.md and screens.md in docs/plans/saas-rework/style-tile. The workspace, people, times and balances are illustrative; the payment’s text, payload hash and decision code come from Q-Vault’s own signing code.</p>
</section>'''


# ----------------------------------------------------------------------------------------- assemble

def build() -> str:
    head = ('<title>Q-Vault Style Tile</title>\n'
            '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400..700'
            '&amp;family=Source+Serif+4:opsz,wght@8..60,400..600&amp;family=JetBrains+Mono:wght@400;500&amp;display=swap">\n')
    style = f"<style>\n{TOKENS.strip()}\n\n{CSS.strip()}\n.sentinel {{ height: 1px; }}\n</style>\n"
    body = (f'{SPRITE}\n<div class="site" id="top">\n{bar()}\n{intro()}\n<main class="pagemain">\n'
            f'{screens_section()}\n{phone_section()}\n{type_section()}\n{colour_section()}\n{components_section()}\n'
            f'{mark_section()}\n{approve_section()}\n</main>\n</div>\n{dialogs()}\n')
    script = f"<script>\n{JS.strip()}\n</script>\n"
    return head + style + body + script


def check(page: str) -> None:
    ids = re.findall(r'\sid="([^"]+)"', page)
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"duplicate ids: {dupes}"
    for ref in re.findall(r'(?:aria-labelledby|aria-describedby|aria-controls|for)="([^"]+)"', page):
        for i in ref.split():
            assert i in ids, f"reference to a missing id: {i}"
    css = page.split("<style>")[1].split("</style>")[0].split(TOKENS.strip())[1]
    literal = re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", css)
    assert not literal, f"colour literals outside the tokens: {literal[:5]}"
    assert "<script" not in page.split("<script>")[0]
    assert page.count("<script") == 1


if __name__ == "__main__":
    page = build()
    check(page)
    OUT.write_text(page, encoding="utf-8", newline="\n")
    print(f"wrote {OUT} ({len(page.encode('utf-8')) / 1024:.0f} KB)")
