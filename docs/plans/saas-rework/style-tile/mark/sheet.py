"""Render the review sheet for the mark candidates. Called by build_marks.py; writes nothing itself."""
import html

SIZES = (16, 24, 32, 64)
RECOMMENDED = 'closing'


def sized(svg, w, h, decorative=True):
    svg = svg.strip()
    if decorative:
        svg = svg.replace('role="img" aria-label="Q-Vault"', 'aria-hidden="true" focusable="false"')
    return svg.replace('<svg ', f'<svg width="{w:g}" height="{h:g}" ', 1)


def lockup_at(b, cap_px):
    x0, y0, x1, y1 = b['box']
    k = cap_px / b['cap']
    return sized(b['lockup'], round((x1 - x0) * k, 2), round((y1 - y0) * k, 2))


def ground(b, tone):
    name = b['c']['name']
    mark = b['mark']
    sizes = ''.join(
        f'<figure><div class="m">{sized(mark, z, z)}</div><figcaption>{z}</figcaption></figure>'
        for z in SIZES)
    pixel = (f'<figure><canvas class="px" width="16" height="16" data-mark="{name}" '
             f'aria-label="The mark rasterised at 16 by 16 pixels, enlarged four times"></canvas>'
             f'<figcaption>16, real pixels, 4×</figcaption></figure>')
    lockups = (f'<figure>{lockup_at(b, 11)}<figcaption>Cap height 11</figcaption></figure>'
               f'<figure>{lockup_at(b, 22)}<figcaption>Cap height 22</figcaption></figure>')
    inuse = (f'<figure><div class="strip"><div class="tab">{sized(mark, 16, 16)}'
             f'<span>Approvals – Q-Vault</span></div></div>'
             f'<figcaption>Browser tab</figcaption></figure>'
             f'<figure><div class="icon">{sized(mark, 34, 34)}</div><figcaption>App icon</figcaption></figure>')
    label = 'Light' if tone == 'light' else 'Dark'
    return (f'<div class="ground {tone}" aria-label="{label} ground">'
            f'<div class="row sizes">{sizes}{pixel}</div>'
            f'<div class="row lockups">{lockups}</div>'
            f'<div class="row inuse">{inuse}</div></div>')


def candidate(b, index):
    c = b['c']
    rec = c['name'] == RECOMMENDED
    tag = '<span class="tag">Recommended</span>' if rec else ''
    return (f'<section class="cand" id="{c["name"]}">'
            f'<header><h2>{html.escape(c["title"])}{tag}</h2>'
            f'<p class="idea">{html.escape(c["idea"])}</p>'
            f'<p class="files">{c["name"]}.svg and {c["name"]}-lockup.svg</p></header>'
            f'<div class="grounds">{ground(b, "light")}{ground(b, "dark")}</div></section>')


def construction(b):
    k = b['construction']
    grid = ''.join(
        f'<line x1="{i}" y1="0" x2="{i}" y2="32" class="{"g4" if i % 4 == 0 else "g1"}"/>'
        f'<line x1="0" y1="{i}" x2="32" y2="{i}" class="{"g4" if i % 4 == 0 else "g1"}"/>'
        for i in range(33))
    mark_paths = b['mark'].split('>', 1)[1].rsplit('</svg>', 1)[0]
    cx, cy = k['cx'], k['cy']
    lines = (
        f'<circle cx="{cx}" cy="{cy}" r="{k["Ro"]}" class="c"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{k["Ri"]}" class="c"/>'
        f'<circle cx="{k["mx"]:.3f}" cy="{k["my"]:.3f}" r="{k["rc"]}" class="c"/>'
        f'<circle cx="{k["mx"]:.3f}" cy="{k["my"]:.3f}" r="{k["r"]}" class="s"/>'
        f'<line x1="{cx}" y1="{cy}" x2="{k["mx"] + 4:.3f}" y2="{k["my"] + 4:.3f}" class="s"/>'
        f'<line x1="{cx - 4}" y1="{cy}" x2="{cx + 4}" y2="{cy}" class="s"/>'
        f'<line x1="{cx}" y1="{cy - 4}" x2="{cx}" y2="{cy + 4}" class="s"/>')
    drawing = (f'<svg class="build" viewBox="-0.5 -0.5 33 33" width="300" height="300" role="img" '
               f'aria-label="Construction of the closing mark on its 32-unit grid">'
               f'<g class="grid">{grid}</g><g class="fill">{mark_paths}</g><g class="con">{lines}</g></svg>')
    frames = ''.join(
        f'<figure><div class="m">{sized(svg, 48, 48)}</div><figcaption>{html.escape(cap)}</figcaption></figure>'
        for cap, svg in k['frames'])
    return drawing, frames


CSS = """
:root {
  --paper: #F7F8FA; --surface: #FFFFFF; --sunk: #EFF1F5; --sunk2: #E7EAF0;
  --rule: #DDE1E9; --ink: #16233A; --ink2: #4A5568; --ink3: #6B7688;
  --chrome: #0E1729; --chrome2: #1B2740; --chrome-rule: #293552;
  --chrome-ink: #EEF1F6; --chrome-ink2: #93A0B8;
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0; background: var(--surface); color: var(--ink);
  font: 400 14px/20px 'Public Sans', system-ui, sans-serif;
  font-variant-numeric: tabular-nums;
  -webkit-font-smoothing: antialiased;
}
main { max-width: 1360px; padding: 40px 40px 56px; }
h1 { font-size: 20px; line-height: 28px; font-weight: 600; letter-spacing: -0.01em; margin: 0; }
h2 { font-size: 16px; line-height: 24px; font-weight: 600; margin: 0; }
p { margin: 0; }
.lede { color: var(--ink2); max-width: 78ch; margin-top: 6px; }
.meta { display: flex; gap: 24px; margin-top: 12px; color: var(--ink3); font-size: 12px; line-height: 16px; }
.meta b { font-weight: 500; color: var(--ink2); }

.cand { display: grid; grid-template-columns: 248px 1fr; gap: 32px;
        border-top: 1px solid var(--rule); padding: 28px 0; }
.cand:first-of-type { margin-top: 28px; }
.idea { color: var(--ink2); margin-top: 8px; }
.files { color: var(--ink3); font-size: 12px; line-height: 16px; margin-top: 12px; }
.tag { display: inline-block; margin-left: 8px; padding: 2px 6px; border-radius: 4px;
       background: var(--sunk2); color: var(--ink2); font-size: 12px; line-height: 16px;
       font-weight: 500; vertical-align: 2px; }

.grounds { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; min-width: 0; }
.ground { border-radius: 8px; padding: 20px 20px 18px; min-width: 0; }
.ground.light { background: var(--paper); color: var(--ink); border: 1px solid var(--rule);
                --cap: var(--ink3); --line: var(--rule); --tab: var(--surface); --tab-line: var(--rule);
                --strip: var(--sunk2); --icon: var(--ink); --icon-ink: var(--paper); }
.ground.dark { background: var(--chrome); color: var(--chrome-ink); border: 1px solid var(--chrome);
               --cap: var(--chrome-ink2); --line: var(--chrome-rule); --tab: var(--chrome2);
               --tab-line: var(--chrome-rule); --strip: #0A1222; --icon: var(--chrome2);
               --icon-ink: var(--chrome-ink); }
.row { display: flex; align-items: flex-end; gap: 22px; flex-wrap: wrap; }
.row + .row { margin-top: 18px; padding-top: 18px; border-top: 1px solid var(--line); }
figure { margin: 0; display: flex; flex-direction: column; align-items: flex-start; gap: 8px; }
figcaption { font-size: 12px; line-height: 16px; color: var(--cap); white-space: nowrap; }
svg { display: block; }
canvas.px { width: 64px; height: 64px; image-rendering: pixelated; display: block;
            outline: 1px dashed var(--line); outline-offset: 0; }
.lockups { gap: 36px; }
.strip { display: flex; padding: 6px 28px 0 8px; background: var(--strip);
         border-bottom: 1px solid var(--tab-line); border-radius: 6px 6px 0 0; }
.tab { display: flex; align-items: center; gap: 8px; height: 32px; padding: 0 14px 0 10px;
       margin-bottom: -1px; background: var(--tab); border: 1px solid var(--tab-line);
       border-bottom: 0; border-radius: 6px 6px 0 0; font-size: 12px; line-height: 16px;
       color: inherit; }
.icon { width: 56px; height: 56px; border-radius: 13px; display: grid; place-items: center;
        background: var(--icon); color: var(--icon-ink); }
.dark .icon { box-shadow: inset 0 0 0 1px var(--chrome-rule); }

.rec { border-top: 1px solid var(--rule); padding-top: 28px; display: grid;
       grid-template-columns: 300px 1fr; gap: 40px; align-items: start; }
.rec h2 { margin-bottom: 10px; }
.rec p + p { margin-top: 10px; }
.rec .body { max-width: 74ch; color: var(--ink); }
.rec h3 { font-size: 14px; line-height: 20px; font-weight: 600; margin: 22px 0 6px; }
.rec ul { margin: 0; padding-left: 18px; color: var(--ink2); }
.rec li + li { margin-top: 6px; }
.build .g1 { stroke: #E7EAF0; stroke-width: 0.04; }
.build .g4 { stroke: #C9D0DC; stroke-width: 0.06; }
.build .fill { fill: #DCE3EE; }
.build .con .c { fill: none; stroke: var(--ink); stroke-width: 0.07; stroke-dasharray: 0.35 0.3; }
.build .con .s { fill: none; stroke: var(--ink); stroke-width: 0.07; }
.spec { margin-top: 12px; color: var(--ink2); font-size: 12px; line-height: 18px; }
.spec div + div { margin-top: 2px; }
.frames { display: flex; gap: 28px; margin-top: 14px; color: var(--ink); }

@media (max-width: 1180px) {
  .cand, .rec { grid-template-columns: 1fr; gap: 16px; }
  .idea { max-width: 72ch; }
}
@media (max-width: 760px) {
  main { padding: 24px 16px 40px; }
  .grounds { grid-template-columns: 1fr; }
  .meta { flex-direction: column; gap: 4px; }
  .build { width: 100%; height: auto; max-width: 300px; }
}
"""

JS = """
// Rasterise each mark at exactly 16x16 device pixels, in the ground's own ink, so the enlargement
// shows what a favicon really gets rather than a smooth vector scaled up.
for (const cv of document.querySelectorAll('canvas.px')) {
  const src = document.getElementById('src-' + cv.dataset.mark).textContent;
  const ink = getComputedStyle(cv.closest('.ground')).color;
  const svg = src.replace('fill="currentColor"', 'fill="' + ink + '" width="16" height="16"');
  const img = new Image();
  img.onload = () => cv.getContext('2d').drawImage(img, 0, 0, 16, 16);
  img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
}
"""


def render(built):
    rec = next(b for b in built if b['c']['name'] == RECOMMENDED)
    drawing, frames = construction(rec)
    sources = ''.join(
        f'<script type="text/plain" id="src-{b["c"]["name"]}">{b["mark"].strip()}</script>'
        for b in built)
    cands = ''.join(candidate(b, i) for i, b in enumerate(built))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Q-Vault logo mark</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>
<main>
<h1>Logo mark: four candidates</h1>
<p class="lede">Each candidate is developed from the quorum seal, the marks the app already draws to show how
many of the required signatures a decision has. Each is one colour and takes the colour of the text around
it, so it themes with no second version. All are drawn on a 32-unit grid, so 16px is exactly half scale,
and each is placed so its strokes and gaps fall on whole pixels at 16px rather than smearing across two.</p>
<div class="meta"><span><b>For</b> R1.1 style tile, owner approval</span><span><b>Wordmark</b> Public Sans 600, outlined, font kerning</span><span><b>Grounds</b> #F7F8FA with #16233A, and #0E1729 with #EEF1F6</span></div>
{cands}
<section class="rec" id="recommendation">
<div>{drawing}
<div class="spec">
<div>Grid 32. Ring 26 across, stroke 4, centred at 15, 15.</div>
<div>Mark 10 across, centred at 25, 25 on the 45° diagonal, which leaves an even margin of 2 on all four sides.</div>
<div>Moat 2, concentric with the mark: one whole pixel at 16px.</div>
<div>In the lockup the ring is 1.3 times the cap height, so its stroke is 1.2 times the wordmark’s stem.</div>
</div>
</div>
<div class="body">
<h2>Recommendation: the closing mark</h2>
<p>It is the only candidate that is a symbol rather than a pattern. It has a silhouette, a ring with
something arriving at it, and that silhouette survives everywhere the brand has to live: one whole
pixel of moat at 16px in a browser tab, a solid shape on an app icon, a blind emboss on paper. Because
it reads as a Q, the favicon and the app icon carry the name without any lettering.</p>
<p>It draws the mechanism, not a state. The other three are counts of marks, and in this product a count
of marks is data: the app draws one mark for each required signature on every decision, and fills them as
people sign. Read that way, round robin and the seal row say “Waiting on 1” and two of four says
“Waiting on 2”, permanently, in the header of the very screens where the real marks appear. The
closing mark keeps the idea and leaves the counting to the interface. Its disc is drawn exactly like the
app’s signed mark; the ring is the seal that signature completes.</p>
<p>It is the product’s one moment of motion, already built. When a signature completes the quorum,
the app presses the last mark in and lets a ring spread outward. The logo is that moment held still, so
the brand and the product share one gesture: if the mark ever moves, on the app’s launch screen for
instance, it moves exactly like this, and nowhere else.</p>
<div class="frames">{frames}</div>
<h3>Why not the others</h3>
<ul>
<li><b>Round robin</b> has the best story, but three dots in a triangle read first as “therefore”
and as the share icon, and its open apex is a single pixel of line at 16px.</li>
<li><b>Two of four</b> is the crispest at 16px, but at a glance it is a domino, and it hard-codes one
vault’s rule into a brand whose vaults come in every size.</li>
<li><b>The seal row</b> is the most honest and the weakest: wide, so the favicon is a thin strip, and at
small sizes it is the “more” menu. Keep it where it belongs, in the interface.</li>
</ul>
<h3>Before adoption</h3>
<ul>
<li>A ring with a separate tail is a known way to build a Q, so what makes this one ownable is its
proportions and the concentric moat. Run a trademark search on the shape in classes 9, 36 and 42 before
it is final.</li>
<li>In the lockup the mark sits next to the wordmark’s own Q. Larger and drawn rather than typeset,
it reads as a symbol rather than a second letter, but judge that at the two sizes above.</li>
<li>Default colour is the ink. If the style tile gives identity to the accent, the mark may take it on
marketing surfaces; in the product it stays ink, so the accent keeps meaning “you can act on this”.</li>
<li>Never redraw it per size. The 32-unit master is the favicon, the app icon and the print file.</li>
</ul>
</div>
</section>
</main>
{sources}
<script>{JS}</script>
</body>
</html>
"""
