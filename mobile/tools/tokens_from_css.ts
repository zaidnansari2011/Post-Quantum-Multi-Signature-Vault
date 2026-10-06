// Writes src/theme/tokens.generated.ts from the web's tokens.css (phone-ux §3.2).
//
// The phone shares every colour and every motion value with the web, and nothing else: type sizes,
// spacing, radius and density are the phone's own (src/theme/scale.ts). So this reads only the
// colour and motion custom properties, from the light `:root` block and the dark
// `:root[data-theme="dark"]` block, resolves each `var()` chain within its scheme, and writes hex.
// A value with alpha (`rgb(14 23 41 / 0.40)`) becomes `#RRGGBBAA`, which React Native accepts.
//
// tests/test_mobile_tokens.py regenerates into a temporary file and fails if the committed file
// differs, so a colour changed on the web cannot silently skip the phone.
//
//   node tools/tokens_from_css.ts [tokens.css] [out.ts] [--json out.json]

import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const mobile = resolve(here, '..');
const repo = resolve(mobile, '..');

const args = process.argv.slice(2);
const jsonAt = args.indexOf('--json');
const jsonOut = jsonAt >= 0 ? args[jsonAt + 1] : null;
const positional = args.filter((_, i) => i !== jsonAt && i !== jsonAt + 1);
// The web's file, once R1 landed it (§3.2): the style tile's copy is a frozen record of the
// approved direction, and the web's is the one that moves.
const source = positional[0] ?? resolve(repo, 'qvault', 'static', 'tokens.css');
const out = positional[1] ?? resolve(mobile, 'src', 'theme', 'tokens.generated.ts');

type Decls = Map<string, string>;

/** The declarations inside the first block whose selector is exactly `selector`. */
function block(css: string, selector: string): Decls {
  const at = css.indexOf(`${selector} {`);
  if (at < 0) throw new Error(`tokens.css has no "${selector} {" block`);
  let depth = 0;
  let start = -1;
  let end = -1;
  for (let i = at; i < css.length; i++) {
    if (css[i] === '{') {
      if (depth === 0) start = i + 1;
      depth++;
    } else if (css[i] === '}') {
      depth--;
      if (depth === 0) {
        end = i;
        break;
      }
    }
  }
  const body = css.slice(start, end);
  const decls: Decls = new Map();
  for (const m of body.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/g)) {
    decls.set(m[1], m[2].replace(/\s+/g, ' ').trim());
  }
  return decls;
}

function resolveVar(name: string, decls: Decls, seen: string[] = []): string {
  if (seen.includes(name)) throw new Error(`var() cycle: ${[...seen, name].join(' -> ')}`);
  const raw = decls.get(name);
  if (raw === undefined) throw new Error(`tokens.css does not define ${name}`);
  const ref = /^var\((--[a-z0-9-]+)\)$/.exec(raw);
  return ref ? resolveVar(ref[1], decls, [...seen, name]) : raw;
}

const hex2 = (n: number) => Math.round(n).toString(16).padStart(2, '0').toUpperCase();

function toHex(value: string, name: string): string {
  const hex = /^#([0-9a-fA-F]{6})$/.exec(value);
  if (hex) return `#${hex[1].toUpperCase()}`;
  const rgb = /^rgb\(\s*(\d+)\s+(\d+)\s+(\d+)\s*(?:\/\s*([\d.]+)\s*)?\)$/.exec(value);
  if (rgb) {
    const [r, g, b] = [rgb[1], rgb[2], rgb[3]].map(Number);
    const alpha = rgb[4] === undefined ? '' : hex2(Number(rgb[4]) * 255);
    return `#${hex2(r)}${hex2(g)}${hex2(b)}${alpha}`;
  }
  throw new Error(`${name}: "${value}" is not a colour this generator understands`);
}

const css = readFileSync(source, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
const lightDecls = block(css, ':root');
// The dark block overrides the light one; anything it leaves alone (type, motion, a few colours)
// keeps its light value, exactly as the cascade does in a browser.
const darkDecls: Decls = new Map([...lightDecls, ...block(css, ':root[data-theme="dark"]')]);

// The phone's names for the web's tokens (phone-ux §3.3). Nested keys become nested objects.
const MAP: Array<[string, string]> = [
  ['bg', '--bg'],
  ['bgSubtle', '--bg-subtle'],
  ['surface', '--surface'],
  ['surfaceRaised', '--surface-raised'],
  ['fill', '--fill'],
  ['fillHover', '--fill-hover'],
  ['fillActive', '--fill-active'],
  ['fillRaisedPressed', '--fill-raised-hover'],
  ['border', '--border'],
  ['borderStrong', '--border-strong'],
  ['text', '--text'],
  ['textMuted', '--text-muted'],
  ['textSubtle', '--text-subtle'],
  ['textDisabled', '--text-disabled'],
  ['fillDisabled', '--fill-disabled'],
  ['borderDisabled', '--border-disabled'],
  ['accent', '--accent'],
  ['accentPressed', '--accent-hover'],
  ['accentText', '--accent-text'],
  ['accentSubtle', '--accent-subtle'],
  ['accentBorder', '--accent-border'],
  ['accentFg', '--accent-fg'],
  ['link', '--link'],
  ['focus', '--focus'],
  ['selection', '--selection'],
  ['danger', '--danger'],
  ['dangerPressed', '--danger-hover'],
  ['dangerText', '--danger-text'],
  ['markFilled', '--mark-filled'],
  ['markEmpty', '--mark-empty'],
  ['backdrop', '--backdrop'],
  ['chrome.bg', '--chrome-bg'],
  ['chrome.bgRaised', '--chrome-bg-raised'],
  ['chrome.border', '--chrome-border'],
  ['chrome.text', '--chrome-text'],
  ['chrome.textMuted', '--chrome-text-muted'],
];
for (const tone of ['success', 'warning', 'critical', 'info', 'neutral']) {
  for (const part of ['fg', 'bg', 'border']) {
    MAP.push([`status.${tone}.${part}`, `--status-${tone}-${part}`]);
  }
}

type Tree = { [key: string]: string | Tree };

function put(tree: Tree, path: string, value: string) {
  const keys = path.split('.');
  let node = tree;
  for (const k of keys.slice(0, -1)) node = (node[k] ??= {}) as Tree;
  node[keys[keys.length - 1]] = value;
}

function palette(decls: Decls): Tree {
  const tree: Tree = {};
  for (const [key, cssName] of MAP) put(tree, key, toHex(resolveVar(cssName, decls), cssName));
  // The shadow colour: the scrim's own hue without its alpha, so a shadow sits in the same
  // temperature as the ink (tokens.css tints its shadows with the chrome navy, never black).
  put(tree, 'shadow', toHex(resolveVar('--backdrop', decls), '--backdrop').slice(0, 7));
  // Phone-only tokens (§3.4). The tab badge and the Activity dot sit on the navy tab bar in both
  // themes, so both themes take the dark theme's values: the warning foreground for the badge, the
  // deep ink for its text, and accent-11 for the unread dot.
  put(tree, 'chrome.badgeBg', toHex(resolveVar('--status-warning-fg', darkDecls), 'badge'));
  put(tree, 'chrome.badgeText', toHex(resolveVar('--neutral-1', darkDecls), 'badge text'));
  put(tree, 'chrome.dot', toHex(resolveVar('--accent-11', darkDecls), 'dot'));
  return tree;
}

const ms = (name: string) => {
  const m = /^(\d+)ms$/.exec(resolveVar(name, lightDecls));
  if (!m) throw new Error(`${name} is not a duration in ms`);
  return Number(m[1]);
};
const bezier = (name: string) => {
  const m = /^cubic-bezier\(([^)]+)\)$/.exec(resolveVar(name, lightDecls));
  if (!m) throw new Error(`${name} is not a cubic-bezier()`);
  return m[1].split(',').map((n) => Number(n.trim()));
};

const light = palette(lightDecls);
const dark = palette(darkDecls);
const motion = {
  press: ms('--duration-press'),
  popover: ms('--duration-popover'),
  dialog: ms('--duration-dialog'),
  dialogExit: ms('--duration-dialog-exit'),
  seal: ms('--duration-seal'),
  easeEnter: bezier('--ease-enter'),
  easeExit: bezier('--ease-exit'),
  easeStandard: bezier('--ease-standard'),
  easeSeal: bezier('--ease-seal'),
};

function shape(tree: Tree, indent: string): string {
  return Object.entries(tree)
    .map(([k, v]) =>
      typeof v === 'string'
        ? `${indent}${k}: string;`
        : `${indent}${k}: {\n${shape(v, indent + '  ')}\n${indent}};`,
    )
    .join('\n');
}

function literal(value: unknown, indent: string): string {
  if (typeof value === 'string') return `'${value}'`;
  if (typeof value === 'number') return String(value);
  if (Array.isArray(value)) return `[${value.map((v) => literal(v, indent)).join(', ')}]`;
  const inner = Object.entries(value as Record<string, unknown>)
    .map(([k, v]) => `${indent}  ${k}: ${literal(v, indent + '  ')},`)
    .join('\n');
  return `{\n${inner}\n${indent}}`;
}

const sourceName = relative(repo, source).split('\\').join('/');
const ts = `// GENERATED by mobile/tools/tokens_from_css.ts from ${sourceName}. Do not edit by hand:
// change tokens.css and run \`node tools/tokens_from_css.ts\` in mobile/.
// tests/test_mobile_tokens.py fails when this file is out of date.

export type ColorTokens = {
${shape(light, '  ')}
};

export const light: ColorTokens = ${literal(light, '')};

export const dark: ColorTokens = ${literal(dark, '')};

/** Durations in ms and easings as cubic-bezier control points, shared with the web. */
export const motionTokens = ${literal(motion, '')} as const;
`;

writeFileSync(out, ts);
if (jsonOut) writeFileSync(jsonOut, JSON.stringify({ light, dark, motion }, null, 2));
