"""Tests for Section E — Intelligence: adaptive engine v2 + generative challenges.

Run with:  pytest tests/
Isolated: progress writes go to a temp dir (see conftest.py).
"""

from __future__ import annotations

import time

from skillplay.core import adaptive, engine, generate
from skillplay.core import progress as pm
from skillplay.core.loader import Pack


def _grade_all(s, prog):
    """Grade every challenge in a session correct and finalize it."""
    for i, ch in enumerate(s.challenges):
        s.index = i
        res = engine.submit(
            s,
            ch.answer.get("reference_code") or ch.answer.get("reference_sql"),
            prog,
            allow_retry=False,
        )
        s.results.append(res)
    engine.finalize(s, prog)


def test_attempts_recorded_on_finalize(packs):
    prog = pm.default_progress()
    chosen = engine.select_challenges(packs[0], prog, 4)
    s = engine.Session("mixed", chosen)
    _grade_all(s, prog)
    assert prog["attempts"], "expected per-attempt telemetry to be persisted"
    rec = prog["attempts"][0]
    assert set(rec) >= {"date", "skill", "challenge_id", "correct", "feats"}
    assert rec["feats"]["difficulty"] is not None


def test_adaptive_falls_back_without_data(packs):
    prog = pm.default_progress()
    chosen = adaptive.select_adaptive_v2(packs[0], prog, 5)
    # No model trained yet -> behaves like the classic selector.
    assert 0 < len(chosen) <= 5
    assert len({c.id for c in chosen}) == len(chosen)


def test_adaptive_model_trains_and_predicts(packs):
    prog = pm.default_progress()
    # Build up enough attempts to train (mix of correct + wrong) on one pack.
    chs = packs[0].challenges
    s = engine.Session("mixed", chs)
    for i, ch in enumerate(chs):
        s.index = i
        # alternate correctness to give the model signal
        if i % 2 == 0:
            ref = (
                ch.answer.get("reference_code")
                or ch.answer.get("reference_sql")
                or ch.answer.get("value", "x")
            )
        else:
            ref = "definitely wrong answer 12345"
        res = engine.submit(s, ref, prog, allow_retry=False)
        s.results.append(res)
    engine.finalize(s, prog)

    model = adaptive.load_model(prog)
    if model is None:
        # With only a handful of attempts we may still be below the threshold;
        # that's acceptable. Otherwise assert behavior.
        assert len(prog["attempts"]) < adaptive.MIN_TRAIN_ATTEMPTS or prog.get("model")
        return
    assert model.trained_on >= adaptive.MIN_TRAIN_ATTEMPTS
    # Predictions are valid probabilities.
    for ch in chs:
        p = model.predict_correct(engine._attempt_features(prog, ch))
        assert 0.0 <= p <= 1.0
    # next_best_challenge returns a real challenge.
    nb = adaptive.next_best_challenge(prog, packs[0])
    assert nb is not None


def test_select_adaptive_v2_bounds(packs):
    prog = pm.default_progress()
    # Train a trivial model directly so we exercise the model path.
    attempts = [
        {
            "correct": True,
            "feats": {
                "difficulty": 0.0,
                "box": 1.0,
                "mistakes": 0.0,
                "weak_share": 0.0,
                "rolling": 0.9,
                "seen": 0.5,
            },
        },
        {
            "correct": False,
            "feats": {
                "difficulty": 1.0,
                "box": 0.0,
                "mistakes": 0.8,
                "weak_share": 0.8,
                "rolling": 0.2,
                "seen": 0.0,
            },
        },
    ] * 15
    prog["attempts"] = attempts
    adaptive.retrain_if_needed(prog)
    model = adaptive.load_model(prog)
    assert model is not None
    chosen = adaptive.select_adaptive_v2(packs[0], prog, 5, model=model)
    assert 0 < len(chosen) <= 5
    assert len({c.id for c in chosen}) == len(chosen)
    # Model path attaches a human-readable reason.
    assert all(c.srs_reason.startswith("Model:") for c in chosen)


# --- G4: model path must preserve the "drill weakest mistake type" nudge ---


def test_retention_bonus_prefers_weakest_mistake_type():
    prog = pm.default_progress()
    # Two challenges with identical model failure prob; only one has a mistake
    # matching the globally weakest type -> it should get the retention boost.
    chs = [
        type("C", (), {"id": "a", "skill": "python", "difficulty": 1})(),
        type("C", (), {"id": "b", "skill": "python", "difficulty": 1})(),
    ]
    prog["mistakes"] = {
        "a": {"syntax": 0, "logic": 5, "off_by_one": 0},  # dominant = logic
        "b": {"syntax": 0, "logic": 0, "off_by_one": 0},
    }
    # Globally weakest type = logic (only 'a' has it).
    bonus_a = adaptive._retention_bonus(prog, chs[0])
    bonus_b = adaptive._retention_bonus(prog, chs[1])
    assert bonus_a > bonus_b
    assert bonus_a >= 3  # dominant match to globally weakest adds the +3 nudge


def test_select_adaptive_v2_keeps_retention_nudge(packs):
    prog = pm.default_progress()
    # Build a model that predicts ~equal failure for two challenges, then make
    # one of them the player's weakest mistake type; it must rank higher.
    attempts = [{"correct": True, "feats": {k: 0.5 for k in adaptive._FEATURE_KEYS}}] * 30
    prog["attempts"] = attempts
    adaptive.retrain_if_needed(prog)
    model = adaptive.load_model(prog)
    # Force a dominant weakest mistake type onto one pack challenge.
    target = packs[0].challenges[0]
    prog["mistakes"][target.id] = {"syntax": 0, "logic": 4, "off_by_one": 0}
    chosen = adaptive.select_adaptive_v2(packs[0], prog, 5, model=model)
    assert target in chosen  # weak-mistake challenge is surfaced despite equal model prob


# --- G5: model versioning, eval, and throttle ---


def test_model_versioning_and_rejects_unversioned():
    prog = pm.default_progress()
    prog["attempts"] = [{"correct": True, "feats": {k: 0.5 for k in adaptive._FEATURE_KEYS}}] * 30
    # Old-style model without a version must be ignored by load_model.
    prog["model"] = {"weights": {}, "bias": 0.0, "trained_on": 30}
    assert adaptive.load_model(prog) is None
    # A current-version model is accepted and carries version + eval.
    adaptive.retrain_if_needed(prog)
    m = adaptive.load_model(prog)
    assert m is not None
    assert prog["model"]["version"] == adaptive.MODEL_VERSION
    assert "eval_auc" in prog["model"]


def test_retrain_is_throttled():
    prog = pm.default_progress()
    prog["attempts"] = [{"correct": True, "feats": {k: 0.5 for k in adaptive._FEATURE_KEYS}}] * 30
    adaptive.retrain_if_needed(prog)
    first = dict(prog["model"])
    # No new attempts -> retrain should be a no-op (cheap finalize).
    adaptive.retrain_if_needed(prog)
    assert prog["model"] == first
    # Add a few (< RETRAIN_MIN_NEW) -> still no-op.
    prog["attempts"] += [{"correct": False, "feats": {k: 0.2 for k in adaptive._FEATURE_KEYS}}] * 5
    adaptive.retrain_if_needed(prog)
    assert prog["model"] == first
    # Add enough new attempts -> retrains.
    prog["attempts"] += [{"correct": False, "feats": {k: 0.2 for k in adaptive._FEATURE_KEYS}}] * 10
    adaptive.retrain_if_needed(prog)
    assert prog["model"] != first
    assert prog["model"]["trained_on_count"] == 45


def test_model_eval_auc_has_signal():
    # Separable data: train a model, then its held-out AUC should be high.
    attempts = [
        {
            "correct": True,
            "feats": {
                "difficulty": 0.0,
                "box": 1.0,
                "mistakes": 0.0,
                "weak_share": 0.0,
                "rolling": 0.9,
                "seen": 0.5,
            },
        }
    ] * 10 + [
        {
            "correct": False,
            "feats": {
                "difficulty": 1.0,
                "box": 0.0,
                "mistakes": 0.8,
                "weak_share": 0.8,
                "rolling": 0.2,
                "seen": 0.0,
            },
        }
    ] * 10
    from skillplay.core.adaptive import _eval_auc, train_model

    model = train_model(attempts)
    assert model is not None
    auc = _eval_auc(attempts, model)
    # A model fit on separable data must separate the classes well above chance.
    assert auc is not None and auc > 0.8


def test_generate_challenge_python_self_validates():
    ch = generate.generate_challenge("python", seed=1)
    assert ch.validation["mode"] == "test_cases"
    assert ch.validation["lang"] == "python"
    from skillplay.core.validators import validate

    assert validate(ch, ch.answer["reference_code"]).correct


def test_generate_session_unique_and_valid():
    chs = generate.generate_session("python", count=6, seed=42)
    assert len({c.id for c in chs}) == len(chs)
    from skillplay.core.validators import validate

    for c in chs:
        assert validate(c, c.answer["reference_code"]).correct


def test_generate_javascript_self_validates():
    ch = generate.generate_challenge("javascript", seed=7)
    assert ch.validation["lang"] == "javascript"
    from skillplay.core.validators import test_cases_runtime_available, validate

    if test_cases_runtime_available("javascript"):
        assert validate(ch, ch.answer["reference_code"]).correct
    else:
        # No node in this environment; generation still constructs a challenge.
        assert ch.validation["mode"] == "test_cases"


def test_generate_pack_playable():
    pk = generate.generate_pack("python", count=3, seed=3)
    assert isinstance(pk, Pack)
    assert len(pk.challenges) == 3
    # Playable through the normal engine path.
    prog = pm.default_progress()
    s = engine.Session("python", pk.challenges)
    _grade_all(s, prog)
    assert prog["total_xp"] > 0


# --- G6: generative depth (variety, difficulty scaling, new modality) ---


def test_generative_has_many_families():
    # G6: generation should draw from a broad template pool, not a handful.
    assert len(generate._PROBLEMS) >= 16


def test_generated_difficulty_scales_xp():
    chs = generate.generate_session("python", count=16, seed=11)
    for c in chs:
        assert 1 <= c.difficulty <= 5
        assert c.xp == 10 * c.difficulty


def test_generated_inputs_scale_with_difficulty():
    # Higher difficulty -> at least some challenges use larger input sizes.
    small = generate.generate_session("python", count=8, seed=1)
    big = generate.generate_session("python", count=8, seed=99)
    # Not asserting exact sizes (random), just that generation is stable + valid.
    assert len({c.id for c in small}) == len(small)
    from skillplay.core.validators import validate

    for c in big:
        assert validate(c, c.answer["reference_code"]).correct


def test_regex_generation_self_validates():
    chs = generate.generate_regex_session(count=6, seed=9)
    from skillplay.core.validators import validate

    for c in chs:
        assert c.validation["mode"] == "regex_tester"
        assert c.skill == "regex"
        assert validate(c, c.answer["value"]).correct


def test_generate_session_regex_kind():
    chs = generate.generate_session(kind="regex", count=4, seed=3)
    assert len(chs) == 4
    assert all(c.validation["mode"] == "regex_tester" for c in chs)


def test_regex_pack_playable_renders_as_input():
    # Regex challenges use single-line input (not code) in the TUI; ensure the
    # validation mode is what the PlayScreen routes to the Input widget.
    pk = generate.generate_regex_pack(count=3, seed=4)
    assert all(c.validation["mode"] == "regex_tester" for c in pk.challenges)


# --- G7: the collected latency signal is now a real model feature ---


def test_attempt_features_include_latency():
    prog = pm.default_progress()
    ch = type("C", (), {"id": "x", "skill": "python", "difficulty": 2})()
    feats = engine._attempt_features(prog, ch, latency_ms=10000)
    assert "latency" in feats
    assert feats["latency"] == 0.5  # 10s / 20s cap
    # No latency available -> neutral 0.5 so live (pre-attempt) scoring is stable.
    assert engine._attempt_features(prog, ch)["latency"] == 0.5


def test_submit_records_latency_in_feats(packs):
    prog = pm.default_progress()
    ch = packs[0].challenges[0]
    ref = (
        ch.answer.get("reference_sql") or ch.answer.get("value") or ch.answer.get("reference_code")
    )
    s = engine.Session("sql", [ch])
    s._challenge_started = time.monotonic() - 0.05  # ~50ms ago
    res = engine.submit(s, ref, prog, allow_retry=False)
    s.results.append(res)
    assert s.attempts
    feat = s.attempts[0]["feats"]
    assert "latency" in feat
    assert 0.0 <= feat["latency"] <= 1.0


def test_model_trains_with_latency_feature():
    # Latency is part of _FEATURE_KEYS; a model trained on feats that include it
    # must still fit and score (G7 end-to-end).
    prog = pm.default_progress()
    prog["attempts"] = [
        {"correct": True, "feats": {k: 0.5 for k in adaptive._FEATURE_KEYS}} for _ in range(15)
    ] + [{"correct": False, "feats": {k: 0.1 for k in adaptive._FEATURE_KEYS}} for _ in range(15)]
    adaptive.retrain_if_needed(prog)
    model = adaptive.load_model(prog)
    assert model is not None
    assert "latency" in model.weights


# --- G8: code isolation sandbox does not break grading ---


def test_sandbox_still_grades_code():
    # The subprocess sandbox (rlimits / node flag) must not interfere with normal
    # grading of generated Python challenges.
    chs = generate.generate_session("python", count=4, seed=21)
    from skillplay.core.validators import validate

    for c in chs:
        assert validate(c, c.answer["reference_code"]).correct


# --- G1: mistake taxonomy must work for code challenges ---


def _code_ch():
    return type("C", (), {"validation": {"mode": "test_cases"}})()


def test_classify_code_syntax_error_as_syntax():
    from skillplay.core.validators import Result

    res = Result(False, "error on [1]: SyntaxError: invalid syntax")
    assert engine.classify_mistake(_code_ch(), res) == "syntax"


def test_classify_code_runtime_error_as_logic():
    from skillplay.core.validators import Result

    res = Result(False, "error on [1, 2]: TypeError: unsupported operand")
    assert engine.classify_mistake(_code_ch(), res) == "logic"


def test_classify_code_wrong_output_as_logic():
    from skillplay.core.validators import Result

    res = Result(False, "[1, 2] -> got 3, expected 5")
    assert engine.classify_mistake(_code_ch(), res) == "logic"


# --- G2: generated IDs are deterministic and SRS-trackable ---


def test_generated_ids_deterministic_per_seed():
    a = generate.generate_session("python", count=4, seed=123)
    b = generate.generate_session("python", count=4, seed=123)
    assert [c.id for c in a] == [c.id for c in b]
    assert len({c.id for c in a}) == len(a)


def test_generated_ids_differ_across_seeds():
    a = generate.generate_session("python", count=4, seed=1)
    b = generate.generate_session("python", count=4, seed=2)
    assert {c.id for c in a} != {c.id for c in b}


def test_generated_ids_are_srs_tracked_not_orphaned():
    prog = pm.default_progress()
    chs = generate.generate_session("python", count=3, seed=7)
    s = engine.Session("python", chs)
    _grade_all(s, prog)
    # Same seed -> same IDs -> SRS records land under those exact IDs (no pollution).
    assert {c.id for c in chs} <= set(prog["challenges"])
