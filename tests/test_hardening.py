"""Tests for the v1.1 hardening wave (W4/W5/W6/W8 quick wins).

- W5: rolling daily backups of progress.json + restore.
- W6: per-skill readiness (learning) metric.
- W4: hesitant-but-correct answers don't over-promote SRS boxes.
- W8: Windows Job Object sandbox path exercises cleanly (graded runs).
"""

from __future__ import annotations

import json
import sys

import pytest

from skillplay.core import engine as eng
from skillplay.core import progress as pm
from skillplay.core import stats as stats_mod
from skillplay.core import validators as val

# --- W5: backups ------------------------------------------------------------


def test_save_creates_daily_backup_and_restore_works():
    prog = pm.default_progress()
    prog["total_xp"] = 42
    pm.save(prog)  # no file yet -> nothing to back up
    prog["total_xp"] = 100
    pm.save(prog)  # backs up the 42-XP state, then writes 100

    backups = pm.list_backups()
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8"))["total_xp"] == 42

    # Same-day saves dedupe: still one backup, still the pre-save state.
    prog["total_xp"] = 500
    pm.save(prog)
    assert len(pm.list_backups()) == 1

    # Restore rolls back to the snapshot (100 XP, and the 500 state is itself
    # backed up as "pre-restore" so a bad restore is recoverable).
    assert pm.restore_backup() is True
    assert pm.load()["total_xp"] == 100
    assert pm.list_backups()[0].name.startswith("progress-pre-restore")


def test_backup_prune_keeps_newest():
    pm.save(pm.default_progress())  # _backup snapshots the current on-disk file
    for i in range(20):
        pm._backup(f"2030-01-{i + 1:02d}")
    assert len(pm.list_backups()) == pm._MAX_BACKUPS
    # Newest first.
    assert pm.list_backups()[0].name == "progress-2030-01-20.json"
    assert pm.list_backups()[-1].name == "progress-2030-01-07.json"


# --- W6: readiness metric ---------------------------------------------------


class _FakePack:
    def __init__(self, skill: str, ids: list[str]):
        self.skill = skill
        self.id = skill
        self.challenges = [type("C", (), {"id": i})() for i in ids]


def _progress_with_skill(ids: list[str], *, seen_frac=0.0, box3_frac=0.0, acc=0.0):
    prog = pm.default_progress()
    n_completed = int(len(ids) * seen_frac)
    n_box3 = int(len(ids) * box3_frac)
    prog["skills"]["sql"] = {
        "xp": 0,
        "level": 1,
        "completed_ids": ids[:n_completed],
        "attempts": 100,
        "correct": int(100 * acc),
    }
    for i, cid in enumerate(ids):
        prog["challenges"][cid] = {"seen": 1, "correct": 1, "box": 3 if i < n_box3 else 1}
    return prog


def test_readiness_bounds_and_monotonicity():
    ids = [f"c{i}" for i in range(10)]
    pack = _FakePack("sql", ids)

    # Fresh player: nothing seen, no attempts -> 0.
    assert stats_mod.readiness(pm.default_progress(), [pack]) == 0

    base = stats_mod.readiness(_progress_with_skill(ids), [pack])
    mid = stats_mod.readiness(
        _progress_with_skill(ids, seen_frac=0.5, box3_frac=0.5, acc=0.5), [pack]
    )
    full = stats_mod.readiness(
        _progress_with_skill(ids, seen_frac=1.0, box3_frac=1.0, acc=1.0), [pack]
    )
    assert base < mid < full == 100

    # Labels escalate with score.
    assert stats_mod.readiness_label(0) == "learning"
    assert stats_mod.readiness_label(50) == "practicing"
    assert stats_mod.readiness_label(75) == "proficient"
    assert stats_mod.readiness_label(95) == "mastered"


def test_readiness_groups_packs_by_skill():
    p1 = _FakePack("python", ["a1", "a2"])
    p2 = _FakePack("python", ["b1"])
    prog = pm.default_progress()
    prog["skills"]["python"] = {
        "xp": 0,
        "level": 1,
        "completed_ids": ["a1", "b1"],
        "attempts": 10,
        "correct": 10,
    }
    rd = stats_mod.readiness_all(prog, [p1, p2])
    assert list(rd) == ["python"]
    # 2 of 3 challenges completed, 10/10 accuracy, no box-3 cards yet.
    assert 20 <= rd["python"] <= 80


# --- W4: latency-aware SRS --------------------------------------------------


def test_hesitant_correct_caps_box():
    # A hesitant correct answer still climbs (1->2->3) but is capped at 3
    # so the card keeps coming back until a *fast* recall proves mastery.
    prog = pm.default_progress()
    eng._advance_box(prog, "c1", correct=True, latency_ms=20_000)
    assert prog["challenges"]["c1"]["box"] == 2
    eng._advance_box(prog, "c1", correct=True, latency_ms=20_000)
    assert prog["challenges"]["c1"]["box"] == 3
    eng._advance_box(prog, "c1", correct=True, latency_ms=20_000)
    assert prog["challenges"]["c1"]["box"] == 3  # capped despite 3rd correct
    eng._advance_box(prog, "c1", correct=True, latency_ms=2_000)  # fast recall proves it
    assert prog["challenges"]["c1"]["box"] == 4


def test_fast_or_unknown_latency_promotes_normally():
    prog = pm.default_progress()
    eng._advance_box(prog, "c1", correct=True, latency_ms=None)
    assert prog["challenges"]["c1"]["box"] == 2
    eng._advance_box(prog, "c1", correct=True, latency_ms=1_000)
    assert prog["challenges"]["c1"]["box"] == 3


# --- W8: Windows sandbox ----------------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object path")
def test_win_sandbox_runs_grading_cleanly():
    """The sandboxed _exec_file path returns identical results to a plain run."""
    path = val._write_temp(".py", "import json\nprint(json.dumps({'passed': True, 'detail': ''}))")
    res = val._exec_file(path, [sys.executable])
    assert res.correct is True


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only helpers")
def test_win_job_lifecycle_is_safe():
    job = val._win_job_begin()
    if job is not None:  # may be None in restricted environments
        val._win_job_end(job)
    # Ending a None job must be a no-op, never a crash.
    val._win_job_end(None)
