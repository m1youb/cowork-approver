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

## Warnings
- Never use `auto_id` to match buttons — Claude Desktop (Electron) leaves it empty; CSS class string is in `auto_id` position and changes with app updates.
- `"Allow once"` must stay in `DENY_EXCLUSIONS` — it contains `"allow"` as substring.
- Engine thread needs `pythoncom.CoInitialize()` before first `Desktop()` call.
- pyautogui confidence matching requires `opencv-python` — add to requirements if using templates.
