// Minimal MQL5 API stubs for a C++ syntax/type check (not a runtime).
#pragma once
#include <string>
#include <vector>
#include <climits>
#include <cmath>
typedef std::string string;
typedef long long datetime;
// ulong comes from sys/types.h (unsigned long, 64-bit)
// uint from sys/types.h
// ushort from sys/types.h
typedef unsigned char uchar;
typedef unsigned int color;
#define INVALID_HANDLE (-1)
#define WRONG_VALUE (-1)
extern string _Symbol; extern double _Point; extern int _Digits;
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
enum ENUM_OBJECT_PROPERTY_INTEGER { OBJPROP_COLOR, OBJPROP_FILL, OBJPROP_BACK, OBJPROP_SELECTABLE, OBJPROP_HIDDEN, OBJPROP_FONTSIZE, OBJPROP_STYLE, OBJPROP_WIDTH };
enum ENUM_OBJECT_PROPERTY_STRING { OBJPROP_TEXT };
enum ENUM_INIT_RETCODE { INIT_SUCCEEDED=0, INIT_FAILED=1, INIT_PARAMETERS_INCORRECT=2 };
#define TRADE_RETCODE_INVALID_FILL 10030
#define FILE_WRITE 2
#define FILE_READ 1
#define FILE_CSV 8
#define FILE_ANSI 32
#define FILE_COMMON 4096
#define TIME_DATE 1
#define TIME_MINUTES 2
#define TIME_SECONDS 4
const color clrRed=1, clrOrange=2, clrDeepPink=3, clrGold=4, clrDodgerBlue=5, clrTurquoise=6, clrDimGray=7, clrSilver=8, clrWhite=9, clrGray=10;
struct MqlRates { datetime time; double open, high, low, close; long tick_volume; int spread; long real_volume; };
struct MqlDateTime { int year, mon, day, hour, min, sec, day_of_week, day_of_year; };
double SymbolInfoDouble(const string&, ENUM_SYMBOL_INFO_DOUBLE);
long SymbolInfoInteger(const string&, ENUM_SYMBOL_INFO_INTEGER);
datetime iTime(const string&, ENUM_TIMEFRAMES, int);
double iClose(const string&, ENUM_TIMEFRAMES, int);
int iBarShift(const string&, ENUM_TIMEFRAMES, datetime, bool exact=false);
int CopyRates(const string&, ENUM_TIMEFRAMES, int, int, std::vector<MqlRates>&);
int CopyBuffer(int, int, int, int, double*);
int iATR(const string&, ENUM_TIMEFRAMES, int);
int iMA(const string&, ENUM_TIMEFRAMES, int, int, ENUM_MA_METHOD, ENUM_APPLIED_PRICE);
bool IndicatorRelease(int);
int PeriodSeconds(ENUM_TIMEFRAMES tf=PERIOD_CURRENT);
datetime TimeCurrent();
bool TimeToStruct(datetime, MqlDateTime&);
datetime StructToTime(MqlDateTime&);
string TimeToString(datetime, int mode=TIME_DATE|TIME_MINUTES);
double NormalizeDouble(double, int);
double MathRound(double); double MathAbs(double); double MathFloor(double); double MathCeil(double);
double MathLog10(double); double MathSqrt(double);
template<class T> T MathMax(T a, T b){return a>b?a:b;}
template<class T> T MathMin(T a, T b){return a<b?a:b;}
int StringSplit(const string&, ushort, std::vector<string>&);
int StringTrimLeft(string&); int StringTrimRight(string&);
int StringLen(const string&); long StringToInteger(const string&);
int StringFind(const string&, const string&, int start=0);
string IntegerToString(long, int len=0, ushort fill=' ');
string DoubleToString(double, int digits=8);
template<class... A> string StringFormat(const string&, A...);
template<class... A> void PrintFormat(const string&, A...);
template<class... A> void Print(A...);
template<class T> string EnumToString(T);
template<class T> int ArrayResize(std::vector<T>& a, int n, int reserve=0){a.resize(n);return n;}
template<class T> int ArraySize(const std::vector<T>& a){return (int)a.size();}
template<class T, size_t N> int ArraySize(const T (&)[N]){return (int)N;}
template<class T> void ZeroMemory(T&);
int PositionsTotal(); ulong PositionGetTicket(int);
string PositionGetString(ENUM_POSITION_PROPERTY_STRING);
long PositionGetInteger(ENUM_POSITION_PROPERTY_INTEGER);
double PositionGetDouble(ENUM_POSITION_PROPERTY_DOUBLE);
int OrdersTotal(); ulong OrderGetTicket(int); bool OrderSelect(ulong);
string OrderGetString(ENUM_ORDER_PROPERTY_STRING);
long OrderGetInteger(ENUM_ORDER_PROPERTY_INTEGER);
bool OrderCalcProfit(ENUM_ORDER_TYPE, const string&, double, double, double, double&);
double AccountInfoDouble(ENUM_ACCOUNT_INFO_DOUBLE);
bool HistorySelect(datetime, datetime); int HistoryDealsTotal(); ulong HistoryDealGetTicket(int);
long HistoryDealGetInteger(ulong, ENUM_DEAL_PROPERTY_INTEGER);
double HistoryDealGetDouble(ulong, ENUM_DEAL_PROPERTY_DOUBLE);
string HistoryDealGetString(ulong, ENUM_DEAL_PROPERTY_STRING);
int FileOpen(const string&, int, short delimiter=';');
template<class... A> uint FileWrite(int, A...);
void FileClose(int);
int ObjectFind(long, const string&);
bool ObjectCreate(long, const string&, ENUM_OBJECT, int, datetime, double, datetime t2=0, double p2=0);
bool ObjectMove(long, const string&, int, datetime, double);
bool ObjectSetInteger(long, const string&, ENUM_OBJECT_PROPERTY_INTEGER, long);
bool ObjectSetString(long, const string&, ENUM_OBJECT_PROPERTY_STRING, const string&);
int MQLInfoInteger(ENUM_MQL_INFO_INTEGER);
class CTrade {
public:
  void SetExpertMagicNumber(ulong); void SetDeviationInPoints(ulong);
  bool SetTypeFilling(ENUM_ORDER_TYPE_FILLING); bool SetTypeFillingBySymbol(const string&);
  bool BuyLimit(double, double, const string& s="", double sl=0, double tp=0, ENUM_ORDER_TYPE_TIME tt=ORDER_TIME_GTC, datetime exp=0, const string& c="");
  bool SellLimit(double, double, const string& s="", double sl=0, double tp=0, ENUM_ORDER_TYPE_TIME tt=ORDER_TIME_GTC, datetime exp=0, const string& c="");
  bool Buy(double, const string& s="", double price=0, double sl=0, double tp=0, const string& c="");
  bool Sell(double, const string& s="", double price=0, double sl=0, double tp=0, const string& c="");
  bool OrderDelete(ulong); bool PositionModify(ulong, double, double); bool PositionClose(ulong, ulong dev=ULONG_MAX);
  ulong ResultOrder() const; uint ResultRetcode() const; string ResultRetcodeDescription() const;
};
string StringSubstr(const string&, int, int len=-1);
int StringReplace(string&, const string&, const string&);
int GetLastError(); bool IsStopped();
int CopyRates(const string&, ENUM_TIMEFRAMES, datetime, datetime, std::vector<MqlRates>&);
