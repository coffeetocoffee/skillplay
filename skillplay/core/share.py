"""Shareable stats output (P8): Markdown snippet + SVG card.

The Markdown snippet is plain text; the card is an SVG string (no image
dependencies). PNG is intentionally out of scope (would require an imaging
library); SVG renders in any browser and most chat tools.
"""

from __future__ import annotations

from typing import Any


def markdown_snippet(prog: dict[str, Any]) -> str:
    lines = [
        "### skillplay stats",
        "",
        f"- Total XP: **{prog['total_xp']}**",
        f"- Streak: current {prog['streak']['current']} / longest {prog['streak']['longest']}",
    ]
    skills = prog.get("skills", {})
    if skills:
        lines.append("")
        lines.append("| Skill | XP | Level | Accuracy |")
        lines.append("|---|---|---|---|")
        for skill, rec in sorted(skills.items()):
            attempts = rec.get("attempts", 0)
            correct = rec.get("correct", 0)
            acc = (correct / attempts * 100) if attempts else 0
            lines.append(f"| {skill} | {rec.get('xp', 0)} | {rec.get('level', 1)} | {acc:.0f}% |")
    earned = prog.get("achievements", [])
    if earned:
        lines.append("")
        lines.append(f"Achievements: {len(earned)}")
    return "\n".join(lines) + "\n"


def svg_card(prog: dict[str, Any]) -> str:
    w, h = 480, 200
    s = prog.get("streak", {})
    skills = prog.get("skills", {})
    top = sorted(skills.items(), key=lambda kv: kv[1].get("xp", 0), reverse=True)[:3]
    skill_lines = "".join(
        f'<text x="24" y="{70 + i * 22}" class="s">{name}: {rec.get("xp", 0)} XP '
        f"(lvl {rec.get('level', 1)})</text>"
        for i, (name, rec) in enumerate(top)
    )
    ach = len(prog.get("achievements", []))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
  <style>
    .bg {{ fill: #0f172a; }}
    .t {{ fill: #e2e8f0; font: 700 26px sans-serif; }}
    .s {{ fill: #94a3b8; font: 400 16px sans-serif; }}
    .x {{ fill: #fbbf24; font: 700 18px sans-serif; }}
  </style>
  <rect class="bg" width="{w}" height="{h}" rx="14"/>
  <text x="24" y="40" class="t">skillplay</text>
  <text x="24" y="62" class="x">&#11088; {prog["total_xp"]} XP   &#128293; {s.get("current", 0)}d</text>
  {skill_lines}
  <text x="24" y="172" class="s">&#127942; {ach} achievements</text>
</svg>
"""
