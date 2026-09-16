//+------------------------------------------------------------------+
//|                                                   VPFR_LVN_EA.mq5 |
//|   Fixed Range Volume Profile / LVN strategy                       |
//|                                                                   |
//|   NOTE: written before the original Pine Script was available and |
//|   it is NOT the LVN Clarity Cascade strategy — see                |
//|   MQL5/Experts/Hayati/LVNCascade_EA.mq5 for that. Kept because the |
//|   profile engine behind it is generic and may serve the second    |
//|   strategy, but nothing here was validated against your rules.    |
//|                                                                   |
//|   Horizontal volume  -> the profile, its POC, value area and the   |
//|                         low/high volume nodes carved out of it.    |
//|   Vertical volume    -> per-bar participation, used to confirm     |
//|                         that a node is being broken or defended.   |
//+------------------------------------------------------------------+
#property copyright "hayati63"
#property link      "https://github.com/hayati63/hayati"
#property version   "1.00"
#property description "Fixed Range Volume Profile + LVN entries, with vertical-volume confirmation."

#include <Trade/Trade.mqh>
#include <Trade/PositionInfo.mqh>
#include <Hayati/VolumeProfile.mqh>
#include <Hayati/VolumeTools.mqh>

//+------------------------------------------------------------------+
//| Modes                                                            |
//+------------------------------------------------------------------+
enum ENUM_ENTRY_MODE
  {
   ENTRY_BREAKOUT  = 0, // Breakout - trade through the low-volume gap
   ENTRY_REJECTION = 1, // Rejection - fade the node back toward the POC
   ENTRY_BOTH      = 2  // Both
  };

enum ENUM_SL_MODE
  {
   SL_NODE   = 0, // Beyond the signal node
   SL_ATR    = 1, // ATR multiple
   SL_POINTS = 2  // Fixed points
  };

enum ENUM_TP_MODE
  {
   TP_NEXT_HVN = 0, // Next high-volume node in the trade direction
   TP_POC      = 1, // Back to the POC
   TP_RR       = 2  // Risk multiple
  };

enum ENUM_TREND_FILTER
  {
   TREND_OFF   = 0, // Off
   TREND_WITH  = 1, // Only trade with the EMA slope/side
   TREND_AGAINST = 2 // Only trade against it (mean reversion)
  };

//+------------------------------------------------------------------+
//| Inputs                                                           |
//+------------------------------------------------------------------+
input group "=== Volume Profile (horizontal volume) ==="
input int                    InpProfileBars     = 200;            // Fixed range: number of bars
input int                    InpProfileShift    = 2;              // Range ends this many bars back
input int                    InpProfileRows     = 120;            // Rows (price bins)
input double                 InpValueAreaPct    = 70.0;           // Value area %
input ENUM_VP_VOLUME_SOURCE  InpVolumeSource    = VP_VOL_AUTO;    // Volume source
input ENUM_VP_DISTRIBUTION   InpDistribution    = VP_DIST_M1;     // Volume distribution
input int                    InpRebuildEveryBar = 1;              // Rebuild profile every N bars

input group "=== Node detection (LVN / HVN) ==="
input double                 InpLVNRatio        = 0.30;           // LVN: row volume <= ratio * POC volume
input double                 InpHVNRatio        = 0.70;           // HVN: row volume >= ratio * POC volume
input int                    InpNodeWindow      = 3;              // Rows each side a node must beat

input group "=== Entry ==="
input ENUM_ENTRY_MODE        InpEntryMode       = ENTRY_BREAKOUT; // Entry mode
input double                 InpBreakoutRVOL    = 1.50;           // Breakout: min relative volume
input double                 InpRejectionRVOL   = 0.90;           // Rejection: max relative volume
input int                    InpRVOLLookback    = 20;             // Bars for the volume average
input double                 InpNodeBufferATR   = 0.10;           // Node buffer, in ATR

input group "=== Filters ==="
input ENUM_TREND_FILTER      InpTrendFilter     = TREND_OFF;      // Trend filter
input int                    InpTrendEMA        = 100;            // Trend EMA period
input bool                   InpUseSession      = false;          // Restrict trading hours
input int                    InpSessionStart    = 8;              // Session start hour (server)
input int                    InpSessionEnd      = 20;             // Session end hour (server)
input int                    InpMaxSpreadPoints = 30;             // Max spread (points, 0 = off)

input group "=== Risk & exits ==="
input double                 InpRiskPercent     = 1.0;            // Risk per trade (% of balance)
input double                 InpFixedLots       = 0.0;            // Fixed lots (>0 overrides risk %)
input ENUM_SL_MODE           InpSLMode          = SL_NODE;        // Stop loss mode
input double                 InpSLATR           = 1.5;            // SL: ATR multiple
input int                    InpSLPoints        = 300;            // SL: fixed points
input ENUM_TP_MODE           InpTPMode          = TP_NEXT_HVN;    // Take profit mode
input double                 InpTPRR            = 2.0;            // TP: risk multiple
input double                 InpBreakEvenR      = 1.0;            // Move to break-even at this R (0 = off)
input double                 InpTrailATR        = 0.0;            // Trailing stop, ATR multiple (0 = off)
input int                    InpATRPeriod       = 14;             // ATR period
input int                    InpMaxPositions    = 1;              // Max simultaneous positions

input group "=== Misc ==="
input long                   InpMagic           = 630001;         // Magic number
input int                    InpSlippage        = 20;             // Slippage (points)
input bool                   InpShowLevels      = true;           // Draw levels on the chart

//+------------------------------------------------------------------+
//| Globals                                                          |
//+------------------------------------------------------------------+
CTrade          g_trade;
CPositionInfo   g_pos;
CVolumeProfile  g_vp;

int      g_atr_handle = INVALID_HANDLE;
int      g_ema_handle = INVALID_HANDLE;
datetime g_last_bar   = 0;
int      g_bars_since = 0;
double   g_point      = 0.0;
int      g_digits     = 0;

#define OBJ_PREFIX "HVP_"

//+------------------------------------------------------------------+
//| OnInit                                                           |
//+------------------------------------------------------------------+
int OnInit(void)
  {
   if(InpProfileBars < 20 || InpProfileRows < 8)
     {
      Print("VPFR_LVN: profile bars must be >= 20 and rows >= 8");
      return(INIT_PARAMETERS_INCORRECT);
     }
   if(InpValueAreaPct <= 0.0 || InpValueAreaPct >= 100.0)
     {
      Print("VPFR_LVN: value area % must be between 0 and 100");
      return(INIT_PARAMETERS_INCORRECT);
     }
   if(InpLVNRatio <= 0.0 || InpLVNRatio >= InpHVNRatio)
     {
      Print("VPFR_LVN: need 0 < LVN ratio < HVN ratio");
      return(INIT_PARAMETERS_INCORRECT);
     }
   if(InpRiskPercent <= 0.0 && InpFixedLots <= 0.0)
     {
      Print("VPFR_LVN: set either a risk percent or fixed lots");
      return(INIT_PARAMETERS_INCORRECT);
     }

   g_point  = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   g_digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);

   g_atr_handle = iATR(_Symbol, _Period, InpATRPeriod);
   if(g_atr_handle == INVALID_HANDLE)
     {
      Print("VPFR_LVN: cannot create the ATR handle");
      return(INIT_FAILED);
     }

   if(InpTrendFilter != TREND_OFF)
     {
      g_ema_handle = iMA(_Symbol, _Period, InpTrendEMA, 0, MODE_EMA, PRICE_CLOSE);
      if(g_ema_handle == INVALID_HANDLE)
        {
         Print("VPFR_LVN: cannot create the EMA handle");
         return(INIT_FAILED);
        }
     }

   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetDeviationInPoints(InpSlippage);
   g_trade.SetTypeFillingBySymbol(_Symbol);
   g_trade.SetAsyncMode(false);

   RebuildProfile();
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| OnDeinit                                                         |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   if(g_atr_handle != INVALID_HANDLE)
      IndicatorRelease(g_atr_handle);
   if(g_ema_handle != INVALID_HANDLE)
      IndicatorRelease(g_ema_handle);
   ObjectsDeleteAll(0, OBJ_PREFIX);
  }

//+------------------------------------------------------------------+
//| OnTick                                                           |
//+------------------------------------------------------------------+
void OnTick(void)
  {
   ManageOpenPositions();

   if(!IsNewBar())
      return;

   g_bars_since++;
   if(g_bars_since >= MathMax(1, InpRebuildEveryBar) || !g_vp.IsValid())
     {
      RebuildProfile();
      g_bars_since = 0;
     }

   if(!g_vp.IsValid() || g_vp.LVNCount() == 0)
      return;
   if(CountOwnPositions() >= InpMaxPositions)
      return;
   if(!PassesSpreadFilter() || !PassesSessionFilter())
      return;

   CheckForSignal();
  }

//+------------------------------------------------------------------+
//| Rebuild the fixed-range profile and its nodes                    |
//+------------------------------------------------------------------+
void RebuildProfile(void)
  {
   bool ok = g_vp.Build(_Symbol, _Period, InpProfileShift, InpProfileBars,
                        InpProfileRows, InpVolumeSource, InpDistribution,
                        InpValueAreaPct);
   if(!ok)
     {
      Print("VPFR_LVN: profile build failed (not enough history?)");
      return;
     }
   g_vp.DetectNodes(InpLVNRatio, InpHVNRatio, InpNodeWindow);

   if(InpShowLevels && !MQLInfoInteger(MQL_OPTIMIZATION))
      DrawLevels();
  }

//+------------------------------------------------------------------+
//| Signal search on the last closed bar                             |
//+------------------------------------------------------------------+
void CheckForSignal(void)
  {
   double c1 = iClose(_Symbol, _Period, 1);
   double c2 = iClose(_Symbol, _Period, 2);
   double o1 = iOpen(_Symbol, _Period, 1);
   double h1 = iHigh(_Symbol, _Period, 1);
   double l1 = iLow(_Symbol, _Period, 1);
   if(c1 <= 0.0 || c2 <= 0.0)
      return;

   double atr = ATR();
   if(atr <= 0.0)
      return;
   double buffer = atr * InpNodeBufferATR;

   double rvol = VT_RelativeVolume(_Symbol, _Period, 1, InpRVOLLookback, InpVolumeSource);

   SVPNode node;

   //--- breakout: the bar closed clean through a low-volume pocket
   if(InpEntryMode == ENTRY_BREAKOUT || InpEntryMode == ENTRY_BOTH)
     {
      if(rvol >= InpBreakoutRVOL)
        {
         //--- upward break
         if(FindCrossedLVN(c2, c1, true, node) && c1 > node.high)
           {
            if(TrendAllows(true, c1))
               OpenTrade(true, node, atr, buffer, "LVN breakout up");
            return;
           }
         //--- downward break
         if(FindCrossedLVN(c2, c1, false, node) && c1 < node.low)
           {
            if(TrendAllows(false, c1))
               OpenTrade(false, node, atr, buffer, "LVN breakout down");
            return;
           }
        }
     }

   //--- rejection: the bar probed the pocket and closed back out of it
   if(InpEntryMode == ENTRY_REJECTION || InpEntryMode == ENTRY_BOTH)
     {
      if(rvol > 0.0 && rvol <= InpRejectionRVOL)
        {
         //--- probed down into a node below, closed back above it -> long
         if(g_vp.NearestLVNBelow(c1, node))
           {
            if(l1 <= node.high && c1 > node.high && c1 > o1 && g_vp.POC() > c1)
              {
               if(TrendAllows(true, c1))
                  OpenTrade(true, node, atr, buffer, "LVN rejection up");
               return;
              }
           }
         //--- probed up into a node above, closed back below it -> short
         if(g_vp.NearestLVNAbove(c1, node))
           {
            if(h1 >= node.low && c1 < node.low && c1 < o1 && g_vp.POC() < c1)
              {
               if(TrendAllows(false, c1))
                  OpenTrade(false, node, atr, buffer, "LVN rejection down");
               return;
              }
           }
        }
     }
  }

//+------------------------------------------------------------------+
//| Find an LVN that price closed through between `from` and `to`    |
//+------------------------------------------------------------------+
bool FindCrossedLVN(const double from, const double to, const bool upward,
                    SVPNode &out)
  {
   int n = g_vp.LVNCount();
   if(n <= 0)
      return(false);

   int    best = -1;
   double best_d = 0.0;
   SVPNode node;

   for(int i = 0; i < n; i++)
     {
      if(!g_vp.GetLVN(i, node))
         continue;
      bool crossed = upward ? (from <= node.low && to > node.high)
                            : (from >= node.high && to < node.low);
      if(!crossed)
         continue;
      //--- keep the node closest to where price ended up
      double d = MathAbs(node.price - to);
      if(best < 0 || d < best_d)
        {
         best   = i;
         best_d = d;
         out    = node;
        }
     }
   return(best >= 0);
  }

//+------------------------------------------------------------------+
//| Trend filter                                                     |
//+------------------------------------------------------------------+
bool TrendAllows(const bool is_long, const double price)
  {
   if(InpTrendFilter == TREND_OFF || g_ema_handle == INVALID_HANDLE)
      return(true);

   double ema[];
   if(CopyBuffer(g_ema_handle, 0, 1, 1, ema) < 1)
      return(true);

   bool above = (price > ema[0]);
   if(InpTrendFilter == TREND_WITH)
      return(is_long ? above : !above);
   return(is_long ? !above : above);
  }

//+------------------------------------------------------------------+
//| Open a position                                                  |
//+------------------------------------------------------------------+
void OpenTrade(const bool is_long, const SVPNode &node, const double atr,
               const double buffer, const string tag)
  {
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double entry = is_long ? ask : bid;
   if(entry <= 0.0)
      return;

   //--- stop loss
   double sl = 0.0;
   if(InpSLMode == SL_NODE)
      sl = is_long ? (node.low - buffer) : (node.high + buffer);
   else
      if(InpSLMode == SL_ATR)
         sl = is_long ? (entry - atr * InpSLATR) : (entry + atr * InpSLATR);
      else
         sl = is_long ? (entry - InpSLPoints * g_point)
                      : (entry + InpSLPoints * g_point);

   double risk_dist = MathAbs(entry - sl);
   if(risk_dist <= 0.0)
      return;

   //--- respect the broker's stop level
   double min_stop = (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * g_point;
   if(risk_dist < min_stop)
     {
      risk_dist = min_stop + 2 * g_point;
      sl = is_long ? (entry - risk_dist) : (entry + risk_dist);
     }

   //--- take profit
   double tp = 0.0;
   SVPNode target;
   if(InpTPMode == TP_NEXT_HVN)
     {
      bool found = is_long ? g_vp.NearestHVNAbove(entry, target)
                           : g_vp.NearestHVNBelow(entry, target);
      if(found)
         tp = target.price;
      else
         tp = is_long ? (entry + risk_dist * InpTPRR) : (entry - risk_dist * InpTPRR);
     }
   else
      if(InpTPMode == TP_POC)
        {
         double poc = g_vp.POC();
         bool usable = is_long ? (poc > entry + min_stop) : (poc < entry - min_stop);
         tp = usable ? poc
                     : (is_long ? entry + risk_dist * InpTPRR : entry - risk_dist * InpTPRR);
        }
      else
         tp = is_long ? (entry + risk_dist * InpTPRR) : (entry - risk_dist * InpTPRR);

   //--- a target that sits the wrong side of entry is no target at all
   if((is_long && tp <= entry) || (!is_long && tp >= entry))
      tp = is_long ? (entry + risk_dist * InpTPRR) : (entry - risk_dist * InpTPRR);

   double lots = CalcLots(risk_dist);
   if(lots <= 0.0)
      return;

   sl = NormalizeDouble(sl, g_digits);
   tp = NormalizeDouble(tp, g_digits);

   bool ok = is_long ? g_trade.Buy(lots, _Symbol, 0.0, sl, tp, tag)
                     : g_trade.Sell(lots, _Symbol, 0.0, sl, tp, tag);
   if(!ok)
      PrintFormat("VPFR_LVN: order failed (%d) %s", g_trade.ResultRetcode(),
                  g_trade.ResultRetcodeDescription());
  }

//+------------------------------------------------------------------+
//| Position size from the money risked over the stop distance       |
//+------------------------------------------------------------------+
double CalcLots(const double sl_distance)
  {
   double vmin  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double vstep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);

   if(InpFixedLots > 0.0)
      return(NormalizeLots(InpFixedLots, vmin, vmax, vstep));

   if(sl_distance <= 0.0)
      return(0.0);

   double tick_value = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_size  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tick_value <= 0.0 || tick_size <= 0.0)
      return(0.0);

   double loss_per_lot = (sl_distance / tick_size) * tick_value;
   if(loss_per_lot <= 0.0)
      return(0.0);

   double risk_money = AccountInfoDouble(ACCOUNT_BALANCE) * InpRiskPercent / 100.0;
   double lots = risk_money / loss_per_lot;

   return(NormalizeLots(lots, vmin, vmax, vstep));
  }

double NormalizeLots(const double lots, const double vmin, const double vmax,
                     const double vstep)
  {
   if(vstep <= 0.0)
      return(0.0);
   double v = MathFloor(lots / vstep) * vstep;
   if(v < vmin)
      v = vmin;
   if(v > vmax)
      v = vmax;
   return(NormalizeDouble(v, 2));
  }

//+------------------------------------------------------------------+
//| Break-even and trailing                                          |
//+------------------------------------------------------------------+
void ManageOpenPositions(void)
  {
   if(InpBreakEvenR <= 0.0 && InpTrailATR <= 0.0)
      return;

   double atr = ATR();
   double min_stop = (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * g_point;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!g_pos.SelectByIndex(i))
         continue;
      if(g_pos.Symbol() != _Symbol || g_pos.Magic() != InpMagic)
         continue;

      bool   is_long = (g_pos.PositionType() == POSITION_TYPE_BUY);
      double entry   = g_pos.PriceOpen();
      double sl      = g_pos.StopLoss();
      double tp      = g_pos.TakeProfit();
      double cur     = is_long ? SymbolInfoDouble(_Symbol, SYMBOL_BID)
                               : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double new_sl  = sl;

      //--- break-even
      if(InpBreakEvenR > 0.0 && sl != 0.0)
        {
         double risk = MathAbs(entry - sl);
         if(risk > 0.0)
           {
            double moved = is_long ? (cur - entry) : (entry - cur);
            if(moved >= risk * InpBreakEvenR)
              {
               double be = is_long ? (entry + min_stop) : (entry - min_stop);
               if(is_long ? (be > new_sl) : (be < new_sl))
                  new_sl = be;
              }
           }
        }

      //--- ATR trailing
      if(InpTrailATR > 0.0 && atr > 0.0)
        {
         double trail = is_long ? (cur - atr * InpTrailATR) : (cur + atr * InpTrailATR);
         if(is_long ? (trail > new_sl) : (trail < new_sl && new_sl != 0.0))
            new_sl = trail;
        }

      if(new_sl == sl)
         continue;
      //--- never move the stop to the wrong side of the market
      if(is_long && new_sl >= cur - min_stop)
         continue;
      if(!is_long && new_sl <= cur + min_stop)
         continue;

      g_trade.PositionModify(g_pos.Ticket(), NormalizeDouble(new_sl, g_digits), tp);
     }
  }

//+------------------------------------------------------------------+
//| Helpers                                                          |
//+------------------------------------------------------------------+
double ATR(void)
  {
   double buf[];
   if(CopyBuffer(g_atr_handle, 0, 1, 1, buf) < 1)
      return(0.0);
   return(buf[0]);
  }

bool IsNewBar(void)
  {
   datetime t = iTime(_Symbol, _Period, 0);
   if(t == g_last_bar)
      return(false);
   g_last_bar = t;
   return(true);
  }

int CountOwnPositions(void)
  {
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!g_pos.SelectByIndex(i))
         continue;
      if(g_pos.Symbol() == _Symbol && g_pos.Magic() == InpMagic)
         count++;
     }
   return(count);
  }

bool PassesSpreadFilter(void)
  {
   if(InpMaxSpreadPoints <= 0)
      return(true);
   long spread = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   return(spread <= InpMaxSpreadPoints);
  }

bool PassesSessionFilter(void)
  {
   if(!InpUseSession)
      return(true);
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   if(InpSessionStart <= InpSessionEnd)
      return(dt.hour >= InpSessionStart && dt.hour < InpSessionEnd);
   //--- window wraps past midnight
   return(dt.hour >= InpSessionStart || dt.hour < InpSessionEnd);
  }

//+------------------------------------------------------------------+
//| Chart levels                                                     |
//+------------------------------------------------------------------+
void DrawLevel(const string name, const double price, const color clr,
               const ENUM_LINE_STYLE style, const int width)
  {
   string id = OBJ_PREFIX + name;
   if(ObjectFind(0, id) < 0)
      ObjectCreate(0, id, OBJ_HLINE, 0, 0, price);
   ObjectSetDouble(0, id, OBJPROP_PRICE, price);
   ObjectSetInteger(0, id, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, id, OBJPROP_STYLE, style);
   ObjectSetInteger(0, id, OBJPROP_WIDTH, width);
   ObjectSetInteger(0, id, OBJPROP_BACK, true);
   ObjectSetInteger(0, id, OBJPROP_SELECTABLE, false);
   ObjectSetString(0, id, OBJPROP_TOOLTIP, name);
  }

void DrawLevels(void)
  {
   ObjectsDeleteAll(0, OBJ_PREFIX);
   if(!g_vp.IsValid())
      return;

   DrawLevel("POC", g_vp.POC(), clrRed,       STYLE_SOLID, 2);
   DrawLevel("VAH", g_vp.VAH(), clrDodgerBlue, STYLE_DOT,  1);
   DrawLevel("VAL", g_vp.VAL(), clrDodgerBlue, STYLE_DOT,  1);

   SVPNode n;
   for(int i = 0; i < g_vp.LVNCount(); i++)
      if(g_vp.GetLVN(i, n))
         DrawLevel(StringFormat("LVN_%d", i), n.price, clrOrange, STYLE_DASH, 1);

   for(int i = 0; i < g_vp.HVNCount(); i++)
      if(g_vp.GetHVN(i, n))
         DrawLevel(StringFormat("HVN_%d", i), n.price, clrMediumSeaGreen, STYLE_DASHDOT, 1);

   ChartRedraw(0);
  }
//+------------------------------------------------------------------+
