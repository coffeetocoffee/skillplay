"""Internationalization scaffolding (P10).

Offline, dependency-free. Strings are looked up by key; `set_language` switches
the active catalog (English is the default and fallback). A second language
(Spanish) exercises the path. Unknown keys fall back to English, then to the key.
"""

from __future__ import annotations

_LANG = "en"

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "app_title": "skillplay",
        "stats": "Stats",
        "daily_challenge": "Daily Challenge",
        "mixed": "Mixed (all skills)",
        "goals": "Goals",
        "achievements": "Achievements",
        "config": "Settings",
        "back_home": "Back to home",
        "session_complete": "Session complete",
        "xp_gained": "XP gained",
        "accuracy": "Accuracy",
        "best_combo": "Best combo",
        "streak": "Streak",
        "total_xp": "Total XP",
        "hint": "Hint",
        "skipped": "Skipped.",
        "your_answer": "Your answer",
        "no_snapshot": "No saved session to resume.",
        "resume": "Resume session",
        "level_up": "Level up!",
        "due_today": "Due today",
        "no_due": "Nothing due right now — take a break or explore a pack.",
        "practice": "Practice",
        "community": "Community packs",
        "adaptive": "Adaptive (model)",
        "generate": "Generate (fresh)",
        "mastery_exams": "Mastery exams",
        "exam_paper": "exam: {questions} questions",
        "exam_topup": "+{topup} from related ({related})",
        "learning_path": "Learning path",
        "start_path_all": "Start full learning path",
        "path_unlocked": "unlocked",
        "path_locked": "locked",
        "path_mastered": "mastered",
        "capstones": "Capstones",
        "build_artifact": "Build artifact",
        "mentor": "Mentor",
    },
    "es": {
        "app_title": "skillplay",
        "stats": "Estadísticas",
        "daily_challenge": "Reto diario",
        "mixed": "Mixto (todas las habilidades)",
        "goals": "Objetivos",
        "achievements": "Logros",
        "config": "Ajustes",
        "back_home": "Volver al inicio",
        "session_complete": "Sesión completada",
        "xp_gained": "XP ganada",
        "accuracy": "Precisión",
        "best_combo": "Mejor racha",
        "streak": "Racha",
        "total_xp": "XP total",
        "hint": "Pista",
        "skipped": "Omitido.",
        "your_answer": "Tu respuesta",
        "no_snapshot": "No hay sesión guardada para reanudar.",
        "resume": "Reanudar sesión",
        "level_up": "¡Subes de nivel!",
        "due_today": "Pendiente hoy",
        "no_due": "Nada pendiente ahora — descansa o explora un pack.",
        "practice": "Practicar",
        "community": "Packs de la comunidad",
        "adaptive": "Adaptativo (modelo)",
        "generate": "Generar (nuevo)",
        "mastery_exams": "Exámenes de maestría",
        "exam_paper": "examen: {questions} preguntas",
        "exam_topup": "+{topup} de habilidades afines ({related})",
        "learning_path": "Ruta de aprendizaje",
        "start_path_all": "Iniciar ruta completa",
        "path_unlocked": "desbloqueado",
        "path_locked": "bloqueado",
        "path_mastered": "dominado",
        "capstones": "Proyectos",
        "build_artifact": "Generar artefacto",
        "mentor": "Mentor",
    },
}


def set_language(lang: str) -> None:
    global _LANG
    _LANG = lang if lang in _STRINGS else "en"


def current_lang() -> str:
    """The active catalog language (V9: also drives challenge-content i18n)."""
    return _LANG


def t(key: str, **kwargs) -> str:
    catalog = _STRINGS.get(_LANG, _STRINGS["en"])
    text = catalog.get(key, _STRINGS["en"].get(key, key))
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            pass
    return text


def available_languages() -> list[str]:
    return sorted(_STRINGS.keys())
