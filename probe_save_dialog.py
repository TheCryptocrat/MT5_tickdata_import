"""Trigger Start export on AUDNZD, list EVERY top-level window on desktop right after."""

from __future__ import annotations
import time
from pathlib import Path
from pywinauto import Application, Desktop
from pywinauto.keyboard import send_keys
from PIL import ImageGrab

SCRIPT_DIR = Path(__file__).resolve().parent
TDM_EXE = r"D:\TickData\Tick Data Manager.exe"


def main():
    try:
        app = Application(backend="uia").connect(title_re=r"Tick Data Manager.*", timeout=5)
    except Exception:
        app = Application(backend="uia").start(f'"{TDM_EXE}"')
        time.sleep(20)
    main_win = app.window(title_re=r"Tick Data Manager.*")
    try: main_win.set_focus()
    except: pass
    time.sleep(1.0)

    # filter to AUDNZD
    txt = next((d for d in main_win.descendants(control_type="Edit")
                if d.element_info.automation_id == "TxtFilter"), None)
    txt.click_input()
    send_keys("^a{DEL}AUDNZD", with_spaces=True, pause=0.04)
    time.sleep(1.5)
    grid = next((d for d in main_win.descendants(control_type="DataGrid")
                 if d.element_info.automation_id == "DataGridSymbol"), None)
    rows = grid.descendants(control_type="DataItem")
    if not rows:
        print("no AUDNZD row"); return 1
    cells = [c for c in rows[0].descendants(control_type="Custom")
             if c.element_info.automation_id == "Cell_AllowedGaps"]
    buttons = cells[0].descendants(control_type="Button")
    buttons[0].click_input()
    time.sleep(1.5)

    ops_win = None
    for c in main_win.children():
        try:
            if c.element_info.control_type == "Window" and "operations" in (c.window_text() or "").lower():
                ops_win = c; break
        except: continue
    print(f"ops_win: {ops_win.window_text() if ops_win else None}")

    tab = next((d for d in ops_win.descendants(control_type="TabItem")
                if d.element_info.automation_id == "TabExportTicks"), None)
    tab.click_input(); time.sleep(0.8)

    btn = next((d for d in ops_win.descendants(control_type="Button")
                if d.element_info.automation_id == "BtnExportTicksStartExport"), None)
    print("clicking Start export...")
    btn.click_input()

    # Immediately list everything every second for 8 seconds
    for sec in range(8):
        time.sleep(1.0)
        print(f"\n--- t={sec+1}s ---")
        for w in Desktop(backend="uia").windows():
            try:
                title = (w.window_text() or "").strip()
                cls = w.class_name() or ""
                pid = w.process_id()
                ct = w.element_info.control_type
                rect = w.rectangle()
                # Skip very small / off-screen
                if rect.right - rect.left < 50 or rect.bottom - rect.top < 50:
                    continue
                print(f"  pid={pid:<6} ct={ct:<10} cls={cls!r:<24} title={title!r}")
            except Exception:
                continue
        # Stop early if a dialog with "save" or class "#32770" appears
        for w in Desktop(backend="uia").windows():
            try:
                if (w.class_name() or "") == "#32770" or "save" in (w.window_text() or "").lower():
                    print(f"  >>> CANDIDATE: pid={w.process_id()} cls={w.class_name()} title={w.window_text()!r}")
            except:
                pass

    # Full desktop screenshot for visual confirmation
    ImageGrab.grab().save(SCRIPT_DIR / "probe_save_desktop.png")

    # Look for any window whose title contains "save" or "csv" or "export"
    print("\n--- final scan for save/export dialog ---")
    for w in Desktop(backend="uia").windows():
        try:
            title = (w.window_text() or "").lower()
            if "save" in title or "export" in title or "csv" in title or w.class_name() == "#32770":
                print(f"  found: pid={w.process_id()} cls={w.class_name()} title={w.window_text()!r}")
                # Try to cancel
                for b in w.descendants(control_type="Button"):
                    if (b.window_text() or "").lower() in ("cancel", "&cancel"):
                        b.click_input()
                        print(f"    -> cancelled")
                        break
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
