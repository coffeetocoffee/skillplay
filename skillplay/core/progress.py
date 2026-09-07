"""Progress persistence with atomic writes + rolling backups (W5)."""

from __future__ import annotations

import json
import os
import shutil
from datetime import date
from pathlib import Path
from typing import Any

from platformdirs import user_data_dir

DATA_DIR = Path(user_data_dir("skillplay", appauthor=False))
PROGRESS_PATH = DATA_DIR / "progress.json"

# Snapshot of an in-flight session, used for crash-safe resume (P9).
SESSION_SNAPSHOT_PATH = DATA_DIR / "session.snapshot.json"

# W5 data-loss guard: one dated backup per day, keep the newest N.
_MAX_BACKUPS = 14


def level_for_xp(xp: int) -> int:
    return int((xp / 100) ** 0.5) + 1


def xp_for_level(level: int) -> int:
    return (level - 1) ** 2 * 100


def _default_settings() -> dict[str, Any]:
    return {
        "session_size": 8,
        "sound": False,
        "theme": "dark",
        "language": "en",
        "telemetry": False,
        "leaderboard": {"name": "anon", "url": ""},
    }


def default_progress() -> dict[str, Any]:
    return {
        "version": 1,
        "total_xp": 0,
        "skills": {},
        "challenges": {},
        "streak": {"current": 0, "longest": 0, "last_played_date": ""},
        "settings": _default_settings(),
        "daily": {"dates": [], "last_done": ""},
        "xp_history": {},
        "accuracy_history": {},
        "achievements": [],
        "feedback": {},
        "mistakes": {},
        "goals": {},
        "attempts": [],
        "model": {},
        "certifications": {},
        "solutions": {},
        "portfolio": {},
    }


def _merge_defaults(data: dict[str, Any]) -> dict[str, Any]:
    """Fill in any missing keys so older progress files stay compatible."""
    base = default_progress()
    for key, value in base.items():
        if key not in data:
            data[key] = value
    # Settings is a nested dict that may have grown new keys.
    settings = data.setdefault("settings", {})
    for key, value in _default_settings().items():
        settings.setdefault(key, value)
    return data


def load() -> dict[str, Any]:
    if not PROGRESS_PATH.is_file():
        return default_progress()
    try:
        with PROGRESS_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        data.setdefault("version", 1)
        return _merge_defaults(data)
    except (json.JSONDecodeError, OSError):
        return default_progress()


def save(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # W5: snapshot the current on-disk file *before* overwriting it, so a bad
    # save or a corrupted in-memory state can always be rolled back. Best-effort
    # — a backup failure must never block the save itself.
    try:
        _backup(date.today().isoformat())
    except Exception:
        pass
    tmp = PROGRESS_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, PROGRESS_PATH)


def _backup(date_iso: str) -> Path | None:
    """Copy the current progress.json to backups/progress-<date>.json (W5)."""
    if not PROGRESS_PATH.is_file():
        return None
    bdir = DATA_DIR / "backups"
    bdir.mkdir(parents=True, exist_ok=True)
    dest = bdir / f"progress-{date_iso}.json"
    shutil.copyfile(PROGRESS_PATH, dest)
    _prune_backups()
    return dest


def _prune_backups(keep: int = _MAX_BACKUPS) -> None:
    backups = list_backups()
    for old in backups[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


def list_backups() -> list[Path]:
    """All backup snapshots, newest first."""
    bdir = DATA_DIR / "backups"
    if not bdir.is_dir():
        return []
    return sorted(bdir.glob("progress-*.json"), reverse=True)


def restore_backup(path: Path | None = None) -> bool:
    """Restore progress.json from a backup (default: the newest one).

    The file being replaced is itself backed up first, so a bad restore is
    also recoverable. Returns True on success.
    """
    src = path or (list_backups()[0] if list_backups() else None)
    if src is None or not src.is_file():
        return False
    if PROGRESS_PATH.is_file():
        try:
            _backup("pre-restore")
        except Exception:
            pass
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = PROGRESS_PATH.with_suffix(".tmp")
    shutil.copyfile(src, tmp)
    os.replace(tmp, PROGRESS_PATH)
    return True


def save_session_snapshot(snapshot: dict[str, Any]) -> None:
    """Persist a crash-safe snapshot of the current session (P9)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SESSION_SNAPSHOT_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, indent=2)
    os.replace(tmp, SESSION_SNAPSHOT_PATH)


def load_session_snapshot() -> dict[str, Any] | None:
    if not SESSION_SNAPSHOT_PATH.is_file():
        return None
    try:
        with SESSION_SNAPSHOT_PATH.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def clear_session_snapshot() -> None:
    if SESSION_SNAPSHOT_PATH.is_file():
        try:
            SESSION_SNAPSHOT_PATH.unlink()
        except OSError:
            pass


def today_str() -> str:
    return date.today().isoformat()
