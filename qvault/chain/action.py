"""The payment a decision authorises, in the one shape every implementation hashes.

A payment decision's canonical payload carries an ``action`` object (plan D4). Four
implementations hash it: the server, the offline verifier, the browser verifier and the phone.
Two of those are JavaScript, so the shape is chosen to hash identically everywhere (D22):

* exactly eight keys, all required, nothing else;
* ``value_wei`` as a decimal string, because 10^18 wei is past what a JavaScript number holds
  exactly;
* every other number a *safe* integer (at most 2^53 - 1), which a browser keeps exactly and the
  phone's canonicaliser accepts;
* addresses in their EIP-55 checksummed form only, so one address cannot be written two ways and
  hash two ways;
* ``data`` in lowercase hex, and always ``"0x"`` for an ETH transfer.

:func:`parse` is the only way in from outside, and it refuses anything else. The verifiers never
call it: they hash what was signed, whatever it is, and let the hash decide.

The policy (D23) is applied once, at creation, and then signed along with everything else: a
fixed ``call_gas`` generous enough for a contract wallet as recipient, a bounded deadline, and an
execution window after it. The text a decision shows is generated from the action (D24), so the
prose and the payment cannot disagree.

Nothing here touches Flask, the database or the network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

from qvault.chain.digest import execution_digest, proposal_id
from qvault.chain.evm import ChainValueError, checksum_address
from qvault.services import signing

KIND_ETH_TRANSFER = "eth_transfer"
ACTION_KEYS = frozenset(
    {"kind", "chain_id", "treasury", "to", "value_wei", "data", "call_gas", "valid_until"}
)
MAX_SAFE_INTEGER = 2**53 - 1
UINT256_MAX = 2**256 - 1
WEI_PER_ETH = 10**18
# EIP-7825: a callGas above the per-transaction cap could never be forwarded, so it could never run.
TX_GAS_CAP = 16_777_216

# D23. 100,000 covers a contract wallet receiving ETH; an externally owned account uses none of
# it. Unused callGas is never charged: it raises the transaction's gas limit, not the gas spent.
ETH_TRANSFER_CALL_GAS = 100_000
DEFAULT_DEADLINE = timedelta(days=7)
MAX_DEADLINE = timedelta(days=30)
EXECUTION_WINDOW = timedelta(hours=72)

NETWORKS = signing.PAYMENT_NETWORKS
ZERO_ADDRESS = "0x" + "00" * 20

_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)", re.ASCII)


class ActionError(ValueError):
    """A payment that cannot be signed: malformed, out of policy, or not in the canonical form."""


@dataclass(frozen=True)
class EthTransfer:
    """Send ``value_wei`` from a vault's treasury to ``to``, once M approvers have signed."""

    chain_id: int
    treasury: str
    to: str
    value_wei: int
    call_gas: int
    valid_until: int

    kind: ClassVar[str] = KIND_ETH_TRANSFER
    data: ClassVar[bytes] = b""

    def canonical(self) -> dict[str, Any]:
        """The ``action`` object exactly as it is signed (D22)."""
        return {
            "kind": self.kind,
            "chain_id": self.chain_id,
            "treasury": self.treasury,
            "to": self.to,
            "value_wei": str(self.value_wei),
            "data": "0x" + self.data.hex(),
            "call_gas": self.call_gas,
            "valid_until": self.valid_until,
        }

    @property
    def network(self) -> str:
        return NETWORKS[self.chain_id]

    def describe(self) -> str:
        """The decision's text (D24): generated, so it can never disagree with the payment.

        Both verifiers regenerate it from the signed action and refuse a decision whose text
        differs, so a server cannot sign one payment under a description of another.
        """
        text = signing.payment_text(self.canonical())
        if text is None:  # unreachable for a built or parsed transfer; never assert it away
            raise ActionError("this payment cannot be described")
        return text

    def valid_until_utc(self) -> datetime:
        return datetime.fromtimestamp(self.valid_until, UTC)

    def execution_digest(self, payload_hash: str) -> bytes:
        """What each approver signs for the treasury (D8): this action, for this decision."""
        return execution_digest(
            chain_id=self.chain_id,
            treasury=self.treasury,
            proposal_id=proposal_id(payload_hash),
            to=self.to,
            value_wei=self.value_wei,
            data=self.data,
            call_gas=self.call_gas,
            valid_until=self.valid_until,
        )


# The text generator lives in qvault.services.signing, beside the payload it describes, so the
# offline verifier can check a decision's text against its payment without Ethereum libraries.
format_wei = signing.format_wei


def parse_eth_value(text: str) -> int:
    """An ETH amount a person typed (``"0.0001"``) as exact wei. At most 18 decimal places."""
    # Length first: Python refuses int() on strings past 4,300 digits with a plain ValueError,
    # and no real amount has more than 60 whole-ETH digits (2^256 wei is 78 digits in total).
    if (
        not isinstance(text, str)
        or len(text.strip()) > 100
        or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", text.strip(), re.ASCII)
    ):
        raise ActionError("enter an amount in ETH, such as 0.0001")
    whole, _, fraction = text.strip().partition(".")
    if len(fraction) > 18:
        raise ActionError("an ETH amount has at most 18 decimal places")
    return int(whole) * WEI_PER_ETH + int(fraction.ljust(18, "0") or "0")


def payment_deadline(now: datetime, requested: datetime | None) -> datetime:
    """The deadline a payment decision gets (D23): 7 days by default, never more than 30."""
    if now.tzinfo is None:
        raise ActionError("the current time must be timezone-aware")
    if requested is None:
        return now + DEFAULT_DEADLINE
    if requested.tzinfo is None:
        raise ActionError("a payment deadline must be timezone-aware")
    if requested <= now:
        raise ActionError("a payment deadline must be in the future")
    if requested - now > MAX_DEADLINE:
        raise ActionError("a payment decision's deadline can be at most 30 days away")
    return requested


def build_eth_transfer(
    *, chain_id: int, treasury: str, to: str, value_wei: int, deadline: datetime
) -> EthTransfer:
    """A new ETH transfer under the D23 policy. Addresses may be given in any valid form."""
    if deadline.tzinfo is None:
        raise ActionError("a payment deadline must be timezone-aware")
    valid_until = int((deadline + EXECUTION_WINDOW).timestamp())
    return _checked(
        chain_id=chain_id,
        treasury=_address(treasury, "treasury", canonical_only=False),
        to=_address(to, "recipient", canonical_only=False),
        value_wei=value_wei,
        call_gas=ETH_TRANSFER_CALL_GAS,
        valid_until=valid_until,
    )


def parse(obj: object) -> EthTransfer:
    """The action inside a signed payload, refusing anything not exactly in the D22 shape."""
    if not isinstance(obj, dict):
        raise ActionError("an action must be an object")
    if set(obj) != ACTION_KEYS:
        missing = sorted(ACTION_KEYS - set(obj))
        extra = sorted(set(obj) - ACTION_KEYS)
        raise ActionError(
            f"an action has exactly the keys {sorted(ACTION_KEYS)} (missing "
            f"{missing}, unexpected {extra})"
        )
    if obj["kind"] != KIND_ETH_TRANSFER:
        raise ActionError(f"unsupported action kind {obj['kind']!r}")
    if obj["data"] != "0x":
        raise ActionError("an ETH transfer carries no call data")
    value = obj["value_wei"]
    if not isinstance(value, str) or not _DECIMAL.fullmatch(value):
        raise ActionError("value_wei must be a decimal string without sign or leading zeros")
    return _checked(
        chain_id=obj["chain_id"],
        treasury=_address(obj["treasury"], "treasury", canonical_only=True),
        to=_address(obj["to"], "recipient", canonical_only=True),
        value_wei=int(value),
        call_gas=obj["call_gas"],
        valid_until=obj["valid_until"],
    )


def _checked(
    *,
    chain_id: object,
    treasury: str,
    to: str,
    value_wei: object,
    call_gas: object,
    valid_until: object,
) -> EthTransfer:
    chain = _safe_integer(chain_id, "chain_id")
    if chain not in NETWORKS:
        raise ActionError(f"chain {chain} is not supported (Sepolia only)")
    if isinstance(value_wei, bool) or not isinstance(value_wei, int) or value_wei < 1:
        raise ActionError("a payment must move at least 1 wei")
    if value_wei > UINT256_MAX:
        raise ActionError("that amount is larger than any Ethereum balance can be")
    gas = _safe_integer(call_gas, "call_gas")
    if not 1 <= gas <= TX_GAS_CAP:
        raise ActionError(f"call_gas must be between 1 and {TX_GAS_CAP}")
    deadline = _safe_integer(valid_until, "valid_until")
    if deadline < 1:
        raise ActionError("valid_until must be a positive timestamp")
    if to == treasury:
        raise ActionError("a treasury cannot pay itself")
    return EthTransfer(
        chain_id=chain,
        treasury=treasury,
        to=to,
        value_wei=value_wei,
        call_gas=gas,
        valid_until=deadline,
    )


def _safe_integer(value: object, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_SAFE_INTEGER:
        raise ActionError(f"{what} must be a non-negative integer no larger than 2^53 - 1")
    return value


def _address(value: object, what: str, *, canonical_only: bool) -> str:
    try:
        checksummed = checksum_address(value)  # type: ignore[arg-type]
    except ChainValueError:
        raise ActionError(f"the {what} is not a valid Ethereum address") from None
    if canonical_only and value != checksummed:
        raise ActionError(f"the {what} must be written in its EIP-55 checksummed form")
    if checksummed == checksum_address(ZERO_ADDRESS):
        raise ActionError(f"the {what} cannot be the zero address")
    return checksummed
