"""V8 - community flywheel: bundles, publish flow, ratings, downloads, index."""

from __future__ import annotations

from pathlib import Path

from skillplay.core import loader, registry
from skillplay.core import progress as pm


def _tmp_registry(monkeypatch, tmp_path):
    packs = tmp_path / "packs"
    packs.mkdir()
    monkeypatch.setattr(registry, "USER_PACKS", packs)
    monkeypatch.setattr(registry, "REGISTRY_FILE", packs / ".registry.json")
    monkeypatch.setattr(registry, "STATS_FILE", packs / ".stats.json")
    return packs


def test_bundle_pack_creates_zip(monkeypatch, tmp_path):
    _tmp_registry(monkeypatch, tmp_path)
    src = loader.BUILTIN_PACKS / "git-basics"
    out = tmp_path / "git-basics.skillpack.zip"
    path = registry.bundle_pack(src, out)
    assert path.is_file()
    import zipfile

    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
    assert any(n.endswith("pack.yaml") for n in names)
    assert any(n.endswith("01-init.yaml") for n in names)


def test_publish_pack_local_only(monkeypatch, tmp_path):
    _tmp_registry(monkeypatch, tmp_path)
    src = loader.BUILTIN_PACKS / "git-basics"
    res = registry.publish_pack(src, base_url=None)
    assert res["published"] is False
    assert Path(res["bundle"]).is_file()
    assert "error" not in res


def test_publish_pack_server_failure_is_graceful(monkeypatch, tmp_path):
    _tmp_registry(monkeypatch, tmp_path)
    src = loader.BUILTIN_PACKS / "git-basics"
    # bogus server -> connection fails -> reported, never raised
    res = registry.publish_pack(src, base_url="http://127.0.0.1:9")
    assert res["published"] is False
    assert "error" in res
    assert Path(res["bundle"]).is_file()


def test_rate_pack_records_locally(monkeypatch, tmp_path):
    _tmp_registry(monkeypatch, tmp_path)
    prog = pm.default_progress()
    res = registry.rate_pack("git-basics", 4, progress=prog)
    assert res["rating"] == 4
    assert prog["ratings"]["git-basics"] == 4
    # out-of-range clamps
    assert registry.rate_pack("git-basics", 99, progress=prog)["rating"] == 5
    assert registry.rate_pack("git-basics", -3, progress=prog)["rating"] == 0


def test_available_packs_carries_flywheel_metadata(monkeypatch, tmp_path):
    _tmp_registry(monkeypatch, tmp_path)
    prog = pm.default_progress()
    prog.setdefault("ratings", {})["css-basics"] = 5
    packs = registry.available_packs(progress=prog)
    css = next(p for p in packs if p["name"] == "css-basics")
    assert css["rating"] == 4.5  # from the index entry
    assert css["downloads"] >= 1280  # index baseline
    assert css["user_rating"] == 5


def test_install_bumps_download_count(monkeypatch, tmp_path):
    packs = _tmp_registry(monkeypatch, tmp_path)
    src = loader.BUILTIN_PACKS / "git-basics"
    name = registry.install(str(src), force=True)
    assert (packs / name / "pack.yaml").is_file()
    assert registry.get_downloads("git-basics") == 1
    registry.install(str(src), force=True)  # re-install (force) bumps again
    assert registry.get_downloads("git-basics") == 2
