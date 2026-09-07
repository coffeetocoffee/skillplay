# skillplay — Architecture

> System design: project structure, data schemas, and runtime flows.
> Companion docs: `roadmap.md` (phases/status). This file describes **how the system works as built**.

## 1. Tech choices

- Python 3.12, Textual (TUI) + Rich (rendering), PyYAML (packs), platformdirs (data dir), `sqlite3` stdlib (SQL validation).
- Offline-first, keyboard-only. Sound off by default (`settings.sound: false`, no audio backend wired).
- Entry point: `skillplay = "skillplay.__main__:main"` (`pyproject.toml`), `SkillPlayApp().run()`.

## 2. Project structure

```
skillplay/                          # project root
  pyproject.toml                    # hatchling build, deps, console script
  roadmap.md                        # phases + verified state
  ARCHITECTURE.md                   # this file
  README.md                         # overview + pipx install + usage
  config.sample.yaml                # documented user config template
  docs/
    authoring-packs.md              # community pack authoring guide
  skillplay/                        # package
    __init__.py
    __main__.py                     # main() -> TUI, or dispatches CLI subcommands
    core/
      __init__.py
      loader.py                     # pack discovery + YAML parsing (loader.py:49-127)
      validators.py                 # answer checking, behavior not strings (validators.py:16-150)
      engine.py                     # session loop, scoring, SRS, weighting (engine.py:23-150)
      progress.py                   # progress.json load/save, XP math (progress.py:18-58)
      streak.py                     # daily streak rules (streak.py:9-33)
      schema.py                     # lightweight pack/challenge schema checks
      config.py                     # optional config.yaml merge over settings
      cli.py                        # validate-packs / new-pack / export-stats / leaderboard
    tui/
      __init__.py
      app.py                        # HomeScreen / PlayScreen / SummaryScreen / StatsScreen / SkillPlayApp
    packs/
      sql-basics/      (15 challenges)
      regex-101/       (15 challenges, regex_tester)
      git-basics/      (10 challenges, exact + multiple_choice)
      fix-bug/         (4 challenges, test_cases / python)
      fix-bug-js/      (3 challenges, test_cases / js via node)
      css-basics/      (6 challenges, exact + multiple_choice)
      shell-basics/    (6 challenges, exact)
      http-rest/       (6 challenges, exact + multiple_choice)
      data-structures/ (4 challenges, test_cases / python)
      algorithms/      (4 challenges, test_cases / python)
      schemas/
        pack.schema.json
        challenge.schema.json
  tests/
    smoke_core.py                   # loader/validators/engine/streak checks (isolated tmp data dir)
    smoke_tui.py                    # headless Textual E2E: Home→Play→retry→Summary→Home
    conftest.py                     # tmp-data-dir fixture + pack fixtures
    test_validators.py              # pytest: per-validator + engine unit tests
```

Module responsibilities:

| Module | Owns | Never touches |
|---|---|---|
| `core/loader` | finding + parsing packs into `Pack`/`Challenge` dataclasses | UI, progress file |
| `core/validators` | `validate(challenge, input) -> Result(correct, detail)` | session state, disk |
| `core/engine` | challenge selection, scoring, SRS box updates, finalize, daily pick | widgets, YAML |
| `core/progress` | `progress.json` load/save, `level_for_xp` / `xp_for_level` | challenges |
| `core/streak` | pure date math for streaks | disk, UI |
| `core/schema` | `validate_pack(pack, strict) -> (errors, warnings)` — required keys, known modes, mode-specific fields, duplicate ids/prompts, over-broad regex, reference self-validation | disk, UI |
| `core/config` | optional `config.yaml` merge over `settings` | disk |
| `core/cli` | `validate-packs` / `export-stats` / `leaderboard` subcommands | UI |
| `tui/app` | screens, input, rendering, wiring engine calls | YAML parsing, SQL |

Dependency direction: `tui → core.{engine,loader,progress,streak}`; `engine → validators, progress, streak`. Validators and streak are leaf modules (no internal imports).

## 3. Schemas

### 3.1 Pack manifest (`pack.yaml`)

```yaml
id: sql-basics
name: SQL Basics
version: 0.1.0
author: core
skill: sql
description: SELECT, WHERE, ORDER BY — learn SQL by doing.
difficulty: beginner
schema_version: 1              # bump on manifest-format changes
tags: [sql, beginner]          # shown on Home; aids discovery
license: MIT                   # optional
min_version: "0.1.0"           # optional: requires skillplay >= this
contributor: core              # defaults to author
entry: challenges/*.yaml        # glob, default challenges/*.yaml
```

Discovery order (`loader.py:49-56`): builtin `skillplay/packs/` → `%LOCALAPPDATA%/skillplay/packs` (user) → `./packs` (local). First pack id wins (dedupe in `load_all_packs`); dirs without `pack.yaml` or with zero challenges are skipped, never fatal.

### 3.2 Challenge file

Required: `id`, `type`. Defaults: `difficulty: 1`, `xp: 10`, `topic/title/hints/explanation` empty. `skill` is inherited from the pack manifest (`loader.py:86`). Real example (`02-where.yaml`):

```yaml
id: sql-where-01
title: Filter with WHERE
topic: where
difficulty: 1
xp: 15
type: sql_query
prompt: |
  Return the names of users who are older than 30.
context:
  db_seed_sql: |
    CREATE TABLE users(name TEXT, age INT);
    INSERT INTO users VALUES ('ana', 25), ('bob', 35), ('cid', 40);
answer:
  reference_sql: "SELECT name FROM users WHERE age > 30"
validation:
  mode: sql_result
  order_matters: false
  normalize: true
hints: [...]
explanation: |
  `WHERE` filters rows before they are projected.
```

`type` values in use / planned: `sql_query`, `regex_build`, `git_command`, `multiple_choice` (used) → `fill_blank`, `fix_bug`, `ordering` (planned).

#### Challenge field reference (plugin API contract)

| Key | Required | Default | Notes |
|---|---|---|---|
| `id` | yes | — | unique across all packs; used for SRS + `completed_ids` |
| `type` | yes | — | selects validator family (`sql_query` today) |
| `prompt` | no | `""` | Markdown-ish text shown to the player |
| `title` / `topic` | no | `id` / `""` | `topic` groups stats later (e.g. `where`) |
| `difficulty` | no | `1` | 1–5 scale; currently informational only |
| `xp` | no | `10` | base XP before combo multiplier / retry halving |
| `answer` | no | `{}` | `reference_sql` for `sql_result`; `value`/`answers` for `exact` |
| `validation` | no | `{}` | must contain a known `mode` or validation always fails (§3.3) |
| `starter_code` | no (freeform) | `""` | V1: template pre-filled in the editor for `freeform` challenges (writing from scratch) |
| `validation.mode` | effectively | — | `exact` \| `regex_tester` \| `sql_result` \| `multiple_choice` \| `test_cases` \| `freeform` |
| `validation.normalize` | no | `true` | sort both row sets (order-insensitive compare) |
| `validation.order_matters` | no | `false` | skip sorting; use with `ORDER BY` challenges |
| `validation.case_insensitive` / `strip` | no | `false` / `true` | `exact` mode only |
| `validation.answers` | no | `[answer.value]` | accepted strings for `exact` mode |
| `validation.answer_id` | yes (MC) | — | correct option id for `multiple_choice`; must appear in `options[]` |
| `validation.must_match` / `must_not_match` | no | `[]` | test strings for `regex_tester` (empty = always fail) |
| `context.db_seed_sql` | no | `""` | `CREATE`/`INSERT` script run before both user + reference queries |
| `options[]` | yes (MC) | `[]` | `[{id, text}, …]` — rendered as buttons; max 8 (fixed button pool) |
| `hints` | no | `[]` | `hints[0]` shown on `Ctrl+H` |
| `explanation` | no | `""` | shown after a correct answer and on demand via `Ctrl+E` |
| `skill` | no (forbidden) | inherited | always overwritten from pack manifest (`loader.py:86`) — do not set per-challenge |
| `srs_reason` | no (runtime) | `""` | set by the engine on selection (`reason_for_challenge`); shown as `why: …` in PlayScreen — never authored in YAML |

### 3.3 Validators (`validators.py:90-150`)

Dispatch on `validation.mode`:

| Mode | Rule | Used by |
|---|---|---|
| `exact` | string match after optional `strip` / `case_insensitive`; `answers[]` or `answer.value` | git-basics commands |
| `regex_tester` | compile user input; must match all `must_match`, none of `must_not_match` | regex-101 |
| `sql_result` | run user SQL + `reference_sql` on seeded in-memory sqlite, compare result sets | sql-basics |
| `multiple_choice` | compare chosen option id (case-insensitive) to `validation.answer_id` | git-basics concepts |
| `test_cases` | run user code in sandboxed subprocess; check named `function` against `test_cases` | fix-bug, data-structures, algorithms |
| `freeform` (V1) | identical runtime to `test_cases` but the TUI hides the test list and pre-fills `starter_code` so the player writes the function from scratch | freeform-intro |
| unknown | always `Result(False, "Unknown validation mode: …")` | — |

SQL safety (`validators.py:_run_sql` / `_reject_risky_sql`): seed via `executescript` first, **then** `PRAGMA query_only = ON`, then run the user query. Reversed order would block the seed itself. `normalize: true` sorts both row sets (order-insensitive); ordered challenges keep `normalize: false` (see `03-order.yaml`). Invalid SQL returns `Result(False, "SQL error: …")` — never raises.

Hardening (`validators.py`):
- `_reject_risky_sql` strips comments/string literals, then rejects multi-statement input (`;` followed by content) and write keywords (`INSERT/UPDATE/DELETE/DROP/…`) before the query runs — defense in depth on top of `query_only`.
- `_run_sql` installs `set_progress_handler` and aborts any query exceeding `_MAX_SQL_STEPS` (runaway `WITH RECURSIVE` / cartesian joins); results beyond `_MAX_SQL_ROWS` are rejected.

Never compare SQL or regex answers by string equality — only by behavior (rows returned / strings matched).

### 3.4 Progress (`progress.json`)

Location via `platformdirs.user_data_dir("skillplay")`: `%LOCALAPPDATA%\skillplay\progress.json` (Windows), `~/.local/share/skillplay/` (Linux), `~/Library/Application Support/skillplay/` (macOS).

```json
{
  "version": 1,
  "total_xp": 40,
  "skills": {
    "sql": { "xp": 40, "level": 1, "completed_ids": ["sql-select-01"], "attempts": 9, "correct": 5 }
  },
  "challenges": {
    "sql-where-01": { "seen": 1, "correct": 1, "box": 2, "next_due": "2026-09-06" }
  },
  "streak": { "current": 1, "longest": 1, "last_played_date": "2026-09-05" },
  "settings": { "session_size": 8, "sound": false }
}
```

- XP/level (`progress.py:18-23`): `level = floor(sqrt(xp/100)) + 1`; `xp_for_level(L) = (L-1)² × 100`.
- SRS box (`engine.py:106-121`): correct → `box = min(5, box+1)`; wrong → `box = 1`. `next_due` offsets by box: `{1:0, 2:1, 3:3, 4:7, 5:16}` days.
- V3 Half-life regression (HLR): `next_due` is now driven by a per-card learned
  half-life (`core/hlr.py`), not the fixed box map. Each review takes one gradient
  step using the delay since `last_review`, correctness, and response `latency`
  (slow correct answers shrink stability — the W4 hesitant-recall rule). The card
  is rescheduled when predicted recall is expected to fall to `TARGET_RECALL`
  (0.90). `box` is still updated for backward-compatible weighting/display; new
  cards stay due today on first encounter. `Stats` shows per-skill avg `memory`
  half-life.
- Save is atomic (`progress.py:49-54`): write `progress.tmp` + `os.replace`. Corrupt JSON falls back to defaults (`progress.py:37-46`).

### 3.5 Streak rules (`streak.py:9-33`)

- Same day → no-op. Consecutive day (`diff == 1`) → `current += 1`. Gap (`diff > 1`) or first run → `current = 1`. `longest = max(longest, current)`. Dates stored as local ISO `YYYY-MM-DD`.

## 4. Flows

### 4.1 Boot (`SkillPlayApp`)

1. `load_all_packs()` → `load()` progress (or defaults) → `apply_config` merges optional `config.yaml`.
2. `compose` renders placeholder → `on_mount` updates streak, saves, pushes `HomeScreen`.
3. Home shows streak / total XP (refreshed on `on_show`), plus buttons: **Stats**, **Daily Challenge**, **Mixed**, **Due today (N)**, **Goals**, **Achievements**, **Community packs**, **Settings**, and one `Button` per pack (`id="pack-{id}"`, colon-free — Textual ids forbid `:`). `Due today (N)` shows `engine.count_due_today` and launches the due-today review session (B). **Community packs** opens `CommunityScreen` (D) listing discoverable packs from the registry index with in-app Install buttons.

### 4.2 Session loop (`PlayScreen`, `engine.py`)

```
pick pack / daily → on_mount: Session(skill, select_challenges(pack, progress, session_size))
    select: skip challenges with next_due > today; if none due, use all;
            weighted sample without replacement, session_size items
            weight = (6 - box) + 2×mistakes + 1  (low box & mistake-heavy first)
            # A3 mistake-type targeting: add 2×dominant-type mistakes, +3 when the
            # challenge's dominant type equals the player's globally weakest type
            # (_weakest_mistake_type). Each chosen card gets `srs_reason`
            # (reason_for_challenge) rendered as "why: …" in the TUI.
    per challenge:
      render HUD (Q i/n, skill XP, combo multiplier) + prompt
      multiple_choice → render option buttons (fixed pool of 8, reused — ids opt0..opt7,
                        option ids tracked in opt_map); Input hidden.
      test_cases      → multi-line `TextArea` (#code, language per `validation.lang`) +
                        `▶ Run tests (Ctrl+Enter)` button; Input hidden. (A1 real code UX.)
      otherwise      → Input shown (up/down recalls input history)
    grade via Input.Submitted or option button → engine.submit(input):
      correct → combo+=1, best_combo=max, xp = int(base × mult)
                mult: combo≥5 → 1.5x, ≥3 → 1.2x, else 1.0x
                retried-before → xp //= 2; advance SRS box; index+=1
      wrong, first time on this challenge → retried_ids.add(id), stay (retry, half XP available)
      wrong, already retried → combo=0, SRS box→1, index+=1
    correct: green "+N XP" + explanation; retry offered: yellow detail; final wrong: red detail
    Ctrl+H → first hint; Ctrl+E → explanation of current challenge;
    Ctrl+S → skip_current (advance, no grade, no SRS/XP);
    Esc → _finish(): finalize (once, guarded by _finalized) → Summary. No progress lost.
  all answered → _finish(): finalize() if any results → pop Play → push Summary
```

`Session` state (`engine.py`): `index`, `combo`/`best_combo`, `correct_count`, `xp_gained`, `results[]`, `retried_ids{}`. `done` ⟺ `index >= len(challenges)`.

Daily challenge: `engine.daily_challenge(packs)` seeds `random.Random(today)` over all challenges across packs; Home wraps the single pick in a synthetic one-challenge `Pack` and pushes `PlayScreen`.

Due-today review (B): `engine.select_due_today(packs, progress, size)` returns only SRS-due (or never-seen) cards across *all* skills, sorted weakest-first; Home's `Due today` button launches it as the daily habit loop. Goals screen (B): each goal exposes a `▶ Practice` button that builds a `Session` from `engine.adaptive_order(pack, progress)` — challenges reordered weakest-first so a curated "path" self-adjusts to the player's performance rather than being a fixed list.

### 4.3 Finalize + summary (`engine.py`, `app.py`)

`finalize`: `total_xp += session.xp_gained`; per-skill `xp`, recompute `level`, `attempts += total`, `correct += correct_count`, append correct ids to `completed_ids`; atomic save. Summary screen then updates streak + saves again, shows XP gained / accuracy / best combo; "Back to home" pops once, revealing Home.

### 4.4 Screen stack

`[base "Loading…" | Home] → push Play → [base | Home | Play] → finish: pop Play, push Summary → [base | Home | Summary] → back: pop once → [base | Home]`. Stats likewise: push StatsScreen → pop back. The base screen is never visible after mount. StatsScreen reads progress live (total XP, streak current/longest, per-skill level/XP/accuracy/completed).

### 4.7 Mastery exams (V6 / W6)

A real learning metric (not engagement). `core/exam.py` builds a randomized, mixed
session of ~`EXAM_SIZE` (20) challenges across all of a skill's packs, weighted
toward the *target difficulty tier* (current certification level + 1, capped at the
skill's hardest challenge). The session is graded normally; on finish,
`exam.certify` records `progress["certifications"][skill]` if accuracy ≥ 90%
(`PASS_RATIO`), setting `level` to the target tier and incrementing `exams_passed`.
Re-taking and passing raises the certified level. The TUI `ExamScreen` lists each
skill with its certified level + "Take exam" button; the result is shown on the
summary screen and persisted (with `progress.save`).

### 4.6 Encrypted sync (V5 / W5)

Account-free, client-side-encrypted `progress.json` sync. No passwords, no
accounts — pairing is a shared **device key** (a Fernet key, `cryptography`):

1. First device: `skillplay sync --pair` → prints the key (stored locally in
   `DATA_DIR/sync.key`, *never* inside the synced blob).
2. Other devices: `skillplay sync --set-key <KEY>` (same key).
3. `sync --push` encrypts the on-disk `progress.json` (Fernet/AES-128-CBC+HMAC)
   and `POST /sync/put` to the leaderboard server. `sync --pull` `GET /sync/get`s
   the blob for an unguessable **slot** = `HMAC(key, handle)`, decrypts, and
   overwrites local progress. `progress.save` snapshots the old file first, so a
   pull is always undoable via `restore-progress`. The server stores only opaque
   ciphertext (`leaderboard_sync.json`); it never sees the key or the plaintext.

### 4.5 CLI (`core/cli.py`, dispatched from `__main__`)

Bare `skillplay` → TUI; with subcommands → CLI:

| Command | Behavior |
|---|---|
| `validate-packs [--json] [--strict] [--fix]` | `schema.validate_pack` on every discovered pack: required keys, known modes, mode-specific fields, duplicate ids **and prompts**, over-broad regex, and reference-answer self-validation. `--json` emits a CI-friendly report; `--strict` promotes warnings (missing explanation/hints) to errors; `--fix` prints concrete fix suggestions per problem. Exit 1 on any error. |
| `new-pack <id> [--skill S] [--dir D]` | scaffolds a new pack at `D/<id>/` with `pack.yaml` + a sample `challenges/01-example.yaml` (A2 authoring). |
| `play --pack PATH` | loads a single local pack (no install) and launches the TUI with just that pack — for authoring previews. |
| `export-stats [--format json|md] [--output PATH]` | dumps `progress.json` or a Markdown table (per-skill XP/level/accuracy/completed). |
| `leaderboard [--name] [--url] [--view] [--skill S] [--publish]` | opt-in, account-free. Default POSTs `{"name", "total_xp", "skills":{...}}` (per-skill XP; URL from flag → `SKILLPLAY_LEADERBOARD_URL` env → `leaderboard.url` config, treated as a **base** URL). `--view [--skill S]` fetches and prints the all-time + weekly boards (per skill when given). `--publish` uploads the player's progress + SVG card to the server's public `/u/<handle>` page. No URL configured → friendly exit 1. |
| `share-stats [--format md\|svg\|json] [--output PATH] [--url URL] [--publish]` | generates a Markdown snippet / SVG card / JSON dump; `--publish` posts the SVG card as a public handle page (see `leaderboard --publish`). |
| `serve-leaderboard [--host H] [--port P] [--db PATH]` | runs the opt-in, account-free leaderboard server. Stores scores in `leaderboard.json` + profiles in `leaderboard_profiles.json`. Routes: `POST /submit` (per-skill scores), `POST /profile` (public page), `GET /api/board[?skill=]`, `GET /api/profile?name=`, `GET /u/<handle>` (HTML card). Weekly board = current ISO week (rolls over); all-time is cumulative. |
| `registry [--index URL]` | D: lists discoverable community packs from the index (`core/registry.available_packs`). |
| `install <name> [--index URL] [--force]` | installs a pack by URL, local path, or index name (`install_from_index`). Updates `.registry.json` so `update-packs` can re-pull. |
| `context --file PATH [--open]` | D: editor integration — maps a file's extension to the best matching pack and (with `--open`) launches its TUI. |
| `play --pack PATH` / `play --pack-id ID` | launches the TUI with one pack (local dir, or a built-in pack by id). |

Config (`core/config.py`): optional `config.yaml` next to `progress.json`; honors `session_size`, `sound`, `leaderboard.{name,url}` — see `config.sample.yaml`.

## 5. Invariants for contributors

1. Validators are pure: `(challenge, str) -> Result`. No I/O, no exceptions outward.
2. Engine mutates `progress` dict in memory; only `finalize`/`progress.save` touch disk.
3. Never trust string equality for SQL/regex — add a `validation.mode`, not a special case.
4. New packs = new folder under `skillplay/packs/` (or user/local dir) with `pack.yaml` + `challenges/*.yaml`. No code changes needed.
5. Textual constraints learned the hard way: no screen ops inside `compose()`; no `self.app` access in `Screen.__init__` (use `on_mount`); widget ids `[A-Za-z0-9_-]` only; `align`/`content-align` need both axes in current Textual.

## 6. Decision log

| Decision | Chosen | Rejected | Why |
|---|---|---|---|
| TUI framework | Textual | BubbleTea (Go), Ratatui (Rust) | content iteration speed matters more than binary size at MVP; Python lets pack authors read validator code; `run_test()` pilot gives free headless E2E |
| Pack format | YAML | TOML, JSON | multi-line `prompt`/`db_seed_sql` blocks are readable in YAML; authors are humans, not machines |
| Progress store | single JSON file, atomic replace | SQLite | progress is one small document, always read/written whole; JSON is inspectable/debuggable by users; atomic replace is enough crash safety |
| SQL validation | in-memory sqlite, result-set compare | string match, hosted DB | zero deps (stdlib), true semantic checking, per-query DB so challenges can't interfere; `query_only` after seed blocks writes (verified) |
| Challenge identity | global string `id` | per-pack numbering | SRS records, `completed_ids`, and `retried_ids` all key on it across sessions |
| Level curve | `floor(sqrt(xp/100))+1` | linear | diminishing returns keep early game rewarding without runaway numbers |

## 7. Failure modes & limits (verified)

| # | Exposure | Behavior today | Status |
|---|---|---|---|
| 1 | Runaway user SQL (`WITH RECURSIVE` bomb, cartesian join) | `set_progress_handler` aborts after `_MAX_SQL_STEPS` (2M) instructions → `Result(False, "SQL error: interrupted")` | HANDLED (P4 guard) |
| 2 | Regex catastrophic backtracking (`(a+)+$` on long non-match) | hangs inside `_regex_tester` `.search()`; test strings are short so impact is a brief freeze | OPEN — acceptable until user-authored packs grow; then add `regex` timeout or length cap |
| 3 | `Esc` mid-session | `_finish()` → finalize (guarded once) → Summary. Answered XP + SRS updates are saved, nothing lost | HANDLED (was: silent loss — fixed in P4) |
| 4 | Multi-statement input (`SELECT …; DELETE …`) | `_reject_risky_sql` strips comments/literals, then rejects `;` followed by content before sqlite sees it → `Result(False, "SQL error: Only a single SQL statement is allowed")` | HANDLED (explicit pre-flight reject) |
| 5 | Write attempt (`DROP TABLE`, `INSERT`) | double-guarded: `_reject_risky_sql` rejects write keywords; `query_only` pragma → `OperationalError` if anything slips through | HANDLED |
| 6 | Corrupt `progress.json` | falls back to defaults (`progress.py`); corrupt file is overwritten on next save (data loss of old progress, app survives) | HANDLED (survival over recovery — by design) |
| 7 | Unknown `validation.mode` / bad pack YAML | challenge always grades wrong (`_unknown`); `validate-packs` CLI now surfaces schema errors + failed self-validation explicitly | HANDLED |
| 8 | Unbounded `fetchall` | queries returning more than `_MAX_SQL_ROWS` (5000) rows are rejected with a clean message | HANDLED (P4 row cap) |
| 9 | Option-button remount id collisions | option buttons are a fixed pool (`opt0..opt7`) reused via `opt_map`, never re-mounted per challenge | HANDLED (Textual `remove_children` is async — dynamic remount races) |

## 8. Testing

```
cd skillplay
python tests/smoke_core.py   # 7 checks: loader, validators, retry/half-XP, finalize, streak, SRS
python tests/smoke_tui.py    # headless pilot: Home→Play→wrong→retry→correct→Summary→Home
python -m pytest tests/      # unit suite: validators, engine, pack validation (needs `pytest`)
```

- All scripts resolve the repo root from `__file__`, so they run from any cwd (packs load via builtin path).
- **Isolation:** all monkeypatch `progress.DATA_DIR`/`PROGRESS_PATH` to a fresh `tempfile.mkdtemp()` before running — real user progress is never touched. (Earlier versions wrote to the live data dir; fixed when moving into the repo.)
- `smoke_tui.py` and the pytest suite need `textual`; `smoke_core.py` needs only `pyyaml` + `platformdirs`. Dev deps: `pip install -e ".[dev]"`.
- pytest suite (`tests/test_validators.py` + `tests/conftest.py` fixtures) covers per-validator behavior (multi-statement/write rejection, runaway-query abort, multiple-choice, regex), engine retry/half-XP, session weighting, and `validate_pack` linting. Smoke scripts are retained for a zero-dep sanity check.
