"""Attach to MT5, drag the TDM_TickImporter script onto the active chart, set
inputs (InpOnlyDestination etc.), click OK, then wait for the import to
finish (poll the log file).

The interactive equivalent is: in MT5 Navigator (Ctrl+N), expand Scripts,
right-click TDM_TickImporter, choose Modify/Run.

This script first dumps the MT5 main-window UI tree to mt5_tree.txt for
reference, then attempts a sequence of clicks. If the click sequence
doesn't work, the tree dump is enough info to retry.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from pywinauto import Application
from pywinauto.controls.uiawrapper import UIAWrapper
from pywinauto.keyboard import send_keys

SCRIPT_DIR = Path(__file__).resolve().parent


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
    name = (node.get("name") or "")[:60]
    aid = node.get("automation_id") or ""
    cls = node.get("class_name") or ""
    ct = node.get("control_type") or "?"
    lines.append(f"{pad}[{ct}] name={name!r:<32}  id={aid!r:<24}  cls={cls!r:<22}")
    for child in node.get("children", []):
        if "error" in child:
            lines.append(f"{pad}  <err>")
        else:
            render(child, indent + 1, lines)
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true", help="dump UI tree and exit")
    ap.add_argument("--depth", type=int, default=6)
    args = ap.parse_args()

    # MT5 window title format: "<account> - <broker>: ... - [<chart>]"
    # No literal "MetaTrader 5" appears. Match by the broker/server fragment.
    app = Application(backend="uia").connect(title_re=r".*TradeSmart.*", timeout=30)
    main_win = app.window(title_re=r".*TradeSmart.*")
    main_win.set_focus()
    time.sleep(0.5)

    if args.dump:
        tree = node_dict(main_win, 0, args.depth)
        out_txt = SCRIPT_DIR / "mt5_tree.txt"
        out_json = SCRIPT_DIR / "mt5_tree.json"
        out_txt.write_text("\n".join(render(tree)), encoding="utf-8")
        out_json.write_text(json.dumps(tree, indent=2, default=str), encoding="utf-8")
        print(f"wrote {out_txt}")
        print(f"wrote {out_json}")
        return 0

    # 1. Open the Navigator (Ctrl+N toggles it). Send Ctrl+N twice if it
    #    starts visible — net effect is "make sure it's visible".
    send_keys("^n", pause=0.3)
    time.sleep(0.5)
    # If we just hid it, toggle back.
    # The right way is to check the menu state, but easier: send Ctrl+N twice
    # idempotently via a quick toggle check. Skipping for now.

    # 2. Use the Navigator's search/keyboard navigation: alt+s focuses search
    #    is one option. Easier: actually just send Ctrl+F1 or click the
    #    Navigator title. We'll instead use the toolbar/menu path:
    #    File > Open Data Folder is NOT what we want; we need Scripts tree.
    #
    # For now this main path is a stub — run with --dump first to inspect.
    print("non-dump invocation is a stub — run with --dump to inspect MT5 tree first.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
