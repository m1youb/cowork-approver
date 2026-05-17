# engine

Finds and clicks Allow buttons in Claude Desktop CoWork permission dialogs via Windows UI Automation (UIA), with a screenshot template-match fallback.

## Key files

| File | Role |
|------|------|
| `app.py` | Contains `Engine` class (lines 172–475) |
| `templates/` | PNG crops of Allow buttons for image fallback (optional, user-created) |
| `autoallow.log` | Rotating log — 1 MB max, 3 backups, written next to `app.py` |
| `crash.log` | Full tracebacks from unhandled exceptions |

## How it works

### Startup
1. `Engine.start()` sets state → `RUNNING`, clears `_stop_evt`, spawns `autoallow-engine` daemon thread.
2. Thread calls `pythoncom.CoInitialize()` — required for pywinauto COM access from a non-main thread.

### Poll loop (`_loop`)
Every `poll_interval` seconds (default 1.5 s, adjustable 0.5–5.0 s):

1. **Liveness check** — `_claude_alive()` enumerates all top-level windows via `Desktop(backend="uia")`, returns True if any window title contains `"claude"`. If False for 5 consecutive ticks, emits a warning; repeats every 60 ticks after that.
2. **UIA scan** — `_scan_uia()` iterates Claude windows, calls `_find_uia(win)` on each.
3. **Image fallback** — `_scan_img()` runs only if UIA found nothing AND `templates/` contains PNGs.
4. After a successful click, waits an extra 0.4 s before next poll (lets dialog close).

### UIA button search (`_find_uia`)
Two-pass approach:

**Fast path** — `win.child_window(title_re=..., control_type="Button")` — pywinauto's built-in BFS with regex:
```
(?i)\b(always allow|allow all browser actions|allow enter|allow)\b
```

**Slow path** — `_find(elem, depth)` — manual DFS up to depth 22, checks every `Button` element.

Both passes run the same two guards before returning a candidate:

| Guard | Logic |
|-------|-------|
| `_matches(name)` | Name contains an ALLOW_LABEL AND doesn't contain a DENY_EXCLUSION |
| `_is_permission_dialog(elem)` | Sibling is a reject Button OR nearby Text contains a permission-context phrase |

### Click (`_click`)
1. Reads `element_info.rectangle` → computes center coords.
2. Tries `btn.invoke()` first (accessibility action, no mouse move).
3. Falls back to `btn.click_input()` (synthesized mouse click).
4. Increments `_clicks_today` and sets `_last_click` under `_lock`.
5. Resets `_consec_errors` to 0.

### Error handling
- **Dedup** — `_emit_error()` suppresses identical messages repeated within 10 s.
- **Backoff** — consecutive errors trigger exponential delay: `poll_interval × 2^n`, capped at 15 s.
- **Crash** — outer `try/except` in `_loop` sets `state = CRASHED` and emits event; GUI watchdog detects this within 150 ms.
- **COM cleanup** — `pythoncom.CoUninitialize()` always called in `finally`.

### Shutdown
`Engine.stop()` sets `state = STOPPED`, signals `_stop_evt`, then calls `_thread.join(timeout=4)` to wait for clean exit.

## Data structures

### Engine states
```python
Engine.STOPPED  = "stopped"   # initial / after stop()
Engine.RUNNING  = "running"   # thread active
Engine.CRASHED  = "crashed"   # unrecoverable error in thread
```

### Event dict (put into queue, consumed by GUI)
```python
{
    "ts":    "14:23:01",     # HH:MM:SS
    "msg":   "✓  'Allow Enter'  (1587, 716)  [invoke]",
    "level": "success"       # "success" | "error" | "warn" | "info" | "crashed"
}
```

### Matching constants
```python
ALLOW_LABELS = [
    "always allow",               # MCP tool permission dialogs
    "allow all browser actions",  # browser action dialogs
    "allow enter",                # file/directory dialogs (Enter = keyboard hint)
    "allow",                      # generic / scheduled task dialogs
]
DENY_EXCLUSIONS = ["disallow", "not allow", "deny", "allow once"]
REJECT_WORDS    = {"deny", "cancel", "no", "reject", "decline", "block", "esc"}
PERMISSION_CONTEXT = ["claude would like to", "allow claude to", "cowork"]
```

## External dependencies

| Package | Use |
|---------|-----|
| `pywinauto` (UIA backend) | Window enumeration, element tree traversal, invoke/click |
| `comtypes` | COM interop layer under pywinauto; checked at startup |
| `pythoncom` | Per-thread COM init/uninit in engine thread |
| `pyautogui` | Template locate + mouse click for image fallback |
| `Pillow / ImageGrab` | Screen capture for image fallback |

No network calls. No env vars required.

## Gotchas

- **Claude Desktop renders dialogs in Chromium's web layer** — UIA exposes them as `Button` elements with the full CSS class string as `auto_id` (very long). Match on `name`, not `auto_id`.
- **Button name includes keyboard shortcut** — e.g. `"Allow Enter"` not `"Allow"`. The `ALLOW_LABELS` list handles this via substring match.
- **`"Allow once"` must be excluded** — it contains `"allow"` as substring but should never be clicked. Excluded via `DENY_EXCLUSIONS`.
- **COM must be initialized per thread** — pywinauto calls fail silently or crash if `pythoncom.CoInitialize()` is skipped in the engine thread. This is done in `_loop` before the first `Desktop()` call.
- **`_find` depth limit is 22** — Electron/Chromium UIA trees are deep (15–20 levels). Going deeper risks infinite loops on malformed trees.
- **Image fallback requires opencv-python** — `pyautogui.locate(..., confidence=...)` uses OpenCV under the hood. If not installed, confidence-based matching raises `ImportError` at locate time, not at import time.
