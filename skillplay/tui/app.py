"""Textual TUI for skillplay."""

from __future__ import annotations

import os
import time

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Container, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Static, TextArea

from ..core import achievements as ach_mod
from ..core import adaptive as adaptive_mod
from ..core import capstone as capstone_mod
from ..core import engine, i18n, loader
from ..core import exam as exam_mod
from ..core import generate as generate_mod
from ..core import goals as goals_mod
from ..core import mentor as mentor_mod
from ..core import progress as progress_mod
from ..core import registry as registry_mod
from ..core import skillgraph as skillgraph_mod
from ..core import stats as stats_mod
from ..core import streak as streak_mod
from ..core.config import apply_config, save_config
from ..core.loader import Pack
from ..core.sound import beep

_SPARK = " ▂▃▄▅▆▇█"


def _sparkline(values: list[float], width: int = 24) -> str:
    if not values:
        return "(no data yet)"
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    step = max(1, int(len(values) / width))
    sample = values[::step][:width]
    return "".join(
        _SPARK[min(len(_SPARK) - 1, int((v - lo) / span * (len(_SPARK) - 1)))] for v in sample
    )


def _heatmap(dates: list[str], weeks: int = 10) -> str:
    """Render a simple calendar heatmap (last `weeks` weeks) from ISO dates."""
    from datetime import date, timedelta

    if not dates:
        return "(no daily challenges yet)"
    done = set(dates)
    today = date.today()
    start = today - timedelta(weeks=weeks, days=today.weekday())
    rows = []
    for wk in range(weeks):
        row = []
        for d in range(7):
            day = start + timedelta(weeks=wk, days=d)
            if day > today:
                row.append(" ")
            elif day.isoformat() in done:
                row.append("█")
            else:
                row.append("·")
        rows.append("".join(row))
    return "Mon\n" + "\n".join(rows) + f"\n{done and len(done)} day(s) done"


class HomeScreen(Screen):
    def compose(self) -> ComposeResult:
        prog = self.app.progress
        streak = prog["streak"]["current"]
        earned = len(prog.get("achievements", []))
        yield Header()
        with Container(id="home"):
            yield Static(f"[b]{i18n.t('app_title')}[/b]", id="brand")
            yield Static(
                f"🔥 {i18n.t('streak')}: {streak}   ⭐ {i18n.t('total_xp')}: {prog['total_xp']}   "
                f"🏅 {earned}",
                id="stats",
            )
            snap = progress_mod.load_session_snapshot()
            if snap and snap.get("challenge_ids"):
                yield Button(f"↩ {i18n.t('resume')}", id="resume-btn")
            yield Button(f"📊 {i18n.t('stats')}", id="stats-btn")
            yield Button(f"⭐ {i18n.t('daily_challenge')}", id="daily-btn")
            yield Button(f"🎲 {i18n.t('mixed')}", id="mixed-btn")
            due = engine.count_due_today(self.app.packs, prog)
            yield Button(f"📅 {i18n.t('due_today')} ({due})", id="due-btn")
            yield Button(f"🎯 {i18n.t('goals')}", id="goals-btn")
            yield Button(f"🏅 {i18n.t('achievements')}", id="ach-btn")
            yield Button(f"🏆 {i18n.t('mastery_exams')}", id="exam-btn")
            yield Button(f"🌐 {i18n.t('community')}", id="community-btn")
            yield Button(f"🧠 {i18n.t('adaptive')}", id="adaptive-btn")
            yield Button(f"🧭 {i18n.t('learning_path')}", id="path-btn")
            if capstone_mod.capstone_packs(self.app.packs):
                yield Button(f"🏗 {i18n.t('capstones')}", id="capstone-btn")
            yield Button(f"🎲 {i18n.t('generate')} (Python)", id="gen-btn")
            if generate_mod.test_cases_runtime_available("javascript"):
                yield Button(f"🎲 {i18n.t('generate')} (JS)", id="gen-js-btn")
            yield Button(f"🔤 {i18n.t('generate')} (regex)", id="gen-re-btn")
            yield Button(f"⚙ {i18n.t('config')}", id="config-btn")
            for idx, pack in enumerate(self.app.packs):
                label = f"{pack.localized('name')}  ({len(pack.challenges)} challenges)"
                if pack.tags:
                    label += f"  [{'/'.join(pack.tags)}]"
                yield Button(label, id=f"pack-{idx}")
        yield Footer()

    def on_show(self) -> None:
        if self.is_attached:
            prog = self.app.progress
            self.query_one("#stats", Static).update(
                f"🔥 {i18n.t('streak')}: {prog['streak']['current']}   "
                f"⭐ {i18n.t('total_xp')}: {prog['total_xp']}   "
                f"🏅 {len(prog.get('achievements', []))}"
            )

    @on(Button.Pressed)
    def pick(self, event: Button.Pressed) -> None:
        if not event.button.id:
            return
        bid = event.button.id
        if bid == "stats-btn":
            self.app.push_screen(StatsScreen())
            return
        if bid == "goals-btn":
            self.app.push_screen(GoalsScreen())
            return
        if bid == "ach-btn":
            self.app.push_screen(AchievementsScreen())
            return
        if bid == "exam-btn":
            self.app.push_screen(ExamScreen())
            return
        if bid == "community-btn":
            self.app.push_screen(CommunityScreen())
            return
        if bid == "config-btn":
            self.app.push_screen(ConfigScreen())
            return
        if bid == "daily-btn":
            ch = engine.daily_challenge(self.app.packs)
            if ch is None:
                return
            daily_pack = Pack(
                id=f"daily-{progress_mod.today_str()}",
                name=i18n.t("daily_challenge"),
                version="0.0.0",
                skill=ch.skill,
                description="One challenge, chosen for today.",
                difficulty="mixed",
                author="core",
                challenges=[ch],
            )
            self.app.push_screen(PlayScreen(daily_pack, daily=True))
            return
        if bid == "mixed-btn":
            mixed_pack = Pack(
                id="mixed",
                name=i18n.t("mixed"),
                version="0.0.0",
                skill="mixed",
                description="A blended session across all your packs.",
                difficulty="mixed",
                author="core",
                challenges=[],
            )
            self.app.push_screen(PlayScreen(mixed_pack))
            return
        if bid == "due-btn":
            size = self.app.progress["settings"].get("session_size", 8)
            due = engine.select_due_today(self.app.packs, self.app.progress, size)
            if not due:
                self.app.notify(i18n.t("no_due"))
                return
            due_pack = Pack(
                id="due-today",
                name=i18n.t("due_today"),
                version="0.0.0",
                skill="mixed",
                description="Only your SRS-due (and new) cards, across all skills.",
                difficulty="mixed",
                author="core",
                challenges=due,
            )
            self.app.push_screen(PlayScreen(due_pack))
            return
        if bid == "resume-btn":
            snap = progress_mod.load_session_snapshot()
            session = engine.resume_session(snap, self.app.packs) if snap else None
            if session is None:
                self.app.notify(i18n.t("no_snapshot"))
                return
            self.app.push_screen(PlayScreen(session=session))
            return
        if bid == "adaptive-btn":
            size = self.app.progress["settings"].get("session_size", 8)
            chosen = adaptive_mod.select_adaptive_v2_pack(self.app.packs, self.app.progress, size)
            if not chosen:
                self.app.notify(i18n.t("no_due"))
                return
            self.app.push_screen(PlayScreen(session=engine.Session("mixed", chosen)))
            return
        if bid == "path-btn":
            self.app.push_screen(PathScreen())
            return
        if bid == "capstone-btn":
            self.app.push_screen(CapstoneScreen())
            return
        if bid == "gen-btn":
            size = self.app.progress["settings"].get("session_size", 8)
            pk = generate_mod.generate_pack("python", size)
            self.app.push_screen(PlayScreen(pk))
            return
        if bid == "gen-js-btn":
            size = self.app.progress["settings"].get("session_size", 8)
            pk = generate_mod.generate_pack("javascript", size, lang="javascript")
            self.app.push_screen(PlayScreen(pk))
            return
        if bid == "gen-re-btn":
            size = self.app.progress["settings"].get("session_size", 8)
            pk = generate_mod.generate_regex_pack(size)
            self.app.push_screen(PlayScreen(pk))
            return
        if bid.startswith("pack-"):
            idx = int(bid.split("-", 1)[1])
            pack = self.app.packs[idx]
            self.app.push_screen(PlayScreen(pack))


class PlayScreen(Screen):
    def __init__(
        self, pack: Pack | None = None, daily: bool = False, session: engine.Session | None = None
    ) -> None:
        super().__init__()
        self.pack = pack
        self.daily = daily
        self.session = session
        self.history: list[str] = []
        self.hist_pos = 0
        self._finalized = False
        self.hint_idx = -1
        self.opt_buttons: list[Button] = []
        self.opt_map: dict[str, str] = {}
        self._skill_xp_running: dict[str, int] = {}
        # V7: the most recent graded attempt, so the Mentor can explain it on demand.
        self._last_attempt: dict | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="play"):
            yield Label("", id="hud")
            yield Static("", id="prompt")
            yield Static("", id="reason")
            yield Static("", id="schema")
            with Vertical(id="options"):
                for i in range(8):
                    yield Button("", id=f"opt{i}", classes="opt-btn")
            yield Input(
                placeholder="Your answer…  (Ctrl+H hint, Ctrl+S skip, Ctrl+U/D rate, Ctrl+M mentor, Esc quit)",
                id="answer",
            )
            yield TextArea("", id="code", language="python")
            yield Button("▶ Run tests  (Ctrl+Enter)", id="run-btn")
            yield Button(f"🧠 {i18n.t('mentor')}  (Ctrl+M)", id="mentor-btn")
            yield Static("", id="feedback")
            yield Static("", id="explanation")
        yield Footer()

    def on_mount(self) -> None:
        self.opt_buttons = [self.query_one(f"#opt{i}", Button) for i in range(8)]
        self.query_one("#mentor-btn", Button).display = False
        if self.session is None:
            size = self.app.progress["settings"].get("session_size", 8)
            if self.pack is not None and self.pack.id == "mixed":
                challenges = engine.select_mixed(self.app.packs, self.app.progress, size)
                skill = "mixed"
            else:
                pack = self.pack or self.app.packs[0]
                challenges = engine.select_challenges(pack, self.app.progress, size)
                skill = pack.skill
            self.session = engine.Session(skill, challenges, daily=self.daily)
        # Seed running XP so we can detect level-ups mid-session.
        for ch in self.session.challenges:
            self._skill_xp_running.setdefault(ch.skill, 0)
        for skill in self._skill_xp_running:
            self._skill_xp_running[skill] = self.app.progress["skills"].get(skill, {}).get("xp", 0)
        self._save_snapshot()
        self._render_current()

    def _save_snapshot(self) -> None:
        if self.session is not None:
            progress_mod.save_session_snapshot(engine.snapshot(self.session))

    def _render_current(self) -> None:
        ch = self.session.current
        if ch is None:
            self._finish()
            return
        self.hint_idx = -1
        # Section E: mark when this challenge started so engine.submit can record
        # a per-attempt latency (used by the local adaptive model's features).
        self.session._challenge_started = time.monotonic()
        skill_xp = self._skill_xp_running.get(ch.skill, 0)
        self.query_one("#hud", Label).update(
            f"Q{self.session.index + 1}/{len(self.session.challenges)}  "
            f"XP {skill_xp}  combo x{engine.combo_multiplier(self.session.combo)}"
        )
        self.query_one("#prompt", Static).update(ch.localized("prompt"))
        if ch.validation.get("mode") == "freeform":
            self.query_one("#feedback", Static).update(
                "[cyan]Freeform: write the function from scratch — tests are hidden.[/cyan]"
            )
        self.query_one("#feedback", Static).update("")
        self.query_one("#explanation", Static).update("")
        schema = self.query_one("#schema", Static)
        reason = self.query_one("#reason", Static)
        if ch.srs_reason:
            reason.update(f"[dim]why: {ch.srs_reason}[/dim]")
            reason.display = True
        else:
            reason.display = False
        if ch.type == "sql_query" and ch.context.get("schema_preview"):
            schema.update(f"[dim]schema: {ch.context['schema_preview']}[/dim]")
            schema.display = True
        else:
            schema.display = False
        opts = self.query_one("#options", Vertical)
        inp = self.query_one("#answer", Input)
        code = self.query_one("#code", TextArea)
        run_btn = self.query_one("#run-btn", Button)
        self.opt_map.clear()
        is_code = ch.validation.get("mode") in ("test_cases", "freeform")
        if ch.validation.get("mode") == "multiple_choice":
            inp.display = False
            code.display = False
            run_btn.display = False
            opts.display = True
            for i, btn in enumerate(self.opt_buttons):
                if i < len(ch.options):
                    opt = ch.options[i]
                    btn.label = f"{opt['id'].upper()}. {opt['text']}"
                    btn.display = True
                    self.opt_map[btn.id] = opt["id"]
                else:
                    btn.display = False
        elif is_code:
            # A1: real code UX — multi-line editor for fix-bug / JS / freeform.
            inp.display = False
            opts.display = False
            for btn in self.opt_buttons:
                btn.display = False
            code.display = True
            code.language = (
                "javascript"
                if (ch.validation.get("lang") or "python").lower() in ("js", "javascript")
                else "python"
            )
            # V1 freeform: pre-fill the starter template so the player writes
            # the function from scratch (hidden tests, not a broken snippet).
            start = self.session.current.starter_code or ""
            code.text = start
            run_btn.display = True
            if ch.validation.get("mode") == "freeform":
                run_btn.label = "▶ Run hidden tests  (Ctrl+Enter)"
            else:
                run_btn.label = "▶ Run tests  (Ctrl+Enter)"
            code.focus()
        else:
            opts.display = False
            code.display = False
            run_btn.display = False
            inp.display = True
            inp.value = ""
            for btn in self.opt_buttons:
                btn.display = False

    def _grade(self, user_input: str) -> None:
        res = engine.submit(self.session, user_input, self.app.progress, allow_retry=True)
        fb = self.query_one("#feedback", Static)
        expl = self.query_one("#explanation", Static)
        # V7: remember this attempt so the Mentor can explain it on demand.
        ch = self.session.current
        if ch is not None:
            self._last_attempt = {
                "ch": ch,
                "user_input": user_input,
                "result": res,
                "mistake_type": (res.mistake_type or None),
            }
            self.query_one("#mentor-btn", Button).display = True
        if res.correct:
            fb.update(f"[green]+{res.xp_gained} XP correct![/green]")
            expl.update(
                f"[dim]{(self.session.current and self.session.current.localized('explanation')) or ''}[/dim]"
            )
            self._maybe_level_up(res)
            self.session.results.append(res)
            self.session.index += 1
            beep("correct", self.app.progress["settings"].get("sound", False))
            self._save_snapshot()
            self._render_current()
        elif res.retried:
            fb.update(f"[yellow]{res.detail} — one retry allowed[/yellow]")
        else:
            fb.update(f"[red]{res.detail}[/red]")
            self.session.results.append(res)
            self.session.index += 1
            beep("wrong", self.app.progress["settings"].get("sound", False))
            self._save_snapshot()
            self._render_current()

    def _maybe_level_up(self, res) -> None:
        skill = res.skill
        before = progress_mod.level_for_xp(self._skill_xp_running.get(skill, 0))
        self._skill_xp_running[skill] = self._skill_xp_running.get(skill, 0) + res.xp_gained
        after = progress_mod.level_for_xp(self._skill_xp_running[skill])
        if after > before:
            beep("level_up", self.app.progress["settings"].get("sound", False))
            self.query_one("#feedback", Static).update(
                f"[green]+{res.xp_gained} XP correct! {i18n.t('level_up')}[/green]"
            )

    def _finish(self) -> None:
        progress_mod.clear_session_snapshot()
        if not self._finalized:
            if self.session.results:
                engine.finalize(self.session, self.app.progress)
            # V6: grade a mastery exam and persist the certification result.
            if getattr(self.session, "exam_skill", None) and not self.session.exam_result:
                result = exam_mod.certify(self.session, self.app.progress)
                self.session.exam_result = result
                progress_mod.save(self.app.progress)
                if result["passed"]:
                    self.app.notify(
                        f"Certified {result['skill']} at level {result['level']}! "
                        f"({result['accuracy']}%)"
                    )
                else:
                    self.app.notify(
                        f"Exam not passed: {result['accuracy']}% (need 90%). "
                        f"Level stays {result['level']}."
                    )
            self._finalized = True
        self.app.pop_screen()
        self.app.push_screen(SummaryScreen(self.session))

    @on(Input.Submitted)
    def submit(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if value:
            if not self.history or self.history[-1] != value:
                self.history.append(value)
            self.hist_pos = len(self.history)
        self._grade(value)

    @on(Button.Pressed)
    def option_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "run-btn":
            self._grade(self.query_one("#code", TextArea).text)
            return
        if bid == "mentor-btn":
            self._show_mentor()
            return
        if bid in self.opt_map:
            self._grade(self.opt_map[bid])

    def on_key(self, event) -> None:
        if event.key == "escape":
            self._finish()
        elif event.key == "ctrl+h":
            ch = self.session.current
            if ch and ch.hints:
                hints = ch.localized("hints")
                self.hint_idx += 1
                if self.hint_idx < len(hints):
                    self.query_one("#feedback", Static).update(
                        f"[cyan]{i18n.t('hint')} {self.hint_idx + 1}/{len(hints)}: {hints[self.hint_idx]}[/cyan]"
                    )
                else:
                    self.query_one("#feedback", Static).update("[cyan](no more hints)[/cyan]")
        elif event.key == "ctrl+s":
            engine.skip_current(self.session)
            self.query_one("#feedback", Static).update(f"[yellow]{i18n.t('skipped')}[/yellow]")
            self.query_one("#explanation", Static).update("")
            self._save_snapshot()
            self._render_current()
        elif event.key == "ctrl+e":
            ch = self.session.current
            if ch and ch.explanation:
                self.query_one("#explanation", Static).update(f"[dim]{ch.explanation}[/dim]")
        elif event.key == "ctrl+enter":
            if self.query_one("#code", TextArea).display:
                self._grade(self.query_one("#code", TextArea).text)
        elif event.key == "ctrl+m":
            self._show_mentor()
        elif event.key in ("ctrl+u", "ctrl+d"):
            self._rate_explanation(event.key == "ctrl+u")
        elif event.key in ("up", "down") and self.query_one("#answer", Input).display:
            self._navigate_history(event.key)

    def _show_mentor(self) -> None:
        """V7: explain the most recent attempt like a senior dev would."""
        if self._last_attempt is None:
            return
        ch = self._last_attempt["ch"]
        req = mentor_mod.MentorRequest(
            challenge=ch,
            user_input=self._last_attempt["user_input"],
            correct=self._last_attempt["result"].correct,
            detail=self._last_attempt["result"].detail,
            mistake_type=self._last_attempt["mistake_type"],
            language=ch.validation.get("lang") or "python",
        )
        text = mentor_mod.explain(req, self.app.progress)
        self.query_one("#explanation", Static).update(f"[dim]🧠 Mentor:[/dim]\n{text}")
        self.query_one("#explanation", Static).display = True

    def _rate_explanation(self, up: bool) -> None:
        ch = self.session.current
        if ch is None:
            return
        fb = self.app.progress.setdefault("feedback", {})
        rec = fb.setdefault(ch.id, {"rating": None, "count": 0})
        rec["rating"] = "up" if up else "down"
        rec["count"] = rec.get("count", 0) + 1
        progress_mod.save(self.app.progress)
        label = "👍" if up else "👎"
        self.query_one("#feedback", Static).update(
            f"[cyan]Rated {label} — thanks for the feedback![/cyan]"
        )

    def _navigate_history(self, key: str) -> None:
        if not self.history:
            return
        if key == "up":
            if self.hist_pos > 0:
                self.hist_pos -= 1
        else:
            if self.hist_pos < len(self.history) - 1:
                self.hist_pos += 1
            else:
                self.hist_pos = len(self.history)
                self.query_one("#answer", Input).value = ""
                return
        self.query_one("#answer", Input).value = self.history[self.hist_pos]


class SummaryScreen(Screen):
    def __init__(self, session: engine.Session) -> None:
        super().__init__()
        self.session = session

    def compose(self) -> ComposeResult:
        prog = self.app.progress
        streak_mod.update_streak(prog["streak"])
        progress_mod.save(prog)
        total = len(self.session.challenges)
        acc = self.session.correct_count / total if total else 0
        earned = prog.get("achievements", [])
        lines = [
            f"[b]{i18n.t('session_complete')}[/b]",
            f"{i18n.t('xp_gained')}: {self.session.xp_gained}",
            f"{i18n.t('accuracy')}: {acc:.0%}",
            f"{i18n.t('best_combo')}: x{self.session.best_combo}",
        ]
        if self.session.daily:
            lines.append(
                f"⭐ {i18n.t('daily_challenge')} done ({len(prog.get('daily', {}).get('dates', []))} total)"
            )
        if earned:
            names = [a["name"] for a in ach_mod.ACHIEVEMENTS if a["id"] in earned]
            lines.append(f"🏅 {', '.join(names)}")
        exam = getattr(self.session, "exam_result", None)
        if exam:
            if exam["passed"]:
                lines.append(
                    f"🏆 Certified [b]{exam['skill']}[/b] at level {exam['level']} "
                    f"({exam['accuracy']}%)"
                )
            else:
                lines.append(
                    f"🏆 Exam result: {exam['accuracy']}% — not certified "
                    f"(need 90%, level stays {exam['level']})."
                )
        yield Header()
        with Container(id="summary"):
            for i, line in enumerate(lines):
                yield Static(line, id=f"sum-{i}")
            yield Button(i18n.t("back_home"), id="home")
        yield Footer()

    @on(Button.Pressed)
    def home(self, event: Button.Pressed) -> None:
        self.app.pop_screen()


class StatsScreen(Screen):
    def compose(self) -> ComposeResult:
        prog = self.app.progress
        # W6: group packs by skill so readiness covers all packs of a skill.
        skill_packs: dict[str, list] = {}
        for p in self.app.packs:
            skill_packs.setdefault(getattr(p, "skill", None) or p.id, []).append(p)
        lines = [f"[b]{i18n.t('stats')}[/b]", ""]
        lines.append(f"⭐ {i18n.t('total_xp')}: {prog['total_xp']}")
        s = prog["streak"]
        lines.append(f"🔥 {i18n.t('streak')}: current {s['current']} / longest {s['longest']}")
        lines.append("")
        lines.append("[b]Per skill[/b]")
        for skill, rec in sorted(prog["skills"].items()):
            attempts = rec.get("attempts", 0)
            correct = rec.get("correct", 0)
            acc = (correct / attempts * 100) if attempts else 0
            rd = stats_mod.readiness(prog, skill_packs.get(skill, []))
            hl = stats_mod.half_life_for_skill(prog, skill, skill_packs.get(skill, []))
            hl_str = f"{hl}d" if hl else "n/a"
            lines.append(
                f"  {skill}: lvl {rec.get('level', 1)} | {rec.get('xp', 0)} XP | "
                f"{acc:.0f}% acc | {len(rec.get('completed_ids', []))} done | "
                f"readiness {rd}% ({stats_mod.readiness_label(rd)}) | "
                f"memory {hl_str}"
            )
        xp_hist = list(prog.get("xp_history", {}).values())
        acc_hist = [round(v * 100) for v in prog.get("accuracy_history", {}).values()]
        yield Header()
        with Container(id="stats-screen"):
            yield Static("\n".join(lines), id="stats-body")
            yield Static(f"XP/day sparkline: {_sparkline(xp_hist)}", id="spark-xp")
            yield Static(f"Accuracy/day sparkline: {_sparkline(acc_hist)}", id="spark-acc")
            yield Static(
                "Daily challenge heatmap:\n" + _heatmap(prog.get("daily", {}).get("dates", [])),
                id="heatmap",
            )
            yield Button(i18n.t("back_home"), id="home")
        yield Footer()

    @on(Button.Pressed)
    def home(self, event: Button.Pressed) -> None:
        self.app.pop_screen()


class CommunityScreen(Screen):
    """D + V8: discoverable community packs plus the content flywheel - install,
    rate (1-5 stars), and publish your own packs from the TUI."""

    def compose(self) -> ComposeResult:
        prog = self.app.progress
        self._entries = {p["name"]: p for p in registry_mod.available_packs(progress=prog)}
        yield Header()
        with Container(id="community-screen"):
            yield Static(f"[b]🌐 {i18n.t('community')}[/b]", id="community-body")
            yield Static(
                "[dim]Discover, install, rate, and publish packs. Ratings & download "
                "counts power the community flywheel.[/dim]"
            )
            if not self._entries:
                yield Static("(no packs found in the index)")
            for name, p in sorted(self._entries.items()):
                yield Static(self._line(name), id=f"line-{name}")
                if p["installed"]:
                    yield Button("★ Rate", id=f"rate-{name}")
                    yield Button("📤 Publish", id=f"publish-{name}")
                else:
                    yield Button(f"Install {name}", id=f"inst-{name}")
            yield Button(i18n.t("back_home"), id="home")
        yield Footer()

    def _line(self, name: str) -> str:
        p = self._entries[name]
        rating = int(p.get("rating", 0) or 0)
        stars = "★" * rating + "☆" * (5 - rating)
        dl = p.get("downloads", 0)
        ur = self.app.progress.get("ratings", {}).get(name)
        ur_s = f"  your rating: {'★' * ur}" if ur else ""
        return (
            f"  {name} [{p['skill']}]  {stars} ({dl} downloads){ur_s}\n"
            f"     [dim]{p['description']}[/dim]"
        )

    @on(Button.Pressed)
    def on_press(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "home":
            self.app.pop_screen()
            return
        if bid.startswith("inst-"):
            name = bid[len("inst-") :]
            try:
                registry_mod.install_from_index(name)
                self.app.notify(f"Installed '{name}' — restart to see it on Home.")
            except Exception as exc:
                self.app.notify(f"Install failed: {exc}")
            self.app.pop_screen()
            self.app.push_screen(CommunityScreen())
            return
        if bid.startswith("rate-"):
            name = bid[len("rate-") :]
            cur = self.app.progress.get("ratings", {}).get(name, 0)
            new = (cur + 1) % 6  # cycle 0..5
            registry_mod.rate_pack(name, new, progress=self.app.progress)
            progress_mod.save(self.app.progress)
            self.query_one(f"#line-{name}", Static).update(self._line(name))
            self.app.notify(f"Rated {name}: {'★' * new if new else 'cleared'}")
            return
        if bid.startswith("publish-"):
            name = bid[len("publish-") :]
            pack_dir = registry_mod.USER_PACKS / name
            base = self.app.progress["settings"].get("leaderboard", {}).get("url") or ""
            res = registry_mod.publish_pack(pack_dir, base_url=base or None)
            if res.get("published"):
                self.app.notify(f"Published {name} → {res['url']}")
            else:
                msg = f"Bundled {name} → {res['bundle']}"
                if res.get("error"):
                    msg += f" (server push skipped: {res['error']})"
                self.app.notify(msg)
            return


class GoalsScreen(Screen):
    def compose(self) -> ComposeResult:
        prog = self.app.progress
        packs_by_id = {p.id: p for p in self.app.packs}
        statuses = {s["id"]: s for s in goals_mod.status(prog)}
        yield Header()
        with Container(id="goals-screen"):
            yield Static(f"[b]🎯 {i18n.t('goals')}[/b]", id="goals-body")
            for goal in goals_mod.GOALS:
                st = statuses.get(goal["id"])
                if st is None:
                    continue
                mark = "✅" if st["done"] else "⬜"
                yield Static(
                    f"  {mark} {goal['name']} — {st['completed']}/{st['total']}\n"
                    f"     [dim]{goal['description']}[/dim]"
                )
                pk = packs_by_id.get(goal["pack"])
                if pk is not None:
                    # B: each path is "self-adjusting" — its Practice button starts
                    # an adaptive-ordered session (weakest cards first).
                    yield Button(f"▶ {i18n.t('practice')}: {goal['name']}", id=f"goal-{goal['id']}")
            yield Button(i18n.t("back_home"), id="home")
        yield Footer()

    @on(Button.Pressed)
    def on_press(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "home":
            self.app.pop_screen()
            return
        if bid.startswith("goal-"):
            gid = bid[len("goal-") :]
            goal = next((g for g in goals_mod.GOALS if g["id"] == gid), None)
            if goal is None:
                return
            pk = next((p for p in self.app.packs if p.id == goal["pack"]), None)
            if pk is None:
                return
            ordered = engine.adaptive_order(pk, self.app.progress)
            session = engine.Session(pk.skill, ordered)
            self.app.push_screen(PlayScreen(session=session))


class AchievementsScreen(Screen):
    def compose(self) -> ComposeResult:
        earned = set(self.app.progress.get("achievements", []))
        lines = [f"[b]🏅 {i18n.t('achievements')}[/b]", ""]
        for a in ach_mod.ACHIEVEMENTS:
            mark = "✅" if a["id"] in earned else "🔒"
            lines.append(f"  {mark} {a['name']} — {a['description']}")
        yield Header()
        with Container(id="ach-screen"):
            yield Static("\n".join(lines), id="ach-body")
            yield Button(i18n.t("back_home"), id="home")
        yield Footer()

    @on(Button.Pressed)
    def home(self, event: Button.Pressed) -> None:
        self.app.pop_screen()


class ExamScreen(Screen):
    """V6: pick a skill and take a randomized mastery exam."""

    def compose(self) -> ComposeResult:
        prog = self.app.progress
        statuses = exam_mod.exam_status(prog)
        yield Header()
        with Container(id="exam-screen"):
            yield Static(f"[b]🏆 {i18n.t('mastery_exams')}[/b]", id="exam-body")
            yield Static(
                "[dim]Randomized mixed exam per skill. Score ≥ 90% to certify the "
                "next level (difficulty tier). Re-taking raises your certified level.[/dim]"
            )
            if not statuses:
                yield Static("(no skills available yet)")
            for st in statuses:
                if st["level"] > 0:
                    state = (
                        f"certified level {st['level']}/{st['max_level']} (best {st['accuracy']}%)"
                    )
                else:
                    state = "not yet certified"
                yield Static(f"  {st['skill']}: {state}")
                if st["max_level"] >= st["next_target"]:
                    yield Button(
                        f"Take exam (target L{st['next_target']})", id=f"exam-{st['skill']}"
                    )
                else:
                    yield Static("    [dim](max level reached)[/dim]")
                yield Static(i18n.t("exam_paper", questions=st["questions"]))
                if st["topup"] > 0:
                    yield Static(
                        i18n.t(
                            "exam_topup",
                            topup=st["topup"],
                            related=", ".join(st["related"]),
                        )
                    )
            yield Button(i18n.t("back_home"), id="home")
        yield Footer()

    @on(Button.Pressed)
    def on_press(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "home":
            self.app.pop_screen()
            return
        if bid.startswith("exam-"):
            skill = bid[len("exam-") :]
            session = exam_mod.build_exam(skill, self.app.progress)
            if session is None:
                self.app.notify("No content for that skill yet.")
                return
            self.app.push_screen(PlayScreen(session=session))


class ConfigScreen(Screen):
    def __init__(self) -> None:
        super().__init__()
        self._sound = False
        self._telemetry = False
        self._theme = "dark"
        self._language = "en"
        self._mentor_backend = "local"

    def compose(self) -> ComposeResult:
        settings = self.app.progress["settings"]
        self._sound = bool(settings.get("sound", False))
        self._telemetry = bool(settings.get("telemetry", False))
        self._theme = settings.get("theme", "dark")
        self._language = settings.get("language", "en")
        self._mentor_backend = settings.get("mentor_backend", "local")
        lb = settings.get("leaderboard", {})
        yield Header()
        with Container(id="config-screen"):
            yield Static("[b]⚙ Settings[/b]")
            yield Static("Session size:")
            yield Input(value=str(settings.get("session_size", 8)), id="cfg-size")
            yield Static("Leaderboard name:")
            yield Input(value=str(lb.get("name", "anon")), id="cfg-name")
            yield Button(self._sound_label(), id="cfg-sound")
            yield Button(self._telemetry_label(), id="cfg-telemetry")
            yield Button(self._theme_label(), id="cfg-theme")
            yield Button(self._language_label(), id="cfg-language")
            yield Static("Mentor backend (V7): local / openai / llama_cpp")
            yield Button(self._mentor_label(), id="cfg-mentor")
            yield Static("Mentor API base URL:")
            yield Input(value=str(settings.get("mentor_base_url", "")), id="cfg-mbase")
            yield Static("Mentor API key (BYO, stored locally):")
            yield Input(value=str(settings.get("mentor_api_key", "")), id="cfg-mkey")
            yield Static("Mentor model:")
            yield Input(value=str(settings.get("mentor_model", "")), id="cfg-mmodel")
            yield Button("Save", id="cfg-save")
            yield Button(i18n.t("back_home"), id="home")
        yield Footer()

    def _sound_label(self) -> str:
        return f"Sound: {'on' if self._sound else 'off'}"

    def _telemetry_label(self) -> str:
        return f"Telemetry: {'on' if self._telemetry else 'off (local-only)'}"

    def _theme_label(self) -> str:
        return f"Theme: {self._theme}"

    def _language_label(self) -> str:
        return f"Language: {self._language}"

    def _mentor_label(self) -> str:
        return f"Mentor: {self._mentor_backend}"

    @on(Button.Pressed)
    def on_press(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "cfg-sound":
            self._sound = not self._sound
            event.button.label = self._sound_label()
        elif bid == "cfg-telemetry":
            self._telemetry = not self._telemetry
            event.button.label = self._telemetry_label()
        elif bid == "cfg-theme":
            order = ["dark", "light", "high_contrast"]
            self._theme = order[(order.index(self._theme) + 1) % len(order)]
            event.button.label = self._theme_label()
        elif bid == "cfg-language":
            langs = i18n.available_languages()
            self._language = langs[(langs.index(self._language) + 1) % len(langs)]
            event.button.label = self._language_label()
        elif bid == "cfg-mentor":
            order = ["local", "openai", "llama_cpp"]
            self._mentor_backend = order[(order.index(self._mentor_backend) + 1) % len(order)]
            event.button.label = self._mentor_label()
        elif bid == "cfg-save":
            self._save()
        elif bid == "home":
            self.app.pop_screen()

    def _save(self) -> None:
        settings = self.app.progress.setdefault("settings", {})
        try:
            settings["session_size"] = max(1, int(self.query_one("#cfg-size", Input).value or 8))
        except ValueError:
            settings["session_size"] = 8
        settings["sound"] = self._sound
        settings["telemetry"] = self._telemetry
        settings["theme"] = self._theme
        settings["language"] = self._language
        settings["mentor_backend"] = self._mentor_backend
        settings["mentor_base_url"] = self.query_one("#cfg-mbase", Input).value or ""
        settings["mentor_api_key"] = self.query_one("#cfg-mkey", Input).value or ""
        settings["mentor_model"] = self.query_one("#cfg-mmodel", Input).value or ""
        settings.setdefault("leaderboard", {})["name"] = (
            self.query_one("#cfg-name", Input).value or "anon"
        )
        save_config(self.app.progress)
        apply_config(self.app.progress)
        i18n.set_language(self._language)
        self.app._apply_theme()
        self.app.notify("Settings saved.")


class PathScreen(Screen):
    """V4: a curriculum view — per-skill unlock progress plus a one-button session
    that walks the next unlockable frontier across all (or one) skills."""

    def compose(self) -> ComposeResult:
        prog = self.app.progress
        stats = skillgraph_mod.frontier_stats(self.app.packs, prog)
        yield Header()
        with Container(id="path-screen"):
            yield Static(f"[b]🧭 {i18n.t('learning_path')}[/b]")
            yield Static(
                "[dim]Challenges unlock as you master their prerequisites. "
                "Start a path to practice only the next reachable frontier.[/dim]"
            )
            if not stats:
                yield Static("(no skills available yet)")
            for skill, st in sorted(stats.items()):
                yield Static(
                    f"  {skill}: {i18n.t('path_unlocked')} {st['unlocked']} / "
                    f"{i18n.t('path_locked')} {st['locked']}   "
                    f"({i18n.t('path_mastered')} {st['mastered']}/{st['total']})"
                )
                yield Button(f"▶ {i18n.t('practice')}: {skill}", id=f"path-{skill}")
            if stats:
                yield Button(f"🧭 {i18n.t('start_path_all')}", id="path-all")
            yield Button(i18n.t("back_home"), id="home")
        yield Footer()

    @on(Button.Pressed)
    def on_press(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "home":
            self.app.pop_screen()
            return
        size = self.app.progress["settings"].get("session_size", 8)
        if bid == "path-all":
            chosen = engine.select_path(self.app.packs, self.app.progress, size)
            skill = "mixed"
            packs = self.app.packs
        elif bid.startswith("path-"):
            skill = bid[len("path-") :]
            packs = [p for p in self.app.packs if (getattr(p, "skill", None) or p.id) == skill]
            chosen = engine.select_path(packs, self.app.progress, size)
        else:
            return
        if not chosen:
            self.app.notify(i18n.t("no_due"))
            return
        self.app.push_screen(PlayScreen(session=engine.Session(skill, chosen)))


class CapstoneScreen(Screen):
    """V2: portfolio view — practice a capstone chain and build the artifact it
    assembles from your own solved challenges."""

    def compose(self) -> ComposeResult:
        prog = self.app.progress
        packs = capstone_mod.capstone_packs(self.app.packs)
        yield Header()
        with Container(id="capstone-screen"):
            yield Static(f"[b]🏗 {i18n.t('capstones')}[/b]")
            yield Static(
                "[dim]Solve a capstone's challenges, then build the artifact it assembles "
                "from your own code. Re-building always reflects your latest solutions.[/dim]"
            )
            if not packs:
                yield Static("(no capstone packs installed)")
            for idx, pack in enumerate(packs):
                st = capstone_mod.capstone_progress(prog, pack)
                built = "✅ built" if st["built"] else "not built"
                yield Static(
                    f"  {pack.name}: {st['solved']}/{st['total']} challenges solved ({built})"
                )
                yield Button(f"▶ {i18n.t('practice')}: {pack.name}", id=f"cap-{idx}")
                yield Button(f"🏗 {i18n.t('build_artifact')}: {pack.name}", id=f"build-{idx}")
            yield Static("", id="capstone-result")
            yield Button(i18n.t("back_home"), id="home")
        yield Footer()

    @on(Button.Pressed)
    def on_press(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "home":
            self.app.pop_screen()
            return
        packs = capstone_mod.capstone_packs(self.app.packs)
        if bid.startswith("cap-"):
            idx = int(bid.split("-", 1)[1])
            pack = packs[idx]
            size = self.app.progress["settings"].get("session_size", 8)
            chosen = engine.select_path([pack], self.app.progress, size)
            if not chosen:
                self.app.notify(i18n.t("no_due"))
                return
            self.app.push_screen(PlayScreen(session=engine.Session(pack.skill, chosen)))
            return
        if bid.startswith("build-"):
            idx = int(bid.split("-", 1)[1])
            pack = packs[idx]
            res = capstone_mod.build_artifact(self.app.progress, pack)
            progress_mod.save(self.app.progress)
            self.query_one("#capstone-result", Static).update(
                f"[green]Built {res['filename']} ({res['solved']}/{res['total']} from your code)[/green]\n"
                f"[dim]{res['path']}[/dim]"
            )
            self.app.notify(f"Artifact built: {res['filename']}")


class SkillPlayApp(App):
    CSS = """
    #home { align: center top; padding: 2; overflow-y: auto; height: 1fr; }
    #brand { content-align: center middle; text-style: bold; }
    #stats { content-align: center middle; }
    #play { padding: 2; }
    #prompt { height: auto; margin: 1 0; }
    #reason { height: auto; margin: 0 0 1 0; }
    #schema { height: auto; }
    #options { height: auto; }
    #code { height: 10; margin: 1 0; }
    #run-btn { width: 24; margin: 0 0 1 0; }
    #feedback { height: 2; }
    #explanation { height: auto; }
    #summary { align: center middle; padding: 2; }
    #stats-screen { padding: 2; }
    #stats-body { height: auto; }
    #spark-xp { height: auto; }
    #spark-acc { height: auto; }
    #heatmap { height: auto; }
    #goals-screen { padding: 2; }
    #goals-body { height: auto; }
    #ach-screen { padding: 2; }
    #ach-body { height: auto; }
    #config-screen { padding: 2; }
    """

    def __init__(self, packs: list | None = None, start_exam_skill: str | None = None) -> None:
        super().__init__()
        self.packs = packs if packs is not None else loader.load_all_packs()
        self.progress = progress_mod.load()
        apply_config(self.progress)
        i18n.set_language(self.progress["settings"].get("language", "en"))
        # V6: optional direct launch into a skill's mastery exam (from `skillplay exam`).
        self._start_exam_skill = start_exam_skill

    def _apply_theme(self) -> None:
        if os.environ.get("NO_COLOR"):
            return  # respect NO_COLOR: skip colored themes
        mapping = {"dark": "dark", "light": "light", "high_contrast": "textual-high-contrast"}
        try:
            self.theme = mapping.get(self.progress["settings"].get("theme", "dark"), "dark")
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Loading…")

    def on_mount(self) -> None:
        self._apply_theme()
        streak_mod.update_streak(self.progress["streak"])
        progress_mod.save(self.progress)
        if self._start_exam_skill:
            session = exam_mod.build_exam(self._start_exam_skill, self.progress)
            if session is not None:
                self.push_screen(PlayScreen(session=session))
                return
        self.push_screen(HomeScreen())


def run() -> None:
    SkillPlayApp().run()
