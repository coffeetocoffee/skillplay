"""Tests for section D: registry index + editor-context mapping."""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from skillplay.core import cli, registry


def test_available_packs_lists_index(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "USER_PACKS", tmp_path / "packs")
    monkeypatch.setattr(registry, "REGISTRY_FILE", tmp_path / "packs" / ".registry.json")
    packs = registry.available_packs()
    names = {p["name"] for p in packs}
    assert {"css-basics", "shell-basics", "fix-bug-js"} <= names
    # Nothing installed yet.
    assert all(not p["installed"] for p in packs)


def test_install_from_index_copies_pack(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "USER_PACKS", tmp_path / "packs")
    monkeypatch.setattr(registry, "REGISTRY_FILE", tmp_path / "packs" / ".registry.json")
    name = registry.install_from_index("css-basics")
    assert (tmp_path / "packs" / name / "pack.yaml").is_file()
    # Now flagged installed.
    assert any(p["name"] == "css-basics" and p["installed"] for p in registry.available_packs())


def test_context_maps_extension_to_pack(capsys):
    from argparse import Namespace

    rc = cli.cmd_context(Namespace(file="foo.py", open=False))
    assert rc == 0
    out = capsys.readouterr().out
    assert "fix-bug" in out

    rc = cli.cmd_context(Namespace(file="weird.unknownext", open=False))
    assert rc == 1
    assert "No skillpack" in capsys.readouterr().out


def test_ext_to_pack_mapping():
    assert cli._EXT_TO_PACK[".py"] == "fix-bug"
    assert cli._EXT_TO_PACK[".css"] == "css-basics"
    assert cli._EXT_TO_PACK[".sql"] == "sql-basics"
    assert cli._EXT_TO_PACK[".http"] == "http-rest"
