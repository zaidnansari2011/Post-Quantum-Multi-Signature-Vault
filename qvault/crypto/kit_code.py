"""The Recovery Kit's code: 150 random bits as 32 Crockford base32 symbols (R9, design §5.1).

``K`` is an integer ``0 <= K < 2**150``, written as 30 symbols of 5 bits each, most significant
first, from the alphabet ``0123456789ABCDEFGHJKMNPQRSTVWXYZ``. Two more symbols carry a CRC-10
over those 150 bits: generator 0x233 (x^10 + x^9 + x^5 + x^4 + x + 1), most significant bit first,
initial value 0, no reflection, final XOR 0; the 10-bit result is written high 5 bits first. The
160-bit codeword is then a multiple of the generator, so every burst of 10 bits or fewer anywhere
in it is caught: any one wrong character, and any swap of two neighbouring characters. Printed as
8 groups of 4.

On input: upper case, spaces and hyphens removed, ``I`` and ``L`` read as ``1`` and ``O`` as
``0``; anything else, or any length but 32, is refused.

The check is a typo check, not a secret: it is public, and a code that passes it is merely
well-formed. The secret is the 150 bits. Pure Python with no Flask, so the vectors in
``tests/vectors/recovery_kit.json`` are checked here and in the browser (``static/recover.js``)
alike.
"""

from __future__ import annotations

import secrets

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_VALUE = {symbol: index for index, symbol in enumerate(ALPHABET)}
# Read as the symbol people mean (Crockford's decoding rule).
_ALIASES = {"I": "1", "L": "1", "O": "0"}

BITS = 150
DATA_SYMBOLS = BITS // 5  # 30
CHECK_SYMBOLS = 2
SYMBOLS = DATA_SYMBOLS + CHECK_SYMBOLS  # 32
GROUP = 4

#: x^10 + x^9 + x^5 + x^4 + x + 1, without its x^10 term.
CRC_POLY = 0x233
CRC_BITS = 10


class KitCodeError(ValueError):
    """A typed code that is not a well-formed kit code. ``str()`` is the sentence to show."""


def _crc_bits(value: int, bits: int) -> int:
    """The CRC one bit at a time: the definition, most significant bit first, initial 0."""
    crc = 0
    for position in range(bits - 1, -1, -1):
        top = ((crc >> (CRC_BITS - 1)) & 1) ^ ((value >> position) & 1)
        crc = (crc << 1) & ((1 << CRC_BITS) - 1)
        if top:
            crc ^= CRC_POLY
    return crc


def _shift5(register: int) -> int:
    for _ in range(5):
        if register & 0x200:
            register = ((register << 1) & 0x3FF) ^ CRC_POLY
        else:
            register = (register << 1) & 0x3FF
    return register


# The same CRC five bits (one symbol) at a time: _SYMBOL_TABLE[i] is what five shifts make of i in
# the register's top five bits. Equal to _crc_bits by linearity; the vector test checks the two
# against each other.
_SYMBOL_TABLE = tuple(_shift5(i << 5) for i in range(32))


def crc10(value: int, bits: int = BITS) -> int:
    """The CRC-10 of the ``bits``-bit big-endian number ``value`` (see the module docstring)."""
    if bits % 5:
        return _crc_bits(value, bits)
    crc = 0
    for shift in range(bits - 5, -1, -5):
        crc = ((crc << 5) & 0x3FF) ^ _SYMBOL_TABLE[(crc >> 5) ^ ((value >> shift) & 31)]
    return crc


def _symbols(value: int, count: int) -> str:
    return "".join(ALPHABET[(value >> (5 * (count - 1 - i))) & 31] for i in range(count))


def encode(k: int) -> str:
    """The 32 symbols for ``k``: 30 for the value, then 2 for its check."""
    if not 0 <= k < (1 << BITS):
        raise ValueError("a kit code holds exactly 150 bits")
    return _symbols(k, DATA_SYMBOLS) + _symbols(crc10(k), CHECK_SYMBOLS)


def grouped(code: str) -> str:
    """``ABCD-EFGH-...``: the 32 symbols as 8 groups of 4, as the kit prints them."""
    return "-".join(code[i : i + GROUP] for i in range(0, len(code), GROUP))


def groups(code: str) -> list[str]:
    return [code[i : i + GROUP] for i in range(0, len(code), GROUP)]


def new_code() -> tuple[int, str]:
    """A fresh ``K`` from the operating system's CSPRNG and its 32-symbol code."""
    k = secrets.randbits(BITS)
    return k, encode(k)


def normalise(typed: str) -> str:
    """The 32 symbols a person meant, or ``KitCodeError`` saying why it can't be one.

    Only the typo check is applied: a result is well-formed, never "right"."""
    if not isinstance(typed, str):
        raise KitCodeError("Type the code from your Recovery Kit.")
    cleaned = []
    for ch in typed.upper():
        if ch in " -\t\r\n":
            continue
        ch = _ALIASES.get(ch, ch)
        if ch not in _VALUE:
            raise KitCodeError(
                "That code has a character a Recovery Kit never uses. Check it against your kit."
            )
        cleaned.append(ch)
    code = "".join(cleaned)
    if len(code) != SYMBOLS:
        raise KitCodeError(
            f"A Recovery Kit code is {SYMBOLS} characters, in 8 groups of 4. That one has "
            f"{len(code)}."
        )
    value = 0
    for ch in code[:DATA_SYMBOLS]:
        value = (value << 5) | _VALUE[ch]
    check = 0
    for ch in code[DATA_SYMBOLS:]:
        check = (check << 5) | _VALUE[ch]
    if crc10(value) != check:
        raise KitCodeError(
            "That code has a typo: one of its characters is wrong, or two are swapped. Check it "
            "against your kit."
        )
    return code


def decode(typed: str) -> int:
    """``K`` from a typed code (after ``normalise``)."""
    code = normalise(typed)
    value = 0
    for ch in code[:DATA_SYMBOLS]:
        value = (value << 5) | _VALUE[ch]
    return value


def argon2_input(code: str) -> str:
    """What Argon2id is given as its password: the 30 normalised data symbols, as ASCII.

    ``code`` must already be normalised; the two check symbols add nothing secret."""
    if len(code) != SYMBOLS or any(ch not in _VALUE for ch in code):
        raise ValueError("argon2_input takes a normalised 32-symbol code")
    return code[:DATA_SYMBOLS]
