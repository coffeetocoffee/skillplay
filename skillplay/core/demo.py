"""V9 - zero-install "try it" web demo.

A tiny, dependency-free HTTP server (stdlib only) that serves a random challenge so
someone can taste skillplay in a browser without installing anything - just run the
single binary: `skillplay demo`. The TUI itself is already zero-install via the
single-binary build; this is the no-account, in-browser on-ramp.

All content respects the active language (see `loader.Challenge.localized`), so the
demo shows prompts/hints/explanations in the user's chosen locale.
"""

from __future__ import annotations

import random
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from .loader import Pack


def _solution_text(ch) -> str:
    mode = ch.validation.get("mode")
    if mode in ("test_cases", "freeform"):
        return ch.answer.get("reference_code", "")
    if mode == "sql_result":
        return ch.answer.get("reference_sql", "")
    if mode == "exact":
        return ch.answer.get("value", "")
    if mode == "regex_tester":
        return ch.answer.get("value", "")
    if mode == "multiple_choice":
        aid = ch.validation.get("answer_id")
        for o in ch.options:
            if o.get("id") == aid:
                return f"{aid}: {o.get('text', '')}"
        return str(aid)
    return ""


def random_challenge_payload(packs: list[Pack], rng: random.Random | None = None) -> dict[str, Any]:
    """A single random challenge as a JSON-serializable dict, using the active
    language for all user-facing text."""
    rng = rng or random.Random()
    all_ch = [c for p in packs for c in p.challenges]
    if not all_ch:
        return {}
    ch = rng.choice(all_ch)
    return {
        "id": ch.id,
        "skill": ch.skill,
        "title": ch.localized("title"),
        "prompt": ch.localized("prompt"),
        "hints": ch.localized("hints"),
        "solution": _solution_text(ch),
        "explanation": ch.localized("explanation"),
        "mode": ch.validation.get("mode"),
    }


_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>skillplay - try it</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; }
  pre { background: #f4f4f4; padding: 1rem; border-radius: 8px; overflow-x: auto; }
  button { margin-right: .5rem; padding: .5rem .8rem; border-radius: 6px; border: 1px solid #888; cursor: pointer; }
  .muted { color: #666; }
</style>
</head>
<body>
  <h1>skillplay</h1>
  <p class="muted">Learn dev skills by playing. A random challenge:</p>
  <h2 id="title"></h2>
  <pre id="prompt"></pre>
  <button onclick="reveal('hint')">Show hint</button>
  <button onclick="reveal('solution')">Show solution</button>
  <button onclick="next()">Next challenge</button>
  <pre id="reveal" style="display:none"></pre>
  <script>
    let current = null;
    async function load() {
      const r = await fetch('/api/challenge');
      current = await r.json();
      document.getElementById('title').textContent = current.title + '  (' + current.skill + ')';
      document.getElementById('prompt').textContent = current.prompt;
      const rev = document.getElementById('reveal');
      rev.style.display = 'none'; rev.textContent = '';
    }
    function reveal(kind) {
      if (!current) return;
      const rev = document.getElementById('reveal');
      rev.style.display = 'block';
      rev.textContent = (kind === 'hint' ? 'Hint: ' : 'Solution:\\n') + (kind === 'hint' ? current.hints[0] : current.solution + '\\n\\n' + current.explanation);
    }
    function next() { load(); }
    load();
  </script>
</body>
</html>
"""


def build_demo_html() -> str:
    return _HTML


class DemoHandler(BaseHTTPRequestHandler):
    """Serves the demo page and a JSON challenge endpoint. The pack list is stored
    on the server instance by `run_demo_server` and read via `self.server.packs`."""

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.startswith("/api/challenge"):
            import json

            payload = random_challenge_payload(getattr(self.server, "packs", []))
            self._send(200, json.dumps(payload).encode("utf-8"), "application/json")
            return
        self._send(200, build_demo_html().encode("utf-8"), "text/html")

    def log_message(self, *args: Any) -> None:  # silence default stderr logging
        return


def run_demo_server(packs: list[Pack], host: str = "127.0.0.1", port: int = 8080) -> HTTPServer:
    """Start (and return) the demo HTTP server. Caller is responsible for
    `serve_forever()` / `shutdown()` - useful for embedding in the CLI."""
    server = HTTPServer((host, port), DemoHandler)
    server.packs = packs
    return server
