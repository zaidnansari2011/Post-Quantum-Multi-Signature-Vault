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

**The client's address.** Behind a reverse proxy every request arrives from the proxy, so all
visitors would share one bucket. ``RATE_LIMIT_PROXY_HOPS`` names how many proxies the deployment
trusts in front of it (Azure Container Apps: 1); the client is then read from that many places
from the right of ``X-Forwarded-For``, where a client cannot forge it. Zero, the default, uses the
connection's own address. Setting it without a proxy in front would let a client choose its own
bucket, so it is off unless the operator says otherwise.

Per address, never per account: a per-account limit would let anyone lock a person out by
guessing at their address on purpose. Each bucket counts every POST, successful or not; the
limits are generous enough that a person typing their own password never meets them.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque

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

#: (attempts, window in seconds) per bucket, per client address. RATE_LIMITS overrides any.
DEFAULT_LIMITS = {
    "sign_in": (20, 10 * 60),
    "sign_up": (10, 60 * 60),
    "pair": (20, 10 * 60),
}


class Limiter:
    """Sliding-window counts per (bucket, address), guarded by one lock (gunicorn threads)."""

    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, bucket: str, key: str, limit: int, window: float, now: float) -> float:
        """Count one attempt. Returns 0 when allowed, else the seconds until the next is."""
        with self._lock:
            hits = self._hits.setdefault((bucket, key), deque())
            while hits and hits[0] <= now - window:
                hits.popleft()
            if len(hits) >= limit:
                return max(1.0, hits[0] + window - now)
            hits.append(now)
            # Forget idle buckets now and then, so the table does not grow without bound.
            if len(self._hits) > 10_000:
                for k in [k for k, v in self._hits.items() if not v or v[-1] <= now - window]:
                    del self._hits[k]
            return 0.0


def client_address() -> str:
    hops = int(current_app.config.get("RATE_LIMIT_PROXY_HOPS") or 0)
    if hops > 0:
        forwarded = [
            part.strip()
            for part in request.headers.get("X-Forwarded-For", "").split(",")
            if part.strip()
        ]
        if len(forwarded) >= hops:
            return forwarded[-hops]
    return request.remote_addr or "unknown"


def limits() -> dict[str, tuple[int, int]]:
    return {**DEFAULT_LIMITS, **(current_app.config.get("RATE_LIMITS") or {})}


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
