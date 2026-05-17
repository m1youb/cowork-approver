"""
app.py — CoWork Auto-Allow GUI  (production build)
Light-mode, Claude palette. Auto-clicks Allow in CoWork permission dialogs.
"""

import sys
import os
import threading
import queue
import traceback
import tkinter as tk
from pathlib import Path
from datetime import datetime
from logging.handlers import RotatingFileHandler
import logging

# ── paths (always relative to this script, never CWD) ─────────────────────
BASE_DIR  = Path(__file__).parent
LOG_FILE  = BASE_DIR / "autoallow.log"
LOCK_FILE = BASE_DIR / ".autoallow.lock"
CRASH_LOG = BASE_DIR / "crash.log"
TEMPLATE_DIR = BASE_DIR / "templates"

# ── logging setup ──────────────────────────────────────────────────────────
_fmt = logging.Formatter("%(asctime)s [%(levelname)-7s] %(message)s",
                         datefmt="%Y-%m-%d %H:%M:%S")
_file_handler = RotatingFileHandler(
    LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
)
_file_handler.setFormatter(_fmt)
logging.basicConfig(level=logging.INFO, handlers=[_file_handler])
log = logging.getLogger("autoallow")

# ── dependency check ───────────────────────────────────────────────────────
_missing = []
try:
    import customtkinter as ctk
except ImportError:
    _missing.append("customtkinter")
try:
    import pystray
except ImportError:
    _missing.append("pystray")
try:
    from PIL import Image, ImageDraw, ImageGrab
except ImportError:
    _missing.append("Pillow")
try:
    from pywinauto import Desktop
    import comtypes.client  # noqa: F401 — trigger COM registration check
except ImportError:
    _missing.append("pywinauto / comtypes")
try:
    import pyautogui
except ImportError:
    _missing.append("pyautogui")

if _missing:
    _root = tk.Tk(); _root.withdraw()
    import tkinter.messagebox as mb
    mb.showerror(
        "Missing dependencies",
        "Install missing packages, then restart:\n\n"
        + "\n".join(f"  • {m}" for m in _missing)
        + "\n\nRun:  pip install -r requirements.txt",
    )
    sys.exit(1)

# ── global exception hooks ─────────────────────────────────────────────────

def _write_crash(exc_type, exc_val, exc_tb):
    ts = datetime.now().isoformat(timespec="seconds")
    text = "".join(traceback.format_exception(exc_type, exc_val, exc_tb))
    try:
        with CRASH_LOG.open("a", encoding="utf-8") as f:
            f.write(f"\n{'='*60}\n{ts}\n{text}\n")
    except Exception:
        pass
    log.critical("Unhandled exception:\n%s", text.rstrip())


def _excepthook(exc_type, exc_val, exc_tb):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_val, exc_tb)
        return
    _write_crash(exc_type, exc_val, exc_tb)


def _thread_excepthook(args):
    if args.exc_type and not issubclass(args.exc_type, SystemExit):
        _write_crash(args.exc_type, args.exc_value, args.exc_traceback)


sys.excepthook = _excepthook
threading.excepthook = _thread_excepthook

# ── Claude light-mode palette ──────────────────────────────────────────────
BG       = "#FAF9F7"
SURF     = "#FFFFFF"
SURF2    = "#F2F0EC"
BORDER   = "#E8E5E0"
TEXT     = "#1A1916"
TEXT2    = "#8C877D"
ACCENT   = "#D97757"
ACCENTHV = "#C4623E"
GREEN    = "#1A7F4B"
RED      = "#B94040"
AMBER    = "#9A6B1F"
MONO     = ("Consolas", 10)
UI_SM    = ("Segoe UI", 10)

# ── automation constants ───────────────────────────────────────────────────
ALLOW_LABELS = [
    "always allow",
    "allow all browser actions",
    "allow enter",
    "allow",
]
DENY_EXCLUSIONS   = ["disallow", "not allow", "deny", "allow once"]
REJECT_WORDS      = {"deny", "cancel", "no", "reject", "decline", "block", "esc"}
PERMISSION_CONTEXT = ["claude would like to", "allow claude to", "cowork"]
MATCH_CONF        = 0.80

# How many consecutive identical errors before we silence repeats (10 s window)
ERROR_DEDUP_SECS  = 10
# Max consecutive errors before backing off poll rate
MAX_CONSECUTIVE_ERRORS = 5


# ══════════════════════════════════════════════════════════════════════════
# Single-instance guard
# ══════════════════════════════════════════════════════════════════════════

class _SingleInstance:
    """Prevent two copies running at once via a PID lock file."""

    def __init__(self):
        self._acquired = False

    def acquire(self) -> bool:
        try:
            if LOCK_FILE.exists():
                pid = LOCK_FILE.read_text().strip()
                if pid.isdigit():
                    # check if process is still alive
                    import ctypes
                    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
                    if handle:
                        ctypes.windll.kernel32.CloseHandle(handle)
                        return False          # another instance is running
            LOCK_FILE.write_text(str(os.getpid()))
            self._acquired = True
            return True
        except Exception:
            return True  # if check fails, let it run

    def release(self):
        if self._acquired:
            try:
                LOCK_FILE.unlink(missing_ok=True)
            except Exception:
                pass


_instance = _SingleInstance()


# ══════════════════════════════════════════════════════════════════════════
# Automation engine
# ══════════════════════════════════════════════════════════════════════════

class Engine:

    # Engine states
    STOPPED = "stopped"
    RUNNING = "running"
    CRASHED = "crashed"

    def __init__(self, event_queue: queue.Queue):
        self.q              = event_queue
        self.state          = self.STOPPED
        self.poll_interval  = 1.5
        self._lock          = threading.Lock()
        self._clicks_today  = 0
        self._last_click    = None
        self._stop_evt      = threading.Event()
        self._thread: threading.Thread | None = None

        # Error deduplication
        self._last_err_msg  = ""
        self._last_err_time = 0.0
        self._consec_errors = 0

    # ── public ──────────────────────────────────────────────────────────

    @property
    def clicks_today(self) -> int:
        with self._lock:
            return self._clicks_today

    @property
    def last_click(self) -> str | None:
        with self._lock:
            return self._last_click

    @property
    def running(self) -> bool:
        return self.state == self.RUNNING

    def start(self):
        if self.state == self.RUNNING:
            return
        self.state = self.RUNNING
        self._stop_evt.clear()
        self._consec_errors = 0
        self._thread = threading.Thread(
            target=self._loop, name="autoallow-engine", daemon=True
        )
        self._thread.start()
        log.info("Engine started (poll=%.1fs)", self.poll_interval)
        self._emit("Engine started", "info")

    def stop(self):
        if self.state == self.STOPPED:
            return
        self.state = self.STOPPED
        self._stop_evt.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=4)
        log.info("Engine stopped")
        self._emit("Engine stopped", "info")

    def is_thread_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── event emitter ────────────────────────────────────────────────────

    def _emit(self, msg: str, level: str = "info"):
        ts = datetime.now().strftime("%H:%M:%S")
        self.q.put({"ts": ts, "msg": msg, "level": level})
        getattr(log, level if level in ("info", "warning", "error", "critical") else "info",
                log.info)(msg)

    def _emit_error(self, msg: str):
        """Emit an error but suppress identical messages within ERROR_DEDUP_SECS."""
        import time
        now = time.monotonic()
        if (msg == self._last_err_msg and
                now - self._last_err_time < ERROR_DEDUP_SECS):
            return
        self._last_err_msg  = msg
        self._last_err_time = now
        self._emit(msg, "error")

    # ── matching logic ───────────────────────────────────────────────────

    def _matches(self, text: str) -> bool:
        t = text.lower().strip()
        if any(x in t for x in DENY_EXCLUSIONS):
            return False
        return any(x in t for x in ALLOW_LABELS)

    def _is_permission_dialog(self, elem) -> bool:
        """Return True if elem is inside a real Claude permission dialog."""
        try:
            siblings = elem.parent().children()
        except Exception:
            return False

        for s in siblings:
            try:
                sn = (s.element_info.name or "").lower()
                st = s.element_info.control_type or ""
                if st == "Button" and any(w in sn for w in REJECT_WORDS):
                    return True
                if st == "Text" and any(p in sn for p in PERMISSION_CONTEXT):
                    return True
            except Exception:
                continue

        # One level up
        try:
            for s in elem.parent().parent().children():
                try:
                    sn = (s.element_info.name or "").lower()
                    if any(p in sn for p in PERMISSION_CONTEXT):
                        return True
                except Exception:
                    continue
        except Exception:
            pass

        return False

    # ── UIA traversal ────────────────────────────────────────────────────

    def _find(self, elem, depth: int = 0):
        if depth > 22:
            return None
        try:
            n = (elem.element_info.name or "").lower()
            t = elem.element_info.control_type or ""
            if t == "Button" and self._matches(n) and self._is_permission_dialog(elem):
                return elem
        except Exception:
            return None
        try:
            children = elem.children()
        except Exception:
            return None
        for c in children:
            r = self._find(c, depth + 1)
            if r:
                return r
        return None

    def _find_uia(self, win):
        # Fast path: pywinauto's built-in search
        try:
            b = win.child_window(
                title_re=r"(?i)\b(always allow|allow all browser actions|allow enter|allow)\b",
                control_type="Button",
            )
            if b.exists(timeout=0):
                n = b.element_info.name or ""
                if self._matches(n) and self._is_permission_dialog(b):
                    return b
        except Exception:
            pass
        # Slow path: full recursive walk
        return self._find(win)

    # ── click ────────────────────────────────────────────────────────────

    def _click(self, btn) -> bool:
        try:
            r        = btn.element_info.rectangle
            cx       = (r.left + r.right)  // 2
            cy       = (r.top  + r.bottom) // 2
            btn_name = (btn.element_info.name or "Allow").strip()
            method   = "invoke"
            try:
                btn.invoke()
            except Exception:
                btn.click_input()
                method = "click_input"
            with self._lock:
                self._clicks_today += 1
                self._last_click = datetime.now().strftime("%H:%M:%S")
            self._emit(f"✓  '{btn_name}'  ({cx}, {cy})  [{method}]", "success")
            self._consec_errors = 0
            return True
        except Exception as exc:
            self._emit_error(f"✗  Click failed: {exc}")
            return False

    # ── scan methods ─────────────────────────────────────────────────────

    def _scan_uia(self) -> bool:
        try:
            desktop = Desktop(backend="uia")
            for win in desktop.windows():
                try:
                    title = win.window_text().lower()
                except Exception:
                    continue
                if "claude" not in title:
                    continue
                btn = self._find_uia(win)
                if btn:
                    return self._click(btn)
        except Exception as exc:
            self._emit_error(f"UIA scan: {type(exc).__name__}: {exc}")
        return False

    def _scan_img(self) -> bool:
        templates = list(TEMPLATE_DIR.glob("*.png")) if TEMPLATE_DIR.exists() else []
        if not templates:
            return False
        tmp = BASE_DIR / "_scr_tmp.png"
        try:
            screen = ImageGrab.grab()
            screen.save(tmp)
            for t in templates:
                try:
                    loc = pyautogui.locate(str(t), str(tmp), confidence=MATCH_CONF)
                    if loc:
                        cx, cy = pyautogui.center(loc)
                        pyautogui.click(cx, cy)
                        with self._lock:
                            self._clicks_today += 1
                            self._last_click = datetime.now().strftime("%H:%M:%S")
                        self._emit(f"✓  Template '{t.stem}'  ({cx}, {cy})", "success")
                        return True
                except pyautogui.ImageNotFoundException:
                    pass
                except Exception as exc:
                    self._emit_error(f"Template '{t.stem}': {exc}")
        except Exception as exc:
            self._emit_error(f"Screenshot: {exc}")
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
        return False

    def _claude_alive(self) -> bool:
        try:
            for win in Desktop(backend="uia").windows():
                try:
                    if "claude" in win.window_text().lower():
                        return True
                except Exception:
                    pass
        except Exception:
            pass
        return False

    # ── main loop ────────────────────────────────────────────────────────

    def _loop(self):
        # COM must be initialized per-thread for pywinauto on Windows
        try:
            import pythoncom
            pythoncom.CoInitialize()
            _com_initialized = True
        except Exception:
            _com_initialized = False

        no_claude_ticks = 0

        try:
            while not self._stop_evt.wait(0):
                try:
                    if not self._claude_alive():
                        no_claude_ticks += 1
                        if no_claude_ticks == 5:
                            self._emit("Claude Desktop not found — waiting", "warn")
                        elif no_claude_ticks % 60 == 0:
                            self._emit("Still waiting for Claude Desktop…", "warn")
                        self._stop_evt.wait(self.poll_interval)
                        continue

                    no_claude_ticks = 0
                    clicked = self._scan_uia()
                    if not clicked:
                        self._scan_img()
                    if clicked:
                        self._consec_errors = 0
                        self._stop_evt.wait(0.4)

                except Exception as exc:
                    self._consec_errors += 1
                    self._emit_error(
                        f"Loop error ({self._consec_errors}): {type(exc).__name__}: {exc}"
                    )
                    # Exponential backoff on repeated errors (cap at 15 s)
                    backoff = min(self.poll_interval * (2 ** min(self._consec_errors, 4)), 15)
                    self._stop_evt.wait(backoff)
                    continue

                self._stop_evt.wait(self.poll_interval)

        except Exception as exc:
            self.state = self.CRASHED
            self._emit(f"Engine crashed: {type(exc).__name__}: {exc}", "error")
            log.exception("Engine thread crashed")
        finally:
            if _com_initialized:
                try:
                    import pythoncom
                    pythoncom.CoUninitialize()
                except Exception:
                    pass


# ══════════════════════════════════════════════════════════════════════════
# GUI
# ══════════════════════════════════════════════════════════════════════════

def _tray_img(color: str) -> Image.Image:
    sz  = 64
    img = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    d.ellipse([4, 4, sz - 5, sz - 5], fill=color)
    d.ellipse([20, 20, sz - 21, sz - 21], fill=(250, 249, 247, 255))
    return img


class App(ctk.CTk):

    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")

        self.q          = queue.Queue()
        self.engine     = Engine(self.q)
        self._dot_phase = 0

        self._build_window()
        self._build_ui()
        self._setup_tray()

        self.protocol("WM_DELETE_WINDOW", self._hide)
        self._drain_queue()
        self._pulse()

        log.info("App started — pid=%d", os.getpid())

    # ── window ──────────────────────────────────────────────────────────────

    def _build_window(self):
        self.title("CoWork Auto-Allow")
        self.geometry("370x570")
        self.resizable(True, True)
        self.minsize(370, 420)
        self.configure(fg_color=BG)
        self.update_idletasks()
        x = (self.winfo_screenwidth()  - 370) // 2
        y = (self.winfo_screenheight() - 570) // 2
        self.geometry(f"370x570+{x}+{y}")

    # ── UI ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # header
        hdr = ctk.CTkFrame(self, fg_color=SURF, corner_radius=0, height=48)
        hdr.pack(fill="x"); hdr.pack_propagate(False)

        self._hdr_dot = ctk.CTkLabel(hdr, text="●", font=("Segoe UI", 13),
                                     text_color=BORDER)
        self._hdr_dot.place(x=14, y=15)
        ctk.CTkLabel(hdr, text="CoWork Auto-Allow",
                     font=("Segoe UI Semibold", 12), text_color=TEXT).place(x=34, y=15)
        ctk.CTkLabel(hdr, text="Claude Desktop",
                     font=UI_SM, text_color=TEXT2).place(x=232, y=16)

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # status card
        card = ctk.CTkFrame(self, fg_color=SURF, corner_radius=10,
                            border_width=1, border_color=BORDER)
        card.pack(fill="x", padx=14, pady=(14, 0))

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(12, 4))

        self._state_lbl = ctk.CTkLabel(top, text="● STOPPED",
                                       font=("Segoe UI Semibold", 12), text_color=RED)
        self._state_lbl.pack(side="left")

        self._clicks_lbl = ctk.CTkLabel(top, text="0 clicks today",
                                        font=UI_SM, text_color=TEXT2)
        self._clicks_lbl.pack(side="right")

        bot = ctk.CTkFrame(card, fg_color="transparent")
        bot.pack(fill="x", padx=14, pady=(0, 12))

        ctk.CTkLabel(bot, text="Last click", font=UI_SM, text_color=TEXT2).pack(side="left")
        self._last_lbl = ctk.CTkLabel(bot, text="—", font=MONO, text_color=TEXT2)
        self._last_lbl.pack(side="right")

        # toggle button
        self._btn = ctk.CTkButton(
            self, text="▶   START",
            font=("Segoe UI Semibold", 13),
            fg_color=ACCENT, hover_color=ACCENTHV, text_color="#FFFFFF",
            height=46, corner_radius=10, command=self._toggle,
        )
        self._btn.pack(fill="x", padx=14, pady=12)

        # interval slider
        sl_row = ctk.CTkFrame(self, fg_color="transparent")
        sl_row.pack(fill="x", padx=14)
        ctk.CTkLabel(sl_row, text="Poll interval", font=UI_SM, text_color=TEXT2).pack(side="left")
        self._iv_lbl = ctk.CTkLabel(sl_row, text="1.5 s", font=MONO, text_color=TEXT)
        self._iv_lbl.pack(side="right")

        self._slider = ctk.CTkSlider(
            self, from_=0.5, to=5.0, number_of_steps=18,
            progress_color=ACCENT, button_color=ACCENT,
            button_hover_color=ACCENTHV, fg_color=BORDER,
            command=self._on_interval,
        )
        self._slider.set(1.5)
        self._slider.pack(fill="x", padx=14, pady=(4, 12))

        # log header
        lh = ctk.CTkFrame(self, fg_color="transparent")
        lh.pack(fill="x", padx=14)
        ctk.CTkLabel(lh, text="ACTIVITY LOG",
                     font=("Segoe UI Semibold", 9), text_color=TEXT2).pack(side="left")
        ctk.CTkButton(
            lh, text="Clear", font=("Segoe UI", 9), text_color=TEXT2,
            fg_color="transparent", hover_color=SURF2,
            height=18, width=38, corner_radius=4, command=self._clear_log,
        ).pack(side="right")

        # log box
        log_wrap = ctk.CTkFrame(self, fg_color=SURF, corner_radius=8,
                                border_width=1, border_color=BORDER)
        log_wrap.pack(fill="both", expand=True, padx=14, pady=(4, 0))

        self._log = tk.Text(
            log_wrap, font=MONO, bg=SURF, fg=TEXT,
            insertbackground=TEXT, selectbackground=SURF2,
            selectforeground=TEXT, relief="flat", bd=0,
            wrap="word", state="disabled", padx=10, pady=8, cursor="arrow",
        )
        self._log.pack(fill="both", expand=True)
        self._log.tag_config("success", foreground=GREEN)
        self._log.tag_config("error",   foreground=RED)
        self._log.tag_config("warn",    foreground=AMBER)
        self._log.tag_config("info",    foreground=TEXT2)
        self._log.tag_config("crashed", foreground=RED)
        self._log.tag_config("ts",      foreground="#C4BCB3")

        # footer
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=14, pady=8)
        ctk.CTkButton(
            footer, text="⊟  Minimize to tray", font=UI_SM, text_color=TEXT2,
            fg_color="transparent", hover_color=SURF2,
            height=26, corner_radius=6, command=self._hide,
        ).pack(side="left")
        self._status_lbl = ctk.CTkLabel(footer, text="", font=("Segoe UI", 9), text_color=TEXT2)
        self._status_lbl.pack(side="right")

    # ── tray ─────────────────────────────────────────────────────────────────

    def _setup_tray(self):
        menu = pystray.Menu(
            pystray.MenuItem("Show",       lambda *_: self.after(0, self._show), default=True),
            pystray.MenuItem("Start/Stop", lambda *_: self.after(0, self._toggle)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit",       lambda *_: self.after(0, self._quit)),
        )
        self._tray = pystray.Icon(
            "autoallow", _tray_img(ACCENTHV), "CoWork Auto-Allow", menu
        )
        threading.Thread(target=self._tray.run, name="tray", daemon=True).start()

    def _show(self):
        self.deiconify(); self.lift(); self.focus_force()

    def _hide(self):
        self.withdraw()
        self._status_lbl.configure(text="Running in tray")

    # ── controls ─────────────────────────────────────────────────────────────

    def _toggle(self):
        if self.engine.running:
            self.engine.stop()
            self._set_ui_stopped()
        else:
            self.engine.start()
            self._set_ui_running()

    def _set_ui_running(self):
        self._btn.configure(text="■   STOP", fg_color="#2D3748",
                            hover_color="#1A202C", text_color="#FFFFFF")
        self._state_lbl.configure(text="● RUNNING", text_color=GREEN)
        self._hdr_dot.configure(text_color=ACCENT)
        self._tray.icon = _tray_img(ACCENT)

    def _set_ui_stopped(self):
        self._btn.configure(text="▶   START", fg_color=ACCENT,
                            hover_color=ACCENTHV, text_color="#FFFFFF")
        self._state_lbl.configure(text="● STOPPED", text_color=RED)
        self._hdr_dot.configure(text_color=BORDER)
        self._tray.icon = _tray_img(ACCENTHV)

    def _set_ui_crashed(self):
        self._btn.configure(text="↺   RESTART", fg_color=RED,
                            hover_color="#9B2020", text_color="#FFFFFF")
        self._state_lbl.configure(text="● CRASHED — click Restart", text_color=RED)
        self._hdr_dot.configure(text_color=RED)
        self._tray.icon = _tray_img(RED)

    def _on_interval(self, v: float):
        self.engine.poll_interval = v
        self._iv_lbl.configure(text=f"{v:.1f} s")

    def _clear_log(self):
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    # ── queue drain + watchdog ────────────────────────────────────────────────

    def _drain_queue(self):
        try:
            while True:
                entry = self.q.get_nowait()
                self._append(entry)
                if entry["level"] == "success":
                    n = self.engine.clicks_today
                    self._clicks_lbl.configure(
                        text=f"{n} click{'s' if n != 1 else ''} today"
                    )
                    self._last_lbl.configure(text=self.engine.last_click or "—")
        except queue.Empty:
            pass

        # Watchdog: detect crashed engine thread, update UI + offer restart
        if self.engine.state == Engine.CRASHED:
            self._set_ui_crashed()
        elif self.engine.running and not self.engine.is_thread_alive():
            # Thread died without setting CRASHED — treat same way
            self.engine.state = Engine.CRASHED
            self._set_ui_crashed()
            self._append({"ts": datetime.now().strftime("%H:%M:%S"),
                          "msg": "Engine thread died unexpectedly",
                          "level": "crashed"})

        self.after(150, self._drain_queue)

    def _append(self, entry: dict):
        try:
            self._log.configure(state="normal")
            self._log.insert("end", entry["ts"] + "  ", "ts")
            self._log.insert("end", entry["msg"] + "\n", entry.get("level", "info"))
            self._log.see("end")
            lines = int(self._log.index("end-1c").split(".")[0])
            if lines > 300:
                self._log.delete("1.0", "2.0")
        except Exception:
            pass
        finally:
            try:
                self._log.configure(state="disabled")
            except Exception:
                pass

    # ── pulse ─────────────────────────────────────────────────────────────────

    def _pulse(self):
        if self.engine.running:
            phases = [ACCENT, "#E8895E", ACCENTHV, "#E8895E"]
            self._hdr_dot.configure(text_color=phases[self._dot_phase % len(phases)])
            self._dot_phase += 1
        self.after(500, self._pulse)

    # ── quit ─────────────────────────────────────────────────────────────────

    def _quit(self):
        try:
            self.engine.stop()
        except Exception:
            pass
        try:
            self._tray.stop()
        except Exception:
            pass
        try:
            _instance.release()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════

def main():
    if not _instance.acquire():
        _root = tk.Tk(); _root.withdraw()
        import tkinter.messagebox as mb
        mb.showwarning(
            "Already running",
            "CoWork Auto-Allow is already running.\n"
            "Check the system tray.",
        )
        sys.exit(0)

    log.info("=" * 50)
    log.info("CoWork Auto-Allow starting — Python %s — pid %d",
             sys.version.split()[0], os.getpid())

    pyautogui.FAILSAFE = True
    pyautogui.PAUSE    = 0.05

    try:
        app = App()
        app.mainloop()
    except Exception:
        log.exception("Fatal error in mainloop")
        raise
    finally:
        _instance.release()


if __name__ == "__main__":
    main()
