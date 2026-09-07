# skillplay

> Learn-by-Play TUI: learn dev skills (SQL, regex, git, Python, algorithms,
> CSS, shell, HTTP, JS) through bite-sized terminal challenges. Offline-first,
> keyboard-only, zero accounts.

## Install

With [pipx](https://pipx.pypa.io/) (recommended — isolates the app in its own env):

```bash
pipx install skillplay          # from PyPI
# or, from a clone of this repo:
pipx install .                  # editable install from source
```

Or with plain pip:

```bash
pip install .                   # from the repo root
python -m skillplay             # launch
```

Requires Python 3.11+.

## Run

```bash
skillplay                              # launches the TUI
skillplay play --pack-id sql-basics    # jump straight into one built-in pack
skillplay demo                         # random challenge served in your browser (zero install)
skillplay exam --skill sql             # take a randomized mastery exam (TUI)
skillplay generate --play              # endless fresh generated challenges (Python/JS/regex)
skillplay validate-packs               # check all installed packs against the schema
skillplay export-stats                 # print progress as Markdown
skillplay export-stats --format json --output stats.json
skillplay share-stats --format md      # a copy-pasteable stats snippet
skillplay share-stats --format svg --output card.svg
skillplay leaderboard --name you       # opt-in POST of (per-skill) XP (needs a URL)
skillplay leaderboard --view --skill sql   # fetch + print the board, by skill
skillplay leaderboard --publish        # publish your public profile/handle page
skillplay serve-leaderboard            # run the opt-in leaderboard server
skillplay sync --pair                  # generate + print the device pairing key
skillplay sync --set-key <KEY>         # install a key copied from another device
skillplay sync --push                  # encrypt + upload progress to the server
skillplay sync --pull                  # download + decrypt progress onto this device
skillplay restore-progress             # list/restore automatic daily progress backups
skillplay registry                     # list discoverable community packs
skillplay install <url|path|name>      # install a community pack
skillplay update-packs                 # re-install community packs
skillplay list-packs                   # list installed community packs
skillplay new-pack my-pack             # scaffold a new pack (authoring)
skillplay pack ./my-pack --publish     # bundle/publish a community pack
skillplay context --file app.py        # suggest a pack for the file you're editing
```

## What's included

13 built-in packs · **110 challenges** across 9 skills:

| Pack | Skill | Challenges | Validator |
|---|---|---|---|
| `sql-basics` | sql | 15 | `sql_result` (in-memory sqlite) · prerequisite DAG · es |
| `regex-101` | regex | 15 | `regex_tester` |
| `git-basics` | git | 10 | `exact` + `multiple_choice` |
| `algorithms` | algorithms | 12 | `test_cases`/`freeform` (sandboxed subprocess) · prerequisite DAG |
| `css-basics` | css | 9 | `exact` + `multiple_choice` |
| `shell-basics` | shell | 9 | `exact` |
| `http-rest` | http | 9 | `exact` + `multiple_choice` |
| `data-structures` | python | 10 | `test_cases` · es |
| `py-stdlib` | python | 8 | `test_cases`/`freeform` (sandboxed subprocess) |
| `fix-bug` | python | 4 | `test_cases` (sandboxed subprocess) |
| `fix-bug-js` | javascript | 3 | `test_cases` (node, sandboxed) |
| `freeform-intro` | python | 3 | `freeform` (hidden-test construction) |
| `mini-cli` | python | 3 | `freeform` (capstone → portfolio artifact) |

## How to play

- Pick a pack (or **Mixed** for an interleaved session across all skills).
- `Ctrl+H` cycles through hints, `Ctrl+S` skips, `Ctrl+E` shows the explanation,
  `Ctrl+U`/`Ctrl+D` rate the explanation, `Esc` finishes and saves the session.
- Correct answers earn XP with a combo multiplier; the first wrong answer
  offers a retry for half XP.
- Reviews are scheduled by a **half-life regression memory model**: each card
  learns its own retention half-life from your delay, correctness, and response
  latency, and comes back just before you'd forget it. Mistakes are tagged
  (syntax / logic / off-by-one) and bias future weighting.
- A local **adaptive model** tilts selection toward what you need next, and the
  **skill graph** unlocks challenge frontiers as prerequisites are passed.
- **Mastery exams** (V6): take a randomized, mixed exam per skill — score ≥ 90%
  to certify the next difficulty level. A real learning metric, not just XP.
- **Capstone packs** (e.g. `mini-cli`) chain challenges that build one real
  artifact; your solutions are assembled into a portfolio file on disk.
- Daily challenge, achievements, curated goals, and a crash-safe session
  resume are all built in. Settings (sound, theme, language, telemetry, mentor
  backend) live in the in-app **Settings** screen. `Ctrl+M` asks the **Mentor**
  to explain a mistake like a senior dev. UI and challenge content ship in
  English + Spanish.

## Authoring your own packs

See [docs/authoring-packs.md](docs/authoring-packs.md). Packs are just a
folder of YAML — no code changes needed. `skillplay new-pack my-pack` scaffolds
one, and `skillplay validate-packs` self-validates every reference answer.

## Distribution

Prefer zero install? `skillplay demo` serves a random challenge in your browser
(stdlib HTTP server, no account). A single-binary build is supported via
`scripts/build_binary.py` (PyInstaller, falling back to `shiv`). On each tagged
release (`v*`), CI builds a one-file binary for Linux, macOS, and Windows and
**attaches them to the GitHub release** (`.github/workflows/ci.yml` →
`build-binary` job), and publishes the wheel to PyPI
(`.github/workflows/ci.yml` → `publish` job).

