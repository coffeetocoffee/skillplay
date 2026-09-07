"""Tests for V6 mastery exams (W6 learning metric) + cross-pack top-up pools."""

from __future__ import annotations

import random

from skillplay.core import engine, exam, loader
from skillplay.core import progress as pm


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
    if mode in ("test_cases", "freeform"):
        return ch.answer["reference_code"]
    raise AssertionError(mode)


def _grade_all_correct(session, prog):
    for ch in list(session.challenges):
        res = engine.submit(session, _reference(ch), prog, allow_retry=False)
        session.results.append(res)
        session.index += 1


def test_build_exam_pulls_from_skill():
    packs = loader.load_all_packs()
    prog = pm.default_progress()
    sess = exam.build_exam("sql", prog, packs=packs, rng=random.Random(1))
    assert sess is not None
    assert sess.exam_skill == "sql"
    assert all(ch.skill == "sql" for ch in sess.challenges)
    # target level starts at 1 (current 0 + 1)
    assert sess.exam_target == 1


def test_exam_certifies_on_pass():
    packs = loader.load_all_packs()
    prog = pm.default_progress()
    sess = exam.build_exam("sql", prog, packs=packs, rng=random.Random(2))
    _grade_all_correct(sess, prog)
    result = exam.certify(sess, prog)
    assert result["passed"] is True
    assert result["accuracy"] == 100
    assert prog["certifications"]["sql"]["level"] == sess.exam_target
    assert prog["certifications"]["sql"]["exams_passed"] == 1


def test_exam_fails_below_threshold():
    packs = loader.load_all_packs()
    prog = pm.default_progress()
    sess = exam.build_exam("sql", prog, packs=packs, rng=random.Random(3))
    total = len(sess.challenges)
    # Answer all but one correctly -> < 100%; with 15 questions, 14/15 = 93% (pass),
    # so instead get two wrong to drop below 90%.
    for i, ch in enumerate(sess.challenges):
        ans = _reference(ch) if i < total - 2 else "definitely_wrong_answer_xyz"
        res = engine.submit(sess, ans, prog, allow_retry=False)
        sess.results.append(res)
        sess.index += 1
    result = exam.certify(sess, prog)
    assert result["passed"] is False
    assert "sql" not in prog["certifications"]


def test_exam_status_reports_levels():
    packs = loader.load_all_packs()
    prog = pm.default_progress()
    prog.setdefault("certifications", {})["sql"] = {
        "level": 2,
        "accuracy": 95,
        "best_accuracy": 95,
        "exams_passed": 1,
        "last_date": "2026-09-06",
    }
    statuses = {s["skill"]: s for s in exam.exam_status(prog, packs)}
    assert statuses["sql"]["level"] == 2
    assert statuses["sql"]["next_target"] == 3


def test_thin_skill_exam_tops_up_from_related():
    packs = loader.load_all_packs()
    prog = pm.default_progress()
    sess = exam.build_exam("git", prog, packs=packs, rng=random.Random(4))
    assert sess is not None
    own = [ch for ch in sess.challenges if ch.skill == "git"]
    fill = [ch for ch in sess.challenges if ch.skill != "git"]
    own_pool, rel_pool = exam.exam_pool(packs, "git")
    assert len(own_pool) == 10 and len(own_pool) < exam.EXAM_SIZE
    assert all(ch.skill == "shell" for ch in fill)
    # Own challenges always come first and dominate: every git challenge picked.
    assert len(own) == len(own_pool)
    # Fill = everything the related pool can offer (shell has 9 < 10 needed).
    assert len(sess.challenges) == len(own_pool) + len(rel_pool)
    ids = [ch.id for ch in sess.challenges]
    assert len(ids) == len(set(ids))  # no duplicates
    assert sess.exam_skill == "git"


def test_deep_skill_exam_stays_pure():
    packs = loader.load_all_packs()
    prog = pm.default_progress()
    sess = exam.build_exam("sql", prog, packs=packs, rng=random.Random(5))
    assert sess is not None
    own_pool, rel_pool = exam.exam_pool(packs, "sql")
    assert len(own_pool) == 15 and rel_pool == []  # deep skill, no related entry
    assert len(sess.challenges) == 15
    assert all(ch.skill == "sql" for ch in sess.challenges)


def test_related_fill_prefers_target_tier():
    packs = loader.load_all_packs()
    prog = pm.default_progress()
    prog.setdefault("certifications", {})["git"] = {
        "level": 2,
        "accuracy": 95,
        "best_accuracy": 95,
        "exams_passed": 1,
        "last_date": "2026-09-06",
    }
    sess = exam.build_exam("git", prog, packs=packs, rng=random.Random(6))
    assert sess is not None
    fill = [ch for ch in sess.challenges if ch.skill != "git"]
    _, rel_pool = exam.exam_pool(packs, "git")
    shell_tier3 = {ch.id for ch in rel_pool if ch.difficulty == 3}
    assert shell_tier3  # shell does carry target-tier content to prefer
    assert sess.exam_target == 3
    assert len(fill) == min(exam.EXAM_SIZE, 10 + len(rel_pool)) - 10
    assert all(ch.skill == "shell" for ch in fill)
    # Preferential fill: all related target-tier challenges make it onto the paper.
    assert shell_tier3 <= {ch.id for ch in fill}


def test_exam_status_reports_topup():
    packs = loader.load_all_packs()
    prog = pm.default_progress()
    statuses = {s["skill"]: s for s in exam.exam_status(prog, packs)}
    assert statuses["git"]["questions"] == 10 + statuses["git"]["topup"]
    assert statuses["git"]["topup"] == min(exam.EXAM_SIZE - 10, 9)
    assert statuses["git"]["related"] == ["shell"]
    assert statuses["sql"]["topup"] == 0
    assert statuses["sql"]["related"] == []
    assert statuses["sql"]["questions"] == 15


def test_related_skills_symmetry_or_declaration():
    # Documents the curated map (declared, not inferred).
    assert exam.related_skills("python") == ("javascript",)
    assert exam.related_skills("javascript") == ("python",)
    assert exam.related_skills("git") == ("shell",)
    assert exam.related_skills("shell") == ("git",)
    assert exam.related_skills("sql") == ()
    assert exam.related_skills("regex") == ()


def test_exam_certifies_mixed_paper():
    packs = loader.load_all_packs()
    prog = pm.default_progress()
    sess = exam.build_exam("javascript", prog, packs=packs, rng=random.Random(7))
    assert sess is not None
    own_pool, rel_pool = exam.exam_pool(packs, "javascript")
    assert len(own_pool) == 3  # fix-bug-js is the only javascript pack
    assert {ch.skill for ch in sess.challenges} == {"javascript", "python"}
    assert len(sess.challenges) == min(exam.EXAM_SIZE, len(own_pool) + len(rel_pool))
    _grade_all_correct(sess, prog)
    result = exam.certify(sess, prog)
    assert result["passed"] is True
    assert result["accuracy"] == 100
    assert result["level"] == sess.exam_target
    assert prog["certifications"]["javascript"]["level"] == sess.exam_target
