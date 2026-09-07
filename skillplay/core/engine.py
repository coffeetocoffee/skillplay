"""Session engine: challenge selection, scoring, SRS, learning signals."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from datetime import date

from . import progress as progress_mod
from . import skillgraph
from . import streak as streak_mod
from .validators import Result, validate

# Mistake taxonomy categories (P7). SRS weights can drill by these types.
MISTAKE_TYPES = ("syntax", "logic", "off_by_one")

MISTAKE_LABELS = {"syntax": "syntax", "logic": "logic", "off_by_one": "off-by-one"}

# W4: at/above this response time a *correct* answer counts as hesitant recall.
_HESITANT_MS = 15_000


@dataclass
class PlayResult:
    challenge_id: str
    correct: bool
    detail: str = ""
    xp_gained: int = 0
    retried: bool = False
    skill: str = ""
    mistake_type: str = ""


@dataclass
class Session:
    skill: str
    challenges: list = field(default_factory=list)
    index: int = 0
    combo: int = 0
    best_combo: int = 0
    correct_count: int = 0
    xp_gained: int = 0
    results: list[PlayResult] = field(default_factory=list)
    retried_ids: set[str] = field(default_factory=set)
    first_tries: dict[str, bool] = field(default_factory=dict)
    daily: bool = False
    attempts: list = field(default_factory=list)
    # V6: mastery exam metadata. `exam_skill` is set when this session is a
    # graded exam; `exam_target` is the level being attempted (difficulty tier).
    exam_skill: str | None = None
    exam_target: int = 0
    exam_result: dict | None = None

    @property
    def done(self) -> bool:
        return self.index >= len(self.challenges)

    @property
    def current(self):
        return self.challenges[self.index] if not self.done else None


def classify_mistake(ch, res: Result) -> str:
    """Best-effort classification of a wrong answer into a mistake type.

    Taxonomy: `syntax` (code won't parse/run or uses an undefined name),
    `logic` (runs but produces the wrong result), `off_by_one` (off by exactly
    one row for SQL). For `test_cases` challenges the validator's `detail` string
    carries the exception type, so we can tell a crash from a wrong-but-runnable
    answer — previously every code failure was lumped into `logic`, which blinded
    the SRS mistake-type targeting and the adaptive model's `weak_share` feature.
    """
    detail = (res.detail or "").lower()
    if res.meta.get("user_rows") is not None and res.meta.get("ref_rows") is not None:
        diff = abs(res.meta["user_rows"] - res.meta["ref_rows"])
        if diff == 1:
            return "off_by_one"
    if "sql error" in detail or "invalid regex" in detail or detail.startswith("invalid"):
        return "syntax"
    if ch.validation.get("mode") == "test_cases":
        return _classify_code_mistake(detail)
    return "logic"


def _classify_code_mistake(detail: str) -> str:
    """Classify a `test_cases` failure from its validator detail string.

    Python runner: ``"error on <args>: <ExcType>: <msg>"``.
    JS runner:     ``"error: <message>"``.
    """
    d = detail.lower()
    if "no function named" in d:
        return "syntax"
    # Parse/link errors: code never successfully ran.
    syntax_markers = (
        "syntaxerror",
        "indentationerror",
        "referenceerror",
        "is not defined",
        "is not a function",
        "unexpected token",
        "unexpected end",
        "unexpected character",
        "missing )",
        "missing ]",
        "missing }",
    )
    if any(m in d for m in syntax_markers):
        return "syntax"
    if "error" in d or "traceback" in d:
        # A runtime exception (TypeError, IndexError, ...) — code ran but the
        # logic was wrong.
        return "logic"
    return "logic"


def _record_mistake(progress: dict, challenge_id: str, mtype: str) -> None:
    mistakes = progress.setdefault("mistakes", {})
    rec = mistakes.setdefault(challenge_id, {t: 0 for t in MISTAKE_TYPES})
    for t in MISTAKE_TYPES:
        rec.setdefault(t, 0)
    rec[mtype] = rec.get(mtype, 0) + 1


def _challenge_weight(progress: dict, ch, rolling_accuracy: float | None = None) -> int:
    """Higher weight == more likely to be scheduled.

    Leitner SRS: lower box (less-mastered) -> higher weight.
    Mistakes: more wrong attempts -> higher weight for review.
    Adaptive difficulty (P7): if the player is doing well, tilt toward
    harder challenges; if struggling, toward easier ones.
    """
    rec = progress["challenges"].get(ch.id, {})
    box = rec.get("box", 1)
    mistakes = max(0, rec.get("seen", 0) - rec.get("correct", 0))
    mistake_types = progress.get("mistakes", {}).get(ch.id, {})
    mistake_total = sum(mistake_types.get(t, 0) for t in MISTAKE_TYPES)
    weight = (6 - box) + mistakes * 2 + mistake_total * 1 + 1
    # A3: target weak mistake types. Drill the challenge's dominant mistake
    # type harder, and add an extra nudge when it matches the player's
    # globally weakest type so sessions self-correct the biggest gaps.
    dom = _dominant_mistake_type(progress, ch.id)
    if dom is not None:
        weight += mistake_types.get(dom, 0) * 2
        if dom == _weakest_mistake_type(progress):
            weight += 3
    if rolling_accuracy is not None:
        difficulty = getattr(ch, "difficulty", 1)
        if rolling_accuracy >= 0.8:
            weight += difficulty  # strong player -> harder
        elif rolling_accuracy <= 0.5:
            weight += 6 - difficulty  # struggling -> easier
    return weight


def _dominant_mistake_type(progress: dict, challenge_id: str) -> str | None:
    mt = progress.get("mistakes", {}).get(challenge_id, {})
    if not any(mt.get(t, 0) for t in MISTAKE_TYPES):
        return None
    return max(MISTAKE_TYPES, key=lambda t: mt.get(t, 0))


def _weakest_mistake_type(progress: dict) -> str | None:
    """Globally weakest mistake type = the one the player makes most often."""
    totals = {t: 0 for t in MISTAKE_TYPES}
    for rec in progress.get("mistakes", {}).values():
        for t in MISTAKE_TYPES:
            totals[t] += rec.get(t, 0)
    best = max(MISTAKE_TYPES, key=lambda t: totals[t])
    return best if totals[best] > 0 else None


def _attempt_features(progress: dict, ch, latency_ms: int | None = None) -> dict[str, float]:
    """Feature vector for a single challenge, captured *before* grading an
    attempt. Used by the Section E adaptive model (core.adaptive) to predict
    the probability of a correct answer. Kept pure and dependency-free.

    Features (all in roughly [0, 1]):
      - difficulty: difficulty normalized to 0..1
      - box:       SRS box (1 new .. 5 mastered) normalized
      - mistakes:  total mistake count for this challenge (capped)
      - weak_share: share of mistakes that are the dominant type
      - rolling:   recent per-skill accuracy (0.5 if unknown)
      - seen:      how often the challenge has been attempted (capped)
      - latency:   response time for this attempt (G7: now a model feature)
    """
    rec = progress["challenges"].get(ch.id, {})
    box = rec.get("box", 1)
    mistakes = progress.get("mistakes", {}).get(ch.id, {})
    mistake_total = sum(mistakes.get(t, 0) for t in MISTAKE_TYPES)
    weak_share = 0.0
    if mistake_total > 0:
        dom = _dominant_mistake_type(progress, ch.id)
        if dom:
            weak_share = min(1.0, mistakes.get(dom, 0) / mistake_total)
    rolling = _rolling_accuracy(progress, ch.skill)
    if rolling is None:
        rolling = 0.5
    # Latency: unknown -> neutral 0.5; otherwise normalized (20s cap). Slow
    # responses can signal struggle, so the model finally uses the signal it
    # collects (G7).
    if latency_ms is None:
        latency = 0.5
    else:
        latency = min(1.0, max(0.0, latency_ms) / 20000.0)
    return {
        "difficulty": (getattr(ch, "difficulty", 1) - 1) / 4.0,
        "box": (box - 1) / 4.0,
        "mistakes": min(1.0, mistake_total / 10.0),
        "weak_share": weak_share,
        "rolling": max(0.0, min(1.0, rolling)),
        "seen": min(1.0, rec.get("seen", 0) / 10.0),
        "latency": latency,
    }


def reason_for_challenge(progress: dict, ch) -> str:
    """A3: explain *why* a card was scheduled, shown to the player in-session."""
    rec = progress["challenges"].get(ch.id, {})
    seen = rec.get("seen", 0)
    box = rec.get("box", 1)
    if seen == 0:
        return "New — never seen before"
    mt = progress.get("mistakes", {}).get(ch.id, {})
    weak = [t for t in MISTAKE_TYPES if mt.get(t, 0) > 0]
    extras = []
    if weak:
        dom = max(weak, key=lambda t: mt[t])
        extras.append(f"weak on {MISTAKE_LABELS[dom]} ({mt[dom]})")
    reason = f"Due for review (box {box})"
    if extras:
        reason += " — " + "; ".join(extras)
    return reason


def _rolling_accuracy(progress: dict, skill: str) -> float | None:
    """Recent accuracy for a skill from history (P7 adaptive difficulty)."""
    hist = progress.get("accuracy_history", {})
    if not hist:
        return None
    recent = list(hist.values())[-7:]
    if not recent:
        return None
    return sum(recent) / len(recent)


def select_challenges(pack, progress: dict, session_size: int) -> list:
    skill = getattr(pack, "skill", None)
    rolling = _rolling_accuracy(progress, skill) if skill else None
    return _select_from(pack.challenges, progress, session_size, rolling)


def select_mixed(packs: list, progress: dict, session_size: int) -> list:
    """Interleaving (P7): pool challenges across all packs, weighted globally."""
    all_ch = [ch for p in packs for ch in p.challenges]
    rolling = None
    return _select_from(all_ch, progress, session_size, rolling)


def _is_due(progress: dict, ch, today: str) -> bool:
    """A card is due if never seen, or its SRS next_due is today or earlier."""
    rec = progress["challenges"].get(ch.id, {})
    if rec.get("seen", 0) == 0:
        return True
    return rec.get("next_due", "") <= today


def count_due_today(packs: list, progress: dict) -> int:
    """B: how many cards across all skills are due right now (the habit loop)."""
    today = progress_mod.today_str()
    return sum(1 for p in packs for ch in p.challenges if _is_due(progress, ch, today))


def select_due_today(packs: list, progress: dict, session_size: int) -> list:
    """B: pull only SRS-due (or new) cards across *all* skills, weakest-first."""
    today = progress_mod.today_str()
    due = [ch for p in packs for ch in p.challenges if _is_due(progress, ch, today)]
    due.sort(key=lambda c: _challenge_weight(progress, c), reverse=True)
    chosen = due[:session_size]
    for ch in chosen:
        ch.srs_reason = reason_for_challenge(progress, ch)
    return chosen


def _gate_prerequisites(challenges: list, progress: dict) -> list:
    """V4: if this set declares any prerequisites, only schedule the unlocked
    ones (soft curriculum). Packs without prerequisites are untouched. If gating
    would leave nothing, fall back to the original set so a session is still
    playable."""
    if not any(getattr(c, "prerequisites", None) for c in challenges):
        return challenges
    unlocked = [c for c in challenges if skillgraph.is_unlocked(progress, c)]
    return unlocked or challenges


def adaptive_order(pack, progress: dict, limit: int | None = None) -> list:
    """B: order a pack's challenges weakest-first so a 'path' session self-adjusts
    to the player's performance (low SRS box + frequent mistake types first)."""
    chs = sorted(pack.challenges, key=lambda c: _challenge_weight(progress, c), reverse=True)
    return chs[:limit] if limit else chs


def _select_from(challenges: list, progress: dict, session_size: int, rolling) -> list:
    today = progress_mod.today_str()
    due = []
    for ch in challenges:
        rec = progress["challenges"].get(ch.id, {})
        next_due = rec.get("next_due", "")
        if next_due and next_due > today:
            continue
        due.append(ch)
    if not due:
        due = list(challenges)
    chosen = _weighted_sample(due, progress, session_size, rolling)
    for ch in chosen:
        ch.srs_reason = reason_for_challenge(progress, ch)
    return chosen


def _weighted_sample(pool: list, progress: dict, session_size: int, rolling=None) -> list:
    """Weighted sample without replacement up to `session_size` (higher weight =
    more likely). Returns an empty list when the pool is empty."""
    if not pool:
        return []
    weights = [_challenge_weight(progress, ch, rolling) for ch in pool]
    chosen: list = []
    pp, pw = list(pool), list(weights)
    while pp and len(chosen) < session_size:
        pick = random.choices(pp, weights=pw, k=1)[0]
        idx = pp.index(pick)
        chosen.append(pp.pop(idx))
        pw.pop(idx)
    return chosen


def select_path(packs: list, progress: dict, session_size: int) -> list:
    """V4: a learning-path session — the next unlockable frontier across `packs`.

    Picks from challenges that are unlocked but not yet mastered (the frontier),
    preferring SRS-due cards within it; falls back to the whole frontier (so you
    can always make forward progress) and finally to everything if nothing is left
    to master. This is the "walk the next unlockable frontier" selection that
    replaces weakest-box-only ordering for curriculum-style content.
    """
    all_ch = [c for p in packs for c in p.challenges]
    fr = [c for c in all_ch if skillgraph.in_frontier(progress, c)]
    if not fr:
        # Nothing left to master: relax the "mastered" filter so the path can
        # still review unlocked cards, and as a last resort allow anything.
        fr = [c for c in all_ch if skillgraph.is_unlocked(progress, c)] or all_ch
    if not fr:
        return []
    today = progress_mod.today_str()
    due = [c for c in fr if _is_due(progress, c, today)]
    pool = due or fr
    chosen = _weighted_sample(pool, progress, session_size)
    for ch in chosen:
        missing = skillgraph.missing_prerequisites(progress, ch)
        if missing:
            ch.srs_reason = "New on the frontier"
        else:
            ch.srs_reason = reason_for_challenge(progress, ch)
    return chosen


def combo_multiplier(combo: int) -> float:
    if combo >= 5:
        return 1.5
    if combo >= 3:
        return 1.2
    return 1.0


def submit(
    session: Session, user_input: str, progress: dict, allow_retry: bool = True
) -> PlayResult:
    ch = session.current
    res: Result = validate(ch, user_input)
    can_retry = allow_retry and ch.id not in session.retried_ids
    first_try = ch.id not in session.first_tries
    rolling = _rolling_accuracy(progress, ch.skill)
    started = getattr(session, "_challenge_started", None)
    latency_ms = int((time.monotonic() - started) * 1000) if started else 0
    feats = _attempt_features(progress, ch, latency_ms)
    mtype = None
    if res.correct:
        if first_try:
            session.first_tries[ch.id] = True
        session.combo += 1
        session.best_combo = max(session.best_combo, session.combo)
        session.correct_count += 1
        mult = combo_multiplier(session.combo)
        xp = int(ch.xp * mult)
        if ch.id in session.retried_ids:
            xp = xp // 2
        session.xp_gained += xp
        _advance_box(progress, ch.id, correct=True, latency_ms=latency_ms)
        # V2: keep the player's own correct code so a capstone can assemble it
        # into a real portfolio artifact (fallback to reference when absent).
        if ch.validation.get("mode") in ("test_cases", "freeform"):
            progress.setdefault("solutions", {})[ch.id] = user_input
        result = PlayResult(ch.id, True, res.detail, xp, skill=ch.skill)
    elif can_retry:
        if first_try:
            session.first_tries[ch.id] = False
        session.retried_ids.add(ch.id)
        mtype = classify_mistake(ch, res)
        _record_mistake(progress, ch.id, mtype)
        result = PlayResult(
            ch.id, False, res.detail, retried=True, skill=ch.skill, mistake_type=mtype
        )
    else:
        if first_try:
            session.first_tries[ch.id] = False
        session.combo = 0
        _advance_box(progress, ch.id, correct=False, latency_ms=latency_ms)
        mtype = classify_mistake(ch, res)
        _record_mistake(progress, ch.id, mtype)
        result = PlayResult(ch.id, False, res.detail, skill=ch.skill, mistake_type=mtype)
    # Section E: append a per-attempt record for the local adaptive model.
    # Persisted to disk only in `finalize` (engine invariant: disk on finalize).
    session.attempts.append(
        {
            "date": progress_mod.today_str(),
            "skill": ch.skill,
            "challenge_id": ch.id,
            "difficulty": getattr(ch, "difficulty", 1),
            "correct": bool(res.correct),
            "mistake_type": mtype or "",
            "latency_ms": latency_ms,
            "rolling_accuracy": rolling,
            "feats": feats,
        }
    )
    return result


def finalize(session: Session, progress: dict) -> None:
    from . import achievements as ach_mod
    from . import goals as goals_mod

    # Per-skill XP / attempts / completion (supports interleaved sessions).
    skills: dict[str, dict] = {}
    for ch in session.challenges:
        rec = skills.setdefault(
            ch.skill,
            {"xp": 0, "level": 1, "completed_ids": [], "attempts": 0, "correct": 0},
        )
        rec["attempts"] += 1

    for res in session.results:
        rec = skills.setdefault(
            res.skill,
            {"xp": 0, "level": 1, "completed_ids": [], "attempts": 0, "correct": 0},
        )
        if res.correct:
            rec["xp"] += res.xp_gained
            rec["correct"] += 1
            if res.challenge_id not in rec["completed_ids"]:
                rec["completed_ids"].append(res.challenge_id)

    progress["total_xp"] += session.xp_gained
    today = progress_mod.today_str()
    hist = progress.get("xp_history", {})
    hist[today] = hist.get(today, 0) + session.xp_gained
    total = len(session.challenges)
    acc = (session.correct_count / total) if total else 0
    progress.setdefault("accuracy_history", {})[today] = acc

    for skill, rec in skills.items():
        sk = progress["skills"].setdefault(
            skill, {"xp": 0, "level": 1, "completed_ids": [], "attempts": 0, "correct": 0}
        )
        sk["xp"] += rec["xp"]
        sk["level"] = progress_mod.level_for_xp(sk["xp"])
        sk["attempts"] += rec["attempts"]
        sk["correct"] += rec["correct"]
        for cid in rec["completed_ids"]:
            if cid not in sk["completed_ids"]:
                sk["completed_ids"].append(cid)

    if session.daily:
        daily = progress.setdefault("daily", {"dates": [], "last_done": ""})
        if today not in daily["dates"]:
            daily["dates"].append(today)
        daily["last_done"] = today

    ach_mod.award(progress)
    goals_mod.refresh(progress)
    from . import telemetry as telemetry_mod

    telemetry_mod.record(progress, session)

    # Section E: persist per-attempt telemetry and (re)train the local adaptive
    # model. Wrapped so a model hiccup can never break a session save.
    try:
        from . import adaptive as adaptive_mod

        if session.attempts:
            attempts = progress.setdefault("attempts", [])
            attempts.extend(session.attempts)
            if len(attempts) > 5000:
                del attempts[:-5000]
            adaptive_mod.retrain_if_needed(progress)
    except Exception:
        pass

    streak_mod.update_streak(progress["streak"], today)
    progress_mod.save(progress)


def skip_current(session: Session) -> None:
    """Advance past the current challenge without grading it (no XP, no SRS)."""
    if session.current is not None:
        session.index += 1


def daily_challenge(packs: list, today: str | None = None) -> object | None:
    """Deterministically pick one challenge for the given day across all packs."""
    today = today or progress_mod.today_str()
    all_challenges = [ch for p in packs for ch in p.challenges]
    if not all_challenges:
        return None
    rng = random.Random(today)
    return rng.choice(all_challenges)


def snapshot(session: Session) -> dict:
    """Serialize enough of a session to resume it later (P9)."""
    return {
        "skill": session.skill,
        "daily": session.daily,
        "index": session.index,
        "combo": session.combo,
        "best_combo": session.best_combo,
        "correct_count": session.correct_count,
        "xp_gained": session.xp_gained,
        "retried_ids": list(session.retried_ids),
        "results": [
            {
                "challenge_id": r.challenge_id,
                "correct": r.correct,
                "detail": r.detail,
                "xp_gained": r.xp_gained,
                "retried": r.retried,
                "skill": r.skill,
                "mistake_type": r.mistake_type,
            }
            for r in session.results
        ],
        "challenge_ids": [ch.id for ch in session.challenges],
    }


def resume_session(snapshot: dict, packs: list) -> Session | None:
    """Rebuild a Session from a snapshot, looking up live challenge objects."""
    by_id: dict[str, object] = {ch.id: ch for p in packs for ch in p.challenges}
    challenges = [by_id[cid] for cid in snapshot["challenge_ids"] if cid in by_id]
    if not challenges:
        return None
    session = Session(
        snapshot.get("skill", "mixed"), challenges, daily=snapshot.get("daily", False)
    )
    session.index = snapshot.get("index", 0)
    session.combo = snapshot.get("combo", 0)
    session.best_combo = snapshot.get("best_combo", 0)
    session.correct_count = snapshot.get("correct_count", 0)
    session.xp_gained = snapshot.get("xp_gained", 0)
    session.retried_ids = set(snapshot.get("retried_ids", []))
    session.results = [
        PlayResult(
            r["challenge_id"],
            r["correct"],
            r.get("detail", ""),
            r.get("xp_gained", 0),
            r.get("retried", False),
            r.get("skill", ""),
            r.get("mistake_type", ""),
        )
        for r in snapshot.get("results", [])
    ]
    return session


def _advance_box(
    progress: dict, challenge_id: str, correct: bool, latency_ms: int | None = None
) -> None:
    from . import hlr

    rec = progress["challenges"].setdefault(
        challenge_id, {"seen": 0, "correct": 0, "box": 1, "next_due": progress_mod.today_str()}
    )
    today = progress_mod.today_str()
    prev_seen = rec.get("seen", 0)
    rec["seen"] = prev_seen + 1
    if correct:
        rec["correct"] = rec.get("correct", 0) + 1
        rec["box"] = min(5, rec.get("box", 1) + 1)
        # W4: a *hesitant* correct answer (slow response) is shaky recall —
        # cap the box at 3 so the card comes back soon until a fast recall
        # proves durable mastery. latency 0/None means "unknown" and is ignored.
        if latency_ms and latency_ms > _HESITANT_MS:
            rec["box"] = min(rec["box"], 3)
    else:
        rec["box"] = 1

    # V3: Half-life regression scheduler (W4). Learn per-card stability from the
    # elapsed delay since the last review + correctness + response latency, then
    # schedule the next review when predicted recall should fall to TARGET_RECALL.
    # `box` is still updated (above) for backward-compatible weighting/display.
    last = rec.get("last_review")
    dt = 0.0
    if last:
        try:
            dt = max(0.0, (date.today() - date.fromisoformat(last)).days)
        except ValueError:
            dt = 0.0
    rec["hl"] = hlr.update(rec.get("hl", 0.0), dt, correct, latency_ms)
    rec["last_review"] = today
    if prev_seen == 0:
        # First encounter: keep it due today so it can be reinforced immediately.
        rec["next_due"] = today
    else:
        rec["next_due"] = hlr.next_due_iso(rec["hl"], today)
