# hayati — استراتژی‌های Volume Profile / LVN

انتقال استراتژی‌های Volume Profile از TradingView به MetaTrader 5.

استراتژی بر پایهٔ چهار مفهوم است:

| مفهوم | یعنی چه | کجای کد |
|---|---|---|
| **Volume Profile Fixed Range** | هیستوگرام حجم روی محور قیمت، در یک بازهٔ ثابت از کندل‌ها | `CVolumeProfile::Build()` |
| **حجم افقی** (Horizontal) | همان پروفایل — حجم معامله‌شده در هر سطح قیمتی | `CVolumeProfile` |
| **حجم عمودی** (Vertical) | حجم هر کندل روی محور زمان — برای تأیید شکست یا دفاع از یک سطح | `VolumeTools.mqh` |
| **LVN / HVN** | نواحی کم‌حجم و پرحجم — درّه‌ها و قله‌های پروفایل | `CVolumeProfile::DetectNodes()` |

## ساختار پروژه

```
MQL5/
├── Include/Hayati/
│   ├── VolumeProfile.mqh     موتور پروفایل: ردیف‌ها، POC، Value Area، LVN/HVN
│   └── VolumeTools.mqh       حجم عمودی: RVOL، اسپایک، دلتای تقریبی
├── Indicators/Hayati/
│   └── VPFR_LVN.mq5          اندیکاتور — برای مقایسهٔ چشمی با TradingView
└── Experts/Hayati/
    └── VPFR_LVN_EA.mq5       اکسپرت معامله‌گر

pinescript/                   کدهای اصلی TradingView (مرجع)
docs/
├── MT5-SETUP.md              نصب، کامپایل و بک‌تست
└── STRATEGY.md               مشخصات دقیق استراتژی
```

## وضعیت فعلی

**✅ آماده:** موتور پروفایل، تشخیص LVN/HVN، ابزار حجم عمودی، اندیکاتور، و یک اکسپرت با دو حالت
ورود (شکست از LVN / برگشت از LVN) به‌همراه مدیریت ریسک کامل.

**⏳ در انتظار:** قوانین دقیق ورود و خروجِ استراتژی‌های اصلی از TradingView.
اکسپرت فعلی یک پیاده‌سازی متعارف از منطق LVN است، نه بازتولید کد Pine شما.
تا وقتی کد Pine اضافه نشده، `docs/STRATEGY.md` را به‌عنوان تفاوت‌های شناخته‌شده بخوانید.

شروع کار: [`docs/MT5-SETUP.md`](docs/MT5-SETUP.md)
