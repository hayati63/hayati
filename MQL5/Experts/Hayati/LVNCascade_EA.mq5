//+------------------------------------------------------------------+
//|                                                 LVNCascade_EA.mq5 |
//|   MT5 port of "LVN Clarity Cascade — Automated v1" (Pine v5)      |
//|                                                                   |
//|   ATTACH TO A 1-MINUTE CHART, exactly like the Pine version.      |
//|                                                                   |
//|   Once per closed top-stage candle the cascade runs: build the    |
//|   clarity profile from that candle's M1 data, find the first      |
//|   lower-TF candle inside it whose range contains the zone, build  |
//|   that candle's profile, and so on down to 5m. The surviving zone |
//|   is then watched. Direction comes only from how price arrives:   |
//|   from above -> BUY, from below -> SELL.                          |
//|                                                                   |
//|   The Pine script is an indicator and defines no exits. Every     |
//|   stop and target below is an ADDITION, not a translation — see   |
//|   docs/STRATEGY.md.                                               |
//+------------------------------------------------------------------+
#property copyright "hayati63"
#property link      "https://github.com/hayati63/hayati"
#property version   "1.00"
#property description "LVN Clarity Cascade - multi-timeframe LVN cascade, reaction entries. Attach to M1."

#include <Trade/Trade.mqh>
#include <Trade/PositionInfo.mqh>
#include <Hayati/ClarityLVN.mqh>

//+------------------------------------------------------------------+
enum ENUM_TOP_STAGE
  {
   TOP_DAILY = 0, // Daily
   TOP_H4    = 1, // 4 Hour
   TOP_H1    = 2, // 1 Hour
   TOP_M15   = 3, // 15 Minute
   TOP_M5    = 4  // 5 Minute
  };

enum ENUM_COVERAGE
  {
   COV_FULL = 0, // Full candle (wicks included)
   COV_BODY = 1  // Body only
  };

enum ENUM_CL_SL
  {
   CLSL_ZONE   = 0, // Beyond the far side of the zone
   CLSL_ATR    = 1, // ATR multiple
   CLSL_POINTS = 2  // Fixed points
  };

enum ENUM_CL_TP
  {
   CLTP_RR     = 0, // Risk multiple
   CLTP_ZONE   = 1, // Zone height multiple
   CLTP_POINTS = 2  // Fixed points
  };

//+------------------------------------------------------------------+
input group "=== Cascade (matches the Pine inputs) ==="
input ENUM_TOP_STAGE        InpTopStage     = TOP_DAILY;   // Start the cascade at this timeframe
input int                   InpMinRows      = 3;           // Minimum rows
input int                   InpMaxRows      = 8;           // Maximum rows
input double                InpGapThreshold = 40.0;        // Minimum valley clarity %
input ENUM_COVERAGE         InpCoverage     = COV_FULL;    // Stage transition coverage
input ENUM_VP_VOLUME_SOURCE InpVolumeSource = VP_VOL_AUTO; // Volume source

input group "=== Entry ==="
input bool                  InpIntrabar     = true;        // Trigger intrabar (as the Pine does)
input int                   InpZoneMaxAgeMin= 0;           // Drop an untouched zone after N minutes (0 = never)
input int                   InpMaxSpreadPts = 30;          // Max spread in points (0 = off)

input group "=== Exits (NOT from the Pine script) ==="
input ENUM_CL_SL            InpSLMode       = CLSL_ZONE;   // Stop loss mode
input double                InpSLZoneBuffer = 0.25;        // SL: zone heights beyond the far side
input double                InpSLATR        = 1.5;         // SL: ATR multiple
input int                   InpSLPoints     = 300;         // SL: fixed points
input ENUM_CL_TP            InpTPMode       = CLTP_RR;     // Take profit mode
input double                InpTPRR         = 2.0;         // TP: risk multiple
input double                InpTPZoneMult   = 3.0;         // TP: zone height multiple
input int                   InpTPPoints     = 600;         // TP: fixed points
input double                InpBreakEvenR   = 0.0;         // Break-even at this R (0 = off)
input double                InpTrailATR     = 0.0;         // ATR trailing multiple (0 = off)
input int                   InpATRPeriod    = 14;          // ATR period

input group "=== Risk ==="
input double                InpRiskPercent  = 1.0;         // Risk per trade (% of balance)
input double                InpFixedLots    = 0.0;         // Fixed lots (>0 overrides risk %)
input int                   InpMaxPositions = 1;           // Max simultaneous positions

input group "=== Misc ==="
input long                  InpMagic        = 630002;      // Magic number
input int                   InpSlippage     = 20;          // Slippage (points)
input bool                  InpDrawZones    = true;        // Draw cascade zones on the chart
input int                   InpHistoryDraw  = 20;          // Also draw the last N past cascades (0 = off)
input bool                  InpVerbose      = false;       // Log every cascade run

//+------------------------------------------------------------------+
CTrade        g_trade;
CPositionInfo g_pos;

ENUM_TIMEFRAMES g_tfs[];
string          g_names[];
int             g_stage_count = 0;

datetime g_last_top_bar = 0;
int      g_atr_handle   = INVALID_HANDLE;
double   g_point        = 0.0;
int      g_digits       = 0;

//--- the single live zone, exactly as the Pine keeps one watch box
bool     g_history_drawn = false;
bool     g_zone_active  = false;
double   g_zone_top     = 0.0;
double   g_zone_bottom  = 0.0;
datetime g_zone_set_at  = 0;
int      g_zone_serial  = 0;

#define ZPFX "CLC_"

//+------------------------------------------------------------------+
int OnInit(void)
  {
   if(_Period != PERIOD_M1)
      Print("LVNCascade: WARNING - this expert is built for a 1-minute chart, "
            "the Pine script it ports runs on M1. Current chart is ", EnumToString(_Period));

   if(InpMinRows < 2 || InpMaxRows < InpMinRows)
     {
      Print("LVNCascade: need 2 <= min rows <= max rows");
      return(INIT_PARAMETERS_INCORRECT);
     }
   if(InpGapThreshold <= 0.0 || InpGapThreshold >= 100.0)
     {
      Print("LVNCascade: clarity threshold must be between 0 and 100");
      return(INIT_PARAMETERS_INCORRECT);
     }
   if(InpRiskPercent <= 0.0 && InpFixedLots <= 0.0)
     {
      Print("LVNCascade: set either a risk percent or fixed lots");
      return(INIT_PARAMETERS_INCORRECT);
     }

   g_stage_count = CL_BuildChain((int)InpTopStage, g_tfs, g_names);
   if(g_stage_count < 1)
      return(INIT_FAILED);

   g_point  = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   g_digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);

   g_atr_handle = iATR(_Symbol, _Period, InpATRPeriod);
   if(g_atr_handle == INVALID_HANDLE)
     {
      Print("LVNCascade: cannot create the ATR handle");
      return(INIT_FAILED);
     }

   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetDeviationInPoints(InpSlippage);
   g_trade.SetTypeFillingBySymbol(_Symbol);

   string chain = g_names[0];
   for(int i = 1; i < g_stage_count; i++)
      chain += " -> " + g_names[i];
   Print("LVNCascade: cascade chain ", chain);

   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   if(g_atr_handle != INVALID_HANDLE)
      IndicatorRelease(g_atr_handle);
   ObjectsDeleteAll(0, ZPFX);
  }

//+------------------------------------------------------------------+
void OnTick(void)
  {
   if(!g_history_drawn)
     {
      g_history_drawn = true;
      if(InpDrawZones && InpHistoryDraw > 0 && !MQLInfoInteger(MQL_OPTIMIZATION))
         DrawHistory();
     }

   ManageOpenPositions();
   CheckTopStageClose();
   CheckZoneTouch();
  }

//+------------------------------------------------------------------+
//| Replay past cascades for the chart only. Purely visual — it never |
//| touches the live zone, so nothing here can open a trade.          |
//+------------------------------------------------------------------+
void DrawHistory(void)
  {
   SCascadeStage stages[];
   int drawn = 0;

   for(int k = InpHistoryDraw; k >= 1; k--)
     {
      datetime from = iTime(_Symbol, g_tfs[0], k);
      datetime to   = iTime(_Symbol, g_tfs[0], k - 1);
      if(from <= 0 || to <= from)
         continue;

      int done = CL_RunCascade(_Symbol, g_tfs, g_stage_count, from, to,
                               InpMinRows, InpMaxRows, InpGapThreshold,
                               InpCoverage == COV_BODY, InpVolumeSource, stages);
      if(done <= 0)
         continue;

      DrawStages(stages, done, -k);
      drawn++;
     }
   PrintFormat("LVNCascade: drew %d past cascade(s) of the last %d %s candles",
               drawn, InpHistoryDraw, g_names[0]);
  }

//+------------------------------------------------------------------+
//| Run the cascade once, when a top-stage candle has just closed     |
//+------------------------------------------------------------------+
void CheckTopStageClose(void)
  {
   datetime cur = iTime(_Symbol, g_tfs[0], 0);
   if(cur <= 0 || cur == g_last_top_bar)
      return;

   datetime prev = g_last_top_bar;
   g_last_top_bar = cur;
   if(prev == 0)                    // first sight of the chart, nothing closed yet
      return;

   datetime top_from = iTime(_Symbol, g_tfs[0], 1);
   if(top_from <= 0)
      return;

   SCascadeStage stages[];
   int done = CL_RunCascade(_Symbol, g_tfs, g_stage_count, top_from, cur,
                            InpMinRows, InpMaxRows, InpGapThreshold,
                            InpCoverage == COV_BODY, InpVolumeSource, stages);

   if(InpVerbose)
      PrintFormat("LVNCascade: %s -> %d/%d stages", TimeToString(top_from), done, g_stage_count);

   if(InpDrawZones && !MQLInfoInteger(MQL_OPTIMIZATION))
      DrawStages(stages, done, g_zone_serial + 1);

   //--- a cascade that stops early leaves the previous zone live, as the Pine does
   if(done < g_stage_count)
      return;

   g_zone_top    = stages[g_stage_count - 1].zone.top;
   g_zone_bottom = stages[g_stage_count - 1].zone.bottom;
   g_zone_active = true;
   g_zone_set_at = cur;
   g_zone_serial++;

   if(InpVerbose)
      PrintFormat("LVNCascade: watching zone %s - %s (%d rows, clarity %.1f%%)",
                  DoubleToString(g_zone_bottom, g_digits),
                  DoubleToString(g_zone_top, g_digits),
                  stages[g_stage_count - 1].zone.rows,
                  stages[g_stage_count - 1].zone.clarity);
  }

//+------------------------------------------------------------------+
//| Watch the live zone and take the reaction trade                   |
//+------------------------------------------------------------------+
void CheckZoneTouch(void)
  {
   if(!g_zone_active)
      return;

   //--- optional expiry, off by default to stay faithful to the Pine
   if(InpZoneMaxAgeMin > 0 &&
      TimeCurrent() - g_zone_set_at > (datetime)(InpZoneMaxAgeMin * 60))
     {
      g_zone_active = false;
      return;
     }

   if(CountOwnPositions() >= InpMaxPositions)
      return;
   if(InpMaxSpreadPts > 0 && SymbolInfoInteger(_Symbol, SYMBOL_SPREAD) > InpMaxSpreadPts)
      return;

   //--- the Pine checks the live candle against the PREVIOUS candle's close
   int shift = InpIntrabar ? 0 : 1;
   double h  = iHigh(_Symbol, PERIOD_M1, shift);
   double l  = iLow(_Symbol, PERIOD_M1, shift);
   double cp = iClose(_Symbol, PERIOD_M1, shift + 1);
   if(h <= 0.0 || l <= 0.0 || cp <= 0.0)
      return;

   bool in_zone = (h >= g_zone_bottom && l <= g_zone_top);
   if(!in_zone)
      return;

   bool from_above = (cp > g_zone_top);
   bool from_below = (cp < g_zone_bottom);
   if(!from_above && !from_below)
      return;                      // already inside the zone, no direction to read

   //--- the zone is consumed either way, matching finalResolved
   g_zone_active = false;
   OpenTrade(from_above);
  }

//+------------------------------------------------------------------+
//| Entry. from_above -> BUY (price fell into the zone), else SELL.   |
//+------------------------------------------------------------------+
void OpenTrade(const bool is_long)
  {
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double entry = is_long ? ask : bid;
   if(entry <= 0.0)
      return;

   double zone_h = g_zone_top - g_zone_bottom;
   if(zone_h <= 0.0)
      return;

   double min_stop = (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * g_point;
   double atr      = ATR();

   //--- stop loss
   double sl;
   if(InpSLMode == CLSL_ZONE)
      sl = is_long ? (g_zone_bottom - zone_h * InpSLZoneBuffer)
                   : (g_zone_top    + zone_h * InpSLZoneBuffer);
   else
      if(InpSLMode == CLSL_ATR && atr > 0.0)
         sl = is_long ? (entry - atr * InpSLATR) : (entry + atr * InpSLATR);
      else
         sl = is_long ? (entry - InpSLPoints * g_point) : (entry + InpSLPoints * g_point);

   //--- a zone stop can land the wrong side of a gapped entry
   if((is_long && sl >= entry) || (!is_long && sl <= entry))
      sl = is_long ? (entry - InpSLPoints * g_point) : (entry + InpSLPoints * g_point);

   double risk = MathAbs(entry - sl);
   if(risk < min_stop)
     {
      risk = min_stop + 2 * g_point;
      sl   = is_long ? (entry - risk) : (entry + risk);
     }
   if(risk <= 0.0)
      return;

   //--- take profit
   double tp;
   if(InpTPMode == CLTP_RR)
      tp = is_long ? (entry + risk * InpTPRR) : (entry - risk * InpTPRR);
   else
      if(InpTPMode == CLTP_ZONE)
         tp = is_long ? (entry + zone_h * InpTPZoneMult) : (entry - zone_h * InpTPZoneMult);
      else
         tp = is_long ? (entry + InpTPPoints * g_point) : (entry - InpTPPoints * g_point);

   if(MathAbs(tp - entry) < min_stop)
      tp = is_long ? (entry + risk * InpTPRR) : (entry - risk * InpTPRR);

   double lots = CalcLots(risk);
   if(lots <= 0.0)
      return;

   string tag = StringFormat("LVN#%d %s", g_zone_serial, is_long ? "from above" : "from below");
   bool ok = is_long
             ? g_trade.Buy(lots, _Symbol, 0.0, NormalizeDouble(sl, g_digits), NormalizeDouble(tp, g_digits), tag)
             : g_trade.Sell(lots, _Symbol, 0.0, NormalizeDouble(sl, g_digits), NormalizeDouble(tp, g_digits), tag);
   if(!ok)
      PrintFormat("LVNCascade: order failed (%d) %s", g_trade.ResultRetcode(),
                  g_trade.ResultRetcodeDescription());
   else
      if(InpDrawZones && !MQLInfoInteger(MQL_OPTIMIZATION))
         DrawArrow(is_long);
  }

//+------------------------------------------------------------------+
double CalcLots(const double sl_distance)
  {
   double vmin  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double vstep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(vstep <= 0.0)
      return(0.0);

   double lots;
   if(InpFixedLots > 0.0)
      lots = InpFixedLots;
   else
     {
      if(sl_distance <= 0.0)
         return(0.0);
      double tick_value = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
      double tick_size  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
      if(tick_value <= 0.0 || tick_size <= 0.0)
         return(0.0);
      double loss_per_lot = (sl_distance / tick_size) * tick_value;
      if(loss_per_lot <= 0.0)
         return(0.0);
      lots = AccountInfoDouble(ACCOUNT_BALANCE) * InpRiskPercent / 100.0 / loss_per_lot;
     }

   double v = MathFloor(lots / vstep) * vstep;
   if(v < vmin)
      v = vmin;
   if(v > vmax)
      v = vmax;
   return(NormalizeDouble(v, 2));
  }

//+------------------------------------------------------------------+
void ManageOpenPositions(void)
  {
   if(InpBreakEvenR <= 0.0 && InpTrailATR <= 0.0)
      return;

   double atr      = ATR();
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

      if(InpBreakEvenR > 0.0 && sl != 0.0)
        {
         double r = MathAbs(entry - sl);
         double moved = is_long ? (cur - entry) : (entry - cur);
         if(r > 0.0 && moved >= r * InpBreakEvenR)
           {
            double be = is_long ? (entry + min_stop) : (entry - min_stop);
            if(is_long ? (be > new_sl) : (be < new_sl))
               new_sl = be;
           }
        }

      if(InpTrailATR > 0.0 && atr > 0.0)
        {
         double trail = is_long ? (cur - atr * InpTrailATR) : (cur + atr * InpTrailATR);
         if(is_long ? (trail > new_sl) : (trail < new_sl && new_sl != 0.0))
            new_sl = trail;
        }

      if(new_sl == sl)
         continue;
      if(is_long && new_sl >= cur - min_stop)
         continue;
      if(!is_long && new_sl <= cur + min_stop)
         continue;

      g_trade.PositionModify(g_pos.Ticket(), NormalizeDouble(new_sl, g_digits), tp);
     }
  }

//+------------------------------------------------------------------+
double ATR(void)
  {
   double buf[];
   if(CopyBuffer(g_atr_handle, 0, 1, 1, buf) < 1)
      return(0.0);
   return(buf[0]);
  }

int CountOwnPositions(void)
  {
   int c = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!g_pos.SelectByIndex(i))
         continue;
      if(g_pos.Symbol() == _Symbol && g_pos.Magic() == InpMagic)
         c++;
     }
   return(c);
  }

//+------------------------------------------------------------------+
//| Chart drawing                                                    |
//+------------------------------------------------------------------+
void DrawStages(const SCascadeStage &stages[], const int done, const int tag)
  {
   color palette[] = {clrTomato, clrOrange, clrMediumSeaGreen, clrDarkTurquoise, clrMediumPurple};

   for(int i = 0; i < done; i++)
     {
      if(!stages[i].zone.valid)
         continue;
      string id = StringFormat("%sZ%d_%d", ZPFX, tag, i);
      color  c  = stages[i].zone.clear
                  ? palette[MathMin(i, ArraySize(palette) - 1)]
                  : clrGold;                       // unclear valley, as the Pine warns
      ObjectCreate(0, id, OBJ_RECTANGLE, 0,
                   stages[i].zone.from, stages[i].zone.top,
                   stages[i].zone.to,   stages[i].zone.bottom);
      ObjectSetInteger(0, id, OBJPROP_COLOR, c);
      ObjectSetInteger(0, id, OBJPROP_FILL, true);
      ObjectSetInteger(0, id, OBJPROP_BACK, true);
      ObjectSetInteger(0, id, OBJPROP_SELECTABLE, false);
      ObjectSetString(0, id, OBJPROP_TOOLTIP,
                      StringFormat("%s LVN  %d rows  clarity %.1f%%",
                                   g_names[i], stages[i].zone.rows, stages[i].zone.clarity));
     }
   ChartRedraw(0);
  }

void DrawArrow(const bool is_long)
  {
   string id = StringFormat("%sSIG_%d", ZPFX, g_zone_serial);
   double p  = is_long ? iLow(_Symbol, PERIOD_M1, 0) : iHigh(_Symbol, PERIOD_M1, 0);
   ObjectCreate(0, id, is_long ? OBJ_ARROW_BUY : OBJ_ARROW_SELL, 0, TimeCurrent(), p);
   ObjectSetInteger(0, id, OBJPROP_COLOR, is_long ? clrLime : clrRed);
   ObjectSetInteger(0, id, OBJPROP_SELECTABLE, false);
   ChartRedraw(0);
  }
//+------------------------------------------------------------------+
