# gui

Light-mode tkinter/customtkinter window with system tray integration. Wraps the `Engine` class, displays live activity log, exposes start/stop toggle, poll-interval control, and optional auto-click label selector.

## Key files

| File | Role |
|------|------|
| `app.py` | `App(ctk.CTk)` class (lines 561–926), `_tray_img()`, `main()` entry point |
| `config.json` | Persisted user settings — `extra_labels` key, written next to `app.py` |
| `crash.log` | Written by global exception hooks on any unhandled exception |

## How it works

### Startup (`main()`)
1. `_SingleInstance.acquire()` — creates a named Windows mutex (`Global\CoWorkAutoAllow_SingleInstance`). If mutex already exists (another live instance), shows warning dialog and exits. OS releases mutex automatically if the process crashes — no stale locks.
2. Sets `pyautogui.FAILSAFE = True` (mouse-to-corner aborts automation).
3. Constructs `App`, calls `mainloop()`.
4. `_instance.release()` releases mutex in `finally`.

### Window
- 370×660 px, resizable, min 370×500.
- Centered on screen at init.
- Close button → `withdraw()` (hides to tray), not destroy.
- `ctk.set_appearance_mode("light")` — must be called before any widget is created.

### Layout (top → bottom)
```
Header (48 px, white, bottom border)
  ● pulse dot | "CoWork Auto-Allow" | "Claude Desktop"
Status card (white, rounded, border)
  ● RUNNING / ● STOPPED / ● CRASHED    [N clicks today]
  Last click                            [HH:MM:SS]
Toggle button (46 px tall, full width)
  ▶ START (orange) / ■ STOP (dark) / ↺ RESTART (red)
Poll interval label + value
Slider (0.5 – 5.0 s, 18 steps)
AUTO-CLICK label                  [none] [all]
Label checkboxes card (white, rounded, border)
  Always: [Allow] [Always Allow] [Browser]   ← read-only pills
  ─────────────────────────────────────────
  [✓] Schedule  [✓] Update   [✓] Save
  [✓] Run       [✗] Delete⚠
ACTIVITY LOG header + Clear button
Log box (tk.Text, expands with window)
Footer
  ⊟ Minimize to tray    [status hint]    Quit
```

### System tray (`_setup_tray`)
- `pystray.Icon` runs in its own daemon thread (`name="tray"`).
- Tray icon: 64×64 RGBA, colored donut ring — orange when running, dark orange when stopped, red on crash.
- Menu: Show (default) / Start|Stop / — / Quit.
- All menu callbacks use `self.after(0, ...)` to marshal back to the main thread.

### Queue drain + watchdog (`_drain_queue`)
Runs every 150 ms via `self.after(150, self._drain_queue)`:
1. Drains all events from `engine.q` into the log box.
2. On `"success"` events: updates click counter and last-click labels.
3. **Watchdog**: if `engine.state == CRASHED` or `engine.running and not engine.is_thread_alive()` → calls `_set_ui_crashed()`, shows red restart button.

### AUTO-CLICK label selector
Two-zone card:

**Always-active pills** (read-only, informational):
- "Allow", "Always Allow", "Browser" — rendered as small rounded labels in SURF2.
- Correspond to `ALLOW_LABELS` constants — always active, not togglable.

**Optional checkboxes** (`OPTIONAL_LABELS`):
- 3-column `grid` inside `cb_frame` (CTkFrame with `fg_color="transparent"`).
- Each checkbox maps to a `(key, display, default_on, risky)` tuple.
- Risky labels (delete) render amber text with `⚠` suffix.
- On change: `_on_labels_changed()` → computes active `frozenset`, pushes to `Engine.set_extra_labels()`, saves `config.json`.
- "all" / "none" quick-select buttons in the section header.
- State persisted in `config.json["extra_labels"]` as a list of key strings.
- Default state (no saved config): all on except `delete`.

### Log box
`tk.Text` (not `ctk.CTkTextbox`) — native widget required for per-line color tags.
Capped at 300 lines; oldest line deleted when exceeded.

| Tag | Color | Used for |
|-----|-------|----------|
| `success` | `#1A7F4B` green | Allow button clicked |
| `error` | `#B94040` red | click failures, UIA errors |
| `warn` | `#9A6B1F` amber | Claude not found, waiting |
| `info` | `#8C877D` gray | start/stop events |
| `crashed` | `#B94040` red | engine thread death |
| `ts` | `#C4BCB3` light gray | timestamp prefix |

### Pulse animation (`_pulse`)
Runs every 500 ms. When running, cycles `_hdr_dot` color through 4 orange shades to create a breathing effect. Stops (dot goes gray) when engine is not running.

### Engine states → UI states

| Engine state | Button | Status label | Dot | Tray icon |
|---|---|---|---|---|
| STOPPED | ▶ START (orange) | ● STOPPED (red) | gray | dark orange |
| RUNNING | ■ STOP (dark) | ● RUNNING (green) | pulse orange | orange |
| CRASHED | ↺ RESTART (red) | ● CRASHED (red) | red | red |

Clicking ↺ RESTART calls `engine.start()` again (engine resets its own state on `start()`).

### Quit (`_quit`)
Footer Quit button calls `_quit()`:
1. `engine.stop()` — signals thread to exit.
2. `engine.join(timeout=3)` — waits up to 3 s for clean exit.
3. `_tray.stop()` — tears down pystray.
4. `_instance.release()` — releases single-instance mutex.
5. `self.destroy()` — destroys tk window.

Unlike close-button (which hides to tray), Quit fully terminates the process.

### Global exception hooks
Installed at module level — survive into any thread:

```python
sys.excepthook       → _excepthook()         # main thread
threading.excepthook → _thread_excepthook()  # all other threads
```

Both call `_write_crash()` which appends full traceback + ISO timestamp to `crash.log`.

## Data structures

### Palette constants
```python
BG       = "#FAF9F7"   # window background
SURF     = "#FFFFFF"   # cards, log box
SURF2    = "#F2F0EC"   # hover, secondary surface, always-active pills
BORDER   = "#E8E5E0"   # dividers, card borders
TEXT     = "#1A1916"   # primary text
TEXT2    = "#8C877D"   # muted / secondary text
ACCENT   = "#D97757"   # Claude terra-cotta (Start button, slider, checkboxes)
ACCENTHV = "#C4623E"   # hover darken
GREEN    = "#1A7F4B"   # running state, success log
RED      = "#B94040"   # stopped/crashed state, error log
AMBER    = "#9A6B1F"   # warning log, risky checkbox labels
```

### Config file (`config.json`)
```json
{
  "extra_labels": ["schedule", "update", "save", "run"]
}
```
Written by `_save_config()` on every checkbox change. Read by `_load_config()` at startup.

## External dependencies

| Package | Use |
|---------|-----|
| `customtkinter` | Themed widgets (CTkFrame, CTkButton, CTkSlider, CTkLabel, CTkCheckBox) |
| `pystray` | System tray icon + menu |
| `Pillow / ImageDraw` | Tray icon generation (64×64 RGBA donut) |
| `tkinter` (stdlib) | `tk.Text` for colored log, `tk.Frame` for separator lines |

## Gotchas

- **`ctk.set_appearance_mode` must be called before any widget is created** — calling it after produces visual glitches on Windows.
- **Tray menu callbacks must marshal to main thread** — pystray runs on its own thread; calling any tkinter method directly from a menu callback causes a crash. Always use `self.after(0, fn)`.
- **`tk.Text` not `CTkTextbox`** — customtkinter's textbox doesn't support per-line color tags. Native `tk.Text` is used for the log box and styled to match the palette manually.
- **Single instance uses named Windows mutex** — `Global\CoWorkAutoAllow_SingleInstance`. Unlike the old PID lock file approach, the OS releases it automatically on process death — no stale locks possible.
- **`minsize(370, 500)` prevents checkbox card from disappearing** — below ~500 px the label checkboxes get squeezed off screen.
- **Checkbox card uses `grid` inside `cb_frame`, not directly on `al_card`** — `al_card` uses `pack` for the always-row, divider, and `cb_frame`. `cb_frame` uses `grid` internally for the checkbox 3-column layout. Do not use `pack` inside `cb_frame` or it will conflict.
- **`_label_vars` keyed by `OPTIONAL_LABELS` key** — `_on_labels_changed` reads all vars, computes active frozenset, pushes to engine, saves `config.json`.
- **Log cap at 300 lines deletes one line at a time** — `delete("1.0", "2.0")` inside the append path. On burst events this is called per-event; acceptable since bursts are rare.
- **`_quit` calls `engine.join(timeout=3)` on main thread** — the 3 s join is safe here because it's called on user action (button click), not in `_drain_queue`. Do not call from `_drain_queue` — it would freeze the UI.
