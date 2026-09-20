//+------------------------------------------------------------------+
//|                                                      ExportM1.mq5 |
//|   Dumps M1 history to CSV so the strategy can be backtested and   |
//|   optimised outside MetaTrader, on the same broker data the       |
//|   expert will actually trade.                                     |
//|                                                                   |
//|   The per-bar spread column matters: it lets the backtest charge  |
//|   the real historical spread instead of a flat guess, which for   |
//|   an entry placed exactly on a narrow zone is the difference      |
//|   between a believable result and a fantasy.                      |
//|                                                                   |
//|   Output lands in <Data Folder>/MQL5/Files/<InpFile>.             |
//+------------------------------------------------------------------+
#property copyright "hayati63"
#property link      "https://github.com/hayati63/hayati"
#property version   "1.00"
#property script_show_inputs
#property description "Export M1 OHLCV + spread to CSV for offline backtesting."

input datetime InpFrom = D'2023.01.01 00:00';  // From
input datetime InpTo   = D'2026.01.01 00:00';  // To
input string   InpFile = "m1_export.csv";      // Output file name

void OnStart(void)
  {
   //--- make sure the terminal actually has the history before asking for it
   datetime probe[];
   CopyTime(_Symbol, PERIOD_M1, InpFrom, InpTo, probe);

   MqlRates r[];
   ArraySetAsSeries(r, false);
   int n = CopyRates(_Symbol, PERIOD_M1, InpFrom, InpTo, r);

   if(n <= 0)
     {
      PrintFormat("ExportM1: no M1 data for %s in that range (error %d). "
                  "Open an M1 chart of this symbol, scroll back to load history, then retry.",
                  _Symbol, GetLastError());
      return;
     }

   int h = FileOpen(InpFile, FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
   if(h == INVALID_HANDLE)
     {
      PrintFormat("ExportM1: cannot create %s (error %d)", InpFile, GetLastError());
      return;
     }

   FileWrite(h, "time", "open", "high", "low", "close", "tick_volume", "real_volume", "spread");

   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   for(int i = 0; i < n; i++)
      FileWrite(h,
                TimeToString(r[i].time, TIME_DATE | TIME_MINUTES | TIME_SECONDS),
                DoubleToString(r[i].open,  digits),
                DoubleToString(r[i].high,  digits),
                DoubleToString(r[i].low,   digits),
                DoubleToString(r[i].close, digits),
                (string)r[i].tick_volume,
                (string)r[i].real_volume,
                (string)r[i].spread);

   FileClose(h);

   PrintFormat("ExportM1: wrote %d M1 bars of %s (%s .. %s) to MQL5/Files/%s",
               n, _Symbol,
               TimeToString(r[0].time, TIME_DATE | TIME_MINUTES),
               TimeToString(r[n - 1].time, TIME_DATE | TIME_MINUTES),
               InpFile);
   PrintFormat("ExportM1: server time here is %s, UTC is %s - note the offset, the "
               "backtest needs it.",
               TimeToString(TimeCurrent(), TIME_DATE | TIME_MINUTES),
               TimeToString(TimeGMT(), TIME_DATE | TIME_MINUTES));
  }
//+------------------------------------------------------------------+
