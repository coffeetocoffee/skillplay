"""Dependency-free sound effects (P9).

No audio backend required: uses the platform terminal bell where available.
On Windows we prefer the `winsound` console beep; elsewhere we emit a
terminal bell escape. Nothing is produced when `enabled` is False.
"""

from __future__ import annotations

import os
import sys


def beep(kind: str = "correct", enabled: bool = True) -> None:
    """Emit a short cue. kind in {correct, wrong, level_up}."""
    if not enabled:
        return
    # Respect a global opt-out env var as well.
    if os.environ.get("SKILLPLAY_NO_SOUND"):
        return
    try:
        if sys.platform.startswith("win"):
            import winsound  # type: ignore

            freq = {"correct": 880, "wrong": 220, "level_up": 1320}.get(kind, 660)
            winsound.Beep(freq, 120)
        else:
            # Terminal bell; level_up repeats for a little flourish.
            count = 1 if kind != "level_up" else 2
            sys.stdout.write("\a" * count)
            sys.stdout.flush()
    except Exception:
        # Sound is best-effort; never break gameplay over it.
        pass
