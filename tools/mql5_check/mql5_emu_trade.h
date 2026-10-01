// MQL5 runtime emulator with a simple trade server: pending/market orders, SL/TP, deal history.
// Derived from mql5_emu.h; the driver (emu_trade_main.inc) walks every M5 bar along an
// open -> low/high -> high/low -> close path and calls OnTick() at each of the four prices.
#pragma once
#include <string>
#include <vector>
#include <map>
#include <cstdio>
#include <cstring>
#include <cmath>
#include <climits>
#include <ctime>
#include <algorithm>
#include <type_traits>
#include <sys/types.h>
typedef std::string string;
typedef long long datetime;
typedef unsigned int color;
#define INVALID_HANDLE (-1)
enum ENUM_TIMEFRAMES { PERIOD_CURRENT=0, PERIOD_M1=1, PERIOD_M5=5, PERIOD_M15=15, PERIOD_M30=30, PERIOD_H1=16385, PERIOD_H4=16388, PERIOD_D1=16408, PERIOD_W1=32769, PERIOD_MN1=49153 };
enum ENUM_ORDER_TYPE { ORDER_TYPE_BUY, ORDER_TYPE_SELL, ORDER_TYPE_BUY_LIMIT, ORDER_TYPE_SELL_LIMIT, ORDER_TYPE_BUY_STOP, ORDER_TYPE_SELL_STOP };
enum ENUM_ORDER_TYPE_FILLING { ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN };
enum ENUM_ORDER_TYPE_TIME { ORDER_TIME_GTC, ORDER_TIME_DAY, ORDER_TIME_SPECIFIED };
enum ENUM_SYMBOL_INFO_DOUBLE { SYMBOL_BID, SYMBOL_ASK, SYMBOL_POINT, SYMBOL_TRADE_TICK_SIZE, SYMBOL_TRADE_TICK_VALUE, SYMBOL_VOLUME_MIN, SYMBOL_VOLUME_MAX, SYMBOL_VOLUME_STEP };
enum ENUM_SYMBOL_INFO_INTEGER { SYMBOL_SPREAD, SYMBOL_TRADE_STOPS_LEVEL, SYMBOL_DIGITS };
enum ENUM_POSITION_PROPERTY_INTEGER { POSITION_MAGIC, POSITION_TIME, POSITION_TYPE, POSITION_IDENTIFIER };
enum ENUM_POSITION_PROPERTY_DOUBLE { POSITION_PRICE_OPEN, POSITION_SL, POSITION_TP, POSITION_VOLUME };
enum ENUM_POSITION_PROPERTY_STRING { POSITION_SYMBOL };
enum ENUM_POSITION_TYPE { POSITION_TYPE_BUY, POSITION_TYPE_SELL };
enum ENUM_ORDER_PROPERTY_INTEGER { ORDER_MAGIC, ORDER_TYPE };
enum ENUM_ORDER_PROPERTY_DOUBLE { ORDER_PRICE_OPEN, ORDER_SL, ORDER_TP, ORDER_VOLUME_CURRENT };
enum ENUM_ORDER_PROPERTY_STRING { ORDER_SYMBOL };
enum ENUM_DEAL_PROPERTY_INTEGER { DEAL_MAGIC, DEAL_POSITION_ID, DEAL_ENTRY, DEAL_TIME, DEAL_ORDER, DEAL_TYPE };
enum ENUM_DEAL_PROPERTY_DOUBLE { DEAL_PROFIT, DEAL_SWAP, DEAL_COMMISSION, DEAL_FEE, DEAL_VOLUME, DEAL_PRICE };
enum ENUM_DEAL_PROPERTY_STRING { DEAL_SYMBOL };
enum ENUM_DEAL_ENTRY { DEAL_ENTRY_IN, DEAL_ENTRY_OUT, DEAL_ENTRY_INOUT, DEAL_ENTRY_OUT_BY };
enum ENUM_ACCOUNT_INFO_DOUBLE { ACCOUNT_EQUITY, ACCOUNT_BALANCE };
enum ENUM_ACCOUNT_INFO_INTEGER { ACCOUNT_MARGIN_MODE };
enum ENUM_ACCOUNT_MARGIN_MODE { ACCOUNT_MARGIN_MODE_RETAIL_NETTING, ACCOUNT_MARGIN_MODE_EXCHANGE, ACCOUNT_MARGIN_MODE_RETAIL_HEDGING };
enum ENUM_MQL_INFO_INTEGER { MQL_TESTER, MQL_OPTIMIZATION, MQL_VISUAL_MODE };
enum ENUM_MA_METHOD { MODE_SMA, MODE_EMA };
enum ENUM_APPLIED_PRICE { PRICE_CLOSE };
enum ENUM_OBJECT { OBJ_RECTANGLE, OBJ_TEXT, OBJ_ARROW_BUY, OBJ_ARROW_SELL };
enum ENUM_OBJECT_PROPERTY_INTEGER { OBJPROP_COLOR, OBJPROP_FILL, OBJPROP_BACK, OBJPROP_SELECTABLE, OBJPROP_HIDDEN, OBJPROP_FONTSIZE };
enum ENUM_OBJECT_PROPERTY_STRING { OBJPROP_TEXT };
enum ENUM_INIT_RETCODE { INIT_SUCCEEDED=0, INIT_FAILED=1, INIT_PARAMETERS_INCORRECT=2 };
#define TRADE_RETCODE_INVALID_FILL 10030
#define FILE_WRITE 2
#define FILE_CSV 8
#define FILE_ANSI 32
#define FILE_COMMON 4096
#define TIME_DATE 1
#define TIME_MINUTES 2
const color clrRed=1, clrOrange=2, clrDeepPink=3, clrGold=4, clrDodgerBlue=5, clrTurquoise=6, clrDimGray=7, clrSilver=8, clrWhite=9, clrGray=10;
struct MqlRates { datetime time; double open, high, low, close; long tick_volume; int spread; long real_volume; };
struct MqlDateTime { int year, mon, day, hour, min, sec, day_of_week, day_of_year; };

// ---------------- emulator state ----------------
inline std::map<int, std::vector<MqlRates>>& EMU_TF() { static std::map<int, std::vector<MqlRates>> m; return m; }
inline datetime& EMU_NOW() { static datetime t = 0; return t; }
inline double& EMU_BID() { static double b = 0; return b; }
inline double& EMU_SPREAD() { static double s = 0.2; return s; }
inline string _emu_sym() { return "XAUUSD"; }
static string _Symbol = "XAUUSD"; static double _Point = 0.01; static int _Digits = 2;

inline int PeriodSeconds(ENUM_TIMEFRAMES tf = PERIOD_CURRENT) {
  switch (tf) { case PERIOD_M1: return 60; case PERIOD_M5: return 300; case PERIOD_M15: return 900; case PERIOD_M30: return 1800;
    case PERIOD_H1: return 3600; case PERIOD_H4: return 14400; case PERIOD_D1: return 86400; default: return 300; }
}
inline int _emu_last_le(ENUM_TIMEFRAMES tf, datetime t) {
  auto& v = EMU_TF()[(int)tf];
  auto it = std::upper_bound(v.begin(), v.end(), t, [](datetime a, const MqlRates& r) { return a < r.time; });
  return (int)(it - v.begin()) - 1;
}
inline int _emu_cur(ENUM_TIMEFRAMES tf) { return _emu_last_le(tf, EMU_NOW()); }
inline datetime iTime(const string&, ENUM_TIMEFRAMES tf, int shift) { int i = _emu_cur(tf) - shift; return i >= 0 ? EMU_TF()[(int)tf][i].time : 0; }
inline double iClose(const string&, ENUM_TIMEFRAMES tf, int shift) { int i = _emu_cur(tf) - shift; return i >= 0 ? EMU_TF()[(int)tf][i].close : 0; }
inline int iBarShift(const string&, ENUM_TIMEFRAMES tf, datetime t, bool exact = false) {
  int j = _emu_last_le(tf, t); if (j < 0) return -1;
  if (exact && EMU_TF()[(int)tf][j].time != t) return -1;
  int c = _emu_cur(tf); return c - j < 0 ? 0 : c - j;
}
inline int CopyRates(const string&, ENUM_TIMEFRAMES tf, int start, int count, std::vector<MqlRates>& out) {
  auto& v = EMU_TF()[(int)tf]; int c = _emu_cur(tf); int newest = c - start; int oldest = newest - count + 1;
  if (newest < 0) return -1; if (oldest < 0) oldest = 0;
  out.assign(v.begin() + oldest, v.begin() + newest + 1); return (int)out.size();
}
inline int CopyRates(const string&, ENUM_TIMEFRAMES tf, datetime a, datetime b, std::vector<MqlRates>& out) {
  out.clear(); for (auto& r : EMU_TF()[(int)tf]) if (r.time >= a && r.time <= b && r.time <= EMU_NOW()) out.push_back(r); return (int)out.size();
}
inline int iATR(const string&, ENUM_TIMEFRAMES, int) { return 1; }
inline int iMA(const string&, ENUM_TIMEFRAMES, int, int, ENUM_MA_METHOD, ENUM_APPLIED_PRICE) { return 2; }
inline bool IndicatorRelease(int) { return true; }
inline int CopyBuffer(int h, int, int start, int count, double* out) {
  if (h != 1) return -1;  // only ATR(14) on H1 is emulated
  auto& v = EMU_TF()[(int)PERIOD_H1]; int c = _emu_cur(PERIOD_H1);
  for (int k = 0; k < count; k++) {
    int e = c - start - k; if (e < 14) return -1;
    double s = 0; for (int i = e - 13; i <= e; i++) { double pc = v[i - 1].close; s += std::max(v[i].high - v[i].low, std::max(std::fabs(v[i].high - pc), std::fabs(v[i].low - pc))); }
    out[k] = s / 14.0;
  }
  return count;
}
inline datetime TimeCurrent() { return EMU_NOW(); }
inline bool TimeToStruct(datetime t, MqlDateTime& d) { time_t tt = (time_t)t; struct tm g; gmtime_r(&tt, &g);
  d.year = g.tm_year + 1900; d.mon = g.tm_mon + 1; d.day = g.tm_mday; d.hour = g.tm_hour; d.min = g.tm_min; d.sec = g.tm_sec; d.day_of_week = g.tm_wday; d.day_of_year = g.tm_yday; return true; }
inline datetime StructToTime(MqlDateTime& d) { struct tm g; memset(&g, 0, sizeof g); g.tm_year = d.year - 1900; g.tm_mon = d.mon - 1; g.tm_mday = d.day; g.tm_hour = d.hour; g.tm_min = d.min; g.tm_sec = d.sec; return (datetime)timegm(&g); }
inline string TimeToString(datetime t, int = TIME_DATE | TIME_MINUTES) { MqlDateTime d; TimeToStruct(t, d); char b[32]; snprintf(b, 32, "%04d.%02d.%02d %02d:%02d", d.year, d.mon, d.day, d.hour, d.min); return b; }
inline double NormalizeDouble(double v, int dg) { double p = std::pow(10.0, dg); return std::round(v * p) / p; }
inline double MathRound(double x) { return std::round(x); } inline double MathAbs(double x) { return std::fabs(x); }
inline double MathFloor(double x) { return std::floor(x); } inline double MathCeil(double x) { return std::ceil(x); }
inline double MathLog10(double x) { return std::log10(x); } inline double MathPow(double a, double b) { return std::pow(a, b); } inline double MathSqrt(double x) { return std::sqrt(x); }
template<class T> T MathMax(T a, T b) { return a > b ? a : b; }
template<class T> T MathMin(T a, T b) { return a < b ? a : b; }
inline int StringSplit(const string& s, ushort sep, std::vector<string>& out) { out.clear(); string cur; for (char ch : s) { if ((ushort)ch == sep) { out.push_back(cur); cur.clear(); } else cur += ch; } out.push_back(cur); return (int)out.size(); }
inline int StringTrimLeft(string& s) { size_t i = s.find_first_not_of(" \t"); s = (i == string::npos) ? "" : s.substr(i); return 0; }
inline int StringTrimRight(string& s) { size_t i = s.find_last_not_of(" \t"); s = (i == string::npos) ? "" : s.substr(0, i + 1); return 0; }
inline int StringLen(const string& s) { return (int)s.size(); }
inline long StringToInteger(const string& s) { return atol(s.c_str()); }
inline int StringFind(const string& s, const string& f, int st = 0) { size_t p = s.find(f, st); return p == string::npos ? -1 : (int)p; }
inline string IntegerToString(long v, int = 0, ushort = ' ') { return std::to_string(v); }
inline string DoubleToString(double v, int dg = 8) { char b[64]; snprintf(b, 64, "%.*f", dg, v); return b; }
template<class T> auto _emu_arg(const T& v) { if constexpr (std::is_same_v<T, string>) return v.c_str(); else if constexpr (std::is_enum_v<T>) return (int)v; else return v; }
template<class... A> string StringFormat(const string& f, A... a) { char b[4096]; snprintf(b, sizeof b, f.c_str(), _emu_arg(a)...); return b; }
template<class... A> void PrintFormat(const string& f, A... a) { printf("%s|%s\n", TimeToString(EMU_NOW()).c_str(), StringFormat(f, a...).c_str()); }
inline void _emu_p(const string& s) { fputs(s.c_str(), stdout); }
template<class T> void _emu_p(const T& v) { fputs(std::to_string(v).c_str(), stdout); }
inline void _emu_p(const char* s) { fputs(s, stdout); }
template<class... A> void Print(A... a) { printf("%s|", TimeToString(EMU_NOW()).c_str()); (_emu_p(a), ...); puts(""); }
template<class T> string EnumToString(T v) { return std::to_string((int)v); }
template<class T> int ArrayResize(std::vector<T>& a, int n, int = 0) { a.resize(n); return n; }
template<class T> int ArraySize(const std::vector<T>& a) { return (int)a.size(); }
template<class T, size_t N> int ArraySize(const T (&)[N]) { return (int)N; }
template<class T> void ZeroMemory(T& x) { static_assert(std::is_trivially_copyable_v<T>); memset(&x, 0, sizeof(T)); }

// ---------------- trade server ----------------
struct EmuOrder { ulong ticket; int type; double price, sl, tp, vol; long magic; string cmt; };
struct EmuPos { ulong id; int dir; double price, sl, tp, vol; long magic; datetime time; string cmt; };
struct EmuDeal { ulong ticket, pos; long magic; int entry; int dir; datetime time; double price, vol, profit, commission; string cmt; double sl = 0; };
inline std::vector<EmuOrder>& EMU_ORD() { static std::vector<EmuOrder> v; return v; }
inline std::vector<EmuPos>& EMU_POS() { static std::vector<EmuPos> v; return v; }
inline std::vector<EmuDeal>& EMU_DEALS() { static std::vector<EmuDeal> v; return v; }
inline std::vector<int>& EMU_HSEL() { static std::vector<int> v; return v; }
inline std::map<ulong, std::vector<int>>& EMU_DBYPOS() { static std::map<ulong, std::vector<int>> m; return m; }
inline std::map<ulong, int>& EMU_DBYTK() { static std::map<ulong, int> m; return m; }
inline void _emu_add_deal(const EmuDeal& d) { EMU_DEALS().push_back(d); int i = (int)EMU_DEALS().size() - 1; EMU_DBYPOS()[d.pos].push_back(i); EMU_DBYTK()[d.ticket] = i; }
inline ulong& EMU_SEQ() { static ulong s = 1000; return s; }
inline double& EMU_COMM_PER_LOT() { static double c = 7.0; return c; }   // round trip, $ per lot
inline double& EMU_BAL() { static double b = 10000.0; return b; }
inline int& EMU_OSEL() { static int i = -1; return i; }
inline int& EMU_PSEL() { static int i = -1; return i; }
inline std::map<string, double>& EMU_GV() { static std::map<string, double> m; return m; }
inline double _emu_ask() { return EMU_BID() + EMU_SPREAD(); }

inline void _emu_open(ulong id, int dir, double px, double vol, double sl, double tp, long magic, const string& c) {
  EMU_POS().push_back({id, dir, px, sl, tp, vol, magic, EMU_NOW(), c});
  _emu_add_deal({++EMU_SEQ(), id, magic, 0, dir, EMU_NOW(), px, vol, 0.0, 0.0, c, sl});
}
inline void _emu_close(size_t i, double px) {
  EmuPos p = EMU_POS()[i];
  double pr = p.dir * (px - p.price) * 100.0 * p.vol, cm = -EMU_COMM_PER_LOT() * p.vol;
  EMU_BAL() += pr + cm;
  _emu_add_deal({++EMU_SEQ(), p.id, p.magic, 1, -p.dir, EMU_NOW(), px, p.vol, pr, cm, p.cmt});
  EMU_POS().erase(EMU_POS().begin() + i);
}
// one price point of the path; at_open: the price may have gapped past order / stop levels
inline void EMU_PROCESS(bool at_open) {
  double bid = EMU_BID(), ask = _emu_ask();
  for (size_t i = 0; i < EMU_ORD().size();) {
    EmuOrder o = EMU_ORD()[i]; bool fill = false; double px = o.price; int dir = 1;
    if (o.type == ORDER_TYPE_BUY_LIMIT && ask <= o.price) { fill = true; if (at_open) px = std::min(ask, o.price); }
    if (o.type == ORDER_TYPE_SELL_LIMIT && bid >= o.price) { fill = true; dir = -1; if (at_open) px = std::max(bid, o.price); }
    if (o.type == ORDER_TYPE_BUY_STOP && ask >= o.price) { fill = true; if (at_open) px = std::max(ask, o.price); }
    if (o.type == ORDER_TYPE_SELL_STOP && bid <= o.price) { fill = true; dir = -1; if (at_open) px = std::min(bid, o.price); }
    if (fill) { EMU_ORD().erase(EMU_ORD().begin() + i); _emu_open(o.ticket, dir, px, o.vol, o.sl, o.tp, o.magic, o.cmt); }
    else i++;
  }
  for (size_t i = 0; i < EMU_POS().size();) {
    EmuPos p = EMU_POS()[i]; double q = p.dir == 1 ? bid : ask; bool done = false; double px = 0;
    if (p.sl > 0 && p.dir * (q - p.sl) <= 0) { done = true; px = at_open ? q : p.sl; }
    else if (p.tp > 0 && p.dir * (q - p.tp) >= 0) { done = true; px = at_open ? q : p.tp; }
    if (done) _emu_close(i, px); else i++;
  }
}
inline double SymbolInfoDouble(const string&, ENUM_SYMBOL_INFO_DOUBLE p) {
  switch (p) { case SYMBOL_BID: return EMU_BID(); case SYMBOL_ASK: return _emu_ask(); case SYMBOL_POINT: return 0.01; case SYMBOL_TRADE_TICK_SIZE: return 0.01;
    case SYMBOL_TRADE_TICK_VALUE: return 1.0; case SYMBOL_VOLUME_MIN: return 0.01; case SYMBOL_VOLUME_MAX: return 100; case SYMBOL_VOLUME_STEP: return 0.01; } return 0; }
inline long SymbolInfoInteger(const string&, ENUM_SYMBOL_INFO_INTEGER p) { if (p == SYMBOL_SPREAD) return (long)std::lround(EMU_SPREAD() / 0.01); if (p == SYMBOL_DIGITS) return 2; return 0; }
inline int PositionsTotal() { return (int)EMU_POS().size(); }
inline ulong PositionGetTicket(int i) { if (i < 0 || i >= (int)EMU_POS().size()) return 0; EMU_PSEL() = i; return EMU_POS()[i].id; }
inline bool PositionSelectByTicket(ulong t) { for (size_t i = 0; i < EMU_POS().size(); i++) if (EMU_POS()[i].id == t) { EMU_PSEL() = (int)i; return true; } return false; }
inline string PositionGetString(ENUM_POSITION_PROPERTY_STRING) { return "XAUUSD"; }
inline long PositionGetInteger(ENUM_POSITION_PROPERTY_INTEGER p) { auto& x = EMU_POS()[EMU_PSEL()];
  switch (p) { case POSITION_MAGIC: return x.magic; case POSITION_TIME: return x.time; case POSITION_TYPE: return x.dir == 1 ? POSITION_TYPE_BUY : POSITION_TYPE_SELL; case POSITION_IDENTIFIER: return (long)x.id; } return 0; }
inline double PositionGetDouble(ENUM_POSITION_PROPERTY_DOUBLE p) { auto& x = EMU_POS()[EMU_PSEL()];
  switch (p) { case POSITION_PRICE_OPEN: return x.price; case POSITION_SL: return x.sl; case POSITION_TP: return x.tp; case POSITION_VOLUME: return x.vol; } return 0; }
inline int OrdersTotal() { return (int)EMU_ORD().size(); }
inline ulong OrderGetTicket(int i) { if (i < 0 || i >= (int)EMU_ORD().size()) return 0; EMU_OSEL() = i; return EMU_ORD()[i].ticket; }
inline bool OrderSelect(ulong t) { for (size_t i = 0; i < EMU_ORD().size(); i++) if (EMU_ORD()[i].ticket == t) { EMU_OSEL() = (int)i; return true; } return false; }
inline string OrderGetString(ENUM_ORDER_PROPERTY_STRING) { return "XAUUSD"; }
inline long OrderGetInteger(ENUM_ORDER_PROPERTY_INTEGER p) { auto& x = EMU_ORD()[EMU_OSEL()]; return p == ORDER_MAGIC ? x.magic : x.type; }
inline double OrderGetDouble(ENUM_ORDER_PROPERTY_DOUBLE p) { auto& x = EMU_ORD()[EMU_OSEL()];
  switch (p) { case ORDER_PRICE_OPEN: return x.price; case ORDER_SL: return x.sl; case ORDER_TP: return x.tp; case ORDER_VOLUME_CURRENT: return x.vol; } return 0; }
inline bool OrderCalcProfit(ENUM_ORDER_TYPE t, const string&, double vol, double a, double b, double& pr) { pr = (t == ORDER_TYPE_BUY ? (b - a) : (a - b)) * 100.0 * vol; return true; }
inline double AccountInfoDouble(ENUM_ACCOUNT_INFO_DOUBLE) { return EMU_BAL(); }
inline long AccountInfoInteger(ENUM_ACCOUNT_INFO_INTEGER) { return ACCOUNT_MARGIN_MODE_RETAIL_HEDGING; }
inline bool HistorySelectByPosition(ulong id) { auto it = EMU_DBYPOS().find(id); if (it == EMU_DBYPOS().end()) EMU_HSEL().clear(); else EMU_HSEL() = it->second; return true; }
inline bool HistorySelect(datetime a, datetime b) { EMU_HSEL().clear(); for (size_t i = 0; i < EMU_DEALS().size(); i++) if (EMU_DEALS()[i].time >= a && EMU_DEALS()[i].time <= b) EMU_HSEL().push_back((int)i); return true; }
inline int HistoryDealsTotal() { return (int)EMU_HSEL().size(); }
inline ulong HistoryDealGetTicket(int i) { return EMU_DEALS()[EMU_HSEL()[i]].ticket; }
inline const EmuDeal& _emu_deal(ulong t) { auto it = EMU_DBYTK().find(t); if (it != EMU_DBYTK().end()) return EMU_DEALS()[it->second]; static EmuDeal z{}; return z; }
inline long HistoryDealGetInteger(ulong t, ENUM_DEAL_PROPERTY_INTEGER p) { auto& d = _emu_deal(t);
  switch (p) { case DEAL_MAGIC: return d.magic; case DEAL_POSITION_ID: return (long)d.pos; case DEAL_ENTRY: return d.entry == 0 ? DEAL_ENTRY_IN : DEAL_ENTRY_OUT;
    case DEAL_TIME: return d.time; case DEAL_ORDER: return (long)d.pos; case DEAL_TYPE: return d.dir == 1 ? 0 : 1; } return 0; }
inline double HistoryDealGetDouble(ulong t, ENUM_DEAL_PROPERTY_DOUBLE p) { auto& d = _emu_deal(t);
  switch (p) { case DEAL_PROFIT: return d.profit; case DEAL_COMMISSION: return d.commission; case DEAL_VOLUME: return d.vol; case DEAL_PRICE: return d.price; default: return 0; } }
inline string HistoryDealGetString(ulong, ENUM_DEAL_PROPERTY_STRING) { return "XAUUSD"; }
inline datetime GlobalVariableSet(const string& n, double v) { EMU_GV()[n] = v; return EMU_NOW(); }
inline double GlobalVariableGet(const string& n) { return EMU_GV()[n]; }
inline bool GlobalVariableCheck(const string& n) { return EMU_GV().count(n) > 0; }
inline int FileOpen(const string&, int, short = ';') { return INVALID_HANDLE; }
template<class... A> uint FileWrite(int, A...) { return 0; }
inline void FileClose(int) {}
inline int MQLInfoInteger(ENUM_MQL_INFO_INTEGER p) { return p == MQL_TESTER ? 1 : 0; }
class CTrade {
  ulong m_last = 0; long m_magic = 0; uint m_ret = 10009;
  bool pend(int type, double v, double p, double sl, double tp, const string& c) {
    double bid = EMU_BID(), ask = _emu_ask();
    bool bad = (type == ORDER_TYPE_BUY_LIMIT && p >= ask) || (type == ORDER_TYPE_SELL_LIMIT && p <= bid) ||
               (type == ORDER_TYPE_BUY_STOP && p <= ask) || (type == ORDER_TYPE_SELL_STOP && p >= bid) || v <= 0;
    if (bad) { m_ret = 10015; return false; }
    m_last = ++EMU_SEQ(); m_ret = 10009; EMU_ORD().push_back({m_last, type, p, sl, tp, v, m_magic, c}); return true; }
  bool mkt(int dir, double v, double sl, double tp, const string& c) {
    if (v <= 0) { m_ret = 10014; return false; }
    m_last = ++EMU_SEQ(); m_ret = 10009; _emu_open(m_last, dir, dir == 1 ? _emu_ask() : EMU_BID(), v, sl, tp, m_magic, c); return true; }
public:
  void SetExpertMagicNumber(ulong m) { m_magic = (long)m; } void SetDeviationInPoints(ulong) {}
  void SetTypeFilling(ENUM_ORDER_TYPE_FILLING) {} bool SetTypeFillingBySymbol(const string&) { return true; }
  bool BuyLimit(double v, double p, const string& = "", double sl = 0, double tp = 0, ENUM_ORDER_TYPE_TIME = ORDER_TIME_GTC, datetime = 0, const string& c = "") { return pend(ORDER_TYPE_BUY_LIMIT, v, p, sl, tp, c); }
  bool SellLimit(double v, double p, const string& = "", double sl = 0, double tp = 0, ENUM_ORDER_TYPE_TIME = ORDER_TIME_GTC, datetime = 0, const string& c = "") { return pend(ORDER_TYPE_SELL_LIMIT, v, p, sl, tp, c); }
  bool BuyStop(double v, double p, const string& = "", double sl = 0, double tp = 0, ENUM_ORDER_TYPE_TIME = ORDER_TIME_GTC, datetime = 0, const string& c = "") { return pend(ORDER_TYPE_BUY_STOP, v, p, sl, tp, c); }
  bool SellStop(double v, double p, const string& = "", double sl = 0, double tp = 0, ENUM_ORDER_TYPE_TIME = ORDER_TIME_GTC, datetime = 0, const string& c = "") { return pend(ORDER_TYPE_SELL_STOP, v, p, sl, tp, c); }
  bool Buy(double v, const string& = "", double = 0, double sl = 0, double tp = 0, const string& c = "") { return mkt(1, v, sl, tp, c); }
  bool Sell(double v, const string& = "", double = 0, double sl = 0, double tp = 0, const string& c = "") { return mkt(-1, v, sl, tp, c); }
  bool OrderDelete(ulong t) { for (size_t i = 0; i < EMU_ORD().size(); i++) if (EMU_ORD()[i].ticket == t) { EMU_ORD().erase(EMU_ORD().begin() + i); return true; } return false; }
  bool PositionModify(ulong t, double sl, double tp) { for (auto& p : EMU_POS()) if (p.id == t) { p.sl = sl; p.tp = tp; return true; } return false; }
  bool PositionClose(ulong t, ulong = ULONG_MAX) { for (size_t i = 0; i < EMU_POS().size(); i++) if (EMU_POS()[i].id == t) { _emu_close(i, EMU_POS()[i].dir == 1 ? EMU_BID() : _emu_ask()); return true; } return false; }
  ulong ResultOrder() const { return m_last; } uint ResultRetcode() const { return m_ret; } string ResultRetcodeDescription() const { return "emu"; }
};
