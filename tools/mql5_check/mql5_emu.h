// Tiny MQL5 runtime emulator: bar-data access + logging trade calls (one tick per base bar open).
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
enum ENUM_ORDER_TYPE { ORDER_TYPE_BUY, ORDER_TYPE_SELL, ORDER_TYPE_BUY_LIMIT, ORDER_TYPE_SELL_LIMIT };
enum ENUM_ORDER_TYPE_FILLING { ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN };
enum ENUM_ORDER_TYPE_TIME { ORDER_TIME_GTC, ORDER_TIME_DAY, ORDER_TIME_SPECIFIED };
enum ENUM_SYMBOL_INFO_DOUBLE { SYMBOL_BID, SYMBOL_ASK, SYMBOL_POINT, SYMBOL_TRADE_TICK_SIZE, SYMBOL_TRADE_TICK_VALUE, SYMBOL_VOLUME_MIN, SYMBOL_VOLUME_MAX, SYMBOL_VOLUME_STEP };
enum ENUM_SYMBOL_INFO_INTEGER { SYMBOL_SPREAD, SYMBOL_TRADE_STOPS_LEVEL, SYMBOL_DIGITS };
enum ENUM_POSITION_PROPERTY_INTEGER { POSITION_MAGIC, POSITION_TIME, POSITION_TYPE, POSITION_IDENTIFIER };
enum ENUM_POSITION_PROPERTY_DOUBLE { POSITION_PRICE_OPEN, POSITION_SL, POSITION_TP };
enum ENUM_POSITION_PROPERTY_STRING { POSITION_SYMBOL };
enum ENUM_POSITION_TYPE { POSITION_TYPE_BUY, POSITION_TYPE_SELL };
enum ENUM_ORDER_PROPERTY_INTEGER { ORDER_MAGIC };
enum ENUM_ORDER_PROPERTY_STRING { ORDER_SYMBOL };
enum ENUM_DEAL_PROPERTY_INTEGER { DEAL_MAGIC, DEAL_POSITION_ID, DEAL_ENTRY, DEAL_TIME };
enum ENUM_DEAL_PROPERTY_DOUBLE { DEAL_PROFIT, DEAL_SWAP, DEAL_COMMISSION, DEAL_FEE };
enum ENUM_DEAL_PROPERTY_STRING { DEAL_SYMBOL };
enum ENUM_DEAL_ENTRY { DEAL_ENTRY_IN, DEAL_ENTRY_OUT, DEAL_ENTRY_INOUT, DEAL_ENTRY_OUT_BY };
enum ENUM_ACCOUNT_INFO_DOUBLE { ACCOUNT_EQUITY, ACCOUNT_BALANCE };
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
inline double MathLog10(double x) { return std::log10(x); } inline double MathSqrt(double x) { return std::sqrt(x); }
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
inline double SymbolInfoDouble(const string&, ENUM_SYMBOL_INFO_DOUBLE p) {
  switch (p) { case SYMBOL_BID: return EMU_BID(); case SYMBOL_ASK: return EMU_BID() + EMU_SPREAD(); case SYMBOL_POINT: return 0.01; case SYMBOL_TRADE_TICK_SIZE: return 0.01;
    case SYMBOL_TRADE_TICK_VALUE: return 1.0; case SYMBOL_VOLUME_MIN: return 0.01; case SYMBOL_VOLUME_MAX: return 100; case SYMBOL_VOLUME_STEP: return 0.01; } return 0; }
inline long SymbolInfoInteger(const string&, ENUM_SYMBOL_INFO_INTEGER p) { if (p == SYMBOL_SPREAD) return (long)std::lround(EMU_SPREAD() / 0.01); if (p == SYMBOL_DIGITS) return 2; return 0; }
inline int PositionsTotal() { return 0; } inline ulong PositionGetTicket(int) { return 0; }
inline string PositionGetString(ENUM_POSITION_PROPERTY_STRING) { return ""; } inline long PositionGetInteger(ENUM_POSITION_PROPERTY_INTEGER) { return 0; }
inline double PositionGetDouble(ENUM_POSITION_PROPERTY_DOUBLE) { return 0; }
inline int OrdersTotal() { return 0; } inline ulong OrderGetTicket(int) { return 0; } inline bool OrderSelect(ulong) { return false; }
inline string OrderGetString(ENUM_ORDER_PROPERTY_STRING) { return ""; } inline long OrderGetInteger(ENUM_ORDER_PROPERTY_INTEGER) { return 0; }
inline bool OrderCalcProfit(ENUM_ORDER_TYPE t, const string&, double vol, double a, double b, double& pr) { pr = (t == ORDER_TYPE_BUY ? (b - a) : (a - b)) * 100.0 * vol; return true; }
inline double AccountInfoDouble(ENUM_ACCOUNT_INFO_DOUBLE) { return 10000.0; }
inline bool HistorySelect(datetime, datetime) { return true; } inline int HistoryDealsTotal() { return 0; } inline ulong HistoryDealGetTicket(int) { return 0; }
inline long HistoryDealGetInteger(ulong, ENUM_DEAL_PROPERTY_INTEGER) { return 0; } inline double HistoryDealGetDouble(ulong, ENUM_DEAL_PROPERTY_DOUBLE) { return 0; }
inline string HistoryDealGetString(ulong, ENUM_DEAL_PROPERTY_STRING) { return ""; }
inline int FileOpen(const string&, int, short = ';') { return INVALID_HANDLE; }
template<class... A> uint FileWrite(int, A...) { return 0; }
inline void FileClose(int) {}
inline int ObjectFind(long, const string&) { return -1; }
inline bool ObjectCreate(long, const string&, ENUM_OBJECT, int, datetime, double, datetime = 0, double = 0) { return true; }
inline bool ObjectMove(long, const string&, int, datetime, double) { return true; }
inline bool ObjectSetInteger(long, const string&, ENUM_OBJECT_PROPERTY_INTEGER, long) { return true; }
inline bool ObjectSetString(long, const string&, ENUM_OBJECT_PROPERTY_STRING, const string&) { return true; }
inline int MQLInfoInteger(ENUM_MQL_INFO_INTEGER) { return 0; }
class CTrade {
  ulong m_last = 0; static ulong& seq() { static ulong s = 1000; return s; }
  bool rec(const char* kind, double lots, double price, double sl, double tp, const string& c) {
    m_last = ++seq(); printf("%s|TRADE %s lots=%.2f price=%.2f sl=%.2f tp=%.2f cmt=%s\n", TimeToString(EMU_NOW()).c_str(), kind, lots, price, sl, tp, c.c_str()); return true; }
public:
  void SetExpertMagicNumber(ulong) {} void SetDeviationInPoints(ulong) {}
  void SetTypeFilling(ENUM_ORDER_TYPE_FILLING) {} bool SetTypeFillingBySymbol(const string&) { return true; }
  bool BuyLimit(double v, double p, const string& = "", double sl = 0, double tp = 0, ENUM_ORDER_TYPE_TIME = ORDER_TIME_GTC, datetime = 0, const string& c = "") { return rec("BUY_LIMIT", v, p, sl, tp, c); }
  bool SellLimit(double v, double p, const string& = "", double sl = 0, double tp = 0, ENUM_ORDER_TYPE_TIME = ORDER_TIME_GTC, datetime = 0, const string& c = "") { return rec("SELL_LIMIT", v, p, sl, tp, c); }
  bool Buy(double v, const string& = "", double = 0, double sl = 0, double tp = 0, const string& c = "") { return rec("BUY", v, SymbolInfoDouble("", SYMBOL_ASK), sl, tp, c); }
  bool Sell(double v, const string& = "", double = 0, double sl = 0, double tp = 0, const string& c = "") { return rec("SELL", v, SymbolInfoDouble("", SYMBOL_BID), sl, tp, c); }
  bool OrderDelete(ulong) { return true; } bool PositionModify(ulong, double, double) { return true; } bool PositionClose(ulong, ulong = ULONG_MAX) { return true; }
  ulong ResultOrder() const { return m_last; } uint ResultRetcode() const { return 10009; } string ResultRetcodeDescription() const { return "done"; }
};
