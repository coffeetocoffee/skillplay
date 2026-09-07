"""V9 - distribution & parity: challenge-content i18n, zero-install web demo,
and the (already-implemented) Windows Job Object sandbox."""

from __future__ import annotations

import sys
import threading
import urllib.request

from skillplay.core import demo as demo_mod
from skillplay.core import i18n, loader


def _data_structures(packs):
    return next(p for p in packs if p.id == "data-structures")


def test_challenge_translations_parsed_and_applied(packs):
    ds = _data_structures(packs)
    ch = next(c for c in ds.challenges if c.id == "ds-first-01")
    assert ch.translations and "es" in ch.translations
    i18n.set_language("en")
    assert ch.localized("prompt").startswith("`first(lst)` should return the first")
    i18n.set_language("es")
    assert "debe devolver el primer elemento" in ch.localized("prompt")
    assert "El índice 0" in ch.localized("hints")[0]
    i18n.set_language("en")  # restore


def test_pack_translations_parsed_and_applied(packs):
    ds = _data_structures(packs)
    assert ds.translations and "es" in ds.translations
    i18n.set_language("es")
    assert ds.localized("name") == "Estructuras de datos"
    assert "Operaciones básicas" in ds.localized("description")
    i18n.set_language("en")


def test_demo_payload_shape_and_solution(packs):
    payload = demo_mod.random_challenge_payload(packs)
    assert {"id", "prompt", "hints", "solution", "explanation", "mode"} <= set(payload)
    # solution text resolves for code and non-code alike
    assert isinstance(payload["solution"], str)


def test_demo_html_contains_markers():
    html = demo_mod.build_demo_html()
    assert "skillplay" in html
    assert "/api/challenge" in html


def test_demo_server_serves_challenge_and_html():

    packs = loader.load_all_packs()
    server = demo_mod.run_demo_server(packs, host="127.0.0.1", port=0)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/challenge", timeout=5) as r:
            import json

            data = json.loads(r.read())
            assert data["id"]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
            assert b"skillplay" in r.read()
    finally:
        server.shutdown()


def test_windows_job_object_sandbox():
    if sys.platform != "win32":
        import pytest

        pytest.skip("Windows Job Object sandbox only runs on Windows")
    from skillplay.core.validators import _win_job_begin, _win_job_end

    job = _win_job_begin()
    assert job is not None
    _win_job_end(job)  # should not raise
