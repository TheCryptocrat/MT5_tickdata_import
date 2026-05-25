"""Generate mapping.csv used by TDM_TickImporter.mq5.

The MQL5 EA reads `<MT5 Common>/Files/TDM_Updater/mapping.csv` to know which
destination MT5 symbols to write each source CSV into.

Columns (no header):
    dest_symbol , template_or_empty , csv_relative_path

Where:
- dest_symbol: e.g. "AUDCAD_TDS" or "EURUSD-TDS"
- template_or_empty: if dest_symbol does not exist in MT5 yet, the EA calls
  CustomSymbolCreate(dest_symbol, "Custom\\TDS", template). Empty = symbol
  already exists, no creation needed.
- csv_relative_path: path under MT5 Common\\Files\\, which thanks to the
  TDS_csvs junction resolves to D:\\TickData\\... (e.g.
  "TDS_csvs\\AUDCAD_GMT+2_US-DST.csv").

Run:
    python build_mapping.py
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

# Source CSV paths (relative to D:\TickData, which is also the
# TDS_csvs junction in MT5 Common\Files\).
SOURCES = {
    "AUDCAD": "AUDCAD_GMT+2_US-DST.csv",
    "AUDJPY": "AUDJPY/AUDJPY_GMT+2_US-DST.csv",
    "AUDNZD": "AUDNZD/AUDNZD_GMT+2_US-DST.csv",
    # AUDUSD intentionally omitted — TDM-stuck, file missing (see README known issues).
    "BTCUSD": "BTCUSD_GMT+2/BTCUSD_GMT+2_US-DST.csv",
    "CADJPY": "CADJPY/CADJPY_GMT+2_US-DST.csv",
    "CHFJPY": "CHFJPY/CHFJPY_GMT+2_US-DST.csv",
    "ETHUSD": "ETHUSD_GMT+2/Ether_vs_US_Dollar_GMT+2_US-DST.csv",
    "EURAUD": "EURAUD/EURAUD_GMT+2_US-DST.csv",
    "EURCAD": "EURCAD/EURCAD_GMT+2_US-DST.csv",
    "EURCHF": "EURCHF_GMT+2_US-DST.csv",
    "EURGBP": "EURGBP/EURGBP_GMT+2_US-DST.csv",
    "EURJPY": "EURJPY/EURJPY_GMT+2_US-DST.csv",
    "EURUSD": "EURUSD_GMT+2/EURUSD_GMT+2_US-DST.csv",
    "GBPAUD": "GBPAUD/GBPAUD_GMT+2_US-DST.csv",
    "GBPCAD": "GBPCAD/GBPCAD_GMT+2_US-DST.csv",
    "GBPCHF": "GBPCHF/GBPCHF_GMT+2_US-DST.csv",
    "GBPJPY": "GBPJPY_GMT+2/GBPJPY_GMT+2_US-DST.csv",
    "GBPNZD": "GBPNZD/GBPNZD_GMT+2_US-DST.csv",
    "GBPUSD": "GBPUSD_GMT+2/GBPUSD_GMT+2_US-DST.csv",
    "NZDCAD": "NZDCAD_GMT+2_US-DST.csv",
    "NZDJPY": "NZDJPY/NZDJPY_GMT+2_US-DST.csv",
    "NZDUSD": "NZDUSD/NZDUSD_GMT+2_US-DST.csv",
    "SGDJPY": "SGDJPY/SGDJPY_GMT+2_US-DST.csv",
    "USDCAD": "USDCAD/USDCAD_GMT+2_US-DST.csv",
    "USDCHF": "USDCHF/USDCHF_GMT+2_US-DST.csv",
    "USDJPY": "USDJPY/USDJPY_GMT+2_US-DST.csv",
    "XAGUSD": "XAGUSD_GMT+2/XAGUSD_GMT+2_US-DST.csv",
    "XAUUSD": "XAUUSD_GMT+2-DST/XAUUSD_GMT+2_US-DST.csv",
}

# Destinations per source. Most go to one `<SYMBOL>_TDS`; the 6 pairs where
# `-TDS` legacy backtest configs exist get dual-written.
# Format: src_symbol → list of (dest_symbol, template_or_empty)
DESTINATIONS: dict[str, list[tuple[str, str]]] = {
    "AUDCAD": [("AUDCAD_TDS", "")],
    "AUDJPY": [("AUDJPY_TDS", "")],
    "AUDNZD": [("AUDNZD_TDS", "")],
    "BTCUSD": [("BTCUSD_TDS", "")],
    "CADJPY": [("CADJPY_TDS", "")],
    "CHFJPY": [("CHFJPY_TDS", "")],
    "ETHUSD": [("ETHUSD_TDS", "")],
    "EURAUD": [("EURAUD_TDS", "")],
    "EURCAD": [("EURCAD_TDS", "AUDCAD_TDS")],   # NEW — clone like-asset FX cross
    "EURCHF": [("EURCHF_TDS", "")],
    "EURGBP": [("EURGBP_TDS", "")],
    "EURJPY": [("EURJPY_TDS", "")],
    "EURUSD": [("EURUSD_TDS", ""), ("EURUSD-TDS", "")],     # DUAL — both exist
    "GBPAUD": [("GBPAUD_TDS", "")],
    "GBPCAD": [("GBPCAD_TDS", "")],
    "GBPCHF": [("GBPCHF_TDS", "EURCHF_TDS")],  # NEW — clone like-asset CHF cross
    "GBPJPY": [("GBPJPY_TDS", "")],
    "GBPNZD": [("GBPNZD_TDS", "")],
    "GBPUSD": [
        ("GBPUSD_TDS", "GBPUSD-TDS"),  # NEW — clone from existing -TDS
        ("GBPUSD-TDS", ""),            # also update the legacy variant
    ],
    "NZDCAD": [("NZDCAD_TDS", "AUDCAD_TDS")],  # NEW — clone like-asset CAD cross
    "NZDJPY": [("NZDJPY_TDS", "")],
    "NZDUSD": [("NZDUSD_TDS", "")],
    "SGDJPY": [("SGDJPY_TDS", "CADJPY_TDS")],  # NEW — clone like-asset JPY cross
    "USDCAD": [("USDCAD_TDS", ""), ("USDCAD-TDS", "")],     # DUAL
    "USDCHF": [("USDCHF_TDS", ""), ("USDCHF-TDS", "")],     # DUAL
    "USDJPY": [("USDJPY_TDS", ""), ("USDJPY-TDS", "")],     # DUAL
    "XAGUSD": [("XAGUSD_TDS", "")],
    "XAUUSD": [
        ("XAUUSD_TDS", "XAUUSD-TDS"),  # NEW — clone from existing -TDS
        ("XAUUSD-TDS", ""),            # also update the legacy variant
    ],
}

MT5_COMMON = Path(os.environ["APPDATA"]) / "MetaQuotes" / "Terminal" / "Common" / "Files"
OUT_DIR = MT5_COMMON / "TDM_Updater"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / "mapping.csv"


def main() -> int:
    rows: list[tuple[str, str, str]] = []
    sanity = []
    for sym, csv_rel in SOURCES.items():
        dests = DESTINATIONS.get(sym)
        if dests is None:
            print(f"WARN: no destinations for {sym!r}, skipping")
            continue
        # MQL5 FileOpen uses backslashes; convert.
        csv_path_mq5 = f"TDS_csvs\\{csv_rel.replace('/', chr(92))}"
        for dest, template in dests:
            rows.append((dest, template, csv_path_mq5))
        sanity.append((sym, len(dests)))

    # Sanity check that the source files actually exist
    print(f"{'src':<10} {'dests':<6} {'exists':<8} csv_path")
    print("-" * 90)
    for sym, csv_rel in SOURCES.items():
        full = Path(r"D:\TickData") / csv_rel.replace("/", os.sep)
        exists = full.exists()
        marker = "OK" if exists else "MISSING"
        print(f"{sym:<10} {len(DESTINATIONS.get(sym, [])):<6} {marker:<8} {full}")

    # Write the mapping CSV (no header, MQL5-friendly).
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for row in rows:
            w.writerow(row)
    print(f"\nwrote {OUT_PATH}")
    print(f"  {len(rows)} destination rows from {len(SOURCES)} source CSVs")
    n_create = sum(1 for _, t, _ in rows if t)
    n_dual = sum(1 for s, d in DESTINATIONS.items() if len(d) > 1)
    print(f"  {n_create} destinations need CustomSymbolCreate (new _TDS)")
    print(f"  {n_dual} sources dual-write to both _TDS and -TDS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
