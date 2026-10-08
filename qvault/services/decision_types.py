"""Decision types (rework plan S13): each type's fields write the decision's text.

General, Payment, Production access and Contract. A General decision's text is the words its
requester writes. Every other type's text is generated from its fields, deterministically, the way
a payment's already is (plan D24, :func:`qvault.services.signing.payment_text`), so approvers read
words nobody typed by hand and a phone can write them again from the fields and refuse to sign
when they differ (``mobile/src/logic/decisionTypes.ts``, the twin of this module).

Nothing about the signed format changes (S9). What is signed is still ``action_text``; the type
and fields of a Production access or Contract decision are stored beside it, unsigned
(``DecisionFields``), and are shown only when they write exactly the signed text again
(:func:`typed_view`). A payment's fields are its signed ``action``, so it stores none.

Both twins follow the same rules, kept to plain code-point and ASCII comparisons so that no
Unicode table, locale or date library can make them disagree:

* every free-text field is one line: no line break, no control, invisible, bidirectional,
  private-use or noncharacter code point (a fixed list below, not a Unicode category, so a newer
  Unicode database on either side changes nothing), only the ordinary space, never at either end
  and never two together. Letters of any script are allowed;
* no free-text field holds a double quotation mark, or anything drawn like one (two single
  quotation marks together among them), because the first line puts each free-text value between
  “ and ”: a value can never close its own quotes and go on to say something its fields do not;
* no free-text field holds one of its type's own labels followed by ``": "`` (``Reason: ``), so
  a value never reads as a line of the text;
* lengths are counted in code points;
* dates are ``YYYY-MM-DD`` and times ``YYYY-MM-DD HH:MM`` in UTC, real calendar dates from 2000;
* an amount is a plain decimal (``48200.50``), shown grouped (``48,200.50``), with a three-letter
  currency code;
* an optional field that is absent, ``null`` or ``""`` is not given, and its line is left out;
* a field this version does not know is refused, so nothing unsigned rides along.

The text is a first line that reads as a sentence (what a phone's prompt quotes) and then one
``Label: value`` line per field. Values cannot contain a line break, so the labelled lines can be
read back into exactly one set of fields: no two sets of fields write the same text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from qvault.services.signing import payment_text

#: The version of the templates below. A decision records the version that wrote its text; a
#: change to any template is a new version, and the old one stays readable.
TEMPLATE_VERSION = 1

TYPES = ("general", "payment", "access", "contract")
#: The types whose fields are stored beside the decision (a payment's are its signed action).
STORED_TYPES = ("access", "contract")
LABELS = {
    "general": "General",
    "payment": "Payment",
    "access": "Production access",
    "contract": "Contract",
}

#: Production access levels: the stored value, the label on its line, the words in the sentence.
ACCESS_LEVELS = {
    "read": ("Read-only", "read-only"),
    "write": ("Read and write", "read and write"),
    "admin": ("Administrator", "administrator"),
}


@dataclass(frozen=True)
class Spec:
    """One field: its key, the label on its line, and what it accepts."""

    key: str
    label: str
    kind: str  # "text" | "choice" | "datetime" | "date" | "amount" | "currency"
    required: bool
    max_len: int = 0


SPECS: dict[str, tuple[Spec, ...]] = {
    "access": (
        Spec("person", "Person", "text", True, 80),
        Spec("system", "System", "text", True, 80),
        Spec("level", "Access", "choice", True),
        Spec("until", "Until", "datetime", True),
        Spec("reason", "Reason", "text", True, 280),
        Spec("reference", "Reference", "text", False, 80),
    ),
    "contract": (
        Spec("counterparty", "Counterparty", "text", True, 120),
        Spec("subject", "Subject", "text", True, 280),
        Spec("amount", "Value", "amount", False),
        Spec("currency", "Currency", "currency", False),
        Spec("starts", "Starts", "date", False),
        Spec("ends", "Ends", "date", False),
        Spec("reference", "Reference", "text", False, 80),
    ),
}

# --- the character rules -------------------------------------------------------------------------

#: Code points that end a line.
LINE_BREAKS = frozenset({0x0A, 0x0B, 0x0C, 0x0D, 0x85, 0x2028, 0x2029})

#: Code points that draw nothing, or draw something other than themselves: controls, zero-width
#: and joining characters, bidirectional controls, fillers, variation selectors, tags, the BOM,
#: specials, surrogates, private use and noncharacters. Inclusive ranges, in code-point order.
HIDDEN_RANGES = (
    (0x0000, 0x001F),  # C0 controls, the tab among them
    (0x007F, 0x009F),  # DEL and C1 controls
    (0x00AD, 0x00AD),  # soft hyphen
    (0x034F, 0x034F),  # combining grapheme joiner
    (0x061C, 0x061C),  # Arabic letter mark
    (0x115F, 0x1160),  # Hangul fillers
    (0x17B4, 0x17B5),  # Khmer inherent vowels
    (0x180B, 0x180F),  # Mongolian variation selectors and vowel separator
    (0x200B, 0x200F),  # zero-width space, joiners, LRM, RLM
    (0x202A, 0x202E),  # bidirectional embeddings and overrides
    (0x2060, 0x206F),  # word joiner, invisible operators, bidirectional isolates
    (0x3164, 0x3164),  # Hangul filler
    (0xD800, 0xDFFF),  # surrogates, which never stand alone in text
    (0xE000, 0xF8FF),  # private use
    (0xFDD0, 0xFDEF),  # noncharacters
    (0xFE00, 0xFE0F),  # variation selectors
    (0xFEFF, 0xFEFF),  # byte order mark, zero-width no-break space
    (0xFFA0, 0xFFA0),  # halfwidth Hangul filler
    (0xFFF0, 0xFFFF),  # specials: annotation marks, the replacement character, noncharacters
    (0x1BCA0, 0x1BCA3),  # shorthand format controls
    (0x1D173, 0x1D17A),  # musical format controls
    (0xE0000, 0xE0FFF),  # tags and variation selectors supplement
    (0xF0000, 0x10FFFF),  # supplementary private use
)

#: Double quotation marks, and what draws like one: a free-text value never holds one, so the
#: quotes the first line puts around it are always the template's own.
DOUBLE_QUOTES = frozenset(
    {
        0x0022,  # quotation mark
        0x00AB,  # left-pointing double angle quotation mark
        0x00BB,  # right-pointing double angle quotation mark
        0x02BA,  # modifier letter double prime
        0x02DD,  # double acute accent
        0x02EE,  # modifier letter double apostrophe
        0x05F4,  # Hebrew punctuation gershayim
        0x201C,  # left double quotation mark
        0x201D,  # right double quotation mark
        0x201E,  # double low-9 quotation mark
        0x201F,  # double high-reversed-9 quotation mark
        0x2033,  # double prime
        0x2036,  # reversed double prime
        0x275D,  # heavy double turned comma quotation mark ornament
        0x275E,  # heavy double comma quotation mark ornament
        0x2E42,  # double low-reversed-9 quotation mark
        0x3003,  # ditto mark
        0x301D,  # reversed double prime quotation mark
        0x301E,  # double prime quotation mark
        0x301F,  # low double prime quotation mark
        0xFF02,  # fullwidth quotation mark
        0x1F676,  # sans-serif heavy double turned comma quotation mark ornament
        0x1F677,  # sans-serif heavy double comma quotation mark ornament
        0x1F678,  # sans-serif heavy low double comma quotation mark ornament
    }
)

#: Single quotation marks and apostrophes. One is allowed (O’Brien); two together draw as a
#: double quotation mark, so they are refused.
SINGLE_QUOTES = frozenset(
    {
        0x0027,  # apostrophe
        0x0060,  # grave accent
        0x00B4,  # acute accent
        0x02B9,  # modifier letter prime
        0x02BB,  # modifier letter turned comma
        0x02BC,  # modifier letter apostrophe
        0x02BD,  # modifier letter reversed comma
        0x2018,  # left single quotation mark
        0x2019,  # right single quotation mark
        0x201A,  # single low-9 quotation mark
        0x201B,  # single high-reversed-9 quotation mark
        0x2032,  # prime
        0x2035,  # reversed prime
        0x2039,  # single left-pointing angle quotation mark
        0x203A,  # single right-pointing angle quotation mark
        0xFF07,  # fullwidth apostrophe
    }
)

#: Spaces other than U+0020: they look like one and are not.
#: The Braille blank is not a space, but draws as one.
OTHER_SPACES = frozenset({0x00A0, 0x1680, 0x202F, 0x205F, 0x2800, 0x3000, *range(0x2000, 0x200B)})


def _hidden(cp: int) -> bool:
    if cp & 0xFFFE == 0xFFFE:  # the last two code points of every plane are noncharacters
        return True
    return any(low <= cp <= high for low, high in HIDDEN_RANGES)


_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", re.ASCII)
_DATETIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}", re.ASCII)
_AMOUNT = re.compile(r"(0|[1-9][0-9]{0,14})(\.[0-9]{1,6})?", re.ASCII)
_CURRENCY = re.compile(r"[A-Z]{3}", re.ASCII)
_NONZERO = re.compile(r"[1-9]", re.ASCII)


@dataclass(frozen=True)
class Problem:
    """Why a set of fields writes no text: the field (None for the set as a whole) and a code.

    The codes are the twin's too, and the vectors pin them (``tests/vectors/decision_types.json``).
    """

    field: str | None
    code: str


def _real_date(text: str) -> bool:
    year, month, day = int(text[0:4]), int(text[5:7]), int(text[8:10])
    if year < 2000 or not 1 <= month <= 12:
        return False
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    days = (31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)[month - 1]
    return 1 <= day <= days


def _text_problem(value: str, max_len: int, labels: tuple[str, ...]) -> str | None:
    after_single = False
    for ch in value:
        cp = ord(ch)
        if cp in LINE_BREAKS:
            return "line_break"
        if _hidden(cp):
            return "hidden_character"
        if cp in OTHER_SPACES:
            return "spacing"
        if cp in DOUBLE_QUOTES or (after_single and cp in SINGLE_QUOTES):
            return "quote_mark"
        after_single = cp in SINGLE_QUOTES
    if value.startswith(" ") or value.endswith(" ") or "  " in value:
        return "spacing"
    if len(value) > max_len:
        return "too_long"
    if any(f"{label}: " in value for label in labels):
        return "label_in_value"
    return None


def _value_problem(spec: Spec, value: str, labels: tuple[str, ...]) -> str | None:
    if spec.kind == "text":
        return _text_problem(value, spec.max_len, labels)
    if spec.kind == "choice":
        return None if value in ACCESS_LEVELS else "choice"
    if spec.kind == "datetime":
        if not _DATETIME.fullmatch(value) or not _real_date(value[:10]):
            return "datetime"
        return None if int(value[11:13]) <= 23 and int(value[14:16]) <= 59 else "datetime"
    if spec.kind == "date":
        return None if _DATE.fullmatch(value) and _real_date(value) else "date"
    if spec.kind == "amount":
        # Above zero: at least one digit that isn't 0.
        return None if _AMOUNT.fullmatch(value) and _NONZERO.search(value) else "amount"
    if spec.kind == "currency":
        return None if _CURRENCY.fullmatch(value) else "currency"
    raise AssertionError(spec.kind)


def check_fields(decision_type: object, fields: object, version: object = TEMPLATE_VERSION):
    """The first reason ``fields`` write no text for ``decision_type``, or None when they do.

    Checked in a fixed order, the twin's: the type and version, the object, unknown keys, then
    each field in its type's order, then the rules between fields.
    """
    if not isinstance(decision_type, str) or decision_type not in SPECS:
        return Problem(None, "unknown_type")
    if version != TEMPLATE_VERSION or isinstance(version, bool):
        return Problem(None, "unknown_version")
    if not isinstance(fields, dict):
        return Problem(None, "not_an_object")
    specs = SPECS[decision_type]
    known = {spec.key for spec in specs}
    if any(key not in known for key in fields):
        return Problem(None, "unknown_field")
    labels = tuple(spec.label for spec in specs)
    for spec in specs:
        value = fields.get(spec.key)
        if value is None or value == "":
            if spec.required:
                return Problem(spec.key, "missing")
            continue
        if not isinstance(value, str):
            return Problem(spec.key, "not_text")
        code = _value_problem(spec, value, labels)
        if code is not None:
            return Problem(spec.key, code)
    if decision_type == "contract":
        if _given(fields, "amount") != _given(fields, "currency"):
            return Problem("currency" if _given(fields, "amount") else "amount", "value_pair")
        if (
            _given(fields, "starts")
            and _given(fields, "ends")
            and fields["ends"] < fields["starts"]
        ):
            return Problem("ends", "order")
    return None


def _given(fields: dict, key: str) -> bool:
    return fields.get(key) not in (None, "")


def _grouped(amount: str) -> str:
    whole, _, fraction = amount.partition(".")
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    return ",".join(groups) + (f".{fraction}" if fraction else "")


def field_rows(decision_type: str, fields: dict) -> list[tuple[str, str]]:
    """The ``(label, value)`` lines under the first line, for fields :func:`check_fields` passed.

    The phone's typed-fields card and the web show exactly these, so a card can never say
    something the signed text does not.
    """
    rows = []
    for spec in SPECS[decision_type]:
        if not _given(fields, spec.key):
            continue
        value = fields[spec.key]
        if spec.kind == "choice":
            value = ACCESS_LEVELS[value][0]
        elif spec.kind == "datetime":
            value = f"{value} UTC"
        elif spec.kind == "amount":
            value = f"{fields['currency']} {_grouped(value)}"
        elif spec.kind == "currency":
            continue  # written with the amount, on the Value line
        rows.append((spec.label, value))
    return rows


def _first_line(decision_type: str, fields: dict) -> str:
    """The sentence a phone's prompt quotes. Each free-text value in it stands between “ and
    ”, which no value can hold, so where a value ends is never in doubt."""
    if decision_type == "access":
        phrase = ACCESS_LEVELS[fields["level"]][1]
        return (
            f"Grant “{fields['person']}” {phrase} access to “{fields['system']}” "
            f"until {fields['until']} UTC."
        )
    value = ""
    if _given(fields, "amount"):
        value = f" for {fields['currency']} {_grouped(fields['amount'])}"
    return f"Sign the contract with “{fields['counterparty']}”{value}."


def decision_text(
    decision_type: object, fields: object, version: object = TEMPLATE_VERSION
) -> str | None:
    """The only text a typed decision may carry, or None when its fields write none.

    A payment's fields are its signed action, and its text is :func:`payment_text`'s. A General
    decision has no fields: its text is what its requester wrote, so there is nothing to write.
    """
    if decision_type == "payment":
        return payment_text(fields)
    if check_fields(decision_type, fields, version) is not None:
        return None
    lines = [_first_line(decision_type, fields)]
    lines += [f"{label}: {value}" for label, value in field_rows(decision_type, fields)]
    return "\n".join(lines)


# --- what a person typed, made into fields (the web form and the API; Python only) --------------

MESSAGES = {
    "missing": "{label} is required.",
    "not_text": "{label} must be text.",
    "too_long": "{label} is limited to {max} characters.",
    "line_break": "{label} must be one line.",
    "hidden_character": (
        "{label} contains a character that doesn’t show on screen (a control, zero-width or "
        "direction character). Type it again without it."
    ),
    "spacing": "{label} has extra or unusual spaces. Use single ordinary spaces between words.",
    "quote_mark": (
        "{label} can’t contain double quotation marks, or two single ones together: the "
        "decision’s text puts quotation marks around it."
    ),
    "label_in_value": (
        "{label} can’t contain the name of a field followed by a colon (like “Reason: ”), "
        "because it would read as a line of its own."
    ),
    "choice": "Choose read-only, read and write, or administrator.",
    "datetime": "Type it as 2026-11-04 17:00, in UTC.",
    "date": "Type it as 2027-01-31.",
    "amount": "Type an amount above zero like 48200.50, with at most 6 decimal places.",
    "currency": "Use a three-letter currency code, like GBP, EUR or USD.",
    "value_pair": "Give the value and its currency together, or neither.",
    "order": "It can’t end before it starts.",
    "in_past": "Choose a time in the future.",
    "unknown_type": "Choose a type of decision.",
    "unknown_version": "This kind of decision can’t be raised here.",
    "not_an_object": "Send the fields as an object.",
    "unknown_field": "One of the fields isn’t one this type of decision has.",
}


def message(decision_type: str, problem: Problem) -> str:
    """The refusal in plain words, naming the field as its form labels it."""
    spec = next((s for s in SPECS.get(decision_type, ()) if s.key == problem.field), None)
    label = FORM_LABELS.get(decision_type, {}).get(problem.field, spec.label if spec else "")
    return MESSAGES[problem.code].format(label=label, max=spec.max_len if spec else 0)


#: The form's label for each field, where it reads better than the label on the text's line.
FORM_LABELS = {
    "access": {
        "person": "Who gets access",
        "system": "System",
        "level": "Access",
        "until": "Until",
        "reason": "Reason",
        "reference": "Ticket or reference",
    },
    "contract": {
        "counterparty": "Counterparty",
        "subject": "What it’s for",
        "amount": "Value",
        "currency": "Currency",
        "starts": "Starts",
        "ends": "Ends",
        "reference": "Contract reference",
    },
}

_THOUSANDS = re.compile(r"[0-9]{1,3}(,[0-9]{3})+(\.[0-9]+)?", re.ASCII)
_LOCAL_TIME = re.compile(
    r"([0-9]{4}-[0-9]{2}-[0-9]{2})[T ]([0-9]{2}:[0-9]{2})(:00)?"
    r"(?: ?(Z|UTC|[+-][0-9]{2}:[0-9]{2}))?",
    re.ASCII | re.IGNORECASE,
)


class FieldsError(ValueError):
    """Typed fields that write no text, with the field to mark (None for the whole form)."""

    def __init__(self, field: str | None, text: str):
        super().__init__(text)
        self.field = field


def normalise(decision_type: str, raw: object) -> dict:
    """The canonical fields for what a person typed, or :class:`FieldsError` in plain words.

    Forgiving where the meaning is certain, and nowhere else: surrounding whitespace is dropped,
    an empty optional field is left out, the access level and currency are case-folded, an amount
    may group thousands with commas (``48,200.50``), and a time may be written the way a browser
    sends it or with an offset, which is converted to UTC. Everything else must already be in
    the canonical form, and is then checked by :func:`check_fields`, the rule both twins share.
    Canonical fields come back unchanged.
    """
    if not isinstance(decision_type, str) or decision_type not in SPECS:
        raise FieldsError(None, MESSAGES["unknown_type"])
    if not isinstance(raw, dict):
        raise FieldsError(None, MESSAGES["not_an_object"])
    specs = SPECS[decision_type]
    known = {spec.key for spec in specs}
    if any(key not in known for key in raw):
        raise FieldsError(None, MESSAGES["unknown_field"])
    fields: dict[str, str] = {}
    for spec in specs:
        value = raw.get(spec.key)
        if isinstance(value, str):
            value = value.strip()
            if spec.kind == "choice":
                value = value.lower()
            elif spec.kind == "currency":
                value = value.upper()
            elif spec.kind == "amount" and _THOUSANDS.fullmatch(value):
                value = value.replace(",", "")
            elif spec.kind == "datetime" and value:
                value = _utc_minute(value)
        if value is None or value == "":
            continue
        fields[spec.key] = value
    problem = check_fields(decision_type, fields)
    if problem is not None:
        raise FieldsError(problem.field, message(decision_type, problem))
    return fields


def _utc_minute(value: str) -> str:
    """``2026-11-04T18:00+01:00`` as ``2026-11-04 17:00``; anything unreadable is returned as
    typed, for :func:`check_fields` to refuse in its own words."""
    match = _LOCAL_TIME.fullmatch(value)
    if match is None:
        return value
    day, minute, _seconds, zone = match.groups()
    try:
        moment = datetime.fromisoformat(f"{day}T{minute}")
    except ValueError:
        return value
    if zone and zone.upper() not in ("Z", "UTC"):
        try:
            moment = datetime.fromisoformat(f"{day}T{minute}{zone}").astimezone(UTC)
        except ValueError:
            return value
    return moment.strftime("%Y-%m-%d %H:%M")


def until_in_future(fields: dict, now: datetime) -> bool:
    """Production access ends in the future when it is raised (a raising rule, not a text one)."""
    until = datetime.strptime(fields["until"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
    return until > now


# --- reading a stored decision's type -----------------------------------------------------------


@dataclass(frozen=True)
class TypedView:
    """A decision's type as every screen shows it.

    ``type`` is ``"payment"`` when the signed payload carries a payment, the stored type when its
    stored fields write exactly the signed text again, and ``"general"`` otherwise. ``fields`` and
    ``rows`` are set only in the second case. ``mismatch`` is True when fields are stored but do
    not write the signed text (a row edited behind the decision's back): the screens then show the
    signed text as a General decision and say why, and never the fields.
    """

    type: str
    fields: dict | None = None
    rows: tuple[tuple[str, str], ...] = ()
    version: int | None = None
    mismatch: bool = False

    @property
    def label(self) -> str:
        return LABELS[self.type]


_LOAD = object()


def typed_view(proposal, stored=_LOAD) -> TypedView:
    """``proposal``'s type, trusting its stored fields only as far as they write its text.

    ``stored`` is its ``DecisionFields`` row (or None) when the caller has loaded it already (a
    list loads a page's rows in one query); otherwise the relationship is read.
    """
    if proposal.action is not None:
        return TypedView("payment")
    if stored is _LOAD:
        stored = proposal.typed
    if stored is None:
        return TypedView("general")
    fields = stored.fields()
    if decision_text(stored.decision_type, fields, stored.template_version) != proposal.action_text:
        return TypedView("general", mismatch=True)
    return TypedView(
        stored.decision_type,
        fields=fields,
        rows=tuple(field_rows(stored.decision_type, fields)),
        version=stored.template_version,
    )
