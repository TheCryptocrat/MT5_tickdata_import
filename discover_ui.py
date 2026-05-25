"""Launch Tick Data Manager and dump its WPF control tree to disk.

This is a one-shot discovery tool. Run once to produce ui_tree.txt + ui_tree.json
which the production export script will reference for selectors.

The dump records: control_type, name, automation_id, class_name, rectangle,
plus the tree of children up to a configurable depth. WPF/UI Automation does
not always populate AutomationId, so we record everything visible.

Run:
    python discover_ui.py             # default: 30s settle, depth 8
    python discover_ui.py --depth 6   # shallower
    python discover_ui.py --attach    # attach to an already-open TDM instead of launching
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from pywinauto import Application
from pywinauto.controls.uiawrapper import UIAWrapper

TDM_EXE = r"D:\TickData\Tick Data Manager.exe"
SCRIPT_DIR = Path(__file__).resolve().parent
TXT_PATH = SCRIPT_DIR / "ui_tree.txt"
JSON_PATH = SCRIPT_DIR / "ui_tree.json"


def node_dict(elem: UIAWrapper, depth: int, max_depth: int) -> dict:
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
        "is_enabled": info.enabled,
        "is_visible": info.visible,
        "children": [],
    }
    if depth >= max_depth:
        return d
    try:
        children = elem.children()
    except Exception as exc:
        d["children_error"] = repr(exc)
        return d
    for child in children:
        try:
            d["children"].append(node_dict(child, depth + 1, max_depth))
        except Exception as exc:
            d["children"].append({"error": repr(exc)})
    return d


def render_tree(node: dict, indent: int = 0, lines: list[str] | None = None) -> list[str]:
    if lines is None:
        lines = []
    pad = "  " * indent
    name = (node.get("name") or "")[:60]
    aid = node.get("automation_id") or ""
    cls = node.get("class_name") or ""
    ct = node.get("control_type") or "?"
    rect = node.get("rectangle")
    rect_s = f"@{rect}" if rect else ""
    lines.append(f"{pad}[{ct}] name={name!r:<32}  id={aid!r:<24}  cls={cls!r:<22} {rect_s}")
    for child in node.get("children", []):
        if "error" in child:
            lines.append(f"{pad}  <error: {child['error']}>")
        else:
            render_tree(child, indent + 1, lines)
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--depth", type=int, default=8)
    ap.add_argument("--settle", type=float, default=15.0,
                    help="seconds to wait after launch before dumping")
    ap.add_argument("--attach", action="store_true",
                    help="attach to a running TDM instead of launching")
    args = ap.parse_args()

    if args.attach:
        print("attaching to running Tick Data Manager...")
        app = Application(backend="uia").connect(title_re=r"Tick Data Manager.*", timeout=30)
    else:
        print(f"launching: {TDM_EXE}")
        app = Application(backend="uia").start(f'"{TDM_EXE}"')
        print(f"waiting {args.settle}s for main window...")
        time.sleep(args.settle)

    windows = app.windows()
    print(f"found {len(windows)} top-level windows")
    for i, w in enumerate(windows):
        try:
            print(f"  [{i}] title={w.window_text()!r} class={w.class_name()!r}")
        except Exception as exc:
            print(f"  [{i}] <error: {exc}>")

    main_win = None
    for w in windows:
        try:
            if "Tick Data Manager" in (w.window_text() or ""):
                main_win = w
                break
        except Exception:
            continue
    if main_win is None:
        print("ERROR: could not find Tick Data Manager main window", file=sys.stderr)
        return 1

    print(f"dumping tree from main window with depth={args.depth}...")
    tree = node_dict(main_win, 0, args.depth)
    JSON_PATH.write_text(json.dumps(tree, indent=2, default=str), encoding="utf-8")
    TXT_PATH.write_text("\n".join(render_tree(tree)), encoding="utf-8")
    print(f"wrote {JSON_PATH}")
    print(f"wrote {TXT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
