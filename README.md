# CoWork Auto-Allow

Automatically clicks **Allow** in Claude Desktop's CoWork permission dialogs on Windows. Runs as a system tray app in the background.

---

## Install

**Requirements:** Python 3.10+, Windows

```
pip install -r requirements.txt
```

---

## Quick start

```
python app.py
```

Click **▶ START** in the window. Minimize to tray. Done.

---

## Files

| File | Purpose |
|------|---------|
| `app.py` | GUI app — primary entry point |
| `autoallow.py` | Headless CLI version (no GUI) |
| `diagnostic.py` | Dumps UIA tree — use to debug button detection |
| `requirements.txt` | Python dependencies |
| `templates/` | Drop PNG crops of Allow buttons here (screenshot fallback) |
| `autoallow.log` | Click history, rotated at 1 MB |
| `crash.log` | Full tracebacks on unexpected errors |

---

## How detection works

**Primary — UIA (Windows Accessibility):**  
Scans Claude Desktop's accessibility tree every 1.5 s (adjustable). Finds `Button` elements whose name matches known Allow variants and confirms they live inside a real permission dialog (reject-side sibling or context text present).

Known button variants detected:

| Dialog type | Button name |
|-------------|-------------|
| File / directory | `Allow Enter` |
| MCP tool permission | `Always allow` |
| Browser actions | `Allow all browser actions` |
| Scheduled task | `Allow` |

**Fallback — Screenshot template matching:**  
If UIA finds nothing and `templates/` contains PNGs, takes a full screenshot and locates the button visually at 80% confidence.

---

## Screenshot fallback setup

1. Trigger a permission dialog in Claude Desktop
2. Screenshot and crop tightly around the Allow button
3. Save as `templates/allow_btn.png` (any filename, `.png`)

---

## Debugging button detection

If clicks aren't happening, run the diagnostic while a dialog is visible:

```
python diagnostic.py
```

Opens `uia_tree_dump.txt`. Search for `allow` — note the exact `name=` value. Add it to `ALLOW_LABELS` in `app.py` if missing.

---

## Settings

All tunable via the GUI or by editing constants at the top of `app.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| Poll interval | 1.5 s | Slider in GUI (0.5 – 5.0 s) |
| Template confidence | 0.80 | `MATCH_CONF` in `app.py` |

---

## Logs

`autoallow.log` — rotated at 1 MB, 3 backups kept.

```
2026-05-17 14:23:01 [INFO   ] Engine started (poll=1.5s)
2026-05-17 14:23:04 [INFO   ] ✓  'Allow Enter'  (1587, 716)  [invoke]
2026-05-17 14:24:12 [WARNING] Claude Desktop not found — waiting
```

`crash.log` — appended on any unhandled exception with full traceback + timestamp.

---

## Tray menu

Right-click the tray icon:
- **Show** — open the window
- **Start/Stop** — toggle automation
- **Quit** — exit completely

---

## Emergency stop

Move mouse to any screen corner — pyautogui failsafe aborts any in-progress mouse action.

---

## Troubleshooting

**Nothing gets clicked:**
1. Run `diagnostic.py` while dialog is open
2. Search `uia_tree_dump.txt` for `allow`
3. If found: note exact `name=` and check it against `ALLOW_LABELS` in `app.py`
4. If not found: button is not in UIA tree → use screenshot fallback

**Template match misses:**
Lower `MATCH_CONF` in `app.py` from `0.80` to `0.70`. Crop template more tightly.

**"Already running" on startup:**
Delete `.autoallow.lock` in the project folder if the previous process crashed.

**`crash.log` has COM errors:**
Ensure `comtypes` is installed: `pip install comtypes`.
