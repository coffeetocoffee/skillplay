"""V5 — Encrypted, account-free progress sync (W5 data-loss guard).

The user's `progress.json` is encrypted client-side with a device-pairing key
never leaves the device. The leaderboard server stores only an opaque blob,
keyed by an unguessable *slot* derived from the key + a free-form handle, so
there are no accounts and the server learns nothing about the contents.

Pairing flow (no accounts):
  1. On the first device:  `skillplay sync --pair`  -> prints the device key.
  2. On each other device:  `skillplay sync --set-key <KEY>`  (same key).
  3. On any device:         `skillplay sync --push`  /  `skillplay sync --pull`

Pull overwrites local progress, but `progress.save` snapshots the current file
first, so `skillplay restore-progress` can always undo a sync.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from . import progress as pm

# Local-only: the device key lives here, never inside the synced progress blob
# (so pulling from another device can't clobber the key used to decrypt it).
# Resolved dynamically from pm.DATA_DIR so tests can redirect the data dir.


def _sync_key_path() -> Path:
    return pm.DATA_DIR / "sync.key"


class SyncError(Exception):
    """Raised for user-facing sync failures (missing key, bad server, decrypt)."""


# ---------------------------------------------------------------------------
# Device-pairing key (local)
# ---------------------------------------------------------------------------


def ensure_device_key() -> str:
    """Return the base64 device key, generating + persisting one if absent."""
    existing = device_key()
    if existing is not None:
        return existing
    key = Fernet.generate_key().decode("ascii")
    set_device_key(key)
    return key


def set_device_key(key_b64: str) -> str:
    """Install a device key copied from another device. Validates it's usable."""
    if not key_b64 or not isinstance(key_b64, str):
        raise SyncError("Device key must be a non-empty string.")
    key_b64 = key_b64.strip()
    try:
        Fernet(key_b64.encode("ascii"))  # raises if malformed
    except Exception as exc:
        raise SyncError(f"Invalid device key: {exc}") from exc
    pm.DATA_DIR.mkdir(parents=True, exist_ok=True)
    _sync_key_path().write_text(key_b64, encoding="utf-8")
    return key_b64


def device_key() -> str | None:
    path = _sync_key_path()
    if path.is_file():
        text = path.read_text(encoding="utf-8").strip()
        return text or None
    return None


def forget_device_key() -> None:
    path = _sync_key_path()
    if path.is_file():
        path.unlink()


# ---------------------------------------------------------------------------
# Crypto (stdlib-free dependency: cryptography's Fernet = AES-128-CBC + HMAC)
# ---------------------------------------------------------------------------


def slot_id(key: str, handle: str) -> str:
    """Unguessable server storage slot, derived from key + handle.

    Without the device key, the slot can't be enumerated — so the encrypted blob
    stays private even though the server is account-free."""
    return hmac.new(key.encode("utf-8"), handle.encode("utf-8"), hashlib.sha256).hexdigest()


def encrypt_progress(key: str, data: dict[str, Any]) -> bytes:
    raw = json.dumps(data, indent=2).encode("utf-8")
    return Fernet(key.encode("ascii")).encrypt(raw)


def decrypt_progress(key: str, blob: bytes) -> dict[str, Any]:
    try:
        raw = Fernet(key.encode("ascii")).decrypt(blob)
    except InvalidToken as exc:
        raise SyncError(
            "Decryption failed — wrong device key for this slot, or the blob was "
            "corrupted in transit."
        ) from exc
    return json.loads(raw.decode("utf-8"))


# ---------------------------------------------------------------------------
# Client transport (uses the leaderboard server's sync endpoints)
# ---------------------------------------------------------------------------


def sync_push(key: str, handle: str, base: str, path: Path | None = None) -> dict[str, Any]:
    """Encrypt the on-disk progress and PUT it to the server.

    `base` is the leaderboard server URL (the same server hosts sync); the caller
    resolves it (env / config / --url)."""
    src = path or pm.PROGRESS_PATH
    if not src.is_file():
        raise SyncError(f"No progress file to sync at {src}")
    data = json.loads(src.read_text(encoding="utf-8"))
    blob = encrypt_progress(key, data)
    payload = {
        "slot": slot_id(key, handle),
        "name": handle,
        "blob": base64.b64encode(blob).decode("ascii"),
    }
    _post_json(f"{base}/sync/put", payload)
    return {"slot": payload["slot"], "bytes": len(blob)}


def sync_pull(key: str, handle: str, base: str) -> dict[str, Any]:
    """GET the encrypted blob, decrypt it, and overwrite local progress.

    The current progress is snapshotted by `progress.save` before the overwrite,
    so the pull is always recoverable via `skillplay restore-progress`."""
    slot = slot_id(key, handle)
    resp = _get_json(f"{base}/sync/get?slot={slot}")
    if "blob" not in resp:
        raise SyncError(f"No synced progress found for handle '{handle}'.")
    blob = base64.b64decode(resp["blob"])
    data = decrypt_progress(key, blob)
    # Backs up the existing progress.json, then writes the decrypted data.
    pm.save(data)
    return {"name": resp.get("name", handle), "bytes": len(blob)}


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        raise SyncError(f"Sync server rejected push: {exc.code} {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise SyncError(f"Could not reach sync server: {exc.reason}") from exc


def _get_json(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {}
        raise SyncError(f"Sync server error: {exc.code} {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise SyncError(f"Could not reach sync server: {exc.reason}") from exc
