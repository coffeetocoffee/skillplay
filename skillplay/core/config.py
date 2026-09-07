"""Optional user config (config.yaml) merged over progress settings.

Kept intentionally tiny: only `session_size` and `sound` are honored today,
plus opt-in `leaderboard` settings. Place a `config.yaml` next to
`progress.json` (same data dir) to use it.
"""

from __future__ import annotations

import yaml

from .progress import DATA_DIR

CONFIG_PATH = DATA_DIR / "config.yaml"


def load_config() -> dict:
    if not CONFIG_PATH.is_file():
        return {}
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except (yaml.YAMLError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def apply_config(progress: dict) -> None:
    cfg = load_config()
    settings = progress.setdefault("settings", {})
    for key in ("session_size", "sound", "theme", "language", "telemetry"):
        if key in cfg:
            settings[key] = cfg[key]
    lb = cfg.get("leaderboard")
    if isinstance(lb, dict):
        settings.setdefault("leaderboard", {}).update(lb)


def save_config(progress: dict) -> None:
    """Persist relevant settings back to config.yaml (the user-editable store)."""
    settings = progress.get("settings", {})
    cfg: dict = {}
    if CONFIG_PATH.is_file():
        try:
            with CONFIG_PATH.open("r", encoding="utf-8") as fh:
                cfg = yaml.safe_load(fh) or {}
        except (yaml.YAMLError, OSError):
            cfg = {}
    cfg["session_size"] = settings.get("session_size", 8)
    cfg["sound"] = bool(settings.get("sound", False))
    cfg["theme"] = settings.get("theme", "dark")
    cfg["language"] = settings.get("language", "en")
    cfg["telemetry"] = bool(settings.get("telemetry", False))
    lb = settings.get("leaderboard", {})
    cfg["leaderboard"] = {
        "name": lb.get("name", "anon"),
        "url": lb.get("url", ""),
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh, default_flow_style=False, sort_keys=False)
