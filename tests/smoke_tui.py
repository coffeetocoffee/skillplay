"""TUI end-to-end test via Textual headless pilot.

Run:  python tests/smoke_tui.py   (from repo root, or anywhere)
Isolated: progress writes go to a temp dir, never the real user data dir.
Covers: Home -> Play -> wrong -> retry -> correct -> Summary -> Home.
"""

import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillplay.core import progress as pm

_tmp = tempfile.mkdtemp(prefix="skillplay-test-")
pm.DATA_DIR = Path(_tmp)
pm.PROGRESS_PATH = Path(_tmp) / "progress.json"

from textual.widgets import Button

from skillplay.tui.app import HomeScreen, PlayScreen, SkillPlayApp


async def main() -> None:
    app = SkillPlayApp()
    async with app.run_test(size=(160, 100)) as pilot:
        # home -> pick the sql-basics pack (home buttons are index-based)
        sql_index = next(i for i, p in enumerate(app.packs) if p.id == "sql-basics")
        assert isinstance(app.screen, HomeScreen), type(app.screen)
        pack_btn = app.screen.query_one(f"#pack-{sql_index}", Button)
        pack_btn.scroll_visible()
        await pilot.click(pack_btn)
        await pilot.pause()
        assert isinstance(app.screen, PlayScreen), type(app.screen)

        s = app.screen.session
        n = len(s.challenges)
        assert n > 0, "empty session"
        print("session size:", n)

        # answer every challenge: wrong first, then correct (retry path)
        for i in range(n):
            ch = s.current
            await pilot.click("#answer")
            await pilot.press(*"x")  # wrong attempt
            await pilot.press("enter")
            await pilot.pause()
            assert ch.id in s.retried_ids, f"Q{i + 1}: expected retry offer"
            inp = app.screen.query_one("#answer")
            inp.value = s.current.answer["reference_sql"]
            await pilot.press("enter")
            await pilot.pause()

        assert s.done, "session should be finished"
        name = type(app.screen).__name__
        assert name == "SummaryScreen", name
        print("summary reached, xp_gained =", s.xp_gained, "| correct =", s.correct_count)

        app.screen.query_one("#home", Button).scroll_visible()
        await pilot.click("#home")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen), type(app.screen)
    print("saved progress:", pm.load()["skills"]["sql"])
    print("TUI E2E PASSED")


asyncio.run(main())
