"""V6 — Mastery exams (W6): a real learning metric, not just engagement.

A mastery exam is a randomized, mixed set of ~EXAM_SIZE challenges drawn across
all packs of one skill. It is graded like a normal session; scoring >= PASS_RATIO
certifies the player at the *target level* for that skill (the next difficulty
tier above their current certification, capped at the skill's hardest challenge).
Re-taking and passing raises the certified level — durable, demonstrable mastery.

Cross-pack pools: a skill with fewer than EXAM_SIZE own challenges (a thin pack)
tops its exam up from curated related skills' packs (RELATED_SKILLS). Own
challenges always come first and dominate the paper; related fill prefers the
target tier, and attempts still attribute to each challenge's real skill.
"""

from __future__ import annotations

import random
from typing import Any

from . import engine, loader
from . import progress as pm

EXAM_SIZE = 20
PASS_RATIO = 0.9  # >= 90% correct certifies the attempted level

# Curated relatedness (not inferred): which skills' packs may top up a thin
# exam pool, in preference order. Skills absent here (sql, regex) keep their
# full-pool mixed exam — their own content is deep enough to stand alone.
RELATED_SKILLS: dict[str, tuple[str, ...]] = {
    "python": ("javascript",),
    "javascript": ("python",),  # fix-bug-js mirrors fix-bug debugging skills
    "algorithms": ("python",),  # algorithms packs are python code
    "git": ("shell",),  # git challenges are terminal work; shell fluency is adjacent
    "shell": ("git",),
    "css": ("http",),  # both web-platform families
    "http": ("css",),
}


def skill_packs(packs: list, skill: str) -> list:
    return [p for p in packs if getattr(p, "skill", None) == skill]


def related_skills(skill: str) -> tuple[str, ...]:
    """Skills whose packs may top up a thin exam pool for `skill` (curated)."""
    return RELATED_SKILLS.get(skill, ())


def exam_pool(packs: list, skill: str) -> tuple[list, list]:
    """Challenges available to a skill's exam: `(own, related)`.

    `own` is every challenge from packs of `skill`; `related` is the pool from
    related skills' packs (RELATED_SKILLS order), consulted only when `own` is
    thinner than EXAM_SIZE.
    """
    by_skill: dict[str, list] = {}
    for p in packs:
        by_skill.setdefault(getattr(p, "skill", None) or p.id, []).extend(p.challenges)
    own = by_skill.get(skill, [])
    related: list = []
    for rel in related_skills(skill):
        related.extend(by_skill.get(rel, []))
    return own, related


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
    own, related = exam_pool(packs, skill)
    if not own:
        return None
    rng = rng or random.Random()
    current = int(progress.get("certifications", {}).get(skill, {}).get("level", 0))
    target = _target_level(own, current)

    # Weight toward the target difficulty so the exam actually tests that tier,
    # but fall back to the full pool if a tier is thin.
    pool = [c for c in own if getattr(c, "difficulty", 1) == target] or own
    picked = rng.sample(pool, min(size, len(pool)))
    # A mixed exam: top up with a spread of other difficulties if room remains.
    remaining = [c for c in own if c not in picked]
    while len(picked) < size and remaining:
        picked.append(remaining.pop(rng.randrange(len(remaining))))

    # Cross-pack pools: thin skills (< `size` own challenges) top up from
    # related skills' packs. Own challenges always come first; related fill
    # prefers the target tier so the exam stays calibrated at the graded level.
    if len(picked) < size and related:
        rest = [c for c in related if c not in picked]
        near = [c for c in rest if getattr(c, "difficulty", 1) == target]
        far = [c for c in rest if getattr(c, "difficulty", 1) != target]
        rng.shuffle(near)
        rng.shuffle(far)
        picked.extend((near + far)[: size - len(picked)])
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
    names = sorted({getattr(p, "skill", None) or p.id for p in packs})
    out: list[dict[str, Any]] = []
    for skill in names:
        pool_own, pool_rel = exam_pool(packs, skill)
        if not pool_own:
            continue
        max_d = max((getattr(c, "difficulty", 1) for c in pool_own), default=1)
        topup = min(EXAM_SIZE - len(pool_own), len(pool_rel)) if len(pool_own) < EXAM_SIZE else 0
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
                "questions": len(pool_own) + topup,
                "topup": topup,
                "related": list(related_skills(skill)),
            }
        )
    return out
