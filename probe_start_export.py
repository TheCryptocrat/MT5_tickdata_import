"""Click Start export on EURUSD and see what happens. Cancel immediately."""

from __future__ import annotations
import time
from pathlib import Path

from pywinauto import Application, Desktop
from pywinauto.keyboard import send_keys
from PIL import ImageGrab

SCRIPT_DIR = Path(__file__).resolve().parent


def main():
    app = Application(backend="uia").connect(title_re=r"Tick Data Manager.*", timeout=15)
    main_win = app.window(title_re=r"Tick Data Manager.*")
    try: main_win.set_focus()
    except: pass
    time.sleep(0.8)

    # Find / open the ops dialog for EURUSD
    ops_win = None
    for c in main_win.children():
        try:
            if c.element_info.control_type == "Window" and "operations" in (c.window_text() or "").lower():
                ops_win = c
                break
        except: continue
    if ops_win is None:
        # open it
        txt = main_win.child_window(auto_id="TxtFilter", control_type="Edit")
        txt.click_input(); send_keys("^a{DEL}EURUSD", with_spaces=True, pause=0.04); time.sleep(1.5)
        grid = main_win.child_window(auto_id="DataGridSymbol", control_type="DataGrid")
        rows = grid.descendants(control_type="DataItem")
        cells = [c for c in rows[0].descendants(control_type="Custom")
                 if c.element_info.automation_id == "Cell_AllowedGaps"]
        buttons = cells[0].descendants(control_type="Button")
        buttons[0].click_input(); time.sleep(1.5)
        for c in main_win.children():
            try:
                if c.element_info.control_type == "Window" and "operations" in (c.window_text() or "").lower():
                    ops_win = c; break
            except: continue
    if ops_win is None:
        print("no ops dialog"); return 1

    # Click TabExportTicks
    tab = next((d for d in ops_win.descendants(control_type="TabItem")
                if d.element_info.automation_id == "TabExportTicks"), None)
    tab.click_input(); time.sleep(1.0)

    # Click Start export
    btn = next((d for d in ops_win.descendants(control_type="Button")
                if d.element_info.automation_id == "BtnExportTicksStartExport"), None)
    if not btn:
        print("no start export button"); return 1
    print("clicking Start export...")
    btn.click_input()
    time.sleep(2.5)

    # Screenshot whole desktop
    ImageGrab.grab().save(SCRIPT_DIR / "after_start_export.png")
    print("saved after_start_export.png")

    # Look for any new top-level windows in TDM process or system file dialog
    pid = app.process
    for w in Desktop(backend="uia").windows():
        try:
            t = w.window_text() or ""
            c = w.class_name() or ""
            if w.process_id() == pid:
                print(f"TDM-window  title={t!r}  class={c!r}")
            elif c in ("#32770",) or "save" in t.lower() or "export" in t.lower():
                print(f"OTHER-window  title={t!r}  class={c!r}")
        except: continue

    # If a file save dialog opened, screenshot it
    save_dialogs = [w for w in Desktop(backend="uia").windows()
                    if (w.class_name() in ("#32770",) and "save" in (w.window_text() or "").lower())]
    for w in save_dialogs:
        r = w.rectangle()
        ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom)).save(SCRIPT_DIR / "save_dialog.png")
        print(f"file save dialog: {w.window_text()!r}")
        # Cancel it
        try:
            cancel = next((d for d in w.descendants(control_type="Button")
                           if (d.window_text() or "").lower() == "cancel"), None)
            if cancel:
                cancel.click_input()
                print("cancelled save dialog")
        except Exception as exc:
            print(f"could not cancel: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
