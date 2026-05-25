"""Hover over toolbar buttons to capture tooltips."""

from __future__ import annotations

import time
from pathlib import Path

from pywinauto import Application, Desktop
from pywinauto.controls.uiawrapper import UIAWrapper
from pywinauto.mouse import move
from PIL import ImageGrab

SCRIPT_DIR = Path(__file__).resolve().parent


def main():
    app = Application(backend="uia").connect(title_re=r"Tick Data Manager.*", timeout=15)
    main_win = app.window(title_re=r"Tick Data Manager.*")
    main_win.set_focus()
    main_win.restore()
    time.sleep(1.0)

    targets = [
        ("filter_clear", 1616, 395),    # the ✖
        ("toolbar_btn1",  1644, 395),   # mystery 1
        ("toolbar_btn2",  1670, 395),   # mystery 2
        ("toolbar_options", 1694, 395), # ☰ BtnOptions
        ("provider_dots", 1016, 395),   # ⋮ next to providers
        ("row_dots", 1660, 470),        # the ... on the EURUSD row
        ("row_download", 1677, 470),    # the per-row download arrow
    ]

    for label, x, y in targets:
        move(coords=(300, 300))
        time.sleep(0.6)
        print(f"hovering {label} at ({x},{y})")
        move(coords=(x, y))
        time.sleep(2.5)  # wait for tooltip to appear
        # Capture full window region
        rect = main_win.rectangle()
        img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
        img.save(SCRIPT_DIR / f"hover_{label}.png")

        # Also look for any Tooltip control on the desktop
        for w in Desktop(backend="uia").windows():
            try:
                if w.element_info.control_type == "ToolTip":
                    print(f"  TOOLTIP: {w.window_text()!r}")
            except Exception:
                pass

    # Move mouse back
    move(coords=(300, 300))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
