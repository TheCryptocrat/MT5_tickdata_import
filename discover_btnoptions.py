"""Click BtnOptions (hamburger) AND the toolbar mystery buttons, screenshot each."""

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


def dump_popups(app):
    out = []
    main_pid = app.process
    for w in Desktop(backend="uia").windows():
        try:
            if w.process_id() == main_pid and w.window_text() != "Tick Data Manager":
                out.append({"title": w.window_text(), "class": w.class_name(),
                            "tree": node_dict(w, 0, 8)})
        except Exception:
            continue
    return out


def click_and_probe(app, main_win, button_elem, label, screenshot_box):
    print(f"\n=== {label} ===")
    print(f"clicking button at {button_elem.rectangle()}...")
    button_elem.click_input()
    time.sleep(1.2)

    # Screenshot immediately (don't lose menu focus)
    img = ImageGrab.grab(bbox=screenshot_box)
    img.save(SCRIPT_DIR / f"shot_{label}.png")

    popups = dump_popups(app)
    lines = [f"=== {label} ==="]
    if popups:
        for p in popups:
            lines.append(f"-- popup: title={p['title']!r} class={p['class']!r}")
            render(p["tree"], 1, lines)
    else:
        lines.append("(no popups detected)")

    # Also re-dump main window in case menu materialized inside it
    main_tree = node_dict(main_win, 0, 7)
    lines.append("\n--- main window tree ---")
    render(main_tree, 0, lines)

    (SCRIPT_DIR / f"probe_{label}.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote shot_{label}.png and probe_{label}.txt; popups={len(popups)}")

    # Close menu / dialog
    send_keys("{ESC}")
    time.sleep(0.5)
    send_keys("{ESC}")
    time.sleep(0.5)


def main():
    app = Application(backend="uia").connect(title_re=r"Tick Data Manager.*", timeout=15)
    main_win = app.window(title_re=r"Tick Data Manager.*")
    main_win.set_focus()
    main_win.restore()
    time.sleep(1.5)

    # Clear filter
    txt = main_win.child_window(auto_id="TxtFilter", control_type="Edit")
    txt.click_input()
    send_keys("^a{DEL}", pause=0.05)
    time.sleep(1.0)

    rect = main_win.rectangle()
    screenshot_box = (rect.left, rect.top, rect.right, rect.bottom)

    # Identify the three top-right toolbar buttons:
    # btn @ (1633, 385) — first unnamed
    # btn @ (1659, 385) — second unnamed
    # BtnOptions @ (1683, 385)
    top_buttons = []
    for b in main_win.descendants(control_type="Button"):
        try:
            r = b.rectangle()
            if r.top in (385,) and r.right > 1600 and (r.right - r.left) < 30:
                top_buttons.append((b, r))
        except Exception:
            pass
    print(f"top-right toolbar buttons matched: {len(top_buttons)}")
    for b, r in top_buttons:
        print(f"  {b.element_info.automation_id!r} @{(r.left, r.top, r.right, r.bottom)} name={b.element_info.name!r}")

    # Find each by automation_id / position
    btn_options = None
    btn1 = None
    btn2 = None
    for b, r in top_buttons:
        aid = b.element_info.automation_id
        if aid == "BtnOptions":
            btn_options = b
        elif 1625 <= r.left <= 1640:
            btn1 = b
        elif 1655 <= r.left <= 1670:
            btn2 = b

    if btn_options:
        click_and_probe(app, main_win, btn_options, "btnoptions", screenshot_box)

    if btn1:
        click_and_probe(app, main_win, btn1, "toolbar_mid1_search", screenshot_box)

    if btn2:
        click_and_probe(app, main_win, btn2, "toolbar_mid2_download", screenshot_box)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
