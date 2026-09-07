"""V6 — Mastery exams (W6): a real learning metric, not just engagement.

A mastery exam is a randomized, mixed set of ~EXAM_SIZE challenges drawn across
all packs of one skill. It is graded like a normal session; scoring >= PASS_RATIO
certifies the player at the *target level* for that skill (the next difficulty
tier above their current certification, capped at the skill's hardest challenge).
Re-taking and passing raises the certified level — durable, demonstrable mastery.
"""

from __future__ import annotations

import random
from typing import Any

from . import engine, loader
from . import progress as pm

EXAM_SIZE = 20
PASS_RATIO = 0.9  # >= 90% correct certifies the attempted level


def skill_packs(packs: list, skill: str) -> list:
    return [p for p in packs if getattr(p, "skill", None) == skill]


def _target_level(challenges: list, current: int) -> int:
    """The difficulty tier this exam should target: current + 1, capped at max."""
    max_d = max((getattr(c, "difficulty", 1) for c in challenges), default=1)
    return min(current + 1, max_d) or 1


def build_exam(
    skill: str,
    progress: dict[str, Any],
    packs: list | None = None,
    size: int = EXAM_SIZE,
    rng: random.Random | None = None,
) -> engine.Session | None:
    """Build a randomized mastery-exam session for `skill`, or None if no content."""
    packs = packs or loader.load_all_packs()
    pk = skill_packs(packs, skill)
    challenges = [c for p in pk for c in p.challenges]
    if not challenges:
        return None
    rng = rng or random.Random()
    current = int(progress.get("certifications", {}).get(skill, {}).get("level", 0))
    target = _target_level(challenges, current)

    # Weight toward the target difficulty so the exam actually tests that tier,
    # but fall back to the full pool if a tier is thin.
    pool = [c for c in challenges if getattr(c, "difficulty", 1) == target] or challenges
    picked = rng.sample(pool, min(size, len(pool)))
    # A mixed exam: top up with a spread of other difficulties if room remains.
    remaining = [c for c in challenges if c not in picked]
    while len(picked) < min(size, len(challenges)) and remaining:
        picked.append(remaining.pop(rng.randrange(len(remaining))))
    rng.shuffle(picked)

    session = engine.Session(skill, picked)
    session.exam_skill = skill
    session.exam_target = target
    return session


def certify(session: engine.Session, progress: dict[str, Any]) -> dict[str, Any]:
    """Grade a finished exam session and record certification.

    Mutates `progress["certifications"]` in place (caller persists). Returns a
    result dict describing pass/fail and the resulting level."""
    total = len(session.challenges)
    skill = session.exam_skill or session.skill
    accuracy = (session.correct_count / total) if total else 0.0
    passed = total > 0 and accuracy >= PASS_RATIO
    current = int(progress.get("certifications", {}).get(skill, {}).get("level", 0))
    result: dict[str, Any] = {
        "skill": skill,
        "passed": passed,
        "accuracy": round(accuracy * 100),
        "target": session.exam_target,
        "level": current,
    }
    if not passed:
        return result

    certs = progress.setdefault("certifications", {})
    rec = certs.setdefault(
        skill,
        {"level": 0, "accuracy": 0, "best_accuracy": 0, "exams_passed": 0, "last_date": ""},
    )
    new_level = max(int(rec.get("level", 0)), session.exam_target)
    rec["level"] = new_level
    rec["accuracy"] = round(accuracy * 100)
    rec["best_accuracy"] = max(int(rec.get("best_accuracy", 0)), round(accuracy * 100))
    rec["exams_passed"] = int(rec.get("exams_passed", 0)) + 1
    rec["last_date"] = pm.today_str()
    result["level"] = new_level
    return result


def exam_status(progress: dict[str, Any], packs: list | None = None) -> list[dict[str, Any]]:
    """Per-skill certification summary for display (no side effects)."""
    packs = packs or loader.load_all_packs()
    skills: dict[str, list] = {}
    for p in packs:
        skills.setdefault(getattr(p, "skill", None) or p.id, []).append(p)
    out: list[dict[str, Any]] = []
    for skill, group in sorted(skills.items()):
        challenges = [c for p in group for c in p.challenges]
        max_d = max((getattr(c, "difficulty", 1) for c in challenges), default=1)
        rec = progress.get("certifications", {}).get(skill, {})
        out.append(
            {
                "skill": skill,
                "level": int(rec.get("level", 0)),
                "max_level": max_d,
                "accuracy": int(rec.get("accuracy", 0)),
                "exams_passed": int(rec.get("exams_passed", 0)),
                "last_date": rec.get("last_date", ""),
                "next_target": min(int(rec.get("level", 0)) + 1, max_d) or 1,
            }
        )
    return out
