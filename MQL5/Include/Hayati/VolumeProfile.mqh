//+------------------------------------------------------------------+
//|                                                VolumeProfile.mqh |
//|   Fixed Range Volume Profile (horizontal volume) engine for MT5   |
//|   POC / Value Area / HVN / LVN detection                          |
//+------------------------------------------------------------------+
#ifndef HAYATI_VOLUME_PROFILE_MQH
#define HAYATI_VOLUME_PROFILE_MQH

//--- which volume field feeds the profile
enum ENUM_VP_VOLUME_SOURCE
  {
   VP_VOL_AUTO = 0,   // Auto (real volume when the broker supplies it)
   VP_VOL_TICK = 1,   // Tick volume
   VP_VOL_REAL = 2    // Real volume
  };

//--- how a single bar's volume is spread across the price axis
enum ENUM_VP_DISTRIBUTION
  {
   VP_DIST_M1      = 0, // Refine with M1 bars (closest to TradingView)
   VP_DIST_UNIFORM = 1, // Uniform over the bar High-Low
   VP_DIST_CLOSE   = 2  // All of the bar's volume at its close
  };

//--- a single row of the horizontal histogram
struct SVPNode
  {
   int               bin;      // row index, 0 = lowest price
   double            price;    // row mid price
   double            low;      // row lower edge
   double            high;     // row upper edge
   double            volume;   // volume accumulated in the row
   double            ratio;    // volume / POC volume, 0..1
  };

//+------------------------------------------------------------------+
//| CVolumeProfile                                                   |
//+------------------------------------------------------------------+
class CVolumeProfile
  {
private:
   string            m_symbol;
   ENUM_TIMEFRAMES   m_tf;
   int               m_bins;
   double            m_bin_size;
   double            m_range_low;
   double            m_range_high;
   double            m_rows[];         // volume per row
   double            m_total_volume;
   datetime          m_from;
   datetime          m_to;
   bool              m_used_real;

   int               m_poc_bin;
   double            m_poc_price;
   double            m_poc_volume;
   double            m_vah;
   double            m_val;

   SVPNode           m_lvn[];
   SVPNode           m_hvn[];
   bool              m_valid;

   //--- map a price onto a row index, clamped to the profile
   int               PriceToBin(const double price) const
     {
      if(m_bin_size <= 0.0)
         return(-1);
      int idx = (int)MathFloor((price - m_range_low) / m_bin_size);
      if(idx < 0)
         idx = 0;
      if(idx > m_bins - 1)
         idx = m_bins - 1;
      return(idx);
     }

   //--- spread one bar's volume over the rows it touches
   void              AddRange(const double low, const double high, const double vol)
     {
      if(vol <= 0.0 || m_bin_size <= 0.0)
         return;
      if(high <= low)
        {
         int only = PriceToBin(low);
         if(only >= 0)
            m_rows[only] += vol;
         return;
        }
      int i0 = PriceToBin(low);
      int i1 = PriceToBin(high);
      if(i0 < 0 || i1 < 0 || i1 < i0)
         return;
      double span = high - low;
      for(int i = i0; i <= i1; i++)
        {
         double b_low  = m_range_low + i * m_bin_size;
         double b_high = b_low + m_bin_size;
         double ov     = MathMin(b_high, high) - MathMax(b_low, low);
         if(ov <= 0.0)
            continue;
         m_rows[i] += vol * (ov / span);
        }
     }

   //--- pick the volume field for one bar
   double            BarVolume(const MqlRates &r) const
     {
      if(m_used_real)
         return((double)r.real_volume);
      return((double)r.tick_volume);
     }

   //--- fill the rows from M1 data covering the whole range
   bool              DistributeM1(void)
     {
      MqlRates m1[];
      ArraySetAsSeries(m1, false);
      int copied = CopyRates(m_symbol, PERIOD_M1, m_from, m_to, m1);
      if(copied <= 0)
         return(false);
      for(int i = 0; i < copied; i++)
         AddRange(m1[i].low, m1[i].high, BarVolume(m1[i]));
      return(true);
     }

   //--- value area: expand out from the POC two rows at a time
   void              ComputeValueArea(const double va_percent)
     {
      m_vah = m_poc_price;
      m_val = m_poc_price;
      if(m_total_volume <= 0.0 || m_poc_bin < 0)
         return;

      double target = m_total_volume * (va_percent / 100.0);
      double acc    = m_rows[m_poc_bin];
      int    upper  = m_poc_bin;
      int    lower  = m_poc_bin;

      while(acc < target && (lower > 0 || upper < m_bins - 1))
        {
         double up_vol = -1.0;
         if(upper < m_bins - 1)
           {
            up_vol = m_rows[upper + 1];
            if(upper + 2 <= m_bins - 1)
               up_vol += m_rows[upper + 2];
           }
         double dn_vol = -1.0;
         if(lower > 0)
           {
            dn_vol = m_rows[lower - 1];
            if(lower - 2 >= 0)
               dn_vol += m_rows[lower - 2];
           }

         if(up_vol < 0.0 && dn_vol < 0.0)
            break;

         if(up_vol >= dn_vol)
           {
            int step = (upper + 2 <= m_bins - 1) ? 2 : 1;
            for(int k = 1; k <= step; k++)
               acc += m_rows[upper + k];
            upper += step;
           }
         else
           {
            int step = (lower - 2 >= 0) ? 2 : 1;
            for(int k = 1; k <= step; k++)
               acc += m_rows[lower - k];
            lower -= step;
           }
        }

      m_vah = m_range_low + (upper + 1) * m_bin_size;
      m_val = m_range_low + lower * m_bin_size;
     }

   //--- fill an SVPNode from a row index
   void              MakeNode(const int bin, SVPNode &n) const
     {
      n.bin    = bin;
      n.low    = m_range_low + bin * m_bin_size;
      n.high   = n.low + m_bin_size;
      n.price  = n.low + m_bin_size * 0.5;
      n.volume = m_rows[bin];
      n.ratio  = (m_poc_volume > 0.0) ? m_rows[bin] / m_poc_volume : 0.0;
     }

public:
                     CVolumeProfile(void) { Reset(); }
                    ~CVolumeProfile(void) {}

   void              Reset(void)
     {
      m_symbol       = _Symbol;
      m_tf           = PERIOD_CURRENT;
      m_bins         = 0;
      m_bin_size     = 0.0;
      m_range_low    = 0.0;
      m_range_high   = 0.0;
      m_total_volume = 0.0;
      m_from         = 0;
      m_to           = 0;
      m_used_real    = false;
      m_poc_bin      = -1;
      m_poc_price    = 0.0;
      m_poc_volume   = 0.0;
      m_vah          = 0.0;
      m_val          = 0.0;
      m_valid        = false;
      ArrayFree(m_rows);
      ArrayFree(m_lvn);
      ArrayFree(m_hvn);
     }

   //+---------------------------------------------------------------+
   //| Build the profile over `bars_count` bars ending at `start_shift`|
   //+---------------------------------------------------------------+
   bool              Build(const string symbol, const ENUM_TIMEFRAMES tf,
                           const int start_shift, const int bars_count,
                           const int bins,
                           const ENUM_VP_VOLUME_SOURCE vsrc,
                           const ENUM_VP_DISTRIBUTION dist,
                           const double va_percent = 70.0)
     {
      Reset();
      if(bins < 8 || bars_count < 3)
         return(false);

      MqlRates rates[];
      ArraySetAsSeries(rates, true);
      int copied = CopyRates(symbol, tf, start_shift, bars_count, rates);
      if(copied < 3)
         return(false);

      m_symbol = symbol;
      m_tf     = tf;
      m_bins   = bins;

      //--- decide which volume field to use
      if(vsrc == VP_VOL_REAL)
         m_used_real = true;
      else
         if(vsrc == VP_VOL_TICK)
            m_used_real = false;
         else
           {
            long real_sum = 0;
            for(int i = 0; i < copied; i++)
               real_sum += rates[i].real_volume;
            m_used_real = (real_sum > 0);
           }

      //--- price range of the window
      m_range_high = rates[0].high;
      m_range_low  = rates[0].low;
      for(int i = 1; i < copied; i++)
        {
         if(rates[i].high > m_range_high)
            m_range_high = rates[i].high;
         if(rates[i].low < m_range_low)
            m_range_low = rates[i].low;
        }
      if(m_range_high <= m_range_low)
         return(false);

      m_bin_size = (m_range_high - m_range_low) / (double)m_bins;
      if(m_bin_size <= 0.0)
         return(false);

      ArrayResize(m_rows, m_bins);
      ArrayInitialize(m_rows, 0.0);

      //--- time window: oldest bar open .. newest bar close
      m_from = rates[copied - 1].time;
      m_to   = rates[0].time + PeriodSeconds(tf) - 1;

      //--- distribute
      bool done = false;
      if(dist == VP_DIST_M1)
         done = DistributeM1();          // falls through to uniform if M1 missing

      if(!done)
        {
         for(int i = 0; i < copied; i++)
           {
            double v = BarVolume(rates[i]);
            if(dist == VP_DIST_CLOSE)
               AddRange(rates[i].close, rates[i].close, v);
            else
               AddRange(rates[i].low, rates[i].high, v);
           }
        }

      //--- POC and totals
      m_total_volume = 0.0;
      m_poc_bin      = 0;
      for(int i = 0; i < m_bins; i++)
        {
         m_total_volume += m_rows[i];
         if(m_rows[i] > m_rows[m_poc_bin])
            m_poc_bin = i;
        }
      if(m_total_volume <= 0.0)
         return(false);

      m_poc_volume = m_rows[m_poc_bin];
      m_poc_price  = m_range_low + (m_poc_bin + 0.5) * m_bin_size;

      ComputeValueArea(va_percent);

      m_valid = true;
      return(true);
     }

   //+---------------------------------------------------------------+
   //| Detect low / high volume nodes                                 |
   //|  lvn_ratio : row volume must be <= ratio * POC volume          |
   //|  hvn_ratio : row volume must be >= ratio * POC volume          |
   //|  window    : rows either side that must be beaten (valley/peak)|
   //+---------------------------------------------------------------+
   int               DetectNodes(const double lvn_ratio = 0.30,
                                 const double hvn_ratio = 0.70,
                                 const int    window    = 3)
     {
      ArrayFree(m_lvn);
      ArrayFree(m_hvn);
      if(!m_valid || m_poc_volume <= 0.0)
         return(0);

      int w = (window < 1) ? 1 : window;

      for(int i = w; i <= m_bins - 1 - w; i++)
        {
         double v = m_rows[i];

         //--- valley test
         if(v <= lvn_ratio * m_poc_volume)
           {
            bool is_min = true;
            for(int k = i - w; k <= i + w && is_min; k++)
              {
               if(k == i)
                  continue;
               if(m_rows[k] < v)
                  is_min = false;
              }
            //--- a genuine LVN has heavier volume on BOTH sides
            if(is_min)
              {
               bool heavier_above = false, heavier_below = false;
               for(int k = i + 1; k < m_bins; k++)
                  if(m_rows[k] > v * 1.5) { heavier_above = true; break; }
               for(int k = i - 1; k >= 0; k--)
                  if(m_rows[k] > v * 1.5) { heavier_below = true; break; }
               if(heavier_above && heavier_below)
                 {
                  int n = ArraySize(m_lvn);
                  ArrayResize(m_lvn, n + 1);
                  MakeNode(i, m_lvn[n]);
                 }
              }
           }

         //--- peak test
         if(v >= hvn_ratio * m_poc_volume)
           {
            bool is_max = true;
            for(int k = i - w; k <= i + w && is_max; k++)
              {
               if(k == i)
                  continue;
               if(m_rows[k] > v)
                  is_max = false;
              }
            if(is_max)
              {
               int n = ArraySize(m_hvn);
               ArrayResize(m_hvn, n + 1);
               MakeNode(i, m_hvn[n]);
              }
           }
        }

      MergeAdjacent(m_lvn, w, true);
      MergeAdjacent(m_hvn, w, false);
      return(ArraySize(m_lvn));
     }

   //--- collapse detections that sit within `w` rows of each other
   void              MergeAdjacent(SVPNode &arr[], const int w, const bool keep_lower)
     {
      int n = ArraySize(arr);
      if(n < 2)
         return;
      SVPNode out[];
      ArrayResize(out, 0);
      int i = 0;
      while(i < n)
        {
         int best = i;
         int j    = i + 1;
         while(j < n && (arr[j].bin - arr[j - 1].bin) <= w)
           {
            if(keep_lower ? (arr[j].volume < arr[best].volume)
                          : (arr[j].volume > arr[best].volume))
               best = j;
            j++;
           }
         int m = ArraySize(out);
         ArrayResize(out, m + 1);
         out[m] = arr[best];
         i = j;
        }
      ArrayFree(arr);
      ArrayCopy(arr, out);
     }

   //+---------------------------------------------------------------+
   //| Queries                                                        |
   //+---------------------------------------------------------------+
   bool              IsValid(void)      const { return(m_valid);        }
   double            POC(void)          const { return(m_poc_price);    }
   double            POCVolume(void)    const { return(m_poc_volume);   }
   double            VAH(void)          const { return(m_vah);          }
   double            VAL(void)          const { return(m_val);          }
   double            RangeHigh(void)    const { return(m_range_high);   }
   double            RangeLow(void)     const { return(m_range_low);    }
   double            BinSize(void)      const { return(m_bin_size);     }
   int               Bins(void)         const { return(m_bins);         }
   double            TotalVolume(void)  const { return(m_total_volume); }
   bool              UsedRealVolume(void) const { return(m_used_real);  }
   datetime          From(void)         const { return(m_from);         }
   datetime          To(void)           const { return(m_to);           }

   double            RowVolume(const int bin) const
     {
      if(bin < 0 || bin >= m_bins)
         return(0.0);
      return(m_rows[bin]);
     }

   int               LVNCount(void) { return(ArraySize(m_lvn)); }
   int               HVNCount(void) { return(ArraySize(m_hvn)); }

   bool              GetLVN(const int i, SVPNode &n)
     {
      if(i < 0 || i >= ArraySize(m_lvn))
         return(false);
      n = m_lvn[i];
      return(true);
     }

   bool              GetHVN(const int i, SVPNode &n)
     {
      if(i < 0 || i >= ArraySize(m_hvn))
         return(false);
      n = m_hvn[i];
      return(true);
     }

   //--- volume sitting at `price`, as a fraction of the POC row
   double            RatioAtPrice(const double price) const
     {
      if(!m_valid || m_poc_volume <= 0.0)
         return(0.0);
      int b = PriceToBin(price);
      if(b < 0)
         return(0.0);
      return(m_rows[b] / m_poc_volume);
     }

   //--- nearest node of either kind, in any direction
   bool              NearestLVN(const double price, SVPNode &out)
     {
      return(NearestIn(m_lvn, price, 0, out));
     }
   bool              NearestLVNAbove(const double price, SVPNode &out)
     {
      return(NearestIn(m_lvn, price, 1, out));
     }
   bool              NearestLVNBelow(const double price, SVPNode &out)
     {
      return(NearestIn(m_lvn, price, -1, out));
     }
   bool              NearestHVNAbove(const double price, SVPNode &out)
     {
      return(NearestIn(m_hvn, price, 1, out));
     }
   bool              NearestHVNBelow(const double price, SVPNode &out)
     {
      return(NearestIn(m_hvn, price, -1, out));
     }

   //--- dir: 0 = any side, 1 = strictly above, -1 = strictly below
   bool              NearestIn(const SVPNode &arr[], const double price,
                               const int dir, SVPNode &out)
     {
      int n = ArraySize(arr);
      if(n <= 0)
         return(false);
      int    best = -1;
      double best_d = 0.0;
      for(int i = 0; i < n; i++)
        {
         if(dir > 0 && arr[i].price <= price)
            continue;
         if(dir < 0 && arr[i].price >= price)
            continue;
         double d = MathAbs(arr[i].price - price);
         if(best < 0 || d < best_d)
           {
            best   = i;
            best_d = d;
           }
        }
      if(best < 0)
         return(false);
      out = arr[best];
      return(true);
     }
  };

#endif // HAYATI_VOLUME_PROFILE_MQH
