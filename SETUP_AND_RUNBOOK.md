# TDM → MT5 Tick Pipeline — Setup & Runbook

Complete end-to-end setup for the weekly tick-data refresh pipeline. Two stages:

1. **TDM Updater** — drives Tick Data Manager (Birt's Tick Data Suite v2) via
   Windows UI Automation to refresh `<SYMBOL>_GMT+2_US-DST.csv` files on disk.
2. **MT5 TickImporter** — an MQL5 script that reads those CSVs and writes
   ticks into MT5's custom `*_TDS` / `*-TDS` symbols (used by tick-accurate
   backtests).

Designed to be replicable on a fresh Windows machine. All paths are explicit.

---

## 1. Prerequisites

| Software | Purpose | Source |
|---|---|---|
| Windows 10/11 (x64) | host OS | n/a |
| Tick Data Manager v2 + Tick Data Suite license | downloads ticks from Dukascopy/fxopen | https://eareview.net/tick-data-suite/ — paid subscription required |
| MetaTrader 5 (build ≥ 2085, recommended 5800+) | the platform that uses the imported ticks | broker-provided installer; pin a portable install for backtests so it doesn't auto-update on launch |
| Python 3.13 (x64) | runs the TDM Updater driver | https://www.python.org/downloads/ — install for current user, add to PATH |
| `pywinauto` package | UI automation for the TDM GUI | `pip install pywinauto` |
| Sufficient disk | ~150 GB free for the canonical CSVs | a dedicated drive recommended (D:\ in this setup) |

This setup uses these specific paths on the reference machine — adjust to your
layout:

```
D:\TickData\                                                                      # canonical CSVs + TDM install
C:\Users\<you>\OneDrive\Desktop\MOL Algos\                                        # TDM internal tick storage
C:\Users\<you>\OneDrive\Documents\MOL Algos\Honest Engine for PC\TDM Updater\     # this project
C:\Users\<you>\Documents\MetaTrader Instances\terminal64.exe                      # dedicated MT5 install
C:\Users\<you>\AppData\Roaming\MetaQuotes\Terminal\<HASH>\                        # MT5 portable data dir
C:\Users\<you>\AppData\Roaming\MetaQuotes\Terminal\Common\Files\                  # shared MT5 sandbox
```

To find your MT5 portable data dir, check `bases\Custom\` (where custom
symbols live) under each hash folder until you find the one that has your
`*_TDS` symbols.

---

## 2. Stage 1 — TDM Updater

### 2.1 Install Tick Data Manager

1. Buy a subscription at https://eareview.net.
2. Install Tick Data Manager. Install the application to `D:\TickData\` (the
   installer will let you choose) so the per-symbol CSV export folders end up
   alongside the executable. If you use the default install path, the
   manifest's filenames still work — you just need a different working dir.
3. Launch `Tick Data Manager.exe`, log in with your eareview credentials.
4. In TDM's settings (`gear` icon, top-right), set the **Storage path** to a
   folder with at least 60 GB free. On the reference machine this is
   `C:\Users\<you>\OneDrive\Desktop\MOL Algos\`. This is where TDM keeps its
   internal tick database (`tds.db` SQLite + `Dukascopy\` / `fxopen\` blobs).
   Back THIS up to preserve downloaded ticks across machines.
5. In TDM, set the **Source** dropdown to `Dukascopy` (the default provider
   for the reference machine). Most FX, metals, and crypto symbols are
   available there.
6. For each symbol you want to back-test on, do an initial manual download:
   - Click `...` (the per-row Operations button) on the symbol's row.
   - Tab: **Download** → click **Get all data** → click **Start download**.
   - Wait for `Status: idle` (multi-hour for full FX history).
7. Manually export each symbol once to establish the canonical CSV path
   (`...` → **Export ticks** → set Start/End to whatever range you want,
   click **Start export** → save to
   `D:\TickData\<SYMBOL>\<SYMBOL>_GMT+2_US-DST.csv`). This export path is
   what the TDM Updater driver will reuse going forward.

### 2.2 Install the TDM Updater scripts

```powershell
# Clone or copy the project into your Documents area
mkdir 'C:\Users\<you>\Documents\MOL Algos\Honest Engine for PC'
cd 'C:\Users\<you>\Documents\MOL Algos\Honest Engine for PC'
# (copy the TDM Updater\ folder from this repo to here)
cd 'TDM Updater'

# Install Python dependency
pip install pywinauto
```

### 2.3 First-time run

```powershell
# Build/refresh the manifest from D:\TickData (classifies every .csv)
python inventory.py --print
# Verify: keep=N, flag_misfiled=Y, skip=Z. Resolve any misfiled by hand.

# Smoke test on a single small symbol:
python tdm_export.py --only AUDNZD

# If that works, run the full refresh (multi-hour):
python tdm_export.py --resume --restart-every 5
```

`--restart-every N` restarts TDM after every N successful exports — TDM's
WPF UI leaks state and the per-row Operations button stops opening after
~6-8 cycles. `5` is a good default; `1` is the safest if you see flakiness.

The script writes `state.json` (resumable; survives crash + power loss),
`logs/run_<timestamp>.log` (per-run DEBUG log), and refreshes every
`<SYMBOL>_GMT+2_US-DST.csv` to cover `1/1/2020 → today` (clamped by TDM's
on-disk data range — typically a symbol's earliest date in TDM determines
the actual start).

### 2.4 Schedule the weekly refresh

```powershell
# Sunday 02:00 default (next sunday at 02:00 unless that's in the past):
.\Register-WeeklyTask.ps1

# Custom:
.\Register-WeeklyTask.ps1 -DayOfWeek Sunday -At "02:00"

# Verify:
Get-ScheduledTaskInfo -TaskName "TDM Updater (weekly tick CSV refresh)"

# Manual run on-demand (useful for catch-up):
Start-ScheduledTask -TaskName "TDM Updater (weekly tick CSV refresh)"

# Remove:
.\Register-WeeklyTask.ps1 -Unregister
```

**Important**: the scheduled task uses `LogonType=Interactive`. TDM is a WPF
GUI and cannot run headless — the user session must be unlocked at trigger
time. Don't lock the workstation overnight, or pick a trigger time when
you're at the machine.

---

## 3. Stage 2 — MT5 TickImporter

This stage reads the CSVs from Stage 1 and writes them into MT5's custom
`*_TDS` / `*-TDS` symbols.

### 3.1 Custom symbol convention

The convention used here is to keep all imported-tick symbols suffixed `_TDS`
(or the legacy `-TDS` if older backtest configs depend on it). E.g.:

| Source CSV | Destination(s) in MT5 |
|---|---|
| `AUDCAD_GMT+2_US-DST.csv` | `AUDCAD_TDS` |
| `EURUSD_GMT+2_US-DST.csv` | `EURUSD_TDS` AND `EURUSD-TDS` (dual-write for legacy compat) |
| `XAUUSD_GMT+2_US-DST.csv` | `XAUUSD_TDS` AND `XAUUSD-TDS` |
| `Ether_vs_US_Dollar_GMT+2_US-DST.csv` | `ETHUSD_TDS` |

Pairs that can have both `_TDS` and `-TDS` (because saved backtest configs
on the reference machine reference both): **EURUSD, GBPUSD, USDCAD, USDCHF,
USDJPY, USDSEK, XAUUSD**.

All custom symbols are configured for **GMT+2 timezone with US DST rules**
(matches TDM's CSV export timezone).

### 3.2 One-time setup

#### 3.2.1 NTFS junction (so MQL5 can read CSVs)

MQL5's `FileOpen()` is sandboxed to `<MT5 portable>\MQL5\Files\` or
`<MT5 Common>\Files\` (when using `FILE_COMMON`). We use a directory
junction to expose `D:\TickData` inside the Common folder without copying
~150 GB:

```cmd
mklink /J "C:\Users\<you>\AppData\Roaming\MetaQuotes\Terminal\Common\Files\TDS_csvs" "D:\TickData"
```

Junctions cross volumes (unlike hardlinks). One-time, idempotent — re-running
errors but doesn't break anything.

#### 3.2.2 Pre-flight: find any backtest configs still using `-TDS`

If you plan to standardize on `_TDS` and let the legacy `-TDS` symbols stale
out, grep for them so you know what to migrate later:

```powershell
Select-String -Path 'C:\Users\<you>\AppData\Roaming\MetaQuotes\Terminal\<HASH>\MQL5\Profiles\Tester\*.ini','C:\Users\<you>\Documents\**\*.set','C:\Users\<you>\Documents\**\*.ini' -Pattern '-TDS'
```

The reference machine had 295 hits across 101 files — so we chose to
**dual-write** to both `_TDS` and `-TDS` rather than delete the legacy
variants. No configs need to change immediately.

#### 3.2.3 Generate the mapping CSV

```powershell
cd 'C:\Users\<you>\Documents\MOL Algos\Honest Engine for PC\TDM Updater'
python build_mapping.py
```

This writes
`<MT5 Common>\Files\TDM_Updater\mapping.csv`, the table of `(dest_symbol,
template_for_create_or_empty, csv_relative_path)` tuples the importer reads.
Edit `build_mapping.py` if you have different symbols or want different
destinations.

#### 3.2.4 Compile the MQL5 script

```powershell
$me  = 'C:\Users\<you>\Documents\MetaTrader Instances\MetaEditor64.exe'
$src = 'C:\Users\<you>\AppData\Roaming\MetaQuotes\Terminal\<HASH>\MQL5\Scripts\TDM_TickImporter.mq5'
& $me /compile:$src /log:"$($src -replace '\.mq5$','.log')"
# Look for "Result: 0 errors, 0 warnings"
```

The `.ex5` lands next to the `.mq5`. MT5 auto-loads new compilations.

### 3.3 Smoke test (one symbol)

In MT5:
1. Press **Ctrl+N** to show the Navigator panel.
2. Expand **Scripts** → drag **TDM_TickImporter** onto any chart.
3. In the input dialog (**Inputs** tab):
   - Set **"smoke test: only this dest_symbol"** to `NZDCAD_TDS` (or another
     small symbol you want to test on).
   - Leave the rest at default.
   - Click **OK**.
4. The script runs in the foreground and auto-detaches when done.
5. Check the log:
   `C:\Users\<you>\AppData\Roaming\MetaQuotes\Terminal\Common\Files\TDM_Updater\import.log`
   — look for `[OK] <SYMBOL>_TDS full <N> ticks`.

A successful full import of a ~3 GB CSV takes ~90 sec on a fast SSD.

### 3.4 Full run (all 33 destinations)

Same as the smoke test, but **clear** the "smoke test: only this dest_symbol"
field so it's blank. The script processes the entire mapping.

Expected runtime on the reference machine: 5-15 min for the typical weekly
refresh (most symbols use the incremental + continuity-check path; only a
few fresh imports take ~90s each).

### ⚠ 3.4.1 CRITICAL: close MT5 via File → Exit after the import

`CustomSymbolCreate()` registers the new symbol **in memory only**. MT5 only
persists the symbol manifest (`<MT5 portable>\bases\symbols.custom.dat`) on a
**clean shutdown via File → Exit**. If MT5 is killed via Task Manager, force-
closed via the X button, or crashes before saving, the newly-created custom
symbols disappear on the next launch — even though their tick data files on
disk under `bases\Custom\ticks\<sym>\` remain. The strategy tester then
reports `symbol <NAME>_TDS not exist` and backtests fail.

After every run that creates a new `_TDS` symbol:

1. **In MT5: File → Exit** (NOT the X button, NOT Alt-F4, NOT Task Manager).
2. Wait ~10 seconds for the process to fully terminate.
3. Re-launch MT5. The new symbols should now persist permanently.

If you discover the symbols are missing after a restart, use
`mapping_recovery.csv` (or generate a similar subset) and re-run the script
just for the missing symbols, then File → Exit again.

### 3.5 What the importer does per symbol

```
for each (dest, template, csv_path) in mapping.csv:
  if dest doesn't exist in MT5:
    if template == empty: FAIL — listed in needs_full_reimport.csv
    else: CustomSymbolCreate(dest, "Custom\TDS", template)  → full import path

  if dest has no ticks: full import path
  elif force_full input set: full import path
  else:
    T_last = MT5's latest tick time for `dest`
    verify continuity:
      - read MT5's ticks in [T_last - 60min, T_last]
      - read CSV's ticks in the same window
      - compare bid/ask within an epsilon
        (0.00001 FX, 0.001 metals/indices, 0.5 BTC/ETH)
    if mismatch: SKIP — listed in needs_full_reimport.csv
    else: append CSV ticks with time > T_last via CustomTicksAdd

full import path:
  wipe existing history via CustomTicksReplace(0, last_msc, first_chunk)
  append remaining chunks via CustomTicksAdd
```

The continuity check is the safety net — if TDM revised any historical
ticks (or your import is targeting the wrong symbol), the mismatch caught
and you can force-reimport that one symbol via the input
`bypass incremental detection: true`.

---

## 4. Wiring stages together (weekly schedule)

The current setup runs Stage 1 (TDM Updater) on a Windows scheduled task
Sundays at 02:00. Stage 2 (MT5 TickImporter) is **currently a manual
drag-to-chart** because MT5 scripts can only be launched that way.

To fully automate Stage 2 in the future:

1. Convert the script to an Expert Advisor (rename
   `TDM_TickImporter.mq5` → `TDM_TickImporter_EA.mq5`, change the entry
   point from `OnStart()` to `OnInit()` that calls `ExpertRemove()` when
   done, place under `MQL5\Experts\`).
2. Write a `tester.ini` that runs the EA on a no-op symbol for a one-day
   period (the EA does its work in `OnInit` and never actually trades).
3. Invoke `terminal64.exe /portable /config:tester.ini` from a PowerShell
   wrapper.
4. Chain after Stage 1 in `run_weekly.ps1`.
5. Lock-out: have the EA write a sentinel file
   (`MQL5\Files\TDM_Updater\IMPORT_IN_PROGRESS`) at start and remove at
   end. Have any other backtest runner check for that file before
   launching.

This was scoped out for the reference deployment; see
`MT5_IMPORT_PLAN.md` § "Phase D: weekly automation".

---

## 5. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `python tdm_export.py` says `D:\TickData does not exist` | the data drive isn't mounted | check Disk Management; re-plug if external |
| `RuntimeError: symbol X not found in TDM grid (check provider)` | the TDM Source dropdown is set to a provider that doesn't have X | manually change Source in TDM, or add an alias in `inventory.py`'s `SYMBOL_OVERRIDES` |
| `TdmTimeout: timed out after 10s waiting for: operations dialog` repeatedly | TDM UI degraded | lower `--restart-every` (try `1`); kill TDM with `taskkill /F /IM "Tick Data Manager.exe"` |
| `target file missing after export` | TDM accepted the export task but didn't write (symbol is "stuck") | open TDM manually, the symbol's `...` → Download → click `Get all data` to force re-download |
| `file mtime did not advance` | TDM skipped because existing CSV already covers requested range | delete the destination CSV to force re-export, or accept existing as still valid |
| TDM_TickImporter writes empty log + skipped=N | mapping CSV parsing broken (TAB vs comma) | verify `FileOpen(..., FILE_CSV, ',')` in TDM_TickImporter.mq5 — comma delimiter is REQUIRED |
| TDM_TickImporter logs `continuity: matched=0  mismatched>0` | MT5's existing ticks for that symbol don't match TDM's CSV — likely a revised history | re-run with `bypass incremental detection: true` to force-reimport that symbol |
| Strategy Tester: `symbol <NAME>_TDS not exist` after a successful import | MT5 was killed/crashed without saving `symbols.custom.dat`; the in-memory symbol was lost on restart | re-run the importer using `mapping_recovery.csv` (only the missing symbols), then **MT5 → File → Exit** to persist. See § 3.4.1. |
| MT5 scheduled task fires but does nothing | MT5 scripts can't run headless — task is wrong concept | either drag manually post-TDM-refresh, or convert to EA + Strategy Tester (see § 4) |
| Many symbols in `needs_full_reimport.csv` after first run | first-time imports of existing `_TDS` symbols that have history that doesn't match TDM | this is expected; re-run those symbols with `forceFullReimport=true` |

---

## 6. Replicating on a new machine

```powershell
# 1. Install prerequisites (see § 1).

# 2. Clone the TDM Updater project:
git clone <repo> 'C:\Users\<you>\Documents\MOL Algos\Honest Engine for PC'

# 3. Install Python deps:
pip install pywinauto

# 4. Set up TDM (§ 2.1) — download all symbols you care about, export each
#    once manually to establish the canonical CSV paths.

# 5. Build the manifest:
cd 'C:\Users\<you>\Documents\MOL Algos\Honest Engine for PC\TDM Updater'
python inventory.py --print

# 6. Schedule the weekly TDM refresh:
.\Register-WeeklyTask.ps1

# 7. Install the MT5 importer:
mklink /J "C:\Users\<you>\AppData\Roaming\MetaQuotes\Terminal\Common\Files\TDS_csvs" "D:\TickData"
# Copy TDM_TickImporter.mq5 to <MT5 portable>\MQL5\Scripts\
python build_mapping.py
# Compile via MetaEditor64.exe /compile:<path>

# 8. Run the importer (drag in MT5 Navigator → Scripts onto a chart).
```

---

## 7. Files in this project

```
TDM Updater/
├── README.md                       # Stage 1 (TDM Updater) detailed docs
├── SETUP_AND_RUNBOOK.md            # ← this file
├── MT5_IMPORT_PLAN.md              # Stage 2 design + decisions
│
├── inventory.py                    # Stage 1: scan D:\TickData → manifest.json
├── tdm_export.py                   # Stage 1: drive TDM via UI automation
├── run_weekly.ps1                  # Stage 1: scheduled-task wrapper
├── Register-WeeklyTask.ps1         # Stage 1: install/remove the schedule
│
├── build_mapping.py                # Stage 2: generate mapping.csv
│   (writes to <MT5 Common>\Files\TDM_Updater\mapping.csv)
│
├── (in <MT5 portable>\MQL5\Scripts\)
│   └── TDM_TickImporter.mq5        # Stage 2: the MQL5 importer
│
├── manifest.json                   # generated by inventory.py
├── state.json                      # generated by tdm_export.py (resumable)
├── logs/run_*.log                  # per-run logs
└── discover_*.py, probe_*.txt      # UI discovery artefacts (reference only)
```

---

## 8. Maintenance notes

- **Adding a new symbol** to the weekly refresh: download it once in TDM,
  manually export to its canonical CSV path, then run
  `python inventory.py` — the new file appears in the `keep` list and the
  next weekly run picks it up. For MT5, add a row to `build_mapping.py`'s
  `SOURCES` and `DESTINATIONS` dicts and re-run `python build_mapping.py`.
- **Forcing a full re-import of one symbol**: drag TDM_TickImporter onto a
  chart, set the "smoke test: only this dest_symbol" input to the symbol
  name AND check **"bypass incremental detection"** to `true`.
- **Renaming a symbol**: do it in MT5 first (right-click → Properties),
  then update `build_mapping.py`, then regenerate `mapping.csv`.
- **Backing up everything**: rsync these three things:
  1. `D:\TickData\` (the CSVs)
  2. `C:\Users\<you>\OneDrive\Desktop\MOL Algos\` (TDM's internal ticks)
  3. `<MT5 portable>\bases\Custom\` (MT5's imported ticks + symbol metadata)

---

## 9. Known constraints & limitations

- **TDM has no documented CLI.** Stage 1 drives the GUI via `pywinauto`; if
  TDM updates and changes its WPF tree, the discovery artefacts in
  `discover_*.py` + `probe_*.txt` are the reference for re-mapping
  selectors.
- **MT5 scripts can't run headless.** Stage 2 currently requires a manual
  drag-to-chart per refresh cycle. See § 4 for the EA/Strategy-Tester
  conversion path.
- **The Python `MetaTrader5` package can READ ticks but NOT WRITE custom
  symbols.** Writing requires MQL5 (`CustomTicksReplace`,
  `CustomTicksAdd`, `CustomSymbolCreate`). The Python API is useful only
  for verification/inspection.
- **The TDM weekly run requires an unlocked Windows session.** Both TDM
  itself and the Common Item Dialog Save-As need a real desktop.
- **Storage:** the canonical CSVs total ~150 GB. The TDM internal storage
  (under "MOL Algos") is another ~50 GB. MT5's `bases\Custom\` grows with
  the imported ticks (~10-20 MB per symbol after compression).

---

*Last updated: 2026-05-25.*
*Reference deployment: Cree's MOL Algos backtest workstation.*
