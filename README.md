# hayati

بازبینی و ابزار بک‌تست استراتژی باکس حجمی (Volume Profile Fixed Range) برای
صندوق‌های ETF بورس ایران.

## محتویات

| فایل | چیست |
|---|---|
| `docs/REVIEW-monthly-dashboard.md` | بازبینی `dashboard_monthly.py` و تعریف باکس — **از اینجا شروع کنید** |
| `tools/vp_box.py` | چهار تعریف باکس: سه انتخاب‌گر دره (پورت Pine) و سه‌بین‌پرحجم (پورت `dash.html`) |
| `tools/verify_box.py` | تست تفاضلی پورت دره در برابر رونویسی مستقل از Pine |
| `tools/monthly_backtest.py` | بک‌تست ماهانه: نرخ پایه، تست جایگشت، هندسهٔ ۱:۱، تفکیک درآمد ثابت |
| `tools/intramonth_test.py` | همان آزمون روی **پنجرهٔ دوم**: باکسِ ماهِ جاری تا امروز |
| `tools/liquidity.py` | روزِ خروج از هر پوزیشن، واحدمحور و مقیاس‌آزاد |
| `tools/build_dashboard.py` | داشبورد HTML تک‌فایل با ۹ پنل بک‌تست و کلید انتخاب تعریف باکس |
| `tools/snapshot_dashboard.py` | داشبورد تصمیم و پرتفو از خروجی `export_monthly_risk.py` |
| `tools/portfolio_dashboard.py` | **داشبورد پرتفوی چنددارایی** — از `dashboard_monthly.html` |
| `data/risk_export_20260921.txt` | خروجی واقعی اجرای ۱۴۰۵/۰۶/۳۰ — ۱۴۲ نماد |
| `data/dashboard_monthly_20260921.html` | داشبورد واقعی — منبع ۱۳۸ نماد و ۶۱۵ معامله |

## اجرا

```bash
python3 tools/verify_box.py                         # صحت پورت
python3 tools/monthly_backtest.py --data data_auto \
    --iters 20000 --json data/evidence_month.json        # پنجرهٔ ۱
python3 tools/intramonth_test.py --data data_auto \
    --iters 20000 --json data/evidence_intramonth.json   # پنجرهٔ ۲
python3 tools/liquidity.py --data data_auto --holdings data/holdings.txt \
    --out data/liquidity.json
python3 tools/build_dashboard.py --data data_auto --out dashboard.html
python3 tools/snapshot_dashboard.py --in data/risk_export_20260921.txt \
    --out decision.html --capital 1000000000
python3 tools/portfolio_dashboard.py --in dashboard_monthly.html \
    --out portfolio.html --capital 1000000000
```

### دو پنجره، دو معنی

یک نکته که تا آخر پروژه گم بود و حالا هر دو سرش اندازه گرفته شده:

| | باکس از | بازده اندازه‌گرفته‌شده | کجا دیده می‌شود |
|---|---|---|---|
| **پنجرهٔ ۱** | ماه **قبلِ** کامل‌شده | کل ماه بعد | ستون «وضعیت ماه قبل» |
| **پنجرهٔ ۲** | **همین ماه تا امروز** | از امروز تا پایان همین ماه | چراغ زندهٔ داشبورد |

این دو می‌توانند هم‌زمان خلاف هم بگویند و تناقض نیست. `monthly_backtest.py`
پنجرهٔ ۱ را می‌سنجد و `intramonth_test.py` پنجرهٔ ۲ را.

`portfolio_dashboard.py` چهار آرایهٔ جاسازی‌شدهٔ `dashboard_monthly.html` را
بیرون می‌کشد (TODAY، TRADES، SUMMARY، SIGNALS) و با همان تم، ده تب می‌سازد:
محرک‌ها، پرتفوی من، تصمیم امروز، پرتفوی هدف، تراز پرتفو، **شواهد**، بک‌تست،
همبستگی دسته‌ها، همهٔ نمادها، سلامت داده. سرمایه، وزن عامل‌ها، تعداد پوزیشن،
کف استاپ و سقف وزن در خود صفحه تنظیم می‌شوند. تب «شواهد» را از
`data/evidence_month.json` و `data/evidence_intramonth.json` می‌خواند و ستون
نقدشوندگی را از `data/liquidity.json` — اگر نبودند، تب می‌گوید چه دستوری را
اجرا کنید.

`snapshot_dashboard.py` خروجی متنی `export_monthly_risk.py` را می‌خواند و
صفحهٔ تصمیم + پرتفو می‌سازد: سایز هر پوزیشن از روی فاصله تا کف باکس، با
`--top`، `--total-risk` و `--capital`. بک‌تست ندارد — ورودی‌اش عکس لحظه‌ای
است، نه سری زمانی.

`build_dashboard.py` همان تحلیل را در یک صفحهٔ HTML خودکفا می‌ریزد. با
`--artifact` اسکلت `html/head/body` را حذف می‌کند تا مستقیم روی claude.ai
منتشر شود، و `--note` یک بنر بالای صفحه می‌گذارد.

`--data` پوشهٔ CSVهای روزانه است (خروجی `algotik_tse` یا BrsApi). ستون تاریخ و
`close` لازم است؛ `high`/`low`/`volume` اگر باشند استفاده می‌شوند.

وابستگی ندارد — فقط کتابخانهٔ استاندارد پایتون ۳.

## آنچه این ابزار متفاوت انجام می‌دهد

بک‌تست‌های قبلی نرخ برد را بدون **نرخ پایه** گزارش می‌کردند. در بازاری که ماه
قبل ۹۸٫۶٪ نمادها بالای باکسشان بسته‌اند، «۷۷٫۹٪ برد» احتمالاً خودِ نرخ پایه است.

سه چیز اضافه می‌کند:

- **نرخ پایه** کنار هر عدد شرطی
- **تست جایگشت** — برچسب سیگنال داخل هر ماه به‌هم می‌ریزد، پس حرکت کل بازار
  خنثی می‌شود. با ۱۴۵ نماد همبسته روی ۶ ماه، t معمولی چند برابر بزرگ‌تر از
  واقعیت درمی‌آید
- **هندسهٔ ۱:۱** خود `CLAUDE.md` (ورود روی پولبک، نرخ «حمایت خالی»)

کف p برابر `۱/(تکرار+۱)` است، نه تابع تعداد ماه: برچسب داخل هر ماه جابه‌جا
می‌شود و هر ماه ده‌ها نماد دارد. آنچه تعداد ماه محدود می‌کند **تعمیم‌پذیری**
است — ۹ ماه یک رژیم بازار است، نه همهٔ رژیم‌ها.

## ⚠️ کلید API

کلید BrsApi در نسخه‌های قبلی `brsapi_download_backtest.py` به‌صورت متن ساده در
سورس بود و باید ابطال شود. کلید تازه را فقط از متغیر محیطی بخوانید:

```python
API_KEY = os.environ["BRSAPI_KEY"]
```
