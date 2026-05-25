"""Click the per-row Operations '...' button. Capture FULL desktop screenshot so
popups that extend beyond the window are visible. Also dump the entire UIA tree
of every top-level window including unowned popups."""

from __future__ import annotations

import time
from pathlib import Path

from pywinauto import Application, Desktop
from pywinauto.keyboard import send_keys
from pywinauto.mouse import move
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
    lines.append(f"{pad}[{ct}] name={name!r:<30}  id={aid!r:<22}  cls={cls!r:<18}  @{rect}")
    for child in node.get("children", []):
        if "error" in child:
            lines.append(f"{pad}  <err>")
        else:
            render(child, indent + 1, lines)
    return lines


def main():
    app = Application(backend="uia").connect(title_re=r"Tick Data Manager.*", timeout=15)
    main_win = app.window(title_re=r"Tick Data Manager.*")
    main_win.set_focus()
    main_win.restore()
    time.sleep(1.2)

    # Re-filter to EURUSD
    txt = main_win.child_window(auto_id="TxtFilter", control_type="Edit")
    txt.click_input()
    send_keys("^a{DEL}EURUSD", with_spaces=True, pause=0.05)
    time.sleep(2.0)

    grid = main_win.child_window(auto_id="DataGridSymbol", control_type="DataGrid")
    rows = grid.descendants(control_type="DataItem")
    if not rows:
        print("no rows after filtering"); return 1
    row = rows[0]
    cells = [c for c in row.descendants(control_type="Custom")
             if c.element_info.automation_id == "Cell_AllowedGaps"]
    buttons = cells[0].descendants(control_type="Button")
    ops_btn = buttons[0]  # the '...' one
    print(f"Operations button rectangle: {ops_btn.rectangle()}")

    # Click the operations button
    ops_btn.click_input()
    # Don't move the mouse! That might dismiss the menu. Just sleep.
    time.sleep(1.5)

    # Full desktop screenshot (catches popups anywhere on screen)
    img = ImageGrab.grab()
    img.save(SCRIPT_DIR / "desktop_after_ops_click.png")
    print("saved desktop_after_ops_click.png")

    # Dump ALL top-level windows owned by TDM process
    pid = app.process
    candidates = []
    for w in Desktop(backend="uia").windows():
        try:
            if w.process_id() == pid:
                candidates.append(w)
        except Exception:
            pass
    print(f"top-level windows from TDM pid={pid}: {len(candidates)}")
    lines = []
    for w in candidates:
        try:
            title = w.window_text()
            cls = w.class_name()
            ct = w.element_info.control_type
            rect = w.rectangle()
            lines.append(f"== window: title={title!r}  cls={cls!r}  ct={ct}  rect={(rect.left, rect.top, rect.right, rect.bottom)}")
            tree = node_dict(w, 0, 7)
            render(tree, 1, lines)
            lines.append("")
        except Exception as exc:
            lines.append(f"<err: {exc}>")
    (SCRIPT_DIR / "probe_05_top_level_windows.txt").write_text("\n".join(lines), encoding="utf-8")
    print("wrote probe_05_top_level_windows.txt")

    # Also dump the main window descendants now (in case menu is inside)
    main_tree = node_dict(main_win, 0, 9)
    (SCRIPT_DIR / "probe_05_main_full_tree.txt").write_text(
        "\n".join(render(main_tree)), encoding="utf-8"
    )
    print("wrote probe_05_main_full_tree.txt")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
