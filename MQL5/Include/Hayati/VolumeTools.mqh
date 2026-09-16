//+------------------------------------------------------------------+
//|                                                  VolumeTools.mqh |
//|   Vertical volume helpers: relative volume, spikes, delta proxy   |
//+------------------------------------------------------------------+
#ifndef HAYATI_VOLUME_TOOLS_MQH
#define HAYATI_VOLUME_TOOLS_MQH

#include <Hayati/VolumeProfile.mqh>

//+------------------------------------------------------------------+
//| Pull the chosen volume field for a run of bars (index 0 = newest) |
//+------------------------------------------------------------------+
bool VT_CopyVolumes(const string symbol, const ENUM_TIMEFRAMES tf,
                    const int shift, const int count,
                    const ENUM_VP_VOLUME_SOURCE vsrc,
                    double &out[])
  {
   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int copied = CopyRates(symbol, tf, shift, count, rates);
   if(copied <= 0)
      return(false);

   bool use_real = (vsrc == VP_VOL_REAL);
   if(vsrc == VP_VOL_AUTO)
     {
      long s = 0;
      for(int i = 0; i < copied; i++)
         s += rates[i].real_volume;
      use_real = (s > 0);
     }

   ArrayResize(out, copied);
   for(int i = 0; i < copied; i++)
      out[i] = use_real ? (double)rates[i].real_volume : (double)rates[i].tick_volume;
   return(true);
  }

//+------------------------------------------------------------------+
//| Average volume over `lookback` bars ending just before `shift`    |
//+------------------------------------------------------------------+
double VT_AverageVolume(const string symbol, const ENUM_TIMEFRAMES tf,
                        const int shift, const int lookback,
                        const ENUM_VP_VOLUME_SOURCE vsrc)
  {
   if(lookback < 1)
      return(0.0);
   double v[];
   if(!VT_CopyVolumes(symbol, tf, shift, lookback, vsrc, v))
      return(0.0);
   int n = ArraySize(v);
   if(n <= 0)
      return(0.0);
   double sum = 0.0;
   for(int i = 0; i < n; i++)
      sum += v[i];
   return(sum / (double)n);
  }

//+------------------------------------------------------------------+
//| Relative volume of the bar at `shift` vs the `lookback` bars      |
//| before it. 1.0 = average, 2.0 = twice the average.                |
//+------------------------------------------------------------------+
double VT_RelativeVolume(const string symbol, const ENUM_TIMEFRAMES tf,
                         const int shift, const int lookback,
                         const ENUM_VP_VOLUME_SOURCE vsrc)
  {
   double cur[];
   if(!VT_CopyVolumes(symbol, tf, shift, 1, vsrc, cur))
      return(0.0);
   if(ArraySize(cur) < 1 || cur[0] <= 0.0)
      return(0.0);

   double avg = VT_AverageVolume(symbol, tf, shift + 1, lookback, vsrc);
   if(avg <= 0.0)
      return(0.0);
   return(cur[0] / avg);
  }

//+------------------------------------------------------------------+
//| Buy/sell split of a bar's volume, estimated from where it closed  |
//| inside its own range. Returns delta = buy - sell.                 |
//+------------------------------------------------------------------+
double VT_BarDelta(const string symbol, const ENUM_TIMEFRAMES tf,
                   const int shift, const ENUM_VP_VOLUME_SOURCE vsrc)
  {
   MqlRates r[];
   ArraySetAsSeries(r, true);
   if(CopyRates(symbol, tf, shift, 1, r) < 1)
      return(0.0);

   bool use_real = (vsrc == VP_VOL_REAL) ||
                   (vsrc == VP_VOL_AUTO && r[0].real_volume > 0);
   double vol = use_real ? (double)r[0].real_volume : (double)r[0].tick_volume;

   double range = r[0].high - r[0].low;
   if(range <= 0.0)
      return(0.0);

   double buy  = vol * (r[0].close - r[0].low)  / range;
   double sell = vol * (r[0].high  - r[0].close) / range;
   return(buy - sell);
  }

//+------------------------------------------------------------------+
//| True when the bar at `shift` traded on at least `mult` times the  |
//| average volume of the bars before it.                             |
//+------------------------------------------------------------------+
bool VT_IsVolumeSpike(const string symbol, const ENUM_TIMEFRAMES tf,
                      const int shift, const int lookback,
                      const double mult, const ENUM_VP_VOLUME_SOURCE vsrc)
  {
   double rv = VT_RelativeVolume(symbol, tf, shift, lookback, vsrc);
   return(rv >= mult && rv > 0.0);
  }

//+------------------------------------------------------------------+
//| True when volume has dried up — used by rejection/fade setups     |
//| that want the approach into a node to lose participation.         |
//+------------------------------------------------------------------+
bool VT_IsVolumeDryUp(const string symbol, const ENUM_TIMEFRAMES tf,
                      const int shift, const int lookback,
                      const double mult, const ENUM_VP_VOLUME_SOURCE vsrc)
  {
   double rv = VT_RelativeVolume(symbol, tf, shift, lookback, vsrc);
   return(rv > 0.0 && rv <= mult);
  }

#endif // HAYATI_VOLUME_TOOLS_MQH
