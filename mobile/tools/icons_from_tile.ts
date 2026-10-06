// Builds the phone's icon font from the style tile's sprite (phone-ux §2.2).
//
// The tile draws its icons as strokes on a 16-unit grid (1.5 wide, round caps and joins). A font
// can only fill shapes, so each stroke is outlined here, at build time, into filled contours:
//
//   - each run of a path between sharp corners becomes one strip, offset half the stroke width to
//     either side (curves are flattened first, to well under a hundredth of a pixel at 24pt);
//   - each corner and each open end gets a disc, which is exactly what a round join and a round cap
//     draw;
//   - a closed run with no corner at all (a circle, a rounded rectangle) becomes a ring: its outer
//     offset, plus its inner offset wound the other way as a hole.
//
// Every contour is wound the same way, so the overlaps union under the nonzero fill rule that
// TrueType rasterisers use; nothing has to compute a boolean union. Fills the tile writes as dots
// (fill="currentColor" stroke="none") are copied as shapes.
//
// The output is a TrueType font loaded through expo-font, so the icons ship over the air and the
// web harness draws them too. tests/test_mobile_icons.py regenerates both outputs and fails if the
// committed copies differ.
//
//   node tools/icons_from_tile.ts [font.ttf] [glyphs.ts]

import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import svgpath from 'svgpath';
import svg2ttf from 'svg2ttf';

const here = dirname(fileURLToPath(import.meta.url));
const mobile = resolve(here, '..');
const repo = resolve(mobile, '..');

const TILE = resolve(repo, 'docs', 'plans', 'saas-rework', 'style-tile', 'style-tile.html');
const ADDITIONS = resolve(here, 'icons', 'phone-additions.svg');
const fontOut = process.argv[2] ?? resolve(mobile, 'assets', 'fonts', 'QVaultIcons.ttf');
const glyphsOut = process.argv[3] ?? resolve(mobile, 'src', 'theme', 'icons.generated.ts');

const STROKE = 1.5;
const UNIT = 64; // font units per grid unit: 16 * 64 = 1024 per em
const EM = 16 * UNIT;
const TOLERANCE = 0.01; // grid units: 0.015px at 24pt
const CORNER = (22 * Math.PI) / 180; // a turn sharper than this is a join, drawn as a disc
const FIRST_CODEPOINT = 0xe001;

type Pt = [number, number];
type Contour = { points: Pt[]; quadratic?: boolean };
type Paint = 'stroke' | 'fill' | 'both' | 'knockout';

// -- reading the sprites --------------------------------------------------------------------------

function symbols(markup: string): Map<string, string> {
  const out = new Map<string, string>();
  for (const m of markup.matchAll(/<symbol id="i-([a-z0-9-]+)" viewBox="0 0 16 16">([\s\S]*?)<\/symbol>/g)) {
    out.set(m[1], m[2]);
  }
  return out;
}

function attrs(source: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const m of source.matchAll(/([a-z-]+)="([^"]*)"/g)) out[m[1]] = m[2];
  return out;
}

const n = (v: string | undefined, fallback = 0) => (v === undefined ? fallback : Number(v));

function elementPath(tag: string, a: Record<string, string>): string {
  if (tag === 'path') return a.d;
  if (tag === 'circle') {
    const [cx, cy, r] = [n(a.cx), n(a.cy), n(a.r)];
    return `M${cx - r} ${cy}A${r} ${r} 0 1 0 ${cx + r} ${cy}A${r} ${r} 0 1 0 ${cx - r} ${cy}Z`;
  }
  if (tag === 'rect') {
    const [x, y, w, h] = [n(a.x), n(a.y), n(a.width), n(a.height)];
    const r = Math.min(n(a.rx, n(a.ry)), w / 2, h / 2);
    if (r <= 0) return `M${x} ${y}H${x + w}V${y + h}H${x}Z`;
    return (
      `M${x + r} ${y}H${x + w - r}A${r} ${r} 0 0 1 ${x + w} ${y + r}V${y + h - r}` +
      `A${r} ${r} 0 0 1 ${x + w - r} ${y + h}H${x + r}A${r} ${r} 0 0 1 ${x} ${y + h - r}` +
      `V${y + r}A${r} ${r} 0 0 1 ${x + r} ${y}Z`
    );
  }
  throw new Error(`unsupported element <${tag}>`);
}

function paintOf(a: Record<string, string>): Paint {
  if (a['data-paint']) return a['data-paint'] as Paint;
  if (a.fill === 'currentColor' && a.stroke === 'none') return 'fill';
  return 'stroke';
}

// -- flattening -----------------------------------------------------------------------------------

type Subpath = { points: Pt[]; closed: boolean };

const lerp = (a: Pt, b: Pt, t: number): Pt => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];

function distToLine(p: Pt, a: Pt, b: Pt): number {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len = Math.hypot(dx, dy);
  if (len < 1e-9) return Math.hypot(p[0] - a[0], p[1] - a[1]);
  return Math.abs((p[0] - a[0]) * dy - (p[1] - a[1]) * dx) / len;
}

function cubic(p0: Pt, p1: Pt, p2: Pt, p3: Pt, out: Pt[], depth = 0) {
  if (depth > 12 || Math.max(distToLine(p1, p0, p3), distToLine(p2, p0, p3)) <= TOLERANCE) {
    out.push(p3);
    return;
  }
  const a = lerp(p0, p1, 0.5);
  const b = lerp(p1, p2, 0.5);
  const c = lerp(p2, p3, 0.5);
  const d = lerp(a, b, 0.5);
  const e = lerp(b, c, 0.5);
  const m = lerp(d, e, 0.5);
  cubic(p0, a, d, m, out, depth + 1);
  cubic(m, e, c, p3, out, depth + 1);
}

function flatten(d: string): Subpath[] {
  const subpaths: Subpath[] = [];
  let current: Subpath | null = null;
  svgpath(d)
    .abs()
    .unarc()
    .unshort()
    .iterate((seg: Array<string | number>, _i: number, x: number, y: number) => {
      const s = seg as [string, ...number[]];
      const at: Pt = [x, y];
      switch (s[0]) {
        case 'M':
          current = { points: [[s[1], s[2]]], closed: false };
          subpaths.push(current);
          break;
        case 'L':
          current!.points.push([s[1], s[2]]);
          break;
        case 'H':
          current!.points.push([s[1], y]);
          break;
        case 'V':
          current!.points.push([x, s[1]]);
          break;
        case 'C':
          cubic(at, [s[1], s[2]], [s[3], s[4]], [s[5], s[6]], current!.points);
          break;
        case 'Q': {
          // Degree-elevated, so one flattening routine serves both.
          const q: Pt = [s[1], s[2]];
          const end: Pt = [s[3], s[4]];
          cubic(at, lerp(at, q, 2 / 3), lerp(end, q, 2 / 3), end, current!.points);
          break;
        }
        case 'Z':
        case 'z':
          current!.closed = true;
          break;
        default:
          throw new Error(`unexpected segment ${s[0]}`);
      }
    });
  for (const sp of subpaths) {
    const pts: Pt[] = [];
    for (const p of sp.points) {
      const last = pts[pts.length - 1];
      if (!last || Math.hypot(p[0] - last[0], p[1] - last[1]) > 1e-6) pts.push(p);
    }
    if (sp.closed && pts.length > 1) {
      const [f, l] = [pts[0], pts[pts.length - 1]];
      if (Math.hypot(f[0] - l[0], f[1] - l[1]) < 1e-6) pts.pop();
    }
    sp.points = pts;
  }
  return subpaths;
}

// -- outlining ------------------------------------------------------------------------------------

const sub = (a: Pt, b: Pt): Pt => [a[0] - b[0], a[1] - b[1]];
const unit = (v: Pt): Pt => {
  const l = Math.hypot(v[0], v[1]);
  return [v[0] / l, v[1] / l];
};
const normal = (a: Pt, b: Pt): Pt => {
  const [dx, dy] = unit(sub(b, a));
  return [-dy, dx];
};
const angle = (a: Pt, b: Pt, c: Pt) => {
  const u = unit(sub(b, a));
  const v = unit(sub(c, b));
  return Math.acos(Math.max(-1, Math.min(1, u[0] * v[0] + u[1] * v[1])));
};

/** A disc as eight quadratic arcs: what a round cap or join draws at a point. */
function disc(c: Pt, r: number): Contour {
  const pts: Pt[] = [];
  const k = r / Math.cos(Math.PI / 8);
  for (let i = 0; i < 8; i++) {
    const on = (i * Math.PI) / 4;
    const off = on + Math.PI / 8;
    pts.push([c[0] + r * Math.cos(on), c[1] + r * Math.sin(on)]);
    pts.push([c[0] + k * Math.cos(off), c[1] + k * Math.sin(off)]);
  }
  return { points: pts, quadratic: true };
}

/** Offset points either side of a run, with each interior vertex mitred along its bisector. */
function offsets(run: Pt[], h: number, closed: boolean): { left: Pt[]; right: Pt[] } {
  const left: Pt[] = [];
  const right: Pt[] = [];
  const m = run.length;
  for (let i = 0; i < m; i++) {
    const prev = closed ? run[(i - 1 + m) % m] : run[i - 1];
    const next = closed ? run[(i + 1) % m] : run[i + 1];
    let nv: Pt;
    if (prev && next) {
      const n1 = normal(prev, run[i]);
      const n2 = normal(run[i], next);
      const bis = unit([n1[0] + n2[0], n1[1] + n2[1]]);
      const scale = 1 / Math.max(0.5, bis[0] * n1[0] + bis[1] * n1[1]);
      nv = [bis[0] * scale, bis[1] * scale];
    } else {
      nv = prev ? normal(prev, run[i]) : normal(run[i], next!);
    }
    left.push([run[i][0] + nv[0] * h, run[i][1] + nv[1] * h]);
    right.push([run[i][0] - nv[0] * h, run[i][1] - nv[1] * h]);
  }
  return { left, right };
}

function outline(sp: Subpath, width: number): Contour[] {
  const h = width / 2;
  const pts = sp.points;
  if (pts.length === 1) return [disc(pts[0], h)];
  const m = pts.length;
  const out: Contour[] = [];

  // Where the path turns sharply: a join, so the run breaks there and a disc covers the corner.
  const corners = new Set<number>();
  for (let i = 0; i < m; i++) {
    const prev = sp.closed ? pts[(i - 1 + m) % m] : pts[i - 1];
    const next = sp.closed ? pts[(i + 1) % m] : pts[i + 1];
    if (!prev || !next || angle(prev, pts[i], next) > CORNER) corners.add(i);
  }

  if (sp.closed && corners.size === 0) {
    const { left, right } = offsets(pts, h, true);
    out.push({ points: left }, { points: right });
    return out;
  }

  for (const i of corners) out.push(disc(pts[i], h));
  const order = [...corners].sort((a, b) => a - b);
  const runs: Pt[][] = [];
  if (sp.closed) {
    for (let k = 0; k < order.length; k++) {
      const a = order[k];
      const b = order[(k + 1) % order.length];
      const run: Pt[] = [];
      for (let i = a; ; i = (i + 1) % m) {
        run.push(pts[i]);
        if (i === b && run.length > 1) break;
      }
      runs.push(run);
    }
  } else {
    for (let k = 0; k + 1 < order.length; k++) runs.push(pts.slice(order[k], order[k + 1] + 1));
  }
  for (const run of runs) {
    const { left, right } = offsets(run, h, false);
    out.push({ points: [...left, ...right.reverse()] });
  }
  return out;
}

// -- winding and output ---------------------------------------------------------------------------

const toFont = ([x, y]: Pt): Pt => [x * UNIT, (16 - y) * UNIT];
const fmt = (v: number) => {
  const r = Math.round(v * 10) / 10;
  return Object.is(r, -0) ? '0' : String(r);
};

/** Signed area (y up): negative is clockwise, the TrueType winding for a filled contour. */
function area(points: Pt[]): number {
  let a = 0;
  for (let i = 0; i < points.length; i++) {
    const [x1, y1] = points[i];
    const [x2, y2] = points[(i + 1) % points.length];
    a += x1 * y2 - x2 * y1;
  }
  return a / 2;
}

/** In font space, wound clockwise (a fill) or anticlockwise (a hole). */
function emit(c: Contour, clockwise: boolean): string {
  let p = c.points.map(toFont);
  const onCurve = c.quadratic ? p.filter((_, i) => i % 2 === 0) : p;
  if (area(onCurve) < 0 !== clockwise) {
    if (c.quadratic) {
      // Reversed so that each control point stays between its own two on-curve points.
      const rev: Pt[] = [];
      for (let i = p.length; i > 0; i -= 2) rev.push(p[i % p.length], p[i - 1]);
      p = rev;
    } else {
      p = [...p].reverse();
    }
  }
  if (!c.quadratic) return `M${p.map(([x, y]) => `${fmt(x)} ${fmt(y)}`).join('L')}Z`;
  let d = `M${fmt(p[0][0])} ${fmt(p[0][1])}`;
  for (let i = 1; i < p.length; i += 2) {
    const end = p[(i + 1) % p.length];
    d += `Q${fmt(p[i][0])} ${fmt(p[i][1])} ${fmt(end[0])} ${fmt(end[1])}`;
  }
  return `${d}Z`;
}

// -- one glyph ------------------------------------------------------------------------------------

function glyph(body: string, name: string): string {
  const out: string[] = [];
  for (const m of body.matchAll(/<(path|circle|rect)\b([^>]*?)\/?>/g)) {
    const a = attrs(m[2]);
    const paint = paintOf(a);
    const subpaths = flatten(elementPath(m[1], a));
    if (paint !== 'stroke') {
      for (const sp of subpaths) {
        if (sp.points.length >= 3) out.push(emit({ points: sp.points }, paint !== 'knockout'));
      }
    }
    if (paint === 'stroke' || paint === 'both') {
      const width = n(a['data-stroke'], STROKE);
      for (const sp of subpaths) {
        const pieces = outline(sp, width);
        const ring = sp.closed && pieces.length === 2 && !pieces.some((c) => c.quadratic);
        if (ring) {
          // The larger loop is filled; the smaller is its hole.
          const sizes = pieces.map((c) => Math.abs(area(c.points)));
          const [outer, inner] = sizes[0] >= sizes[1] ? pieces : [pieces[1], pieces[0]];
          out.push(emit(outer, true), emit(inner, false));
        } else {
          for (const c of pieces) out.push(emit(c, true));
        }
      }
    }
  }
  if (out.length === 0) throw new Error(`icon ${name} drew nothing`);
  return out.join('');
}

// -- the font -------------------------------------------------------------------------------------

const tile = symbols(readFileSync(TILE, 'utf8'));
const additions = symbols(readFileSync(ADDITIONS, 'utf8'));
for (const name of additions.keys()) {
  if (tile.has(name)) throw new Error(`i-${name} is in the tile already; drop it from the additions`);
}
const all = new Map([...tile, ...additions]);
const names = [...all.keys()].sort();

const glyphs: string[] = [];
const map: string[] = [];
names.forEach((name, i) => {
  const code = FIRST_CODEPOINT + i;
  glyphs.push(
    `<glyph glyph-name="${name}" unicode="&#x${code.toString(16)};" horiz-adv-x="${EM}" d="${glyph(all.get(name)!, name)}"/>`,
  );
  map.push(`  '${name}': '\\u${code.toString(16).toUpperCase()}',`);
});

const svgFont = `<?xml version="1.0" standalone="no"?>
<svg xmlns="http://www.w3.org/2000/svg"><defs>
<font id="QVaultIcons" horiz-adv-x="${EM}">
<font-face font-family="QVaultIcons" units-per-em="${EM}" ascent="${EM}" descent="0"/>
<missing-glyph horiz-adv-x="${EM}"/>
${glyphs.join('\n')}
</font></defs></svg>`;

const ttf = svg2ttf(svgFont, {
  ts: 0, // a fixed timestamp, so the same sprite always gives the same bytes
  version: 'Version 1.0',
  description: 'Q-Vault icons, outlined from the style tile sprite',
  url: '',
});
writeFileSync(fontOut, Buffer.from(ttf.buffer));

writeFileSync(
  glyphsOut,
  `// GENERATED by mobile/tools/icons_from_tile.ts from the style tile's sprite and
// mobile/tools/icons/phone-additions.svg. Do not edit by hand; run \`node tools/icons_from_tile.ts\`.
// tests/test_mobile_icons.py fails when this file or assets/fonts/QVaultIcons.ttf is out of date.

export const ICON_GLYPHS = {
${map.join('\n')}
} as const;

export type IconName = keyof typeof ICON_GLYPHS;
`,
);
