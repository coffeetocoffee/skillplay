"""Opt-in leaderboard server (P8 / C).

A minimal, account-free backend for the `skillplay leaderboard` / `share-stats`
clients. Scores are stored in a single JSON file; the board is available
all-time and per ISO **week** (weekly rollover), and can be filtered **by skill**
so rankings reflect real per-skill execution rather than total-XP inflation.
No login, no friends/rooms — handles + opt-in only.

Run with `skillplay serve-leaderboard`.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .progress import DATA_DIR


def _week_key(ts: float) -> str:
    y, w, _ = datetime.fromtimestamp(ts).isocalendar()
    return f"{y}-W{w:02d}"


def _now_week() -> str:
    return _week_key(datetime.now().timestamp())


def load_scores(db_path: str) -> list[dict[str, Any]]:
    if not os.path.isfile(db_path):
        return []
    try:
        with open(db_path, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return []


def save_scores(db_path: str, scores: list[dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    tmp = db_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(scores, fh, indent=2)
    os.replace(tmp, db_path)


def add_score(db_path: str, name: str, total_xp: int, skills: dict[str, int] | None = None) -> None:
    scores = load_scores(db_path)
    scores.append(
        {
            "name": name,
            "total_xp": int(total_xp),
            "skills": skills or {},
            "ts": datetime.now().timestamp(),
        }
    )
    save_scores(db_path, scores)


def boards(db_path: str, skill: str | None = None) -> dict[str, Any]:
    """All-time + current-week boards; optional per-skill ranking."""
    scores = load_scores(db_path)
    all_time = sorted(scores, key=lambda s: s.get("total_xp", 0), reverse=True)[:20]
    wk = _now_week()
    weekly = sorted(
        (s for s in scores if _week_key(s["ts"]) == wk),
        key=lambda s: s.get("total_xp", 0),
        reverse=True,
    )[:20]
    by_skill = None
    if skill:
        ents = [s for s in scores if (s.get("skills") or {}).get(skill) is not None]
        by_skill = sorted(ents, key=lambda s: s["skills"][skill], reverse=True)[:20]
    return {"all_time": all_time, "weekly": weekly, "by_skill": by_skill, "skill": skill}


# --- Public profile pages (C: auto-shareable progress, no accounts) ---------


def _profiles_path(db_path: str) -> str:
    return os.path.join(os.path.dirname(db_path) or ".", "leaderboard_profiles.json")


def load_profiles(db_path: str) -> dict[str, Any]:
    path = _profiles_path(db_path)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}


def save_profiles(db_path: str, profiles: dict[str, Any]) -> None:
    path = _profiles_path(db_path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(profiles, fh, indent=2)
    os.replace(tmp, path)


def add_profile(db_path: str, handle: str, profile: dict[str, Any]) -> None:
    profiles = load_profiles(db_path)
    profiles[handle] = profile
    save_profiles(db_path, profiles)


def get_profile(db_path: str, handle: str) -> dict[str, Any] | None:
    return load_profiles(db_path).get(handle)


# --- V5: end-to-end encrypted, account-free progress sync storage -----------
# The server stores only opaque ciphertext blobs keyed by an unguessable slot
# (derived client-side from the device key + handle). It cannot read the data.


def _sync_path(db_path: str) -> str:
    return os.path.join(os.path.dirname(db_path) or ".", "leaderboard_sync.json")


def load_sync(db_path: str) -> dict[str, Any]:
    path = _sync_path(db_path)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}


def save_sync(db_path: str, store: dict[str, Any]) -> None:
    path = _sync_path(db_path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(store, fh, indent=2)
    os.replace(tmp, path)


def put_sync_blob(db_path: str, slot: str, name: str, blob: str) -> None:
    store = load_sync(db_path)
    store[slot] = {"name": name, "blob": blob, "ts": datetime.now().timestamp()}
    save_sync(db_path, store)


def get_sync_blob(db_path: str, slot: str) -> dict[str, Any] | None:
    return load_sync(db_path).get(slot)


def profile_html(prof: dict[str, Any]) -> str:
    svg = prof.get("svg", "")
    skills = prof.get("skills", {})
    rows = "".join(
        f"<li>{k}: {v} XP</li>" for k, v in sorted(skills.items(), key=lambda kv: -kv[1])
    )
    return (
        f'<!doctype html><html><head><meta charset="utf-8">'
        f"<title>skillplay — {prof.get('name', 'anon')}</title></head>"
        f'<body style="background:#0f172a;color:#e2e8f0;font-family:sans-serif;padding:24px">'
        f"{svg}"
        f"<h1>{prof.get('name', 'anon')}</h1>"
        f"<p>Total XP: {prof.get('total_xp', 0)}</p>"
        f"<ul>{rows}</ul>"
        f'<p><a style="color:#94a3b8" href="/api/board">view leaderboard</a></p>'
        f"</body></html>"
    )


class _Handler(BaseHTTPRequestHandler):
    db_path = ""
    server_version = "skillplay-lb/1.0"

    def _send(self, code: int, payload: str, ctype: str = "application/json") -> None:
        body = payload.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path in ("", "/board", "/api/board"):
            q = parse_qs(parsed.query)
            skill = q.get("skill", [None])[0]
            self._send(200, json.dumps(boards(self.db_path, skill)))
        elif path == "/api/profile":
            q = parse_qs(parsed.query)
            name = q.get("name", ["anon"])[0]
            prof = get_profile(self.db_path, name)
            if prof is None:
                self._send(404, json.dumps({"error": "no profile for " + name}))
            else:
                self._send(200, json.dumps(prof))
        elif path == "/sync/get":
            q = parse_qs(parsed.query)
            slot = q.get("slot", [""])[0]
            rec = get_sync_blob(self.db_path, slot)
            if rec is None:
                self._send(404, json.dumps({"error": "no synced progress for slot"}))
            else:
                self._send(200, json.dumps(rec))
        elif path.startswith("/u/"):
            handle = path[len("/u/") :]
            prof = get_profile(self.db_path, handle)
            if prof is None:
                self._send(404, "<h1>not found</h1>", "text/html")
            else:
                self._send(200, profile_html(prof), "text/html")
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._send(400, json.dumps({"error": "bad json"}))
            return
        if path == "/submit":
            name = str(data.get("name", "anon"))[:32]
            xp = int(data.get("total_xp", 0))
            skills = {str(k): int(v) for k, v in (data.get("skills") or {}).items()}
            add_score(self.db_path, name, xp, skills)
            self._send(200, json.dumps({"ok": True}))
        elif path == "/profile":
            name = str(data.get("name", "anon"))[:32]
            prof = {
                "name": name,
                "total_xp": int(data.get("total_xp", 0)),
                "skills": {str(k): int(v) for k, v in (data.get("skills") or {}).items()},
                "streak": data.get("streak", {}),
                "achievements": data.get("achievements", []),
                "svg": str(data.get("svg", "")),
                "ts": datetime.now().timestamp(),
            }
            add_profile(self.db_path, name, prof)
            self._send(200, json.dumps({"ok": True, "url": f"/u/{name}"}))
        elif path == "/sync/put":
            slot = str(data.get("slot", ""))[:128]
            name = str(data.get("name", "anon"))[:32]
            blob = str(data.get("blob", ""))
            if not slot or not blob:
                self._send(400, json.dumps({"error": "slot and blob required"}))
            else:
                put_sync_blob(self.db_path, slot, name, blob)
                self._send(200, json.dumps({"ok": True}))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def log_message(self, *_args: Any) -> None:  # quiet
        pass


def run_server(host: str = "127.0.0.1", port: int = 8000, db_path: str | None = None) -> None:
    db = db_path or str(DATA_DIR / "leaderboard.json")
    _Handler.db_path = db
    srv = HTTPServer((host, port), _Handler)
    print(f"skillplay leaderboard server on http://{host}:{port}  (db: {db})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="serve-leaderboard", description="Run the skillplay leaderboard server."
    )
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--db", default=None, help="Path to the scores JSON file.")
    args = p.parse_args(argv)
    run_server(args.host, args.port, args.db)
    return 0
