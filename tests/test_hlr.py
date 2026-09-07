"""Tests for V3 half-life regression (HLR) scheduler (W4)."""

from __future__ import annotations

from datetime import date, timedelta

from skillplay.core import engine, hlr
from skillplay.core import progress as pm


def test_predict_recall_monotonic_in_delay():
    assert hlr.predict_recall(10, 0) == 1.0
    p1 = hlr.predict_recall(10, 5)
    p2 = hlr.predict_recall(10, 20)
    assert 0 < p2 < p1 < 1.0


def test_predict_recall_increases_with_half_life():
    assert hlr.predict_recall(20, 5) > hlr.predict_recall(5, 5)


def test_update_increases_stability_on_recall_after_delay():
    base = hlr.DEFAULT_HALF_LIFE
    # recalled correctly after a 5-day gap -> stability should grow.
    grown = hlr.update(base, dt_days=5, correct=True, latency_ms=None)
    assert grown > base


def test_update_decreases_stability_on_failure():
    base = 10.0
    shrunk = hlr.update(base, dt_days=2, correct=False, latency_ms=None)
    assert shrunk < base


def test_update_hesitant_correct_shrinks_more():
    fast = hlr.update(5.0, dt_days=3, correct=True, latency_ms=1000)
    slow = hlr.update(5.0, dt_days=3, correct=True, latency_ms=20000)
    assert slow < fast  # slow-but-correct is shakier recall


def test_next_due_orders_by_half_life():
    soon = hlr.next_due_days(2.5)
    later = hlr.next_due_days(40.0)
    assert 0 < soon < later


def test_next_due_iso_future_and_capped():
    today = date.today().isoformat()
    d_small = hlr.next_due_iso(2.5, today)
    d_big = hlr.next_due_iso(365.0, today)
    assert d_small >= today
    assert d_big > d_small


def test_first_encounter_stays_due_today():
    prog = pm.default_progress()
    prog["challenges"]["x1"] = {
        "seen": 0,
        "correct": 0,
        "box": 1,
        "next_due": pm.today_str(),
    }
    engine._advance_box(prog, "x1", correct=True, latency_ms=None)
    assert prog["challenges"]["x1"]["next_due"] == pm.today_str()
    assert prog["challenges"]["x1"]["hl"] > 0


def test_repeated_recall_grows_half_life():
    prog = pm.default_progress()
    rec = prog["challenges"]["y1"] = {
        "seen": 1,
        "correct": 1,
        "box": 2,
        "hl": hlr.DEFAULT_HALF_LIFE,
        "next_due": pm.today_str(),
    }
    prev = rec["hl"]
    for gap in (1, 3, 7, 14):
        rec["last_review"] = (date.today() - timedelta(days=gap)).isoformat()
        rec["seen"] = 1
        engine._advance_box(prog, "y1", correct=True, latency_ms=2000)
        assert prog["challenges"]["y1"]["hl"] >= prev - 1e-9
        prev = prog["challenges"]["y1"]["hl"]


def test_failure_shrinks_half_life_and_resets_box():
    prog = pm.default_progress()
    prog["challenges"]["z1"] = {
        "seen": 5,
        "correct": 4,
        "box": 5,
        "hl": 30.0,
        "next_due": pm.today_str(),
        "last_review": (date.today() - timedelta(days=1)).isoformat(),
    }
    engine._advance_box(prog, "z1", correct=False, latency_ms=None)
    assert prog["challenges"]["z1"]["hl"] < 30.0
    assert prog["challenges"]["z1"]["box"] == 1
