# MT5 Tick Import — Research & Plan

**Status: research only — do not execute until Cree clears the MT5 backtest queue.**

This document explains how the canonical CSVs produced by TDM Updater will be
imported into MT5's existing `*_TDS` / `*-TDS` custom symbols, and what choices
need to be made before writing the importer.

---

## TL;DR

The cleanest automatable path is a single **MQL5 EA** (`TDM_TickImporter.mq5`)
that reads each TDM CSV directly off `D:\TickData` (via a one-time NTFS
junction so the files appear inside MT5's sandboxed `Common\Files\` tree) and
calls `CustomTicksReplace()` for each `<SYMBOL>_TDS` / `<SYMBOL>-TDS` custom
symbol.

Rationale: MT5's Python package can read ticks but **cannot write to custom
symbols** — that capability only exists in MQL5. The only alternative is
clicking through 27 manual GUI imports (Right-click → Symbols → Ticks tab →
Import), which is fragile, undocumented, and not repeatable for the weekly
refresh cycle.

---

## What we have

### Source: TDM Updater output
- 27 valid `<SYMBOL>_GMT+2_US-DST.csv` files under `D:\TickData\…`
- Format: `YYYY.MM.DD HH:MM:SS.fff,bid,ask` — no header, GMT+2 with US DST.
- Sizes range from 1 GB (NZDCAD) to 17 GB (EURUSD).

### Destination: MT5 custom symbols (already created by Cree)

Found in `C:\Users\me\AppData\Roaming\MetaQuotes\Terminal\EACE9A382E6AACB6A53D9C4DFC6909F6\bases\Custom\`:

**Single-variant (only `_TDS`):** AUDCAD_TDS, AUDJPY_TDS, AUDNZD_TDS, AUDUSD_TDS,
BTCUSD_TDS, CADJPY_TDS, CHFJPY_TDS, EURAUD_TDS, EURCHF_TDS, EURGBP_TDS,
EURJPY_TDS, GBPAUD_TDS, GBPCAD_TDS, GBPJPY_TDS, GBPNZD_TDS, NZDJPY_TDS,
NZDUSD_TDS, XAGUSD_TDS.

**Both variants exist (need to choose):** EURUSD_TDS + EURUSD-TDS, GBPUSD-TDS,
USDCAD_TDS + USDCAD-TDS, USDCHF_TDS + USDCHF-TDS, USDJPY_TDS + USDJPY-TDS,
USDSEK_TDS + USDSEK-TDS, XAUUSD-TDS.

**In MT5 but no CSV yet:** ETHUSD_TDS, USDSEK_TDS / USDSEK-TDS, XPDUSD_TDS,
XPTUSD_TDS. (We have an `Ether_vs_US_Dollar_GMT+2_US-DST.csv` flagged
misfiled — it could map to ETHUSD_TDS once cleaned up.)

**Have CSV but no `_TDS` in MT5:** EURCAD, GBPCHF, NZDCAD, SGDJPY. These pairs
need a custom symbol created in MT5 before the importer can target them.

---

## Why MQL5 (not Python)

The `MetaTrader5` PyPI package exposes:
- `copy_ticks_from`, `copy_ticks_range` (READ ticks)
- `copy_rates_from`, `copy_rates_range` (READ bars)
- `symbols_get`, `symbol_info`, `symbol_select`
- Trading APIs (`order_send`, `positions_get`, etc.)

But **NOT** `custom_symbol_create`, `custom_ticks_replace`, `custom_ticks_add`,
or any other write-to-custom-symbol function. Those exist only in MQL5
(`CustomTicksReplace`, `CustomTicksAdd`, `CustomSymbolCreate`, etc.).

So the importer has to be MQL5 code running inside MT5.

---

## MQL5 file-access constraint

`FileOpen()` in MQL5 is **sandboxed** to two locations:

1. **Terminal data dir/Files**: `<MT5 portable>\MQL5\Files\` — accessed
   without `FILE_COMMON` flag, just `FileOpen("foo.csv", FILE_READ|...)`.
2. **MT5 Common Files**: `C:\Users\me\AppData\Roaming\MetaQuotes\Terminal\Common\Files\` —
   accessed by adding the `FILE_COMMON` flag.

Absolute paths like `D:\TickData\…` are **rejected** by `FileOpen`.

Options to bridge that:
- **(a) Copy each CSV** (5–17 GB each) into `Common\Files\` before processing.
  Total ~135 GB. Slow, wasteful, may run out of C: disk space.
- **(b) NTFS directory junction** (recommended): `mklink /J Common\Files\TDS_csvs D:\TickData`
  exposes `D:\TickData` as if it lived under `Common\Files\TDS_csvs\`.
  Directory junctions cross volumes (unlike hardlinks). Zero copy, zero
  disk overhead.
- **(c) Per-file symlinks**: `mklink Common\Files\AUDCAD.csv "D:\TickData\AUDCAD_GMT+2_US-DST.csv"`.
  Works for individual files. More setup per symbol than (b).

**Recommendation: (b).** One `mklink /J` at setup time, then the MQL5 script
reads `TDS_csvs\AUDCAD\AUDCAD_GMT+2_US-DST.csv` with `FILE_COMMON|FILE_READ`.

---

## Proposed implementation

### Phase A: one-time setup (manual, ~30 sec)

```cmd
mklink /J "C:\Users\me\AppData\Roaming\MetaQuotes\Terminal\Common\Files\TDS_csvs" "D:\TickData"
```

(Idempotent — if the junction already exists, the command errors and we
verify with `dir`.)

### Phase B: MQL5 EA `TDM_TickImporter.mq5`

Inputs (configurable in the EA's input panel):
- `string MapCsv` — path to a small mapping CSV that lists `(mt5_symbol,
  csv_relative_path)` pairs. Lives in `Common\Files\TDM_Updater\mapping.csv`.
  Example rows:
    ```
    AUDCAD_TDS,TDS_csvs\AUDCAD_GMT+2_US-DST.csv
    EURUSD_TDS,TDS_csvs\EURUSD_GMT+2\EURUSD_GMT+2_US-DST.csv
    EURUSD-TDS,TDS_csvs\EURUSD_GMT+2\EURUSD_GMT+2_US-DST.csv
    ```
  (Both `_TDS` and `-TDS` rows allowed — same source file, two destinations
  if Cree wants both updated.)
- `bool ClearBeforeImport` — default true. If true, calls
  `CustomTicksReplace(symbol, 0, LLONG_MAX, empty_array)` first to wipe
  existing history before importing fresh ticks. Otherwise we replace
  only the date range present in the CSV.
- `int ChunkSize` — default 1,000,000 ticks per `CustomTicksReplace` call.

Per row in the mapping CSV:
1. `CustomSymbolSelect(symbol, true)` — make sure it's in MarketWatch.
2. Open the source CSV with `FileOpen(rel_path, FILE_COMMON|FILE_READ|FILE_TXT|FILE_ANSI)`.
3. Loop:
   - Read up to `ChunkSize` lines, parse `YYYY.MM.DD HH:MM:SS.fff,bid,ask` into
     `MqlTick[]` with `time_msc` = ms-since-epoch, `bid`, `ask`, `flags=TICK_FLAG_BID|TICK_FLAG_ASK`.
   - Call `CustomTicksReplace(symbol, chunk_start_msc, chunk_end_msc, ticks)`.
   - If return value != chunk length, log a warning (MT5 docs: function
     stops on chronological violations and leaves the rest unchanged).
4. Close the file. Log "[OK] <symbol>: N ticks imported in M sec".
5. On any error, log and continue to the next symbol — don't abort the
   whole batch.

The EA writes a side log to `<MT5>\MQL5\Files\TDM_Updater\import_<timestamp>.log`
with the same level of detail as `tdm_export.py`'s log.

When done, `ExpertRemove()` so the EA detaches from the chart.

### Phase C: invocation

Two reasonable patterns:

- **Manual one-click**: Cree double-clicks the EA in the Navigator → Experts
  tree, drops it on any chart. The EA reads its inputs, runs through the
  mapping, removes itself. Cree watches the Experts tab for log output.
- **Headless via Strategy Tester** (matches the existing automated backtest
  framework): a `tester.ini` that runs the EA on a no-op symbol (e.g. one
  of the empty TDS symbols) for a one-day no-trade run, with the EA
  performing the import in `OnInit`. The tester logs go to MQL5\Files\…
  and the headless runner can wait for the log file to appear.

Recommendation: start with the manual pattern. Add headless mode after
we've verified the EA works end-to-end on a single symbol.

### Phase D: weekly automation (later)

Once Phase B/C is proven, hook it into the existing weekly schedule:

```
Sunday 02:00 — TDM Updater scheduled task runs (existing)
   → tdm_export.py refreshes all CSVs
   → on success, invokes terminal64.exe with the tester.ini that runs
     the TDM_TickImporter EA, which re-imports all 27 symbols.
```

Constraint: the existing automated backtest framework also uses
terminal64.exe via `/config`. The importer should NOT run while a backtest
is queued. The simplest sync: the importer EA acquires a file lock
(`MQL5\Files\TDM_Updater\IMPORT_IN_PROGRESS`) at start, the backtest runner
checks for that lock before launching. We'll design this when we get
there — for now Phase D is out of scope until Phase B/C is proven.

---

## Decisions (confirmed 2026-05-24)

1. **Target only `_TDS`** as the canonical name. Ignore `-TDS` while writing.
2. **Script creates missing `_TDS` symbols** via `CustomSymbolCreate` (template:
   the existing same-asset `_TDS` or `-TDS` if present; otherwise a like-asset
   `_TDS`).
3. **ETHUSD_TDS** receives the data from `Ether_vs_US_Dollar_GMT+2_US-DST.csv`.
4. **Incremental updates with continuity verification.** Per symbol: read MT5's
   last tick time T_last → seek CSV to T_last → verify the LAST 1 hour of MT5's
   ticks matches the corresponding window in the CSV byte-for-byte (within a
   small tolerance for floating-point bid/ask) → if they match, append via
   `CustomTicksAdd()`; if they don't, ABORT that symbol and mark it for
   manual full-reimport.
5. **Timezone is GMT+2 with US DST** on every `_TDS` symbol. No conversion
   needed when writing `time_msc`.
6. **Delete the `-TDS` variants** after the first successful import of the
   matching `_TDS`. Cree confirmed this is the intended cleanup. **Warning**:
   any saved chart / .set file / tester.ini that still references `-TDS`
   names will error after deletion. Grep configs for those names BEFORE the
   first run.
7. **Build 5833** → ≥ 2085, so auto-bar-generation from imported ticks works.
   No need to call `CustomRatesReplace` separately.

## Final design

**Mode auto-detection per symbol**:
- If `<SYMBOL>_TDS` doesn't exist → call `CustomSymbolCreate(clone_from=template)`,
  then **full import** via `CustomTicksReplace(symbol, 0, last_csv_msc, ticks)`.
- If `<SYMBOL>_TDS` exists but has zero ticks → **full import**.
- If `<SYMBOL>_TDS` exists and has ticks → query `T_last` (the most recent
  tick's `time_msc`), seek the CSV to the line whose timestamp matches
  T_last, run the **continuity check** on the prior 1-hour window, and:
  - If matches → **incremental append** via `CustomTicksAdd(symbol, new_ticks)`
    for everything after T_last.
  - If mismatch → log loudly, leave the symbol untouched, list it in a
    `needs_full_reimport.csv` for Cree to review.

**Template-symbol map for new `_TDS` creation** (used by `CustomSymbolCreate`):

| New symbol | Template (clone_from) |
|---|---|
| GBPUSD_TDS | GBPUSD-TDS (existing) |
| XAUUSD_TDS | XAUUSD-TDS (existing) |
| EURCAD_TDS | AUDCAD_TDS (FX major) |
| GBPCHF_TDS | EURCHF_TDS (FX cross with CHF) |
| NZDCAD_TDS | AUDCAD_TDS (FX cross with CAD) |
| SGDJPY_TDS | CADJPY_TDS (FX cross with JPY) |

After the first successful import + verification, delete the `-TDS`
counterparts:
- EURUSD-TDS, GBPUSD-TDS, USDCAD-TDS, USDCHF-TDS, USDJPY-TDS, USDSEK-TDS, XAUUSD-TDS

**Continuity check** (the 1-hour overlap verification):
- Define `WINDOW = 1 hour` (configurable).
- Read MT5's ticks for the range `[T_last - WINDOW, T_last]` via
  `CopyTicksRange(symbol, T_last-WINDOW, T_last)` → array A.
- Read the CSV lines whose timestamps fall in the same range → array B.
- Compare: same length, same time_msc per index, |A.bid - B.bid| < epsilon,
  |A.ask - B.ask| < epsilon. Epsilon = 0.00001 for FX, 0.001 for indices
  and metals, 0.5 for BTCUSD (broker rounding tolerance).
- Mismatch → symbol fails, listed in `needs_full_reimport.csv`.

**Pre-flight check (manual, before the first import run)**:
- Grep all backtest .ini, .set, and EA configs for `-TDS` references:
  ```powershell
  Select-String -Path 'C:\Users\me\AppData\Roaming\MetaQuotes\Terminal\EACE9A382E6AACB6A53D9C4DFC6909F6\MQL5\Profiles\Tester\*.ini', 'C:\Users\me\Documents\MOL Algos\**\*.set', 'C:\Users\me\Documents\MOL Algos\**\*.ini' -Pattern '-TDS'
  ```
- Replace each hit with the corresponding `_TDS` name BEFORE running the
  importer (the importer will delete the `-TDS` symbols at the end).

---

## Risks and precautions

- **Cree's running backtests use these `_TDS` symbols.** Replacing the tick
  history while a backtest is reading it will at best produce inconsistent
  results, at worst crash the tester. **Wait for the queue to clear** before
  the first import test. Confirmed by Cree.
- **CustomTicksReplace REPLACES, doesn't merge.** If `ClearBeforeImport=true`,
  the symbol's prior tick history is gone forever. Cree should know this is
  the intended behavior, since the source-of-truth is now TDM's CSVs.
- **MQL5 EA on a multi-GB CSV may take 10–30 minutes per symbol** depending
  on chunk size and disk speed. The full 27-symbol import will run for
  several hours, same as the TDM export side.
- **Backup before first run**: copy `bases\Custom\ticks\` and
  `bases\Custom\historical\` somewhere safe before the first import in
  case the EA has a bug we didn't catch.
- **MQL5 errors are easy to miss** — the EA's "Experts" log doesn't always
  surface clearly. The EA will write to its own log file at
  `MQL5\Files\TDM_Updater\import_*.log` with full DEBUG output, separate
  from MT5's own log.

---

## Estimated effort

- Phase A (junction): 1 min.
- Phase B (write the EA): 2–4 hours (parse CSV, chunked import, mapping,
  error handling, logging). The CSV parser is the most error-prone part —
  TDM's microsecond-precision timestamps need careful `time_msc` math.
- Phase C (first end-to-end test on one small symbol): 30 min.
- Full 27-symbol import: 2–6 hours wall time (mostly tick parsing + disk I/O).

---

## Pause point (2026-05-24)

Implementation was started and immediately halted: **D:\ drive is not mounted**
on the system right now. Only C:\ (OS) and G:\ (Google Drive) are visible.

Before resuming the MT5 import, restore D:\ so the CSVs are reachable. Quick
sanity check when D:\ is back:

```powershell
ls 'D:\TickData\AUDCAD_GMT+2_US-DST.csv'   # should exist, ~6.9 GB, mtime 2026-05-23 12:27
ls 'D:\TickData\XAUUSD_GMT+2-DST\XAUUSD_GMT+2_US-DST.csv'  # ~15.8 GB, mtime 2026-05-23 20:51
```

If those are intact, the next steps to execute (in order) are:

1. Create the NTFS junction:
   ```cmd
   mklink /J "C:\Users\me\AppData\Roaming\MetaQuotes\Terminal\Common\Files\TDS_csvs" "D:\TickData"
   ```
2. Pre-flight: confirm `Get-Process terminal64` is empty (no backtests running).
3. Build `TDM_TickImporter.mq5` per the design above (auto-detect mode,
   dual-write to `_TDS` AND `-TDS` for the 7 pairs that have both, continuity
   verification on overlap window, `CustomSymbolCreate` for missing `_TDS`).
4. Compile via MetaEditor command line:
   `MetaEditor64.exe /compile:"<path>\TDM_TickImporter.mq5" /log`
5. Smoke test on a small symbol (NZDCAD recommended — only ~1 GB).
6. Full run.

The pre-flight grep also found **295 references to `-TDS` symbols across 101
files** in MT5 Profiles\Tester and project configs — most under
`Profiles\Tester\Agg V1 Pro XAUUSD May 1.XAUUSD-TDS.M1.…`. Per Cree's decision
on 2026-05-24, the importer will **dual-write to both `_TDS` and `-TDS`** for
the 7 pairs that have both, and not delete anything. This protects all 100+
saved backtest configs.

The TDM Updater weekly scheduled task is still registered for Sun 5/31 02:00.
If D:\ is not back by then, it will fail cleanly at the
`inventory.py` step (raises `D:\TickData does not exist`) without
touching `state.json` — safe to leave armed.

## Sources

- [MQL5 CustomTicksReplace docs](https://www.mql5.com/en/docs/customsymbols/customticksreplace)
- [MQL5 CustomTicksAdd docs](https://www.mql5.com/en/docs/customsymbols/customticksadd)
- [MQL5 Python integration (read-only API)](https://www.mql5.com/en/docs/python_metatrader5)
- [MQL5 FileOpen sandbox rules](https://www.mql5.com/en/docs/files/fileopen)
- [Klondike FX: Importing tick data into MT5](http://klondikefx.com/import-tickdata-in-metatrader5/) — GUI approach reference
- [Importing High Quality Tick Data to MT5](https://www.mql5.com/en/blogs/post/746240) — MQL5 community walkthrough
