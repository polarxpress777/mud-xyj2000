#!/usr/bin/env python3
"""boteditor -- browser code editor for bots/*.py.

    python3 boteditor.py        then open http://127.0.0.1:8777

Bots are plain Python files with a run(api) function (see botapi.py) --
this is just a textarea that reads/writes bots/<name>.py, so you can
paste/copy freely and it's the same files botproxy.py's /run loads.
Any real editor works too; this exists for convenience, not because
the format needs one.

The UI is editor.html next to this file; this module is only the small
JSON API that reads and writes bots/. Edit the HTML and reload the page.

Stdlib only.
"""
from __future__ import annotations

import json
import re
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

BOTS_DIR = Path(__file__).with_name("bots")
PORT = 8777
NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")

TEMPLATE = '''# %s -- describe what this bot does here.
#
# Run in-game with: /run %s   (stop with /stop %s)

def run(api):
    while not api.stopped():
        api.send("look")
        api.sleep(5)
'''

PAGE_FILE = Path(__file__).with_name("editor.html")


def page() -> bytes:
    """The editor UI, read fresh on every request.

    It lives in editor.html rather than in a string here so it can be edited
    as HTML -- with highlighting, and without escaping -- and so reloading
    the browser is enough to see a change. Only the API below is Python.
    """
    try:
        return PAGE_FILE.read_bytes()
    except OSError:
        return (f"<h1>editor.html is missing</h1><p>Expected it next to "
                f"{Path(__file__).name}, at {PAGE_FILE}.</p>").encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def _send(self, body: bytes, ctype="application/json", status=200):
        self.send_response(status)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status=200):
        self._send(json.dumps(obj, ensure_ascii=False).encode("utf-8"), status=status)

    def _safe_name(self, name: str):
        return name if isinstance(name, str) and NAME_RE.match(name) else None

    def do_GET(self):
        path = urlparse(self.path).path
        qs = dict(p.split("=", 1) for p in urlparse(self.path).query.split("&") if "=" in p)

        if path == "/":
            return self._send(page(), "text/html")

        if path == "/api/bots":
            BOTS_DIR.mkdir(exist_ok=True)
            names = sorted(p.stem for p in BOTS_DIR.glob("*.py"))
            return self._json({"bots": names})

        if path == "/api/bot":
            from urllib.parse import unquote
            name = self._safe_name(unquote(qs.get("name", "")))
            if not name:
                return self._send(b"bad name", status=400)
            f = BOTS_DIR / f"{name}.py"
            if not f.exists():
                return self._send(b"not found", status=404)
            return self._json({"name": name, "code": f.read_text(encoding="utf-8")})

        if path == "/api/template":
            from urllib.parse import unquote
            name = self._safe_name(unquote(qs.get("name", "bot"))) or "bot"
            return self._json({"code": TEMPLATE % (name, name, name)})

        self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        n = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(n) or b"{}")

        if path == "/api/bot":
            name = self._safe_name(payload.get("name", ""))
            code = payload.get("code", "")
            if not name:
                return self._send(b"bad name", status=400)
            BOTS_DIR.mkdir(exist_ok=True)
            (BOTS_DIR / f"{name}.py").write_text(code, encoding="utf-8")
            return self._json({"saved": True})

        self.send_error(404)

    def do_DELETE(self):
        path = urlparse(self.path).path
        n = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(n) or b"{}")

        if path == "/api/bot":
            name = self._safe_name(payload.get("name", ""))
            if not name:
                return self._send(b"bad name", status=400)
            f = BOTS_DIR / f"{name}.py"
            if f.exists():
                f.unlink()
            return self._json({"deleted": True})

        self.send_error(404)

    def log_message(self, *a):
        pass          # keep the console quiet


def main():
    BOTS_DIR.mkdir(exist_ok=True)
    srv = HTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"boteditor: {url}   (Ctrl-C to stop)")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nboteditor stopped.")


if __name__ == "__main__":
    main()
