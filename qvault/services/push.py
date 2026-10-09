"""Sending one phone push through Expo's push service, and reading its receipts (plan R8).

Expo's service takes a message for an ``ExponentPushToken[...]`` and hands it to Firebase Cloud
Messaging for Android (the owner's FCM V1 key is uploaded to Expo for ``com.qvault.approvals``).
It answers with a *ticket*: accepted (with an id) or refused (with a reason). Whether FCM then
delivered it is a *receipt*, fetched later by ticket id. ``DeviceNotRegistered`` in either means
the app is gone from that phone, and its token is dropped (``delivery_service``).

Two transports: ``expo`` (HTTPS, over ``urllib`` like the mail and chain clients) and ``memory``
(tests: keeps each message and answers with what the test scripted). The suite never reaches Expo.

A push carries no amount, no address and no decision title (S12, phone-ux §6.23): those are written
by ``delivery_copy``, and what is sent here is only what it wrote.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from flask import current_app

SEND_URL = "https://exp.host/--/api/v2/push/send"
RECEIPTS_URL = "https://exp.host/--/api/v2/push/getReceipts"
TIMEOUT_S = 10.0
MAX_RESPONSE_BYTES = 256 * 1024
#: Expo takes at most this many receipt ids per request.
MAX_RECEIPT_IDS = 300

#: An Expo push token, the only kind this server sends to.
TOKEN = re.compile(r"^Expo(?:nent)?PushToken\[[A-Za-z0-9_-]{8,200}\]$")
_ERROR = re.compile(r"^[A-Za-z]{1,40}$")


class PushError(Exception):
    """A push that was not sent. ``str()`` is safe to store and log."""


class PushRefused(PushError):
    """Refused for good. ``code`` is Expo's reason, e.g. ``DeviceNotRegistered``."""

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class PushUnavailable(PushError):
    """Not sent this time; it may go if tried again later."""


@dataclass(frozen=True)
class PushMessage:
    to: str
    title: str
    body: str
    data: dict
    #: The Android channel the phone created: ``needs_you``, ``updates`` or ``security``.
    channel_id: str
    priority: str = "default"  # Expo's "default" or "high"


def transport_name(config) -> str:
    chosen = (config.get("PUSH_TRANSPORT") or "").strip().lower()
    return chosen if chosen in ("expo", "memory", "off") else "off"


def ready(config) -> bool:
    return transport_name(config) != "off"


def valid_token(token: object) -> bool:
    return isinstance(token, str) and bool(TOKEN.match(token))


# -- the memory transport (tests) ------------------------------------------------------------------


@dataclass
class _Memory:
    sent: list[PushMessage] = field(default_factory=list)
    #: Token -> Expo error code: the ticket refuses a push to it (``DeviceNotRegistered``).
    refuse: dict[str, str] = field(default_factory=dict)
    #: Ticket id -> Expo error code for its receipt; any other ticket's receipt is ``ok``.
    receipts: dict[str, str] = field(default_factory=dict)
    #: When set, every call fails as if Expo were unreachable.
    down: bool = False

    def clear(self) -> None:
        self.sent.clear()
        self.refuse.clear()
        self.receipts.clear()
        self.down = False


memory = _Memory()


# -- sending ---------------------------------------------------------------------------------------


def send(message: PushMessage) -> str:
    """Send ``message``; returns Expo's ticket id."""
    config = current_app.config
    if not valid_token(message.to):
        raise PushRefused("not an Expo push token", "InvalidToken")
    name = transport_name(config)
    if name == "off":
        raise PushUnavailable("push is not set up")
    if name == "memory":
        if memory.down:
            raise PushUnavailable("Expo unreachable: memory transport is down")
        if message.to in memory.refuse:
            code = memory.refuse[message.to]
            raise PushRefused(f"Expo refused the push ({code})", code)
        memory.sent.append(message)
        return f"ticket-{len(memory.sent)}"
    body = {
        "to": message.to,
        "title": message.title,
        "body": message.body,
        "data": message.data,
        "channelId": message.channel_id,
        "priority": message.priority,
        "sound": "default",
    }
    answer = _post(config, SEND_URL, body)
    ticket = answer.get("data") if isinstance(answer, dict) else None
    if isinstance(ticket, list) and len(ticket) == 1:
        ticket = ticket[0]
    if not isinstance(ticket, dict):
        raise PushUnavailable("Expo sent no ticket")
    if ticket.get("status") == "ok" and isinstance(ticket.get("id"), str):
        return ticket["id"][:120]
    code = _code(ticket)
    if code == "MessageRateExceeded":
        raise PushUnavailable("Expo asked to slow down (MessageRateExceeded)")
    raise PushRefused(f"Expo refused the push ({code or 'no reason given'})", code)


def receipts(ticket_ids: list[str]) -> dict[str, str]:
    """Each ticket's receipt: ``ok``, an Expo error code, or absent while it is not ready yet."""
    if not ticket_ids:
        return {}
    config = current_app.config
    name = transport_name(config)
    if name == "off":
        raise PushUnavailable("push is not set up")
    if name == "memory":
        if memory.down:
            raise PushUnavailable("Expo unreachable: memory transport is down")
        return {tid: memory.receipts.get(tid, "ok") for tid in ticket_ids}
    answer = _post(config, RECEIPTS_URL, {"ids": ticket_ids[:MAX_RECEIPT_IDS]})
    data = answer.get("data") if isinstance(answer, dict) else None
    if not isinstance(data, dict):
        raise PushUnavailable("Expo sent no receipts")
    found = {}
    for tid in ticket_ids:
        receipt = data.get(tid)
        if not isinstance(receipt, dict):
            continue
        found[tid] = "ok" if receipt.get("status") == "ok" else (_code(receipt) or "error")
    return found


def _code(ticket: dict) -> str | None:
    details = ticket.get("details")
    code = details.get("error") if isinstance(details, dict) else None
    return code if isinstance(code, str) and _ERROR.match(code) else None


def _post(config, url: str, body: dict) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "qvault-push",
    }
    if config.get("EXPO_ACCESS_TOKEN"):
        headers["Authorization"] = f"Bearer {config['EXPO_ACCESS_TOKEN']}"
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
    )
    payload = b""
    failure: PushError | None = None
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        # 429 and 5xx are worth another try; any other 4xx is a request Expo will never take.
        what = f"Expo answered HTTP {exc.code}"
        failure = PushUnavailable(what) if exc.code == 429 or exc.code >= 500 else PushRefused(what)
    except Exception as exc:  # noqa: BLE001
        failure = PushUnavailable(f"Expo unreachable: {type(exc).__name__}")
    if failure is not None:
        raise failure
    try:
        parsed = json.loads(payload[:MAX_RESPONSE_BYTES])
    except ValueError:
        raise PushUnavailable("Expo sent an unreadable answer") from None
    return parsed if isinstance(parsed, dict) else {}
