"""V4 — skill graph + prerequisites: unlock logic, frontier selection, and
cross-pack validation. Progress writes are isolated via the shared fixture."""

from __future__ import annotations

from skillplay.core import engine, skillgraph
from skillplay.core import progress as pm
from skillplay.core.loader import load_all_packs


def _mark_known(prog, cid, correct=1, box=1):
    prog.setdefault("challenges", {})[cid] = {"seen": correct, "correct": correct, "box": box}


def test_loader_parses_prerequisites(git_pack):
    by_id = {c.id: c for c in git_pack.challenges}
    assert by_id["git-init-01"].prerequisites == []
    assert by_id["git-status-01"].prerequisites == ["git-init-01"]
    assert by_id["git-commit-01"].prerequisites == ["git-add-01"]
    assert by_id["git-mc-remote-01"].prerequisites == ["git-mc-clone-01"]


def test_unlock_new_player(git_pack):
    prog = pm.default_progress()
    by_id = {c.id: c for c in git_pack.challenges}
    assert skillgraph.is_unlocked(prog, by_id["git-init-01"]) is True
    assert skillgraph.is_unlocked(prog, by_id["git-status-01"]) is False
    assert skillgraph.missing_prerequisites(prog, by_id["git-status-01"]) == ["git-init-01"]


def test_unlock_after_prereq_known(git_pack):
    prog = pm.default_progress()
    by_id = {c.id: c for c in git_pack.challenges}
    _mark_known(prog, "git-init-01")
    assert skillgraph.is_unlocked(prog, by_id["git-status-01"]) is True
    # deeper chain still locked until the next link is known
    assert skillgraph.is_unlocked(prog, by_id["git-commit-01"]) is False
    _mark_known(prog, "git-add-01")
    assert skillgraph.is_unlocked(prog, by_id["git-commit-01"]) is True


def test_frontier_excludes_locked(git_pack):
    prog = pm.default_progress()
    fr = skillgraph.frontier([git_pack], prog)
    ids = {c.id for c in fr}
    assert "git-init-01" in ids
    assert "git-status-01" not in ids  # locked
    assert "git-mc-remote-01" not in ids  # locked deep


def test_frontier_excludes_mastered(git_pack):
    prog = pm.default_progress()
    by_id = {c.id: c for c in git_pack.challenges}
    # learn everything, then master init so it leaves the frontier
    for cid in by_id:
        _mark_known(prog, cid)
    _mark_known(prog, "git-init-01", correct=5, box=5)
    fr = skillgraph.frontier([git_pack], prog)
    ids = {c.id for c in fr}
    assert "git-init-01" not in ids  # mastered -> out of frontier
    # everything else is unlocked and not yet mastered -> still on the frontier
    assert "git-mc-remote-01" in ids


def test_frontier_stats_counts(git_pack):
    prog = pm.default_progress()
    stats = skillgraph.frontier_stats([git_pack], prog)["git"]
    assert stats["total"] == len(git_pack.challenges)
    assert stats["unlocked"] >= 1  # git-init-01
    assert stats["locked"] >= 1
    assert stats["mastered"] == 0


def test_select_path_walks_frontier(git_pack):
    prog = pm.default_progress()
    chosen = engine.select_path([git_pack], prog, 8)
    assert chosen  # non-empty
    # a brand-new player can only reach the root(s) of the DAG
    assert all(skillgraph.is_unlocked(prog, c) for c in chosen)
    assert {c.id for c in chosen} == {"git-init-01"}


def test_select_path_advances_after_learning(git_pack):
    prog = pm.default_progress()
    _mark_known(prog, "git-init-01")
    _mark_known(prog, "git-add-01")
    _mark_known(prog, "git-commit-01")
    chosen = engine.select_path([git_pack], prog, 8)
    ids = {c.id for c in chosen}
    # the chain has progressed past its first three links
    assert "git-status-01" in ids
    assert "git-branch-01" in ids
    assert all(skillgraph.is_unlocked(prog, c) for c in chosen)


def test_path_selection_gates_prerequisites(git_pack):
    prog = pm.default_progress()
    # select_path must respect prereqs for a pack that declares them
    chosen = engine.select_path([git_pack], prog, 8)
    assert chosen
    assert all(skillgraph.is_unlocked(prog, c) for c in chosen)


def test_validate_graph_clean_for_builtin_packs():
    packs = load_all_packs()
    errors, _ = skillgraph.validate_graph(packs)
    assert errors == [], errors


def test_validate_graph_detects_missing_ref_and_cycle():
    from skillplay.core.loader import Challenge, Pack

    def ch(cid, prereqs):
        return Challenge(
            id=cid,
            skill="x",
            title=cid,
            topic="t",
            difficulty=1,
            xp=1,
            type="exact",
            prompt="p",
            answer={"value": "v"},
            validation={"mode": "exact"},
            prerequisites=prereqs,
        )

    pack = Pack(
        id="p",
        name="p",
        version="1",
        skill="x",
        description="d",
        difficulty="beginner",
        author="a",
        challenges=[ch("a", ["ghost"]), ch("b", ["a"]), ch("c", ["c"])],
    )
    errors, _ = skillgraph.validate_graph([pack])
    assert any("ghost" in e for e in errors)  # missing reference
    assert any("cycle" in e for e in errors)  # c -> c self-cycle


def test_adaptive_next_best_respects_prereqs(git_pack):
    prog = pm.default_progress()
    # with no model, next_best falls back to heuristic; must still be unlocked
    best = __import__("skillplay.core.adaptive", fromlist=["adaptive"]).next_best_challenge(
        prog, git_pack, skill="git"
    )
    assert best is not None
    assert skillgraph.is_unlocked(prog, best)
