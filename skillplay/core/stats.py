"""Learning metrics (W6): per-skill *readiness* — a mastery score, not engagement.

Readiness blends three signals a learner actually cares about:
  - coverage:  share of the skill's challenges ever completed correctly
  - retention: share of the skill's challenges sitting in a strong SRS box (>= 3)
  - accuracy:  lifetime correct/attempt ratio for the skill

It answers "am I actually learning this skill?" instead of "how much XP do I
have?" — the missing learning metric the Stats screen only implied.
"""

from __future__ import annotations

# (threshold, label) pairs, checked high -> low.
LEVELS: tuple[tuple[int, str], ...] = (
    (90, "mastered"),
    (70, "proficient"),
    (40, "practicing"),
    (0, "learning"),
)

_STRONG_BOX = 3

_WEIGHTS = {"coverage": 0.40, "retention": 0.35, "accuracy": 0.25}


def readiness(progress: dict, packs: list) -> int:
    """0-100 mastery score for one skill, given the skill's pack(s).

    `packs` may hold several packs that share a skill (e.g. fix-bug +
    fix-bug-js for python). No data yet -> 0.
    """
    ids: list[str] = []
    for p in packs:
        ids.extend(ch.id for ch in p.challenges)
    total = len(ids)
    if total == 0:
        return 0
    skill = getattr(packs[0], "skill", None) or getattr(packs[0], "id", "")
    rec = progress.get("skills", {}).get(skill, {})

    completed = set(rec.get("completed_ids", [])) & set(ids)
    coverage = len(completed) / total

    ch_recs = progress.get("challenges", {})
    strong = sum(1 for cid in ids if ch_recs.get(cid, {}).get("box", 0) >= _STRONG_BOX)
    retention = strong / total

    attempts = rec.get("attempts", 0)
    accuracy = (rec.get("correct", 0) / attempts) if attempts else 0.0

    score = (
        _WEIGHTS["coverage"] * coverage
        + _WEIGHTS["retention"] * retention
        + _WEIGHTS["accuracy"] * accuracy
    )
    return round(score * 100)


def readiness_label(score: int) -> str:
    for threshold, label in LEVELS:
        if score >= threshold:
            return label
    return LEVELS[-1][1]


def readiness_all(progress: dict, packs: list) -> dict[str, int]:
    """Readiness per skill key, grouped across packs sharing a skill."""
    by_skill: dict[str, list] = {}
    for p in packs:
        by_skill.setdefault(getattr(p, "skill", None) or p.id, []).append(p)
    return {skill: readiness(progress, group) for skill, group in sorted(by_skill.items())}


def half_life_for_skill(progress: dict, skill: str, packs: list) -> float:
    """V3: average learned half-life (days) across a skill's challenges.

    A higher value means the scheduler believes the skill is retained longer, so
    reviews are spaced further apart. 0.0 = no HLR data yet for that skill."""
    ids: list[str] = []
    for p in packs:
        if (getattr(p, "skill", None) or p.id) == skill:
            ids.extend(c.id for c in p.challenges)
    hls = [progress.get("challenges", {}).get(cid, {}).get("hl") for cid in ids]
    hls = [h for h in hls if h]
    if not hls:
        return 0.0
    return round(sum(hls) / len(hls), 2)
