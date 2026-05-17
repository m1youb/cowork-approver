"""
diagnostic.py — Dump UIA control tree for Claude Desktop permission dialogs.

Run this while a "Always allow" permission dialog is visible in Claude Desktop.
Output saved to uia_tree_dump.txt and printed to console.
"""

import sys
import datetime
from pathlib import Path

try:
    from pywinauto import Desktop, Application
    from pywinauto.uia_defines import IUIA
except ImportError:
    print("Missing dependency. Run: pip install -r requirements.txt")
    sys.exit(1)


OUTPUT_FILE = Path("uia_tree_dump.txt")
CLAUDE_PROCESS_NAMES = ["claude", "claude desktop", "claude.exe"]


def find_claude_app():
    """Return pywinauto Application connected to Claude Desktop, or None."""
    desktop = Desktop(backend="uia")
    for win in desktop.windows():
        try:
            name = win.window_text().lower()
            proc = win.process_id()
            # Claude Desktop windows are titled "Claude" or contain "Claude"
            if "claude" in name:
                return win, Application(backend="uia").connect(process=proc)
        except Exception:
            continue
    return None, None


def dump_element(elem, depth=0, lines=None):
    """Recursively dump UIA element tree into lines list."""
    if lines is None:
        lines = []
    indent = "  " * depth
    try:
        ctrl_type = elem.element_info.control_type
        name = elem.element_info.name or ""
        auto_id = getattr(elem.element_info, "automation_id", "") or ""
        class_name = elem.element_info.class_name or ""
        rect = elem.element_info.rectangle
        line = (
            f"{indent}[{ctrl_type}] name={name!r} "
            f"auto_id={auto_id!r} class={class_name!r} "
            f"rect=({rect.left},{rect.top},{rect.right},{rect.bottom})"
        )
        lines.append(line)
    except Exception as exc:
        lines.append(f"{indent}<error reading element: {exc}>")
        return lines

    try:
        children = elem.children()
    except Exception:
        children = []

    for child in children:
        dump_element(child, depth + 1, lines)

    return lines


def dump_all_claude_windows():
    desktop = Desktop(backend="uia")
    results = []

    for win in desktop.windows():
        try:
            title = win.window_text()
        except Exception:
            continue
        if "claude" not in title.lower():
            continue

        results.append(f"\n{'='*70}")
        results.append(f"WINDOW: {title!r}  pid={win.process_id()}")
        results.append(f"{'='*70}")
        try:
            lines = dump_element(win)
            results.extend(lines)
        except Exception as exc:
            results.append(f"  <failed to dump: {exc}>")

    return results


def main():
    print("Claude Desktop UIA Tree Diagnostic")
    print(f"Time: {datetime.datetime.now().isoformat()}")
    print("Looking for Claude Desktop windows...\n")

    lines = dump_all_claude_windows()

    if not lines:
        print("No Claude Desktop windows found.")
        print("Make sure Claude Desktop is running and a dialog is visible.")
        sys.exit(1)

    header = [
        f"UIA Tree Dump — {datetime.datetime.now().isoformat()}",
        "Run while 'Always allow' permission dialog is open.",
        "Search for 'Always allow' or 'allow' in this file to find the button.",
        "",
    ]
    output = "\n".join(header + lines)

    OUTPUT_FILE.write_text(output, encoding="utf-8")
    # Print with unicode error replacement so Windows cp1252 console doesn't crash
    safe_output = output.encode("cp1252", errors="replace").decode("cp1252")
    print(safe_output)
    print(f"\n\nDump saved to: {OUTPUT_FILE.resolve()}")
    print("\nTips:")
    print("  1. Search uia_tree_dump.txt for 'allow' (case-insensitive)")
    print("  2. Note the [ControlType], name=, and auto_id= of the button")
    print("  3. If nothing matches, the button lives inside Chromium's web layer")
    print("     — autoallow.py will fall back to screenshot-based matching")


if __name__ == "__main__":
    main()
