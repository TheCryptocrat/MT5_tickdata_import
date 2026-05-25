"""Try multiple strategies to fill the Save As filename, verify which works."""

from __future__ import annotations
import time
import subprocess
from pathlib import Path

from pywinauto import Application
from pywinauto.keyboard import send_keys

SCRIPT_DIR = Path(__file__).resolve().parent
TARGET = r"D:\TickData\AUDNZD\AUDNZD_GMT+2_US-DST.csv"


def open_dialog():
    try:
        app = Application(backend="uia").connect(title_re=r"Tick Data Manager.*", timeout=5)
    except Exception:
        app = Application(backend="uia").start(r'"D:\TickData\Tick Data Manager.exe"')
        time.sleep(20)
    main_win = app.window(title_re=r"Tick Data Manager.*")
    try: main_win.set_focus()
    except: pass
    time.sleep(0.8)

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
    ops_win = next((c for c in main_win.children()
                    if c.element_info.control_type == "Window" and "operations" in (c.window_text() or "").lower()),
                   None)
    tab = next((d for d in ops_win.descendants(control_type="TabItem")
                if d.element_info.automation_id == "TabExportTicks"), None)
    tab.click_input(); time.sleep(0.6)
    btn = next((d for d in ops_win.descendants(control_type="Button")
                if d.element_info.automation_id == "BtnExportTicksStartExport"), None)
    btn.click_input()
    time.sleep(2.5)

    # Find Save As dialog
    for d in main_win.descendants(control_type="Window"):
        try:
            if (d.class_name() or "") == "#32770":
                return main_win, d
        except: continue
    return main_win, None


def get_edit_value(dlg):
    edit = next((e for e in dlg.descendants(control_type="Edit")
                 if e.element_info.automation_id == "1001"), None)
    if not edit: return "<no Edit>"
    try:
        v = edit.legacy_properties()
        return v.get("Value", "") or v.get("Name", "")
    except Exception as exc:
        return f"<err {exc}>"


def try_strategy(label, fn, dlg):
    print(f"\n--- {label} ---")
    try:
        fn(dlg)
        time.sleep(0.5)
        val = get_edit_value(dlg)
        print(f"  edit value after: {val!r}")
    except Exception as exc:
        print(f"  ERROR: {exc}")


def main():
    main_win, dlg = open_dialog()
    if dlg is None:
        print("no Save As dialog"); return 1
    print(f"dlg = {dlg.window_text()!r} {dlg.class_name()!r}")
    print(f"initial value: {get_edit_value(dlg)!r}")

    # Strategy A: send_keys to whatever has focus on dialog
    def A(d):
        d.set_focus()
        time.sleep(0.3)
        send_keys("^a{DEL}", pause=0.05)
        subprocess.run(["clip"], input=TARGET.encode("utf-16-le"), check=True, timeout=5)
        send_keys("^v", pause=0.05)
    try_strategy("A: dlg.set_focus + paste", A, dlg)

    # Strategy B: click on FileNameControlHost combo
    def B(d):
        combo = next((c for c in d.descendants(control_type="ComboBox")
                      if c.element_info.automation_id == "FileNameControlHost"), None)
        combo.click_input(); time.sleep(0.3)
        send_keys("^a{DEL}", pause=0.05)
        subprocess.run(["clip"], input=TARGET.encode("utf-16-le"), check=True, timeout=5)
        send_keys("^v", pause=0.05)
    try_strategy("B: click combo + paste", B, dlg)

    # Strategy C: edit.set_text (Win32 WM_SETTEXT)
    def C(d):
        edit = next((e for e in d.descendants(control_type="Edit")
                     if e.element_info.automation_id == "1001"), None)
        edit.set_text(TARGET)
    try_strategy("C: edit.set_text WM_SETTEXT", C, dlg)

    # Strategy D: type via send_keys with no click (dialog has default focus on filename)
    def D(d):
        # Don't focus anything; the freshly-opened dialog should already have focus
        send_keys("^a{DEL}", pause=0.05)
        # type each char (no clipboard) — slow but reliable
        for ch in TARGET:
            if ch == "+":
                send_keys("{+}", pause=0.01)
            else:
                send_keys(ch, with_spaces=True, pause=0.01)
    try_strategy("D: char-by-char type (no click)", D, dlg)

    # Cancel
    cancel = next((b for b in dlg.descendants(control_type="Button")
                   if b.element_info.automation_id == "2"
                   or (b.window_text() or "").strip().lower() in ("cancel", "&cancel")), None)
    if cancel: cancel.click_input(); print("cancelled")


if __name__ == "__main__":
    raise SystemExit(main())
