r"""Scan D:\TickData and emit manifest.json — the work list of CSVs to refresh.

Classification rules (defaults, override via --include-extra):
  KEEP   : canonical pure-tick export  <SYMBOL>_GMT+2_US-DST.csv  (or <SYMBOL>_GMT+2.csv)
  SKIP   : 0-byte files
  SKIP   : files under \\OHLC_Broker_Data\\, \\1HR For Training Data\\,
           \\1M OHLC\\, \\1YR USDJPY\\, \\New folder*, \\parquet\\, \\Stocks\\
  SKIP   : filenames ending  _M1*  _H1*  _M15*  _M5*   (these are bars)
  SKIP   : filenames containing "-5YR", "-3YR", "20YY-20YY" date ranges
  SKIP   : "_TDS" variants alongside the canonical export
  FLAG   : filename's symbol prefix does not match its parent folder name
           (e.g. \\NZDJPY\\GBPJPY_GMT+2_US-DST.csv) — likely misfile, do NOT auto-process

Run:  python inventory.py            # writes manifest.json next to the script
      python inventory.py --print    # also prints the classification table
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(r"D:\TickData")
SCRIPT_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = SCRIPT_DIR / "manifest.json"

EXCLUDED_DIR_FRAGMENTS = (
    "\\OHLC_Broker_Data\\",
    "\\1HR For Training Data\\",
    "\\1M OHLC\\",
    "\\1YR USDJPY\\",
    "\\parquet\\",
    "\\Stocks\\",
)
EXCLUDED_PARENT_PREFIXES = ("New folder",)

BAR_SUFFIX_RE = re.compile(r"_(?:M1|M5|M15|M30|H1|H4|D1|W1|MN)(?:[-_].*)?\.csv$", re.IGNORECASE)
DATERANGE_RE = re.compile(r"(?:[-_])(?:\d{4}-\d{4}|\d+YR)\.csv$", re.IGNORECASE)
TDS_VARIANT_RE = re.compile(r"_TDS\.csv$", re.IGNORECASE)

# Canonical export name pattern. Captures the symbol prefix (what TDM displays).
# Accepts SYMBOL_GMT+2_US-DST.csv   and   SYMBOL_GMT+2.csv   variants.
CANONICAL_RE = re.compile(r"^(?P<symbol>[A-Za-z0-9_]+?)_GMT\+2(?:_US-DST)?\.csv$", re.IGNORECASE)

# Hand-curated filename->TDM-symbol overrides for non-trivial cases
# (TDM may name an asset differently than the destination filename suggests).
SYMBOL_OVERRIDES: dict[str, str] = {
    "Ether_vs_US_Dollar": "ETHUSD",
    "Bitcoin_vs_US_Dollar": "BTCUSD",
    "US_Small_Cap_2000": "US_Small_Cap_2000",
    "USA_30_Index": "USA_30_Index",
    "USA_500_Index": "USA_500_Index",
    "USA_100_Technical_Index": "USA_100_Technical_Index",
}


def is_excluded_path(p: Path) -> bool:
    s = str(p)
    if any(frag in s for frag in EXCLUDED_DIR_FRAGMENTS):
        return True
    parent = p.parent.name
    if any(parent.startswith(pre) for pre in EXCLUDED_PARENT_PREFIXES):
        return True
    return False


def classify(p: Path) -> dict:
    rec: dict = {
        "path": str(p),
        "parent_folder": p.parent.name,
        "filename": p.name,
        "size_bytes": p.stat().st_size,
        "modified": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "status": None,
        "reason": None,
        "symbol": None,
    }

    if rec["size_bytes"] == 0:
        rec["status"] = "skip"
        rec["reason"] = "empty file"
        return rec

    if is_excluded_path(p):
        rec["status"] = "skip"
        rec["reason"] = "excluded directory"
        return rec

    fn = p.name
    if BAR_SUFFIX_RE.search(fn):
        rec["status"] = "skip"
        rec["reason"] = "bar export (not ticks)"
        return rec
    if DATERANGE_RE.search(fn):
        rec["status"] = "skip"
        rec["reason"] = "date-ranged subset (manual)"
        return rec
    if TDS_VARIANT_RE.search(fn) or "_TDS." in fn or "_DS_TDS" in fn:
        rec["status"] = "skip"
        rec["reason"] = "_TDS variant (legacy alongside canonical)"
        return rec

    m = CANONICAL_RE.match(fn)
    if not m:
        rec["status"] = "skip"
        rec["reason"] = "filename does not match canonical <SYMBOL>_GMT+2[_US-DST].csv pattern"
        return rec

    raw_symbol = m.group("symbol")
    tdm_symbol = SYMBOL_OVERRIDES.get(raw_symbol, raw_symbol)
    rec["symbol"] = tdm_symbol
    rec["filename_symbol"] = raw_symbol

    parent = p.parent.name
    # If the parent folder name contains a different symbol prefix, flag as misfiled.
    if parent and parent.lower() != "tickdata":
        parent_prefix = re.split(r"[_\-]", parent)[0]
        if (
            parent_prefix
            and parent_prefix.upper() not in raw_symbol.upper()
            and raw_symbol.upper() not in parent_prefix.upper()
            and parent_prefix.upper() not in {"NEW", "OHLC", "1HR", "1M", "1YR", "STOCKS", "PARQUET"}
        ):
            rec["status"] = "flag_misfiled"
            rec["reason"] = (
                f"filename symbol '{raw_symbol}' does not match parent folder '{parent}'"
            )
            return rec

    rec["status"] = "keep"
    rec["reason"] = "canonical tick export"
    return rec


def build_manifest() -> dict:
    files = []
    for p in ROOT.rglob("*.csv"):
        if not p.is_file():
            continue
        try:
            files.append(classify(p))
        except OSError as exc:
            files.append(
                {"path": str(p), "status": "skip", "reason": f"stat failed: {exc}"}
            )

    keep = [r for r in files if r["status"] == "keep"]
    flag = [r for r in files if r["status"] == "flag_misfiled"]
    skip = [r for r in files if r["status"] == "skip"]

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "root": str(ROOT),
        "totals": {"keep": len(keep), "flag": len(flag), "skip": len(skip)},
        "keep": sorted(keep, key=lambda r: r["path"]),
        "flag_misfiled": sorted(flag, key=lambda r: r["path"]),
        "skip": sorted(skip, key=lambda r: r["path"]),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", action="store_true", help="print the classification table")
    args = ap.parse_args()

    if not ROOT.exists():
        print(f"ERROR: {ROOT} does not exist", file=sys.stderr)
        return 2

    manifest = build_manifest()
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    t = manifest["totals"]
    print(
        f"manifest written: {MANIFEST_PATH}\n"
        f"  keep={t['keep']}  flag_misfiled={t['flag']}  skip={t['skip']}"
    )

    if args.print:
        print("\n=== KEEP (will be updated) ===")
        for r in manifest["keep"]:
            print(
                f"  {r['symbol']:<28}  {r['modified']}  "
                f"{r['size_bytes']/1024/1024/1024:6.2f} GB  {r['path']}"
            )
        if manifest["flag_misfiled"]:
            print("\n=== FLAG_MISFILED (review manually) ===")
            for r in manifest["flag_misfiled"]:
                print(f"  {r['reason']:<70}  {r['path']}")
        print(f"\n=== SKIP ({t['skip']} files) ===  (use --verbose to list)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
