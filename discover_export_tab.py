"""Open the EURUSD operations dialog, click each tab, dump its contents."""

from __future__ import annotations

import time
from pathlib import Path

from pywinauto import Application, Desktop
from pywinauto.keyboard import send_keys
from PIL import ImageGrab

SCRIPT_DIR = Path(__file__).resolve().parent


def node_dict(elem, depth, max_depth):
    info = elem.element_info
    try:
        rect = elem.rectangle()
        rect_t = (rect.left, rect.top, rect.right, rect.bottom)
    except Exception:
        rect_t = None
    d = {"control_type": info.control_type, "name": info.name,
         "automation_id": info.automation_id, "class_name": info.class_name,
         "rectangle": rect_t, "children": []}
    if depth >= max_depth:
        return d
    try:
        children = elem.children()
    except Exception:
        return d
    for child in children:
        try:
            d["children"].append(node_dict(child, depth + 1, max_depth))
        except Exception as exc:
            d["children"].append({"error": repr(exc)})
    return d


def render(node, indent=0, lines=None):
    if lines is None:
        lines = []
    pad = "  " * indent
    name = (node.get("name") or "")[:60]
    aid = node.get("automation_id") or ""
    cls = node.get("class_name") or ""
    ct = node.get("control_type") or "?"
    rect = node.get("rectangle")
    lines.append(f"{pad}[{ct}] name={name!r:<32}  id={aid!r:<22}  cls={cls!r:<18}  @{rect}")
    for child in node.get("children", []):
        if "error" in child:
            lines.append(f"{pad}  <err>")
        else:
            render(child, indent + 1, lines)
    return lines


def find_operations_window(main_win):
    """The operations dialog is a child Window of main_win."""
    for c in main_win.children():
        try:
            if c.element_info.control_type == "Window" and "operations" in (c.window_text() or "").lower():
                return c
        except Exception:
            continue
    # Fallback: any Window child whose title contains 'operations'
    return None


def main():
    app = Application(backend="uia").connect(title_re=r"Tick Data Manager.*", timeout=15)
    main_win = app.window(title_re=r"Tick Data Manager.*")
    try:
        main_win.set_focus()
    except Exception:
        pass
    try:
        main_win.restore()
    except Exception:
        pass
    time.sleep(1.0)

    # close any leftover operations dialog from a previous run
    for c in main_win.children():
        try:
            if c.element_info.control_type == "Window" and "operations" in (c.window_text() or "").lower():
                print(f"closing leftover dialog: {c.window_text()}")
                try:
                    c.child_window(auto_id="BtnCancel", control_type="Button").click_input()
                except Exception:
                    send_keys("{ESC}")
                time.sleep(0.6)
        except Exception:
            continue

    # filter to EURUSD
    txt = main_win.child_window(auto_id="TxtFilter", control_type="Edit")
    txt.click_input()
    send_keys("^a{DEL}EURUSD", with_spaces=True, pause=0.04)
    time.sleep(1.5)

    grid = main_win.child_window(auto_id="DataGridSymbol", control_type="DataGrid")
    rows = grid.descendants(control_type="DataItem")
    if not rows:
        print("no rows"); return 1
    row = rows[0]
    cells = [c for c in row.descendants(control_type="Custom")
             if c.element_info.automation_id == "Cell_AllowedGaps"]
    buttons = cells[0].descendants(control_type="Button")
    ops_btn = buttons[0]
    ops_btn.click_input()
    time.sleep(1.5)

    ops_win = find_operations_window(main_win)
    if ops_win is None:
        print("operations dialog NOT found"); return 1
    print(f"operations window: {ops_win.window_text()!r} rect={ops_win.rectangle()}")

    # Iterate over the tabs we care about
    tabs = [("TabExportTicks", "export_ticks"),
            ("TabExportBars", "export_bars"),
            ("TabManage", "manage"),
            ("TabProperties", "properties")]

    for auto_id, label in tabs:
        try:
            tab = next((d for d in ops_win.descendants(control_type="TabItem")
                        if d.element_info.automation_id == auto_id), None)
            if tab is None:
                print(f"  no TabItem with id {auto_id}"); continue
            print(f"clicking tab {auto_id}...")
            tab.click_input()
            time.sleep(1.2)
            # Screenshot the dialog area
            r = ops_win.rectangle()
            img = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom))
            img.save(SCRIPT_DIR / f"opsdlg_{label}.png")
            # Dump the dialog tree
            tree = node_dict(ops_win, 0, 8)
            (SCRIPT_DIR / f"opsdlg_{label}.txt").write_text(
                "\n".join(render(tree)), encoding="utf-8"
            )
            print(f"  wrote opsdlg_{label}.png / .txt")
        except Exception as exc:
            print(f"  ERROR clicking {auto_id}: {exc}")

    # close the dialog
    try:
        cancel = next((d for d in ops_win.descendants(control_type="Button")
                       if d.element_info.automation_id == "BtnCancel"), None)
        if cancel:
            cancel.click_input()
            time.sleep(0.5)
        else:
            send_keys("{ESC}")
    except Exception:
        send_keys("{ESC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
