# Editor integrations (learn-in-context)

skillplay can jump straight into a relevant practice pack from the file you're
editing. This is the "learn-in-context" workflow from roadmap section D.

## The `context` command

`skillplay context` maps a file's extension to the most relevant pack and either
prints the suggestion or launches the TUI directly:

```bash
skillplay context --file src/app.py          # -> suggests 'fix-bug'
skillplay context --file src/app.py --open   # -> launches the fix-bug TUI
```

Extension → pack mapping:

| Extension | Pack |
|---|---|
| `.py` | `fix-bug` |
| `.js` `.mjs` `.jsx` `.ts` | `fix-bug-js` |
| `.css` `.scss` | `css-basics` |
| `.sh` `.bash` | `shell-basics` |
| `.sql` | `sql-basics` |
| `.http` `.rest` | `http-rest` |

You can also open any built-in pack by id directly:

```bash
skillplay play --pack-id sql-basics
```

## VS Code

Add a keybinding (`keybindings.json`) that pipes the active file to `context`:

```json
{
  "key": "ctrl+alt+s",
  "command": "workbench.action.terminal.sendSequence",
  "args": { "text": "skillplay context --file \"${file}\" --open\u000D" }
}
```

Or wire it as a task in `.vscode/tasks.json`:

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "skillplay: practice this file",
      "type": "shell",
      "command": "skillplay context --file ${file} --open",
      "problemMatcher": []
    }
  ]
}
```

Then `Terminal → Run Task → skillplay: practice this file`.

## Neovim (Lua)

```lua
vim.keymap.set("n", "<leader>sp", function()
  local file = vim.fn.expand("%:p")
  vim.cmd("!" .. "skillplay context --file " .. vim.fn.shellescape(file) .. " --open")
end, { desc = "skillplay: practice the current file" })
```

## Requirements

- `skillplay` must be on your `PATH` (e.g. via `pipx install skillplay`).
- The matching pack must be installed (built-ins always are; community packs via
  `skillplay registry` / the in-app **Community packs** screen).
