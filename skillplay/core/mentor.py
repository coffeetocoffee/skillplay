"""V7 - Mentor-mode explanations (W?): explain mistakes like a senior dev.

After a challenge attempt the mentor compares the learner's answer to an idiomatic
solution and explains *why* it was wrong. Two backends:

  - ``local``  (default, always available, offline): a deterministic, rule-based
    explanation built from the challenge's reference answer, its `explanation`,
    and the recorded mistake type. No network, no accounts.
  - ``openai`` / ``llama_cpp`` (opt-in, BYO key or local server): sends a focused
    prompt to an OpenAI-compatible Chat Completions endpoint and returns the
    model's mentoring prose. Any failure (no key, network error, non-200) falls
    back to the local backend so the feature never breaks a session.

The module is pure except `explain`, which may perform an (opt-in, time-boxed,
best-effort) network call in the LLM path; callers should treat the return value
as always present.
"""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Any

from .loader import Challenge

LOCAL = "local"
OPENAI = "openai"
LLAMA = "llama_cpp"

_CODE_MODES = ("test_cases", "freeform")
_LLM_TIMEOUT = 20  # seconds; the local fallback is instant so we can afford to wait


@dataclass
class MentorRequest:
    challenge: Any
    user_input: str
    correct: bool
    detail: str = ""
    mistake_type: str | None = None
    language: str = "python"


def pick_backend(progress: dict[str, Any] | None) -> str:
    if not progress:
        return LOCAL
    return (progress.get("settings", {}).get("mentor_backend") or LOCAL).lower()


def explain(req: MentorRequest, progress: dict[str, Any] | None = None) -> str:
    """Return a mentor explanation. Uses the configured backend; on any LLM
    failure, silently falls back to the local explanation."""
    backend = pick_backend(progress)
    if backend == LOCAL:
        return _explain_local(req)
    try:
        return _explain_with_llm(req, backend, progress)
    except Exception:
        return _explain_local(req)


def _correct_answer(ch: Challenge) -> str:
    mode = ch.validation.get("mode")
    if mode == "sql_result":
        return ch.answer.get("reference_sql", "")
    if mode == "exact":
        return ch.answer.get("value") or (ch.validation.get("answers") or [""])[0]
    if mode == "regex_tester":
        return ch.answer.get("value", "")
    if mode == "multiple_choice":
        aid = ch.validation.get("answer_id")
        for o in ch.options:
            if o.get("id") == aid:
                return f"{aid}: {o.get('text', '')}"
        return str(aid)
    if mode in _CODE_MODES:
        return ch.answer.get("reference_code", "")
    return ""


def _explain_local(req: MentorRequest) -> str:
    ch: Challenge = req.challenge
    if req.correct:
        note = "Nailed it."
        if ch.explanation:
            note += " " + ch.explanation.strip()
        return note
    if ch.validation.get("mode") in _CODE_MODES:
        return _mentor_code(req)
    return _mentor_noncode(req)


def _mentor_code(req: MentorRequest) -> str:
    ch: Challenge = req.challenge
    user = (req.user_input or "").strip()
    ref = (ch.answer.get("reference_code") or "").strip()
    parts: list[str] = []
    if req.mistake_type == "syntax":
        parts.append(
            "Your code didn't run cleanly - the grader reported a syntax or runtime "
            "error, so it likely never produced a result."
        )
    elif req.mistake_type == "logic":
        parts.append(
            "Your code ran, but it produced the wrong result - the logic doesn't "
            "match what the tests expect."
        )
    else:
        parts.append("That attempt wasn't quite right.")
    parts.append("")
    if user:
        parts.append("What you wrote:\n```\n" + user + "\n```")
    if ref:
        parts.append("An idiomatic version:\n```\n" + ref + "\n```")
    note = _idiomatic_note(ch)
    if note:
        parts.append(note)
    return "\n".join(parts)


def _mentor_noncode(req: MentorRequest) -> str:
    ch: Challenge = req.challenge
    correct = _correct_answer(ch)
    parts: list[str] = ["Not quite - let's break it down."]
    if req.mistake_type:
        parts.append(f"(This looks like a {req.mistake_type} issue.)")
    parts.append("")
    if correct:
        parts.append("Correct answer: " + correct)
    note = ch.localized("explanation")
    if note:
        parts.append("Why: " + note.strip())
    return "\n".join(parts)


def _idiomatic_note(ch: Challenge) -> str:
    """A short senior-dev nudge. Prefer the authored explanation; otherwise a
    generic reminder to aim for the smallest change that makes the tests pass."""
    note = ch.localized("explanation")
    if note:
        return "Mentor note: " + note.strip()
    return (
        "Mentor note: aim for the smallest change that makes the hidden tests pass, "
        "then worry about style."
    )


def _explain_with_llm(req: MentorRequest, backend: str, progress: dict[str, Any] | None) -> str:
    settings = (progress or {}).get("settings", {})
    if backend == OPENAI:
        base = (
            settings.get("mentor_base_url")
            or os.environ.get("OPENAI_BASE_URL")
            or "https://api.openai.com/v1"
        )
        api_key = settings.get("mentor_api_key") or os.environ.get("OPENAI_API_KEY") or ""
        model = settings.get("mentor_model") or "gpt-4o-mini"
        if not api_key:
            raise ValueError("openai backend requires mentor_api_key")
    else:  # llama_cpp
        base = settings.get("mentor_base_url") or os.environ.get("LLAMACPP_BASE_URL") or ""
        api_key = (
            settings.get("mentor_api_key") or os.environ.get("LLAMACPP_API_KEY") or "not-needed"
        )
        model = settings.get("mentor_model") or "local"
        if not base:
            raise ValueError("llama_cpp backend requires mentor_base_url")

    base = base.rstrip("/")
    url = base + "/chat/completions"
    prompt = _build_prompt(req)
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a senior software engineer mentoring a learner through "
                    "short coding challenges. Explain concisely (under 120 words) why "
                    "their answer was wrong and show the idiomatic solution. Be kind "
                    "and specific."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    req_obj = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
    )
    with urllib.request.urlopen(req_obj, timeout=_LLM_TIMEOUT) as resp:
        if resp.status != 200:
            raise RuntimeError(f"llm status {resp.status}")
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


def _build_prompt(req: MentorRequest) -> str:
    ch: Challenge = req.challenge
    correct = _correct_answer(ch)
    user = (req.user_input or "").strip()
    lines = [
        f"Challenge: {ch.prompt.strip()}",
        f"Mode: {ch.validation.get('mode')}",
        f"Correct answer: {correct}",
        f"Learner's answer: {user or '(empty)'}",
        f"Mistake type: {req.mistake_type or 'unknown'}",
        f"Grader detail: {req.detail or '(none)'}",
    ]
    return "\n".join(lines)
