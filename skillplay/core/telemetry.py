"""Anonymous, local-first telemetry (P10).

Tracks the *low first-try rate* per skill (fraction of challenges where the
first attempt was wrong). Stored locally in `progress["telemetry"]` by default.
If `settings.telemetry` is true, an anonymized aggregate is POSTed to the
configured leaderboard/telemetry URL. Nothing leaves the machine otherwise.
"""

from __future__ import annotations

import json
import os


def _low_first_try_rate(session) -> dict[str, float]:
    """Per-skill low first-try rate from a finished session."""
    totals: dict[str, list[bool]] = {}
    for ch in session.challenges:
        ft = session.first_tries.get(ch.id)
        if ft is None:
            continue
        totals.setdefault(ch.skill, []).append(ft)
    out: dict[str, float] = {}
    for skill, results in totals.items():
        if results:
            out[skill] = 1.0 - (sum(results) / len(results))
    return out


def record(progress: dict, session) -> None:
    """Update local telemetry and, if enabled, push an anonymized aggregate."""
    rates = _low_first_try_rate(session)
    if not rates:
        return
    local = progress.setdefault("telemetry", {})
    for skill, rate in rates.items():
        sk = local.setdefault(skill, {"samples": 0, "sum": 0.0})
        sk["samples"] += 1
        sk["sum"] += rate
    if not progress.get("settings", {}).get("telemetry"):
        return  # local-only unless explicitly enabled
    _post(progress, rates)


def _post(progress: dict, rates: dict[str, float]) -> None:
    url = os.environ.get("SKILLPLAY_TELEMETRY_URL") or progress.get("settings", {}).get(
        "leaderboard", {}
    ).get("url")
    if not url:
        return
    # Anonymized: no names, only aggregate rates keyed by skill.
    payload = json.dumps({"kind": "telemetry", "rates": rates}).encode("utf-8")
    try:
        import urllib.request

        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as _resp:
            pass
    except Exception:
        # Telemetry must never break the app.
        pass
