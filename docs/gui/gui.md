# gui

Light-mode tkinter/customtkinter window with system tray integration. Wraps the `Engine` class, displays live activity log, exposes start/stop toggle and poll-interval control.

## Key files

| File | Role |
|------|------|
| `app.py` | `App(ctk.CTk)` class (lines 491–766), `_tray_img()`, `main()` entry point |
| `.autoallow.lock` | PID lock file — prevents second instance |
| `crash.log` | Written by global exception hooks on any unhandled exception |

## How it works

### Startup (`main()`)
1. `_SingleInstance.acquire()` — reads `.autoallow.lock`, checks if stored PID is alive via `OpenProcess`. If alive, shows warning dialog and exits. Otherwise writes current PID.
2. Sets `pyautogui.FAILSAFE = True` (mouse-to-corner aborts automation).
3. Constructs `App`, calls `mainloop()`.
4. `_instance.release()` deletes lock file in `finally`.

### Window
- 370×570 px, resizable, min 370×420.
- Centered on screen at init.
- Close button → `withdraw()` (hides to tray), not destroy.
- `ctk.set_appearance_mode("light")` — Claude's warm off-white palette.

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
ACTIVITY LOG header + Clear button
Log box (tk.Text, expands with window)
Footer
  ⊟ Minimize to tray        [status hint]
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
SURF2    = "#F2F0EC"   # hover, secondary surface
BORDER   = "#E8E5E0"   # dividers, card borders
TEXT     = "#1A1916"   # primary text
TEXT2    = "#8C877D"   # muted / secondary text
ACCENT   = "#D97757"   # Claude terra-cotta (Start button, slider)
ACCENTHV = "#C4623E"   # hover darken
GREEN    = "#1A7F4B"   # running state, success log
RED      = "#B94040"   # stopped/crashed state, error log
AMBER    = "#9A6B1F"   # warning log
```

## External dependencies

| Package | Use |
|---------|-----|
| `customtkinter` | Themed widgets (CTkFrame, CTkButton, CTkSlider, CTkLabel) |
| `pystray` | System tray icon + menu |
| `Pillow / ImageDraw` | Tray icon generation (64×64 RGBA donut) |
| `tkinter` (stdlib) | `tk.Text` for colored log, `tk.Frame` for separator |

## Gotchas

- **`ctk.set_appearance_mode` must be called before any widget is created** — calling it after produces visual glitches on Windows.
- **Tray menu callbacks must marshal to main thread** — pystray runs on its own thread; calling any tkinter method directly from a menu callback causes a crash. Always use `self.after(0, fn)`.
- **`tk.Text` not `CTkTextbox`** — customtkinter's textbox doesn't support per-line color tags. Native `tk.Text` is used for the log box and styled to match the palette manually.
- **Single instance check uses `OpenProcess(0x1000)`** — `PROCESS_QUERY_LIMITED_INFORMATION`. A stale lock file from a crash is cleaned automatically because the old PID won't be alive. If `OpenProcess` fails for any reason, the check is bypassed (fail-open).
- **`minsize(370, 420)` prevents slider from disappearing** — below ~420 px the slider + log header get squeezed off screen.
- **Log cap at 300 lines deletes one line at a time** — `delete("1.0", "2.0")` inside the append loop. On burst events this is called per-event; acceptable since bursts are rare.
