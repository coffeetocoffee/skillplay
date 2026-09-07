"""V2 — capstone mode: artifact assembly from solved challenges + validation."""

from __future__ import annotations

import subprocess
import sys

from skillplay.core import capstone, engine
from skillplay.core import progress as pm


def _mini_cli(packs):
    return next(p for p in packs if p.id == "mini-cli")


def test_loader_parses_capstone(packs):
    mp = _mini_cli(packs)
    assert capstone.is_capstone(mp) is True
    assert mp.artifact.get("filename") == "mini_cli.py"
    assert mp.artifact.get("lang") == "python"
    # setup was injected from prerequisites so the chain validates in isolation
    by_id = {c.id: c for c in mp.challenges}
    assert "greet" in by_id["mini-cli-03"].validation.get("setup", "")


def test_capstone_packs_list(packs):
    caps = capstone.capstone_packs(packs)
    assert any(p.id == "mini-cli" for p in caps)


def test_topo_order_respects_prerequisites(packs):
    mp = _mini_cli(packs)
    order = [c.id for c in capstone._topo_order(mp)]
    assert order.index("mini-cli-01") < order.index("mini-cli-02")
    assert order.index("mini-cli-02") < order.index("mini-cli-03")


def test_engine_records_code_solution(packs):
    mp = _mini_cli(packs)
    prog = pm.default_progress()
    sess = engine.Session(mp.skill, [mp.challenges[0]])
    r = engine.submit(sess, mp.challenges[0].answer["reference_code"], prog, allow_retry=False)
    assert r.correct
    assert prog["solutions"].get("mini-cli-01") == mp.challenges[0].answer["reference_code"]


def test_capstone_progress_reflects_solutions(packs):
    mp = _mini_cli(packs)
    prog = pm.default_progress()
    assert capstone.capstone_progress(prog, mp)["solved"] == 0
    prog.setdefault("solutions", {})["mini-cli-01"] = "x"
    assert capstone.capstone_progress(prog, mp)["solved"] == 1


def test_build_artifact_from_own_code(packs, tmp_path):
    mp = _mini_cli(packs)
    prog = pm.default_progress()
    sess = engine.Session(mp.skill, list(mp.challenges))
    for ch in mp.challenges:
        r = engine.submit(sess, ch.answer["reference_code"], prog, allow_retry=False)
        assert r.correct
        sess.results.append(r)
        sess.index += 1
    engine.finalize(sess, prog)
    res = capstone.build_artifact(prog, mp, data_dir=tmp_path)
    assert res["ok"]
    assert res["solved"] == 3
    text = (tmp_path / "portfolio" / "mini_cli.py").read_text(encoding="utf-8")
    assert "def greet" in text and "def add" in text and "def main" in text
    # the assembled artifact must actually run and produce the expected output
    out = subprocess.run([sys.executable, res["path"]], capture_output=True, text=True, timeout=20)
    assert out.returncode == 0
    assert "Hello, World!" in out.stdout
    assert "2 + 3 = 5" in out.stdout


def test_build_artifact_falls_back_to_reference(packs, tmp_path):
    mp = _mini_cli(packs)
    prog = pm.default_progress()  # no solutions recorded
    res = capstone.build_artifact(prog, mp, data_dir=tmp_path)
    assert res["solved"] == 0  # nothing from the player
    assert (tmp_path / "portfolio" / "mini_cli.py").is_file()
