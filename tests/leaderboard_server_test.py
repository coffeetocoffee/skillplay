"""Tests for the opt-in leaderboard server (section C).

Runs a real HTTPServer in a background thread against a temp DB so we exercise
the actual HTTP routes (submit, board-by-skill, weekly rollover, profile page).
"""

from __future__ import annotations

import json
import threading
import urllib.request
from http.server import HTTPServer

from skillplay.core import leaderboard_server as lbs


def _start_server(db_path):
    srv = HTTPServer(("127.0.0.1", 0), lbs._Handler)
    lbs._Handler.db_path = str(db_path)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, port


def _post(port, path, payload):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode())


def _get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
        return r.read().decode()


def _get_status(port, path):
    import urllib.error

    try:
        _get(port, path)
        return 200
    except urllib.error.HTTPError as exc:
        return exc.code


def test_submit_and_board_by_skill(tmp_path):
    srv, port = _start_server(tmp_path / "lb.json")
    try:
        _post(port, "/submit", {"name": "alice", "total_xp": 100, "skills": {"sql": 80, "git": 20}})
        _post(port, "/submit", {"name": "bob", "total_xp": 50, "skills": {"sql": 30}})

        board = json.loads(_get(port, "/api/board?skill=sql"))
        assert board["skill"] == "sql"
        assert board["by_skill"][0]["name"] == "alice"
        assert board["by_skill"][0]["skills"]["sql"] == 80
        # all-time ranked by total_xp
        assert board["all_time"][0]["name"] == "alice"
        # weekly includes both (same ISO week)
        assert len(board["weekly"]) == 2
    finally:
        srv.shutdown()


def test_weekly_rollover_excludes_old_entries(tmp_path):
    db = tmp_path / "lb.json"
    lbs.add_score(str(db), "old", 999, {"sql": 999})
    # Rewind the stored entry into a previous ISO year so it leaves "this week".
    scores = lbs.load_scores(str(db))
    from datetime import datetime

    old_year = datetime.now().year - 2
    jan1 = datetime(old_year, 1, 1).timestamp()
    scores[0]["ts"] = jan1
    lbs.save_scores(str(db), scores)

    srv, port = _start_server(db)
    try:
        _post(port, "/submit", {"name": "new", "total_xp": 10, "skills": {"sql": 10}})
        board = json.loads(_get(port, "/api/board?skill=sql"))
        assert [r["name"] for r in board["weekly"]] == ["new"]  # old entry rolled out
        assert [r["name"] for r in board["all_time"]] == ["old", "new"]  # still in all-time
    finally:
        srv.shutdown()


def test_profile_public_page(tmp_path):
    srv, port = _start_server(tmp_path / "lb.json")
    try:
        _post(
            port,
            "/profile",
            {
                "name": "alice",
                "total_xp": 120,
                "skills": {"sql": 80},
                "svg": "<svg>card</svg>",
                "streak": {"current": 3},
                "achievements": ["first_blood"],
            },
        )
        html = _get(port, "/u/alice")
        assert "alice" in html and "<svg>card</svg>" in html
        prof = json.loads(_get(port, "/api/profile?name=alice"))
        assert prof["total_xp"] == 120
        # Missing handle -> 404
        assert _get_status(port, "/u/ghost") == 404
        assert _get_status(port, "/api/profile?name=ghost") == 404
    finally:
        srv.shutdown()
