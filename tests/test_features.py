"""Feature tests for P7-P10 learning engine, social, and platform features.

Run with:  pytest tests/
Isolated: progress writes go to a temp dir (see conftest.py).
"""

from __future__ import annotations

from skillplay.core import (
    achievements,
    engine,
    goals,
    leaderboard_server,
    registry,
    share,
    telemetry,
)
from skillplay.core import progress as pm
from skillplay.core.validators import validate


def _progress_with_sql_done(packs, prog):
    sql_ids = {c.id for p in packs if p.skill == "sql" for c in p.challenges}
    prog["skills"].setdefault(
        "sql", {"xp": 9999, "level": 10, "completed_ids": [], "attempts": 0, "correct": 0}
    )
    prog["skills"]["sql"]["completed_ids"] = list(sql_ids)
    return prog


def test_mistake_taxonomy_syntax(sql_pack):
    ch = sql_pack.challenges[0]
    r = validate(ch, "SELEC * FROM users")
    assert not r.correct
    assert engine.classify_mistake(ch, r) == "syntax"


def test_mistake_taxonomy_logic(sql_pack):
    ch = sql_pack.challenges[1]
    r = validate(ch, "SELECT name FROM users WHERE age > 100")
    assert not r.correct
    assert engine.classify_mistake(ch, r) == "logic"


def test_select_mixed_spans_skills(packs):
    prog = pm.default_progress()
    chosen = engine.select_mixed(packs, prog, 10)
    skills = {c.skill for c in chosen}
    assert len(skills) >= 2


def test_finalize_mixed_per_skill_and_daily(packs):
    prog = pm.default_progress()
    chosen = engine.select_mixed(packs, prog, 6)
    s = engine.Session("mixed", chosen, daily=True)
    # grade them all correct
    for i, ch in enumerate(chosen):
        s.index = i
        res = engine.submit(s, _reference(ch), prog, allow_retry=False)
        s.results.append(res)
    before = prog["total_xp"]
    engine.finalize(s, prog)
    assert prog["total_xp"] > before
    # per-skill XP attributed
    assert any(sk.get("xp", 0) > 0 for sk in prog["skills"].values())
    # daily challenge recorded
    assert prog["daily"]["dates"]


def _reference(ch):
    mode = ch.validation.get("mode")
    if mode == "sql_result":
        return ch.answer["reference_sql"]
    if mode == "exact":
        return ch.answer["value"]
    if mode == "regex_tester":
        return ch.answer["value"]
    if mode == "multiple_choice":
        return str(ch.validation["answer_id"])
    if mode == "test_cases":
        return ch.answer["reference_code"]
    if mode == "freeform":
        return ch.answer["reference_code"]
    raise AssertionError(mode)


def test_achievements_awarded(packs):
    prog = pm.default_progress()
    prog = _progress_with_sql_done(packs, prog)
    prog["streak"] = {"current": 7, "longest": 7, "last_played_date": ""}
    prog["total_xp"] = 150
    achievements.award(prog)
    assert "first_blood" in prog["achievements"]
    assert "pack_complete" in prog["achievements"]
    assert "streak_7" in prog["achievements"]


def test_goals_refresh(packs):
    prog = pm.default_progress()
    prog = _progress_with_sql_done(packs, prog)
    goals.refresh(prog)
    assert "sql-in-7" in prog["goals"]
    assert prog["goals"]["sql-in-7"]["done"] is True
    statuses = goals.status(prog)
    sql_goal = next(g for g in statuses if g["id"] == "sql-in-7")
    assert sql_goal["done"]


def test_session_snapshot_roundtrip(packs):
    prog = pm.default_progress()
    s = engine.Session("sql", engine.select_challenges(packs[0], prog, 4))
    snap = engine.snapshot(s)
    restored = engine.resume_session(snap, packs)
    assert restored is not None
    assert [c.id for c in restored.challenges] == snap["challenge_ids"]


def test_telemetry_local_only(packs):
    prog = pm.default_progress()
    s = engine.Session("sql", [packs[0].challenges[0]])
    r = engine.submit(s, "totally wrong", prog, allow_retry=False)
    assert not r.correct
    telemetry.record(prog, s)
    assert prog["telemetry"]  # some skill recorded
    assert next(iter(prog["telemetry"].values()))["samples"] >= 1


def test_leaderboard_server_boards(tmp_path):
    db = str(tmp_path / "lb.json")
    leaderboard_server.add_score(db, "alice", 120)
    leaderboard_server.add_score(db, "bob", 200)
    boards = leaderboard_server.boards(db)
    assert boards["all_time"][0]["name"] == "bob"
    assert len(boards["weekly"]) >= 1


def test_registry_install_local(tmp_path, packs):
    from skillplay.core import loader

    pack_dir = loader.BUILTIN_PACKS / "git-basics"
    registry.USER_PACKS = tmp_path / "packs"
    registry.REGISTRY_FILE = registry.USER_PACKS / ".registry.json"
    name = registry.install(str(pack_dir))
    assert (registry.USER_PACKS / name / "pack.yaml").is_file()
    assert name in registry.list_installed()


def test_share_outputs():
    prog = pm.default_progress()
    prog["total_xp"] = 42
    md = share.markdown_snippet(prog)
    assert "Total XP" in md
    svg = share.svg_card(prog)
    assert svg.startswith("<svg")
    assert "42" in svg


def test_i18n_fallback():
    from skillplay.core import i18n

    i18n.set_language("es")
    assert i18n.t("stats") == "Estadísticas"
    i18n.set_language("en")
    assert i18n.t("stats") == "Stats"
    i18n.set_language("nope")
    assert i18n.t("stats") == "Stats"
