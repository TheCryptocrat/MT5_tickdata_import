"""Sanity check: read EURCAD_TDS ticks from MT5 and confirm they're
EURCAD values (1.3-1.8 range), NOT AUDCAD values (0.6-1.1)."""

from __future__ import annotations
import sys
from datetime import datetime
import MetaTrader5 as mt5

TERMINAL = r"C:\Users\me\Documents\MetaTrader Instances\terminal64.exe"

if not mt5.initialize(path=TERMINAL):
    print("mt5.initialize failed:", mt5.last_error())
    sys.exit(1)

print(f"connected to MT5 build {mt5.terminal_info().build}")

for sym in ("EURCAD_TDS", "AUDCAD_TDS", "GBPCHF_TDS", "EURCHF_TDS"):
    info = mt5.symbol_info(sym)
    if info is None:
        print(f"{sym}: NOT FOUND in MT5")
        continue
    print(f"\n=== {sym} ===")
    print(f"  digits={info.digits}  point={info.point}  bid={info.bid}  ask={info.ask}")
    # Get a few historic ticks from early in the data range
    ticks = mt5.copy_ticks_from(sym, datetime(2024, 1, 5), 5, mt5.COPY_TICKS_ALL)
    if ticks is None or len(ticks) == 0:
        print(f"  no ticks around 2024-01-05; trying 2020-01-02...")
        ticks = mt5.copy_ticks_from(sym, datetime(2020, 1, 2), 5, mt5.COPY_TICKS_ALL)
    if ticks is None or len(ticks) == 0:
        print(f"  no ticks at all in MT5")
        continue
    print(f"  first 5 ticks (after seek):")
    for t in ticks[:5]:
        ts = datetime.utcfromtimestamp(t['time_msc']/1000)
        print(f"    {ts}  bid={t['bid']:.5f}  ask={t['ask']:.5f}")

mt5.shutdown()
