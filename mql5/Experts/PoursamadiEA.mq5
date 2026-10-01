//+------------------------------------------------------------------+
//| PoursamadiEA.mq5                                                  |
//| Two of M. A. Poursamadi's published setups on XAUUSD, in the form  |
//| that held up in a 2012-2025 out-of-sample backtest:                |
//|   * SP2L (Spike-2Leg) on H1: 3-candle spike with a price gap, in   |
//|     the direction of the H1 EMA-200 trend; buy-limit on the low of |
//|     the previous candle (2nd leg), add-on at 50% to the stop,      |
//|     SL behind the spike's first candle, TP 3R                      |
//|   * Pro BTB on M15: a strong candle that closes through >= 2       |
//|     still-unbroken previous-day highs (lows) at once; market entry |
//|     after the first candle that returns to the breakout close and |
//|     closes back on the breakout side; SL behind the breakout       |
//|     candle, TP 3R; only inside Poursamadi's gold windows          |
//|     10:00-13:00 and 15:30-18:00 (broker GMT+3 clock)               |
//| Money management: risk % of balance per trade, optional            |
//| anti-martingale (x mult after each win of the same setup, back to |
//| base after a loss, capped).  Positions are closed after 24 h.     |
//| Works on any chart timeframe (reads H1 / M15 itself).             |
//| Needs a HEDGING account (several positions at once).               |
//+------------------------------------------------------------------+
#property copyright "research build"
#property version   "1.30"

#include <Trade/Trade.mqh>

input group "Setups"
input bool   InpUseSP2L        = true;   // trade SP2L (H1)
input bool   InpUseBTB         = true;   // trade Pro BTB (M15)

input group "Money management"
input double InpRiskPct        = 0.5;    // base risk per trade, % of balance
input bool   InpAntiMartingale = true;   // raise risk after wins (per setup)
input double InpAMMult         = 1.5;    // risk multiplier per consecutive win
input double InpAMCapPct       = 1.5;    // maximum risk per trade, %
input double InpMaxSpreadUSD   = 1.00;   // skip new entries when spread is wider ($)
input int    InpMaxHoldHours   = 24;     // close any position after this many hours
input bool   InpRoundNearest   = true;   // round lots to the nearest step (false = always down)
input double InpMinLotMaxX     = 2.0;    // allow the minimum lot if it risks <= x times the plan (0 = skip)
input double InpMaxMarginPct   = 30.0;   // one trade may use at most this % of free margin (0 = off)

input group "SP2L (H1)"
input int    InpSpikeBars      = 3;      // strong candles in the spike
input double InpSpikeATR       = 1.0;    // spike move >= x ATR(14)
input int    InpSP2LWait       = 12;     // candles to wait for the 2nd leg
input double InpSP2LRR         = 3.0;    // take profit, R
input bool   InpSP2LAddOn      = true;   // add-on limit at 50% entry-SL
input bool   InpSP2LTrend      = true;   // only with the H1 EMA trend
input int    InpTrendEMA       = 200;    // EMA period (H1) for the trend filter

input group "Pro BTB"
input ENUM_TIMEFRAMES InpBTBTF = PERIOD_M15; // BTB timeframe (M15 validated; M5 also positive)
input int    InpMinLevels      = 2;      // min. previous-day levels broken by one candle
input bool   InpBTBStrong      = true;   // breakout candle must be a strong trend candle
input double InpBTBRR          = 3.0;    // take profit, R
input int    InpBTBExpiry      = 100;    // candles to wait for the return to break-even
input int    InpLevelLife      = 2000;   // candles an unbroken level stays valid
input bool   InpBTBWindows     = true;   // only 10:00-13:00 and 15:30-18:00 (GMT+3 clock)
input int    InpClockShiftMin  = 0;      // minutes to add to server time to get GMT+3

input group "Misc"
input long   InpMagic          = 26100;  // magic (SP2L main; +1 add-on; +2 BTB)
input bool   InpVerbose        = true;   // log setups and trades

//--- SP2L state --------------------------------------------------------------------------------
struct SPSetup
  {
   int      dir;        // +1 buy, -1 sell
   datetime kTime;      // open time of the last spike candle
   double   stopPx;     // SL: beyond the first spike candle
   int      seen;       // candles evaluated since the spike
  };
struct SPTrade
  {
   int      state;      // 0 idle, 1 order pending, 2 in trade
   ulong    mainId;     // order ticket == position id
   ulong    addId;
   double   entry, stopPx, tpPx, lots;
   datetime fillTime;
  };
SPSetup  g_spPend[];
SPTrade  g_sp[2];
datetime g_spExitBar[2];     // H1 bar in which the last SP2L trade of that side ended
datetime g_lastH1 = 0;

//--- BTB state ---------------------------------------------------------------------------------
struct Level
  {
   int    dir;
   double px;
   long   born;     // M15 candle counter when the level appeared
  };
struct BTBSetup
  {
   int      dir;
   double   be;      // close of the breakout candle
   double   stopPx;  // beyond the breakout candle
   long     born;
  };
Level    g_lv[];
BTBSetup g_bs[];
ulong    g_btbOpen[];          // open BTB position ids (for the win/loss streak)
long     g_m15Count = 0;
datetime g_lastM15 = 0;

CTrade   g_trade;
int      g_streak[2];          // consecutive wins: 0 SP2L, 1 BTB

//+------------------------------------------------------------------+
int DirIdx(int dir) { return dir == 1 ? 0 : 1; }

string GVName(int i) { return StringFormat("PSE_%d_%s_streak_%d", (int)InpMagic, _Symbol, i); }

void SaveStreak(int i) { GlobalVariableSet(GVName(i), (double)g_streak[i]); }

double RiskPct(int setup)
  {
   double r = InpRiskPct;
   if(InpAntiMartingale)
      r = MathMin(InpAMCapPct, InpRiskPct * MathPow(InpAMMult, (double)g_streak[setup]));
   return r;
  }

double SpreadUSD() { return SymbolInfoDouble(_Symbol, SYMBOL_ASK) - SymbolInfoDouble(_Symbol, SYMBOL_BID); }

// lots so that a loss from entry to stop costs `pct`% of balance divided by `units` positions
double LotsFor(double entry, double stopPx, double pct, double units)
  {
   double loss = 0.0;
   ENUM_ORDER_TYPE t = entry > stopPx ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   if(!OrderCalcProfit(t, _Symbol, 1.0, entry, stopPx, loss) || loss == 0.0)
      return 0.0;
   double money = AccountInfoDouble(ACCOUNT_BALANCE) * pct / 100.0 / units;
   double lots = money / MathAbs(loss);
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   // nearest lot step instead of always rounding down (at high gold prices the lots are small
   // and flooring cut the real risk by up to half)
   lots = InpRoundNearest ? MathRound(lots / step) * step : MathFloor(lots / step) * step;
   if(lots < vmin)
     {
      // below the broker minimum: trade the minimum lot only if that risks at most
      // InpMinLotMaxX times the planned amount, otherwise skip the trade
      if(InpMinLotMaxX > 0 && vmin * MathAbs(loss) <= InpMinLotMaxX * money)
         return vmin;
      return 0.0;
     }
   lots = MathMin(lots, vmax);
   // margin guard: with high risk and a tight stop the position can get large; cap it so one
   // trade never uses more than InpMaxMarginPct of the free margin (no margin call / stop-out)
   if(InpMaxMarginPct > 0)
     {
      double m1 = 0.0;
      if(OrderCalcMargin(t, _Symbol, 1.0, entry, m1) && m1 > 0)
        {
         double maxLots = AccountInfoDouble(ACCOUNT_MARGIN_FREE) * InpMaxMarginPct / 100.0 / m1;
         maxLots = MathFloor(maxLots / step) * step;
         if(lots > maxLots)
            lots = maxLots;
         if(lots < vmin)
            return 0.0;
        }
     }
   return lots;
  }

double Np(double p) { return NormalizeDouble(p, _Digits); }

bool InWindow(datetime t)
  {
   MqlDateTime d;
   TimeToStruct(t + InpClockShiftMin * 60, d);
   double hr = d.hour + d.min / 60.0;
   return (hr >= 10.0 && hr < 13.0) || (hr >= 15.5 && hr < 18.0);
  }

bool OrderExists(ulong ticket)
  {
   for(int i = OrdersTotal() - 1; i >= 0; i--)
      if(OrderGetTicket(i) == ticket)
         return true;
   return false;
  }

bool PositionOpen(ulong id)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong tk = PositionGetTicket(i);
      if(tk == 0)
         continue;
      if((ulong)PositionGetInteger(POSITION_IDENTIFIER) == id)
         return true;
     }
   return false;
  }

// deals of a position: filled?, closed?, net result and times
bool PositionHistory(ulong id, bool &filled, bool &closed, double &net, datetime &inTime, datetime &outTime)
  {
   filled = false;
   closed = false;
   net = 0.0;
   inTime = 0;
   outTime = 0;
   if(!HistorySelectByPosition(id))
      return false;
   double volIn = 0.0, volOut = 0.0;
   for(int i = 0; i < HistoryDealsTotal(); i++)
     {
      ulong dt = HistoryDealGetTicket(i);
      if(dt == 0)
         continue;
      long entry = HistoryDealGetInteger(dt, DEAL_ENTRY);
      net += HistoryDealGetDouble(dt, DEAL_PROFIT) + HistoryDealGetDouble(dt, DEAL_COMMISSION)
             + HistoryDealGetDouble(dt, DEAL_SWAP) + HistoryDealGetDouble(dt, DEAL_FEE);
      if(entry == DEAL_ENTRY_IN)
        {
         filled = true;
         volIn += HistoryDealGetDouble(dt, DEAL_VOLUME);
         inTime = (datetime)HistoryDealGetInteger(dt, DEAL_TIME);
        }
      else
        {
         volOut += HistoryDealGetDouble(dt, DEAL_VOLUME);
         outTime = (datetime)HistoryDealGetInteger(dt, DEAL_TIME);
        }
     }
   closed = filled && volOut >= volIn - 1e-9;
   return true;
  }

void UpdateStreak(int setup, double net)
  {
   g_streak[setup] = net > 0.0 ? g_streak[setup] + 1 : 0;
   SaveStreak(setup);
  }

// close positions of this EA that have been open for longer than InpMaxHoldHours
void TimeExits()
  {
   datetime now = TimeCurrent();
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong tk = PositionGetTicket(i);
      if(tk == 0 || PositionGetString(POSITION_SYMBOL) != _Symbol)
         continue;
      long mg = PositionGetInteger(POSITION_MAGIC);
      if(mg < InpMagic || mg > InpMagic + 2)
         continue;
      if(now - (datetime)PositionGetInteger(POSITION_TIME) >= InpMaxHoldHours * 3600)
         g_trade.PositionClose(tk);
     }
  }

//+------------------------------------------------------------------+
//| SP2L                                                              |
//+------------------------------------------------------------------+
bool StrongCandle(const MqlRates &r, int dir)
  {
   double rng = r.high - r.low;
   if(rng <= 0)
      return false;
   if(dir == 1)
      return r.close > r.open && r.close - r.open >= 0.5 * rng && r.close - r.low >= 0.667 * rng;
   return r.close < r.open && r.open - r.close >= 0.5 * rng && r.high - r.close >= 0.667 * rng;
  }

// ATR(14) as a simple average of true range, for candle index e of `rt`
double ATRAt(MqlRates &rt[], int e)
  {
   if(e < 14)
      return 0.0;
   double s = 0.0;
   for(int i = e - 13; i <= e; i++)
     {
      double pc = rt[i - 1].close;
      s += MathMax(rt[i].high - rt[i].low, MathMax(MathAbs(rt[i].high - pc), MathAbs(rt[i].low - pc)));
     }
   return s / 14.0;
  }

bool SpikeEnd(MqlRates &rt[], int k, int dir)
  {
   int ns = InpSpikeBars;
   if(k < ns + 16)
      return false;
   for(int i = k - ns + 1; i <= k; i++)
      if(!StrongCandle(rt[i], dir))
         return false;
   int s0 = k - ns + 1;
   double a = ATRAt(rt, s0 - 1);
   if(a <= 0)
      return false;
   if(dir * (rt[k].close - rt[s0].open) < InpSpikeATR * a)
      return false;
   if(dir == 1)
      return rt[k].low > rt[k - 2].high;        // P-Gap
   return rt[k].high < rt[k - 2].low;
  }

// EMA of H1 closes up to and including candle k (seeded far back, like an indicator)
double TrendEMA(MqlRates &rt[], int k)
  {
   double al = 2.0 / (InpTrendEMA + 1.0);
   double e = rt[0].close;
   for(int i = 1; i <= k; i++)
      e = al * rt[i].close + (1.0 - al) * e;
   return e;
  }

void SPRemovePending(int idx)
  {
   int n = ArraySize(g_spPend);
   for(int i = idx; i < n - 1; i++)
      g_spPend[i] = g_spPend[i + 1];
   ArrayResize(g_spPend, n - 1);
  }

void SPClearPending(int dir)
  {
   for(int i = ArraySize(g_spPend) - 1; i >= 0; i--)
      if(g_spPend[i].dir == dir)
         SPRemovePending(i);
  }

// called on every tick: order filled? trade finished?
void SPSync()
  {
   for(int s = 0; s < 2; s++)
     {
      int dir = s == 0 ? 1 : -1;
      if(g_sp[s].state == 1 && !OrderExists(g_sp[s].mainId))
        {
         bool f, c;
         double net;
         datetime ti, to;
         PositionHistory(g_sp[s].mainId, f, c, net, ti, to);
         if(!f)
           {
            g_sp[s].state = 0;                     // cancelled
            continue;
           }
         g_sp[s].state = 2;
         g_sp[s].fillTime = ti;
         SPClearPending(dir);
         if(InpVerbose)
            PrintFormat("SP2L FILL %s entry=%.2f sl=%.2f tp=%.2f", dir == 1 ? "BUY" : "SELL", g_sp[s].entry,
                        g_sp[s].stopPx, g_sp[s].tpPx);
         if(InpSP2LAddOn && !c)
           {
            double md = Np(0.5 * (g_sp[s].entry + g_sp[s].stopPx));
            double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK), bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
            g_trade.SetExpertMagicNumber(InpMagic + 1);
            bool ok;
            if(dir == 1)
               ok = ask <= md ? g_trade.Buy(g_sp[s].lots, _Symbol, 0, g_sp[s].stopPx, g_sp[s].tpPx, "SP2L add")
                    : g_trade.BuyLimit(g_sp[s].lots, md, _Symbol, g_sp[s].stopPx, g_sp[s].tpPx, ORDER_TIME_GTC, 0, "SP2L add");
            else
               ok = bid >= md ? g_trade.Sell(g_sp[s].lots, _Symbol, 0, g_sp[s].stopPx, g_sp[s].tpPx, "SP2L add")
                    : g_trade.SellLimit(g_sp[s].lots, md, _Symbol, g_sp[s].stopPx, g_sp[s].tpPx, ORDER_TIME_GTC, 0, "SP2L add");
            g_sp[s].addId = ok ? g_trade.ResultOrder() : 0;
           }
        }
      if(g_sp[s].state == 2)
        {
         bool f, c;
         double net;
         datetime ti, to;
         PositionHistory(g_sp[s].mainId, f, c, net, ti, to);
         if(!c)
            continue;
         // main closed: drop the unfilled add-on; finished once the add-on is flat too
         double addNet = 0.0;
         if(g_sp[s].addId != 0)
           {
            if(OrderExists(g_sp[s].addId))
               g_trade.OrderDelete(g_sp[s].addId);
            bool f2, c2;
            double n2;
            datetime ti2, to2;
            PositionHistory(g_sp[s].addId, f2, c2, n2, ti2, to2);
            if(f2 && !c2)
               continue;
            addNet = n2;
            if(to2 > to)
               to = to2;
           }
         UpdateStreak(0, net + addNet);
         g_spExitBar[s] = iTime(_Symbol, PERIOD_H1, iBarShift(_Symbol, PERIOD_H1, to));
         if(InpVerbose)
            PrintFormat("SP2L DONE %s net=%.2f streak=%d", dir == 1 ? "BUY" : "SELL", net + addNet, g_streak[0]);
         g_sp[s].state = 0;
         g_sp[s].addId = 0;
        }
     }
  }

void SPOnNewBar()
  {
   MqlRates rt[];
   int n = CopyRates(_Symbol, PERIOD_H1, 1, 3000, rt);     // closed candles, oldest first
   if(n < 300)
      return;
   int k = n - 1;                                          // the candle that just closed
   // 1) pending setups: the candle that just closed could not fill them -> invalid if it traded
   //    through the stop; expire after InpSP2LWait candles
   for(int i = ArraySize(g_spPend) - 1; i >= 0; i--)
     {
      if(g_spPend[i].kTime >= rt[k].time)
         continue;
      g_spPend[i].seen++;
      double lowSide = g_spPend[i].dir == 1 ? rt[k].low : -rt[k].high;
      double st = g_spPend[i].dir * g_spPend[i].stopPx;
      if(lowSide <= st || g_spPend[i].seen >= InpSP2LWait)
         SPRemovePending(i);
     }
   // 2) new spike on the closed candle
   for(int s = 0; s < 2; s++)
     {
      int dir = s == 0 ? 1 : -1;
      if(g_sp[s].state == 2 || rt[k].time <= g_spExitBar[s])
         continue;
      if(!SpikeEnd(rt, k, dir))
         continue;
      if(InpSP2LTrend)
        {
         double ema = TrendEMA(rt, k);
         if(dir * (rt[k].close - ema) <= 0)
            continue;
        }
      int s0 = k - InpSpikeBars + 1;
      int m = ArraySize(g_spPend);
      ArrayResize(g_spPend, m + 1);
      g_spPend[m].dir = dir;
      g_spPend[m].kTime = rt[k].time;
      g_spPend[m].stopPx = dir == 1 ? rt[s0].low : rt[s0].high;
      g_spPend[m].seen = 0;
      if(InpVerbose)
         PrintFormat("SP2L SETUP %s spike=%s sl=%.2f", dir == 1 ? "BUY" : "SELL", TimeToString(rt[k].time), g_spPend[m].stopPx);
     }
   // 3) one order per side: limit on the previous candle's low (high) for the oldest valid setup
   for(int s = 0; s < 2; s++)
     {
      int dir = s == 0 ? 1 : -1;
      if(g_sp[s].state == 2)
         continue;
      if(g_sp[s].state == 1)
        {
         if(OrderExists(g_sp[s].mainId))
            g_trade.OrderDelete(g_sp[s].mainId);
         g_sp[s].state = 0;
        }
      // every setup whose stop is not beyond the new limit price is void; trade the oldest valid one
      int pick = -1;
      for(int i = 0; i < ArraySize(g_spPend); i++)
        {
         if(g_spPend[i].dir != dir)
            continue;
         double ed = dir == 1 ? rt[k].low : rt[k].high;
         if(dir * (ed - g_spPend[i].stopPx) <= 0)
           {
            SPRemovePending(i);
            i--;
            continue;
           }
         if(pick < 0)
            pick = i;
        }
      if(pick < 0)
         continue;
      if(SpreadUSD() > InpMaxSpreadUSD)
         continue;
      double E = Np(dir == 1 ? rt[k].low : rt[k].high);
      double S = Np(g_spPend[pick].stopPx);
      double T = Np(E + dir * InpSP2LRR * MathAbs(E - S));
      double lots = LotsFor(E, S, RiskPct(0), InpSP2LAddOn ? 1.5 : 1.0);
      if(lots <= 0)
         continue;
      g_trade.SetExpertMagicNumber(InpMagic);
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK), bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      bool ok;
      if(dir == 1)
         ok = ask <= E ? g_trade.Buy(lots, _Symbol, 0, S, T, "SP2L")
              : g_trade.BuyLimit(lots, E, _Symbol, S, T, ORDER_TIME_GTC, 0, "SP2L");
      else
         ok = bid >= E ? g_trade.Sell(lots, _Symbol, 0, S, T, "SP2L")
              : g_trade.SellLimit(lots, E, _Symbol, S, T, ORDER_TIME_GTC, 0, "SP2L");
      if(!ok)
         continue;
      g_sp[s].state = 1;
      g_sp[s].mainId = g_trade.ResultOrder();
      g_sp[s].addId = 0;
      g_sp[s].entry = E;
      g_sp[s].stopPx = S;
      g_sp[s].tpPx = T;
      g_sp[s].lots = lots;
     }
  }

//+------------------------------------------------------------------+
//| Pro BTB                                                           |
//+------------------------------------------------------------------+
void BTBRemoveLevel(int i)
  {
   int n = ArraySize(g_lv);
   g_lv[i] = g_lv[n - 1];
   ArrayResize(g_lv, n - 1);
  }

void BTBRemoveSetup(int i)
  {
   int n = ArraySize(g_bs);
   for(int j = i; j < n - 1; j++)
      g_bs[j] = g_bs[j + 1];
   ArrayResize(g_bs, n - 1);
  }

void BTBEnter(int dir, double stopPx)
  {
   if(SpreadUSD() > InpMaxSpreadUSD)
      return;
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK), bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double E = dir == 1 ? ask : bid;
   double S = Np(stopPx);
   if(dir * (E - S) <= 0)
      return;
   double T = Np(E + dir * InpBTBRR * MathAbs(E - S));
   double lots = LotsFor(E, S, RiskPct(1), 1.0);
   if(lots <= 0)
      return;
   g_trade.SetExpertMagicNumber(InpMagic + 2);
   bool ok = dir == 1 ? g_trade.Buy(lots, _Symbol, 0, S, T, "BTB") : g_trade.Sell(lots, _Symbol, 0, S, T, "BTB");
   if(!ok)
      return;
   int n = ArraySize(g_btbOpen);
   ArrayResize(g_btbOpen, n + 1);
   g_btbOpen[n] = g_trade.ResultOrder();
   if(InpVerbose)
      PrintFormat("BTB ENTRY %s entry=%.2f sl=%.2f tp=%.2f lots=%.2f", dir == 1 ? "BUY" : "SELL", E, S, T, lots);
  }

void BTBSync()
  {
   for(int i = ArraySize(g_btbOpen) - 1; i >= 0; i--)
     {
      bool f, c;
      double net;
      datetime ti, to;
      PositionHistory(g_btbOpen[i], f, c, net, ti, to);
      if(!c)
         continue;
      UpdateStreak(1, net);
      if(InpVerbose)
         PrintFormat("BTB DONE net=%.2f streak=%d", net, g_streak[1]);
      int n = ArraySize(g_btbOpen);
      g_btbOpen[i] = g_btbOpen[n - 1];
      ArrayResize(g_btbOpen, n - 1);
     }
  }

// process one closed M15 candle (rt[k]); trade=false while warming up the level list
void BTBOnCandle(MqlRates &rt[], int k, bool trade)
  {
   g_m15Count++;
   MqlDateTime a, b;
   TimeToStruct(rt[k].time, a);
   TimeToStruct(rt[k - 1].time, b);
   // first candle of a new server day: the previous day's high / low become levels
   if(a.day_of_year != b.day_of_year || a.year != b.year)
     {
      double hi = rt[k - 1].high, lo = rt[k - 1].low;
      for(int i = k - 2; i >= 0; i--)
        {
         MqlDateTime c;
         TimeToStruct(rt[i].time, c);
         if(c.day_of_year != b.day_of_year || c.year != b.year)
            break;
         hi = MathMax(hi, rt[i].high);
         lo = MathMin(lo, rt[i].low);
        }
      int n = ArraySize(g_lv);
      ArrayResize(g_lv, n + 2);
      g_lv[n].dir = 1;
      g_lv[n].px = hi;
      g_lv[n].born = g_m15Count;
      g_lv[n + 1].dir = -1;
      g_lv[n + 1].px = lo;
      g_lv[n + 1].born = g_m15Count;
     }
   // pending setups: return candle?
   for(int i = 0; i < ArraySize(g_bs); i++)
     {
      int dir = g_bs[i].dir;
      if(g_m15Count - g_bs[i].born > InpBTBExpiry || dir * (rt[k].close - g_bs[i].stopPx) <= 0)
        {
         BTBRemoveSetup(i);
         i--;
         continue;
        }
      bool touched = dir == 1 ? rt[k].low <= g_bs[i].be : rt[k].high >= g_bs[i].be;
      if(touched && dir * (rt[k].close - g_bs[i].be) > 0)
        {
         double st = g_bs[i].stopPx;
         BTBRemoveSetup(i);
         i--;
         // entry at the open of the next candle (= now)
         datetime nextOpen = rt[k].time + PeriodSeconds(InpBTBTF);
         if(trade && (!InpBTBWindows || InWindow(nextOpen)))
            BTBEnter(dir, st);
        }
     }
   // breakouts of this candle, per side
   for(int s = 0; s < 2; s++)
     {
      int dir = s == 0 ? 1 : -1;
      int crossed = 0;
      for(int i = ArraySize(g_lv) - 1; i >= 0; i--)
        {
         if(g_lv[i].dir != dir)
            continue;
         bool expired = g_m15Count - g_lv[i].born > InpLevelLife;
         bool broke = dir * (rt[k].close - g_lv[i].px) > 0 && dir * (rt[k - 1].close - g_lv[i].px) <= 0;
         if(expired || broke)
           {
            if(!expired)
               crossed++;
            BTBRemoveLevel(i);
           }
        }
      if(crossed < InpMinLevels || (InpBTBStrong && !StrongCandle(rt[k], dir)))
         continue;
      double be = rt[k].close, st = dir == 1 ? rt[k].low : rt[k].high;
      if(dir * (be - st) <= 0)
         continue;
      int n = ArraySize(g_bs);
      ArrayResize(g_bs, n + 1);
      g_bs[n].dir = dir;
      g_bs[n].be = be;
      g_bs[n].stopPx = st;
      g_bs[n].born = g_m15Count;
      if(trade && InpVerbose)
         PrintFormat("BTB SETUP %s levels=%d be=%.2f sl=%.2f", dir == 1 ? "BUY" : "SELL", crossed, be, st);
     }
  }

void BTBOnNewBars()
  {
   MqlRates rt[];
   int n = CopyRates(_Symbol, InpBTBTF, 1, 1000, rt);
   if(n < 100)
      return;
   int first = n - 1;
   while(first > 1 && rt[first - 1].time > g_lastM15)
      first--;
   for(int k = first; k < n; k++)
      if(rt[k].time > g_lastM15)
         BTBOnCandle(rt, k, true);
   g_lastM15 = rt[n - 1].time;
  }

void BTBWarmUp()
  {
   MqlRates rt[];
   int n = CopyRates(_Symbol, InpBTBTF, 1, InpLevelLife + 400, rt);
   if(n < 100)
      return;
   for(int k = 1; k < n; k++)
      BTBOnCandle(rt, k, false);
   ArrayResize(g_bs, 0);
   g_lastM15 = rt[n - 1].time;
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   if(AccountInfoInteger(ACCOUNT_MARGIN_MODE) != ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
     {
      Print("PoursamadiEA needs a hedging account (it can hold several positions at once).");
      return INIT_FAILED;
     }
   if(InpBTBTF != PERIOD_M15 && InpBTBTF != PERIOD_M5)
      Print("Warning: Pro BTB was only validated on M15 (and M5).");
   g_trade.SetDeviationInPoints(50);
   g_trade.SetTypeFillingBySymbol(_Symbol);
   for(int i = 0; i < 2; i++)
     {
      g_streak[i] = 0;
      if(MQLInfoInteger(MQL_TESTER))
         SaveStreak(i);
      else if(GlobalVariableCheck(GVName(i)))
         g_streak[i] = (int)GlobalVariableGet(GVName(i));
      g_sp[i].state = 0;
      g_sp[i].mainId = 0;
      g_sp[i].addId = 0;
      g_spExitBar[i] = 0;
     }
   ArrayResize(g_spPend, 0);
   ArrayResize(g_lv, 0);
   ArrayResize(g_bs, 0);
   ArrayResize(g_btbOpen, 0);
   g_lastH1 = iTime(_Symbol, PERIOD_H1, 1);
   if(InpUseBTB)
      BTBWarmUp();
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason) {}

void OnTick()
  {
   TimeExits();
   if(InpUseSP2L)
     {
      SPSync();
      datetime h1 = iTime(_Symbol, PERIOD_H1, 1);
      if(h1 > g_lastH1)
        {
         g_lastH1 = h1;
         SPOnNewBar();
        }
     }
   if(InpUseBTB)
     {
      BTBSync();
      if(iTime(_Symbol, InpBTBTF, 1) > g_lastM15)
         BTBOnNewBars();
     }
  }
//+------------------------------------------------------------------+
