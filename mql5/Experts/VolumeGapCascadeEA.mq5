//+------------------------------------------------------------------+
//|                                          VolumeGapCascadeEA.mq5  |
//|        XAUUSD Vertical Volume Gap Cascade  —  MT5 Expert Advisor |
//|                                                                  |
//|  Port of the TradingView indicator "Vertical Volume Gap Cascade  |
//|  v3" to a tradable, optimisable MT5 EA:                          |
//|   1) top-TF volume gap: vol[c-1] < vol[c-2] and < vol[c]         |
//|   2) bias from the confirm candle close (above / below the box); |
//|      closes inside -> wait up to N closes of the next-lower TF   |
//|   3) H1 top only: skip gap candles at 23:30 / 00:30 Tehran       |
//|   4) cascade: deepest local volume minimum one TF lower inside   |
//|      the box window, down to M5 and finally M1                   |
//|   5) entries: limit orders at any zone and/or market entries on  |
//|      a reaction (pin bar near the box, rejection close)          |
//|  Research, results and settings: docs/REPORT_fa.md               |
//+------------------------------------------------------------------+
#property copyright   "hayati63"
#property version     "1.00"
#property description "Vertical Volume Gap Cascade (Pine v3 port) for XAUUSD."
#property description "Attach to any chart of the symbol; all timeframes are read internally."

#include <Trade\Trade.mqh>

//--- enumerations ---------------------------------------------------
enum ENUM_VGC_TOP
  {
   VGC_TOP_D1  = 0, // D1  (D1>H4>H1>M15>M5>M1)
   VGC_TOP_H4  = 1, // H4  (H4>H1>M15>M5>M1)
   VGC_TOP_H1  = 2, // H1  (H1>M15>M5>M1) = Pine default
   VGC_TOP_M15 = 3  // M15 (M15>M5>M1)
  };

enum ENUM_VGC_EXCL
  {
   VGC_EXCL_NONE   = 0, // None
   VGC_EXCL_TEHRAN = 1, // Tehran times (Pine v3: 23:30, 00:30)
   VGC_EXCL_SERVER = 2  // Server hours list
  };

enum ENUM_VGC_DST
  {
   VGC_DST_US   = 0, // US DST (GMT+2 winter / GMT+3 summer brokers)
   VGC_DST_EU   = 1, // EU DST
   VGC_DST_NONE = 2  // No DST (winter offset all year)
  };

enum ENUM_VGC_SLREF
  {
   VGC_SL_OWN_ZONE = 0, // Far edge of the entry zone
   VGC_SL_TOP_ZONE = 1, // Far edge of the top (largest) zone
   VGC_SL_BAR      = 2  // Reaction bar extreme (zone limits use own zone)
  };

enum ENUM_VGC_SIDE
  {
   VGC_SIDE_BOTH  = 0, // Buy and sell
   VGC_SIDE_LONG  = 1, // Buy only
   VGC_SIDE_SHORT = 2  // Sell only
  };

enum ENUM_VGC_LOT
  {
   VGC_LOT_RISK  = 0, // Risk % of equity
   VGC_LOT_FIXED = 1  // Fixed lot
  };

//--- inputs ---------------------------------------------------------
input group "=== Cascade ==="
input ENUM_VGC_TOP InpTopTF      = VGC_TOP_H4; // Top timeframe (volume-gap trigger)
input int          InpWaitBars   = 4;          // Confirm closes inside box: wait N closes of next-lower TF (0=drop)
input bool         InpDirectOnly = false;      // Trade only setups biased by the confirm candle itself
input double       InpGapRatio   = 1.0;        // Gap volume < ratio x min(neighbours)  (1.0 = Pine rule)
input bool         InpUseM1Stage = true;       // Final M1 stage (deepest M1 volume gap)

input group "=== Session exclusion (H1 top only, as in Pine v3) ==="
input ENUM_VGC_EXCL InpExclMode   = VGC_EXCL_TEHRAN; // Exclusion mode
input string        InpExclTehran = "23:30,00:30";   // Tehran HH:MM list (UTC+3:30)
input string        InpExclServer = "22,23,0,1";     // Server-hour list
input int           InpGMTWinter  = 2;               // Server GMT offset, winter (LiteFinance = 2)
input int           InpGMTSummer  = 3;               // Server GMT offset, summer (LiteFinance = 3)
input ENUM_VGC_DST  InpDSTRule    = VGC_DST_US;      // DST rule of the server clock

input group "=== Zone entries (limit orders) ==="
input bool   InpTradeZ0    = false; // Limit at level-0 zone (top box: D1/H4/H1)
input bool   InpTradeZ1    = false; // Limit at level-1 zone
input bool   InpTradeZ2    = false; // Limit at level-2 zone
input bool   InpTradeZ3    = false; // Limit at level-3 zone
input bool   InpTradeZ4    = false; // Limit at level-4 zone
input bool   InpTradeZM1   = false; // Limit at the M1 zone
input double InpEntryDepth = 0.0;   // Entry depth inside zone (0 = near edge, 0.5 = middle)

input group "=== Reaction entries (market orders) ==="
input bool            InpTradePin    = true;      // Pin bar near the zone without touching it
input bool            InpTradeReject = false;     // Rejection: touches zone, closes back outside
input ENUM_TIMEFRAMES InpReactTF     = PERIOD_M5; // Timeframe of the reaction bars
input int             InpReactLevel  = 0;         // Zone level used for reactions (0 = top box)
input double          InpPinWickBody = 2.0;       // Pin bar: wick >= X x body
input double          InpPinBand     = 0.30;      // Pin bar: max distance from zone edge (x zone height)

input group "=== Stop loss / take profit ==="
input ENUM_VGC_SLREF InpSLRef        = VGC_SL_OWN_ZONE; // Stop-loss reference
input double         InpSLBufATR     = 0.10; // SL buffer beyond reference (x ATR H1)
input double         InpMinRiskATR   = 0.0;  // Minimum SL distance (x ATR H1, 0 = off)
input double         InpMaxRiskATR   = 0.0;  // Skip if SL distance > X ATR H1 (0 = off)
input double         InpRR           = 2.5;  // Take profit = RR x risk
input double         InpBreakEvenR   = 0.0;  // Move SL to entry after +X R (0 = off)
input int            InpMaxHoldHours = 96;   // Close position after N hours (0 = off)
input int            InpATRPeriod    = 14;   // ATR period (H1)

input group "=== Setup lifetime ==="
input bool InpReplaceOnNew    = true; // New setup cancels the previous one (Pine behaviour)
input int  InpMaxAgeHours     = 0;    // Cancel an unfilled setup after N hours (0 = off)
input int  InpEntryDelayHours = 0;    // Arm entries only N hours after the setup

input group "=== Filters ==="
input ENUM_VGC_SIDE InpSide        = VGC_SIDE_BOTH; // Allowed direction
input bool          InpTrendFilter = false;         // Only with the D1 trend (D1 close vs EMA)
input int           InpTrendEMA    = 50;            // D1 EMA period
input int           InpMaxSpreadPts= 0;             // Max spread for new entries, points (0 = off)

input group "=== Money management ==="
input ENUM_VGC_LOT InpLotMode      = VGC_LOT_RISK; // Lot mode
input double       InpRiskPct      = 0.5;          // Risk per trade, % of equity
input double       InpFixedLot     = 0.01;         // Fixed lot
input int          InpMaxPositions = 4;            // Max open positions + pending orders of this EA
input long         InpMagic        = 26092901;     // Magic number

input group "=== Chart / output ==="
input bool InpDraw           = true;  // Draw boxes and signals (off during optimisation)
input bool InpVerbose        = false; // Print details to the journal
input bool InpWriteCSV       = true;  // Write trade list to Common\Files at the end of a test
input int  InpMinTradesScore = 50;    // OnTester: minimum trades for a valid score

//--- constants / types ----------------------------------------------
#define VGC_MAX_LEVELS 6
#define VGC_KIND_PIN   10
#define VGC_KIND_REJ   11
#define VGC_SLOTS      8

struct VgcZone
  {
   bool     found;
   double   top;
   double   bot;
   datetime t0;
   datetime t1;
  };

struct VgcSetup
  {
   int      id;
   int      dir;           // +1 buy bias, -1 sell bias
   bool     direct;        // bias came from the confirm candle itself
   datetime created;
   datetime armAt;         // entries allowed from this time
   datetime expiry;        // 0 = no expiry
   bool     active;
   bool     allowEntries;  // side / trend / direct-only filters
   bool     ordersPlaced;
   bool     reactDone;
   bool     touched;       // reaction zone already touched (pin bars stop)
   bool     failed;        // closed beyond the far edge of the reaction zone
   double   atr;
   int      nz;
   VgcZone  z[VGC_MAX_LEVELS];
  };

struct VgcOrder
  {
   ulong    ticket;        // order ticket (= position identifier once filled)
   int      setupId;
   int      kind;          // zone level 0..5, VGC_KIND_PIN, VGC_KIND_REJ
   int      dir;
   double   riskMoney;
   double   entry;
   double   sl;
   datetime placed;
  };

struct VgcWait
  {
   bool     on;
   datetime gapT0;
   datetime gapT1;
   double   top;
   double   bot;
   datetime after;         // only lower-TF bars opening at/after this time count
   int      count;
  };

struct VgcStat
  {
   int      n;
   int      wins;
   double   sumR;
   double   winR;
   double   lossR;
  };

//--- globals ---------------------------------------------------------
CTrade          g_trade;
ENUM_TIMEFRAMES g_chain[5];
int             g_nChain    = 0;
ENUM_TIMEFRAMES g_waitTF    = PERIOD_M15;
int             g_atrHandle = INVALID_HANDLE;
int             g_emaHandle = INVALID_HANDLE;
datetime        g_lastTop   = 0;
datetime        g_lastWait  = 0;
datetime        g_lastReact = 0;
bool            g_draw      = true;
int             g_nextId    = 1;
VgcWait         g_wait;
VgcSetup        g_setups[];
VgcOrder        g_orders[];
int             g_exclTehran[];
int             g_exclServer[];
color           g_levelClr[VGC_MAX_LEVELS] = {clrRed, clrOrange, clrDeepPink, clrGold, clrDodgerBlue, clrTurquoise};

//+------------------------------------------------------------------+
//| helpers                                                          |
//+------------------------------------------------------------------+
string TFName(ENUM_TIMEFRAMES tf)
  {
   switch(tf)
     {
      case PERIOD_M1:
         return "M1";
      case PERIOD_M5:
         return "M5";
      case PERIOD_M15:
         return "M15";
      case PERIOD_M30:
         return "M30";
      case PERIOD_H1:
         return "H1";
      case PERIOD_H4:
         return "H4";
      case PERIOD_D1:
         return "D1";
      default:
         break;
     }
   return EnumToString(tf);
  }

string KindName(int kind)
  {
   if(kind == VGC_KIND_PIN)
      return "PIN";
   if(kind == VGC_KIND_REJ)
      return "REJ";
   if(kind >= 0 && kind < g_nChain)
      return TFName(g_chain[kind]) + "zone";
   if(kind == g_nChain)
      return "M1zone";
   return "L" + IntegerToString(kind);
  }

int KindSlot(int kind)
  {
   if(kind == VGC_KIND_PIN)
      return 6;
   if(kind == VGC_KIND_REJ)
      return 7;
   if(kind >= 0 && kind < VGC_MAX_LEVELS)
      return kind;
   return -1;
  }

bool ZoneTradeEnabled(int li)
  {
   if(li == g_nChain)
      return InpTradeZM1;
   switch(li)
     {
      case 0:
         return InpTradeZ0;
      case 1:
         return InpTradeZ1;
      case 2:
         return InpTradeZ2;
      case 3:
         return InpTradeZ3;
      case 4:
         return InpTradeZ4;
      default:
         break;
     }
   return false;
  }

double NormalizePrice(double p)
  {
   double ts = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(ts <= 0.0)
      ts = _Point;
   return NormalizeDouble(MathRound(p / ts) * ts, _Digits);
  }

double CurrentSpread()
  {
   return SymbolInfoDouble(_Symbol, SYMBOL_ASK) - SymbolInfoDouble(_Symbol, SYMBOL_BID);
  }

bool SpreadOK()
  {
   if(InpMaxSpreadPts <= 0)
      return true;
   return SymbolInfoInteger(_Symbol, SYMBOL_SPREAD) <= InpMaxSpreadPts;
  }

bool NewBar(ENUM_TIMEFRAMES tf, datetime &last)
  {
   datetime t = iTime(_Symbol, tf, 0);
   if(t == 0 || t == last)
      return false;
   bool first = (last == 0);
   last = t;
   return !first;
  }

double ATRH1()
  {
   double b[1];
   if(CopyBuffer(g_atrHandle, 0, 1, 1, b) != 1)
      return 0.0;
   return b[0];
  }

bool TrendOK(int dir)
  {
   if(!InpTrendFilter)
      return true;
   double e[1];
   if(CopyBuffer(g_emaHandle, 0, 1, 1, e) != 1)
      return false;
   double c = iClose(_Symbol, PERIOD_D1, 1);
   if(c <= 0.0)
      return false;
   return (dir > 0) ? (c > e[0]) : (c < e[0]);
  }

bool SideOK(int dir)
  {
   if(InpSide == VGC_SIDE_LONG)
      return dir > 0;
   if(InpSide == VGC_SIDE_SHORT)
      return dir < 0;
   return true;
  }

//--- server clock -> UTC ------------------------------------------------
datetime NthSunday(int year, int mon, int nth)
  {
   MqlDateTime d;
   ZeroMemory(d);
   d.year = year;
   d.mon  = mon;
   d.day  = 1;
   datetime first = StructToTime(d);
   MqlDateTime f;
   TimeToStruct(first, f);
   int add = (7 - f.day_of_week) % 7;
   return first + (add + 7 * (nth - 1)) * 86400;
  }

datetime LastSunday(int year, int mon)
  {
   MqlDateTime d;
   ZeroMemory(d);
   d.year = (mon == 12) ? year + 1 : year;
   d.mon  = (mon == 12) ? 1 : mon + 1;
   d.day  = 1;
   datetime firstNext = StructToTime(d);
   MqlDateTime f;
   TimeToStruct(firstNext, f);
   int back = (f.day_of_week == 0) ? 7 : f.day_of_week;
   return firstNext - back * 86400;
  }

int ServerGMTOffset(datetime t)
  {
   if(InpDSTRule == VGC_DST_NONE)
      return InpGMTWinter;
   MqlDateTime s;
   TimeToStruct(t, s);
   datetime a, b;
   if(InpDSTRule == VGC_DST_US)
     {
      a = NthSunday(s.year, 3, 2);
      b = NthSunday(s.year, 11, 1);
     }
   else
     {
      a = LastSunday(s.year, 3);
      b = LastSunday(s.year, 10);
     }
   return (t >= a && t < b) ? InpGMTSummer : InpGMTWinter;
  }

void ParseExclusions()
  {
   ArrayResize(g_exclTehran, 0);
   ArrayResize(g_exclServer, 0);
   string parts[];
   int n = StringSplit(InpExclTehran, ',', parts);
   for(int i = 0; i < n; i++)
     {
      string s = parts[i];
      StringTrimLeft(s);
      StringTrimRight(s);
      string hm[];
      if(StringSplit(s, ':', hm) != 2)
         continue;
      int k = ArraySize(g_exclTehran);
      ArrayResize(g_exclTehran, k + 1);
      g_exclTehran[k] = (int)StringToInteger(hm[0]) * 60 + (int)StringToInteger(hm[1]);
     }
   n = StringSplit(InpExclServer, ',', parts);
   for(int i = 0; i < n; i++)
     {
      string s = parts[i];
      StringTrimLeft(s);
      StringTrimRight(s);
      if(StringLen(s) == 0)
         continue;
      int k = ArraySize(g_exclServer);
      ArrayResize(g_exclServer, k + 1);
      g_exclServer[k] = (int)StringToInteger(s);
     }
  }

bool IsExcludedGap(datetime t)
  {
   if(g_chain[0] != PERIOD_H1 || InpExclMode == VGC_EXCL_NONE)
      return false;
   MqlDateTime s;
   if(InpExclMode == VGC_EXCL_SERVER)
     {
      TimeToStruct(t, s);
      for(int i = 0; i < ArraySize(g_exclServer); i++)
         if(s.hour == g_exclServer[i])
            return true;
      return false;
     }
   datetime utc = t - ServerGMTOffset(t) * 3600;
   TimeToStruct(utc + 210 * 60, s);   // Tehran = UTC+3:30
   int m = s.hour * 60 + s.min;
   for(int i = 0; i < ArraySize(g_exclTehran); i++)
      if(m == g_exclTehran[i])
         return true;
   return false;
  }

//--- orders bookkeeping ------------------------------------------------
int FindOrderRec(ulong ticket)
  {
   for(int i = ArraySize(g_orders) - 1; i >= 0; i--)
      if(g_orders[i].ticket == ticket)
         return i;
   return -1;
  }

void AddOrderRec(ulong ticket, int setupId, int kind, int dir, double riskMoney, double entry, double sl)
  {
   int k = ArraySize(g_orders);
   ArrayResize(g_orders, k + 1, 256);
   g_orders[k].ticket    = ticket;
   g_orders[k].setupId   = setupId;
   g_orders[k].kind      = kind;
   g_orders[k].dir       = dir;
   g_orders[k].riskMoney = riskMoney;
   g_orders[k].entry     = entry;
   g_orders[k].sl        = sl;
   g_orders[k].placed    = TimeCurrent();
  }

int CountMyExposure()
  {
   int n = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong tk = PositionGetTicket(i);
      if(tk == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) == _Symbol && PositionGetInteger(POSITION_MAGIC) == InpMagic)
         n++;
     }
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong tk = OrderGetTicket(i);
      if(tk == 0)
         continue;
      if(OrderGetString(ORDER_SYMBOL) == _Symbol && OrderGetInteger(ORDER_MAGIC) == InpMagic)
         n++;
     }
   return n;
  }

void DeleteSetupOrders(int setupId)
  {
   for(int i = 0; i < ArraySize(g_orders); i++)
     {
      if(g_orders[i].setupId != setupId)
         continue;
      if(OrderSelect(g_orders[i].ticket))
         g_trade.OrderDelete(g_orders[i].ticket);
     }
  }

//--- money -----------------------------------------------------------
double LossPerLot(int dir, double entry, double sl)
  {
   double profit = 0.0;
   ENUM_ORDER_TYPE t = (dir > 0) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   if(OrderCalcProfit(t, _Symbol, 1.0, entry, sl, profit) && profit != 0.0)
      return MathAbs(profit);
   double ts = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tv = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   if(ts <= 0.0)
      return 0.0;
   return MathAbs(entry - sl) / ts * tv;
  }

double CalcLots(int dir, double entry, double sl)
  {
   double vmin  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double vstep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double lots  = InpFixedLot;
   if(InpLotMode == VGC_LOT_RISK)
     {
      double lpl = LossPerLot(dir, entry, sl);
      if(lpl <= 0.0)
         return 0.0;
      lots = AccountInfoDouble(ACCOUNT_EQUITY) * InpRiskPct / 100.0 / lpl;
     }
   if(vstep > 0.0)
      lots = MathFloor(lots / vstep + 1e-9) * vstep;
   if(lots < vmin)
     {
      if(InpVerbose)
         PrintFormat("VGC: lot %.4f < minimum %.2f -> trade skipped (raise risk %% / deposit, or use fixed lot)", lots, vmin);
      return 0.0;
     }
   lots = MathMin(lots, vmax);
   int vd = (vstep > 0.0) ? (int)MathMax(0.0, MathCeil(-MathLog10(vstep) - 1e-9)) : 2;
   return NormalizeDouble(lots, vd);
  }

//--- stop placement ----------------------------------------------------
bool AdjustRisk(int dir, double entry, double &sl, double atr)
  {
   if(InpMinRiskATR > 0.0 && atr > 0.0 && MathAbs(entry - sl) < InpMinRiskATR * atr)
      sl = (dir > 0) ? entry - InpMinRiskATR * atr : entry + InpMinRiskATR * atr;
   double risk = MathAbs(entry - sl);
   if(InpMaxRiskATR > 0.0 && atr > 0.0 && risk > InpMaxRiskATR * atr)
      return false;
   if(dir > 0 && sl >= entry)
      return false;
   if(dir < 0 && sl <= entry)
      return false;
   return risk > 0.0;
  }

double ZoneStop(const VgcSetup &s, int li)
  {
   int ref = (InpSLRef == VGC_SL_TOP_ZONE) ? 0 : li;
   double buf = InpSLBufATR * s.atr;
   if(s.dir > 0)
      return s.z[ref].bot - buf;
   return s.z[ref].top + buf + CurrentSpread();   // sell stops trigger on the ask
  }

//+------------------------------------------------------------------+
//| drawing                                                          |
//+------------------------------------------------------------------+
void DrawBox(string name, datetime t1, double p1, datetime t2, double p2, color c)
  {
   if(!g_draw)
      return;
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_RECTANGLE, 0, t1, p1, t2, p2);
   else
     {
      ObjectMove(0, name, 0, t1, p1);
      ObjectMove(0, name, 1, t2, p2);
     }
   ObjectSetInteger(0, name, OBJPROP_COLOR, c);
   ObjectSetInteger(0, name, OBJPROP_FILL, true);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
  }

void DrawText(string name, datetime t, double p, string txt, color c)
  {
   if(!g_draw)
      return;
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_TEXT, 0, t, p);
   ObjectSetString(0, name, OBJPROP_TEXT, txt);
   ObjectSetInteger(0, name, OBJPROP_COLOR, c);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 8);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
  }

void DrawArrow(string name, datetime t, double p, bool buy)
  {
   if(!g_draw)
      return;
   ObjectCreate(0, name, buy ? OBJ_ARROW_BUY : OBJ_ARROW_SELL, 0, t, p);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
  }

string ZoneObjName(const VgcSetup &s, int li)
  {
   return "VGC_" + IntegerToString(s.id) + "_Z" + IntegerToString(li);
  }

void DrawSetup(const VgcSetup &s)
  {
   if(!g_draw)
      return;
   for(int li = 0; li < s.nz; li++)
     {
      string nm = ZoneObjName(s, li);
      if(s.z[li].found)
         DrawBox(nm, s.z[li].t0, s.z[li].top, s.z[li].t1, s.z[li].bot, g_levelClr[li < VGC_MAX_LEVELS ? li : VGC_MAX_LEVELS - 1]);
      else
         DrawBox(nm + "x", s.z[li].t0, s.z[li].top, s.z[li].t1, s.z[li].bot, clrDimGray);
     }
   if(s.nz > g_nChain && s.z[g_nChain].found)          // the M1 zone is always turquoise
      ObjectSetInteger(0, ZoneObjName(s, g_nChain), OBJPROP_COLOR, clrTurquoise);
   string lbl = StringFormat("%s gap #%d %s%s", TFName(g_chain[0]), s.id, s.dir > 0 ? "BUY bias" : "SELL bias",
                             s.direct ? "" : " (waited)");
   DrawText("VGC_" + IntegerToString(s.id) + "_T", s.z[0].t0, s.dir > 0 ? s.z[0].bot : s.z[0].top, lbl, clrSilver);
  }

void ExtendSetup(const VgcSetup &s, datetime t)
  {
   if(!g_draw)
      return;
   for(int li = 0; li < s.nz; li++)
      if(s.z[li].found)
         ObjectMove(0, ZoneObjName(s, li), 1, t, s.z[li].bot);
  }

//+------------------------------------------------------------------+
//| cascade                                                          |
//+------------------------------------------------------------------+
//--- deepest local tick-volume minimum among bars fully inside [w0, w1)
bool FindDeepestGap(ENUM_TIMEFRAMES tf, datetime w0, datetime w1, datetime &gt, double &gh, double &gl)
  {
   int P = PeriodSeconds(tf);
   int sFirst = iBarShift(_Symbol, tf, w0, false);
   int sLast  = iBarShift(_Symbol, tf, w1 - 1, false);
   if(sFirst < 0 || sLast < 0)
      return false;
   int newest = MathMax(sLast - 2, 1);   // right neighbour must be a closed bar
   int oldest = sFirst + 2;
   int count  = oldest - newest + 1;
   if(count < 3)
      return false;
   MqlRates r[];
   int got = CopyRates(_Symbol, tf, newest, count, r);
   if(got < 3)
      return false;
   int  best  = -1;
   long bestV = LONG_MAX;
   for(int i = 1; i < got - 1; i++)
     {
      if(r[i].time < w0 || r[i].time + P > w1)
         continue;
      long v0 = r[i].tick_volume;
      if(v0 < r[i - 1].tick_volume && v0 < r[i + 1].tick_volume && v0 < bestV)
        {
         bestV = v0;
         best  = i;
        }
     }
   if(best < 0)
      return false;
   gt = r[best].time;
   gh = r[best].high;
   gl = r[best].low;
   return true;
  }

void RunCascade(VgcSetup &s, datetime winT0, datetime winT1, double zt, double zb)
  {
   s.z[0].found = true;
   s.z[0].top   = zt;
   s.z[0].bot   = zb;
   s.z[0].t0    = winT0;
   s.z[0].t1    = winT1;
   s.nz = 1;
   datetime w0 = winT0, w1 = winT1;
   int stages = g_nChain + (InpUseM1Stage ? 1 : 0);
   for(int li = 1; li < stages && li < VGC_MAX_LEVELS; li++)
     {
      ENUM_TIMEFRAMES tf = (li < g_nChain) ? g_chain[li] : PERIOD_M1;
      datetime gt = 0;
      double gh = 0.0, gl = 0.0;
      if(FindDeepestGap(tf, w0, w1, gt, gh, gl))
        {
         s.z[li].found = true;
         s.z[li].top   = gh;
         s.z[li].bot   = gl;
         s.z[li].t0    = gt;
         s.z[li].t1    = gt + PeriodSeconds(tf);
         w0 = s.z[li].t0;
         w1 = s.z[li].t1;
        }
      else
        {
         // "no volume gap here -> drop to the lower TF with the same window"
         s.z[li].found = false;
         s.z[li].top   = s.z[li - 1].top;   // "gray" level keeps the previous level's box
         s.z[li].bot   = s.z[li - 1].bot;
         s.z[li].t0    = w0;
         s.z[li].t1    = w1;
        }
      s.nz = li + 1;
     }
  }

//+------------------------------------------------------------------+
//| entries                                                          |
//+------------------------------------------------------------------+
bool SendLimit(int dir, double lots, double price, double sl, double tp, string cmt)
  {
   ENUM_ORDER_TYPE_FILLING modes[3] = {ORDER_FILLING_RETURN, ORDER_FILLING_FOK, ORDER_FILLING_IOC};
   bool ok = false;
   for(int a = 0; a < 4 && !ok; a++)
     {
      if(a == 0)
         g_trade.SetTypeFillingBySymbol(_Symbol);
      else
         g_trade.SetTypeFilling(modes[a - 1]);
      if(dir > 0)
         ok = g_trade.BuyLimit(lots, price, _Symbol, sl, tp, ORDER_TIME_GTC, 0, cmt);
      else
         ok = g_trade.SellLimit(lots, price, _Symbol, sl, tp, ORDER_TIME_GTC, 0, cmt);
      ok = ok && g_trade.ResultOrder() > 0;
      if(!ok && g_trade.ResultRetcode() != TRADE_RETCODE_INVALID_FILL)
         break;
     }
   g_trade.SetTypeFillingBySymbol(_Symbol);
   return ok;
  }

void PlaceLimit(VgcSetup &s, int kind, double entry, double sl)
  {
   if(!AdjustRisk(s.dir, entry, sl, s.atr) || !SpreadOK())
      return;
   if(CountMyExposure() >= InpMaxPositions)
      return;
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double lvl = (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;
   entry = NormalizePrice(entry);
   sl    = NormalizePrice(sl);
   double risk = MathAbs(entry - sl);
   if(risk < lvl || risk <= 0.0)
      return;
   double tp = NormalizePrice(s.dir > 0 ? entry + InpRR * risk : entry - InpRR * risk);
   if(s.dir > 0 && entry > ask - lvl)
      return;                                   // buy limit must be below the market
   if(s.dir < 0 && entry < bid + lvl)
      return;                                   // sell limit must be above the market
   double lots = CalcLots(s.dir, entry, sl);
   if(lots <= 0.0)
      return;
   string cmt = StringFormat("VGC#%d %s", s.id, KindName(kind));
   if(!SendLimit(s.dir, lots, entry, sl, tp, cmt))
     {
      if(InpVerbose)
         PrintFormat("VGC: limit order failed (%s): %u %s", cmt, g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
      return;
     }
   AddOrderRec(g_trade.ResultOrder(), s.id, kind, s.dir, lots * LossPerLot(s.dir, entry, sl), entry, sl);
   if(InpVerbose)
      PrintFormat("VGC: %s limit %.2f sl %.2f tp %.2f lots %.2f", cmt, entry, sl, tp, lots);
  }

void PlaceZoneOrders(VgcSetup &s)
  {
   s.ordersPlaced = true;
   if(!s.allowEntries)
      return;
   for(int li = 0; li < s.nz; li++)
     {
      if(!s.z[li].found || !ZoneTradeEnabled(li))
         continue;
      double h = s.z[li].top - s.z[li].bot;
      double entry = (s.dir > 0) ? s.z[li].top - InpEntryDepth * h : s.z[li].bot + InpEntryDepth * h;
      PlaceLimit(s, li, entry, ZoneStop(s, li));
     }
  }

void EnterReaction(VgcSetup &s, int kind, const MqlRates &b)
  {
   if(!SpreadOK() || CountMyExposure() >= InpMaxPositions)
      return;
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double entry = (s.dir > 0) ? ask : bid;
   double buf = InpSLBufATR * s.atr;
   double sl;
   if(InpSLRef == VGC_SL_BAR)
      sl = (s.dir > 0) ? b.low - buf : b.high + buf + (ask - bid);
   else
     {
      int ref = (InpSLRef == VGC_SL_TOP_ZONE) ? 0 : InpReactLevel;
      sl = (s.dir > 0) ? s.z[ref].bot - buf : s.z[ref].top + buf + (ask - bid);
     }
   if(!AdjustRisk(s.dir, entry, sl, s.atr))
      return;
   double lvl = (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;
   sl = NormalizePrice(sl);
   double risk = MathAbs(entry - sl);
   if(risk < lvl || risk <= 0.0)
      return;
   double tp = NormalizePrice(s.dir > 0 ? entry + InpRR * risk : entry - InpRR * risk);
   double lots = CalcLots(s.dir, entry, sl);
   if(lots <= 0.0)
      return;
   string cmt = StringFormat("VGC#%d %s", s.id, KindName(kind));
   g_trade.SetTypeFillingBySymbol(_Symbol);
   bool ok = (s.dir > 0) ? g_trade.Buy(lots, _Symbol, 0.0, sl, tp, cmt) : g_trade.Sell(lots, _Symbol, 0.0, sl, tp, cmt);
   if(!ok || g_trade.ResultOrder() == 0)
     {
      if(InpVerbose)
         PrintFormat("VGC: market order failed (%s): %u %s", cmt, g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
      return;
     }
   AddOrderRec(g_trade.ResultOrder(), s.id, kind, s.dir, lots * LossPerLot(s.dir, entry, sl), entry, sl);
   DrawArrow("VGC_" + IntegerToString(s.id) + "_" + KindName(kind), TimeCurrent(), entry, s.dir > 0);
   if(InpVerbose)
      PrintFormat("VGC: %s market %.2f sl %.2f tp %.2f lots %.2f", cmt, entry, sl, tp, lots);
  }

//--- reaction bars (pin bar / rejection) on the closed bar `b` ---------
void CheckReaction(VgcSetup &s, const MqlRates &b)
  {
   if(s.reactDone || s.failed)
      return;
   int li = InpReactLevel;
   if(li >= s.nz || !s.z[li].found)
     {
      s.reactDone = true;
      return;
     }
   double zt = s.z[li].top, zb = s.z[li].bot, h = zt - zb;
   double body = MathAbs(b.close - b.open);
   double upW  = b.high - MathMax(b.open, b.close);
   double loW  = MathMin(b.open, b.close) - b.low;
   bool armed  = s.allowEntries && TimeCurrent() >= s.armAt;
   if(s.dir > 0)
     {
      bool touch = (b.low <= zt);
      if(InpTradeReject && armed && touch && b.close > zt)
        {
         EnterReaction(s, VGC_KIND_REJ, b);
         s.reactDone = true;
         return;
        }
      if(InpTradePin && armed && !s.touched)
        {
         bool pin = body > 0.0 && loW >= InpPinWickBody * body && loW > upW;
         if(pin && b.low > zt && b.low <= zt + InpPinBand * h && b.close > zt)
           {
            DrawText("VGC_" + IntegerToString(s.id) + "_PIN", b.time, b.low, "Pin", clrWhite);
            EnterReaction(s, VGC_KIND_PIN, b);
            s.reactDone = true;
            return;
           }
        }
      if(touch)
         s.touched = true;
      if(b.close < zb)
         s.failed = true;
     }
   else
     {
      bool touch = (b.high >= zb);
      if(InpTradeReject && armed && touch && b.close < zb)
        {
         EnterReaction(s, VGC_KIND_REJ, b);
         s.reactDone = true;
         return;
        }
      if(InpTradePin && armed && !s.touched)
        {
         bool pin = body > 0.0 && upW >= InpPinWickBody * body && upW > loW;
         if(pin && b.high < zb && b.high >= zb - InpPinBand * h && b.close < zb)
           {
            DrawText("VGC_" + IntegerToString(s.id) + "_PIN", b.time, b.high, "Pin", clrWhite);
            EnterReaction(s, VGC_KIND_PIN, b);
            s.reactDone = true;
            return;
           }
        }
      if(touch)
         s.touched = true;
      if(b.close > zt)
         s.failed = true;
     }
  }

//+------------------------------------------------------------------+
//| setups                                                           |
//+------------------------------------------------------------------+
void DeactivateSetup(int i)
  {
   if(!g_setups[i].active)
      return;
   g_setups[i].active = false;
   DeleteSetupOrders(g_setups[i].id);
  }

void CreateSetup(int dir, datetime t0, datetime t1, double zt, double zb, bool direct)
  {
   VgcSetup s;
   ZeroMemory(s);
   s.id           = g_nextId++;
   s.dir          = dir;
   s.direct       = direct;
   s.created      = TimeCurrent();
   s.armAt        = s.created + InpEntryDelayHours * 3600;
   s.expiry       = (InpMaxAgeHours > 0) ? s.created + InpMaxAgeHours * 3600 : (datetime)0;
   s.active       = true;
   s.allowEntries = SideOK(dir) && TrendOK(dir) && (direct || !InpDirectOnly);
   s.atr          = ATRH1();
   RunCascade(s, t0, t1, zt, zb);
   if(s.atr <= 0.0)
      s.allowEntries = false;
   if(InpReplaceOnNew)
      for(int i = 0; i < ArraySize(g_setups); i++)
         DeactivateSetup(i);
   //--- keep the array small: drop inactive setups
   int w = 0;
   for(int i = 0; i < ArraySize(g_setups); i++)
      if(g_setups[i].active)
        {
         if(w != i)
            g_setups[w] = g_setups[i];
         w++;
        }
   ArrayResize(g_setups, w + 1);
   g_setups[w] = s;
   DrawSetup(s);
   if(InpVerbose)
     {
      string zs = "";
      for(int li = 0; li < s.nz; li++)
         zs += StringFormat(" [%s %s %.2f-%.2f]", li < g_nChain ? TFName(g_chain[li]) : "M1",
                            s.z[li].found ? "gap" : "none", s.z[li].bot, s.z[li].top);
      PrintFormat("VGC: setup #%d %s %s entries=%s%s", s.id, dir > 0 ? "BUY" : "SELL", direct ? "direct" : "waited",
                  s.allowEntries ? "on" : "off", zs);
     }
  }

void OnNewTopBar()
  {
   MqlRates r[];
   if(CopyRates(_Symbol, g_chain[0], 1, 3, r) != 3)
      return;
   // r[0] = left neighbour, r[1] = gap candidate, r[2] = confirm candle (just closed)
   long vL = r[0].tick_volume, vC = r[1].tick_volume, vR = r[2].tick_volume;
   if(!(vC < vL && vC < vR))
      return;
   if(InpGapRatio < 1.0 && (double)vC >= InpGapRatio * MathMin((double)vL, (double)vR))
      return;
   datetime t0 = r[1].time;
   datetime t1 = t0 + PeriodSeconds(g_chain[0]);
   if(IsExcludedGap(t0))
     {
      DrawBox("VGC_X_" + IntegerToString((long)t0), t0, r[1].high, t1, r[1].low, clrDimGray);
      if(InpVerbose)
         PrintFormat("VGC: gap %s excluded (session boundary)", TimeToString(t0));
      return;
     }
   g_wait.on = false;                                  // a newer valid gap supersedes an unresolved wait
   double zt = r[1].high, zb = r[1].low, cc = r[2].close;
   if(cc > zt)
     {
      CreateSetup(1, t0, t1, zt, zb, true);
      return;
     }
   if(cc < zb)
     {
      CreateSetup(-1, t0, t1, zt, zb, true);
      return;
     }
   if(InpWaitBars <= 0)
      return;
   g_wait.on    = true;
   g_wait.gapT0 = t0;
   g_wait.gapT1 = t1;
   g_wait.top   = zt;
   g_wait.bot   = zb;
   g_wait.after = r[2].time + PeriodSeconds(g_chain[0]);
   g_wait.count = 0;
  }

void OnNewWaitBar()
  {
   if(!g_wait.on)
      return;
   MqlRates r[];
   if(CopyRates(_Symbol, g_waitTF, 1, 1, r) != 1)
      return;
   if(r[0].time < g_wait.after)
      return;
   int dir = 0;
   if(r[0].close > g_wait.top)
      dir = 1;
   else
      if(r[0].close < g_wait.bot)
         dir = -1;
   if(dir != 0)
     {
      g_wait.on = false;
      CreateSetup(dir, g_wait.gapT0, g_wait.gapT1, g_wait.top, g_wait.bot, false);
      return;
     }
   g_wait.count++;
   if(g_wait.count >= InpWaitBars)
      g_wait.on = false;
  }

void OnNewReactBar()
  {
   MqlRates r[];
   if(CopyRates(_Symbol, InpReactTF, 1, 1, r) != 1)
      return;
   int P = PeriodSeconds(InpReactTF);
   for(int i = 0; i < ArraySize(g_setups); i++)
     {
      if(!g_setups[i].active)
         continue;
      if(r[0].time + P <= g_setups[i].created)
         continue;                                     // bar closed before the setup existed
      ExtendSetup(g_setups[i], r[0].time + P);
      if(InpTradePin || InpTradeReject)
         CheckReaction(g_setups[i], r[0]);
     }
  }

void ManageSetups()
  {
   datetime now = TimeCurrent();
   for(int i = 0; i < ArraySize(g_setups); i++)
     {
      if(!g_setups[i].active)
         continue;
      if(g_setups[i].expiry > 0 && now >= g_setups[i].expiry)
        {
         DeactivateSetup(i);
         continue;
        }
      if(!g_setups[i].ordersPlaced && now >= g_setups[i].armAt)
         PlaceZoneOrders(g_setups[i]);
     }
  }

void ManagePositions()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong tk = PositionGetTicket(i);
      if(tk == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol || PositionGetInteger(POSITION_MAGIC) != InpMagic)
         continue;
      datetime opened = (datetime)PositionGetInteger(POSITION_TIME);
      if(InpMaxHoldHours > 0 && TimeCurrent() - opened >= (long)InpMaxHoldHours * 3600)
        {
         g_trade.PositionClose(tk);
         continue;
        }
      if(InpBreakEvenR <= 0.0)
         continue;
      int idx = FindOrderRec((ulong)PositionGetInteger(POSITION_IDENTIFIER));
      if(idx < 0)
         continue;
      double risk = MathAbs(g_orders[idx].entry - g_orders[idx].sl);
      double op = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl = PositionGetDouble(POSITION_SL);
      double tp = PositionGetDouble(POSITION_TP);
      if(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY)
        {
         if(sl < op && SymbolInfoDouble(_Symbol, SYMBOL_BID) - op >= InpBreakEvenR * risk)
            g_trade.PositionModify(tk, NormalizePrice(op), tp);
        }
      else
        {
         if((sl > op || sl == 0.0) && op - SymbolInfoDouble(_Symbol, SYMBOL_ASK) >= InpBreakEvenR * risk)
            g_trade.PositionModify(tk, NormalizePrice(op), tp);
        }
     }
  }

//+------------------------------------------------------------------+
//| statistics (R multiples per entry type)                          |
//+------------------------------------------------------------------+
int CollectR(double &rOut[], int &kindOut[], datetime &tIn[], datetime &tOut[], double &pnl[])
  {
   int no = ArraySize(g_orders);
   double   prof[];
   bool     closed[];
   datetime t0[], t1[];
   ArrayResize(prof, no);
   ArrayResize(closed, no);
   ArrayResize(t0, no);
   ArrayResize(t1, no);
   for(int i = 0; i < no; i++)
     {
      prof[i] = 0.0;
      closed[i] = false;
      t0[i] = 0;
      t1[i] = 0;
     }
   if(!HistorySelect(0, TimeCurrent() + 86400))
      return 0;
   int nd = HistoryDealsTotal();
   for(int d = 0; d < nd; d++)
     {
      ulong tk = HistoryDealGetTicket(d);
      if(tk == 0)
         continue;
      if(HistoryDealGetInteger(tk, DEAL_MAGIC) != InpMagic || HistoryDealGetString(tk, DEAL_SYMBOL) != _Symbol)
         continue;
      int idx = FindOrderRec((ulong)HistoryDealGetInteger(tk, DEAL_POSITION_ID));
      if(idx < 0)
         continue;
      prof[idx] += HistoryDealGetDouble(tk, DEAL_PROFIT) + HistoryDealGetDouble(tk, DEAL_SWAP)
                   + HistoryDealGetDouble(tk, DEAL_COMMISSION) + HistoryDealGetDouble(tk, DEAL_FEE);
      long entryType = HistoryDealGetInteger(tk, DEAL_ENTRY);
      datetime dt = (datetime)HistoryDealGetInteger(tk, DEAL_TIME);
      if(entryType == DEAL_ENTRY_IN)
         t0[idx] = dt;
      else
         if(entryType == DEAL_ENTRY_OUT || entryType == DEAL_ENTRY_OUT_BY || entryType == DEAL_ENTRY_INOUT)
           {
            closed[idx] = true;
            t1[idx] = dt;
           }
     }
   int n = 0;
   ArrayResize(rOut, no);
   ArrayResize(kindOut, no);
   ArrayResize(tIn, no);
   ArrayResize(tOut, no);
   ArrayResize(pnl, no);
   for(int i = 0; i < no; i++)
     {
      if(!closed[i] || g_orders[i].riskMoney <= 0.0)
         continue;
      rOut[n]    = prof[i] / g_orders[i].riskMoney;
      kindOut[n] = g_orders[i].kind;
      tIn[n]     = t0[i];
      tOut[n]    = t1[i];
      pnl[n]     = prof[i];
      n++;
     }
   return n;
  }

void ReportStats(bool writeCsv)
  {
   double r[];
   int kinds[];
   datetime tin[], tout[];
   double pnl[];
   int n = CollectR(r, kinds, tin, tout, pnl);
   VgcStat st[VGC_SLOTS + 1];
   for(int k = 0; k <= VGC_SLOTS; k++)
     {
      st[k].n = 0;
      st[k].wins = 0;
      st[k].sumR = 0.0;
      st[k].winR = 0.0;
      st[k].lossR = 0.0;
     }
   for(int i = 0; i < n; i++)
     {
      int slot = KindSlot(kinds[i]);
      for(int pass = 0; pass < 2; pass++)
        {
         int k = (pass == 0) ? VGC_SLOTS : slot;      // slot VGC_SLOTS = all trades
         if(k < 0)
            continue;
         st[k].n++;
         st[k].sumR += r[i];
         if(r[i] > 0.0)
           {
            st[k].wins++;
            st[k].winR += r[i];
           }
         else
            st[k].lossR -= r[i];
        }
     }
   Print("VGC ===== R-multiple summary (net of spread/commission/swap) =====");
   for(int k = 0; k <= VGC_SLOTS; k++)
     {
      if(st[k].n == 0)
         continue;
      string nm = (k == VGC_SLOTS) ? "ALL" : (k == 6 ? "PIN" : (k == 7 ? "REJ" : KindName(k)));
      double pf = st[k].lossR > 0.0 ? st[k].winR / st[k].lossR : 0.0;
      PrintFormat("VGC %-8s trades=%5d  win=%5.1f%%  avgR=%+.3f  totalR=%+.1f  PF=%.2f", nm, st[k].n,
                  100.0 * st[k].wins / st[k].n, st[k].sumR / st[k].n, st[k].sumR, pf);
     }
   if(!writeCsv || n == 0)
      return;
   string fn = "VGC_trades_" + _Symbol + ".csv";
   int fh = FileOpen(fn, FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
   if(fh == INVALID_HANDLE)
      return;
   FileWrite(fh, "open_time", "close_time", "kind", "profit", "R");
   for(int i = 0; i < n; i++)
      FileWrite(fh, TimeToString(tin[i], TIME_DATE | TIME_MINUTES), TimeToString(tout[i], TIME_DATE | TIME_MINUTES),
                KindName(kinds[i]), DoubleToString(pnl[i], 2), DoubleToString(r[i], 4));
   FileClose(fh);
   PrintFormat("VGC: trade list written to Common\\Files\\%s", fn);
  }

//+------------------------------------------------------------------+
//| expert events                                                    |
//+------------------------------------------------------------------+
int OnInit()
  {
   g_nChain = 0;
   if(InpTopTF == VGC_TOP_D1)
      g_chain[g_nChain++] = PERIOD_D1;
   if(InpTopTF == VGC_TOP_D1 || InpTopTF == VGC_TOP_H4)
      g_chain[g_nChain++] = PERIOD_H4;
   if(InpTopTF != VGC_TOP_M15)
      g_chain[g_nChain++] = PERIOD_H1;
   g_chain[g_nChain++] = PERIOD_M15;
   g_chain[g_nChain++] = PERIOD_M5;
   g_waitTF = g_chain[1];

   if(InpReactLevel < 0 || InpReactLevel >= g_nChain + (InpUseM1Stage ? 1 : 0))
     {
      Print("VGC: InpReactLevel is outside the cascade levels");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(InpRR <= 0.0 || InpRiskPct <= 0.0)
      return INIT_PARAMETERS_INCORRECT;

   g_atrHandle = iATR(_Symbol, PERIOD_H1, InpATRPeriod);
   if(g_atrHandle == INVALID_HANDLE)
     {
      Print("VGC: cannot create ATR handle");
      return INIT_FAILED;
     }
   if(InpTrendFilter)
     {
      g_emaHandle = iMA(_Symbol, PERIOD_D1, InpTrendEMA, 0, MODE_EMA, PRICE_CLOSE);
      if(g_emaHandle == INVALID_HANDLE)
        {
         Print("VGC: cannot create EMA handle");
         return INIT_FAILED;
        }
     }
   ParseExclusions();
   g_trade.SetExpertMagicNumber((ulong)InpMagic);
   g_trade.SetDeviationInPoints(50);
   g_trade.SetTypeFillingBySymbol(_Symbol);
   g_draw = InpDraw && !(bool)MQLInfoInteger(MQL_OPTIMIZATION);
   ZeroMemory(g_wait);
   g_wait.on = false;
   ArrayResize(g_setups, 0);
   ArrayResize(g_orders, 0, 1024);
   g_lastTop = 0;
   g_lastWait = 0;
   g_lastReact = 0;
   if(StringFind(_Symbol, "XAU") < 0 && StringFind(_Symbol, "GOLD") < 0)
      Print("VGC: warning - researched on XAUUSD only");
   string chain = "";
   for(int i = 0; i < g_nChain; i++)
      chain += TFName(g_chain[i]) + ">";
   PrintFormat("VGC: chain %s%s  wait TF %s  reactions on %s", chain, InpUseM1Stage ? "M1" : "", TFName(g_waitTF), TFName(InpReactTF));
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   if(MQLInfoInteger(MQL_TESTER) && !MQLInfoInteger(MQL_OPTIMIZATION))
      ReportStats(InpWriteCSV);
   if(g_atrHandle != INVALID_HANDLE)
      IndicatorRelease(g_atrHandle);
   if(g_emaHandle != INVALID_HANDLE)
      IndicatorRelease(g_emaHandle);
  }

void OnTick()
  {
   ManagePositions();
   bool newReact = NewBar(InpReactTF, g_lastReact);
   bool newTop   = NewBar(g_chain[0], g_lastTop);
   bool newWait  = NewBar(g_waitTF, g_lastWait);
   if(newReact)
      OnNewReactBar();       // reactions of existing setups on the bar that just closed
   if(newTop)
      OnNewTopBar();         // new volume gap -> setup or wait
   if(newWait)
      OnNewWaitBar();        // resolve a pending wait
   ManageSetups();           // arm limit orders / expire setups
  }

//--- custom optimisation criterion: t-statistic of the net R per trade
double OnTester()
  {
   double r[];
   int kinds[];
   datetime tin[], tout[];
   double pnl[];
   int n = CollectR(r, kinds, tin, tout, pnl);
   if(n < InpMinTradesScore || n < 2)
      return -100.0;
   double m = 0.0, v = 0.0;
   for(int i = 0; i < n; i++)
      m += r[i];
   m /= n;
   for(int i = 0; i < n; i++)
      v += (r[i] - m) * (r[i] - m);
   v /= (n - 1);
   if(v <= 0.0)
      return 0.0;
   return m / MathSqrt(v) * MathSqrt((double)n);
  }
//+------------------------------------------------------------------+
