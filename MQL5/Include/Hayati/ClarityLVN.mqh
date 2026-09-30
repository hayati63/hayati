//+------------------------------------------------------------------+
//|                                                    ClarityLVN.mqh |
//|   Port of "LVN Clarity Cascade" (Pine v5) — see                   |
//|   pinescript/lvn_clarity_cascade.pine                             |
//|                                                                   |
//|   Every profile is built from M1 candles inside one higher-TF     |
//|   candle's time window, with MIDPOINT BINNING: a candle's whole   |
//|   volume lands in the bucket its (H+L)/2 falls into. The row      |
//|   count is not fixed — it is searched from minRows upward and the |
//|   count with the highest "clarity" wins, where clarity is how far |
//|   the thinnest bucket sits below the average of the others.       |
//|                                                                   |
//|   The cascade then walks down the timeframes. Each step needs the |
//|   FIRST lower-TF candle inside the parent window whose own range  |
//|   fully CONTAINS the current zone. No containing candle ends the  |
//|   cascade — there is no "closest match" fallback.                 |
//+------------------------------------------------------------------+
#ifndef HAYATI_CLARITY_LVN_MQH
#define HAYATI_CLARITY_LVN_MQH

#include <Hayati/VolumeProfile.mqh>   // ENUM_VP_VOLUME_SOURCE

#define CL_MAX_STAGES 5

//--- one stage's low volume zone
struct SClarityZone
  {
   bool              valid;      // a zone was produced at all
   double            top;
   double            bottom;
   int               rows;       // winning row count
   double            clarity;    // best clarity, in percent
   bool              clear;      // clarity reached the threshold ("found" in Pine)
   datetime          from;       // window open
   datetime          to;         // window close
  };

//--- one rung of the cascade
struct SCascadeStage
  {
   ENUM_TIMEFRAMES   tf;
   datetime          bar_time;   // the candle this stage zoomed into
   SClarityZone      zone;
  };

//--- reset a zone to "nothing found"
void CL_ClearZone(SClarityZone &z)
  {
   z.valid   = false;
   z.top     = 0.0;
   z.bottom  = 0.0;
   z.rows    = 0;
   z.clarity = 0.0;
   z.clear   = false;
   z.from    = 0;
   z.to      = 0;
  }

//+------------------------------------------------------------------+
//| The cascade's timeframe chain. top_index 0 = Daily, matching the  |
//| Pine input: Daily, 4 Hour, 1 Hour, 15 Minute, 5 Minute.           |
//+------------------------------------------------------------------+
int CL_BuildChain(const int top_index, ENUM_TIMEFRAMES &tfs[], string &names[])
  {
   ENUM_TIMEFRAMES all[] = {PERIOD_D1, PERIOD_H4, PERIOD_H1, PERIOD_M15, PERIOD_M5};
   string          lbl[] = {"Daily",   "4H",      "1H",      "15m",      "5m"};

   int total = ArraySize(all);
   int start = top_index;
   if(start < 0)
      start = 0;
   if(start > total - 1)
      start = total - 1;

   int count = total - start;
   ArrayResize(tfs, count);
   ArrayResize(names, count);
   for(int i = 0; i < count; i++)
     {
      tfs[i]   = all[start + i];
      names[i] = lbl[start + i];
     }
   return(count);
  }

//+------------------------------------------------------------------+
//| Pick the volume field the way the rest of the project does        |
//+------------------------------------------------------------------+
bool CL_UseRealVolume(const MqlRates &r[], const int n, const ENUM_VP_VOLUME_SOURCE vsrc)
  {
   if(vsrc == VP_VOL_REAL)
      return(true);
   if(vsrc == VP_VOL_TICK)
      return(false);
   long sum = 0;
   for(int i = 0; i < n; i++)
      sum += r[i].real_volume;
   return(sum > 0);
  }

//+------------------------------------------------------------------+
//| The clarity search over the M1 candles in [from, to)              |
//|                                                                   |
//| Faithful to f_valleyClarity():                                    |
//|  - the range is the M1 extremes, not the parent candle's own      |
//|  - midpoint binning, whole volume into one bucket                 |
//|  - row counts tried in ascending order, stopping at the first one |
//|    to reach the threshold; when nothing reaches it, the best      |
//|    clarity over the whole sweep is reported and flagged unclear   |
//|  - ties on the thinnest bucket go to the LOWEST bucket, because   |
//|    array.indexof returns the first match                          |
//+------------------------------------------------------------------+
bool CL_ZoneFromM1(const string symbol, const datetime from, const datetime to,
                   const int min_rows, const int max_rows, const double gap_threshold,
                   const ENUM_VP_VOLUME_SOURCE vsrc, SClarityZone &z)
  {
   CL_ClearZone(z);
   z.from = from;
   z.to   = to;

   if(to <= from || min_rows < 2 || max_rows < min_rows)
      return(false);

   MqlRates m1[];
   ArraySetAsSeries(m1, false);
   int n = CopyRates(symbol, PERIOD_M1, from, to - 1, m1);
   if(n < 2)                 // Pine requires endIdx > startIdx, i.e. two M1 candles
      return(false);

   bool use_real = CL_UseRealVolume(m1, n, vsrc);

   double bar_high = m1[0].high;
   double bar_low  = m1[0].low;
   for(int i = 1; i < n; i++)
     {
      if(m1[i].high > bar_high)
         bar_high = m1[i].high;
      if(m1[i].low < bar_low)
         bar_low = m1[i].low;
     }
   if(bar_high <= bar_low)
      return(false);

   double best_clarity = -1.0;
   int    best_rows    = 0;
   int    best_idx     = -1;
   double best_step    = 0.0;
   bool   found        = false;

   double bins[];
   for(int rows = min_rows; rows <= max_rows && !found; rows++)
     {
      double step = (bar_high - bar_low) / rows;
      if(step <= 0.0)
         continue;

      ArrayResize(bins, rows);
      ArrayInitialize(bins, 0.0);

      for(int i = 0; i < n; i++)
        {
         double mid = (m1[i].high + m1[i].low) * 0.5;
         int    idx = (int)MathFloor((mid - bar_low) / step);
         if(idx < 0)
            idx = 0;
         if(idx > rows - 1)
            idx = rows - 1;
         bins[idx] += use_real ? (double)m1[i].real_volume : (double)m1[i].tick_volume;
        }

      int    min_idx = ArrayMinimum(bins, 0, rows);   // first minimum, i.e. lowest bucket
      double min_vol = bins[min_idx];
      double total   = 0.0;
      for(int i = 0; i < rows; i++)
         total += bins[i];

      double avg_other = (rows > 1) ? (total - min_vol) / (rows - 1) : min_vol;
      double clarity   = (avg_other > 0.0) ? (1.0 - min_vol / avg_other) * 100.0 : 0.0;

      if(clarity > best_clarity)
        {
         best_clarity = clarity;
         best_rows    = rows;
         best_idx     = min_idx;
         best_step    = step;
        }
      if(clarity >= gap_threshold)
         found = true;
     }

   if(best_idx < 0)
      return(false);

   z.bottom  = bar_low + best_idx * best_step;
   z.top     = z.bottom + best_step;
   z.rows    = best_rows;
   z.clarity = best_clarity;
   z.clear   = found;
   z.valid   = true;
   return(true);
  }

//+------------------------------------------------------------------+
//| Does this candle's range cover the whole zone?                    |
//+------------------------------------------------------------------+
bool CL_Contains(const MqlRates &r, const double z_top, const double z_bottom,
                 const bool body_only)
  {
   double cover_high = body_only ? MathMax(r.open, r.close) : r.high;
   double cover_low  = body_only ? MathMin(r.open, r.close) : r.low;
   return(cover_high >= z_top && cover_low <= z_bottom);
  }

//+------------------------------------------------------------------+
//| First candle of `tf` inside [win_from, win_to] that contains the  |
//| zone. Chronological — the first one wins, not the best fitting.   |
//+------------------------------------------------------------------+
bool CL_FindFirstContaining(const string symbol, const ENUM_TIMEFRAMES tf,
                            const datetime win_from, const datetime win_to,
                            const double z_top, const double z_bottom,
                            const bool body_only, datetime &out_time)
  {
   out_time = 0;

   MqlRates r[];
   ArraySetAsSeries(r, false);            // oldest first
   int n = CopyRates(symbol, tf, win_from, win_to - 1, r);
   if(n <= 0)
      return(false);

   int dur = PeriodSeconds(tf);
   for(int i = 0; i < n; i++)
     {
      if(r[i].time < win_from)
         continue;
      if(r[i].time + dur > win_to)        // the candle must close inside the parent
         continue;
      if(CL_Contains(r[i], z_top, z_bottom, body_only))
        {
         out_time = r[i].time;
         return(true);
        }
     }
   return(false);
  }

//+------------------------------------------------------------------+
//| Run the whole cascade for one closed top-stage candle.            |
//| Returns how many stages completed; the cascade only counts as     |
//| finished when the return value equals tf_count.                   |
//+------------------------------------------------------------------+
int CL_RunCascade(const string symbol,
                  const ENUM_TIMEFRAMES &tfs[], const int tf_count,
                  const datetime top_from, const datetime top_to,
                  const int min_rows, const int max_rows, const double gap_threshold,
                  const bool body_only, const ENUM_VP_VOLUME_SOURCE vsrc,
                  SCascadeStage &out[])
  {
   ArrayResize(out, tf_count);
   for(int i = 0; i < tf_count; i++)
     {
      out[i].tf       = tfs[i];
      out[i].bar_time = 0;
      CL_ClearZone(out[i].zone);
     }
   if(tf_count <= 0 || top_to <= top_from)
      return(0);

   SClarityZone zone;
   if(!CL_ZoneFromM1(symbol, top_from, top_to, min_rows, max_rows, gap_threshold, vsrc, zone))
      return(0);

   out[0].bar_time = top_from;
   out[0].zone     = zone;

   datetime win_from = top_from;
   datetime win_to   = top_to;

   for(int si = 1; si < tf_count; si++)
     {
      datetime found_time;
      if(!CL_FindFirstContaining(symbol, tfs[si], win_from, win_to,
                                 zone.top, zone.bottom, body_only, found_time))
         return(si);

      datetime child_to = found_time + PeriodSeconds(tfs[si]);

      SClarityZone child;
      if(!CL_ZoneFromM1(symbol, found_time, child_to, min_rows, max_rows,
                        gap_threshold, vsrc, child))
         return(si);

      out[si].bar_time = found_time;
      out[si].zone     = child;

      zone     = child;
      win_from = found_time;
      win_to   = child_to;
     }

   return(tf_count);
  }

#endif // HAYATI_CLARITY_LVN_MQH
