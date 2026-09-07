"""Unit tests for validators, engine, and pack validation.

Run with:  pytest tests/
Isolated: progress writes go to a temp dir (see conftest.py).
"""

from __future__ import annotations

import time

from skillplay.core import engine, loader, validators
from skillplay.core import progress as pm
from skillplay.core.schema import validate_pack


def _ref(ch):
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
    raise AssertionError(f"unknown mode {mode}")


def test_all_packs_self_validate(packs):
    for pk in packs:
        for ch in pk.challenges:
            if ch.validation.get(
                "mode"
            ) == "test_cases" and not validators.test_cases_runtime_available(
                ch.validation.get("lang", "python")
            ):
                # Skip code challenges whose runtime (e.g. node) isn't installed.
                continue
            r = validators.validate(ch, _ref(ch))
            assert r.correct, f"{ch.id}: {r.detail}"


def test_wrong_sql_rejected(sql_pack):
    ch = sql_pack.challenges[1]
    r = validators.validate(ch, "SELECT name FROM users WHERE age > 100")
    assert not r.correct


def test_multi_statement_rejected(sql_pack):
    ch = sql_pack.challenges[0]
    r = validators.validate(ch, "SELECT * FROM users; DROP TABLE users")
    assert not r.correct
    assert "single SQL statement" in r.detail


def test_write_keyword_rejected(sql_pack):
    ch = sql_pack.challenges[0]
    r = validators.validate(ch, "DELETE FROM users")
    assert not r.correct
    assert "not allowed" in r.detail


def test_runaway_query_aborts(sql_pack):
    ch = sql_pack.challenges[0]
    bomb = (
        "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c) "
        "SELECT x FROM c LIMIT 100000000"
    )
    t0 = time.time()
    r = validators.validate(ch, bomb)
    elapsed = time.time() - t0
    assert not r.correct
    assert elapsed < 5.0, f"runaway query not aborted in time ({elapsed:.1f}s)"


def test_multiple_choice(git_pack):
    mc = next(c for c in git_pack.challenges if c.validation.get("mode") == "multiple_choice")
    r = validators.validate(mc, str(mc.validation["answer_id"]))
    assert r.correct
    wrong = next(o["id"] for o in mc.options if o["id"] != mc.validation["answer_id"])
    assert not validators.validate(mc, wrong).correct


def test_regex(regex_pack):
    ch = regex_pack.challenges[0]
    assert validators.validate(ch, ch.answer["value"]).correct


def test_validate_pack_reports_no_errors(packs):
    for pk in packs:
        errors, _ = validate_pack(pk, strict=False)
        assert errors == [], f"{pk.id} errors: {errors}"


def test_due_today_counts_all_when_fresh(packs):
    from skillplay.core import engine as eng

    prog = pm.default_progress()
    total = sum(len(p.challenges) for p in packs)
    assert eng.count_due_today(packs, prog) == total
    due = eng.select_due_today(packs, prog, 100)
    assert len(due) == total
    assert all(ch.srs_reason for ch in due)


def test_adaptive_order_returns_full_pack(sql_pack):
    from skillplay.core import engine as eng

    prog = pm.default_progress()
    order = eng.adaptive_order(sql_pack, prog)
    assert len(order) == len(sql_pack.challenges)
    # No duplicate ids in the ordered list.
    assert len({c.id for c in order}) == len(order)


def test_goals_cover_new_packs():
    from skillplay.core import goals

    ids = {g["id"] for g in goals.GOALS}
    for expected in ("css-basics", "shell-basics", "http-rest", "data-structures", "algorithms"):
        assert expected in ids, f"missing goal for {expected}"


def test_validate_pack_detects_duplicate_prompt(tmp_path):
    d = tmp_path / "bad-pack"
    (d / "challenges").mkdir(parents=True)
    (d / "pack.yaml").write_text(
        "id: bad\nname: Bad\nversion: 0.1.0\nskill: bad\n", encoding="utf-8"
    )
    (d / "challenges" / "a.yaml").write_text(
        "id: bad-a\ntype: exact\nprompt: Same\nanswer:\n  value: x\nvalidation:\n  mode: exact\n",
        encoding="utf-8",
    )
    (d / "challenges" / "b.yaml").write_text(
        "id: bad-b\ntype: exact\nprompt: Same\nanswer:\n  value: y\nvalidation:\n  mode: exact\n",
        encoding="utf-8",
    )
    pk = loader.load_pack(d)
    errors, _ = validate_pack(pk)
    assert any("duplicate prompt" in e for e in errors)


def test_session_weighting_returns_within_bounds(sql_pack):
    prog = pm.default_progress()
    chosen = engine.select_challenges(sql_pack, prog, 5)
    assert len(chosen) <= 5
    assert len({c.id for c in chosen}) == len(chosen)  # no duplicates


def test_retry_gives_half_xp(sql_pack):
    prog = pm.default_progress()
    s = engine.Session("sql", engine.select_challenges(sql_pack, prog, 8))
    ch0 = s.current
    r1 = engine.submit(s, "totally wrong", prog, allow_retry=True)
    assert r1.retried and not r1.correct
    r2 = engine.submit(s, ch0.answer["reference_sql"], prog, allow_retry=True)
    assert r2.correct and r2.xp_gained == ch0.xp // 2


def test_srs_reason_new_and_review():
    from skillplay.core import engine as eng

    prog = pm.default_progress()
    ch = type("C", (), {"id": "x1", "skill": "python"})()
    assert eng.reason_for_challenge(prog, ch) == "New — never seen before"
    prog["challenges"]["x1"] = {"seen": 3, "correct": 1, "box": 3, "next_due": "2026-01-01"}
    prog.setdefault("mistakes", {})["x1"] = {"syntax": 2, "logic": 0, "off_by_one": 0}
    reason = eng.reason_for_challenge(prog, ch)
    assert "box 3" in reason
    assert "syntax" in reason


def test_weakest_mistake_type_targets_gaps():
    from skillplay.core import engine as eng

    prog = pm.default_progress()
    prog.setdefault("mistakes", {})["c1"] = {"syntax": 5, "logic": 1, "off_by_one": 0}
    assert eng._weakest_mistake_type(prog) == "syntax"


def test_new_pack_scaffold(tmp_path):
    from argparse import Namespace

    from skillplay.core import cli

    rc = cli.cmd_new_pack(Namespace(name="demo", skill="demo", dir=str(tmp_path)))
    assert rc == 0
    pack_dir = tmp_path / "demo"
    assert (pack_dir / "pack.yaml").is_file()
    assert (pack_dir / "challenges" / "01-example.yaml").is_file()


def test_fix_suggestions_emitted(tmp_path):

    from skillplay.core import cli, loader

    d = tmp_path / "fp"
    (d / "challenges").mkdir(parents=True)
    (d / "pack.yaml").write_text("id: fp\nname: FP\nversion: 0.1.0\nskill: fp\n", encoding="utf-8")
    (d / "challenges" / "a.yaml").write_text(
        "id: fp-a\ntype: exact\nprompt: P\nanswer:\n  value: x\nvalidation:\n  mode: exact\n",
        encoding="utf-8",
    )
    pk = loader.load_pack(d)
    sug = cli._fix_suggestions(pk, [], ["[fp-a] missing explanation"])
    assert any("explanation" in s for s in sug)
