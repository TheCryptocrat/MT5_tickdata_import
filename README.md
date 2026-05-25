# TDM Updater

Automated weekly refresh of the canonical `<SYMBOL>_GMT+2_US-DST.csv` tick CSVs
under `D:\TickData` by driving Tick Data Manager (Birt's Tick Data Suite v2)
via Windows UI Automation.

**Status as of 2026-05-24:** 27 of 28 canonical symbols are exporting cleanly;
the weekly scheduled task is registered to fire **Sundays at 02:00**, next run
2026-05-31.

---

## What it does

For each symbol in `manifest.json`:

1. Filter the TDM grid to the symbol.
2. Open the per-row Operations dialog (the **⋮** button — *not* right-click;
   right-click does nothing in TDM).
3. On the **Download** tab: click *Get new data* → *Start download*. Wait for
   the TDS download queue to drain.
4. On the **Export ticks** tab: set Start/End dates to `1/1/2020 → today`
   (TDM may clamp either end down to its on-disk data range; the script
   accepts whatever TDM gives back).
5. Click *Start export*. Handle the Save-As dialog (path verified pasted via
   `legacy_properties().Value` after each method, hard-fails if the path
   doesn't stick), click Save, click Yes on the overwrite prompt.
6. Wait for *Status: idle*.
7. Verify the destination file's mtime advanced and size is sane.
8. Save state.json so a crash or power-loss restart resumes from the next
   symbol — never re-does completed work.

Downloads are queued **in parallel** (TDS supports queueing many downloads).
Exports run **strictly sequentially** (TDS's export-ticks UI doesn't accept
queueing a second export while one is running, and we proved that parallel
attempts cause data corruption — see *Lessons learned* below).

---

## Quick start

```powershell
# One-time, manual full run (multi-hour):
python tdm_export.py --resume --restart-every 5

# Just one symbol (smoke test):
python tdm_export.py --only EURUSD

# Inspect what would happen without doing anything:
python tdm_export.py --dry-run

# Resume after a crash or partial run:
python tdm_export.py --resume

# Aggressive: restart TDM after every successful export
# (use when the UI is flaky / for forced-clean re-exports)
python tdm_export.py --resume --restart-every 1

# Rebuild the manifest after adding new symbols/folders:
python inventory.py --print
```

The weekly schedule:

```powershell
# Install (Sunday 02:00 default; needs interactive logon — TDM has no headless mode):
.\Register-WeeklyTask.ps1

# Custom day/time:
.\Register-WeeklyTask.ps1 -DayOfWeek Saturday -At "23:30"

# Remove:
.\Register-WeeklyTask.ps1 -Unregister

# Run on-demand:
Start-ScheduledTask -TaskName "TDM Updater (weekly tick CSV refresh)"

# View status:
Get-ScheduledTaskInfo -TaskName "TDM Updater (weekly tick CSV refresh)"
```

---

## Files

| File | Purpose |
|---|---|
| `inventory.py` | Scans `D:\TickData`, classifies every `.csv`, writes `manifest.json`. |
| `manifest.json` | Generated. `keep` is the work list, `flag_misfiled`/`skip` explain everything intentionally excluded. |
| `tdm_export.py` | Main driver. CLI flags: `--resume`, `--restart-every N`, `--only A,B,C`, `--dry-run`. |
| `state.json` | Generated. Per-symbol status (`pending`/`downloading`/`exporting`/`done`/`failed`), attempt count, pre/post size+mtime, last error. |
| `run_weekly.ps1` | Wrapper for the scheduled task: rebuilds manifest, runs `tdm_export.py --resume`. |
| `Register-WeeklyTask.ps1` | Installs/uninstalls the Windows scheduled task. |
| `logs/run_YYYYMMDD_HHMMSS.log` | Per-run DEBUG log. |
| `discover_*.py`, `probe_*.txt`, `*.png` | Discovery artefacts from the UI-mapping phase. Keep for reference if TDM updates and breaks selectors. |

---

## Lessons learned the hard way (2026-05-23 marathon)

Worth knowing before changing anything in `tdm_export.py`:

### 1. NEVER parallel-queue exports — it silently corrupts data

TDS *downloads* parallel-queue fine, but if you fire-and-forget multiple Start-Export
clicks in succession, the Save-As dialogs overlap. `_wait_for_save_dialog()` then
returns a *stale* dialog from a previous symbol, and your path gets pasted into
the wrong dialog — so symbol N's tick data is written to symbol K's destination file.

We confirmed real-world cross-corruption in our 2026-05-23 run:
- AUDUSD ended up with **AUDJPY** data (Oct 2021 onwards, 84.89 first bid)
- CHFJPY ended up with **BTCUSD** data (7157.6 first bid in 2020)
- XAGUSD finished at 0 bytes

Phase 2 in `tdm_export.py` is now strictly `wait_for_completion=True`. The hard
guard in `_fill_save_dialog` (see lesson 4) is a backstop.

### 2. TDM degrades after ~6–8 ops dialog opens — restart it

After about 6–8 successive `...`-button → ops-dialog cycles, the dialog stops
opening (timeout), and date pickers stop accepting input (typed values get
silently rejected). Likely a leak in TDM's WPF state.

The driver now restarts TDM (gracefully then `taskkill /F`) after:
- `--restart-every N` successful exports (default 5)
- 2 consecutive failures (so a wedged TDM doesn't burn through the whole list)

For maximum reliability, use `--restart-every 1` (one symbol per fresh TDM
instance). Adds ~25 sec of overhead per symbol but never wedges.

### 3. Date pickers clamp silently — accept what TDM gives back

TDM's Export-Ticks Start picker won't go before the symbol's actual on-disk
data range. Example: we asked for `1/1/2020` for AUDJPY, but TDM only has
AUDJPY back to `10/25/2021`, so it kept `10/25/2021`. Same on the End picker
if today's ticks aren't yet downloaded — it clamps to yesterday.

The script tries to set the requested date, reads back the value via
`legacy_properties().Value` (NOT `window_text()` — that returns the placeholder
string), and if TDM kept any real date, **accepts it and moves on**. It does
not fail just because TDM clamped.

### 4. Save-As filename Edit is brittle — multi-method paste with hard verify

Modern Common Item Dialog (Win10/11): the filename `Edit` (auto_id `1001`) is
nested inside a `ComboBox` (`FileNameControlHost`). A single Ctrl+V paste was
flaky — sometimes the previous symbol's path was retained, and Save then wrote
THE CURRENT symbol's tick data to the PREVIOUS symbol's path. Silent data
corruption.

The current `_fill_save_dialog` tries four methods in sequence:
1. `clipboard + Ctrl+V`
2. `pywinauto send_keys` (with `+`, `^`, `%`, `~` escapes)
3. `edit.set_edit_text(...)`
4. `clipboard + Ctrl+V` retry

After each, it reads `edit.legacy_properties()["Value"]` and confirms the
target path is a substring. If none of the four methods sticks, the script
sends `Esc` to cancel the Save-As (preventing a wrong-path write) and raises.
The symbol is then marked `failed` in state.json.

### 5. mtime-only verify is too strict — TDM legitimately skips no-op exports

If the destination CSV already covers the requested date range with valid data,
TDM dismisses the export quickly and never actually rewrites the file. Our
strict "mtime must advance" check then flagged the symbol as failed.

For our 2026-05-23 recovery, the workaround was: if a re-export needs to be
forced, **delete the destination CSV first**. With no file there, TDM has to
write fresh. (We did this for AUDUSD and XAGUSD.)

A future enhancement: relax the verify to also accept "mtime unchanged but
file's tail-line date ≥ requested end date" as a pass.

### 6. `window_text()` is a lying placeholder

On both the Save-As filename Edit and the WPF date-picker text boxes,
`window_text()` returns `"File name:"` or empty — it shows the placeholder
caption, **not** the value. Always read `legacy_properties()["Value"]`
instead.

### 7. Some symbols can be "stuck" in TDM internally

In our 2026-05-23 run, AUDUSD reached a state where clicking *Start Export*
did nothing — no overwrite prompt, no file write, no error. Killing TDM and
restarting did not help. The script could not work around it.

Workaround: open TDM manually, AUDUSD row's `...` → **Download** tab → click
*Get all data* (or *Reset*) to force a re-download. Then re-run the script.

---

## State of the data store

| Source | Path | Notes |
|---|---|---|
| TDM install | `D:\TickData\` | Tick Data Manager.exe lives here. Also where the canonical CSVs are exported. |
| TDM internal storage | `C:\Users\me\OneDrive\Desktop\MOL Algos\` | Per registry `HKCU\Software\eareview.net\Tick Data Suite v2\StoragePath`. SQLite catalog (`tds.db`) + per-source tick blobs under `Dukascopy\` and `fxopen\`. Back THIS up if you want to back up downloaded ticks. |
| Per-symbol CSV exports | `D:\TickData\<SYMBOL_FOLDER>\<SYMBOL>_GMT+2_US-DST.csv` | The work products. Format: `YYYY.MM.DD HH:MM:SS.fff,bid,ask`, no header, GMT+2 with US DST. |

---

## Manifest details

`inventory.py` walks `D:\TickData` and classifies every `.csv` into one of:

- **keep** — `<SYMBOL>_GMT+2_US-DST.csv` or `<SYMBOL>_GMT+2.csv` matching the
  canonical pattern; the symbol prefix matches its parent folder name; not
  in an excluded directory or a bar/date-range/legacy filename. *Processed.*
- **flag_misfiled** — filename's symbol prefix doesn't match its parent
  folder (e.g. `D:\TickData\NZDJPY\GBPJPY_GMT+2_US-DST.csv`). *Listed but
  not processed* — need a human to decide whether to move/delete/rename.
- **skip** — bar exports (`_M1`, `_H1`, etc.), date-ranged subsets (`-5YR`,
  `2022-2023.csv`), `_TDS` legacy variants, files under `New folder*`,
  `OHLC_Broker_Data\`, `1HR For Training Data\`, `1M OHLC\`, `1YR USDJPY\`,
  `Stocks\`, `parquet\`. *Not processed.*

If you add a new symbol folder under `D:\TickData`, the next weekly run picks
it up automatically (after `run_weekly.ps1` regenerates `manifest.json`).

---

## Known unresolved items

| Symbol | Issue | Fix |
|---|---|---|
| AUDUSD | TDM-side "stuck" — Start Export does nothing | Manually click *Get all data* on the Download tab in TDM, then re-run the script. |
| SOLUSD | Not present in Dukascopy provider | Switch TDM Source to a provider that has it (fxopen?), or accept that it can't be auto-refreshed. |
| USA_30_Index, USA_500_Index, USA_100_Technical_Index, US_Small_Cap_2000 | Symbol names don't match anything in Dukascopy | Likely indexed under shorter ticker names (USA30, USA500, USTEC, US2000) in some other TDM provider. Identify the correct provider + name, then add an entry to `SYMBOL_OVERRIDES` in `inventory.py`. |

---

## Adding a new symbol

1. In TDM GUI, download the new symbol via the per-row `...` → Download tab.
2. Export it once manually via TDM to confirm the canonical destination path
   (e.g. `D:\TickData\<NEW>\<NEW>_GMT+2_US-DST.csv`).
3. Run `python inventory.py --print`. The new file should appear in the
   `keep` list. If it's in `flag_misfiled` or `skip`, either fix the
   filename/folder or add a `SYMBOL_OVERRIDES` mapping in `inventory.py`.
4. The next weekly run will refresh it.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `RuntimeError: symbol X not found in TDM grid (check provider)` | TDM's Source dropdown is set to a provider that doesn't have X. | Change the Source dropdown manually, or add an alias in `SYMBOL_OVERRIDES`. |
| `TdmTimeout: timed out after 10s waiting for: operations dialog` (repeated) | TDM UI degraded. | Lower `--restart-every`, or stop and let `taskkill /F /IM "Tick Data Manager.exe"` clear it. |
| `date picker DatePickerExportTicksStart not found` | Tab didn't switch, or ops dialog is stale. | Restart TDM. The restart-on-2-failures logic should auto-handle this in the next iteration. |
| `target file missing after export` (with no other error) | TDM accepted the export task but didn't actually write. Usually means the symbol is "stuck" (see lesson 7). | Manually intervene in TDM. |
| `file mtime did not advance` | TDM skipped because the existing file already covers the range. | Delete the destination CSV to force a re-export, or accept the existing data as still-valid. |
| Scheduled task didn't run | Workstation was locked or logged off. | Stay logged in; the task is `LogonType=Interactive` because TDM has no headless mode. |

---

## Architecture summary

```
┌────────────────────────────────────────────────────────────────┐
│  Sunday 02:00 — Windows Task Scheduler                          │
│  → run_weekly.ps1                                               │
│     → python inventory.py     (rebuild manifest)                │
│     → python tdm_export.py --resume --restart-every 5            │
│        │                                                         │
│        │  Phase 1: queue all downloads in parallel (TDS supports │
│        │           this; the script reads each row's available  │
│        │           range, clicks `...` → Download → New data)   │
│        │  Phase 2: sequentially export each symbol's CSV        │
│        │           (open ops, set dates, Start export, paste    │
│        │           path, Save, Yes-overwrite, wait for idle,    │
│        │           verify mtime advanced)                       │
│        │  Phase 3: implicit — Phase 2 verifies each symbol      │
│        │           inline                                       │
│        └──────────────┬─────────────────────────────────────────┘
                       │
                  state.json (resumable; atomic-ish per-symbol)
                       │
                  logs/run_YYYYMMDD_HHMMSS.log (DEBUG)
```

Phase 1 finishes quickly when most symbols are already up to date (TDS
detects this and skips). Phase 2 is the time-dominant part — each symbol
takes anywhere from 1 minute (small range, slow disk) to 30 minutes
(BTCUSD or EURUSD, 14+ GB).

---

## See also

- Related project memory: `~/.claude/projects/.../memory/project_tdm_updater.md`
- Broker symbol suffix rule: `~/.claude/projects/.../memory/broker_symbol_suffix.md`
- Symonds methodology (canonical backtest method that consumes these CSVs):
  `~/.claude/projects/.../memory/symonds_methodology.md`
