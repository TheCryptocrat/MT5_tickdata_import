"""Capture the TDM window to PNG, plus crop the top-toolbar area for closer look."""

from pathlib import Path
import time

from pywinauto import Application
from PIL import ImageGrab

SCRIPT_DIR = Path(__file__).resolve().parent


def main():
    app = Application(backend="uia").connect(title_re=r"Tick Data Manager.*", timeout=15)
    main_win = app.window(title_re=r"Tick Data Manager.*")
    main_win.set_focus()
    main_win.restore()
    time.sleep(1.5)
    rect = main_win.rectangle()
    print(f"window rect: {rect}")

    full = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
    full.save(SCRIPT_DIR / "tdm_full.png")
    # Top-right toolbar area (mystery buttons): roughly 1450..1710, 375..415 from earlier tree
    toolbar = ImageGrab.grab(bbox=(rect.left + 600, rect.top + 30, rect.right, rect.top + 75))
    toolbar.save(SCRIPT_DIR / "tdm_toolbar.png")
    print("saved tdm_full.png, tdm_toolbar.png")


if __name__ == "__main__":
    main()
