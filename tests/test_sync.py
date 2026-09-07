"""Tests for V5 encrypted, account-free progress sync.

Covers the crypto round-trip, unguessable slot derivation, the server's
sync endpoints, and an end-to-end CLI push/pull against a local server.
"""

from __future__ import annotations

import base64
import json
import threading
import urllib.request
from http.server import HTTPServer

from skillplay.core import leaderboard_server as lbs
from skillplay.core import sync as sync_mod

# --- unit: crypto + slot -----------------------------------------------------


def test_encrypt_decrypt_round_trip():
    key = sync_mod.ensure_device_key()
    data = {"total_xp": 42, "skills": {"sql": {"xp": 42}}}
    blob = sync_mod.encrypt_progress(key, data)
    # ciphertext must not leak plaintext
    assert b"total_xp" not in blob
    assert sync_mod.decrypt_progress(key, blob) == data


def test_decrypt_with_wrong_key_fails():
    from cryptography.fernet import Fernet

    key_a = sync_mod.ensure_device_key()
    other = Fernet.generate_key().decode("ascii")  # valid format, different key
    blob = sync_mod.encrypt_progress(key_a, {"x": 1})
    try:
        sync_mod.decrypt_progress(other, blob)
        assert False, "expected SyncError"
    except sync_mod.SyncError:
        pass


def test_slot_id_is_deterministic_and_key_dependent():
    a = "AAAAkey-one"
    b = "AAAAkey-two"
    assert sync_mod.slot_id(a, "alice") == sync_mod.slot_id(a, "alice")
    assert sync_mod.slot_id(a, "alice") != sync_mod.slot_id(a, "bob")
    assert sync_mod.slot_id(a, "alice") != sync_mod.slot_id(b, "alice")


# --- server: sync endpoints --------------------------------------------------


def _start_server(db_path):
    srv = HTTPServer(("127.0.0.1", 0), lbs._Handler)
    lbs._Handler.db_path = str(db_path)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
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


def test_server_sync_put_get_round_trip(tmp_path):
    import urllib.error

    srv, port = _start_server(tmp_path / "lb.json")
    try:
        slot = "s" * 64
        blob = base64.b64encode(b"opaque-ciphertext").decode()
        _post(port, "/sync/put", {"slot": slot, "name": "alice", "blob": blob})
        resp = json.loads(_get(port, f"/sync/get?slot={slot}"))
        assert resp["name"] == "alice"
        assert resp["blob"] == blob
        # unknown slot -> 404
        try:
            _get(port, "/sync/get?slot=missing")
            assert False, "expected 404"
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
    finally:
        srv.shutdown()


# --- end-to-end: CLI push then pull into a fresh device ----------------------


def test_cli_sync_push_then_pull(tmp_path, monkeypatch):
    from argparse import Namespace

    from skillplay.core import cli

    # Device A: isolated data dir with some progress.
    dir_a = tmp_path / "a"
    dir_a.mkdir()
    monkeypatch.setattr(cli.pm, "DATA_DIR", dir_a)
    monkeypatch.setattr(cli.pm, "PROGRESS_PATH", dir_a / "progress.json")
    monkeypatch.setattr(sync_mod, "pm", cli.pm)  # keep sync pointed at same dir

    prog = cli.pm.default_progress()
    prog["total_xp"] = 123
    cli.pm.save(prog)

    # Start a local sync server.
    srv, port = _start_server(tmp_path / "lb.json")
    url = f"http://127.0.0.1:{port}"
    try:
        # Pair on device A -> get a key.
        rc = cli.cmd_sync(
            Namespace(pair=True, set_key=None, push=False, pull=False, handle="alice", url=url)
        )
        assert rc == 0
        key = sync_mod.device_key()
        assert key

        # Push from A.
        rc = cli.cmd_sync(
            Namespace(pair=False, set_key=None, push=True, pull=False, handle="alice", url=url)
        )
        assert rc == 0

        # Device B: fresh data dir, same key installed, then pull.
        dir_b = tmp_path / "b"
        dir_b.mkdir()
        monkeypatch.setattr(cli.pm, "DATA_DIR", dir_b)
        monkeypatch.setattr(cli.pm, "PROGRESS_PATH", dir_b / "progress.json")
        rc = cli.cmd_sync(
            Namespace(pair=False, set_key=key, push=False, pull=False, handle="alice", url=url)
        )
        assert rc == 0
        rc = cli.cmd_sync(
            Namespace(pair=False, set_key=None, push=False, pull=True, handle="alice", url=url)
        )
        assert rc == 0
        pulled = cli.pm.load()
        assert pulled["total_xp"] == 123
    finally:
        srv.shutdown()
