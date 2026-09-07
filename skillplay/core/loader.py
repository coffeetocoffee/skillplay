"""Lesson pack discovery and parsing."""

from __future__ import annotations

import glob
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from platformdirs import user_data_dir

BUILTIN_PACKS = Path(__file__).resolve().parent.parent / "packs"

CHALLENGE_GLOB = "challenges/*.yaml"
PACK_MANIFEST = "pack.yaml"


@dataclass
class Challenge:
    id: str
    skill: str
    title: str
    topic: str
    difficulty: int
    xp: int
    type: str
    prompt: str
    answer: dict[str, Any]
    validation: dict[str, Any]
    context: dict[str, Any] = field(default_factory=dict)
    hints: list[str] = field(default_factory=list)
    explanation: str = ""
    options: list[dict[str, Any]] = field(default_factory=list)
    srs_reason: str = ""
    # V1 freeform tier: starter template pre-filled in the editor. Authored
    # top-level (`starter_code:`) with `validation.starter_code` as fallback.
    starter_code: str = ""
    # V4: prerequisite challenge ids that must be answered correctly before this one unlocks.
    prerequisites: list[str] = field(default_factory=list)
    # V9: per-language overrides for user-facing text (prompt/title/hints/explanation).
    translations: dict[str, dict[str, Any]] = field(default_factory=dict)

    def localized(self, field: str, lang: str | None = None) -> Any:
        """V9: return the translation for `field` in `lang` (or the active
        language), falling back to the base value when no translation exists."""
        from . import i18n

        lang = lang or i18n.current_lang()
        tr = self.translations.get(lang)
        if tr and field in tr and tr[field] not in (None, ""):
            return tr[field]
        return getattr(self, field)


@dataclass
class Pack:
    id: str
    name: str
    version: str
    skill: str
    description: str
    difficulty: str
    author: str
    challenges: list[Challenge] = field(default_factory=list)
    schema_version: int = 1
    tags: list[str] = field(default_factory=list)
    license: str = ""
    min_version: str = ""
    contributor: str = ""
    capstone: bool = False
    # V2: portfolio artifact metadata for capstone packs (the thing the chain builds).
    artifact: dict[str, Any] = field(default_factory=dict)
    # V9: per-language overrides for pack name/description.
    translations: dict[str, dict[str, Any]] = field(default_factory=dict)

    def localized(self, field: str, lang: str | None = None) -> Any:
        """V9: localized pack name/description (see Challenge.localized)."""
        from . import i18n

        lang = lang or i18n.current_lang()
        tr = self.translations.get(lang)
        if tr and field in tr and tr[field] not in (None, ""):
            return tr[field]
        return getattr(self, field)


def discovery_dirs() -> list[Path]:
    dirs: list[Path] = [BUILTIN_PACKS]
    user_pack = Path(user_data_dir("skillplay", appauthor=False)) / "packs"
    local_pack = Path.cwd() / "packs"
    for d in (user_pack, local_pack):
        if d.is_dir():
            dirs.append(d)
    return dirs


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_pack(pack_dir: Path) -> Pack | None:
    manifest = pack_dir / PACK_MANIFEST
    if not manifest.is_file():
        return None
    meta = _load_yaml(manifest)
    pack = Pack(
        id=meta.get("id", pack_dir.name),
        name=meta.get("name", pack_dir.name),
        version=str(meta.get("version", "0.0.0")),
        skill=meta.get("skill", meta.get("id", "unknown")),
        description=meta.get("description", ""),
        difficulty=meta.get("difficulty", "beginner"),
        author=meta.get("author", "unknown"),
        schema_version=int(meta.get("schema_version", 1)),
        tags=list(meta.get("tags", []) or []),
        license=meta.get("license", ""),
        min_version=meta.get("min_version", ""),
        contributor=meta.get("contributor", meta.get("author", "unknown")),
        capstone=bool(meta.get("capstone", False)),
        artifact=dict(meta.get("artifact", {}) or {}),
        translations=dict(meta.get("translations", {}) or {}),
    )
    entry = meta.get("entry", CHALLENGE_GLOB)
    for ch_path in sorted(glob.glob(str(pack_dir / entry))):
        data = _load_yaml(Path(ch_path))
        if not data:
            continue
        validation = data.get("validation", {})
        starter = data.get("starter_code", "") or validation.get("starter_code", "") or ""
        pack.challenges.append(
            Challenge(
                id=data["id"],
                skill=pack.skill,
                title=data.get("title", data["id"]),
                topic=data.get("topic", ""),
                difficulty=int(data.get("difficulty", 1)),
                xp=int(data.get("xp", 10)),
                type=data["type"],
                prompt=data.get("prompt", ""),
                answer=data.get("answer", {}),
                validation=validation,
                context=data.get("context", {}),
                hints=data.get("hints", []),
                explanation=data.get("explanation", ""),
                options=data.get("options", []),
                starter_code=starter,
                prerequisites=list(data.get("prerequisites", []) or []),
                translations=dict(data.get("translations", {}) or {}),
            )
        )
    # V2: a capstone challenge that builds on earlier functions can't be graded in
    # isolation, so inject the transitive prerequisite reference code into each
    # code challenge's `setup`. That makes both live grading and self-validation
    # resolve the earlier names, while the assembled artifact stays clean (it uses
    # each challenge's own reference code only).
    if pack.capstone:
        _resolve_capstone_setup(pack)
    return pack


def _resolve_capstone_setup(pack: Pack) -> None:
    by_id = {c.id: c for c in pack.challenges}
    code_modes = {"test_cases", "freeform"}
    for ch in pack.challenges:
        if ch.validation.get("mode") not in code_modes:
            continue
        prelude = _capstone_prelude(ch, by_id)
        if not prelude:
            continue
        existing = ch.validation.get("setup", "") or ""
        ch.validation["setup"] = (existing + "\n" + prelude).strip() if existing else prelude


def _capstone_prelude(ch: Challenge, by_id: dict) -> str:
    """Concatenated reference code of (transitive) in-pack prerequisites."""
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


def load_all_packs() -> list[Pack]:
    packs: list[Pack] = []
    seen: set[tuple[str, str]] = set()
    for base in discovery_dirs():
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            if not entry.is_dir():
                continue
            pack = load_pack(entry)
            if pack is None or not pack.challenges:
                continue
            key = (pack.author, pack.id)
            if key in seen:
                continue
            seen.add(key)
            packs.append(pack)
    return packs
