# diagnostic

One-shot tool that dumps the full UIA accessibility tree of all Claude Desktop windows to console and `uia_tree_dump.txt`. Run this to discover button names and control types before modifying matching logic.

## Key files

| File | Role |
|------|------|
| `diagnostic.py` | Standalone script — no shared code with other modules |
| `uia_tree_dump.txt` | Output — created/overwritten each run, relative to CWD |

## How it works

1. Enumerates all top-level windows via `Desktop(backend="uia").windows()`.
2. Filters to windows with `"claude"` in title (case-insensitive).
3. For each matching window, calls `dump_element(win)` — recursive DFS that reads every element's `control_type`, `name`, `automation_id`, `class_name`, `rectangle`.
4. Writes result to `uia_tree_dump.txt` (UTF-8) and prints to console with cp1252 encoding (replaces unmappable chars with `?` to avoid crash on Windows terminal).

### `dump_element(elem, depth, lines)`
Recursive. No depth limit — dumps the entire tree.  
Each element → one line:
```
  [Button] name='Allow Enter' auto_id='' class='...' rect=(1518,694,1656,739)
```
Indentation = 2 spaces × depth.  
On any element read error → appends `<error reading element: ...>` and stops that branch.

## Output format

```
UIA Tree Dump — 2026-05-17T18:47:46.403551
Run while 'Always allow' permission dialog is open.
Search for 'Always allow' or 'allow' in this file to find the button.

======================================================================
WINDOW: 'Claude'  pid=26176
======================================================================
[Window] name='Claude' auto_id='' class='Chrome_WidgetWin_1' rect=(...)
  [Pane] ...
    [Button] name='Allow Enter' auto_id='' class='...' rect=(1518,694,1656,739)
    [Button] name='Deny Esc' auto_id='' class='...' rect=(1388,694,1509,739)
```

## Confirmed findings (from actual run)

Claude Desktop (Electron/Chromium) exposes dialog buttons in the UIA tree:

| Button | `name` | `rect` (example) |
|--------|--------|------------------|
| Allow | `Allow Enter` | `(1518, 694, 1656, 739)` |
| Deny | `Deny Esc` | `(1388, 694, 1509, 739)` |

- `auto_id` is always `''` for these buttons.
- `class` is a long serialized CSS class string (hundreds of chars) — useless for matching.
- Keyboard shortcut is appended to button name: `"Allow Enter"` = "Allow" button, Enter key.
- Buttons are ~20 levels deep inside the Chromium rendering tree.
- Context text is present as sibling `Text` elements: `"Claude would like to "`, `"Cowork"`, `" in:"`.

## External dependencies

| Package | Use |
|---------|-----|
| `pywinauto` | UIA backend, `Desktop`, `Application` |

## Gotchas

- **Run while the dialog is actually visible** — if no dialog is open, the relevant buttons won't appear in the dump. The dump still succeeds but won't contain Allow/Deny entries.
- **cp1252 console encoding** — Claude Desktop window titles contain Unicode characters outside cp1252 (e.g. Braille patterns used in terminal tab titles). The script encodes with `errors="replace"` for console output. The file is always clean UTF-8.
- **No depth limit** — on a busy Claude session with many chat messages, the dump can be large (hundreds of KB). Search with `Ctrl+F` for `allow` rather than reading top to bottom.
- **`find_claude_app()` is defined but unused** — was scaffolded for future per-process connection. `dump_all_claude_windows()` uses `Desktop` directly instead.
- **Output path relative to CWD** — `uia_tree_dump.txt` lands wherever you run the script from. Launch from the project directory.
