"""V7 - mentor-mode explanations: local backend + LLM fallback behavior."""

from __future__ import annotations

from skillplay.core import mentor
from skillplay.core.loader import Challenge


def _ch(mode, answer, explanation="Because reasons.", prompt="Do the thing."):
    return Challenge(
        id="x",
        skill="python",
        title="t",
        topic="tp",
        difficulty=1,
        xp=1,
        type="t",
        prompt=prompt,
        answer=answer,
        validation={"mode": mode},
        explanation=explanation,
    )


def _code_ch(user, ref, mode="test_cases", mistake="logic"):
    ch = _ch(mode, {"reference_code": ref})
    req = mentor.MentorRequest(
        challenge=ch, user_input=user, correct=False, detail="boom", mistake_type=mistake
    )
    return mentor._explain_local(req)


def test_local_code_logic_shows_both_blocks():
    out = _code_ch("def add(a,b): return a-b", "def add(a,b): return a+b")
    assert "What you wrote" in out
    assert "idiomatic" in out or "An idiomatic" in out
    assert "def add(a,b): return a+b" in out
    assert "Mentor note" in out


def test_local_code_syntax_mentions_not_running():
    out = _code_ch("def add(a,b) return a+b", "def add(a,b): return a+b", mistake="syntax")
    assert "didn't run" in out or "never produced" in out


def test_local_noncode_explains():
    ch = _ch("exact", {"value": "git init"})
    req = mentor.MentorRequest(
        challenge=ch, user_input="git start", correct=False, detail="x", mistake_type="logic"
    )
    out = mentor._explain_local(req)
    assert "Correct answer: git init" in out
    assert "Because reasons." in out


def test_local_correct_reinforces():
    ch = _ch("exact", {"value": "git init"})
    req = mentor.MentorRequest(challenge=ch, user_input="git init", correct=True)
    out = mentor._explain_local(req)
    assert "Nailed it" in out
    assert "Because reasons." in out


def test_pick_backend_defaults_local():
    assert mentor.pick_backend(None) == mentor.LOCAL
    assert mentor.pick_backend({"settings": {"mentor_backend": "openai"}}) == "openai"


def test_openai_without_key_falls_back_to_local():
    ch = _ch("exact", {"value": "git init"})
    req = mentor.MentorRequest(challenge=ch, user_input="git start", correct=False, detail="x")
    # openai backend but no key -> raises -> explain() falls back to local output
    out = mentor.explain(req, {"settings": {"mentor_backend": "openai"}})
    assert "Correct answer: git init" in out


def test_correct_answer_extraction_per_mode():
    assert "git init" in mentor._correct_answer(_ch("exact", {"value": "git init"}))
    assert "SELECT" in mentor._correct_answer(_ch("sql_result", {"reference_sql": "SELECT 1"}))
    assert ".+" in mentor._correct_answer(_ch("regex_tester", {"value": ".+"}))
    mc = _ch("multiple_choice", {}, prompt="?")
    mc.validation["answer_id"] = "b"
    mc.options = [{"id": "a", "text": "no"}, {"id": "b", "text": "yes"}]
    assert "yes" in mentor._correct_answer(mc)
    assert "return a+b" in mentor._correct_answer(
        _ch("freeform", {"reference_code": "def add:\n    return a+b"})
    )
