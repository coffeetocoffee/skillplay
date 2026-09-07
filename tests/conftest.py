"""Shared pytest fixtures for skillplay tests.

Progress writes are redirected to a fresh temp dir so the real user data dir is
never touched (same isolation strategy as the smoke scripts).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from skillplay.core import progress as pm  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_progress(tmp_path):
    data_dir = Path(tempfile.mkdtemp(dir=tmp_path))
    pm.DATA_DIR = data_dir
    pm.PROGRESS_PATH = data_dir / "progress.json"
    yield


@pytest.fixture
def packs():
    from skillplay.core import loader

    return loader.load_all_packs()


@pytest.fixture
def sql_pack(packs):
    return next(p for p in packs if p.skill == "sql")


@pytest.fixture
def git_pack(packs):
    return next(p for p in packs if p.id == "git-basics")


@pytest.fixture
def regex_pack(packs):
    return next(p for p in packs if p.id == "regex-101")
