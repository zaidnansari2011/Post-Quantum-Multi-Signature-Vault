// Decision types (rework plan S13): each type's fields write the decision's text.
//
// The twin of qvault/services/decision_types.py. A Production access or Contract decision's text
// is generated from its fields, the way a payment's is from its signed action (`paymentText`).
// The type and fields travel unsigned beside the signed text, so the phone writes the text again
// from them and trusts the fields only when the result is the signed text, byte for byte. Both
// twins are run over tests/vectors/decision_types.json (tests/test_mobile_decision_types.py, via
// tools/decision_types_probe.ts) and must give the same text, or the same refusal, for every case.
//
// The rules, kept to code-point and ASCII comparisons so no Unicode table, locale or Date parser
// can make the twins disagree:
//   - a free-text field is one line: no line break; no control, invisible, bidirectional,
//     private-use or noncharacter code point (the fixed list below, not a Unicode category); only
//     the ordinary space, never at either end and never two together. Letters of any script pass;
//   - no free-text field holds a double quotation mark, or anything drawn like one (two single
//     quotation marks together among them), because the first line puts each free-text value
//     between “ and ”: a value can never close its own quotes and say what its fields do not;
//   - no free-text field holds one of its type's own labels followed by ": " (Reason: ), so a
//     value never reads as a line of the text;
//   - lengths count code points, not UTF-16 units;
//   - dates are YYYY-MM-DD and times YYYY-MM-DD HH:MM in UTC, real calendar dates from 2000;
//   - an amount is a plain decimal (48200.50), shown grouped (48,200.50), with a currency code;
//   - an optional field that is absent, null or "" is not given, and its line is left out;
//   - a field this version does not know is refused, so nothing unsigned rides along.
//
// No React Native import: plain .ts with explicit extensions, so Node runs it in the probe.
//
// For the phone stream (src/checks.ts `verifyDecisionType`): call `verifyTypedDecision(detail)`
// after `verifyProposalIntegrity` has passed, and refuse with reason `type_text` when it returns
// `{ ok: false }`. When it returns `{ ok: true, rows }`, draw the typed-fields card from `rows`
// (they are the signed text's own lines); `rows: null` means no card (General, Payment, or a type
// or template version this app does not know), with the signed text alone, signing allowed.

import { paymentText, type PaymentAction } from '../crypto/signing.ts';

/** The version of the templates below; the server's `TEMPLATE_VERSION`. */
export const TEMPLATE_VERSION = 1;

export type DecisionType = 'general' | 'payment' | 'access' | 'contract';

export const TYPE_LABELS: Record<DecisionType, string> = {
  general: 'General',
  payment: 'Payment',
  access: 'Production access',
  contract: 'Contract',
};

/** Production access levels: the label on its line, and the words in the sentence. */
export const ACCESS_LEVELS: Record<string, [label: string, phrase: string]> = {
  read: ['Read-only', 'read-only'],
  write: ['Read and write', 'read and write'],
  admin: ['Administrator', 'administrator'],
};

type Kind = 'text' | 'choice' | 'datetime' | 'date' | 'amount' | 'currency';
type Spec = { key: string; label: string; kind: Kind; required: boolean; maxLen?: number };

const SPECS: Record<'access' | 'contract', Spec[]> = {
  access: [
    { key: 'person', label: 'Person', kind: 'text', required: true, maxLen: 80 },
    { key: 'system', label: 'System', kind: 'text', required: true, maxLen: 80 },
    { key: 'level', label: 'Access', kind: 'choice', required: true },
    { key: 'until', label: 'Until', kind: 'datetime', required: true },
    { key: 'reason', label: 'Reason', kind: 'text', required: true, maxLen: 280 },
    { key: 'reference', label: 'Reference', kind: 'text', required: false, maxLen: 80 },
  ],
  contract: [
    { key: 'counterparty', label: 'Counterparty', kind: 'text', required: true, maxLen: 120 },
    { key: 'subject', label: 'Subject', kind: 'text', required: true, maxLen: 280 },
    { key: 'amount', label: 'Value', kind: 'amount', required: false },
    { key: 'currency', label: 'Currency', kind: 'currency', required: false },
    { key: 'starts', label: 'Starts', kind: 'date', required: false },
    { key: 'ends', label: 'Ends', kind: 'date', required: false },
    { key: 'reference', label: 'Reference', kind: 'text', required: false, maxLen: 80 },
  ],
};

// -- the character rules (the server's LINE_BREAKS, HIDDEN_RANGES, OTHER_SPACES) ----------------

const LINE_BREAKS = new Set([0x0a, 0x0b, 0x0c, 0x0d, 0x85, 0x2028, 0x2029]);

const HIDDEN_RANGES: Array<[number, number]> = [
  [0x0000, 0x001f], // C0 controls, the tab among them
  [0x007f, 0x009f], // DEL and C1 controls
  [0x00ad, 0x00ad], // soft hyphen
  [0x034f, 0x034f], // combining grapheme joiner
  [0x061c, 0x061c], // Arabic letter mark
  [0x115f, 0x1160], // Hangul fillers
  [0x17b4, 0x17b5], // Khmer inherent vowels
  [0x180b, 0x180f], // Mongolian variation selectors and vowel separator
  [0x200b, 0x200f], // zero-width space, joiners, LRM, RLM
  [0x202a, 0x202e], // bidirectional embeddings and overrides
  [0x2060, 0x206f], // word joiner, invisible operators, bidirectional isolates
  [0x3164, 0x3164], // Hangul filler
  [0xd800, 0xdfff], // surrogates, which never stand alone in text
  [0xe000, 0xf8ff], // private use
  [0xfdd0, 0xfdef], // noncharacters
  [0xfe00, 0xfe0f], // variation selectors
  [0xfeff, 0xfeff], // byte order mark, zero-width no-break space
  [0xffa0, 0xffa0], // halfwidth Hangul filler
  [0xfff0, 0xffff], // specials: annotation marks, the replacement character, noncharacters
  [0x1bca0, 0x1bca3], // shorthand format controls
  [0x1d173, 0x1d17a], // musical format controls
  [0xe0000, 0xe0fff], // tags and variation selectors supplement
  [0xf0000, 0x10ffff], // supplementary private use
];

/** Double quotation marks and what draws like one (the server's DOUBLE_QUOTES). */
const DOUBLE_QUOTES = new Set([
  0x0022, 0x00ab, 0x00bb, 0x02ba, 0x02dd, 0x02ee, 0x05f4, 0x201c, 0x201d, 0x201e, 0x201f, 0x2033,
  0x2036, 0x275d, 0x275e, 0x2e42, 0x3003, 0x301d, 0x301e, 0x301f, 0xff02, 0x1f676, 0x1f677, 0x1f678,
]);

/** Single quotation marks and apostrophes: one is allowed (O’Brien), two together are not. */
const SINGLE_QUOTES = new Set([
  0x0027, 0x0060, 0x00b4, 0x02b9, 0x02bb, 0x02bc, 0x02bd, 0x2018, 0x2019, 0x201a, 0x201b, 0x2032,
  0x2035, 0x2039, 0x203a, 0xff07,
]);

/** Spaces other than U+0020: they look like one and are not. The Braille blank draws as one. */
const OTHER_SPACES = new Set([
  0x00a0, 0x1680, 0x202f, 0x205f, 0x2800, 0x3000,
  0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2007, 0x2008, 0x2009, 0x200a,
]);

function hidden(cp: number): boolean {
  // The last two code points of every plane are noncharacters.
  if ((cp & 0xfffe) === 0xfffe) return true;
  return HIDDEN_RANGES.some(([low, high]) => low <= cp && cp <= high);
}

const DATE = /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/;
const DATETIME = /^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}$/;
const AMOUNT = /^(0|[1-9][0-9]{0,14})(\.[0-9]{1,6})?$/;
const CURRENCY = /^[A-Z]{3}$/;
const NONZERO = /[1-9]/;

/** Why a set of fields writes no text: the field (null for the set as a whole) and a code. */
export type Problem = { field: string | null; code: string };

type Fields = Record<string, unknown>;

function own(fields: Fields, key: string): unknown {
  return Object.prototype.hasOwnProperty.call(fields, key) ? fields[key] : undefined;
}

function given(fields: Fields, key: string): boolean {
  const value = own(fields, key);
  return value !== undefined && value !== null && value !== '';
}

function realDate(text: string): boolean {
  const year = Number(text.slice(0, 4));
  const month = Number(text.slice(5, 7));
  const day = Number(text.slice(8, 10));
  if (year < 2000 || month < 1 || month > 12) return false;
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1];
  return day >= 1 && day <= days;
}

function textProblem(value: string, maxLen: number, labels: string[]): string | null {
  let length = 0;
  let afterSingle = false;
  // `for...of` walks code points; a lone surrogate comes through on its own and is hidden.
  for (const ch of value) {
    const cp = ch.codePointAt(0)!;
    if (LINE_BREAKS.has(cp)) return 'line_break';
    if (hidden(cp)) return 'hidden_character';
    if (OTHER_SPACES.has(cp)) return 'spacing';
    if (DOUBLE_QUOTES.has(cp) || (afterSingle && SINGLE_QUOTES.has(cp))) return 'quote_mark';
    afterSingle = SINGLE_QUOTES.has(cp);
    length += 1;
  }
  if (value.startsWith(' ') || value.endsWith(' ') || value.includes('  ')) return 'spacing';
  if (length > maxLen) return 'too_long';
  if (labels.some((label) => value.includes(`${label}: `))) return 'label_in_value';
  return null;
}

function valueProblem(spec: Spec, value: string, labels: string[]): string | null {
  switch (spec.kind) {
    case 'text':
      return textProblem(value, spec.maxLen ?? 0, labels);
    case 'choice':
      return Object.prototype.hasOwnProperty.call(ACCESS_LEVELS, value) ? null : 'choice';
    case 'datetime':
      if (!DATETIME.test(value) || !realDate(value.slice(0, 10))) return 'datetime';
      return Number(value.slice(11, 13)) <= 23 && Number(value.slice(14, 16)) <= 59 ? null : 'datetime';
    case 'date':
      return DATE.test(value) && realDate(value) ? null : 'date';
    case 'amount':
      return AMOUNT.test(value) && NONZERO.test(value) ? null : 'amount';
    case 'currency':
      return CURRENCY.test(value) ? null : 'currency';
  }
}

function isFields(value: unknown): value is Fields {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * The first reason `fields` write no text for `type`, or null when they do. The server's
 * `check_fields`, in the same order: the type and version, the object, unknown keys, each field in
 * its type's order, then the rules between fields.
 */
export function checkFields(type: unknown, fields: unknown, version: unknown = TEMPLATE_VERSION): Problem | null {
  if (type !== 'access' && type !== 'contract') return { field: null, code: 'unknown_type' };
  if (version !== TEMPLATE_VERSION) return { field: null, code: 'unknown_version' };
  if (!isFields(fields)) return { field: null, code: 'not_an_object' };
  const specs = SPECS[type];
  const labels = specs.map((spec) => spec.label);
  if (Object.keys(fields).some((key) => !specs.some((spec) => spec.key === key))) {
    return { field: null, code: 'unknown_field' };
  }
  for (const spec of specs) {
    if (!given(fields, spec.key)) {
      if (spec.required) return { field: spec.key, code: 'missing' };
      continue;
    }
    const value = own(fields, spec.key);
    if (typeof value !== 'string') return { field: spec.key, code: 'not_text' };
    const code = valueProblem(spec, value, labels);
    if (code !== null) return { field: spec.key, code };
  }
  if (type === 'contract') {
    if (given(fields, 'amount') !== given(fields, 'currency')) {
      return { field: given(fields, 'amount') ? 'currency' : 'amount', code: 'value_pair' };
    }
    if (given(fields, 'starts') && given(fields, 'ends') && (fields.ends as string) < (fields.starts as string)) {
      return { field: 'ends', code: 'order' };
    }
  }
  return null;
}

function grouped(amount: string): string {
  const [whole, fraction] = amount.split('.');
  const groups: string[] = [];
  let rest = whole;
  while (rest.length > 3) {
    groups.unshift(rest.slice(-3));
    rest = rest.slice(0, -3);
  }
  groups.unshift(rest);
  return groups.join(',') + (fraction ? '.' + fraction : '');
}

export type FieldRow = { label: string; value: string };

/**
 * The `Label: value` lines under the first line, for fields `checkFields` passed. The typed-fields
 * card draws exactly these, so it can never say something the signed text does not.
 */
export function fieldRows(type: 'access' | 'contract', fields: Fields): FieldRow[] {
  const rows: FieldRow[] = [];
  for (const spec of SPECS[type]) {
    if (!given(fields, spec.key)) continue;
    let value = own(fields, spec.key) as string;
    if (spec.kind === 'choice') value = ACCESS_LEVELS[value][0];
    else if (spec.kind === 'datetime') value = `${value} UTC`;
    else if (spec.kind === 'amount') value = `${fields.currency as string} ${grouped(value)}`;
    else if (spec.kind === 'currency') continue; // written with the amount, on the Value line
    rows.push({ label: spec.label, value });
  }
  return rows;
}

/** The sentence the prompt quotes: each free-text value between “ and ”, which no value holds. */
function firstLine(type: 'access' | 'contract', fields: Fields): string {
  if (type === 'access') {
    const phrase = ACCESS_LEVELS[fields.level as string][1];
    return `Grant “${fields.person as string}” ${phrase} access to “${fields.system as string}” until ${fields.until as string} UTC.`;
  }
  const value = given(fields, 'amount')
    ? ` for ${fields.currency as string} ${grouped(fields.amount as string)}`
    : '';
  return `Sign the contract with “${fields.counterparty as string}”${value}.`;
}

/**
 * The only text a typed decision may carry, or null when its fields write none. A payment's fields
 * are its signed action (`paymentText`); a General decision has none, so there is nothing to write.
 */
export function decisionText(type: unknown, fields: unknown, version: unknown = TEMPLATE_VERSION): string | null {
  if (type === 'payment') return isFields(fields) ? paymentText(fields as unknown as PaymentAction) : null;
  if (checkFields(type, fields, version) !== null) return null;
  const t = type as 'access' | 'contract';
  const f = fields as Fields;
  return [firstLine(t, f), ...fieldRows(t, f).map((row) => `${row.label}: ${row.value}`)].join('\n');
}

/** The parts of a decision's detail this check reads (`ProposalDetail` has them all). */
export type TypedDetail = {
  decision_type?: unknown;
  fields?: unknown;
  template_version?: unknown;
  signing_inputs: { action_text: string; action?: unknown };
};

export type TypedCheck =
  | { ok: true; type: DecisionType | null; rows: FieldRow[] | null }
  | { ok: false };

/**
 * Whether a decision's unsigned type and fields agree with what it signs. Call it only after the
 * payload hash has been derived and matched, so `signing_inputs` is what the hash covers.
 *
 *   - Production access or Contract at a known template version: the fields must write exactly
 *     `signing_inputs.action_text`; then `rows` is the card. Otherwise it fails (`type_text`).
 *   - Payment: the signed payload must carry a payment, and a decision that carries one must say
 *     Payment, so the type can never hide one. Its text is checked by `paymentText` in flows.ts.
 *   - General: no fields to check, no card.
 *   - No type (an older server), or a type or template version this app does not know: no card,
 *     and the signed text alone decides (phone-ux, S13 row): nothing unsigned is shown.
 */
export function verifyTypedDecision(detail: TypedDetail): TypedCheck {
  const type = detail.decision_type;
  const signedPayment = detail.signing_inputs.action !== undefined && detail.signing_inputs.action !== null;
  if (type === undefined || type === null) return { ok: true, type: null, rows: null };
  if (type === 'payment' || signedPayment) {
    return type === 'payment' && signedPayment ? { ok: true, type: 'payment', rows: null } : { ok: false };
  }
  if (type === 'general') return { ok: true, type: 'general', rows: null };
  if ((type !== 'access' && type !== 'contract') || detail.template_version !== TEMPLATE_VERSION) {
    return { ok: true, type: null, rows: null };
  }
  const text = decisionText(type, detail.fields, detail.template_version);
  if (text === null || text !== detail.signing_inputs.action_text) return { ok: false };
  return { ok: true, type, rows: fieldRows(type, detail.fields as Fields) };
}
