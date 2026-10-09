"""Sending one email, through whichever transport this instance is configured with (plan R8).

Three transports behind one ``send(message)``:

- ``resend``: Resend's HTTPS API (owner decision 2026-10-09), over ``urllib`` like the witness and
  chain clients, so no HTTP dependency is added. The API key is a secret: it goes in one request
  header and nowhere else, never into a log line, an exception or a stored error.
- ``log``: development. Writes the recipient and subject to the application log (and the text,
  under ``debug``), so a developer sees what would have gone.
- ``memory``: tests. Keeps each message in a list the test reads.

A transport raises ``MailRefused`` when the provider said no for good (a bad address, a domain not
verified) and ``MailUnavailable`` when trying again later may work (a timeout, a 5xx, a rate limit).
The outbox decides what to do with each (``delivery_service``).

**Headers are built here, from values cleaned here.** A subject carries a vault's name, which a
person typed; a carriage return or line feed in it must never become a second header. Every header
value is stripped of control characters and folded to one line, and a recipient must be one plain
address (no name, no comma, no angle bracket), so one email can only ever go to one person.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from flask import current_app

RESEND_URL = "https://api.resend.com/emails"
TIMEOUT_S = 10.0
MAX_RESPONSE_BYTES = 64 * 1024
#: Longest subject sent; a longer one is cut with an ellipsis.
MAX_SUBJECT = 140

#: One plain address: no display name, no list, nothing a header parser could split.
_ADDRESS = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$"
)
#: ``Name <address>`` or a plain address, for MAIL_FROM (which comes from configuration).
_FROM = re.compile(r"^(?:[^<>\"\r\n]{1,80} <(?P<inner>[^<>\s]+)>|(?P<bare>[^<>\s]+))$")


class MailError(Exception):
    """A message that was not sent. ``str()`` is safe to store and log: a few words, no secret."""


class MailRefused(MailError):
    """The provider refused it for good: sending it again would be refused again."""


class MailUnavailable(MailError):
    """It was not sent this time; it may go if tried again later."""


@dataclass(frozen=True)
class Message:
    to: str
    subject: str
    text: str
    html: str
    #: Extra headers (``List-Unsubscribe``). Cleaned like the subject.
    headers: dict[str, str] = field(default_factory=dict)
    #: Stops a retried send from being sent twice (Resend's ``Idempotency-Key``).
    idempotency_key: str | None = None


def header_value(value: str, *, limit: int | None = None) -> str:
    """``value`` as one safe header line: control characters (CR and LF among them) become spaces,
    runs of space fold to one, and it is cut to ``limit`` characters with an ellipsis."""
    cleaned = "".join(
        " " if (ord(ch) < 32 or 127 <= ord(ch) < 160 or ch in "  ") else ch for ch in str(value)
    )
    cleaned = " ".join(cleaned.split())
    if limit is not None and len(cleaned) > limit:
        cleaned = cleaned[: limit - 1].rstrip() + "…"
    return cleaned


def valid_address(address: str) -> bool:
    return isinstance(address, str) and len(address) <= 254 and bool(_ADDRESS.match(address))


def valid_from(value: str | None) -> bool:
    if not value or any(ord(ch) < 32 for ch in value):
        return False
    match = _FROM.match(value)
    return bool(match) and valid_address(match.group("inner") or match.group("bare"))


def transport_name(config) -> str:
    """The configured transport: ``resend``, ``log``, ``memory`` or ``off``."""
    chosen = (config.get("MAIL_TRANSPORT") or "").strip().lower()
    if not chosen:
        chosen = "resend" if config.get("RESEND_API_KEY") else "off"
    return chosen if chosen in ("resend", "log", "memory", "off") else "off"


def ready(config) -> bool:
    """Whether email can be sent at all: a transport, a valid sender, and (for real email) a key."""
    name = transport_name(config)
    if name == "off" or not valid_from(config.get("MAIL_FROM")):
        return False
    return name != "resend" or bool(config.get("RESEND_API_KEY"))


# -- the transports --------------------------------------------------------------------------------


#: What the ``memory`` transport has sent, oldest first. Tests clear it.
outbox: list[Message] = []


def send(message: Message) -> str:
    """Send ``message`` by the configured transport. Returns the provider's id for it."""
    config = current_app.config
    if not valid_address(message.to):
        raise MailRefused("the recipient is not one plain email address")
    name = transport_name(config)
    if name == "off" or not ready(config):
        raise MailUnavailable("email is not set up")
    subject = header_value(message.subject, limit=MAX_SUBJECT)
    headers = {header_value(k): header_value(v) for k, v in message.headers.items()}
    if name == "memory":
        outbox.append(
            Message(
                to=message.to,
                subject=subject,
                text=message.text,
                html=message.html,
                headers=headers,
                idempotency_key=message.idempotency_key,
            )
        )
        return f"memory-{len(outbox)}"
    if name == "log":
        current_app.logger.info(
            "email (not sent: MAIL_TRANSPORT=log) to %s: %s", message.to, subject
        )
        if current_app.debug:
            current_app.logger.info("%s", message.text)
        return "logged"
    return _resend(config, message, subject, headers)


def _resend(config, message: Message, subject: str, headers: dict[str, str]) -> str:
    body = {
        "from": header_value(config["MAIL_FROM"]),
        "to": [message.to],
        "subject": subject,
        "html": message.html,
        "text": message.text,
    }
    if headers:
        body["headers"] = headers
    request_headers = {
        "Authorization": f"Bearer {config['RESEND_API_KEY']}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "qvault-mail",
    }
    if message.idempotency_key:
        request_headers["Idempotency-Key"] = header_value(message.idempotency_key, limit=256)
    request = urllib.request.Request(
        RESEND_URL, data=json.dumps(body).encode("utf-8"), headers=request_headers, method="POST"
    )
    payload = b""
    failure: MailError | None = None
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        # Only the status and Resend's error name are kept: its message can quote the request.
        name = _error_name(exc)
        what = f"Resend answered HTTP {exc.code}" + (f" ({name})" if name else "")
        if exc.code == 429 or exc.code >= 500 or exc.code in (408, 409):
            failure = MailUnavailable(what)
        else:
            failure = MailRefused(what)
    except Exception as exc:  # noqa: BLE001 - timeouts, resets, DNS: all "try again later"
        failure = MailUnavailable(f"Resend unreachable: {type(exc).__name__}")
    if failure is not None:
        # Raised outside the handler, so no exception context carries the request (and its key).
        raise failure
    try:
        sent_id = json.loads(payload[:MAX_RESPONSE_BYTES]).get("id")
    except (ValueError, AttributeError):
        sent_id = None
    if not isinstance(sent_id, str) or not sent_id:
        # Resend took it (2xx) but said nothing readable: it is sent, so it must not be resent.
        return "unknown"
    return sent_id[:120]


def _error_name(exc: urllib.error.HTTPError) -> str | None:
    try:
        parsed = json.loads(exc.read(MAX_RESPONSE_BYTES))
    except Exception:  # noqa: BLE001 - an unreadable error body is no error name
        return None
    name = parsed.get("name") if isinstance(parsed, dict) else None
    if isinstance(name, str) and re.fullmatch(r"[a-z_]{1,60}", name):
        return name
    return None
