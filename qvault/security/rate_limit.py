"""A small in-process rate limiter for the password-guessing doors (rework R6).

Four doors take a password from anyone: sign-in (``POST /login``), the two sign-ups
(``POST /register`` and ``POST /invite/<token>/register``), and the phone's pairing endpoints
(``POST /api/v1/devices/challenge`` and ``POST /api/v1/devices``). Each POST counts against a
bucket for the client's address over a sliding window; past the limit the request is refused with
429 and ``Retry-After`` before the view runs, so a refused guess costs no Argon2id work either.

**Per process.** The counts live in this process's memory (``app.extensions``), which is right for
the deployment as it is: one container, one gunicorn worker (the Dockerfile explains why). With
more workers or replicas each keeps its own counts, so the effective limit multiplies by their
number, and a restart forgets them. A shared store (Redis or the database) is the change that
lifts this; no third-party service is used today.

**Bounded.** Each bucket keeps its addresses in the order they were last counted, so the ones whose
window has passed are at the front and are dropped a few at a time on every hit, each bucket with
its own window (a sign-in hit never forgets a sign-up count early). No hit scans the table. Past
``MAX_KEYS`` addresses in one bucket the least recently counted is dropped to make room, so memory
stays bounded whatever an attacker with many addresses sends.

**The client's address.** Behind a reverse proxy every request arrives from the proxy, so all
visitors would share one bucket. ``RATE_LIMIT_PROXY_HOPS`` names how many proxies the deployment
trusts in front of it (Azure Container Apps' ingress: 1; with Cloudflare proxying in front of it:
2); the client is then read from that many places from the right of ``X-Forwarded-For``, where a
client cannot forge it. Zero uses the connection's own address. Production refuses to start
without the setting (``config.ProdConfig``). An address is parsed, not taken as text: a port is
stripped (``203.0.113.7:4711``, ``[2001:db8::1]:443``), an IPv6 client is counted by its /64
(one household or server is given a whole /64, so a per-address count would be a fresh bucket per
guess), and a value that is not an address falls back to the connection's own.

Per address, never per account, for the doors anyone can knock on: a per-account limit there
would let anyone lock a person out by guessing at their address on purpose. Each bucket counts
every POST, successful or not; the limits are generous enough that a person typing their own
password never meets them. (Signed-in password checks are limited per account instead, in
``qvault.security.password_attempts``: there only the account's own session can spend them.)
"""

from __future__ import annotations

import ipaddress
import math
import threading
import time
from collections import OrderedDict, deque

from flask import current_app, jsonify, request
from werkzeug.exceptions import TooManyRequests

#: Which bucket each endpoint's POSTs count against.
ENDPOINT_BUCKETS = {
    "auth.login": "sign_in",
    "auth.register": "sign_up",
    "workspace.register": "sign_up",
    "api.request_challenge": "pair",
    "api.enrol_device": "pair",
}

#: (attempts, window in seconds) per bucket, per client address. RATE_LIMIT_SIGNUP_PER_HOUR sets
#: the sign-up count; RATE_LIMITS overrides any bucket.
DEFAULT_LIMITS = {
    "sign_in": (20, 10 * 60),
    "sign_up": (10, 60 * 60),
    "pair": (20, 10 * 60),
}

#: Addresses remembered per bucket before the least recently counted is dropped.
MAX_KEYS = 50_000
#: Expired addresses dropped per bucket on each hit: enough to keep up with any arrival rate the
#: hits themselves create, small enough that no single hit does real work.
SWEEP_PER_HIT = 8


class _Bucket:
    __slots__ = ("window", "hits")

    def __init__(self, window: float) -> None:
        self.window = window
        # key -> the times it was counted, oldest first. Ordered by each key's newest count.
        self.hits: OrderedDict[str, deque[float]] = OrderedDict()

    def sweep(self, now: float, budget: int) -> None:
        """Drop up to ``budget`` keys from the front whose newest count is outside the window."""
        hits = self.hits
        while budget and hits:
            key, times = next(iter(hits.items()))
            if times and times[-1] > now - self.window:
                return
            del hits[key]
            budget -= 1


class Limiter:
    """Sliding-window counts per (bucket, address), guarded by one lock (gunicorn threads)."""

    def __init__(self, max_keys: int = MAX_KEYS) -> None:
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()
        self.max_keys = max_keys

    def __len__(self) -> int:
        return sum(len(b.hits) for b in self._buckets.values())

    def hit(self, bucket: str, key: str, limit: int, window: float, now: float) -> float:
        """Count one attempt. Returns 0 when allowed, else the seconds until the next is."""
        with self._lock:
            b = self._buckets.get(bucket)
            if b is None:
                b = self._buckets[bucket] = _Bucket(window)
            b.window = window
            for other in self._buckets.values():
                other.sweep(now, SWEEP_PER_HIT)

            hits = b.hits.get(key)
            if hits is None:
                while len(b.hits) >= self.max_keys:
                    b.hits.popitem(last=False)
                hits = b.hits[key] = deque()
            while hits and hits[0] <= now - window:
                hits.popleft()
            if len(hits) >= limit:
                return max(1.0, hits[0] + window - now)
            hits.append(now)
            b.hits.move_to_end(key)
            return 0.0


def normalise_address(value: str | None) -> str | None:
    """The bucket key for one address as a proxy or the socket gives it, or None if it is not
    one. Ports and brackets are stripped; IPv6 is counted by its /64."""
    if not value:
        return None
    text = value.strip().strip('"').strip()
    if text.startswith("["):  # [2001:db8::1] or [2001:db8::1]:443
        end = text.find("]")
        if end == -1:
            return None
        text = text[1:end]
    elif text.count(":") == 1:  # 203.0.113.7:4711
        text = text.split(":", 1)[0]
    text = text.split("%", 1)[0]  # an IPv6 zone index names an interface, not a client
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        return str(ipaddress.IPv6Network((address, 64), strict=False))
    return str(address)


def client_address() -> str:
    hops = int(current_app.config.get("RATE_LIMIT_PROXY_HOPS") or 0)
    if hops > 0:
        forwarded = [
            part.strip()
            for part in request.headers.get("X-Forwarded-For", "").split(",")
            if part.strip()
        ]
        if len(forwarded) >= hops:
            chosen = normalise_address(forwarded[-hops])
            if chosen is not None:
                return chosen
    return normalise_address(request.remote_addr) or request.remote_addr or "unknown"


def limits() -> dict[str, tuple[int, int]]:
    config = current_app.config
    out = dict(DEFAULT_LIMITS)
    per_hour = config.get("RATE_LIMIT_SIGNUP_PER_HOUR")
    if per_hour:
        out["sign_up"] = (int(per_hour), 60 * 60)
    return {**out, **(config.get("RATE_LIMITS") or {})}


def _check():
    if request.method != "POST" or not current_app.config.get("RATE_LIMIT_ENABLED", True):
        return None
    bucket = ENDPOINT_BUCKETS.get(request.endpoint or "")
    if bucket is None:
        return None
    limit, window = limits()[bucket]
    limiter: Limiter = current_app.extensions["rate_limiter"]
    wait = limiter.hit(bucket, client_address(), limit, window, time.monotonic())
    if not wait:
        return None
    retry = math.ceil(wait)
    minutes = max(1, math.ceil(retry / 60))
    message = (
        f"Too many attempts from this address. Try again in {minutes} "
        f"minute{'' if minutes == 1 else 's'}."
    )
    if request.path.startswith("/api/"):
        response = jsonify(ok=False, code="rate_limited", error=message, retry_after=retry)
        response.status_code = 429
        response.headers["Retry-After"] = str(retry)
        return response
    raise TooManyRequests(description=message, retry_after=retry)


def init_app(app) -> None:
    app.extensions["rate_limiter"] = Limiter()
    app.before_request(_check)
