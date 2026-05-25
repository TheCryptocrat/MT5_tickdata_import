"""Click the per-row '...' button on a filtered EURUSD row, dump resulting menu/popup."""

from __future__ import annotations

import json
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
    d = {
        "control_type": info.control_type,
        "name": info.name,
        "automation_id": info.automation_id,
        "class_name": info.class_name,
        "rectangle": rect_t,
        "children": [],
    }
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
    name = (node.get("name") or "")[:50]
    aid = node.get("automation_id") or ""
    cls = node.get("class_name") or ""
    ct = node.get("control_type") or "?"
    rect = node.get("rectangle")
    lines.append(f"{pad}[{ct}] name={name!r:<25}  id={aid!r:<22}  cls={cls!r:<18}  @{rect}")
    for child in node.get("children", []):
        if "error" in child:
            lines.append(f"{pad}  <err>")
        else:
            render(child, indent + 1, lines)
    return lines


def dump_popups(app, label):
    out = []
    main_pid = app.process
    for w in Desktop(backend="uia").windows():
        try:
            if w.process_id() == main_pid and w.window_text() != "Tick Data Manager":
                out.append({
                    "title": w.window_text(),
                    "class": w.class_name(),
                    "tree": node_dict(w, 0, 8),
                })
        except Exception:
            continue
    # Also any new Menu/MenuItem controls under main window
    main_win = app.window(title_re=r"Tick Data Manager.*")
    menus = []
    try:
        for ct in ("Menu", "MenuItem", "Popup", "ContextMenu"):
            for m in main_win.descendants(control_type=ct):
                menus.append({"control_type": ct,
                              "name": m.element_info.name,
                              "tree": node_dict(m, 0, 5)})
    except Exception as exc:
        menus.append({"error": repr(exc)})
    return {"label": label, "popups": out, "menus": menus}


def main():
    app = Application(backend="uia").connect(title_re=r"Tick Data Manager.*", timeout=15)
    main_win = app.window(title_re=r"Tick Data Manager.*")
    main_win.set_focus()
    main_win.restore()
    time.sleep(1.5)

    # Re-filter to EURUSD (it might already be filtered from the previous probe)
    txt = main_win.child_window(auto_id="TxtFilter", control_type="Edit")
    txt.click_input()
    send_keys("^a{DEL}EURUSD", with_spaces=True, pause=0.04)
    time.sleep(1.8)

    # Locate the unnamed '...' button inside the only row
    grid = main_win.child_window(auto_id="DataGridSymbol", control_type="DataGrid")
    rows = grid.descendants(control_type="DataItem")
    if not rows:
        print("NO ROWS visible after filtering")
        return 1
    row = rows[0]
    # Find the buttons inside Cell_AllowedGaps cell
    cells = [c for c in row.descendants(control_type="Custom")
             if c.element_info.automation_id == "Cell_AllowedGaps"]
    print(f"Cell_AllowedGaps cells found: {len(cells)}")
    if not cells:
        print("no Cell_AllowedGaps; aborting")
        return 1
    cell = cells[0]
    buttons = cell.descendants(control_type="Button")
    print(f"buttons in cell: {len(buttons)}")
    for i, b in enumerate(buttons):
        try:
            r = b.rectangle()
            print(f"  [{i}] id={b.element_info.automation_id!r}  name={b.element_info.name!r}  @{(r.left, r.top, r.right, r.bottom)}")
        except Exception as exc:
            print(f"  [{i}] err: {exc}")

    # First button (no id) at ~ (1652, 462) -> (1668, 478) is the '...' menu
    if len(buttons) >= 1:
        ellipsis_btn = buttons[0]
        print("clicking '...' button...")
        ellipsis_btn.click_input()
        time.sleep(1.2)

        snap = dump_popups(app, "after_ellipsis_click")

        lines = ["=== POPUPS AFTER '...' CLICK ==="]
        for p in snap["popups"]:
            lines.append(f"-- popup: title={p['title']!r} class={p['class']!r}")
            render(p["tree"], 1, lines)
            lines.append("")
        lines.append("=== MENU/POPUP descendants in main window ===")
        for m in snap["menus"]:
            if "error" in m:
                lines.append(f"  <err: {m['error']}>")
                continue
            lines.append(f"  [{m['control_type']}] name={m['name']!r}")
            render(m["tree"], 1, lines)
        (SCRIPT_DIR / "probe_04_ellipsis_menu.txt").write_text("\n".join(lines), encoding="utf-8")
        print("wrote probe_04_ellipsis_menu.txt")

        # Screenshot the area around (1640, 460) where the menu probably appears
        img = ImageGrab.grab(bbox=(1500, 440, 1900, 800))
        img.save(SCRIPT_DIR / "tdm_ellipsis_menu.png")
        print("wrote tdm_ellipsis_menu.png")

    # Press ESC to close any menu before exiting
    send_keys("{ESC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
