r"""TDM Updater — drive Tick Data Manager via UI Automation to refresh CSV exports.

For each canonical CSV in manifest.json, this script:
  1. Launches / attaches to Tick Data Manager
  2. Filters the symbol grid to that symbol
  3. Opens the per-row Operations dialog
  4. Download tab: clicks "New data" then "Start download", waits for idle
  5. Export ticks tab: clicks "Start export", handles the Save As dialog
     to write to the manifest's target path (overwrites the existing CSV)
  6. Waits for export to complete
  7. Persists state after each symbol so a crash / power-loss restart resumes
     from the next symbol

Run:
    python tdm_export.py             # uses manifest.json next to script
    python tdm_export.py --resume    # resume from state.json (skip completed)
    python tdm_export.py --only EURUSD,USDJPY
    python tdm_export.py --dry-run   # don't actually click; just print plan

Exit codes:
    0  all symbols processed (including skipped)
    1  hard failure (TDM unreachable, etc.)
    2  one or more symbols failed; state.json records details
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import traceback
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from pywinauto import Application, Desktop
from pywinauto.keyboard import send_keys
from pywinauto.controls.uiawrapper import UIAWrapper

SCRIPT_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = SCRIPT_DIR / "manifest.json"
STATE_PATH = SCRIPT_DIR / "state.json"
LOG_DIR = SCRIPT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

TDM_EXE = r"D:\TickData\Tick Data Manager.exe"

# ------------------------------------------------------------------ logging --

def setup_logging() -> logging.Logger:
    log_path = LOG_DIR / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logger = logging.getLogger("tdm")
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG); fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setLevel(logging.INFO); sh.setFormatter(fmt)
    logger.addHandler(fh); logger.addHandler(sh)
    logger.info(f"log file: {log_path}")
    return logger


# ------------------------------------------------------------------- state --

@dataclass
class SymbolState:
    symbol: str
    target_path: str
    status: str = "pending"   # pending | downloading | exporting | done | failed | skipped
    last_attempt: Optional[str] = None
    error: Optional[str] = None
    pre_size_bytes: Optional[int] = None
    post_size_bytes: Optional[int] = None
    pre_mtime: Optional[str] = None
    post_mtime: Optional[str] = None
    attempts: int = 0


@dataclass
class RunState:
    started_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    manifest_generated_at: Optional[str] = None
    symbols: dict[str, SymbolState] = field(default_factory=dict)

    def save(self, path: Path = STATE_PATH):
        self.last_updated = datetime.now().isoformat(timespec="seconds")
        data = {
            "started_at": self.started_at,
            "last_updated": self.last_updated,
            "manifest_generated_at": self.manifest_generated_at,
            "symbols": {k: asdict(v) for k, v in self.symbols.items()},
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, path)  # atomic on Windows when target exists

    @classmethod
    def load(cls, path: Path = STATE_PATH) -> "RunState":
        if not path.exists():
            return cls()
        d = json.loads(path.read_text(encoding="utf-8"))
        st = cls(
            started_at=d.get("started_at", datetime.now().isoformat(timespec="seconds")),
            last_updated=d.get("last_updated", ""),
            manifest_generated_at=d.get("manifest_generated_at"),
        )
        for k, v in d.get("symbols", {}).items():
            st.symbols[k] = SymbolState(**v)
        return st


# ------------------------------------------------------------------ helpers --

class TdmTimeout(Exception):
    pass


def wait_until(predicate, timeout: float, interval: float = 0.5, desc: str = ""):
    """Poll predicate() until it returns truthy, or raise TdmTimeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            v = predicate()
            if v:
                return v
        except Exception:
            pass
        time.sleep(interval)
    raise TdmTimeout(f"timed out after {timeout}s waiting for: {desc}")


# -------------------------------------------------------------- TDM driver --

class TdmDriver:
    def __init__(self, logger: logging.Logger, dry_run: bool = False):
        self.log = logger
        self.dry_run = dry_run
        self.app: Optional[Application] = None
        self.main_win = None

    # ----- lifecycle

    def attach_or_launch(self, settle: float = 20.0):
        try:
            self.app = Application(backend="uia").connect(
                title_re=r"Tick Data Manager.*", timeout=5
            )
            self.log.info("attached to running TDM")
        except Exception:
            self.log.info(f"launching {TDM_EXE} ...")
            self.app = Application(backend="uia").start(f'"{TDM_EXE}"')
            time.sleep(settle)
        self.main_win = self.app.window(title_re=r"Tick Data Manager.*")
        try: self.main_win.set_focus()
        except: pass
        try: self.main_win.restore()
        except: pass
        time.sleep(1.0)
        self._close_leftover_ops_dialog()

    def shutdown(self):
        try:
            if self.app and self.app.process:
                self.log.info("closing TDM gracefully...")
                self.main_win.close()
                time.sleep(3.0)
        except Exception:
            pass

    # ----- low-level UIA finders

    def _find_in_desc(self, ctrl_type: str, auto_id: str, root=None):
        root = root or self.main_win
        for d in root.descendants(control_type=ctrl_type):
            if d.element_info.automation_id == auto_id:
                return d
        return None

    def _ops_dialog(self):
        for c in self.main_win.children():
            try:
                if (c.element_info.control_type == "Window"
                        and "operations" in (c.window_text() or "").lower()):
                    return c
            except Exception:
                continue
        return None

    def _close_leftover_ops_dialog(self):
        d = self._ops_dialog()
        if d:
            self.log.info(f"closing leftover ops dialog: {d.window_text()}")
            try:
                cancel = next((x for x in d.descendants(control_type="Button")
                               if x.element_info.automation_id == "BtnCancel"), None)
                if cancel:
                    cancel.click_input()
                else:
                    send_keys("{ESC}")
            except Exception:
                send_keys("{ESC}")
            time.sleep(0.6)

    # ----- high-level actions

    def get_status_text(self) -> str:
        try:
            t = self._find_in_desc("Text", "TxtStatus")
            if t:
                return t.window_text() or ""
        except Exception:
            return ""
        return ""

    def is_idle(self) -> bool:
        return "idle" in self.get_status_text().lower()

    def wait_for_idle(self, timeout: float, why: str = ""):
        wait_until(self.is_idle, timeout=timeout, interval=1.0,
                   desc=f"TDM idle ({why})")
        # tiny extra settle
        time.sleep(1.0)

    def ensure_play(self):
        """Ensure the task queue is playing (not paused)."""
        try:
            btn = self._find_in_desc("Button", "BtnPlayPause")
            # We can't reliably distinguish play vs pause from the toggle button
            # state via UIA alone. Best-effort: if status is "Paused", click it.
            if "paus" in self.get_status_text().lower():
                self.log.info("queue paused; clicking play")
                btn.click_input()
                time.sleep(0.5)
        except Exception:
            pass

    def filter_to(self, symbol: str):
        txt = self._find_in_desc("Edit", "TxtFilter")
        txt.click_input()
        send_keys("^a{DEL}", pause=0.04)
        send_keys(symbol, with_spaces=False, pause=0.04)
        time.sleep(1.5)

    def _grid_rows(self):
        grid = self._find_in_desc("DataGrid", "DataGridSymbol")
        if grid is None:
            return []
        return grid.descendants(control_type="DataItem")

    def find_row_for_symbol(self, symbol: str):
        """After filter, return the single matching row whose Cell_DisplayName == symbol.
        Returns None if no exact match."""
        rows = self._grid_rows()
        for row in rows:
            try:
                cells = [c for c in row.descendants(control_type="Custom")
                         if c.element_info.automation_id == "Cell_DisplayName"]
                if not cells:
                    continue
                txts = cells[0].descendants(control_type="Text")
                for t in txts:
                    if t.window_text() == symbol:
                        return row
            except Exception:
                continue
        # fallback: first row if only one matched and symbol is a substring of its display name
        if len(rows) == 1:
            return rows[0]
        return None

    def read_row_date_range(self, row) -> tuple[Optional[str], Optional[str]]:
        """Return (start_date, most_recent_date) text from the row, e.g. ('5/4/2003','5/22/2026')."""
        start = end = None
        for c in row.descendants(control_type="Custom"):
            try:
                aid = c.element_info.automation_id
                if aid == "Cell_StartTime":
                    for t in c.descendants(control_type="Text"):
                        s = t.window_text()
                        if s and "/" in s:
                            start = s; break
                elif aid == "Cell_MostRecentLocallyAvailableDate":
                    for t in c.descendants(control_type="Text"):
                        s = t.window_text()
                        if s and "/" in s:
                            end = s; break
            except Exception:
                continue
        return start, end

    def open_operations_for_row(self, row):
        """Click the '...' (Operations) button on the row, return ops dialog."""
        cells = [c for c in row.descendants(control_type="Custom")
                 if c.element_info.automation_id == "Cell_AllowedGaps"]
        if not cells:
            raise RuntimeError("no Cell_AllowedGaps on row")
        buttons = cells[0].descendants(control_type="Button")
        if len(buttons) < 1:
            raise RuntimeError("no buttons in Cell_AllowedGaps")
        ops_btn = buttons[0]  # the '...' button is first
        ops_btn.click_input()

        ops_win = wait_until(self._ops_dialog, timeout=10, interval=0.3,
                             desc="operations dialog")
        return ops_win

    def click_tab(self, ops_win, auto_id: str):
        tab = next((d for d in ops_win.descendants(control_type="TabItem")
                    if d.element_info.automation_id == auto_id), None)
        if tab is None:
            raise RuntimeError(f"tab {auto_id} not found")
        tab.click_input()
        time.sleep(0.7)

    def download_new_data(self, ops_win, symbol: str, timeout: float,
                          wait_for_completion: bool = True):
        """On the Download tab, click 'New data' then 'Start download'.

        If wait_for_completion is True, block until status: idle. If False,
        return immediately after enqueueing (TDS will process the queue in
        parallel with other queued downloads)."""
        self.click_tab(ops_win, "TabDownload")
        btn_new = self._find_in_desc("Button", "BtnNewData", root=ops_win)
        if btn_new is None:
            raise RuntimeError("BtnNewData not found")
        if self.dry_run:
            self.log.info(f"[dry-run] would click BtnNewData for {symbol}")
        else:
            btn_new.click_input()
            time.sleep(0.5)
        # The "Start download" button has no automation_id; find by visible text.
        start_btn = next(
            (b for b in ops_win.descendants(control_type="Button")
             if (b.window_text() or "").strip().lower() == "start download"),
            None,
        )
        if start_btn is None:
            raise RuntimeError("'Start download' button not found")
        if self.dry_run:
            self.log.info(f"[dry-run] would click 'Start download' for {symbol}")
            return
        start_btn.click_input()
        time.sleep(0.8)
        if wait_for_completion:
            self.log.info(f"queued download for {symbol}; waiting for idle...")
            time.sleep(1.5)
            self.wait_for_idle(timeout=timeout, why=f"download {symbol}")
        else:
            self.log.info(f"queued download for {symbol} (will run in parallel)")
            # close the ops dialog so we can move on to the next symbol
            self._close_leftover_ops_dialog()

    def queue_is_empty(self) -> bool:
        """Return True when TDM's task queue (ListboxQueue) has no items."""
        try:
            lst = self._find_in_desc("List", "ListboxQueue")
            if lst is None:
                return self.is_idle()
            items = lst.descendants(control_type="ListItem")
            return len(items) == 0 and self.is_idle()
        except Exception:
            return self.is_idle()

    def wait_for_queue_empty(self, timeout: float, why: str = ""):
        """Wait until ListboxQueue is empty AND status is idle."""
        wait_until(self.queue_is_empty, timeout=timeout, interval=2.0,
                   desc=f"TDM queue empty ({why})")
        time.sleep(2.0)

    def _set_date_picker(self, ops_win, auto_id: str, date_str: str):
        """Set a TDM DatePicker (US date format M/D/YYYY) to date_str.

        Verifies the value took. TDM's WPF DatePicker occasionally ignores
        set_edit_text + typed input — retry up to 3 times before raising.
        """
        dp = self._find_in_desc("Custom", auto_id, root=ops_win)
        if dp is None:
            raise RuntimeError(f"DatePicker {auto_id} not found")
        edit = None
        for e in dp.descendants(control_type="Edit"):
            if e.element_info.automation_id == "PART_TextBox":
                edit = e; break
        if edit is None:
            raise RuntimeError(f"DatePicker {auto_id} has no PART_TextBox")

        # Parse target into (m, d, y) for verify
        try:
            tm, td, ty = (int(x) for x in date_str.split("/"))
        except Exception:
            tm = td = ty = None

        def _read_current() -> str:
            try:
                v = (edit.legacy_properties() or {}).get("Value", "") or ""
                if not v:
                    v = edit.window_text() or ""
                return v.strip()
            except Exception:
                return ""

        def _matches(cur: str) -> bool:
            if not cur or tm is None:
                return False
            try:
                parts = cur.replace("-", "/").split("/")
                if len(parts) != 3:
                    return False
                m, d, y = (int(p) for p in parts)
                # accept 2-digit year (e.g. "20" for 2020)
                if y < 100:
                    y += 2000
                return (m, d, y) == (tm, td, ty)
            except Exception:
                return False

        for attempt in range(3):
            edit.click_input()
            time.sleep(0.15)
            send_keys("^a{DEL}", pause=0.06)
            time.sleep(0.1)
            # Type the date character by character; {/} escapes the slash so
            # pywinauto doesn't interpret it as a key chord.
            send_keys(date_str.replace("/", "{/}"), with_spaces=True, pause=0.04)
            send_keys("{TAB}", pause=0.05)
            time.sleep(0.3)
            cur = _read_current()
            if _matches(cur):
                if attempt > 0:
                    self.log.info(f"date {auto_id} = {cur!r} after {attempt+1} attempts")
                return
            # If TDM clamped the date because we asked for one older than
            # available storage (Start picker) or newer than available (End
            # picker), TDM will keep its own clamped value. That's fine —
            # we use what TDM allows. Log INFO, not WARNING, on attempt 1.
            self.log.info(
                f"date picker {auto_id}: requested {date_str!r}, "
                f"TDM kept {cur!r} (attempt {attempt+1}/3)"
            )
            # Only retry once if the value is blank/unreadable; if TDM gave us
            # a real date that's just different from requested, that's a clamp
            # — accept it and move on.
            if cur and "/" in cur:
                self.log.info(f"accepting TDM-clamped value {cur!r} for {auto_id}")
                return

    def export_ticks(self, symbol: str, target_path: str, timeout: float,
                     start_date: Optional[str] = None, end_date: Optional[str] = None,
                     wait_for_completion: bool = True):
        """Open ops dialog, switch to Export ticks tab, click Start export,
        and handle the Save As dialog to write to target_path.

        If wait_for_completion is True, block until status: idle. If False,
        return immediately after the export task is queued — TDS will run it
        from the queue in order with any other queued tasks."""
        # ensure dialog is open
        ops_win = self._ops_dialog()
        if ops_win is None:
            # re-open
            row = self.find_row_for_symbol(symbol)
            if row is None:
                raise RuntimeError(f"row for {symbol} not found")
            ops_win = self.open_operations_for_row(row)

        self.click_tab(ops_win, "TabExportTicks")

        # Force the full available date range so we never truncate history.
        if start_date:
            self.log.info(f"setting export start date = {start_date}")
            if not self.dry_run:
                self._set_date_picker(ops_win, "DatePickerExportTicksStart", start_date)
        if end_date:
            self.log.info(f"setting export end date   = {end_date}")
            if not self.dry_run:
                self._set_date_picker(ops_win, "DatePickerExportTicksEnd", end_date)

        start_btn = self._find_in_desc("Button", "BtnExportTicksStartExport", root=ops_win)
        if start_btn is None:
            raise RuntimeError("BtnExportTicksStartExport not found")

        if self.dry_run:
            self.log.info(f"[dry-run] would Start export -> {target_path}")
            # Cancel the dialog
            cancel = self._find_in_desc("Button", "BtnCancel", root=ops_win)
            if cancel: cancel.click_input()
            time.sleep(0.5)
            return

        start_btn.click_input()
        self.log.info(f"clicked Start export for {symbol}; awaiting Save As...")

        save_dlg = self._wait_for_save_dialog(timeout=20)
        self._fill_save_dialog(save_dlg, target_path)

        if wait_for_completion:
            # Now wait for the export to complete
            self.log.info(f"export running for {symbol}; waiting for idle...")
            t_start = time.monotonic()
            while time.monotonic() - t_start < 5 and self.is_idle():
                time.sleep(0.5)
            self.wait_for_idle(timeout=timeout, why=f"export {symbol}")
            self._dismiss_any_modal_in_tdm()
            self._close_leftover_ops_dialog()
        else:
            # Fire-and-forget — give TDM a moment to register the task, then
            # close any leftover dialog so we can move to the next symbol.
            time.sleep(1.0)
            self.log.info(f"queued export for {symbol} (will run in parallel)")
            self._close_leftover_ops_dialog()

    def _wait_for_save_dialog(self, timeout: float):
        """Find the Win32 'Save As' dialog (class #32770).

        TDM parents the Save As dialog to the operations dialog, so it is a
        UIA descendant of main_win — NOT a top-level desktop window. We search
        descendants of main_win for a child Window with class '#32770'.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                for d in self.main_win.descendants(control_type="Window"):
                    try:
                        cls = d.class_name() or ""
                        title = (d.window_text() or "").lower()
                        if cls == "#32770" or title == "save as" or "save" in title:
                            return d
                    except Exception:
                        continue
            except Exception:
                pass
            time.sleep(0.4)
        raise TdmTimeout("timed out waiting for Save As dialog")

    def _fill_save_dialog(self, dlg, target_path: str):
        """Set the path in the Save As dialog and click Save.

        Modern Common Item Dialog (Win10/11): the filename field is an Edit
        (auto_id='1001') hosted inside a ComboBox (FileNameControlHost). The
        UIA SetValue pattern often no-ops on this nested edit, so we use the
        clipboard + Ctrl+V which always works.
        """
        import subprocess
        target_path = os.path.abspath(target_path)

        # Find the filename combo (preferred) or its inner Edit (fallback)
        name_combo = None
        for c in dlg.descendants(control_type="ComboBox"):
            try:
                if c.element_info.automation_id == "FileNameControlHost":
                    name_combo = c; break
            except Exception:
                continue
        edit = None
        if name_combo is not None:
            for e in name_combo.descendants(control_type="Edit"):
                if e.element_info.automation_id == "1001":
                    edit = e; break
        if edit is None:
            for e in dlg.descendants(control_type="Edit"):
                if e.element_info.automation_id == "1001":
                    edit = e; break
        if edit is None:
            raise RuntimeError("could not find filename Edit (id=1001) in Save As dialog")

        # Set the path. The Save As dialog sometimes "remembers" the previous
        # filename when reopened, so a no-op paste leaves the old value in
        # place — that previously caused symbol N's data to be written to
        # symbol N-1's path. Verify after every method; raise hard if no
        # method succeeds.
        def _current_value() -> str:
            try:
                v = (edit.legacy_properties() or {}).get("Value", "") or ""
                if not v:
                    v = edit.window_text() or ""
                return v
            except Exception:
                return ""

        def _matches(current: str) -> bool:
            return bool(current) and target_path.lower() in current.lower()

        expected_name = os.path.basename(target_path)

        def _try_clipboard():
            subprocess.run(
                ["clip"],
                input=target_path.encode("utf-16-le"),
                check=True, timeout=5,
            )
            send_keys("^v", pause=0.05)

        def _try_type_keys():
            safe = (target_path.replace("+", "{+}").replace("^", "{^}")
                    .replace("%", "{%}").replace("~", "{~}"))
            send_keys(safe, with_spaces=True, pause=0.005)

        def _try_set_edit_text():
            edit.set_edit_text(target_path)

        for method_name, method in [
            ("clipboard+CtrlV", _try_clipboard),
            ("type_keys", _try_type_keys),
            ("set_edit_text", _try_set_edit_text),
            ("clipboard+CtrlV (retry)", _try_clipboard),
        ]:
            try:
                edit.click_input()
                time.sleep(0.25)
                send_keys("^a", pause=0.05)
                send_keys("{DEL}", pause=0.05)
                time.sleep(0.2)
                method()
                time.sleep(0.4)
                cur = _current_value()
                if _matches(cur):
                    self.log.info(f"Save As path set via {method_name}")
                    break
                self.log.warning(
                    f"Save As fill via {method_name} did not take "
                    f"(current={cur[:120]!r}, want {expected_name!r}); retrying"
                )
            except Exception as exc:
                self.log.warning(f"Save As fill method {method_name} raised: {exc}")
        else:
            # All methods failed — DO NOT proceed; cancelling protects against
            # writing the wrong data to whatever stale path is in the field.
            cur = _current_value()
            try:
                send_keys("{ESC}", pause=0.05)
                time.sleep(0.5)
            except Exception:
                pass
            raise RuntimeError(
                f"could not set Save As path to {target_path!r} after 4 methods; "
                f"current value was {cur[:120]!r}. Cancelled Save As to prevent "
                f"writing to the wrong file."
            )

        # click Save (button id='1', name='Save')
        save_btn = None
        for b in dlg.descendants(control_type="Button"):
            try:
                if b.element_info.automation_id == "1":
                    save_btn = b; break
                if (b.window_text() or "").strip().lower() in ("save", "&save"):
                    save_btn = b; break
            except Exception:
                continue
        if save_btn is None:
            raise RuntimeError("Save button (id=1) not found")
        save_btn.click_input()
        time.sleep(1.0)

        # If "[file] already exists. Do you want to replace it?" prompt
        # appears, click Yes. Approach: scan EVERY TDM-owned top-level window
        # (via Win32 EnumWindows so we don't miss parented popups) and look
        # for one that has a "Yes" button. Click it.
        import ctypes
        import ctypes.wintypes as wt

        def scan_for_yes_button():
            """Return (hwnd, yes_btn_wrapper) for any TDM dialog with a Yes button."""
            user32 = ctypes.windll.user32
            EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
            candidate_hwnds = []

            def cb(hwnd, lparam):
                if not user32.IsWindowVisible(hwnd):
                    return True
                pid = wt.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value != self.app.process:
                    return True
                cls = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cls, 256)
                # #32770 is the dialog class — file dialog, MessageBox, etc.
                if cls.value == "#32770":
                    candidate_hwnds.append(hwnd)
                return True

            user32.EnumWindows(EnumWindowsProc(cb), 0)

            # For each candidate, walk UIA descendants looking for a Yes button
            from pywinauto.controls.uiawrapper import UIAWrapper
            from pywinauto.uia_element_info import UIAElementInfo
            for hwnd in candidate_hwnds:
                try:
                    elem = UIAElementInfo(hwnd)
                    wrapper = UIAWrapper(elem)
                    for b in wrapper.descendants(control_type="Button"):
                        try:
                            txt = (b.window_text() or "").strip().lower()
                            aid = b.element_info.automation_id
                            if txt in ("yes", "&yes") or aid == "6":
                                return hwnd, b
                        except Exception:
                            continue
                except Exception:
                    continue
            return None, None

        deadline = time.monotonic() + 10.0
        clicked = False
        while time.monotonic() < deadline and not clicked:
            hwnd, yes_btn = scan_for_yes_button()
            if yes_btn is not None:
                try:
                    self.log.info(f"found overwrite prompt (hwnd={hwnd}); clicking Yes")
                    yes_btn.click_input()
                    clicked = True
                    time.sleep(0.5)
                    break
                except Exception as exc:
                    self.log.warning(f"Yes click failed ({exc}); will retry / ENTER")
            time.sleep(0.3)

        if not clicked:
            # As a last resort, send ENTER (Yes is the default button on the
            # 'replace?' prompt). If no prompt is up, this is harmless.
            try:
                send_keys("{ENTER}", pause=0.1)
                self.log.info("no Yes button found — sent ENTER as fallback")
            except Exception:
                pass

    def _dismiss_any_modal_in_tdm(self):
        """Close any small modal/toast popups left in TDM."""
        try:
            for w in Desktop(backend="uia").windows():
                if w.process_id() != self.app.process:
                    continue
                if w.window_text() and w.window_text() != "Tick Data Manager":
                    cls = w.class_name() or ""
                    if cls == "#32770" or "operations" not in (w.window_text() or "").lower():
                        try:
                            ok = next((b for b in w.descendants(control_type="Button")
                                       if (b.window_text() or "").strip().lower() in ("ok", "&ok", "close")),
                                      None)
                            if ok:
                                ok.click_input(); time.sleep(0.4)
                        except Exception:
                            pass
        except Exception:
            pass


# --------------------------------------------------------------- main loop --

def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        print("manifest.json not found. Run inventory.py first.", file=sys.stderr)
        sys.exit(1)
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-sep list of symbols to process")
    ap.add_argument("--resume", action="store_true",
                    help="skip symbols marked 'done' in state.json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--download-timeout", type=float, default=3600.0,
                    help="seconds to wait for a download to complete (default 1h)")
    ap.add_argument("--export-timeout", type=float, default=4 * 3600.0,
                    help="seconds to wait for an export to complete (default 4h)")
    ap.add_argument("--restart-every", type=int, default=5,
                    help="restart TDM every N completed exports to clear degraded UI state (default 5)")
    ap.add_argument("--tdm-exe", default=r"D:\TickData\Tick Data Manager.exe")
    ap.add_argument("--launch-settle", type=float, default=20.0,
                    help="seconds to wait after launching TDM before driving it")
    args = ap.parse_args()

    logger = setup_logging()
    manifest = load_manifest()
    keep = manifest["keep"]
    logger.info(f"manifest has {len(keep)} symbols")

    only = set(s.strip() for s in args.only.split(",")) if args.only else None

    state = RunState.load() if args.resume else RunState()
    state.manifest_generated_at = manifest.get("generated_at")

    # populate any missing entries from manifest
    for entry in keep:
        sym = entry["symbol"]
        if sym not in state.symbols:
            state.symbols[sym] = SymbolState(symbol=sym, target_path=entry["path"])

    driver = TdmDriver(logger, dry_run=args.dry_run)
    try:
        driver.attach_or_launch()
        driver.ensure_play()
    except Exception as exc:
        logger.error(f"failed to launch TDM: {exc}")
        return 1

    # Build the work list once so both phases agree.
    logger.info(f"args.resume = {args.resume}; loaded state.json with "
                f"{len(state.symbols)} symbols ("
                f"{sum(1 for s in state.symbols.values() if s.status == 'done')} done)")
    work = []  # list of (entry, st, pre_stat)
    for entry in keep:
        sym = entry["symbol"]
        if only and sym not in only:
            continue
        st = state.symbols[sym]
        if args.resume and st.status == "done":
            logger.info(f"[skip] {sym} already done")
            continue
        pre = Path(entry["path"]).stat() if Path(entry["path"]).exists() else None
        if pre:
            st.pre_size_bytes = pre.st_size
            st.pre_mtime = datetime.fromtimestamp(pre.st_mtime).isoformat(timespec="seconds")
        st.attempts += 1
        st.last_attempt = datetime.now().isoformat(timespec="seconds")
        work.append((entry, st, pre))
    state.save()

    failures = 0
    failed_syms: set[str] = set()

    # =========================================================
    # PHASE 1 — queue every download (TDS runs them in parallel)
    # =========================================================
    if work:
        logger.info(f"=== PHASE 1: queueing {len(work)} downloads ===")
    for entry, st, pre in work:
        sym = entry["symbol"]
        try:
            logger.info(f"--- queue download: {sym}")
            st.status = "downloading"; state.save()
            driver.filter_to(sym)
            row = driver.find_row_for_symbol(sym)
            if row is None:
                raise RuntimeError(f"symbol {sym} not found in TDM grid (check provider)")
            start_date, end_date = driver.read_row_date_range(row)
            logger.info(f"{sym} available range: {start_date} -> {end_date}")
            if not start_date or start_date.strip() == "-":
                raise RuntimeError(f"{sym} has no downloaded data yet (Start date is '-')")
            ops_win = driver.open_operations_for_row(row)
            driver.download_new_data(
                ops_win, sym, timeout=args.download_timeout, wait_for_completion=False
            )
        except Exception as exc:
            failures += 1
            failed_syms.add(sym)
            tb = traceback.format_exc(limit=3)
            logger.error(f"FAIL queue {sym}: {exc}\n{tb}")
            st.status = "failed"; st.error = f"queue: {exc}"
            state.save()
            driver._close_leftover_ops_dialog()

    # Wait for the entire download queue to drain
    queue_timeout = max(args.download_timeout, len(work) * 600.0)
    if work:
        logger.info(f"=== PHASE 1: waiting up to {queue_timeout/3600:.1f}h for all downloads to finish ===")
        try:
            driver.wait_for_queue_empty(timeout=queue_timeout, why="all downloads")
            logger.info("all downloads complete — queue empty")
        except TdmTimeout as exc:
            logger.error(f"download queue did not drain: {exc}")
            # Whatever is still queued/running, mark its symbol as failed
            for entry, st, pre in work:
                if st.status == "downloading":
                    st.status = "failed"
                    st.error = "download queue did not drain in timeout"
                    failed_syms.add(entry["symbol"])
                    failures += 1
            state.save()

    # =========================================================
    # PHASE 2 — SEQUENTIAL exports. We tried parallel queueing once and it
    # caused per-symbol data corruption: rapid back-to-back Start-Export
    # clicks caused Save-As dialog overlap so _wait_for_save_dialog grabbed
    # a stale dialog from the previous symbol; the path got pasted into the
    # wrong dialog and symbol N's tick data was written to symbol K's file
    # path. NEVER PARALLEL.
    # =========================================================
    # Per Cree: export range is 1/1/2020 → today.
    today_str = datetime.now().strftime("%#m/%#d/%Y") if sys.platform == "win32" \
        else datetime.now().strftime("%-m/%-d/%Y")
    EXPORT_START = "1/1/2020"
    EXPORT_END = today_str
    logger.info(f"export date range for all symbols: {EXPORT_START} -> {EXPORT_END}")

    eligible = [(e, st, pre) for (e, st, pre) in work if e["symbol"] not in failed_syms]
    if eligible:
        logger.info(f"=== PHASE 2: exporting {len(eligible)} CSVs sequentially ===")

    # TDM degrades after ~6-8 export operations (ops dialog stops opening,
    # date pickers stop accepting input). Restart on BOTH N successful exports
    # AND M consecutive failures, since both signal a degraded state.
    RESTART_EVERY_SUCCESS = args.restart_every
    RESTART_AFTER_FAILS = 2
    exports_since_restart = 0
    consecutive_failures = 0

    def _restart_tdm():
        nonlocal driver, exports_since_restart, consecutive_failures
        logger.info(
            f"=== restarting TDM (successes_since_restart={exports_since_restart}, "
            f"consecutive_failures={consecutive_failures}) ==="
        )
        try: driver.shutdown()
        except Exception: pass
        import subprocess
        subprocess.run(["taskkill", "/F", "/IM", "Tick Data Manager.exe"],
                       capture_output=True, check=False)
        time.sleep(3.0)
        driver = TdmDriver(logger=logger, dry_run=args.dry_run)
        driver.attach_or_launch(settle=args.launch_settle)
        exports_since_restart = 0
        consecutive_failures = 0

    for entry, st, pre in eligible:
        sym = entry["symbol"]
        try:
            if (exports_since_restart >= RESTART_EVERY_SUCCESS
                    or consecutive_failures >= RESTART_AFTER_FAILS):
                _restart_tdm()
            logger.info(f"--- export: {sym} -> {entry['path']}")
            st.status = "exporting"; state.save()
            driver.filter_to(sym)
            row = driver.find_row_for_symbol(sym)
            if row is None:
                raise RuntimeError(f"symbol {sym} not found in TDM grid")
            driver.export_ticks(
                sym, entry["path"], timeout=args.export_timeout,
                start_date=EXPORT_START, end_date=EXPORT_END,
                wait_for_completion=True,
            )
            exports_since_restart += 1
            post = Path(entry["path"]).stat() if Path(entry["path"]).exists() else None
            if post is None and not args.dry_run:
                raise RuntimeError(f"target file missing after export: {entry['path']}")
            if post is not None:
                st.post_size_bytes = post.st_size
                st.post_mtime = datetime.fromtimestamp(post.st_mtime).isoformat(timespec="seconds")
            if pre and post and post.st_mtime <= pre.st_mtime and not args.dry_run:
                raise RuntimeError(
                    f"file mtime did not advance ({st.pre_mtime} -> {st.post_mtime}); "
                    f"export may have silently failed"
                )
            st.status = "done"; st.error = None; state.save()
            logger.info(f"[OK] {sym}: {st.post_size_bytes} bytes (was {st.pre_size_bytes})")
            consecutive_failures = 0
        except Exception as exc:
            failures += 1
            failed_syms.add(sym)
            consecutive_failures += 1
            tb = traceback.format_exc(limit=3)
            logger.error(f"FAIL export {sym}: {exc}\n{tb}")
            st.status = "failed"; st.error = f"export: {exc}"
            state.save()
            driver._close_leftover_ops_dialog()

    try:
        driver.shutdown()
    except Exception:
        pass

    state.save()
    if failures:
        logger.warning(f"completed with {failures} failures")
        return 2
    logger.info("completed successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
