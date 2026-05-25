"""Attach to TDM, filter to one symbol, right-click the row, dump menu + popups."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from pywinauto import Application, Desktop
from pywinauto.controls.uiawrapper import UIAWrapper
from pywinauto.keyboard import send_keys

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


def dump_all_popups(app, label):
    """Find all top-level windows from app's process (besides main) and dump them."""
    out = []
    main_pid = app.process
    for w in Desktop(backend="uia").windows():
        try:
            if w.process_id() == main_pid and w.window_text() != "Tick Data Manager":
                out.append({"title": w.window_text(), "class": w.class_name(),
                            "tree": node_dict(w, 0, 7)})
        except Exception:
            continue
    # Also check the main window for any newly-materialized menus
    main_win = app.window(title_re=r"Tick Data Manager.*")
    main_tree = node_dict(main_win, 0, 7)
    # Find Menu/MenuItem descendants in main
    return {"label": label, "popups": out, "main_at_moment": main_tree}


def main() -> int:
    print("attaching to running TDM (start it manually first if not running)...")
    try:
        app = Application(backend="uia").connect(title_re=r"Tick Data Manager.*", timeout=10)
    except Exception as exc:
        print(f"could not attach: {exc}", file=sys.stderr)
        print("trying to launch...", file=sys.stderr)
        app = Application(backend="uia").start(r'"D:\TickData\Tick Data Manager.exe"')
        time.sleep(15)

    main_win = app.window(title_re=r"Tick Data Manager.*")
    main_win.set_focus()
    main_win.restore()  # ensure not minimized
    time.sleep(1.5)

    # Type EURUSD into the filter
    print("focusing TxtFilter and typing EURUSD...")
    txt_filter = main_win.child_window(auto_id="TxtFilter", control_type="Edit")
    txt_filter.click_input()
    time.sleep(0.5)
    send_keys("^a{DEL}EURUSD", with_spaces=True, pause=0.05)
    time.sleep(2.0)

    snapshot1 = dump_all_popups(app, "after_filter_eurusd")
    (SCRIPT_DIR / "probe_01_after_filter.txt").write_text(
        "\n".join(render(snapshot1["main_at_moment"])), encoding="utf-8"
    )
    print("wrote probe_01_after_filter.txt")

    # Now find the (only) DataRow and right-click it
    grid = main_win.child_window(auto_id="DataGridSymbol", control_type="DataGrid")
    rows = [c for c in grid.descendants(control_type="DataItem")]
    print(f"DataItem descendants in grid: {len(rows)}")
    for r in rows:
        try:
            ri = r.element_info
            print(f"  row id={ri.automation_id} name={ri.name!r}")
        except Exception:
            pass
    if not rows:
        print("no rows found — cannot right-click", file=sys.stderr)
        return 1
    target_row = rows[0]
    print("right-clicking the first row...")
    target_row.right_click_input()
    time.sleep(1.2)

    snapshot2 = dump_all_popups(app, "after_right_click")
    out_lines = []
    out_lines.append("=== POPUPS AFTER RIGHT-CLICK ===")
    for p in snapshot2["popups"]:
        out_lines.append(f"-- popup: title={p['title']!r} class={p['class']!r}")
        render(p["tree"], 1, out_lines)
        out_lines.append("")
    out_lines.append("=== MAIN WINDOW AFTER RIGHT-CLICK (look for Menu items) ===")
    render(snapshot2["main_at_moment"], 0, out_lines)
    (SCRIPT_DIR / "probe_02_after_right_click.txt").write_text(
        "\n".join(out_lines), encoding="utf-8"
    )
    print("wrote probe_02_after_right_click.txt")

    # Also scan Desktop for any Menu control
    print("scanning Desktop for Menu / ContextMenu controls...")
    found_menus = []
    for w in Desktop(backend="uia").windows():
        try:
            if w.process_id() == app.process:
                # Look for any Menu under this window
                try:
                    for m in w.descendants(control_type="Menu"):
                        found_menus.append({"window": w.window_text(),
                                            "tree": node_dict(m, 0, 5)})
                except Exception:
                    pass
        except Exception:
            pass
    if found_menus:
        lines = []
        for m in found_menus:
            lines.append(f"-- menu under window {m['window']!r}")
            render(m["tree"], 1, lines)
        (SCRIPT_DIR / "probe_03_menus.txt").write_text("\n".join(lines), encoding="utf-8")
        print(f"wrote probe_03_menus.txt ({len(found_menus)} menus)")
    else:
        print("no Menu controls found anywhere in the process")

    # Press Escape to close menu
    send_keys("{ESC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
