"""After clicking Start export, enumerate descendants of TDM main window AND
all windows visible on the desktop via a broader scan. We saw the dialog in
the screenshot but Desktop().windows() didn't list it — so it must be a child
window in the UIA tree, or owned through a different parent."""

from __future__ import annotations
import time
from pathlib import Path
from pywinauto import Application, Desktop
from pywinauto.keyboard import send_keys

import ctypes
import ctypes.wintypes as wt

SCRIPT_DIR = Path(__file__).resolve().parent


def enum_top_level_windows_winapi():
    """Use Win32 EnumWindows to list every top-level window — bypasses UIA tree."""
    user32 = ctypes.windll.user32
    rows = []
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        rows.append((hwnd, pid.value, cls.value, buf.value))
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return rows


def main():
    app = Application(backend="uia").connect(title_re=r"Tick Data Manager.*", timeout=10)
    main_win = app.window(title_re=r"Tick Data Manager.*")
    try: main_win.set_focus()
    except: pass
    time.sleep(0.8)

    # filter to AUDNZD and open ops if needed
    ops_win = None
    for c in main_win.children():
        try:
            if c.element_info.control_type == "Window" and "operations" in (c.window_text() or "").lower():
                ops_win = c; break
        except: continue
    if ops_win is None:
        txt = next((d for d in main_win.descendants(control_type="Edit")
                    if d.element_info.automation_id == "TxtFilter"), None)
        txt.click_input(); send_keys("^a{DEL}AUDNZD", with_spaces=True, pause=0.04); time.sleep(1.5)
        grid = next((d for d in main_win.descendants(control_type="DataGrid")
                     if d.element_info.automation_id == "DataGridSymbol"), None)
        rows = grid.descendants(control_type="DataItem")
        cells = [c for c in rows[0].descendants(control_type="Custom")
                 if c.element_info.automation_id == "Cell_AllowedGaps"]
        buttons = cells[0].descendants(control_type="Button")
        buttons[0].click_input(); time.sleep(1.5)
        for c in main_win.children():
            if c.element_info.control_type == "Window" and "operations" in (c.window_text() or "").lower():
                ops_win = c; break
    print(f"ops_win: {ops_win.window_text() if ops_win else None}")

    tab = next((d for d in ops_win.descendants(control_type="TabItem")
                if d.element_info.automation_id == "TabExportTicks"), None)
    tab.click_input(); time.sleep(0.6)

    print("clicking Start export...")
    btn = next((d for d in ops_win.descendants(control_type="Button")
                if d.element_info.automation_id == "BtnExportTicksStartExport"), None)
    btn.click_input()
    time.sleep(2.5)

    # 1) Enumerate top-level windows via WinAPI EnumWindows (catches everything visible)
    print("\n=== WinAPI EnumWindows ===")
    for hwnd, pid, cls, title in enum_top_level_windows_winapi():
        if title or "dialog" in cls.lower() or cls == "#32770":
            print(f"  hwnd={hwnd:<10} pid={pid:<6} cls={cls!r:<28} title={title!r}")

    # 2) Look at children of main_win recursively, anything Window-like
    print("\n=== descendants of main_win with ct=Window ===")
    for d in main_win.descendants():
        try:
            if d.element_info.control_type == "Window":
                t = d.window_text(); cls = d.class_name()
                r = d.rectangle()
                print(f"  ct=Window title={t!r:<40} cls={cls!r:<20} rect={(r.left,r.top,r.right,r.bottom)}")
        except Exception:
            pass

    # 3) Check ops_win children
    print("\n=== children of ops_win ===")
    for d in ops_win.children():
        try:
            ct = d.element_info.control_type
            t = d.window_text(); cls = d.class_name()
            r = d.rectangle()
            print(f"  ct={ct:<10} title={t!r:<40} cls={cls!r:<20} rect={(r.left,r.top,r.right,r.bottom)}")
        except Exception:
            pass

    # cancel
    send_keys("{ESC}"); time.sleep(0.5)
    send_keys("{ESC}"); time.sleep(0.5)


if __name__ == "__main__":
    raise SystemExit(main())
