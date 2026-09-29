//+------------------------------------------------------------------+
//|                                               ExportBarsCSV.mq5  |
//|  Exports OHLC + tick volume + spread of the chart symbol to      |
//|  MQL5\Files (or Common\Files) so the Python research in          |
//|  research/ can be re-run on your own broker's data.              |
//+------------------------------------------------------------------+
#property copyright   "hayati63"
#property version     "1.00"
#property script_show_inputs

input ENUM_TIMEFRAMES InpTF       = PERIOD_M1;               // Timeframe to export (M1 recommended)
input datetime        InpFrom     = D'2018.01.01 00:00';     // From (server time)
input datetime        InpTo       = D'2030.01.01 00:00';     // To (server time)
input bool            InpCommon   = true;                    // Write to Common\Files (else MQL5\Files)

void OnStart()
  {
   string tf = StringSubstr(EnumToString(InpTF), 7);          // "PERIOD_M1" -> "M1"
   string fn = StringFormat("%s_%s_%s_%s.csv", _Symbol, tf,
                            TimeToString(InpFrom, TIME_DATE), TimeToString(InpTo, TIME_DATE));
   StringReplace(fn, ".", "");
   StringReplace(fn, "csv", ".csv");
   int flags = FILE_WRITE | FILE_CSV | FILE_ANSI | (InpCommon ? FILE_COMMON : 0);
   int fh = FileOpen(fn, flags, ',');
   if(fh == INVALID_HANDLE)
     {
      PrintFormat("Cannot open %s (error %d)", fn, GetLastError());
      return;
     }
   FileWrite(fh, "time", "open", "high", "low", "close", "tick_volume", "spread");
   //--- export in yearly chunks so very long M1 histories do not exhaust memory
   long total = 0;
   datetime from = InpFrom;
   while(from < InpTo && !IsStopped())
     {
      MqlDateTime d;
      TimeToStruct(from, d);
      d.year += 1;
      d.mon = 1;
      d.day = 1;
      d.hour = 0;
      d.min = 0;
      d.sec = 0;
      datetime to = StructToTime(d);
      if(to > InpTo)
         to = InpTo;
      MqlRates r[];
      int n = CopyRates(_Symbol, InpTF, from, to - 1, r);
      if(n < 0)
        {
         PrintFormat("CopyRates failed for %s..%s (error %d) - open the chart and scroll back to load history, then retry",
                     TimeToString(from), TimeToString(to), GetLastError());
        }
      for(int i = 0; i < n; i++)
         FileWrite(fh, TimeToString(r[i].time, TIME_DATE | TIME_MINUTES), DoubleToString(r[i].open, _Digits),
                   DoubleToString(r[i].high, _Digits), DoubleToString(r[i].low, _Digits),
                   DoubleToString(r[i].close, _Digits), IntegerToString(r[i].tick_volume), IntegerToString(r[i].spread));
      total += (n > 0 ? n : 0);
      from = to;
     }
   FileClose(fh);
   PrintFormat("Exported %I64d bars of %s %s to %s\\%s", total, _Symbol, tf,
               InpCommon ? "Common\\Files" : "MQL5\\Files", fn);
  }
//+------------------------------------------------------------------+
