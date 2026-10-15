"""Build the Q-Vault logo-mark candidates, their lockups, and the review sheet.

Every mark is drawn on a 32-unit grid (viewBox 0 0 32 32), so 16px is exactly half scale, 32px is
1:1 and 64px is 2x. Everything is circles and annuli computed here, so the geometry is exact rather
than eyeballed, and one colour throughout (fill="currentColor") so a mark themes with its context.

The wordmark "Q-Vault" is Public Sans 600, outlined from the font file the app already vendors, with
the font's own GPOS kerning applied (checked against Chromium's shaping: 7102 font units both ways).

Run with any Python that has fontTools (the q-vault .venv does not; the system Python 3.10 does):
    python build_marks.py
Outputs, next to this file: <name>.svg, <name>-lockup.svg, sheet.html.
"""
import math
import pathlib

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[4]
FONT = REPO / 'mobile/node_modules/@expo-google-fonts/public-sans/600SemiBold/PublicSans_600SemiBold.ttf'


# --------------------------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------------------------

def n(v):
    s = f"{v:.3f}".rstrip('0').rstrip('.')
    return '0' if s in ('-0', '') else s


def circle(cx, cy, r, ccw=False):
    sw = 0 if ccw else 1
    return (f"M{n(cx - r)} {n(cy)}A{n(r)} {n(r)} 0 1 {sw} {n(cx + r)} {n(cy)}"
            f"A{n(r)} {n(r)} 0 1 {sw} {n(cx - r)} {n(cy)}Z")


def annulus(cx, cy, r_out, r_in):
    # Opposite windings, so the hole survives under the default nonzero fill rule.
    return circle(cx, cy, r_out) + circle(cx, cy, r_in, ccw=True)


def annulus_cut(cx, cy, r_out, r_in, mx, my, rc):
    """The annulus minus the disc (mx, my, rc), as one closed path. The two cut ends are arcs
    concentric with the cutting disc, so the clearance around the mark is an even moat."""
    d = math.hypot(mx - cx, my - cy)
    phi = math.atan2(my - cy, mx - cx)

    def half_angle(R):
        return math.acos((d * d + R * R - rc * rc) / (2 * d * R))

    ao, ai = half_angle(r_out), half_angle(r_in)

    def P(R, a):
        return cx + R * math.cos(a), cy + R * math.sin(a)

    o1, o2 = P(r_out, phi + ao), P(r_out, phi - ao)
    i1, i2 = P(r_in, phi + ai), P(r_in, phi - ai)

    def cut(a, b):
        cross = (a[0] - mx) * (b[1] - my) - (a[1] - my) * (b[0] - mx)
        return f"A{n(rc)} {n(rc)} 0 0 {1 if cross > 0 else 0} {n(b[0])} {n(b[1])}"

    return (f"M{n(o1[0])} {n(o1[1])}A{n(r_out)} {n(r_out)} 0 1 1 {n(o2[0])} {n(o2[1])}"
            + cut(o2, i2)
            + f"A{n(r_in)} {n(r_in)} 0 1 0 {n(i1[0])} {n(i1[1])}"
            + cut(i1, o1) + "Z")


class Shape:
    """A path plus its exact bounds, so lockups can be laid out on real geometry."""

    def __init__(self, d, x0, y0, x1, y1):
        self.d, self.box = d, (x0, y0, x1, y1)


def disc(cx, cy, r):
    return Shape(circle(cx, cy, r), cx - r, cy - r, cx + r, cy + r)


def ring(cx, cy, r, stroke):
    return Shape(annulus(cx, cy, r, r - stroke), cx - r, cy - r, cx + r, cy + r)


def bounds(shapes):
    xs0, ys0, xs1, ys1 = zip(*(s.box for s in shapes))
    return min(xs0), min(ys0), max(xs1), max(ys1)


# --------------------------------------------------------------------------------------------
# The candidates (32-unit grid)
# --------------------------------------------------------------------------------------------

def closing():
    # The ring is the decision, open until the last required signature lands; the disc is that
    # signature, sitting in the gap it closes. Ring 26 across with a 4 stroke, centred at 15,15; the
    # disc is 10 across, centred at 25,25 on the 45-degree diagonal, which leaves the whole mark an
    # even 2-unit margin on all four sides and reads as the tail of a Q. The moat around the disc is
    # 2 units (one whole pixel at 16px), concentric with it. At 16px every extreme edge of the ring
    # and of the disc lands on a whole pixel.
    cx = cy = 15
    Ro, w, r, moat = 13, 4, 5, 2
    mx = my = 25
    cut = annulus_cut(cx, cy, Ro, Ro - w, mx, my, r + moat)
    body = Shape(cut, cx - Ro, cy - Ro, cx + Ro, cy + Ro)
    # The same mark as motion, for the sheet: the open seal, the last signature on its way in, and
    # the mark at rest. The gap never changes; only the signature moves.
    far = cx + 19 * math.sqrt(0.5)
    frame_box = (-2, -2, 34, 34)
    frames = [
        ('Waiting on 1', svg_doc([cut], frame_box, 'Q-Vault')),
        ('Signing', svg_doc([cut, circle(far, far, r)], frame_box, 'Q-Vault')),
        ('Approved', svg_doc([cut, circle(mx, my, r)], frame_box, 'Q-Vault')),
    ]
    construction = dict(cx=cx, cy=cy, Ro=Ro, Ri=Ro - w, mx=mx, my=my, r=r, rc=r + moat,
                        frames=frames)
    return [body, disc(mx, my, r)], construction


def round_robin():
    # Three places on a circle, two sealed, the apex open. Marks 12 across; apex at 16,8 and base at
    # 8,22 and 24,22, so every centre and edge is on a whole pixel at 16px. The triangle is 14 tall
    # on a 16 base (60.3 degrees at the base, equilateral to the eye), and the group sits one unit
    # high because two marks at the base weigh more than one at the top. Open stroke 2 (1px at 16).
    r, stroke = 6, 2
    return [ring(16, 8, r, stroke), disc(8, 22, r), disc(24, 22, r)]


def two_of_four():
    # Four places, any two: the Operations rule. Filled on the diagonal so it can never read as a
    # sequence or a fill level. Centres on 8 and 24, marks 12 across, so the gaps are 4 (2px at
    # 16px) and the margin is 2 all round. Open stroke 2, which leaves a 4px hole at 16px.
    r, stroke, a, b = 6, 2, 8, 24
    return [disc(a, a, r), ring(b, a, r, stroke), ring(a, b, r, stroke), disc(b, b, r)]


def seal_row(r=4, gap=2, stroke=2, cy=16):
    # The app's own quorum marks, two sealed and one open. For the square mark the row is snapped to
    # the 16px grid (centres 6, 16, 26; marks 8 across); the lockup passes its own, airier spacing.
    W = 6 * r + 2 * gap
    x = 16 - W / 2 + r
    out = []
    for i in range(3):
        out.append(disc(x, cy, r) if i < 2 else ring(x, cy, r, stroke))
        x += 2 * r + gap
    return out


CANDIDATES = [
    dict(
        name='closing',
        title='The closing mark',
        idea='A decision is an open seal until the last required signature lands. The ring is the '
             'decision; the mark in its gap is the signature that closes it. Together they write the Q.',
        build=closing,
        # Lockup: the ring's centre sits on the middle of the cap height; the mark drops below the
        # baseline the way a Q's tail does.
        ring_to_cap=1.30, word_gap=0.50,
    ),
    dict(
        name='round-robin',
        title='Round robin',
        idea='Petitioners once signed in a circle so that no name came first. Three places, any two '
             'sealed: the rule is about who, never about order.',
        build=round_robin,
        ring_to_cap=1.40, word_gap=0.48,
    ),
    dict(
        name='two-of-four',
        title='Two of four',
        idea='The Operations vault’s rule as four places, any two filled. Filled on the diagonal '
             'so it never reads as a sequence or a level.',
        build=two_of_four,
        ring_to_cap=1.36, word_gap=0.52,
    ),
    dict(
        name='seal-row',
        title='The seal row',
        idea='The quorum marks exactly as the app draws them on every decision: two sealed, one still '
             'open. The logo is the interface.',
        build=seal_row,
        ring_to_cap=None, word_gap=0.60,
    ),
]


# --------------------------------------------------------------------------------------------
# The wordmark
# --------------------------------------------------------------------------------------------

FONT_TT = TTFont(str(FONT))
UPM = FONT_TT['head'].unitsPerEm
CAP = FONT_TT['OS/2'].sCapHeight
XH = FONT_TT['OS/2'].sxHeight
GLYPHS = FONT_TT.getGlyphSet()
CMAP = FONT_TT.getBestCmap()


def kern(left, right):
    gpos = FONT_TT['GPOS'].table
    for rec in gpos.FeatureList.FeatureRecord:
        if rec.FeatureTag != 'kern':
            continue
        for li in rec.Feature.LookupListIndex:
            lookup = gpos.LookupList.Lookup[li]
            for st in lookup.SubTable:
                if lookup.LookupType == 9:
                    st = st.ExtSubTable
                if not hasattr(st, 'Coverage') or left not in st.Coverage.glyphs:
                    continue
                if st.Format == 1:
                    for pvr in st.PairSet[st.Coverage.glyphs.index(left)].PairValueRecord:
                        if pvr.SecondGlyph == right:
                            return getattr(pvr.Value1, 'XAdvance', 0) or 0
                elif st.Format == 2:
                    c1 = st.ClassDef1.classDefs.get(left, 0)
                    c2 = st.ClassDef2.classDefs.get(right, 0)
                    x = getattr(st.Class1Record[c1].Class2Record[c2].Value1, 'XAdvance', 0) or 0
                    if x:
                        return x
    return 0


def wordmark(text, cap_height, x, baseline, tracking=-0.008):
    """Outline `text` so its caps are `cap_height` tall, starting at x on `baseline`.
    Returns (path data, bounds)."""
    s = cap_height / CAP
    names = [CMAP[ord(c)] for c in text]
    pen = SVGPathPen(GLYPHS, ntos=lambda v: n(v))
    bpen = BoundsPen(GLYPHS)
    pen_x = 0.0
    for i, g in enumerate(names):
        t = (s, 0, 0, -s, x + pen_x * s, baseline)
        GLYPHS[g].draw(TransformPen(pen, t))
        GLYPHS[g].draw(TransformPen(bpen, t))
        pen_x += GLYPHS[g].width + tracking * UPM
        if i + 1 < len(names):
            pen_x += kern(g, names[i + 1])
    return pen.getCommands(), bpen.bounds


# --------------------------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------------------------

def svg_doc(paths, box, label, pad=0):
    x0, y0, x1, y1 = box
    vb = f"{n(x0 - pad)} {n(y0 - pad)} {n(x1 - x0 + 2 * pad)} {n(y1 - y0 + 2 * pad)}"
    body = ''.join(f'<path d="{d}"/>' for d in paths)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" fill="currentColor" '
            f'role="img" aria-label="{label}">{body}</svg>\n')


def lockup(c, shapes):
    """Mark, then the wordmark, one colour, laid out on the wordmark's cap height.

    Returns (svg, cap height in viewBox units) so the sheet can show every lockup at the same
    cap height rather than the same box height."""
    if c['name'] == 'seal-row':
        # The row is a prefix, not a symbol: marks a little under the cap height, centred on it,
        # spaced like the app's row rather than like a favicon.
        cap = 18.0
        r = cap * 0.30
        mark = seal_row(r=r, gap=r * 0.9, stroke=cap * 0.125, cy=0)
        centre_y = 0.0
        gap = cap * c['word_gap']
    else:
        mark = shapes
        x0, y0, x1, y1 = bounds(mark)
        if c['name'] == 'closing':
            # Size and centre on the ring, not the box: the tail is a descender, like a Q's.
            ring_d, centre_y = 26.0, 15.0
        else:
            ring_d, centre_y = y1 - y0, (y0 + y1) / 2
        cap = ring_d / c['ring_to_cap']
        gap = cap * c['word_gap']
    mx0, my0, mx1, my1 = bounds(mark)
    baseline = centre_y + cap / 2
    # Measure the gap to the Q's ink, not to its side bearing.
    _, probe = wordmark('Q-Vault', cap, 0, baseline)
    word_d, wb = wordmark('Q-Vault', cap, mx1 + gap - probe[0], baseline)
    box = (mx0, min(my0, wb[1]), wb[2], max(my1, wb[3]))
    vb = f"{n(box[0])} {n(box[1])} {n(box[2] - box[0])} {n(box[3] - box[1])}"
    body = ''.join(f'<path d="{s.d}"/>' for s in mark)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" fill="currentColor" '
           f'role="img" aria-label="Q-Vault">{body}<path d="{word_d}"/></svg>\n')
    return svg, cap, box


def main():
    built = []
    for c in CANDIDATES:
        result = c['build']()
        shapes, construction = (result if isinstance(result, tuple) else (result, None))
        mark_svg = svg_doc([s.d for s in shapes], (0, 0, 32, 32), 'Q-Vault')
        lock_svg, cap, box = lockup(c, shapes)
        (HERE / f"{c['name']}.svg").write_text(mark_svg, encoding='utf-8')
        (HERE / f"{c['name']}-lockup.svg").write_text(lock_svg, encoding='utf-8')
        built.append(dict(c=c, mark=mark_svg, lockup=lock_svg, cap=cap, box=box,
                          construction=construction))
    import sys
    sys.path.insert(0, str(HERE))
    from sheet import render
    (HERE / 'sheet.html').write_text(render(built), encoding='utf-8')
    for b in built:
        print(b['c']['name'], 'lockup box', [n(v) for v in b['box']])


if __name__ == '__main__':
    main()
