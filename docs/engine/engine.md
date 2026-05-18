# engine

Finds and clicks Allow buttons in Claude Desktop CoWork permission dialogs via Windows UI Automation (UIA), with a screenshot template-match fallback.

## Key files

| File | Role |
|------|------|
| `app.py` | Contains `Engine` class (lines 201–546) |
| `templates/` | PNG crops of Allow buttons for image fallback (optional, user-created) |
| `autoallow.log` | Rotating log — 1 MB max, 3 backups, written next to `app.py` |
| `crash.log` | Full tracebacks from unhandled exceptions |
| `config.json` | Persisted user config — `extra_labels` key holds list of toggled-on optional label keys |

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
Three-pass approach, ordered by priority:

**Priority pass** — searches only for persistent-allow variants first:
```
(?i)(\balways allow\b|\ballow all browser actions\b)
```
Uses `win.child_window(title_re=..., control_type="Button")`. If found and passes both guards → returned immediately, no further search. This ensures "Always allow" wins over plain "Allow" when both exist in the same dialog.

**Full-pattern pass** — `win.child_window(title_re=..., control_type="Button")` with a dynamically-built regex combining ALL labels:
```
(?i)(\balways allow\b|\ballow all browser actions\b|\ballow enter\b|\ballow\b|\bschedule\b|\bupdate\b|...)
```
Pattern rebuilt every scan to reflect live checkbox state.

**Slow path** — `_find(win)` — calls `_find_all` (manual DFS up to depth 22, collects all matching Button elements) then `max(..., key=_label_score)` to return the highest-priority match.

All candidates run the same two guards before being returned:

| Guard | Logic |
|-------|-------|
| `_matches(name)` | Name contains an ALLOW_LABEL (substring) or extra_label (word-boundary regex) AND doesn't contain a DENY_EXCLUSION |
| `_is_permission_dialog(elem)` | Sibling is a reject Button (cancel/deny/esc) OR nearby Text contains a permission-context phrase |

### Priority scoring (`_label_score`)
Used by `_find` (slow path) to pick the best candidate when multiple Allow buttons exist in the same subtree:

| Button name contains | Score |
|---------------------|-------|
| `"always allow"` | 4 |
| `"allow all browser actions"` | 3 |
| anything else (extra labels, plain allow) | 1 |

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
`Engine.stop()` sets `state = STOPPED`, signals `_stop_evt`. Thread exits on next `_stop_evt.wait()` check. `Engine.join(timeout)` blocks until thread exits — call only from non-GUI threads (used by `App._quit`).

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
    "msg":   "✓  'Always allow Enter'  (1587, 716)  [invoke]",
    "level": "success"       # "success" | "error" | "warn" | "info" | "crashed"
}
```

### Matching constants
```python
ALLOW_LABELS = [
    "always allow",               # MCP tool permission dialogs — primary button
    "allow all browser actions",  # browser domain dialogs
    "allow enter",                # file/directory dialogs (Enter = keyboard shortcut in name)
    "allow",                      # generic / scheduled task dialogs
]

# User-togglable action-card labels (key, display, default_on, risky)
OPTIONAL_LABELS = [
    ("schedule", "Schedule", True,  False),  # confirmed UIA: "Schedule Enter"
    ("update",   "Update",   True,  False),  # confirmed UIA: "Update Enter"
    ("save",     "Save",     True,  False),
    ("run",      "Run",      True,  False),
    ("delete",   "Delete",   False, True),   # destructive — off by default
]

DENY_EXCLUSIONS    = ["disallow", "not allow", "deny", "allow once"]
REJECT_WORDS       = {"deny", "cancel", "no", "reject", "decline", "block", "esc"}
PERMISSION_CONTEXT = ["claude would like to", "allow claude to", "cowork"]
```

### Extra labels (runtime)
`Engine._extra_labels: frozenset` — loaded from `config.json` at startup, updated live via `set_extra_labels(frozenset)` when user toggles checkboxes. Atomic reference swap (GIL-safe). Persisted to `config.json` on every change.

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
- **Button name includes keyboard shortcut** — e.g. `"Allow Enter"`, `"Schedule Enter"`, `"Always allow Enter"`. The `ALLOW_LABELS` list handles this via substring match.
- **`"Allow once"` must stay in DENY_EXCLUSIONS** — it contains `"allow"` as substring but should never be clicked. Both the button name and any dropdown item exposing it must be excluded.
- **Extra labels use word-boundary regex, ALLOW_LABELS use substring** — `"schedule"` with `\b` won't match `"Scheduled"` (sidebar nav item). ALLOW_LABELS use plain `in` because their patterns are already specific enough (`"always allow"`, `"allow enter"`, etc.).
- **Priority pass prevents wrong-button clicks** — if MCP dialog exposes both an "Always allow" button and a plain "Allow" button, the priority pass finds "Always allow" first. Without it, UIA tree order determines which button gets clicked.
- **COM must be initialized per thread** — pywinauto calls fail silently or crash if `pythoncom.CoInitialize()` is skipped in the engine thread.
- **`_find_all` depth limit is 22** — Electron/Chromium UIA trees are deep (15–20 levels). Going deeper risks infinite loops on malformed trees.
- **Image fallback requires opencv-python** — `pyautogui.locate(..., confidence=...)` uses OpenCV under the hood. If not installed, confidence-based matching raises `ImportError` at locate time, not at import time.
- **Chromium accessibility lazy init** — UIA tree only populates after an AT queries it. Run `app.py` first to wake Chromium, then `diagnostic.py`. A fresh Claude Desktop with no running UIA client will return a shallow tree.
