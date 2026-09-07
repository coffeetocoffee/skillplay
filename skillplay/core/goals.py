"""Curated learning paths/goals assembled from existing challenges (P7).

A goal references a named pack (or explicit challenge ids) and tracks completion
based on `progress["skills"][skill]["completed_ids"]`. `refresh` is called from
`engine.finalize` and records which goals are now complete.
"""

from __future__ import annotations

# Each goal is purely declarative over existing packs/challenges.
GOALS: list[dict] = [
    {
        "id": "sql-in-7",
        "name": "SQL in 7 days",
        "description": "Finish every SQL Basics challenge.",
        "pack": "sql-basics",
        "skill": "sql",
    },
    {
        "id": "regex-101",
        "name": "Regex 101",
        "description": "Finish every Regex 101 challenge.",
        "pack": "regex-101",
        "skill": "regex",
    },
    {
        "id": "git-grounded",
        "name": "Git Grounded",
        "description": "Finish every Git Basics challenge.",
        "pack": "git-basics",
        "skill": "git",
    },
    {
        "id": "css-basics",
        "name": "CSS Basics",
        "description": "Finish every CSS Basics challenge.",
        "pack": "css-basics",
        "skill": "css",
    },
    {
        "id": "shell-basics",
        "name": "Shell Basics",
        "description": "Finish every Shell Basics challenge.",
        "pack": "shell-basics",
        "skill": "shell",
    },
    {
        "id": "http-rest",
        "name": "HTTP & REST",
        "description": "Finish every HTTP & REST challenge.",
        "pack": "http-rest",
        "skill": "http",
    },
    {
        "id": "data-structures",
        "name": "Data Structures",
        "description": "Finish every Data Structures challenge.",
        "pack": "data-structures",
        "skill": "python",
    },
    {
        "id": "algorithms",
        "name": "Algorithms",
        "description": "Finish every Algorithms challenge.",
        "pack": "algorithms",
        "skill": "algorithms",
    },
    {
        "id": "fix-bug",
        "name": "Fix the Bug (Python)",
        "description": "Finish every Python fix-bug challenge.",
        "pack": "fix-bug",
        "skill": "python",
    },
    {
        "id": "fix-bug-js",
        "name": "Fix the Bug (JavaScript)",
        "description": "Finish every JavaScript fix-bug challenge.",
        "pack": "fix-bug-js",
        "skill": "javascript",
    },
]


def _goal_progress(
    progress: dict, goal: dict, pack_challenge_ids: set[str]
) -> tuple[int, int, bool]:
    done = set(progress.get("skills", {}).get(goal["skill"], {}).get("completed_ids", []))
    total = len(pack_challenge_ids)
    completed = len(pack_challenge_ids & done)
    return completed, total, total > 0 and completed >= total


def refresh(progress: dict) -> list[str]:
    """Recompute goal completion; return ids newly completed this refresh."""
    from . import loader

    newly: list[str] = []
    stored = progress.setdefault("goals", {})
    packs_by_id = {p.id: p for p in loader.load_all_packs()}
    for goal in GOALS:
        rec = stored.setdefault(goal["id"], {"done": False, "completed": 0, "total": 0})
        pack = packs_by_id.get(goal["pack"])
        if pack is None:
            continue
        ids = {c.id for c in pack.challenges}
        completed, total, done = _goal_progress(progress, goal, ids)
        rec["completed"] = completed
        rec["total"] = total
        if done and not rec["done"]:
            rec["done"] = True
            newly.append(goal["id"])
    return newly


def status(progress: dict) -> list[dict]:
    """Return per-goal progress for display (no side effects)."""
    from . import loader

    packs_by_id = {p.id: p for p in loader.load_all_packs()}
    out: list[dict] = []
    stored = progress.get("goals", {})
    for goal in GOALS:
        rec = stored.get(goal["id"], {"done": False, "completed": 0, "total": 0})
        pack = packs_by_id.get(goal["pack"])
        ids = {c.id for c in pack.challenges} if pack else set()
        completed, total, done = _goal_progress(progress, goal, ids)
        out.append(
            {
                "id": goal["id"],
                "name": goal["name"],
                "description": goal["description"],
                "completed": rec.get("completed", completed),
                "total": rec.get("total", total),
                "done": rec.get("done", done),
            }
        )
    return out
