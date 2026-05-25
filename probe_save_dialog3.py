"""Open AUDNZD ops, click Start export, then dump the FULL Save As dialog tree
and identify exactly the filename Edit and Save Button to use."""

from __future__ import annotations
import time
from pathlib import Path

from pywinauto import Application, Desktop
from pywinauto.keyboard import send_keys

SCRIPT_DIR = Path(__file__).resolve().parent


def render(elem, depth, max_depth, lines, indent=0):
    if depth > max_depth: return
    try:
        info = elem.element_info
        try:
            r = elem.rectangle(); rect=(r.left,r.top,r.right,r.bottom)
        except: rect = None
        pad = "  "*indent
        lines.append(f"{pad}[{info.control_type}] name={(info.name or '')[:40]!r} id={(info.automation_id or '')!r} cls={(info.class_name or '')!r} rect={rect}")
        for c in elem.children():
            render(c, depth+1, max_depth, lines, indent+1)
    except Exception as exc:
        lines.append(f"{'  '*indent}<err: {exc}>")


def main():
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
    time.sleep(3.0)

    # Find Save As dialog
    save_dlg = None
    for d in main_win.descendants(control_type="Window"):
        try:
            if (d.class_name() or "") == "#32770" or (d.window_text() or "").lower() == "save as":
                save_dlg = d; break
        except: continue
    if save_dlg is None:
        print("no save dialog"); return 1

    print(f"save dialog: {save_dlg.window_text()!r} {save_dlg.class_name()!r}")
    lines = []
    render(save_dlg, 0, 6, lines)
    (SCRIPT_DIR / "probe_savedlg_tree.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote probe_savedlg_tree.txt ({len(lines)} lines)")

    # Find all Edit controls and print their current values
    print("\nAll Edit descendants in Save As dialog:")
    for i, e in enumerate(save_dlg.descendants(control_type="Edit")):
        try:
            r = e.rectangle()
            text = e.window_text() or ""
            print(f"  [{i}] id={e.element_info.automation_id!r:<10} name={e.element_info.name!r:<25} text={text[:80]!r} @{(r.left,r.top,r.right,r.bottom)}")
        except Exception as exc:
            print(f"  [{i}] err: {exc}")

    print("\nAll Button descendants in Save As dialog:")
    for i, b in enumerate(save_dlg.descendants(control_type="Button")):
        try:
            r = b.rectangle()
            print(f"  [{i}] id={b.element_info.automation_id!r:<10} name={b.element_info.name!r:<25} @{(r.left,r.top,r.right,r.bottom)}")
        except Exception as exc:
            print(f"  [{i}] err: {exc}")

    print("\nAll ComboBox descendants in Save As dialog:")
    for i, c in enumerate(save_dlg.descendants(control_type="ComboBox")):
        try:
            r = c.rectangle()
            print(f"  [{i}] id={c.element_info.automation_id!r:<10} name={c.element_info.name!r:<25} text={(c.window_text() or '')[:80]!r} @{(r.left,r.top,r.right,r.bottom)}")
        except Exception as exc:
            print(f"  [{i}] err: {exc}")

    # cancel
    cancel_btn = next((b for b in save_dlg.descendants(control_type="Button")
                       if (b.window_text() or "").strip().lower() in ("cancel", "&cancel")), None)
    if cancel_btn:
        cancel_btn.click_input(); print("cancelled")
    else:
        send_keys("{ESC}")


if __name__ == "__main__":
    raise SystemExit(main())
