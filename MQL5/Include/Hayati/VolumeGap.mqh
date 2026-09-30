//+------------------------------------------------------------------+
//|                                                     VolumeGap.mqh |
//|   Primitives of "XAUUSD Vertical Volume Gap Cascade v3" (Pine v5) |
//|                                                                   |
//|   PARTIAL PORT. The Pine source arrived truncated — see           |
//|   pinescript/vertical_volume_gap_cascade_v3.PARTIAL.pine. What is |
//|   here are the self-contained pieces that the paste fully         |
//|   specified. The cascade body that consumes them is NOT here      |
//|   because its code was cut off.                                   |
//|                                                                   |
//|   Nothing in this strategy uses a horizontal volume profile. The  |
//|   zone at each stage is a whole candle's High-Low range, and the  |
//|   candle is picked by VERTICAL volume: a genuine local minimum,   |
//|   deepest one wins.                                               |
//+------------------------------------------------------------------+
#ifndef HAYATI_VOLUME_GAP_MQH
#define HAYATI_VOLUME_GAP_MQH

//--- one stage's zone: a candle's own range, not a profile row
struct SVGZone
  {
   bool              valid;
   double            top;
   double            bottom;
   datetime          from;
   datetime          to;
  };

void VG_ClearZone(SVGZone &z)
  {
   z.valid  = false;
   z.top    = 0.0;
   z.bottom = 0.0;
   z.from   = 0;
   z.to     = 0;
  }

//+------------------------------------------------------------------+
//| f_findVolumeGapByIndex: the deepest genuine local minimum of      |
//| vertical volume between sa and sb. Returns -1 when there is none. |
//|                                                                   |
//| Two details carried over deliberately:                            |
//|  - both comparisons are strict, so a flat pair is not a minimum   |
//|  - `lo` is clamped to 1 and `hi` to n-2, which means the candle   |
//|    at the very edge of the window is still compared against a     |
//|    neighbour OUTSIDE the window. That is what the Pine does.      |
//|  - ties on the deepest volume go to the EARLIEST candle, because  |
//|    the comparison is `<` and not `<=`                             |
//+------------------------------------------------------------------+
int VG_FindVolumeGap(const double &vol[], const int sa, const int sb)
  {
   int n  = ArraySize(vol);
   int lo = MathMax(sa, 1);
   int hi = MathMin(sb, n - 2);

   int    best_idx = -1;
   double best_vol = 1e18;

   for(int i = lo; i <= hi; i++)
     {
      double v0 = vol[i];
      double vl = vol[i - 1];
      double vr = vol[i + 1];
      if(v0 < vl && v0 < vr && v0 < best_vol)
        {
         best_vol = v0;
         best_idx = i;
        }
     }
   return(best_idx);
  }

//+------------------------------------------------------------------+
//| f_indexRange: first and last candle fully inside [from, to]       |
//+------------------------------------------------------------------+
bool VG_IndexRange(const MqlRates &r[], const datetime from, const datetime to,
                   const int duration, int &start_idx, int &end_idx)
  {
   start_idx = -1;
   end_idx   = -1;
   int n = ArraySize(r);
   for(int i = 0; i < n; i++)
     {
      datetime t  = r[i].time;
      datetime tc = r[i].time + duration;
      if(t >= from && tc <= to)
        {
         if(start_idx == -1)
            start_idx = i;
         end_idx = i;
        }
     }
   return(start_idx >= 0);
  }

//+------------------------------------------------------------------+
//| f_isPinBar: rejection wick at least twice the body, on the side   |
//| the bias needs. dir +1 wants a bullish pin, -1 a bearish one.     |
//+------------------------------------------------------------------+
bool VG_IsPinBar(const double o, const double h, const double l, const double c,
                 const int dir)
  {
   double body       = MathAbs(c - o);
   double upper_wick = h - MathMax(o, c);
   double lower_wick = MathMin(o, c) - l;

   bool is_bull = (body > 0.0 && lower_wick >= 2.0 * body && lower_wick > upper_wick);
   bool is_bear = (body > 0.0 && upper_wick >= 2.0 * body && upper_wick > lower_wick);

   if(dir == 1)
      return(is_bull);
   if(dir == -1)
      return(is_bear);
   return(false);
  }

//+------------------------------------------------------------------+
//| f_nearZonePinBar: a pin bar that approached the zone's near edge  |
//| without closing inside it. The proximity band is 30% of the       |
//| zone's own height, so wider zones tolerate a wider approach.      |
//+------------------------------------------------------------------+
bool VG_NearZonePinBar(const double z_top, const double z_bottom, const int dir,
                       const double o, const double h, const double l, const double c)
  {
   double band = (z_top - z_bottom) * 0.30;
   if(!VG_IsPinBar(o, h, l, c, dir))
      return(false);

   if(dir == 1)
      return(l >= z_bottom - band && l < z_bottom && c < z_bottom);
   if(dir == -1)
      return(h <= z_top + band && h > z_top && c > z_top);
   return(false);
  }

//+------------------------------------------------------------------+
//| f_zonesOverlap                                                   |
//+------------------------------------------------------------------+
bool VG_ZonesOverlap(const double top1, const double bot1,
                     const double top2, const double bot2)
  {
   return(bot1 <= top2 && bot2 <= top1);
  }

//+------------------------------------------------------------------+
//| Bias from the confirming candle's close: outside the zone fixes   |
//| the direction, inside it is ambiguous and hands over to the M15   |
//| wait. Returns +1, -1 or 0.                                        |
//+------------------------------------------------------------------+
int VG_ResolveDirection(const double conf_close, const double z_top, const double z_bottom)
  {
   if(conf_close > z_top)
      return(1);
   if(conf_close < z_bottom)
      return(-1);
   return(0);
  }

//+------------------------------------------------------------------+
//| Tehran time                                                       |
//|                                                                   |
//| Iran ran DST at UTC+4:30 until it was abolished in 2022; the last |
//| DST period ended on 21 September 2022. Since then Tehran is a     |
//| fixed UTC+3:30. Pine's hour(t, "Asia/Tehran") knows this history, |
//| so a backtest that reaches back before September 2022 needs it    |
//| too, otherwise the excluded hours land one hour off all summer.   |
//|                                                                   |
//| The DST window is approximated as 22 March .. 21 September, which |
//| is what Iran used; the Iranian calendar can move it by a day in   |
//| some years.                                                       |
//+------------------------------------------------------------------+
bool VG_TehranIsDST(const datetime utc)
  {
   MqlDateTime d;
   TimeToStruct(utc, d);
   if(d.year > 2022)
      return(false);
   if(d.year == 2022 && d.mon == 9 && d.day > 21)
      return(false);
   if(d.mon > 3 && d.mon < 9)
      return(true);
   if(d.mon == 3)
      return(d.day >= 22);
   if(d.mon == 9)
      return(d.day <= 21);
   return(false);
  }

int VG_TehranOffsetSeconds(const datetime utc)
  {
   return(VG_TehranIsDST(utc) ? (4 * 3600 + 1800) : (3 * 3600 + 1800));
  }

datetime VG_ToTehran(const datetime utc)
  {
   return(utc + VG_TehranOffsetSeconds(utc));
  }

//+------------------------------------------------------------------+
//| The two thin-liquidity hours at the daily session boundary: an H1 |
//| candle opening at 23:30 or 00:30 Tehran. Pass the candle's open   |
//| in UTC, not in broker server time.                                |
//|                                                                   |
//| With Tehran at UTC+3:30 those are the H1 candles opening at 20:00 |
//| and 21:00 UTC; under the old DST they were 19:00 and 20:00 UTC.   |
//+------------------------------------------------------------------+
bool VG_IsExcludedTehranHour(const datetime bar_open_utc)
  {
   MqlDateTime d;
   TimeToStruct(VG_ToTehran(bar_open_utc), d);
   if(d.min != 30)
      return(false);
   return(d.hour == 23 || d.hour == 0);
  }

//+------------------------------------------------------------------+
//| Grading                                                           |
//|                                                                   |
//| Implemented from the v3 header's description, NOT from code — the |
//| scoring block itself was in the truncated part of the paste.      |
//|                                                                   |
//|   zones containing the close: 0 -> A, 1 -> B, 2 -> C, 3+ -> D     |
//|   confluence: one point per overlapping PAIR of zones, plus one   |
//|   bonus when the close sits outside every zone                    |
//+------------------------------------------------------------------+
int VG_ContainCount(const SVGZone &zones[], const int count, const double price)
  {
   int n = 0;
   for(int i = 0; i < count; i++)
     {
      if(!zones[i].valid)
         continue;
      if(price >= zones[i].bottom && price <= zones[i].top)
         n++;
     }
   return(n);
  }

string VG_Grade(const int contain_count)
  {
   if(contain_count <= 0)
      return("A");
   if(contain_count == 1)
      return("B");
   if(contain_count == 2)
      return("C");
   return("D");
  }

int VG_ConfluenceScore(const SVGZone &zones[], const int count, const double close_price)
  {
   int score = 0;
   for(int i = 0; i < count; i++)
     {
      if(!zones[i].valid)
         continue;
      for(int j = i + 1; j < count; j++)
        {
         if(!zones[j].valid)
            continue;
         if(VG_ZonesOverlap(zones[i].top, zones[i].bottom, zones[j].top, zones[j].bottom))
            score++;
        }
     }
   if(VG_ContainCount(zones, count, close_price) == 0)
      score++;
   return(score);
  }

#endif // HAYATI_VOLUME_GAP_MQH
