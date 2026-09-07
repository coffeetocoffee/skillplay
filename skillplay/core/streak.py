"""Streak bookkeeping."""

from __future__ import annotations

import datetime
from typing import Any


def update_streak(streak: dict[str, Any], today: str | None = None) -> dict[str, Any]:
    today = today or datetime.date.today().isoformat()
    last = streak.get("last_played_date", "")
    current = streak.get("current", 0)
    longest = streak.get("longest", 0)

    if last == today:
        return streak

    if last:
        prev = datetime.date.fromisoformat(last)
        diff = (datetime.date.fromisoformat(today) - prev).days
        if diff == 1:
            current += 1
        elif diff > 1:
            current = 1
        else:
            current = 1
    else:
        current = 1

    streak["current"] = current
    streak["longest"] = max(longest, current)
    streak["last_played_date"] = today
    return streak
