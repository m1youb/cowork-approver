# cli

Headless CLI automation script. Same UIA + screenshot logic as the GUI engine but runs in a single blocking loop with console/file logging. Use when you don't want the GUI.

## Key files

| File | Role |
|------|------|
| `autoallow.py` | Standalone script — all logic self-contained |
| `templates/` | PNG crops for screenshot fallback (optional) |
| `autoallow.log` | Plain log file written relative to CWD (not script dir) |

## How it works

1. Loads PNG templates from `templates/` (if any).
2. Enters `while True` loop:
   - `is_claude_running()` — enumerates windows, checks for `"claude"` in title.
   - `scan_uia()` — iterates Claude windows, calls `find_button_uia(win)` on each.
   - `scan_screenshot(templates)` — runs if UIA found nothing and templates exist.
   - Sleeps `POLL_INTERVAL` (1.5 s default).
3. `KeyboardInterrupt` → clean exit. Any other exception → logged, loop continues.

### UIA search (`find_button_uia`)
Fast path: `win.child_window(title_re=..., control_type="Button")` with regex covering known labels.  
Slow path: `_recursive_find(elem, depth)` — DFS up to depth 20.  
Both check `_has_deny_sibling()` before returning — requires a sibling Button containing `"deny"`.

> **Note:** `autoallow.py` uses the older `_has_deny_sibling` guard (only checks for `"deny"`), not the broader `_is_permission_dialog` from `app.py`. MCP tool dialogs and browser dialogs without a "Deny" sibling will be missed. Use `app.py` for full coverage.

### Click (`click_via_uia`)
1. `btn.invoke()` — accessibility invoke action.
2. Falls back to `btn.click_input()`.
3. Logs result to console + file.

## Configuration

All constants at top of file — edit directly, no config file:

| Constant | Default | Description |
|----------|---------|-------------|
| `POLL_INTERVAL` | `1.5` | Seconds between scans |
| `MATCH_CONFIDENCE` | `0.80` | pyautogui template match threshold (0–1) |
| `BUTTON_LABELS` | see below | Allow button name substrings |
| `BUTTON_LABEL_EXCLUSIONS` | see below | Disqualifying substrings |
| `DIALOG_TITLE_HINTS` | `["claude"]` | Window title must contain one of these |

```python
BUTTON_LABELS           = ["always allow", "allow enter", "allow"]
BUTTON_LABEL_EXCLUSIONS = ["disallow", "not allow", "deny"]
```

> `"allow once"` is NOT in exclusions here (unlike `app.py`). Could click the one-time button by accident if it appears as a UIA Button.

## Logging

Two handlers at startup:
- `FileHandler("autoallow.log")` — relative to CWD, not rotated, grows unbounded.
- `StreamHandler(sys.stdout)` — console output.

Format: `%(asctime)s [%(levelname)s] %(message)s`

## External dependencies

| Package | Use |
|---------|-----|
| `pywinauto` | UIA traversal |
| `pyautogui` | Template locate + mouse click |
| `Pillow / ImageGrab` | Screen capture |

## Gotchas

- **`autoallow.log` path is relative to CWD** — if launched from a different directory, log lands there. `app.py` fixes this with `BASE_DIR = Path(__file__).parent`.
- **No COM init** — `pythoncom.CoInitialize()` is not called. Runs on the main thread so COM is usually initialized by the runtime, but may fail in some environments.
- **No error deduplication** — the same UIA error logs every 1.5 s. Long outages fill the log quickly.
- **No single-instance guard** — multiple copies can run simultaneously.
- **`_has_deny_sibling` narrower than app.py** — only recognizes `"deny"` as a reject-side button. Browser and MCP dialogs with `"Cancel"` or other reject labels are skipped.
- **No priority pass for "Always allow"** — `find_button_uia` uses a single regex pass. If a dialog exposes both "Always allow" and "Allow" buttons, whichever appears first in the UIA tree gets clicked. `app.py` solves this with a dedicated priority pass.
- **DFS depth limit is 20, not 22** — `_recursive_find` goes 2 levels shallower than `app.py`'s `_find_all`. Deep Electron trees may be missed.
- **Temp file `_screen_tmp.png`** — created in CWD during template scan, deleted after. On crash mid-scan the file persists.
