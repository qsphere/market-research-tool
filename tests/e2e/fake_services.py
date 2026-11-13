"""A local fake Nominatim + Overpass server so e2e runs never touch the real services."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from tests.helpers import fixture_text

GIFT = json.loads(fixture_text("overpass_gift.json"))
BOUTIQUES = {
    "elements": [
        {"type": "node", "id": 7001, "lat": 45.5, "lon": -122.6,
         "tags": {"name": "Treasure Trove Boutique", "shop": "boutique"}},
        {"type": "node", "id": 7002, "lat": 45.5001, "lon": -122.6,
         "tags": {"name": "Treasure Trove Boutiques", "shop": "boutique"}},
    ]
}  # fmt: skip
PORTLAND = json.loads(fixture_text("nominatim_portland.json"))
AMBIGUOUS = json.loads(fixture_text("nominatim_portland.json"))
AMBIGUOUS[1]["importance"] = 0.7


class FakeServices:
    """Start with ``.start()``; point the app at ``.url``. Behaviour is switchable per test."""

    def __init__(self) -> None:
        self.overpass_fail = False
        self.stats = {"nominatim": 0, "overpass": 0}
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # silence
                pass

            def _send(self, status: int, body) -> None:
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                url = urlparse(self.path)
                if url.path == "/search":
                    outer.stats["nominatim"] += 1
                    q = parse_qs(url.query).get("q", [""])[0].lower()
                    if "springfield" in q:
                        return self._send(200, AMBIGUOUS)
                    if "nowhere" in q:
                        return self._send(200, [])
                    return self._send(200, PORTLAND)
                self._send(404, {})

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = parse_qs(self.rfile.read(length).decode()).get("data", [""])[0]
                if self.path.startswith("/interpreter"):
                    outer.stats["overpass"] += 1
                    if outer.overpass_fail:
                        return self._send(504, {"error": "busy"})
                    return self._send(200, BOUTIQUES if '"shop"="boutique"' in body else GIFT)
                self._send(404, {})

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"

    def start(self) -> None:
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
