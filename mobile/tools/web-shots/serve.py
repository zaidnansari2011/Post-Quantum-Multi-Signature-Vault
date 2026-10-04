"""Web screenshot harness ONLY: serve the `expo export --platform web` build and proxy /api to a
local backend on the same origin, so the browser needs no CORS (the Flask API sends none).

Usage: python serve.py <dist dir> <port> <backend origin, e.g. http://127.0.0.1:5077>
Refuses any backend that is not on localhost, so a typo cannot point the harness at production.
"""

import http.client
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

DIST = Path(sys.argv[1]).resolve()
PORT = int(sys.argv[2])
BACKEND = urlsplit(sys.argv[3])
if BACKEND.hostname not in ("127.0.0.1", "localhost"):
    sys.exit(f"refusing non-local backend {sys.argv[3]}")

HOP = {
    "connection",
    "keep-alive",
    "transfer-encoding",
    "te",
    "trailer",
    "upgrade",
    "content-length",
}
FORWARD = ("Accept", "Authorization", "Content-Type", "X-QVault-Capabilities")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet, but keep API calls visible
        if self.path.startswith("/api/"):
            sys.stderr.write(f"{self.command} {fmt % args}\n")

    def _proxy(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {h: self.headers[h] for h in FORWARD if self.headers.get(h)}
        conn = http.client.HTTPConnection(BACKEND.hostname, BACKEND.port or 80, timeout=120)
        conn.request(self.command, self.path, body=body, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        self.send_response(resp.status)
        for k, v in resp.getheaders():
            if k.lower() not in HOP:
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        conn.close()

    def _static(self):
        rel = urlsplit(self.path).path.lstrip("/")
        target = (DIST / rel).resolve()
        if not str(target).startswith(str(DIST)) or not target.is_file():
            target = DIST / "index.html"  # single-page app fallback
        data = target.read_bytes()
        self.send_response(200)
        self.send_header(
            "Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        )
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._proxy() if self.path.startswith("/api/") else self._static()

    def do_POST(self):
        self._proxy()

    def do_PUT(self):
        self._proxy()


if __name__ == "__main__":
    print(f"serving {DIST} on http://127.0.0.1:{PORT}, /api -> {sys.argv[3]}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
