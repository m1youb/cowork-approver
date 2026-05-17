"""
autoallow.py — Auto-click "Always allow" in Claude Desktop CoWork permission dialogs.

Strategy:
  1. UIA traversal — find button via accessibility tree (fast, reliable if exposed)
  2. Screenshot template match — find button visually via PIL image comparison (fallback)

Run continuously in background. Logs every attempt to autoallow.log.
"""

import sys
import time
import logging
import datetime
from pathlib import Path

try:
    import pyautogui
    from PIL import Image, ImageGrab
    from pywinauto import Desktop
    from pywinauto.findwindows import ElementNotFoundError
except ImportError:
    print("Missing dependency. Run: pip install -r requirements.txt")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

POLL_INTERVAL = 1.5          # seconds between scans
LOG_FILE = Path("autoallow.log")
TEMPLATE_DIR = Path("templates")   # place "always_allow_btn.png" here for visual match
MATCH_CONFIDENCE = 0.80            # pyautogui confidence threshold (0–1)

# UIA: text strings that identify the target button (case-insensitive substrings).
# "Allow Enter" = the Allow button with keyboard shortcut shown in name.
# Listed most-specific first.
BUTTON_LABELS = ["always allow", "allow enter", "allow"]

# UIA: window title fragments — the dialog lives inside the main Claude window.
DIALOG_TITLE_HINTS = ["claude"]

# UIA: button names to SKIP so we don't accidentally click something else.
# "allow" is also a substring of "disallow" etc — guard against false positives.
BUTTON_LABEL_EXCLUSIONS = ["disallow", "not allow", "deny"]

# pyautogui safety: move mouse to corner to abort (built-in failsafe)
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("autoallow")

# ---------------------------------------------------------------------------
# UIA helpers
# ---------------------------------------------------------------------------

def is_claude_running() -> bool:
    desktop = Desktop(backend="uia")
    for win in desktop.windows():
        try:
            if "claude" in win.window_text().lower():
                return True
        except Exception:
            pass
    return False


def _text_matches(text: str) -> bool:
    t = text.lower().strip()
    if any(excl in t for excl in BUTTON_LABEL_EXCLUSIONS):
        return False
    return any(label in t for label in BUTTON_LABELS)


def find_button_uia(win):
    """
    Depth-first search the UIA tree under `win` for a button whose name
    matches BUTTON_LABELS. Returns the element or None.
    """
    try:
        # pywinauto child_window does a breadth-first search internally.
        # Use a single regex that covers all target labels.
        try:
            btn = win.child_window(
                title_re=r"(?i)\b(always allow|allow enter|allow)\b",
                control_type="Button",
            )
            if btn.exists(timeout=0):
                name = btn.element_info.name or ""
                if _text_matches(name) and _has_deny_sibling(btn):
                    return btn
        except Exception:
            pass

        # Manual recursive search as fallback
        return _recursive_find(win)
    except Exception:
        return None


def _has_deny_sibling(elem) -> bool:
    """Return True if elem has a sibling Button containing 'deny' — confirms permission dialog."""
    try:
        siblings = elem.parent().children()
        for s in siblings:
            try:
                sname = (s.element_info.name or "").lower()
                stype = s.element_info.control_type or ""
                if stype == "Button" and "deny" in sname:
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _recursive_find(elem, depth=0):
    if depth > 20:
        return None
    try:
        name = (elem.element_info.name or "").lower()
        ctrl = elem.element_info.control_type or ""
        if ctrl == "Button" and _text_matches(name) and _has_deny_sibling(elem):
            return elem
    except Exception:
        return None

    try:
        children = elem.children()
    except Exception:
        return None

    for child in children:
        result = _recursive_find(child, depth + 1)
        if result is not None:
            return result
    return None


def click_via_uia(btn) -> bool:
    """Click a UIA element. Returns True on success."""
    try:
        rect = btn.element_info.rectangle
        cx = (rect.left + rect.right) // 2
        cy = (rect.top + rect.bottom) // 2
        # Prefer invoke pattern; fall back to click_input
        try:
            btn.invoke()
        except Exception:
            btn.click_input()
        log.info(f"UIA click SUCCESS at ({cx},{cy}) on element {btn.element_info.name!r}")
        return True
    except Exception as exc:
        log.warning(f"UIA click FAILED: {exc}")
        return False


def scan_uia() -> bool:
    """Scan all windows for the Always Allow button via UIA. Returns True if clicked."""
    desktop = Desktop(backend="uia")
    for win in desktop.windows():
        try:
            title = win.window_text().lower()
        except Exception:
            continue
        if not any(hint in title for hint in DIALOG_TITLE_HINTS):
            continue
        btn = find_button_uia(win)
        if btn is not None:
            log.info(f"UIA: found button in window {win.window_text()!r}")
            return click_via_uia(btn)
    return False


# ---------------------------------------------------------------------------
# Screenshot / template-match helpers
# ---------------------------------------------------------------------------

def load_templates() -> list:
    """Load all PNG templates from TEMPLATE_DIR. Returns list of (name, path)."""
    if not TEMPLATE_DIR.exists():
        return []
    return [(p.stem, p) for p in TEMPLATE_DIR.glob("*.png")]


def scan_screenshot(templates: list) -> bool:
    """
    Take a screenshot and look for button via template matching.
    Returns True if a button was found and clicked.
    """
    if not templates:
        log.debug("No templates loaded; skipping screenshot scan")
        return False

    try:
        screen = ImageGrab.grab()
    except Exception as exc:
        log.warning(f"Screenshot failed: {exc}")
        return False

    screen_path = Path("_screen_tmp.png")
    screen.save(screen_path)

    for name, tmpl_path in templates:
        try:
            loc = pyautogui.locate(
                str(tmpl_path),
                str(screen_path),
                confidence=MATCH_CONFIDENCE,
            )
            if loc is not None:
                cx, cy = pyautogui.center(loc)
                pyautogui.click(cx, cy)
                log.info(
                    f"Template match SUCCESS: template={name!r} "
                    f"at ({cx},{cy}) confidence>={MATCH_CONFIDENCE}"
                )
                screen_path.unlink(missing_ok=True)
                return True
        except pyautogui.ImageNotFoundException:
            pass
        except Exception as exc:
            log.warning(f"Template match error for {name!r}: {exc}")

    screen_path.unlink(missing_ok=True)
    return False


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    log.info("autoallow.py started — polling every %.1fs", POLL_INTERVAL)
    log.info("Press Ctrl+C to stop. Move mouse to screen corner for emergency abort.")

    templates = load_templates()
    if templates:
        log.info("Loaded %d screenshot template(s): %s", len(templates), [n for n,_ in templates])
    else:
        log.info(
            "No templates in templates/. "
            "Screenshot fallback disabled. UIA-only mode active."
        )

    consecutive_no_claude = 0

    while True:
        try:
            if not is_claude_running():
                consecutive_no_claude += 1
                if consecutive_no_claude == 5:
                    log.info("Claude Desktop not detected — waiting...")
                elif consecutive_no_claude % 30 == 0:
                    log.info("Still waiting for Claude Desktop...")
                time.sleep(POLL_INTERVAL)
                continue

            consecutive_no_claude = 0

            # Primary: UIA tree
            clicked = scan_uia()

            # Fallback: screenshot
            if not clicked:
                clicked = scan_screenshot(templates)

            if clicked:
                # Brief pause after click to let dialog close before next poll
                time.sleep(0.5)

            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            log.info("Stopped by user.")
            break
        except Exception as exc:
            log.error(f"Unexpected error in main loop: {exc}", exc_info=True)
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
