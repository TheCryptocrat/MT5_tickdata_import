//+------------------------------------------------------------------+
//|                                          TDM_TickImporter.mq5    |
//|  Reads TDM-format tick CSVs (under D:\TickData via the           |
//|  TDS_csvs NTFS junction in MT5 Common\Files\) and writes them    |
//|  into custom symbols ending in _TDS / -TDS.                       |
//|                                                                   |
//|  Behavior per destination symbol:                                 |
//|   - If symbol doesn't exist: CustomSymbolCreate from template.    |
//|   - If symbol is empty: full import via CustomTicksReplace.       |
//|   - If symbol has ticks: continuity-check the last 1h overlap     |
//|     between MT5 and CSV; on match, append everything after        |
//|     T_last via CustomTicksAdd. On mismatch, skip + flag for       |
//|     manual full-reimport.                                         |
//|                                                                   |
//|  Mapping is read from <MT5 Common>\Files\TDM_Updater\mapping.csv. |
//|  Format (no header): dest_symbol , template_or_empty , csv_path   |
//|  csv_path uses backslashes, relative to Common\Files\ (uses the   |
//|  TDS_csvs junction).                                              |
//|                                                                   |
//|  Drag onto any chart to run. The script auto-removes when done.   |
//+------------------------------------------------------------------+
#property script_show_inputs
#property strict
#property version   "1.00"
#property copyright "TDM Updater"
#property description "Import TDM tick CSVs into MT5 custom _TDS symbols (full or incremental)."

input string  InpMappingFile        = "TDM_Updater\\mapping.csv"; // mapping CSV (FILE_COMMON)
input string  InpLogFile            = "TDM_Updater\\import.log";   // log output (FILE_COMMON)
input string  InpFailFile           = "TDM_Updater\\needs_full_reimport.csv"; // continuity-mismatch list
input int     InpChunkTicks         = 200000;                       // ticks per CustomTicksAdd call
input bool    InpForceFullReimport  = false;                        // bypass incremental detection
input string  InpOnlyDestination    = "";                           // smoke test: only this dest_symbol
input int     InpOverlapMinutes     = 60;                           // continuity verification window
input double  InpEpsilonFx          = 0.00001;                      // FP tolerance for FX
input double  InpEpsilonMetal       = 0.001;                        // FP tolerance for metals/indices
input double  InpEpsilonCrypto      = 0.5;                          // FP tolerance for BTC/ETH

int           g_log_handle          = INVALID_HANDLE;
int           g_fail_handle         = INVALID_HANDLE;

//+------------------------------------------------------------------+
//|  Logging                                                          |
//+------------------------------------------------------------------+
void OpenLog()
  {
   g_log_handle = FileOpen(InpLogFile, FILE_COMMON|FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_SHARE_READ);
   if(g_log_handle == INVALID_HANDLE)
      Print("WARN: could not open log file ", InpLogFile, " err=", GetLastError());
  }

void Log(string msg)
  {
   string stamp = TimeToString(TimeLocal(), TIME_DATE|TIME_SECONDS);
   string line = stamp + " " + msg;
   Print(line);
   if(g_log_handle != INVALID_HANDLE)
     {
      FileWriteString(g_log_handle, line + "\r\n");
      FileFlush(g_log_handle);
     }
  }

void FailListAppend(string dest, string reason)
  {
   if(g_fail_handle == INVALID_HANDLE)
     {
      // Truncate on first open so we don't accumulate stale entries
      // across runs. Use comma delimiter for CSV consistency.
      g_fail_handle = FileOpen(InpFailFile, FILE_COMMON|FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_SHARE_READ, ',');
      if(g_fail_handle == INVALID_HANDLE) return;
     }
   FileWrite(g_fail_handle, dest, reason);
   FileFlush(g_fail_handle);
  }

void CloseLog()
  {
   if(g_log_handle != INVALID_HANDLE) FileClose(g_log_handle);
   if(g_fail_handle != INVALID_HANDLE) FileClose(g_fail_handle);
  }

//+------------------------------------------------------------------+
//|  Parse one CSV line: "YYYY.MM.DD HH:MM:SS.fff,bid,ask"            |
//|  Returns true on success; sets out_msc / out_bid / out_ask.       |
//+------------------------------------------------------------------+
bool ParseCsvLine(const string line, long &out_msc, double &out_bid, double &out_ask)
  {
   // Find the two commas.
   int c1 = StringFind(line, ",");
   if(c1 <= 0) return false;
   int c2 = StringFind(line, ",", c1+1);
   if(c2 <= c1) return false;

   string ts = StringSubstr(line, 0, c1);              // "YYYY.MM.DD HH:MM:SS.fff"
   string bid_s = StringSubstr(line, c1+1, c2-c1-1);
   string ask_s = StringSubstr(line, c2+1);

   // Split timestamp on the '.' before milliseconds (last '.' in the string).
   int last_dot = StringFind(ts, ".", StringLen(ts)-5); // millis is 3 digits after a '.'
   // ts looks like "2026.05.22 23:59:59.123" — dots also separate Y/M/D
   // The millisecond dot is AFTER the space.
   int space_pos = StringFind(ts, " ");
   if(space_pos < 0) return false;
   int ms_dot = StringFind(ts, ".", space_pos);
   string base_ts;
   int ms = 0;
   if(ms_dot > 0)
     {
      base_ts = StringSubstr(ts, 0, ms_dot);
      string ms_s = StringSubstr(ts, ms_dot+1);
      // Pad/truncate to 3 digits.
      while(StringLen(ms_s) < 3) ms_s = ms_s + "0";
      if(StringLen(ms_s) > 3) ms_s = StringSubstr(ms_s, 0, 3);
      ms = (int)StringToInteger(ms_s);
     }
   else
     {
      base_ts = ts;
     }
   datetime dt = StringToTime(base_ts);
   if(dt == 0) return false;
   out_msc = ((long)dt) * 1000 + ms;
   out_bid = StringToDouble(bid_s);
   out_ask = StringToDouble(ask_s);
   return true;
  }

//+------------------------------------------------------------------+
//|  Detect asset class to pick FP epsilon                            |
//+------------------------------------------------------------------+
double EpsilonForDest(const string dest)
  {
   if(StringFind(dest, "BTC") >= 0 || StringFind(dest, "ETH") >= 0) return InpEpsilonCrypto;
   if(StringFind(dest, "XAU") >= 0 || StringFind(dest, "XAG") >= 0 ||
      StringFind(dest, "XPD") >= 0 || StringFind(dest, "XPT") >= 0 ||
      StringFind(dest, "Index") >= 0 || StringFind(dest, "Cap") >= 0)
      return InpEpsilonMetal;
   return InpEpsilonFx;
  }

//+------------------------------------------------------------------+
//|  Does a custom symbol exist?                                      |
//+------------------------------------------------------------------+
bool SymbolExists(const string sym)
  {
   ResetLastError();
   bool exists = SymbolInfoInteger(sym, SYMBOL_CUSTOM) != 0
                 || SymbolSelect(sym, true); // SymbolSelect succeeds even for non-custom
   // The cleanest check: ask MarketWatch
   if(SymbolSelect(sym, true)) return true;
   return false;
  }

//+------------------------------------------------------------------+
//|  Get the most recent tick time_msc for an existing symbol.       |
//|  Returns 0 if no ticks (or symbol empty).                        |
//+------------------------------------------------------------------+
long GetLastTickMsc(const string sym)
  {
   MqlTick latest[];
   int n = CopyTicks(sym, latest, COPY_TICKS_ALL, 0, 1);
   if(n <= 0) return 0;
   return latest[0].time_msc;
  }

//+------------------------------------------------------------------+
//|  Continuity check: do MT5's ticks in [T_last - window, T_last]   |
//|  match the CSV's ticks in the same window?                       |
//|  Returns true on match, false on mismatch.                       |
//|  Leaves the CSV file handle's position UNDEFINED (caller resets).|
//+------------------------------------------------------------------+
bool VerifyContinuity(const string dest, int csv_handle, long t_last, double epsilon)
  {
   long window_start = t_last - (long)InpOverlapMinutes * 60 * 1000;

   // Pull MT5's overlap ticks.
   MqlTick mt5_ticks[];
   int mt5_n = CopyTicksRange(dest, mt5_ticks, COPY_TICKS_ALL, window_start, t_last);
   if(mt5_n <= 0)
     {
      Log("  continuity: MT5 has 0 ticks in window — accepting (will full-import)");
      return false;  // will fall through to full-import path
     }
   Log(StringFormat("  continuity: MT5 has %d ticks in window [%I64d..%I64d]",
                    mt5_n, window_start, t_last));

   // Scan CSV from the start until we hit the window. (Linear scan — N seeks
   // would be faster but harder to write reliably; TDM CSVs are not so big
   // that linear scan to find a 1h window late in the file is intolerable
   // — usually <60s on a fast SSD.)
   FileSeek(csv_handle, 0, SEEK_SET);
   long csv_msc = 0;
   double csv_bid = 0, csv_ask = 0;
   int csv_idx = 0;
   int matched = 0, mismatched = 0;
   while(!FileIsEnding(csv_handle))
     {
      string line = FileReadString(csv_handle);
      if(StringLen(line) < 5) continue;
      if(!ParseCsvLine(line, csv_msc, csv_bid, csv_ask)) continue;
      if(csv_msc < window_start) continue;
      if(csv_msc > t_last) break;
      // Compare to mt5_ticks[csv_idx]; both arrays are time-sorted.
      // Skip MT5 ticks earlier than this CSV tick.
      while(csv_idx < mt5_n && mt5_ticks[csv_idx].time_msc < csv_msc) csv_idx++;
      if(csv_idx >= mt5_n) break;
      if(mt5_ticks[csv_idx].time_msc != csv_msc) continue; // not a tick MT5 has
      double db = MathAbs(mt5_ticks[csv_idx].bid - csv_bid);
      double da = MathAbs(mt5_ticks[csv_idx].ask - csv_ask);
      if(db <= epsilon && da <= epsilon)
        {
         matched++;
        }
      else
        {
         mismatched++;
         if(mismatched <= 3)
            Log(StringFormat("  MISMATCH @ %I64d: MT5 bid/ask=%.5f/%.5f  CSV=%.5f/%.5f",
                             csv_msc, mt5_ticks[csv_idx].bid, mt5_ticks[csv_idx].ask, csv_bid, csv_ask));
        }
      csv_idx++;
     }
   Log(StringFormat("  continuity: matched=%d  mismatched=%d  (epsilon=%g)",
                    matched, mismatched, epsilon));
   // Require at least 50% of MT5's ticks to be matched and zero mismatches.
   if(mismatched > 0) return false;
   if(matched < mt5_n / 2) { Log("  continuity: too few matches to trust"); return false; }
   return true;
  }

//+------------------------------------------------------------------+
//|  Read CSV, buffer ticks, flush in chunks via CustomTicksAdd      |
//|  (incremental) or CustomTicksReplace (full).                     |
//|  If t_after > 0, skip ticks with time_msc <= t_after.            |
//+------------------------------------------------------------------+
long ImportTicks(const string dest, int csv_handle, long t_after, bool full_replace)
  {
   FileSeek(csv_handle, 0, SEEK_SET);
   MqlTick buf[];
   ArrayResize(buf, InpChunkTicks);
   int buf_n = 0;
   long total = 0;
   long first_msc = 0, last_msc = 0;
   long csv_msc = 0;
   double csv_bid = 0, csv_ask = 0;
   uint t_start = GetTickCount();

   while(!FileIsEnding(csv_handle))
     {
      string line = FileReadString(csv_handle);
      if(StringLen(line) < 5) continue;
      if(!ParseCsvLine(line, csv_msc, csv_bid, csv_ask)) continue;
      if(t_after > 0 && csv_msc <= t_after) continue;
      if(first_msc == 0) first_msc = csv_msc;
      last_msc = csv_msc;
      MqlTick t;
      t.time      = (datetime)(csv_msc / 1000);
      t.time_msc  = csv_msc;
      t.bid       = csv_bid;
      t.ask       = csv_ask;
      t.last      = 0;
      t.volume    = 0;
      t.flags     = TICK_FLAG_BID | TICK_FLAG_ASK;
      buf[buf_n++] = t;
      if(buf_n >= InpChunkTicks)
        {
         long written = 0;
         if(full_replace && total == 0)
           {
            // First chunk of a full replace: wipe history first.
            written = CustomTicksReplace(dest, 0, last_msc, buf, (uint)buf_n);
           }
         else
           {
            written = CustomTicksAdd(dest, buf, (uint)buf_n);
           }
         if(written < 0)
           {
            Log(StringFormat("  ERROR: write failed at total=%I64d err=%d", total, GetLastError()));
            return -1;
           }
         total += written;
         buf_n = 0;
         if(total % (InpChunkTicks * 10) == 0)
            Log(StringFormat("  progress: %I64d ticks (last_time_msc=%I64d)", total, last_msc));
        }
     }
   // Final partial chunk.
   if(buf_n > 0)
     {
      long written = 0;
      if(full_replace && total == 0)
        {
         written = CustomTicksReplace(dest, 0, last_msc, buf, (uint)buf_n);
        }
      else
        {
         written = CustomTicksAdd(dest, buf, (uint)buf_n);
        }
      if(written < 0)
        {
         Log(StringFormat("  ERROR: final write failed err=%d", GetLastError()));
         return -1;
        }
      total += written;
     }
   uint elapsed_s = (GetTickCount() - t_start) / 1000;
   Log(StringFormat("  imported %I64d ticks [%I64d..%I64d] in %us",
                    total, first_msc, last_msc, elapsed_s));
   return total;
  }

//+------------------------------------------------------------------+
//|  Process one mapping row.                                         |
//+------------------------------------------------------------------+
void ProcessRow(string dest, string templ, string csv_path)
  {
   Log("--- " + dest + " <- " + csv_path);
   bool created = false;
   if(!SymbolExists(dest))
     {
      if(templ == "")
        {
         Log("  FAIL: " + dest + " doesn't exist and no template given");
         FailListAppend(dest, "missing symbol, no template");
         return;
        }
      ResetLastError();
      if(!CustomSymbolCreate(dest, "Custom\\TDS", templ))
        {
         Log(StringFormat("  FAIL: CustomSymbolCreate(%s, template=%s) err=%d",
                          dest, templ, GetLastError()));
         FailListAppend(dest, "CustomSymbolCreate failed");
         return;
        }
      created = true;
      Log("  created " + dest + " (template=" + templ + ")");
     }
   if(!SymbolSelect(dest, true))
     {
      Log("  WARN: SymbolSelect(" + dest + ") failed err=" + (string)GetLastError());
     }
   int handle = FileOpen(csv_path, FILE_COMMON|FILE_READ|FILE_TXT|FILE_ANSI|FILE_SHARE_READ);
   if(handle == INVALID_HANDLE)
     {
      Log("  FAIL: cannot open " + csv_path + " err=" + (string)GetLastError());
      FailListAppend(dest, "csv unreadable: " + csv_path);
      return;
     }

   long t_last = (created || InpForceFullReimport) ? 0 : GetLastTickMsc(dest);
   bool incremental = (t_last > 0) && !InpForceFullReimport;
   double epsilon = EpsilonForDest(dest);

   if(incremental)
     {
      Log(StringFormat("  incremental: MT5 last_msc=%I64d  epsilon=%g", t_last, epsilon));
      if(!VerifyContinuity(dest, handle, t_last, epsilon))
        {
         Log("  SKIP: continuity verification failed — needs manual full reimport");
         FailListAppend(dest, "continuity mismatch");
         FileClose(handle);
         return;
        }
      long n = ImportTicks(dest, handle, t_last, false);
      if(n < 0) FailListAppend(dest, "ImportTicks (incremental) returned error");
      else      Log("  [OK] " + dest + " incremental +" + (string)n + " ticks");
     }
   else
     {
      Log("  full import (created=" + (string)created + ", force=" + (string)InpForceFullReimport + ")");
      long n = ImportTicks(dest, handle, 0, true);
      if(n < 0) FailListAppend(dest, "ImportTicks (full) returned error");
      else      Log("  [OK] " + dest + " full " + (string)n + " ticks");
     }
   FileClose(handle);
  }

//+------------------------------------------------------------------+
//|  Entry point                                                      |
//+------------------------------------------------------------------+
void OnStart()
  {
   OpenLog();
   Log("==== TDM_TickImporter start ====");
   Log("  mapping=" + InpMappingFile + "  only=" + InpOnlyDestination
       + "  forceFull=" + (string)InpForceFullReimport);

   // Use comma as the CSV delimiter — without this, FileReadString reads
   // entire lines (since MQL5's FILE_CSV defaults to TAB).
   int mh = FileOpen(InpMappingFile, FILE_COMMON|FILE_READ|FILE_CSV|FILE_ANSI|FILE_SHARE_READ, ',');
   if(mh == INVALID_HANDLE)
     {
      Log("FATAL: cannot open mapping file " + InpMappingFile + " err=" + (string)GetLastError());
      CloseLog();
      return;
     }

   int processed = 0, skipped = 0;
   while(!FileIsEnding(mh))
     {
      string dest  = FileReadString(mh);
      string templ = FileReadString(mh);
      string csv   = FileReadString(mh);
      if(StringLen(dest) == 0) break;
      if(StringLen(InpOnlyDestination) > 0 && dest != InpOnlyDestination)
        {
         skipped++;
         continue;
        }
      ProcessRow(dest, templ, csv);
      processed++;
     }
   FileClose(mh);
   Log(StringFormat("==== TDM_TickImporter done: processed=%d  skipped=%d ====", processed, skipped));
   CloseLog();
  }
//+------------------------------------------------------------------+
