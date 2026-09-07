"""Achievement/badge definitions and awarding (P8).

Achievements are pure functions over the progress document. `award` is called
from `engine.finalize` and appends any newly-earned ids to `progress["achievements"]`.
"""

from __future__ import annotations

from collections.abc import Callable


def _total_completed(progress: dict) -> int:
    return sum(len(s.get("completed_ids", [])) for s in progress.get("skills", {}).values())


def _checkers() -> list[tuple[str, str, str, Callable[[dict], bool]]]:
    def first_blood(p: dict) -> bool:
        return _total_completed(p) >= 1

    def streak_7(p: dict) -> bool:
        return p.get("streak", {}).get("longest", 0) >= 7

    def century(p: dict) -> bool:
        return p.get("total_xp", 0) >= 100

    def pack_complete(p: dict) -> bool:
        from . import loader

        for pack in loader.load_all_packs():
            ids = {c.id for c in pack.challenges}
            done = set(p.get("skills", {}).get(pack.skill, {}).get("completed_ids", []))
            if ids and ids <= done:
                return True
        return False

    def daily_5(p: dict) -> bool:
        return len(p.get("daily", {}).get("dates", [])) >= 5

    def combo_master(p: dict) -> bool:
        # Reached via any session; we approximate using daily/weekly accuracy.
        return p.get("total_xp", 0) >= 500

    return [
        ("first_blood", "First Blood", "Complete your first challenge.", first_blood),
        ("streak_7", "Week Strong", "Keep a 7-day streak alive.", streak_7),
        ("century", "Century", "Earn 100 total XP.", century),
        ("pack_complete", "Pack Rat", "Finish every challenge in a pack.", pack_complete),
        ("daily_5", "Daily Devotion", "Complete 5 daily challenges.", daily_5),
        ("combo_master", "Combo Master", "Reach 500 total XP.", combo_master),
    ]


ACHIEVEMENTS: list[dict] = [{"id": i, "name": n, "description": d} for (i, n, d, _) in _checkers()]


def award(progress: dict) -> list[str]:
    """Append any newly-earned achievement ids; return the newly awarded list."""
    earned = set(progress.get("achievements", []))
    newly: list[str] = []
    for aid, _name, _desc, check in _checkers():
        if aid not in earned and check(progress):
            earned.add(aid)
            newly.append(aid)
    if newly:
        progress["achievements"] = sorted(earned)
    return newly


def by_id(aid: str) -> dict | None:
    for a in ACHIEVEMENTS:
        if a["id"] == aid:
            return a
    return None
