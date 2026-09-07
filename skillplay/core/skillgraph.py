"""V4 — Skill graph + prerequisites (W3): content as a DAG.

Until now selection was purely "weakest SRS box" (recognition drills). V4 adds a
dependency layer: each challenge may declare `prerequisites` (a list of other
challenge ids that must be *known* first). The graph lets selection walk the
**next unlockable frontier** — challenges whose prerequisites are satisfied but
that are not yet mastered — instead of just drilling the weakest card in
isolation. This turns packs into curricula: a learner advances through a skill in
a sensible order and only sees material once its prerequisites are in place.

All functions here are pure (no I/O, no outward exceptions) so they can be used
by the engine, the adaptive model, the TUI, and `validate-packs` alike.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .loader import Challenge, Pack

# A prerequisite is considered "known" once the player has answered it correctly
# at least this many times.
KNOW_THRESHOLD = 1
# A challenge drops out of the frontier (is "mastered" for path purposes) once
# its SRS box reaches this level — the scheduler believes it's durably retained.
MASTERED_BOX = 4


if TYPE_CHECKING:  # pragma: no cover - typing only
    pass


def known(progress: dict[str, Any], challenge_id: str) -> bool:
    """Has the player demonstrated this challenge at least once (correct > 0)?"""
    rec = progress.get("challenges", {}).get(challenge_id)
    if not rec:
        return False
    return rec.get("correct", 0) >= KNOW_THRESHOLD


def is_unlocked(progress: dict[str, Any], ch: Challenge) -> bool:
    """True when every prerequisite of `ch` is known (or it has none).

    A missing prerequisite id (shouldn't happen post-`validate_graph`) counts as
    *not* known, so an authoring error fails safe to "locked" rather than
    silently surfacing an impossible challenge.
    """
    prereqs = getattr(ch, "prerequisites", None) or []
    if not prereqs:
        return True
    return all(known(progress, pid) for pid in prereqs)


def is_mastered(progress: dict[str, Any], ch: Challenge) -> bool:
    rec = progress.get("challenges", {}).get(ch.id)
    if not rec:
        return False
    return rec.get("box", 1) >= MASTERED_BOX


def in_frontier(progress: dict[str, Any], ch: Challenge) -> bool:
    """A challenge belongs to the *next unlockable frontier* when it is unlocked
    but not yet mastered."""
    return is_unlocked(progress, ch) and not is_mastered(progress, ch)


def missing_prerequisites(progress: dict[str, Any], ch: Challenge) -> list[str]:
    """The subset of `ch`'s prerequisites the player has not yet learned."""
    return [pid for pid in (getattr(ch, "prerequisites", None) or []) if not known(progress, pid)]


def frontier(packs: list[Pack], progress: dict[str, Any]) -> list[Challenge]:
    """All challenges across `packs` that sit on the current unlockable frontier."""
    out: list[Challenge] = []
    for p in packs:
        out.extend(c for c in p.challenges if in_frontier(progress, c))
    return out


def _skill_of(pack: Pack) -> str:
    return getattr(pack, "skill", None) or getattr(pack, "id", "unknown")


def frontier_stats(packs: list[Pack], progress: dict[str, Any]) -> dict[str, dict[str, int]]:
    """Per-skill counts for the learning-path UI: totals plus how many challenges
    are unlocked / locked / mastered."""
    stats: dict[str, dict[str, int]] = {}
    for p in packs:
        skill = _skill_of(p)
        s = stats.setdefault(skill, {"total": 0, "unlocked": 0, "locked": 0, "mastered": 0})
        for c in p.challenges:
            s["total"] += 1
            if is_mastered(progress, c):
                s["mastered"] += 1
            elif is_unlocked(progress, c):
                s["unlocked"] += 1
            else:
                s["locked"] += 1
    return stats


def prerequisite_map(packs: list[Pack]) -> dict[str, Challenge]:
    """Global id -> Challenge map across all packs (ids are global)."""
    return {c.id: c for p in packs for c in p.challenges}


def _find_cycles(by_id: dict[str, Challenge]) -> list[list[str]]:
    """Return a list of prerequisite cycles (each a list of challenge ids forming
    a loop). A cycle would make part of the DAG unsatisfiable."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {cid: WHITE for cid in by_id}
    cycles: list[list[str]] = []

    def visit(start: str, node: str, stack: list[str]) -> None:
        color[node] = GRAY
        stack.append(node)
        for pid in by_id[node].prerequisites:
            if pid not in by_id:
                continue  # missing refs handled separately
            if color.get(pid, WHITE) == GRAY:
                # Found a back-edge: report the cycle from pid..node.
                if pid in stack:
                    idx = stack.index(pid)
                    cycles.append([*stack[idx:], pid])
            elif color.get(pid, WHITE) == WHITE:
                visit(start, pid, stack)
        stack.pop()
        color[node] = BLACK

    for cid in by_id:
        if color[cid] == WHITE:
            visit(cid, cid, [])
    return cycles


def validate_graph(packs: list[Pack]) -> tuple[list[str], list[str]]:
    """Cross-pack prerequisite checks for `validate-packs`.

    Returns `(errors, warnings)`:
      - error: a prerequisite id that references a non-existent challenge
      - error: a prerequisite cycle (DAG violated)
    Packs without prerequisites are unaffected.
    """
    errors: list[str] = []
    warnings: list[str] = []
    by_id = prerequisite_map(packs)
    for cid, ch in by_id.items():
        for pid in ch.prerequisites:
            if pid not in by_id:
                errors.append(f"[{cid}] prerequisite '{pid}' does not exist in any pack")
    for cyc in _find_cycles(by_id):
        errors.append("prerequisite cycle: " + " -> ".join(cyc))
    return errors, warnings


def reason_locked(progress: dict[str, Any], ch: Challenge) -> str:
    """Human-readable explanation of why a challenge is currently locked."""
    missing = missing_prerequisites(progress, ch)
    if not missing:
        return ""
    return "Locked — needs: " + ", ".join(missing)
