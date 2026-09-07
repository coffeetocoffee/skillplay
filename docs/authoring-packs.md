# Authoring packs

A **pack** is a folder of YAML files. No Python changes are required to add one.
skillplay discovers packs from (in order, first id wins):

1. Built-in: `skillplay/packs/`
2. User: `%LOCALAPPDATA%/skillplay/packs` (Windows) / `~/.local/share/skillplay/packs`
3. Local: `./packs` (next to where you run the app)

## Layout

```
my-pack/
  pack.yaml              # manifest
  challenges/
    01-first.yaml
    02-second.yaml
```

## `pack.yaml` (manifest)

```yaml
id: my-pack
name: My Pack
version: 0.1.0
author: you
skill: my-skill          # groups stats + SRS under this skill key
description: One-line summary.
difficulty: beginner     # beginner | intermediate | advanced
entry: challenges/*.yaml # optional glob, defaults to challenges/*.yaml
```

## Challenge file

Required keys: `id` (unique across *all* packs) and `type`. `skill` is
inherited from the manifest — do not set it per challenge.

```yaml
id: my-pack-q1
title: Short title
topic: select            # free-form grouping for stats
difficulty: 1            # 1-5, informational
xp: 10                   # base XP before combo/retry math
type: sql_query
prompt: |
  What SQL returns ...?
context:
  db_seed_sql: |
    CREATE TABLE t(a INT);
    INSERT INTO t VALUES (1),(2);
  schema_preview: "t(a INT)"
answer:
  reference_sql: "SELECT a FROM t"
validation:
  mode: sql_result
  normalize: true        # order-insensitive row compare
hints:
  - "Think about SELECT."
explanation: |
  Why this works.
```

## Validation modes

| `mode` | Use for | Key fields |
|---|---|---|
| `sql_result` | SQL queries | `answer.reference_sql`, `normalize`, `order_matters` |
| `regex_tester` | Regex patterns | `must_match[]`, `must_not_match[]` |
| `exact` | Commands / fill-in | `answer.value` or `validation.answers[]`, `case_insensitive` |
| `multiple_choice` | Concept checks | `validation.answer_id`, `options[]` |
| `test_cases` | Fix broken code | `validation.function`, `validation.test_cases[]`, `answer.reference_code`, `validation.lang` |
| `freeform` | Write code from scratch (hidden tests) | same as `test_cases` + `starter_code` template |

### `freeform` example (V1: write from scratch)

The player writes the whole function against tests they cannot see; the editor is
pre-filled with `starter_code` and the test list is hidden in the TUI. Grading
runs in the same sandboxed subprocess as `test_cases`.

```yaml
id: my-pack-ff1
type: freeform
prompt: |
  Write a function `double(n)` that returns n * 2.
starter_code: |
  def double(n):
      # your code here
      pass
answer:
  reference_code: |
    def double(n):
        return n * 2
validation:
  mode: freeform
  lang: python
  function: double
  test_cases:
    - args: [2]
      expected: 4
    - args: [-3]
      expected: -6
```

The TUI renders the same multi-line code editor as `test_cases`, but labels the
button **Run hidden tests** and shows a "tests are hidden" note.

### `multiple_choice` example

```yaml
id: my-pack-mc1
type: multiple_choice
prompt: Which command stages changes?
options:
  - id: a
    text: "git commit -a"
  - id: b
    text: "git add ."
  - id: c
    text: "git push"
answer:
  value: "b"
validation:
  mode: multiple_choice
  answer_id: "b"
```

The TUI renders one button per option; grading compares the chosen `id` to
`answer_id` (case-insensitive).

## Validating your pack

```bash
skillplay validate-packs
```

This checks manifests + every challenge against the schema and confirms each
reference answer self-validates. JSON Schemas for editor autocompletion live in
`skillplay/packs/schemas/`.

## Minimal starter: `git-basics`

The built-in `git-basics` pack (in this repo) uses only `exact` and
`multiple_choice` and is a good template to copy.
