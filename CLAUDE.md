# CoWork Auto-Allow — Claude Instructions

## Stack
- Python 3.12, Windows only
- `customtkinter` — GUI widgets
- `pystray` — system tray
- `pywinauto` (UIA backend) — accessibility tree traversal
- `pyautogui` + `Pillow` — screenshot fallback

## Entry points

| File | Purpose |
|------|---------|
| `app.py` | **Primary** — GUI app, run this |
| `autoallow.py` | Headless CLI fallback (older, fewer features) |
| `diagnostic.py` | UIA tree dump — run while dialog is visible to discover button names |

## Key constants (app.py top of file)
- `ALLOW_LABELS` — button name substrings that trigger a click
- `DENY_EXCLUSIONS` — substrings that disqualify a match (including `"allow once"`)
- `REJECT_WORDS` — sibling button words that confirm it's a real permission dialog
- `PERMISSION_CONTEXT` — text element phrases used as fallback dialog confirmation

## Paths
All paths in `app.py` are relative to `Path(__file__).parent` (not CWD).
`autoallow.py` uses CWD — always run from the project directory.

## Docs
- `docs/engine/engine.md` — UIA traversal, matching logic, click flow, error handling
- `docs/gui/gui.md` — window layout, tray, watchdog, palette constants
- `docs/cli/cli.md` — headless autoallow.py, differences from app.py
- `docs/diagnostic/diagnostic.md` — UIA dump tool, confirmed button names

## Architecture diagrams
- `architecture/system-overview/overview.md` — component map, thread model
- `architecture/engine-flow/engine-flow.md` — poll loop sequence, startup/shutdown
- `architecture/matching-flow/matching-flow.md` — three-pass UIA search, _matches, _is_permission_dialog
- `architecture/engine-states/engine-states.md` — engine state machine, UI states, error backoff

## Runtime files
| File | Created by | Purpose |
|------|-----------|---------|
| `config.json` | App on first checkbox change | Persists `extra_labels` list across restarts |
| `autoallow.log` | Engine | Rotating log, 1 MB max, 3 backups |
| `crash.log` | Exception hooks | Full tracebacks from any unhandled exception |
| `uia_tree_dump.txt` | `diagnostic.py` | UIA tree snapshot, overwritten each run |

## Warnings
- Never use `auto_id` to match buttons — Claude Desktop (Electron) leaves it empty; CSS class string is in `auto_id` position and changes with app updates.
- `"Allow once"` must stay in `DENY_EXCLUSIONS` — it contains `"allow"` as substring.
- Engine thread needs `pythoncom.CoInitialize()` before first `Desktop()` call.
- pyautogui confidence matching requires `opencv-python` — add to requirements if using templates.
- `_find_uia` runs a priority pass for `"always allow"` before the full-pattern pass — preserves MCP "Always allow" preference over plain "Allow". Do not merge these passes.
- Single-instance guard uses a named Windows mutex, not a PID lock file.
