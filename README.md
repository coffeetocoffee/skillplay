# skillplay

> Learn-by-Play TUI: learn dev skills (SQL, regex, git, CSS, JS) through
> bite-sized terminal challenges. Offline-first, keyboard-only, zero accounts.

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
skillplay                      # launches the TUI
skillplay validate-packs       # check all installed packs against the schema
skillplay export-stats         # print progress as Markdown
skillplay export-stats --format json --output stats.json
skillplay share-stats --format md     # a copy-pasteable stats snippet
skillplay share-stats --format svg --output card.svg
skillplay leaderboard --name you       # opt-in POST of (per-skill) XP (needs a URL)
skillplay leaderboard --view --skill sql   # fetch + print the board, by skill
skillplay leaderboard --publish        # publish your public profile/handle page
skillplay serve-leaderboard            # run the opt-in leaderboard server (C)
skillplay registry                     # list discoverable community packs
skillplay install css-basics           # install a community pack by index name
skillplay context --file app.py        # D: suggest a pack for the file you're editing
skillplay play --pack-id sql-basics     # jump straight into one built-in pack
skillplay install <url|path|name>      # install a community pack (P10)
skillplay update-packs                 # re-install community packs
skillplay restore-progress             # W5: list/restore automatic daily progress backups
skillplay sync --pair                  # V5: generate + print the device pairing key
skillplay sync --set-key <KEY>         # V5: install a key copied from another device
skillplay sync --push                  # V5: encrypt + upload progress to the server
skillplay sync --pull                  # V5: download + decrypt progress onto this device
skillplay exam --skill sql              # V6: take a randomized mastery exam (TUI)
```

## What's included

| Pack | Skill | Challenges | Validator |
|---|---|---|---|
| `sql-basics` | sql | 15 | `sql_result` (in-memory sqlite) |
| `regex-101` | regex | 15 | `regex_tester` |
| `git-basics` | git | 10 | `exact` + `multiple_choice` |
| `fix-bug` | python | 4 | `test_cases` (sandboxed subprocess) |
| `fix-bug-js` | javascript | 3 | `test_cases` (node, sandboxed) |
| `css-basics` | css | 6 | `exact` + `multiple_choice` |
| `shell-basics` | shell | 6 | `exact` |
| `http-rest` | http | 6 | `exact` + `multiple_choice` |
| `data-structures` | python | 4 | `test_cases` |
| `freeform-intro` | python | 3 | `freeform` (hidden-test construction) |

## How to play

- Pick a pack (or **Mixed** for an interleaved session across all skills).
- `Ctrl+H` cycles through hints, `Ctrl+S` skips, `Ctrl+E` shows the explanation,
  `Ctrl+U`/`Ctrl+D` rate the explanation, `Esc` finishes and saves the session.
- Correct answers earn XP with a combo multiplier; the first wrong answer
  offers a retry for half XP.
- A Leitner spaced-repetition schedule brings weak challenges back sooner.
  Mistakes are tagged (syntax / logic / off-by-one) and bias future weighting.
- Adaptive difficulty tilts selection toward harder challenges as you improve.
- Daily challenge, achievements, curated goals, and a crash-safe session
  resume are all built in. Settings (sound, theme, language, telemetry) live in
  the in-app **Settings** screen.
- **Mastery exams** (V6): take a randomized, mixed exam per skill — score ≥ 90%
  to certify the next difficulty level. A real learning metric, not just XP.

## Authoring your own packs

See [docs/authoring-packs.md](docs/authoring-packs.md). Packs are just a
folder of YAML — no code changes needed. The built-in `git-basics` pack is a
minimal example using only `exact` and `multiple_choice` validators.

## Distribution

A single-binary build is supported via `scripts/build_binary.py` (PyInstaller,
falling back to `shiv`). On each tagged release (`v*`), CI builds a one-file
binary for Linux, macOS, and Windows and uploads them as artifacts
(`.github/workflows/ci.yml` → `build-binary` job), and publishes the wheel to
PyPI (`.github/workflows/ci.yml` → `publish` job).

