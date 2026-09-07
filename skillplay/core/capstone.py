"""V2 - Project / capstone mode (W1): session practice -> portfolio outcomes.

A capstone pack is a chain of challenges (ordered by the V4 prerequisite DAG)
that together build a single real artifact - a small CLI, a module, a tiny API.
As the player solves the code-producing challenges, their own correct solutions
are stitched together into a runnable file saved under the portfolio directory,
so a learning session leaves behind something tangible.

All functions here are pure except `build_artifact`, which writes the artifact
file and updates `progress["portfolio"]` in memory (the caller persists, per the
engine's save invariant).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import progress as progress_mod
from .loader import Pack

# Validation modes whose answer is code we can assemble into an artifact.
_CODE_MODES = ("test_cases", "freeform")


def is_capstone(pack: Pack) -> bool:
    return bool(getattr(pack, "capstone", False))


def capstone_packs(packs: list[Pack]) -> list[Pack]:
    return [p for p in packs if is_capstone(p)]


def _topo_order(pack: Pack) -> list:
    """Order the pack's challenges so prerequisites come before dependents (Kahn).
    Cross-pack prerequisites are ignored for ordering (placed at the end)."""
    by_id = {c.id: c for c in pack.challenges}
    indeg = {c.id: 0 for c in pack.challenges}
    adj: dict[str, list[str]] = {c.id: [] for c in pack.challenges}
    for c in pack.challenges:
        for pid in getattr(c, "prerequisites", None) or []:
            if pid in by_id:
                adj[pid].append(c.id)
                indeg[c.id] += 1
    queue = [cid for cid, d in indeg.items() if d == 0]
    order: list[str] = []
    while queue:
        n = queue.pop(0)
        order.append(n)
        for m in adj[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                queue.append(m)
    for cid in by_id:  # safety: append any leftovers (should be none - DAG-checked)
        if cid not in order:
            order.append(cid)
    return [by_id[cid] for cid in order]


def code_challenges(pack: Pack) -> list:
    return [c for c in _topo_order(pack) if c.validation.get("mode") in _CODE_MODES]


def _solution_for(progress: dict[str, Any], ch) -> str:
    """The player's own correct code if recorded, else the reference solution."""
    sol = progress.get("solutions", {}).get(ch.id)
    if sol:
        return sol
    return (ch.answer.get("reference_code") or "").strip()


def capstone_progress(progress: dict[str, Any], pack: Pack) -> dict[str, int]:
    """Summary for the UI: how many code challenges solved and if built."""
    code = code_challenges(pack)
    solved = sum(1 for c in code if c.id in progress.get("solutions", {}))
    built = 1 if progress.get("portfolio", {}).get(pack.id) else 0
    return {"total": len(code), "solved": solved, "built": built}


def _ensure_guard(code: str, lang: str) -> str:
    """For python artifacts, ensure a defined `main` is actually invoked."""
    if lang != "python":
        return code
    if "def main(" not in code:
        return code
    if 'if __name__ == "__main__"' in code or "if __name__ == '__main__'" in code:
        return code
    return code + '\n\nif __name__ == "__main__":\n    main()\n'


def build_artifact(
    progress: dict[str, Any], pack: Pack, data_dir: Path | None = None
) -> dict[str, Any]:
    """Assemble the capstone's code challenges (in prerequisite order) into one
    artifact file under `<data_dir>/portfolio/<filename>`.

    Uses the player's own correct solutions where available, falling back to each
    challenge's reference code so the artifact is always buildable. Returns a
    result dict; side effects are limited to writing the file and updating
    `progress["portfolio"][pack.id]` in memory (caller persists).
    """
    data_dir = data_dir or progress_mod.DATA_DIR
    artifact = getattr(pack, "artifact", {}) or {}
    filename = artifact.get("filename") or f"{pack.id}.py"
    lang = artifact.get("lang", "python")
    code_chs = code_challenges(pack)

    parts: list[str] = [f"# {pack.name} - assembled skillplay capstone artifact"]
    solved = 0
    for ch in code_chs:
        sol = _solution_for(progress, ch)
        if not sol:
            continue
        if ch.id in progress.get("solutions", {}):
            solved += 1
        parts.append(f"\n# --- {ch.id}: {ch.title} ---\n{sol}")
    body = "\n".join(parts) + "\n"
    body = _ensure_guard(body, lang)

    out_dir = Path(data_dir) / "portfolio"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    path.write_text(body, encoding="utf-8")

    progress.setdefault("portfolio", {})[pack.id] = {
        "path": str(path),
        "filename": filename,
        "built": progress_mod.today_str(),
        "solved": solved,
        "total": len(code_chs),
    }
    return {
        "ok": True,
        "path": str(path),
        "filename": filename,
        "lang": lang,
        "solved": solved,
        "total": len(code_chs),
        "code": body,
    }
