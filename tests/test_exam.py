"""Tests for V6 mastery exams (W6 learning metric)."""

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
