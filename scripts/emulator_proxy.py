"""Auth-injecting proxy so the emulator never holds the real ingest token.

Run it to look at the real UI with real data in an emulator:

    UPSTREAM=http://<ct-ip>:8000 REAL_TOKEN=<token> python3 scripts/emulator_proxy.py

then in the app's Settings set Backend URL to `http://10.0.2.2:8900`
(the emulator's route to the host) and the ingest token to any non-blank
string — `isConfigured()` only checks for non-blank, and this proxy
supplies the real credential upstream.

Solves the two things that make emulator verification fail otherwise:

  1. The emulator is NAT'd and cannot reach the CT's LAN address, so the
     app just reports "couldn't reach the backend".
  2. Typing a 64-char hex token through `adb shell input` drops
     characters and 401s, and the Settings screen then displays the real
     token in any screenshot you take.


The app only requires SOME non-blank bearer token to consider itself
configured, so the emulator gets a throwaway one ("emulator") and this
proxy swaps in the real credential on the way out. That means:

  - no 64-char hex string typed through `adb shell input` (which dropped
    characters and produced a 401 last time), and
  - nothing secret can appear in a screenshot of the Settings screen.

Listens on the host; the emulator reaches it at 10.0.2.2:8900.

READ-ONLY BY DEFAULT. The emulator runs the same app as the phone, so its
SyncWorker cheerfully posts diagnostics to production — and because the
emulator has no Health Connect grants, those say "0 of 13 permissions". The
dashboard's health banner reads the MOST RECENT heartbeat regardless of which
device sent it, so a test install raises a false "Health Connect is denying
reads on the phone" alarm on the real dashboard and keeps re-raising it every
15 minutes. Writes that would corrupt shared state are refused here instead of
being cleaned up afterwards. Set ALLOW_WRITES=1 if you genuinely need them.
"""
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = os.environ["UPSTREAM"]          # e.g. http://<ct-ip>:8000
TOKEN = os.environ["REAL_TOKEN"]
HOP = {"host", "connection", "authorization", "content-length",
       "transfer-encoding", "keep-alive"}

ALLOW_WRITES = os.environ.get("ALLOW_WRITES") == "1"

# Endpoints where a test client writes state the real phone owns. Refused with
# a 200 so the app's own retry/buffer logic doesn't treat it as an outage.
BLOCKED_WRITES = ("/ingest/heartbeat", "/ingest/batch", "/logs")


class Proxy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _blocked(self) -> None:
        """Swallow a state-writing POST without forwarding it."""
        payload = b'{"status":"ok","note":"blocked by emulator_proxy"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
        print(f"BLOCKED write {self.path}", file=sys.stderr)

    def _relay(self, method: str) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        if (not ALLOW_WRITES and method == "POST"
                and any(self.path.startswith(b) for b in BLOCKED_WRITES)):
            self._blocked()
            return
        req = urllib.request.Request(
            UPSTREAM + self.path, data=body, method=method,
        )
        for k, v in self.headers.items():
            if k.lower() not in HOP:
                req.add_header(k, v)
        req.add_header("Authorization", f"Bearer {TOKEN}")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                payload, status, hdrs = r.read(), r.status, r.headers
        except urllib.error.HTTPError as e:
            payload, status, hdrs = e.read(), e.code, e.headers
        except Exception as e:  # noqa: BLE001
            payload, status, hdrs = str(e).encode(), 502, {}
            print(f"  !! {method} {self.path} -> {e}", file=sys.stderr)
        self.send_response(status)
        ctype = (hdrs.get("Content-Type") if hdrs else None) or "application/json"
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self): self._relay("GET")
    def do_POST(self): self._relay("POST")
    def do_PUT(self): self._relay("PUT")
    def do_PATCH(self): self._relay("PATCH")
    def do_DELETE(self): self._relay("DELETE")

    def log_message(self, fmt, *args):
        # Path only — never the headers, which carry the injected token.
        print(f"  {args[0] if args else ''} -> {args[1] if len(args) > 1 else ''}")


ThreadingHTTPServer(("0.0.0.0", 8900), Proxy).serve_forever()
