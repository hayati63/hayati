//+------------------------------------------------------------------+
//|                                                      VPFR_LVN.mq5 |
//|   Draws the Fixed Range Volume Profile the EA trades from, so the |
//|   rows, POC, value area and nodes can be eyeballed against the    |
//|   same range on TradingView before any backtest is trusted.       |
//+------------------------------------------------------------------+
#property copyright "hayati63"
#property link      "https://github.com/hayati63/hayati"
#property version   "1.00"
#property description "Fixed Range Volume Profile with POC, Value Area, HVN and LVN."
#property indicator_chart_window
#property indicator_buffers 0
#property indicator_plots   0

#include <Hayati/VolumeProfile.mqh>

input group "=== Range ==="
input int                    InpProfileBars  = 200;         // Fixed range: number of bars
input int                    InpProfileShift = 2;           // Range ends this many bars back
input int                    InpProfileRows  = 120;         // Rows (price bins)
input double                 InpValueAreaPct = 70.0;        // Value area %
input ENUM_VP_VOLUME_SOURCE  InpVolumeSource = VP_VOL_AUTO; // Volume source
input ENUM_VP_DISTRIBUTION   InpDistribution = VP_DIST_M1;  // Volume distribution

input group "=== Nodes ==="
input double                 InpLVNRatio     = 0.30;        // LVN: row volume <= ratio * POC
input double                 InpHVNRatio     = 0.70;        // HVN: row volume >= ratio * POC
input int                    InpNodeWindow   = 3;           // Rows each side a node must beat

input group "=== Drawing ==="
input int                    InpHistoWidth   = 60;          // Histogram width (bars)
input bool                   InpDrawRows     = true;        // Draw the row histogram
input bool                   InpDrawNodes    = true;        // Draw LVN / HVN lines
input color                  InpColorRow     = clrSteelBlue;      // Row (outside value area)
input color                  InpColorVA      = clrCornflowerBlue; // Row (inside value area)
input color                  InpColorPOC     = clrRed;            // POC
input color                  InpColorLVN     = clrOrange;         // LVN
input color                  InpColorHVN     = clrMediumSeaGreen; // HVN

#define PFX "VPFR_"

CVolumeProfile g_vp;
datetime       g_last_bar = 0;

//+------------------------------------------------------------------+
int OnInit(void)
  {
   if(InpProfileBars < 20 || InpProfileRows < 8)
     {
      Print("VPFR_LVN: profile bars must be >= 20 and rows >= 8");
      return(INIT_PARAMETERS_INCORRECT);
     }
   IndicatorSetString(INDICATOR_SHORTNAME,
                      StringFormat("VPFR/LVN (%d bars, %d rows)", InpProfileBars, InpProfileRows));
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   ObjectsDeleteAll(0, PFX);
   ChartRedraw(0);
  }

//+------------------------------------------------------------------+
int OnCalculate(const int rates_total, const int prev_calculated,
                const datetime &time[], const double &open[],
                const double &high[], const double &low[], const double &close[],
                const long &tick_volume[], const long &volume[], const int &spread[])
  {
   if(rates_total < InpProfileBars + InpProfileShift + 2)
      return(rates_total);

   datetime t0 = iTime(_Symbol, _Period, 0);
   if(t0 == g_last_bar && prev_calculated > 0)
      return(rates_total);
   g_last_bar = t0;

   if(!g_vp.Build(_Symbol, _Period, InpProfileShift, InpProfileBars,
                  InpProfileRows, InpVolumeSource, InpDistribution, InpValueAreaPct))
      return(rates_total);

   g_vp.DetectNodes(InpLVNRatio, InpHVNRatio, InpNodeWindow);
   Redraw();
   return(rates_total);
  }

//+------------------------------------------------------------------+
//| Drawing                                                          |
//+------------------------------------------------------------------+
void Redraw(void)
  {
   ObjectsDeleteAll(0, PFX);

   datetime anchor = iTime(_Symbol, _Period, InpProfileShift + InpProfileBars - 1);
   if(anchor <= 0)
      return;

   int      secs     = PeriodSeconds(_Period);
   datetime range_to = iTime(_Symbol, _Period, InpProfileShift) + secs;

   //--- the histogram never extends past the range it describes
   int    max_bars = MathMin(InpHistoWidth, InpProfileBars);
   double poc_vol  = g_vp.POCVolume();

   if(InpDrawRows && poc_vol > 0.0)
     {
      double vah = g_vp.VAH();
      double val = g_vp.VAL();

      for(int i = 0; i < g_vp.Bins(); i++)
        {
         double vol = g_vp.RowVolume(i);
         if(vol <= 0.0)
            continue;

         double lo = g_vp.RangeLow() + i * g_vp.BinSize();
         double hi = lo + g_vp.BinSize();
         double mid = (lo + hi) * 0.5;

         int      bars  = (int)MathRound((vol / poc_vol) * max_bars);
         if(bars < 1)
            bars = 1;
         datetime right = anchor + (datetime)(bars * secs);

         color clr = InpColorRow;
         if(mid >= val && mid <= vah)
            clr = InpColorVA;
         if(MathAbs(mid - g_vp.POC()) < g_vp.BinSize() * 0.5)
            clr = InpColorPOC;

         string id = StringFormat("%sROW_%d", PFX, i);
         ObjectCreate(0, id, OBJ_RECTANGLE, 0, anchor, lo, right, hi);
         ObjectSetInteger(0, id, OBJPROP_COLOR, clr);
         ObjectSetInteger(0, id, OBJPROP_FILL, true);
         ObjectSetInteger(0, id, OBJPROP_BACK, true);
         ObjectSetInteger(0, id, OBJPROP_SELECTABLE, false);
        }
     }

   //--- POC / value area, spanning the whole range
   HLineSegment("POC", g_vp.POC(), anchor, range_to, InpColorPOC, STYLE_SOLID, 2);
   HLineSegment("VAH", g_vp.VAH(), anchor, range_to, InpColorVA, STYLE_DOT, 1);
   HLineSegment("VAL", g_vp.VAL(), anchor, range_to, InpColorVA, STYLE_DOT, 1);

   //--- nodes, extended to the right so they can be traded against
   if(InpDrawNodes)
     {
      datetime far = iTime(_Symbol, _Period, 0) + (datetime)(secs * 10);
      SVPNode n;
      for(int i = 0; i < g_vp.LVNCount(); i++)
         if(g_vp.GetLVN(i, n))
            HLineSegment(StringFormat("LVN_%d", i), n.price, anchor, far,
                         InpColorLVN, STYLE_DASH, 1);

      for(int i = 0; i < g_vp.HVNCount(); i++)
         if(g_vp.GetHVN(i, n))
            HLineSegment(StringFormat("HVN_%d", i), n.price, anchor, far,
                         InpColorHVN, STYLE_DASHDOT, 1);
     }

   Comment(StringFormat("VPFR: %s volume | rows %d | POC %s | VAH %s | VAL %s | LVN %d | HVN %d",
                        g_vp.UsedRealVolume() ? "real" : "tick",
                        g_vp.Bins(),
                        DoubleToString(g_vp.POC(), _Digits),
                        DoubleToString(g_vp.VAH(), _Digits),
                        DoubleToString(g_vp.VAL(), _Digits),
                        g_vp.LVNCount(), g_vp.HVNCount()));

   ChartRedraw(0);
  }

//+------------------------------------------------------------------+
void HLineSegment(const string name, const double price,
                  const datetime t1, const datetime t2,
                  const color clr, const ENUM_LINE_STYLE style, const int width)
  {
   string id = PFX + name;
   ObjectCreate(0, id, OBJ_TREND, 0, t1, price, t2, price);
   ObjectSetInteger(0, id, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, id, OBJPROP_STYLE, style);
   ObjectSetInteger(0, id, OBJPROP_WIDTH, width);
   ObjectSetInteger(0, id, OBJPROP_RAY_RIGHT, false);
   ObjectSetInteger(0, id, OBJPROP_BACK, false);
   ObjectSetInteger(0, id, OBJPROP_SELECTABLE, false);
   ObjectSetString(0, id, OBJPROP_TOOLTIP, StringFormat("%s %s", name, DoubleToString(price, _Digits)));
  }
//+------------------------------------------------------------------+
