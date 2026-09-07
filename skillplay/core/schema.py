"""Lightweight pack/challenge schema checks (no external deps).

Used by the `validate-packs` CLI. For editor autocompletion, see the JSON
Schema files under `skillplay/packs/schemas/`.
"""

from __future__ import annotations

KNOWN_MODES = {"exact", "regex_tester", "multiple_choice", "sql_result", "test_cases", "freeform"}
REQUIRED_CHALLENGE_KEYS = {"id", "type"}

# Regex references that match essentially anything — a red flag for a real test.
_OVERBROAD_REGEX = {".*", ".+", "(.|\\s)*", "(.|\\n)*", "[\\s\\S]*"}


def validate_pack(pack, strict: bool = False) -> tuple[list[str], list[str]]:
    """Return `(errors, warnings)`. In `strict` mode warnings are promoted to errors."""
    errors: list[str] = []
    warnings: list[str] = []
    if not pack.challenges:
        errors.append(f"[{pack.id}] pack has no challenges")
    seen_ids: set[str] = set()
    seen_prompts: dict[str, str] = {}
    by_id: dict[str, object] = {ch.id: ch for ch in pack.challenges}
    for ch in pack.challenges:
        cid = ch.id
        if cid in seen_ids:
            errors.append(f"[{pack.id}] duplicate challenge id: {cid}")
        seen_ids.add(cid)

        prompt_key = (ch.prompt or "").strip().lower()
        if prompt_key:
            if prompt_key in seen_prompts:
                errors.append(f"[{cid}] duplicate prompt text (also in {seen_prompts[prompt_key]})")
            else:
                seen_prompts[prompt_key] = cid

        errors.extend(f"[{cid}] {msg}" for msg in _validate_challenge(ch, by_id))

        if not (ch.explanation or "").strip():
            warnings.append(f"[{cid}] missing explanation")
        if not ch.hints:
            warnings.append(f"[{cid}] missing hints")

    # V2: capstone packs must declare an artifact target and contain at least one
    # code-producing challenge, otherwise there's nothing to assemble.
    if getattr(pack, "capstone", False):
        if not (getattr(pack, "artifact", {}) or {}).get("filename"):
            errors.append(f"[{pack.id}] capstone pack requires artifact.filename")
        code_modes = {"test_cases", "freeform"}
        if not any(ch.validation.get("mode") in code_modes for ch in pack.challenges):
            errors.append(
                f"[{pack.id}] capstone pack needs at least one code challenge (test_cases/freeform)"
            )
        mode = ch.validation.get("mode")
        if ch.context and mode in ("exact", "regex_tester", "multiple_choice"):
            warnings.append(f"[{cid}] context provided but unused by mode '{mode}'")
        if mode == "regex_tester":
            ref = (ch.answer.get("value") or "").strip()
            if ref in _OVERBROAD_REGEX:
                warnings.append(f"[{cid}] reference regex '{ref}' is over-broad")

    if strict:
        errors.extend(warnings)
        warnings = []
    return errors, warnings


def _validate_challenge(ch, by_id: dict[str, object] | None = None) -> list[str]:
    errors: list[str] = []
    if not ch.id:
        errors.append("missing id")
    if not ch.type:
        errors.append("missing type")
    mode = ch.validation.get("mode")
    if mode not in KNOWN_MODES:
        errors.append(f"unknown validation.mode: {mode!r}")
    if mode == "sql_result":
        if not ch.answer.get("reference_sql"):
            errors.append("sql_result requires answer.reference_sql")
    elif mode == "multiple_choice":
        if not ch.validation.get("answer_id"):
            errors.append("multiple_choice requires validation.answer_id")
        if not ch.options:
            errors.append("multiple_choice requires options")
        else:
            opt_ids = {o.get("id") for o in ch.options}
            if ch.validation.get("answer_id") not in opt_ids:
                errors.append("validation.answer_id not present in options")
    elif mode == "exact":
        if not (ch.answer.get("value") or ch.validation.get("answers")):
            errors.append("exact requires answer.value or validation.answers")
    elif mode == "regex_tester":
        if not ch.validation.get("must_match") and not ch.validation.get("must_not_match"):
            errors.append("regex_tester requires must_match and/or must_not_match")
    elif mode == "test_cases":
        if not ch.validation.get("test_cases"):
            errors.append("test_cases requires validation.test_cases")
        if not ch.validation.get("function"):
            errors.append("test_cases requires validation.function")
        if not ch.answer.get("reference_code"):
            errors.append("test_cases requires answer.reference_code")
    elif mode == "freeform":
        # V1: hidden-test construction — same requirements as test_cases, plus a
        # starter template so the player has a blank function to fill in.
        if not ch.validation.get("test_cases"):
            errors.append("freeform requires validation.test_cases")
        if not ch.validation.get("function"):
            errors.append("freeform requires validation.function")
        if not ch.answer.get("reference_code"):
            errors.append("freeform requires answer.reference_code")
        if not (ch.starter_code or ch.validation.get("starter_code")):
            errors.append(f"[{ch.id}] freeform requires a starter_code template")
    # Try a self-check: the reference answer should validate against itself.
    if mode in ("sql_result", "exact", "regex_tester", "multiple_choice", "test_cases", "freeform"):
        from .validators import test_cases_runtime_available, validate

        ref = _reference_input(ch)
        if ref is not None:
            # Skip self-check when the required runtime (e.g. node for JS) is
            # not installed, so `validate-packs` stays green in minimal envs.
            if mode in ("test_cases", "freeform") and not test_cases_runtime_available(
                ch.validation.get("lang", "python")
            ):
                pass
            else:
                # V2: a capstone challenge may depend on earlier functions in the
                # same pack. Prepend their reference code so the isolated self-check
                # can resolve names that only exist once the artifact is assembled.
                if mode in ("test_cases", "freeform") and by_id is not None:
                    prelude = _prereq_prelude(ch, by_id)
                    if prelude:
                        ref = prelude + "\n" + ref
                res = validate(ch, ref)
                if not res.correct:
                    errors.append(f"reference answer does not self-validate: {res.detail}")
    return errors


def _prereq_prelude(ch, by_id: dict[str, object]) -> str:
    """Concatenated reference code of (transitive) in-pack prerequisites, so an
    isolated self-check can resolve names that only exist once the artifact is
    assembled. Recurses through the prerequisite DAG; cycles are broken via `seen`."""
    parts: list[str] = []
    seen: set[str] = set()

    def _collect(cid: str) -> None:
        dep = by_id.get(cid)
        if dep is None or cid in seen:
            return
        seen.add(cid)
        for pid in getattr(dep, "prerequisites", None) or []:
            _collect(pid)
        code = getattr(dep, "answer", {}).get("reference_code", "")
        if code and code.strip():
            parts.append(code.strip())

    for pid in getattr(ch, "prerequisites", None) or []:
        _collect(pid)
    return "\n".join(parts)


def _reference_input(ch) -> str | None:
    mode = ch.validation.get("mode")
    if mode == "sql_result":
        return ch.answer.get("reference_sql")
    if mode == "exact":
        return ch.answer.get("value")
    if mode == "regex_tester":
        return ch.answer.get("value")
    if mode == "multiple_choice":
        return str(ch.validation.get("answer_id"))
    if mode == "test_cases":
        return ch.answer.get("reference_code")
    if mode == "freeform":
        return ch.answer.get("reference_code")
    return None
