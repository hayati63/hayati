# hayati

بازبینی و ابزار بک‌تست استراتژی باکس حجمی (Volume Profile Fixed Range) برای
صندوق‌های ETF بورس ایران.

## محتویات

| فایل | چیست |
|---|---|
| `docs/REVIEW-monthly-dashboard.md` | بازبینی `dashboard_monthly.py` و تعریف باکس — **از اینجا شروع کنید** |
| `tools/vp_box.py` | دو تعریف باکس: درهٔ حجمی (پورت Pine) و سه بین پرحجم (پورت `dash.html`) |
| `tools/verify_box.py` | تست تفاضلی پورت دره در برابر رونویسی مستقل از Pine |
| `tools/monthly_backtest.py` | بک‌تست ماهانه **با نرخ پایه**، تفکیک درآمد ثابت، و گزارش ماه‌به‌ماه |

## اجرا

```bash
python3 tools/verify_box.py                              # صحت پورت
python3 tools/monthly_backtest.py --data data_auto       # بک‌تست با تعریف دره
python3 tools/monthly_backtest.py --data data_auto --box value_area
```

`--data` پوشهٔ CSVهای روزانه است (خروجی `algotik_tse` یا BrsApi). ستون تاریخ و
`close` لازم است؛ `high`/`low`/`volume` اگر باشند استفاده می‌شوند.

وابستگی ندارد — فقط کتابخانهٔ استاندارد پایتون ۳.

## آنچه این ابزار متفاوت انجام می‌دهد

بک‌تست‌های قبلی نرخ برد را بدون **نرخ پایه** گزارش می‌کردند. در بازاری که ماه
قبل ۹۸٫۶٪ نمادها بالای باکسشان بسته‌اند، «۷۷٫۹٪ برد» احتمالاً خودِ نرخ پایه است.
`monthly_backtest.py` هر عدد شرطی را کنار گروه کنترلش می‌گذارد و t را روی
تعداد **ماه** حساب می‌کند، نه تعداد معامله.

## ⚠️ کلید API

کلید BrsApi در نسخه‌های قبلی `brsapi_download_backtest.py` به‌صورت متن ساده در
سورس بود و باید ابطال شود. کلید تازه را فقط از متغیر محیطی بخوانید:

```python
API_KEY = os.environ["BRSAPI_KEY"]
```
