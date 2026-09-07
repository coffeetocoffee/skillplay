"""Core smoke tests: loader, validators, engine, streak.

Run:  python tests/smoke_core.py   (from repo root, or anywhere)
Isolated: progress writes go to a temp dir, never the real user data dir.
"""

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillplay.core import engine, loader, validators
from skillplay.core import progress as pm
from skillplay.core.streak import update_streak

_tmp = tempfile.mkdtemp(prefix="skillplay-test-")
pm.DATA_DIR = Path(_tmp)
pm.PROGRESS_PATH = Path(_tmp) / "progress.json"

packs = loader.load_all_packs()
print("packs:", [p.id for p in packs], "| challenges:", sum(len(p.challenges) for p in packs))
assert packs, "no packs loaded — run from repo root so skillplay/packs/ is found"
p = next(pk for pk in packs if pk.id == "sql-basics")


# 1. reference answers validate (mode-aware)
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


for pk in packs:
    for ch in pk.challenges:
        r = validators.validate(ch, _ref(ch))
        assert r.correct, f"{ch.id} failed: {r.detail}"
print("1. reference answers: all correct")

# 2. wrong-but-valid SQL detected
ch = p.challenges[1]
r = validators.validate(ch, "SELECT name FROM users WHERE age > 100")
assert not r.correct
print("2. wrong-but-valid SQL rejected:", r.detail)

# 3. invalid SQL handled (no raise)
r = validators.validate(ch, "SELEC name FROM users")
assert not r.correct
print("3. invalid SQL:", r.detail)

# 4. equivalent query accepted (case)
r = validators.validate(ch, "select NAME from USERS where AGE > 30")
assert r.correct, r.detail
print("4. case-insensitive equivalent accepted")

# 5. retry logic: first wrong -> retry allowed, then correct -> half XP
prog = pm.default_progress()
s = engine.Session("sql", engine.select_challenges(p, prog, 8))
first = len(s.challenges)
ch0 = s.current
r1 = engine.submit(s, "totally wrong", prog, allow_retry=True)
assert r1.retried and not r1.correct
r2 = engine.submit(s, ch0.answer["reference_sql"], prog, allow_retry=True)
assert r2.correct and r2.xp_gained == ch0.xp // 2, (ch0.xp, r2.xp_gained)
print(f"5. retry: half XP ok ({ch0.xp} -> {r2.xp_gained})")

# 6. finalize: xp + streak
s.index = len(s.challenges)
engine.finalize(s, prog)
assert prog["total_xp"] == s.xp_gained and prog["skills"]["sql"]["attempts"] == first
update_streak(prog["streak"])
assert prog["streak"]["current"] == 1
print("6. finalize ok:", "total_xp =", prog["total_xp"], "| streak =", prog["streak"]["current"])

# 7. SRS box advance
assert prog["challenges"][ch0.id]["box"] == 2
print("7. SRS box advanced:", prog["challenges"][ch0.id])
print("ALL CORE TESTS PASSED")
