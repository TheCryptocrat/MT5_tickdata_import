"""Verify GBPUSD_TDS state — does the symbol exist, have data, and is it
visible to the strategy tester?"""

import sys
from datetime import datetime
import MetaTrader5 as mt5

TERMINAL = r"C:\Users\me\Documents\MetaTrader Instances\terminal64.exe"
if not mt5.initialize(path=TERMINAL):
    print("init failed:", mt5.last_error()); sys.exit(1)

print(f"MT5 build {mt5.terminal_info().build}")

for sym in ("GBPUSD_TDS", "XAUUSD_TDS", "EURCAD_TDS", "GBPCHF_TDS",
            "NZDCAD_TDS", "SGDJPY_TDS",
            "GBPUSD-TDS", "AUDCAD_TDS"):
    info = mt5.symbol_info(sym)
    if info is None:
        print(f"\n{sym}: symbol_info=None — DOES NOT EXIST in this terminal")
        continue
    print(f"\n=== {sym} ===")
    print(f"  visible      = {info.visible}")
    print(f"  custom       = {info.custom}")
    print(f"  digits       = {info.digits}  point = {info.point}")
    print(f"  bid          = {info.bid}  ask = {info.ask}")
    print(f"  trade_mode   = {info.trade_mode}")
    print(f"  expiration   = {info.expiration_mode}")
    print(f"  contract_size= {info.trade_contract_size}")
    print(f"  margin       = {info.margin_initial}")
    print(f"  path         = {info.path}")
    print(f"  description  = {info.description}")
    # Tick count check
    ticks = mt5.copy_ticks_from(sym, datetime(2024, 1, 5), 3, mt5.COPY_TICKS_ALL)
    if ticks is None or len(ticks) == 0:
        print(f"  TICK CHECK   = no ticks at 2024-01-05")
    else:
        print(f"  TICK CHECK   = {len(ticks)} ticks; first bid={ticks[0]['bid']}")

mt5.shutdown()
