# -*- coding: utf-8 -*-
"""بورس — یک فایل، بدون نصب هیچ‌چیز.

    python bourse.py

همین. دانلود می‌کند، حساب می‌کند، و یک صفحهٔ HTML می‌سازد و بازش می‌کند.
نه گیت لازم دارد، نه pandas، نه numpy — فقط پایتون.

اولین بار چند دقیقه طول می‌کشد (دانلود کلِ تاریخچه). دفعات بعد سریع‌تر،
چون فقط روزهای جدید را می‌گیرد.

    python bourse.py --telegram        هشدار به تلگرام هم بفرست
    python bourse.py --no-open         صفحه را باز نکن، فقط بساز

برای تلگرام، یک‌بار در همان پنجره:
    set TELEGRAM_BOT_TOKEN=...
    set TELEGRAM_CHAT_ID=...

──────────────────────────────────────────────────────────────────────
این خوانشِ قاعده‌های خودت روی داده است، نه توصیهٔ مالی.
──────────────────────────────────────────────────────────────────────
"""
import argparse
import csv
import gzip
import io
import json
import math
import os
import re
import ssl
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections import defaultdict, OrderedDict
from datetime import date, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent
DATA = HERE / "data_bourse"
OUT = HERE / "dashboard.html"

BASE = "https://cdn.tsetmc.com/api"
HIST = BASE + "/ClosingPrice/GetClosingPriceDailyList/{ins}/0"
WATCH = (BASE + "/ClosingPrice/GetMarketWatch?market=0&paperTypes[0]=1"
         "&paperTypes[1]=8&showTraded=false&withBestLimits=false")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")

# ── تنظیمات، از بک‌تست ─────────────────────────────────────────────
# نوارِ خرید: سقفِ باکس تا +X٪. ماهانه +۳٪ بهترین بود (+۰٫۲۴۷R، t=۵٫۴۱)
# در برابر خودِ سقفِ باکس (+۰٫۰۸۸R، t=۱٫۳۵). هفتگی +۰٫۵٪ بهترین بود.
BAND = {"month": {"aim": 3.0, "hi": 4.0}, "week": {"aim": 0.5, "hi": 2.0}}
MIN_VALUE_BN = 500.0      # کمینه ارزشِ معاملاتِ روزانه، میلیارد ریال
# سقفِ وزنِ هر نماد. **۲۰ بود، ۳۴ شد** — و این مهم‌ترین عددِ اینجاست.
#
# سقفِ تمرکز خودش نقد می‌سازد: وقتی فقط ۲ نماد واجد شرط‌اند و سقف ۲۰٪
# است، ۶۰٪ سرمایه به اجبار نقد می‌ماند. `tools/rotate.py --wcap` روی
# ۱۱ نمادِ بزرگ اندازه‌اش گرفت (۴۰ هفته):
#
#   سقفِ وزن   بازدهِ چرخش      (هولد در همین دوره ۲۵۵٪)
#   بی‌سقف        ۳۰۹٪
#   ۳۴٪           ۱۸۱٪
#   ۲۵٪           ۱۶۴٪
#   ۲۰٪           ۱۴۱٪  ← عددِ قبلی، **بدتر از هولد**
#   ۱۵٪            ۹۸٪
#
# یعنی سقفِ ۲۰٪ کلِ مزیتِ چرخش را می‌خورد و از نگه‌داشتنِ ساده هم بدتر
# می‌شود. علتش نقدِ اجباری است، نه انتخابِ بد.
#
# ۳۴ انتخاب شد نه بی‌سقف: بی‌سقف یعنی گاهی ۱۰۰٪ روی یک صندوقِ اهرمی،
# و یک ماهِ −۲۳٪ (که در ۱۹ ماهِ قبلِ این پنجره رخ داده) کلِ سرمایه را
# می‌برد. ۳۴٪ اجازه می‌دهد سه نماد دفتر را پر کنند.
#
# ⚠️ این یک **انتخابِ ریسک** است، نه یافتهٔ بک‌تست. داده می‌گوید هرچه
# سقف بازتر، بازده بیشتر — در همین رژیمِ صعودی. با --max-weight
# عوضش کن.
MAX_WEIGHT = 34.0
# سقفِ کلِ سرمایهٔ در بازار.
#
# **۶۰ بود، ۱۰۰ شد.** `tools/rotate.py` چهار راه را روی یک سرمایه و یک
# دوره گذاشت (۴۶ هفته، کارمزد روی گردشِ واقعی):
#
#                      هولد  نقدشو  چرخش  هسته+نوسان
#   همهٔ نمادها        ۱۲۶٪   ۷۶٪   ۲۳۶٪     ۱۶۹٪
#   ۱۱ نمادِ بزرگ      ۲۵۵٪  ۱۳۷٪   ۳۰۹٪     ۲۷۹٪
#
# «نقدشو» در هر دسته از هولد عقب ماند. و جاروی نسبتِ هسته **یکنواخت**
# است — هرچه چرخش بیشتر، بازده بیشتر؛ هیچ نقطهٔ بهینهٔ میانی وجود
# ندارد (۰٪ هسته ۳۰۹٪، ۱۰۰٪ هسته ۲۳۹٪). پس نگه‌داشتنِ نقد به‌عنوان
# هدف کنار گذاشته شد؛ نقد فقط باقی‌ماندهٔ نبودِ سیگنال است.
#
# ⚠️ این روی یک رژیمِ **صعودی** اندازه‌گیری شده. دادهٔ رژیمِ نزولی در
# مخزن نیست. با --max-invested می‌شود برش گرداند.
MAX_INVESTED = 100.0
# شرطِ سوم: باکسِ ماهِ **جاری** (از اول ماه میلادی تا امروز) هم باید
# مثبت باشد. قاعدهٔ مصطفی، روی نقران گرفتش: «از ابتدای ماه فعلی یک
# مقاومت ایجاد کرده بالای عدد، ولی هفته‌اش مثبت است... باید جفتش مثبت
# باشد.» و خودش قید را هم گفت: «صد در صد نیست تا وقتی ماه بسته بشه.»
#
# اندازه‌گیری (`tools/curmonth_filter.py`، ۲٬۴۵۷ مشاهده، ۴۲ هفته):
#   ماه قبل + هفتگی          n=۱۲۴۸  مزیت +۰٫۳۹۹  t=۰٫۹۷
#   + ماه جاری بالا          n=۹۸۴   مزیت +۰٫۴۶۷  t=۰٫۸۴
#   + ماه جاری زیر           n=۲۴    — هیچ هفته‌ای ۳ عضو ندارد
#
# مزیت +۰٫۰۶۷ واحد بالا می‌رود ولی t **پایین** می‌آید و ۲۱٪ سیگنال
# حذف می‌شود. یعنی شاهدِ محکمی نیست. روشن است چون قاعدهٔ خودِ اوست و
# ریسکِ مقاومتِ بالای سر را حذف می‌کند؛ با --no-curmonth خاموش.
REQUIRE_CUR_MONTH = True

# ── نرخِ بردِ تاریخی، از بک‌تست ─────────────────────────────────────
# `tools/fund_vs_driver.py` روی ۱۲۱ نماد. هر حالتِ باکس، چند درصد
# دوره‌های بعدش مثبت بوده و میانگینش چه بوده. این‌ها **توصیف** است نه
# پیش‌بینی: دورهٔ اندازه‌گیری ۱۱ ماه و ۴۲ هفته بوده و رژیمش صعودی.
#
#   هفتگی  ۲٬۴۵۷ مشاهده · ۴۲ هفته · پایه +۱٫۳۳٪ و ۶۱٪ مثبت
#   ماهانه   ۵۶۴ مشاهده · ۱۱ ماه  · پایه +۸٫۲۷٪ و ۶۸٪ مثبت
WINRATE = {
    "week": {
        "هر سه بالا":       (984, 71, 2.48),
        "ماه قبل + هفتگی": (1248, 69, 2.52),
        "فقط هفتگی":       (1461, 65, 2.14),
        "فقط ماه قبل":     (1743, 66, 1.96),
        "هفتگی زیر":        (706, 52, -0.21),
        "هر سه زیر":        (242, 43, -1.07),
        "_base":           (2457, 61, 1.33),
    },
    "month": {
        "ماه قبل + هفتگی":  (300, 85, 12.40),
        "فقط هفتگی":        (339, 81, 11.31),
        "فقط ماه قبل":      (397, 79, 10.67),
        "هفتگی زیر":        (162, 36, 2.14),
        "_base":            (564, 68, 8.27),
    },
}


def wr_key(r):
    """نمادِ امروز در کدام سطرِ جدولِ بک‌تست می‌نشیند."""
    m, c, w = r.get("mst"), r.get("cur_st"), r.get("wst")
    if m == "بالا" and c == "بالا" and w == "بالا":
        return "هر سه بالا"
    if m == "بالا" and w == "بالا":
        return "ماه قبل + هفتگی"
    if m == "زیر" and c == "زیر" and w == "زیر":
        return "هر سه زیر"
    if w == "زیر":
        return "هفتگی زیر"
    if w == "بالا":
        return "فقط هفتگی"
    if m == "بالا":
        return "فقط ماه قبل"
    return None
MIN_DAYS = 40

CATEGORY = {
    "املاک": "ارزش مسکن امین شهر دانیک عمارت دی مالک آتیه کاخ کاشانه کلید",
    "اهرمی": "اهرم بیدار توان جهش دوآیکس دوایکس شتاب موج نارنج پیشران",
    "بخشی": "امگا بانکا بانکدار بانکو بانکیا بنکر بنکوداریوش بهین رو تخت گاز خودران دارا یکم دارایکم دارونو دلتا رسانا رویین سمان سورنافود سیمانا سیمانو پالایش پتروآبان پتروآگاه پتروسورین پتروصبا پتروفارس پتروما پتروپاداش پناه پولاد چاشنی چتر",
    "سهامی": "آبنوس آتیمس آس آساس آمیتیس آوا آوان آوید آگاس ابتکار ارزش اطلس اعتبارسهام افق ملت الماس امتیاز انار اوج اکستریم اکسیژن بذر برلیان بزرگ تاراز ترمه تکپاد تیام ثروت ساز پادا پرتو پرتوسا پیروز",
    "شاخصی": "آرام فیروزه هم تراز هم وزن همسنگ هوشمند وبازار کاردان",
    "صندوق_در_صندوق": "تمشک خوشه صنم",
    "طلا": "ریتون زر زرفام زروان زرگر زریران زمرد طلا عیار قلک گلد قیراط لیان مثقال مهرگلد میراث ناب نفیس نگین فارس همیان کهربا گلدا گلدیس گنج گوهر",
    "مختلط": "آسام آفرین زیتون شیلد صنوین ضمان مختلط هیبرید گارانتی",
    "نقره": "سیلور سیمین سیگلو نقرابی نقران نقرسا نقرفام نقرین پلاتا",
    # سینرژی صندوقِ **سپردهٔ کالایی** است، نه سهامی. مصطفی:
    # «سینرژی یک صندوق سهامی نیست، بر اساس نفت و دلار است،
    # به سهام ربطی ندارد.» و راهنما هم بند ۳ آن را کنارِ
    # نهال و کهربا زیرِ «صندوق طلا/کالایی» آورده.
    "کالایی": "سافرون نهال سینرژی",
}
SYM_CAT = {s: c for c, ss in CATEGORY.items() for s in ss.split()}

# ── معاف از قیدِ «پهنای دسته» ──────────────────────────────────────
# قیدِ پهنا فقط وقتی معنا دارد که نماد واقعاً با دسته‌اش حرکت کند.
# این‌ها اندازه‌گیری شده‌اند (همبستگیِ بازده روزانه) و با برچسبشان
# نمی‌خوانند، پس تحمیلِ پهنای آن دسته به آن‌ها غلط است:
#
#   سینرژی  برچسب «سهامی» · همبستگی با شاخص کل **−۰٫۱۷** · محرکش دلار +۰٫۴۰
#   نقران   برچسب «نقره»  · با گواهی شمش **طلا** +۰٫۴۹ بیشتر از نقره +۰٫۴۳
#
# سینرژی ضدِ گروهش حرکت می‌کند، پس «هشت تا از ده تا منفی‌اند» دربارهٔ
# او چیزی نمی‌گوید.
BREADTH_EXEMPT = {"سینرژی", "نقران"}
# ⚠️ TSETMC نام‌ها را با حروف **عربی** می‌دهد: «سينرژي» با ي و ك عربی.
# مقایسهٔ خام با این مجموعه هیچ‌وقت نمی‌گیرد و سینرژی بی‌صدا از دفتر
# می‌افتد — همین اتفاق در اولین اجرای مصطفی افتاد. پس نرمال‌شده مقایسه
# می‌شود، مثل CATEGORY.
NORM_EXEMPT = set()          # بعد از تعریفِ norm پر می‌شود

FIXED_INCOME = ("یاقوت کارا اعتماد همای آوند کمند فیروزا ثابت گنجینه "
                "افران آرامش پاداش بلوط زمرد سپر کیان نسیم")


def norm(s):
    """عربی/فارسی را یکدست کن: ي→ی و ك→ک و حذف فاصله‌ها."""
    return (s.replace("\u064a", "\u06cc").replace("\u0643", "\u06a9")
            .replace("\u200c", "").replace(" ", "").strip())


NORM_CAT = {norm(k): v for k, v in SYM_CAT.items()}
NORM_FIXED = {norm(x) for x in FIXED_INCOME.split()}
NORM_EXEMPT.update(norm(x) for x in BREADTH_EXEMPT)
# نامِ نمایشیِ فارسی، تا «عيار» و «زيتون» عربی در خروجی نیفتد
DISPLAY = {norm(k): k for k in SYM_CAT}

# پرتفوی، از بند ۷ راهنما. برای **آلارمِ خروج** لازم است: تا ندانیم
# چه داریم، نمی‌شود گفت کِی بفروش.
HOLDING = {"نقران": 4238989, "کهربا": 157741, "سمازن": 129712,
           "دوایکس": 111801, "شاراک": 34835, "سقاین": 29021,
           "فباهنر": 1}
NORM_HOLD = {norm(k): v for k, v in HOLDING.items()}


# ══ ۱. دانلود ═══════════════════════════════════════════════════════
def get(url, tries=4, timeout=40):
    ctx = ssl.create_default_context()
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Accept": "application/json",
                "Accept-Encoding": "gzip", "Referer": "https://www.tsetmc.com/"})
            with urllib.request.urlopen(req, timeout=timeout,
                                        context=ctx) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
                return json.loads(raw.decode("utf-8", "replace"))
        except Exception as e:                       # noqa: BLE001
            last = e
            if i < tries - 1:
                time.sleep(2 ** i)
    raise RuntimeError(f"دانلود نشد پس از {tries} تلاش: {last}\n  {url}")


def discover():
    """نماد → insCode، از دیدبان بازار."""
    d = get(WATCH)
    rows = d if isinstance(d, list) else (
        d.get("marketwatch") or d.get("MarketWatch") or [])
    # TSETMC اسمِ فیلدها را بینِ نسخه‌ها عوض کرده. چند املا امتحان
    # می‌شود، و اگر هیچ‌کدام نگرفت **کلیدهای واقعی چاپ می‌شوند** تا
    # بشود درستش کرد — نه اینکه بی‌صدا خالی برگردد.
    SYM_KEYS = ("lva", "lVal18AFC", "symbol", "Symbol", "lva18", "l18")
    INS_KEYS = ("insCode", "InsCode", "inscode", "insCode18")
    out = {}
    for r in rows:
        sym = ins = ""
        for k in SYM_KEYS:
            if r.get(k):
                sym = str(r[k]).strip()
                break
        for k in INS_KEYS:
            if r.get(k):
                ins = str(r[k]).strip()
                break
        if sym and ins and norm(sym) in NORM_CAT:
            out[sym] = ins
    if not out:
        keys = sorted(rows[0].keys()) if rows else []
        raise RuntimeError(
            f"از {len(rows)} ردیفِ دیدبان هیچ نمادِ شناخته‌شده‌ای درنیامد.\n"
            f"  کلیدهای واقعیِ پاسخ: {', '.join(keys[:30])}\n"
            "  این متن را برای من بفرست تا پارسر را درست کنم.")
    return out


def fetch_symbol(sym, ins):
    """تاریخچهٔ روزانه. قیمتِ پایانی (pClosing) نه آخرین معامله."""
    d = get(HIST.format(ins=ins))
    rows = d.get("closingPriceDaily") or d.get("ClosingPriceDaily") or []
    if not rows and isinstance(d, list):
        rows = d
    out = []
    for r in rows:
        try:
            dv = str(r.get("dEven") or r.get("DEven") or "")
            if len(dv) != 8:
                continue
            c = float(r.get("pClosing") or r.get("PClosing") or 0)
            if c <= 0:
                continue
            out.append({
                "date": f"{dv[:4]}-{dv[4:6]}-{dv[6:]}",
                "open": float(r.get("priceFirst") or r.get("PriceFirst") or c),
                "high": float(r.get("priceMax") or r.get("PriceMax") or c),
                "low": float(r.get("priceMin") or r.get("PriceMin") or c),
                "close": c,
                "volume": float(r.get("qTotTran5J")
                                or r.get("QTotTran5J") or 0)})
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda x: x["date"])
    return out


def save(sym, rows):
    DATA.mkdir(exist_ok=True)
    p = DATA / f"{sym}.csv"
    with p.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "open", "high", "low", "close", "volume"])
        for r in rows:
            w.writerow([r["date"], r["open"], r["high"], r["low"],
                        r["close"], r["volume"]])


def load(sym):
    p = DATA / f"{sym}.csv"
    if not p.exists():
        return []
    out = []
    with p.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                y, m, dd = (int(x) for x in r["date"].split("-"))
                out.append({"d": date(y, m, dd),
                            "h": float(r["high"]), "l": float(r["low"]),
                            "c": float(r["close"]),
                            "v": float(r["volume"] or 0)})
            except (TypeError, ValueError, KeyError):
                continue
    return out


# ══ ۱.۵ کاوشِ منابعِ درون‌روزی ═══════════════════════════════════════
# چرا لازم است: باکسِ هفتگی روی ۵ کندلِ روزانه، در ۴۰٪ نمادها اصلاً
# دره‌ای پیدا نمی‌کند (۵۴ از ۱۳۴). بالا بردنِ تعداد ردیف فقط ۴۰٪ را به
# ۳۳٪ می‌آورد و همان‌جا می‌ماند — یعنی مسئله رزولوشنِ **داده** است نه
# پروفایل. با H1 یک هفته ~۱۲۰ کندل دارد به‌جای ۵ تا.
#
# گرفتنِ دستیِ ۱۳۴ اکسپورت از چارتیکس عملی نیست. پس دنبالِ منبعی
# می‌گردیم که خودش بدهد. من از اینجا نمی‌توانم تستش کنم — شبکهٔ این
# کانتینر به هر چهار میزبان ۴۰۳ می‌دهد — ولی ماشینِ تو می‌تواند.
#
#     python bourse.py --probe
#
# هر نامزد را روی یک نماد امتحان می‌کند و می‌گوید کدام جواب داد.
PROBE_INS = "34144395039913458"          # عیار

def _probe_urls(day):
    k = os.environ.get("BRSAPI_KEY", "").strip()
    out = [
        ("TSETMC معاملات روز (cdn)",
         f"{BASE}/Trade/GetTradeHistory/{PROBE_INS}/{day}/false"),
        ("TSETMC معاملات روز (true)",
         f"{BASE}/Trade/GetTradeHistory/{PROBE_INS}/{day}/true"),
        ("TSETMC ریزمعاملات (old)",
         f"http://old.tsetmc.com/tsev2/data/TradeDetail.aspx"
         f"?i={PROBE_INS}&d={day}"),
        ("TSETMC سابقهٔ روزانه (old)",
         f"http://old.tsetmc.com/tsev2/data/InstTradeHistory.aspx"
         f"?i={PROBE_INS}&Top=10&A=0"),
        ("TSETMC سابقهٔ قیمت لحظه‌ای",
         f"{BASE}/ClosingPrice/GetClosingPriceDailyListZ/{PROBE_INS}/0"),
    ]
    if k:
        out += [
            ("BrsApi همهٔ نمادها",
             f"https://BrsApi.ir/Api/Tsetmc/AllSymbols.php?key={k}"),
            ("BrsApi تاریخچه",
             f"https://BrsApi.ir/Api/Tsetmc/History.php"
             f"?key={k}&symbol=عیار"),
        ]
    return out, bool(k)


def probe():
    """هر منبع را امتحان کن و بگو کدام جواب داد. کلید چاپ **نمی‌شود**."""
    from datetime import timedelta
    d = date.today()
    while d.weekday() in (3, 4):        # پنجشنبه و جمعه بازار بسته
        d -= timedelta(days=1)
    day = d.strftime("%Y%m%d")
    urls, has_key = _probe_urls(day)

    print("=" * 68)
    print(f"  کاوشِ منابع — روزِ آزمون {d} · نماد عیار")
    print("=" * 68)
    if not has_key:
        print("\n  BRSAPI_KEY در محیط نیست، پس BrsApi امتحان نشد.")
        print("  اگر کلید داری، در همان پنجره بزن (PowerShell):")
        print('     $env:BRSAPI_KEY="کلیدت"')
        print("  کلید را در چت نفرست — فقط همین‌جا بگذار.")
    print()
    ok_any = False
    for name, url in urls:
        shown = url.split("key=")[0] + "key=***" if "key=" in url else url
        try:
            # URL ممکن است حروف فارسی داشته باشد (symbol=عیار) و
            # urllib آن را ASCII می‌خواهد. بدونِ quote خطای یونیکد
            # می‌دهد — همان که مصطفی روی BrsApi دید.
            safe = urllib.parse.quote(url, safe=":/?&=%")
            req = urllib.request.Request(safe, headers={
                "User-Agent": UA, "Accept": "*/*",
                "Referer": "https://www.tsetmc.com/"})
            with urllib.request.urlopen(req, timeout=25) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
                txt = raw.decode("utf-8", "replace")
                head = txt[:220].replace("\n", " ")
                empty = len(txt.strip()) < 12 or txt.strip() in (
                    "[]", "{}", '{"tradeHistory":[]}')
                mark = "خالی" if empty else "دارد"
                ok_any = ok_any or not empty
                print(f"  [{r.status}] {mark:<5} {len(raw):>9,} بایت  {name}")
                print(f"        {head}")
        except urllib.error.HTTPError as e:      # noqa: PERF203
            print(f"  [{e.code}] ——                      {name}")
        except Exception as e:                   # noqa: BLE001
            print(f"  [---] {type(e).__name__:<18} {name}")
            print(f"        {str(e)[:90]}")
        print()

    print("=" * 68)
    if ok_any:
        print("  دستِ‌کم یکی داده برگرداند. کلِ این خروجی را برای من")
        print("  بفرست تا پارسرش را بنویسم و باکسِ هفتگی روی کندلِ")
        print("  ساعتی ساخته شود — آن‌وقت آن ۴۰٪ حل می‌شود.")
    else:
        print("  هیچ‌کدام داده نداد. باز هم کلِ خروجی را بفرست؛ از خودِ")
        print("  پیام‌های خطا معلوم می‌شود کدام راه باز است.")
    print("=" * 68)
    return 0


# ══ ۱.۷ کندلِ درون‌روزی از ریزمعاملاتِ TSETMC ════════════════════════
# کاوش جواب داد: `old.tsetmc.com/tsev2/data/TradeDetail.aspx?i=..&d=..`
# با کدِ ۲۰۰ و ۹ مگابایت XML برمی‌گردد — تیک‌به‌تیکِ یک روز. از همان
# می‌شود پروفایلِ حجمیِ واقعی ساخت، که حتی از H1 هم ریزتر است.
#
# حجمش زیاد است، پس:
#   • فقط برای نمادهایی گرفته می‌شود که باکسِ روزانه‌شان دره ندارد
#   • فقط برای ۵ روزِ هفتهٔ باکس
#   • بعد از تبدیل به کندلِ ساعتی، خامش دور ریخته و کندل‌ها کش می‌شوند
#     پس اجرای بعدی دوباره دانلود نمی‌کند
TICK_URL = ("http://old.tsetmc.com/tsev2/data/TradeDetail.aspx"
            "?i={ins}&d={day}")
H1DIR = DATA / "h1"


def parse_ticks(xml):
    """(زمان، حجم، قیمت) از XMLِ ریزمعاملات.

    شکلِ **واقعی** که از old.tsetmc.com می‌آید — از خروجیِ `--sample`
    روی ماشینِ مصطفی:

        <?xml version="1.0" encoding="UTF-8"?>
        <rows>
        <row>
        <cell>1</cell>            ← شمارهٔ ردیف
        <cell>12:00:01</cell>     ← زمان
        <cell>100000</cell>       ← حجم
        <cell>663000.00</cell>    ← قیمت
        </row>

    اولین نسخهٔ پارسر دنبالِ `<Row>` و `<Data ss:Type=...>` می‌گشت —
    شکلِ Excel-XML که از حافظه فرض کرده بودم. صفر تیک خواند. این
    نسخه از روی فایلِ واقعی نوشته شده، و هر دو شکل را می‌پذیرد تا اگر
    TSETMC روزی عوضش کرد نشکند.

    ⚠️ ردیف‌ها **از آخر به اول**اند (ردیف ۱ آخرین معاملهٔ روز است)، پس
    قبل از ساختنِ کندل بر اساس زمان مرتب می‌شوند — وگرنه «کلوزِ ساعت»
    اولین معاملهٔ آن ساعت می‌شد نه آخرینش.
    """
    out = []
    for row in re.findall(r"<row[^>]*>(.*?)</row>", xml, re.S | re.I):
        vals = re.findall(r"<(?:cell|Data)[^>]*>(.*?)</(?:cell|Data)>",
                          row, re.S | re.I)
        vals = [v.strip() for v in vals if v.strip()]
        ti = next((i for i, v in enumerate(vals)
                   if re.fullmatch(r"\d{1,2}:\d{2}:\d{2}", v)), None)
        if ti is None:
            continue
        nums = []
        for v in vals[ti + 1:]:
            try:
                nums.append(float(v.replace(",", "")))
            except ValueError:
                pass
        if len(nums) < 2:
            continue
        hh, mm, ss = (int(x) for x in vals[ti].split(":"))
        out.append((hh * 3600 + mm * 60 + ss, hh, nums[0], nums[1]))
    out.sort()                       # از اول روز به آخرِ روز
    return [(hh, vol, px) for _, hh, vol, px in out]


def ticks_to_h1(ticks):
    """تیک‌ها → کندلِ ساعتی."""
    by_h = OrderedDict()
    for hh, vol, px in ticks:
        if px <= 0 or vol <= 0:
            continue
        e = by_h.get(hh)
        if e is None:
            by_h[hh] = {"h": px, "l": px, "c": px, "v": vol}
        else:
            e["h"] = max(e["h"], px)
            e["l"] = min(e["l"], px)
            e["c"] = px
            e["v"] += vol
    return list(by_h.values())


def get_h1(sym, ins, d, quiet=False):
    """کندلِ ساعتیِ یک روز — از کش، وگرنه دانلود و کش کن."""
    H1DIR.mkdir(parents=True, exist_ok=True)
    day = d.strftime("%Y%m%d")
    cache = H1DIR / f"{sym}_{day}.csv"
    if cache.exists():
        out = []
        with cache.open(encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                try:
                    out.append({"h": float(r["high"]), "l": float(r["low"]),
                                "c": float(r["close"]),
                                "v": float(r["volume"])})
                except (KeyError, ValueError):
                    pass
        return out
    try:
        req = urllib.request.Request(
            TICK_URL.format(ins=ins, day=day),
            headers={"User-Agent": UA, "Accept": "*/*",
                     "Referer": "http://www.tsetmc.com/"})
        with urllib.request.urlopen(req, timeout=90) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
        bars = ticks_to_h1(parse_ticks(raw.decode("utf-8", "replace")))
    except Exception as e:                       # noqa: BLE001
        if not quiet:
            print(f"      {sym} {day}: {type(e).__name__}")
        bars = []
    # حتی خالی هم کش می‌شود، تا هر اجرا دوباره ۹ مگابایت نگیرد
    with cache.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["high", "low", "close", "volume"])
        for b in bars:
            w.writerow([b["h"], b["l"], b["c"], b["v"]])
    return bars


def sample():
    """یک روزِ ریزمعاملات را خام ذخیره کن و بگو پارسر چه دید.

    پارسرِ `parse_ticks` را نتوانستم از اینجا تست کنم — شبکهٔ این
    کانتینر به old.tsetmc.com ۴۰۳ می‌دهد. اگر شمارشِ زیر صفر بود،
    فایلِ ذخیره‌شده را بفرست تا با شکلِ واقعی بازنویسی‌اش کنم.
    """
    from datetime import timedelta
    d = date.today() - timedelta(days=1)
    while d.weekday() in (3, 4):
        d -= timedelta(days=1)
    day = d.strftime("%Y%m%d")
    url = TICK_URL.format(ins=PROBE_INS, day=day)
    print("=" * 68)
    print(f"  نمونهٔ ریزمعاملات — عیار · {d}")
    print("=" * 68)
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Accept": "*/*",
            "Referer": "http://www.tsetmc.com/"})
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
    except Exception as e:                       # noqa: BLE001
        print(f"\n  دانلود نشد: {type(e).__name__}: {e}")
        return 1
    txt = raw.decode("utf-8", "replace")
    out = HERE / f"sample_ticks_{day}.xml"
    out.write_text(txt[:400_000], encoding="utf-8")
    ticks = parse_ticks(txt)
    bars = ticks_to_h1(ticks)
    print(f"\n  دانلود: {len(raw):,} بایت")
    print(f"  تیکِ خوانده‌شده: {len(ticks):,}")
    print(f"  کندلِ ساعتی: {len(bars)}")
    if bars:
        print(f"\n  {'ساعت':<6}{'های':>12}{'لو':>12}{'کلوز':>12}{'حجم':>14}")
        for i, b in enumerate(bars):
            print(f"  {i:<6}{b['h']:>12,.0f}{b['l']:>12,.0f}"
                  f"{b['c']:>12,.0f}{b['v']:>14,.0f}")
        bx = make_box(bars)
        print(f"\n  باکس از کندلِ ساعتی: "
              f"{bx[0]:,.0f} – {bx[1]:,.0f}" if bx else
              "\n  باکس ساخته نشد (حتی با ساعتی)")
        print("\n  ✓ پارسر کار می‌کند. `python bourse.py` را بزن.")
    else:
        print("\n  ✗ پارسر هیچ تیکی نخواند.")
        print(f"  خامش ذخیره شد: {out}")
        print("  آن فایل را برای من بفرست تا با شکلِ واقعی بازنویسی کنم.")
        print(f"\n  ۴۰۰ کاراکترِ اول:\n{txt[:400]}")
    print("\n" + "=" * 68)
    return 0


# ══ ۲. باکس حجمی ════════════════════════════════════════════════════
def make_box(bars, min_rows=3, max_rows=20):
    """باکس = بازهٔ پیوستهٔ **پرحجم** حولِ POC، محدود به دره‌ها.

    پروفایل مثل قبل ساخته می‌شود و چهار ریزه‌کاری‌اش دست‌نخورده است —
    اگر رعایت نشوند جواب عوض می‌شود:

      • دامنه از High/Low کلِ پنجره گرفته می‌شود، نه از Close
      • حجمِ هر کندل به نسبتِ هم‌پوشانی بینِ ردیف‌ها **پخش** می‌شود،
        نه اینکه کلش در ردیفِ Close بنشیند
      • کندلی با دامنهٔ صفر، کلِ حجمش در یک ردیف می‌نشیند
      • دره فقط روی ردیف‌های **میانی** (۱ تا rows−۲) شمرده می‌شود

    تعداد ردیف ثابت نیست: از ۳ بالا می‌رود تا اولین دره ظاهر شود.

    ## چه چیزی عوض شد، و چرا

    تا امروز این تابع **خودِ ردیفِ دره** را برمی‌گرداند — یعنی ناحیهٔ
    کم‌حجم. ولی بند ۱ راهنما این را نمی‌گوید:

        «آن دره **مرز باکس** است»
        «باکس = بازهٔ پیوستهٔ حول POC، محدود به نزدیک‌ترین دره‌ها»

    یعنی باکس ناحیهٔ **پرحجمی** است که دره مرزش است. دو چیزِ متفاوت،
    و جای متفاوتی می‌افتند. مصطفی روی عیار گرفتش: حمایتی که او کشیده
    بود ۶۵٬۰۰۰ تومان بود، این تابع ۶۳٬۷۳۷ می‌داد. ۶۳٬۷۳۷ دقیقاً
    **کفِ** باکسِ اوست — یعنی مرز، نه خودِ ناحیه.

    اندازه‌گیری، روی همان دادهٔ ۱۱ ماهه (`data_auto`)، با همان آزمونِ
    جایگشتِ درون‌دوره:

        ماهانه   مزیت      p         R (هندسهٔ ۱:۱)   استاپ   هم‌کندل
        دره      +۰٫۷۶   ۰٫۰۰۰۴      +۰٫۱۷۱           ۵۳      ۱۲ (۲٪)
        POC      +۱٫۷۲   ۰٫۰۰۰۰      +۰٫۳۳۳            ۸       ۱ (۰٪)

        هفتگی    مزیت      p         R
        دره      +۰٫۶۶   ۰٫۰۰۰۲      +۰٫۱۲۴          ۲۲۱ هم‌کندل (۱۳٪)
        POC      +۰٫۸۵   ۰٫۰۰۰۲      +۰٫۴۰۹           ۴۰ هم‌کندل (۳٪)

    POC در هر دو افق هم **بهتر جدا می‌کند** و هم هندسهٔ سالم‌تری دارد.
    و آن +۰٫۴۰۹R هفتگی دقیقاً عددی است که بند ۳ راهنما ثبت کرده — یعنی
    قاعدهٔ اصلی از اول با باکسِ پرحجم حساب شده بود، نه با ردیفِ دره.

    علتِ هندسه روشن است: باکسِ دره میانهٔ ۱٫۴٪ پهنا دارد و دامنهٔ یک
    روزِ معاملاتی میانهٔ ۲٫۶٪ — یعنی استاپ داخلِ نوسانِ یک کندل می‌افتاد.
    """
    n = len(bars)
    if n <= 2:
        return None
    r_hi = max(b["h"] for b in bars)
    r_lo = min(b["l"] for b in bars)
    rng = r_hi - r_lo
    if rng <= 0:
        return None
    for rows in range(max(3, min_rows), max_rows + 1):
        step = rng / rows
        bins = [0.0] * rows
        for b in bars:
            br = b["h"] - b["l"]
            if br <= 0:
                i = max(0, min(rows - 1, int((b["h"] - r_lo) / step)))
                bins[i] += b["v"]
                continue
            i_lo = max(0, int((b["l"] - r_lo) / step))
            i_hi = min(rows - 1, int((b["h"] - r_lo) / step))
            for bi in range(i_lo, i_hi + 1):
                b_lo = r_lo + bi * step
                ov = min(b["h"], b_lo + step) - max(b["l"], b_lo)
                if ov > 0:
                    bins[bi] += b["v"] * (ov / br)
        valleys = [i for i in range(1, rows - 1)
                   if bins[i] < bins[i - 1] and bins[i] < bins[i + 1]]
        if valleys:
            # ── باکس = بازهٔ پیوستهٔ پرحجم حولِ POC، محدود به دره‌ها ──
            # از POC به هر دو طرف برو تا به اولین دره برسی. خودِ دره
            # **مرز** است، پس بیرون می‌ماند.
            poc = max(range(rows), key=lambda i: (bins[i], -i))
            vs = set(valleys)
            lo_i = poc
            while lo_i - 1 >= 0 and (lo_i - 1) not in vs:
                lo_i -= 1
            hi_i = poc
            while hi_i + 1 <= rows - 1 and (hi_i + 1) not in vs:
                hi_i += 1
            return (r_lo + lo_i * step, r_lo + (hi_i + 1) * step)
    return None


# ── میله و پرچم: سه تارگت ──────────────────────────────────────────
# مصطفی: «یک میله داره و یک پرچم داره که هرگاه اون پرچم به بالا شکسته
# بشه یه میله رشد می‌کنه … سه تا تارگت، کوتاه‌مدت و میان‌مدت و بلندمدت.»
#
# بک‌تست شد (`tools/flagpole.py`) با گروهِ کنترلِ **هم‌هندسه** — همان
# نماد، روزِ تصادفی، همان فاصلهٔ درصدیِ تارگت و استاپ — چون تارگتی که
# ۸٪ بالاتر است در بازارِ صعودی خودبه‌خود می‌خورد و نرخِ خامِ رسیدن
# بی‌معناست (بند ۰ قانون ۲):
#
#   مقیاس            n     میله و پرچم   کنترل    اختلاف     t       p
#   کوتاه ≤۳ کندل    ۷۲      +۰٫۷۸      +۰٫۲۰   +۰٫۵۸R   ۳٫۰۵  ۰٫۰۰۱۳
#   میان  ≤۸ کندل   ۱۷۸      +۱٫۳۶      +۰٫۱۹   +۱٫۱۷R   ۸٫۶۲  ۰٫۰۰۰۷
#   بلند  ≤۲۰ کندل  ۴۳۸      +۱٫۰۶      +۰٫۴۰   +۰٫۶۵R   ۶٫۶۱  ۰٫۰۰۰۷
#
# هر سه از کنترل جلو زدند. قوی‌ترین، مقیاسِ میان است.
#
# ⚠️ روی کندلِ **روزانه**. او سه تایم‌فریم (H4/دیلی/هفتگی) گفته بود؛
# با دادهٔ روزانه سه *طولِ میله* جای سه تایم‌فریم را می‌گیرد. نزدیک
# است، یکی نیست.
FLAG_SCALES = (("کوتاه", 3, 6.0), ("میان", 8, 10.0), ("بلند", 20, 15.0))


def flag_targets(bars, px, retrace_max=0.5, flag_max=6):
    """آخرین میله‌وپرچمِ هر مقیاس → تارگتی که هنوز نخورده."""
    out = []
    n = len(bars)
    for name, pole_max, min_pct in FLAG_SCALES:
        best = None
        for i in range(1, n):
            for plen in range(1, pole_max + 1):
                j = i + plen - 1
                if j >= n:
                    break
                p_lo = bars[i - 1]["c"]
                p_hi = max(b["h"] for b in bars[i:j + 1])
                if p_lo <= 0 or (p_hi - p_lo) / p_lo * 100 < min_pct:
                    continue
                pole = p_hi - p_lo
                for flen in range(2, flag_max + 1):
                    k = j + flen
                    if k >= n:
                        break
                    fl = bars[j + 1:k + 1]
                    f_lo = min(b["l"] for b in fl)
                    f_hi = max(b["h"] for b in fl)
                    if p_hi - f_lo > pole * retrace_max or f_hi > p_hi:
                        break
                    t = k + 1
                    if t < n and bars[t]["c"] > f_hi:
                        best = {"scale": name, "at": bars[t]["d"],
                                "target": bars[t]["c"] + pole,
                                "stop": f_lo}
                        break
                break
        # فقط تارگتی که هنوز بالای قیمتِ امروز است معنی دارد
        if best and best["target"] > px:
            best["up_pct"] = (best["target"] / px - 1) * 100
            out.append(best)
    return out


def value_area_box(bars):
    """جایگزین وقتی هیچ دره‌ای نیست: سه بینِ پرحجم‌ترین، روی Close.

    **چرا لازم شد.** مصطفی پرسید «الان نهال کجاست؟ نهال نیست.» و راست
    می‌گفت — نهال بی‌صدا افتاده بود چون در هفتهٔ قبلش هیچ درهٔ حجمی
    نبود. وقتی همه را شمردیم، **۵۴ نماد از ۱۳۴ (۴۰٪)** همین حال را
    داشتند، و هر ۵۴ تا دقیقاً ۵ کندل در هفته داشتند.

    علتش ریاضی است: پروفایلِ تطبیقی از ۳ ردیف شروع می‌کند و دنبالِ
    کمینهٔ **میانی** می‌گردد. با ۵ کندلِ روزانه اغلب هیچ ردیفِ میانی‌ای
    از هر دو همسایه‌اش کمتر نیست، پس دره پیدا نمی‌شود. همان چیزی که
    بند ۱ راهنما از اول گفته بود: پروفایلِ هفتگی باید روی **H1** ساخته
    شود، نه روزانه — آنجا ~۱۲۰ کندل هست، نه ۵ تا.

    تا رسیدنِ H1، به‌جای انداختنِ نماد، از تعریفِ «ناحیهٔ ارزش» استفاده
    می‌کنیم — این همیشه تعریف‌شدنی است. ولی **علامت می‌خورد**، چون
    تعریفِ دیگری است: در بک‌تستِ ماهانه دره p=۰٫۰۰۰۴ داد و ناحیهٔ ارزش
    p=۰٫۱۱ (از تصادف جدا نشد). پس این «بهتر از هیچ» است، نه هم‌ارز.
    """
    if len(bars) < 3:
        return None
    if sum(b["v"] for b in bars) <= 0:
        return None
    lo = min(b["c"] for b in bars)
    hi = max(b["c"] for b in bars)
    if hi <= lo:
        return (lo, hi)
    nb = min(20, max(5, len(bars) // 2))
    w = (hi - lo) / nb
    vol = [0.0] * nb
    for b in bars:
        k = max(0, min(nb - 1, int((b["c"] - lo) / w)))
        vol[k] += b["v"]
    order = sorted(range(nb), key=lambda j: (-vol[j], j))[:min(3, nb)]
    return (lo + min(order) * w, lo + (max(order) + 1) * w)


def state(px, box):
    if box is None:
        return "؟"
    if px > box[1]:
        return "بالا"
    if px < box[0]:
        return "زیر"
    return "داخل"


def state4(px, box):
    """مثلِ state، ولی «داخل» را به نیمهٔ بالا و پایین می‌شکند.

    **چرا لازم شد.** مصطفی: «سینرژی نیست. امروز باید سیگنال می‌شد،
    بهترین ناحیه بود برای خرید… من جایی بودم نتونستم بخرم.»

    حق داشت. سینرژی کلوزِ ۶٬۶۹۳ داشت داخلِ باکسِ ۶٬۴۷۲–۶٬۷۳۲ — یعنی
    **نیمهٔ بالای** باکس، ولی قاعده فقط «بالای باکس» را سیگنال
    می‌دانست و هیچ‌چیز نشان نداد.

    اندازه گرفتیم (۲٬۸۷۸ مشاهده، ۴۰ هفته، باکسِ POC، مزیت نسبت به
    نرخ پایهٔ همان هفته):

        بالا              n=۱۰۱۲   +۳٫۴۵٪   مزیت +۱٫۰۶   ۷۲٪ مثبت
        داخل — نیمهٔ بالا  n=۷۵۱    +۲٫۶۴٪   مزیت +۰٫۳۳   ۶۴٪ مثبت
        داخل — نیمهٔ پایین n=۵۳۲    +۱٫۴۲٪   مزیت −۰٫۸۸   ۵۹٪ مثبت
        زیر               n=۵۸۳    −۰٫۱۸٪   مزیت −۰٫۵۹   ۴۶٪ مثبت
        (نرخ پایه +۲٫۱۳٪ و ۶۲٪ مثبت)

    نیمهٔ بالا مزیتِ مثبت دارد، نیمهٔ پایین منفی. پس «داخل» را یکجا
    دور ریختن، نصفِ یک سیگنالِ واقعی را دور می‌ریخت.
    """
    if box is None:
        return "؟"
    if px > box[1]:
        return "بالا"
    if px < box[0]:
        return "زیر"
    return "نیمهٔ بالا" if px >= (box[0] + box[1]) / 2 else "نیمهٔ پایین"


# مرزِ هفتهٔ صندوق‌های بورسی: **یکشنبه تا شنبه**.
#
# این با بند ۰ قانون ۱ راهنما («هفته شنبه تا چهارشنبه») فرق دارد و
# عمدی است. مصطفی جدولش را این‌طور نوشت: «پایان دورهٔ باکس = شنبه،
# روز تصمیم = یکشنبه، روز اجرا = دوشنبه.» یعنی کندلِ **شنبه** باید
# داخلِ باکس باشد، نه اولین روزِ هفتهٔ بعد.
#
# اول شنبه‌محور ساخته بودم (باکس شنبه..چهارشنبه، شنبهٔ تازه بیرون).
# هر دو خوانش «یکشنبه» را روزِ تصمیم می‌دهند، ولی باکسشان فرق دارد.
# اندازه گرفته شد (`tools/decision_day.py`، مزیتِ درون‌هفته‌ای):
#
#   شنبه‌محور، باکس شنبهٔ تازه را ندارد   +۰٫۳۸۸ واحد   t=۰٫۹۶   ۳۶ هفته
#   یکشنبه‌محور، باکس شنبه را دارد        +۰٫۶۵۲ واحد   t=۱٫۵۱   ۳۹ هفته
#
# ۶۸٪ بهتر. جدولِ او درست بود.
#
# ⚠️ t=۱٫۵۱ روی ۳۹ هفته هنوز بزرگ نیست و اختلافِ دو خوانش (+۰٫۲۶ واحد)
# از خطای نمونه جدا نمی‌شود. ولی هم بهتر اندازه گرفت و هم قاعدهٔ خودِ
# اوست، پس همین مبناست.
FUND_WEEK_ANCHOR = 6          # یکشنبه


def week_key(d):
    """هفتهٔ صندوق‌های بورسی: یکشنبه تا شنبه."""
    back = (d.weekday() - FUND_WEEK_ANCHOR) % 7
    return d.fromordinal(d.toordinal() - back)


# ── تقویمِ تصمیم ────────────────────────────────────────────────────
# مصطفی: «صندوق‌های بورسی شنبه بسته می‌شود، ناحیه مشخص می‌شود، و کلوزِ
# یکشنبه جهت را تعیین می‌کند. تتر و دلار یکشنبه بسته می‌شوند و کلوزِ
# دوشنبه تصمیم‌گیرنده است.»
#
# اندازه‌گیری شد (`tools/decision_day.py`، مزیتِ درون‌هفته‌ای):
#
#   صندوق‌های بورسی، لنگرِ یکشنبه (باکس تا شنبه)
#     روز ۱ یکشنبه    +۰٫۶۵۲ واحد   t=۱٫۵۱   p=۰٫۰۰۰۳   ← بهترین
#     روز ۲ دوشنبه    +۰٫۶۰۱ واحد   t=۱٫۹۹   p=۰٫۰۰۰۳
#
#   محرک‌ها (دلار، تتر، طلای ۱۸)، لنگرِ دوشنبه
#     روز ۱ دوشنبه    +۰٫۲۹۴ واحد   t=۳٫۸۲   p=۰٫۰۰۰۳   ← بهترین
#     روز ۲ سه‌شنبه   +۰٫۱۲۱ واحد   t=۱٫۸۰
#
# هر دو حرفش درست بود. تفاوتِ یکشنبه با شنبه کوچک است (+۰٫۰۹۹ واحد)
# ولی در همان جهتی است که او گفت.
DECIDE_FUND = 6      # یکشنبه — روز **اولِ** هفتهٔ جدید، چون هفته شنبه بست
DECIDE_DRIVER = 0    # دوشنبه — روز اولِ هفتهٔ جهانی
WD = ("دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه")


# تقویمِ ثابتِ هفته — همیشه نشان داده می‌شود، نه فقط روزِ تصمیم.
# ستونِ «چه خبر» از اندازه‌گیریِ tools/decision_day.py می‌آید.
WEEK_PLAN = [
    (5, "شنبه", "هفتهٔ صندوق‌ها بسته می‌شود",
     "باکس قفل شد — فردا تکلیف روشن می‌شود"),
    (6, "یکشنبه", "🔔 سیگنالِ صندوق‌های بورسی",
     "کلوزِ امروز بالای نوار → در پولبک بخر · زیرِ نوار → در پولبک بفروش"),
    (0, "دوشنبه", "🔔 سیگنالِ تتر و دلار و طلای ۱۸  +  اجرای صندوق‌ها",
     "هفتهٔ ارزی دیشب بست؛ کلوزِ امروز تکلیفش را روشن می‌کند"),
    (1, "سه‌شنبه", "اجرای تتر و دلار و طلای ۱۸", "روزِ سفارشِ ارزی"),
    (2, "چهارشنبه", "—", "آخرین روزِ معاملاتیِ بورس"),
    (3, "پنجشنبه", "بازار بسته", "فقط ارز و طلا باز است"),
    (4, "جمعه", "بازار بسته", "فقط ارز و طلا باز است"),
]


def month_note(d):
    """اولین روزِ معاملاتیِ ماه میلادی = روزِ تصمیمِ ماهانه."""
    return ("🔔 **اولین روزِ ماه میلادی** — باکسِ ماه قبل قفل شد، "
            "تصمیمِ ماهانه امروز است" if d.day <= 3 else
            f"تصمیمِ ماهانهٔ بعد: اولِ ماه میلادیِ آینده")


def today_says(last_date):
    """کلوزِ این روز چه تصمیمی را می‌سازد؟"""
    wd = last_date.weekday()
    out = []
    if wd == DECIDE_FUND:
        out.append(("صندوق‌های بورسی",
                    "باکس دیشب (شنبه) بسته شد — کلوزِ امروز تصمیم‌گیرنده است",
                    "فردا (دوشنبه) خرید و فروش کن"))
    if wd == DECIDE_DRIVER:
        out.append(("تتر و دلار و طلای ۱۸",
                    "کلوزِ امروز تصمیم‌گیرنده است",
                    "امروز آخر وقت یا فردا صبح"))
    if not out:
        nf = (DECIDE_FUND - wd) % 7 or 7
        nd = (DECIDE_DRIVER - wd) % 7 or 7
        out.append(("—", "امروز روزِ تصمیم نیست",
                    f"صندوق‌ها {nf} روز دیگر (یکشنبه) · "
                    f"محرک‌ها {nd} روز دیگر (دوشنبه)"))
    return out


def zone(box, px, band):
    lo, hi = box
    z_lo = hi
    z_aim = hi * (1 + band["aim"] / 100)
    z_hi = hi * (1 + band["hi"] / 100)
    risk = z_aim - lo
    st = ("زیر نوار" if px < z_lo
          else "در نوار" if px <= z_hi else "بالای نوار")
    return {"lo": z_lo, "aim": z_aim, "hi": z_hi, "stop": lo,
            "target": z_aim + risk, "risk_pct": risk / z_aim * 100,
            "state": st,
            # فاصلهٔ درصدی تا کفِ نوار — مبنای ستونِ آلارم.
            # مثبت = هنوز باید بالا بیاید · منفی = از نوار رد شده
            "dist_pct": (z_lo - px) / px * 100 if px else 0.0}


# ══ ۳. تحلیل ════════════════════════════════════════════════════════
def analyse(sym, rows, ins=None, allow_ticks=False):
    """هیچ نمادی **بی‌صدا حذف نمی‌شود.**

    قبلاً هر جا باکس ساخته نمی‌شد `None` برمی‌گشت و نماد از جدول غیب
    می‌شد. مصطفی روی نهال گرفتش: «الان نهال کجاست؟ نهال نیست. من باید
    دونه دونه بگم؟» حق داشت — نهال در هفتهٔ قبلش هیچ درهٔ حجمی نداشت،
    پس `make_box` هیچ داد و کد بی‌صدا انداختش بیرون.
    حالا هر نماد یک ردیف دارد، با `reason` که می‌گوید چرا هست یا نیست.
    """
    name = DISPLAY.get(norm(sym), sym)
    base = {"sym": name, "cat": NORM_CAT.get(norm(sym), "؟"),
            "close": rows[-1]["c"] if rows else 0,
            "date": rows[-1]["d"].isoformat() if rows else "",
            "mst": "—", "wst": "—", "cur_st": "—",
            "cur_box": None, "month": None, "week": None,
            "med_vol": 0, "value_bn": 0, "ok": False}
    if len(rows) < MIN_DAYS:
        return {**base, "reason": f"تاریخچهٔ کم ({len(rows)} روز)"}
    by_m, by_w = defaultdict(list), defaultdict(list)
    for b in rows:
        by_m[(b["d"].year, b["d"].month)].append(b)
        by_w[week_key(b["d"])].append(b)
    ms, ws = sorted(by_m), sorted(by_w)
    if len(ms) < 2 or len(ws) < 2:
        return {**base, "reason": "کمتر از دو ماه یا دو هفته داده"}
    px = rows[-1]["c"]
    vols = sorted(b["v"] for b in rows[-20:])
    mv = vols[len(vols) // 2] if vols else 0
    base.update({"med_vol": mv, "value_bn": mv * px / 1e9,
                 "wbars": len(by_w[ws[-2]]), "mbars": len(by_m[ms[-2]])})
    mb, wb = make_box(by_m[ms[-2]]), make_box(by_w[ws[-2]])
    fb = []                                  # کدام باکس با جایگزین ساخته شد
    # ── پلهٔ اول: اگر باکسِ هفتگی نشد، با کندلِ **ساعتی** دوباره بساز ──
    # ۵ کندلِ روزانه اغلب دره ندارد؛ ~۱۲۰ کندلِ ساعتی دارد. این همان
    # چیزی است که بند ۱ راهنما از اول خواسته بود.
    if wb is None and allow_ticks and ins:
        wdays = sorted({b["d"] for b in by_w[ws[-2]]})
        h1 = []
        for d in wdays:
            h1.extend(get_h1(sym, ins, d, quiet=True))
        if len(h1) >= 8:
            wb = make_box(h1)
            if wb is not None:
                fb.append("هفتگی←ساعتی")
                base["h1bars"] = len(h1)
    if mb is None:
        mb = value_area_box(by_m[ms[-2]])
        if mb:
            fb.append("ماهانه")
    if wb is None:
        wb = value_area_box(by_w[ws[-2]])
        if wb:
            fb.append("هفتگی")
    base["fallback"] = fb
    rets = [(rows[i]["c"] / rows[i - 1]["c"] - 1) * 100
            for i in range(1, len(rows)) if rows[i - 1]["c"] > 0]
    base["vol"] = statistics.pstdev(rets) if len(rets) >= 30 else None
    if mb is None or wb is None:
        miss = "ماهانه" if mb is None else "هفتگی"
        return {**base, "reason": f"باکسِ {miss} به هیچ روشی ساخته نشد"}
    # باکسِ ماهِ **جاری** (تا امروز). مصطفی این ستون را در داشبورد قبلی
    # داشت و می‌خواهدش. ولی یک قید دارد که باید دیده شود: این باکس روی
    # دوره‌ای ساخته می‌شود که حجمش هنوز کامل نشده، و وقتی اندازه گرفتیم
    # (کنترلِ ماه × روزِ ماه) مزیتش +۰٫۰۱ واحد با t=+۰٫۰۶ درآمد — یعنی
    # از تصادف جدا نمی‌شود. پس **خبر** است، نه سیگنال.
    cm = by_m[ms[-1]]
    cur = (make_box(cm) or value_area_box(cm)) if len(cm) >= 3 else None
    return {**base, "ok": True, "reason": "",
            "flags": flag_targets(rows, px),
            "w4": state4(px, wb), "m4": state4(px, mb),
            "mst": state(px, mb), "wst": state(px, wb),
            "cur_box": cur, "cur_st": state(px, cur) if cur else "؟",
            "cur4": state4(px, cur) if cur else "؟",
            "month": zone(mb, px, BAND["month"]),
            "week": zone(wb, px, BAND["week"])}


def build_book(rows, capital):
    """واجد شرط: بالای هر دو باکس. از هر دسته فقط بزرگ‌ترین.

    **پهنای دسته.** اگر از ده صندوق طلا هشت تا زیر باکسِ هفتگی باشند،
    آن دو تای دیگر سیگنال نیستند — عقب‌افتاده‌اند. پس دسته‌ای که کمتر
    از نصفِ اعضایش بالای باکس هفتگی است کنار گذاشته می‌شود.
    """
    rows = [r for r in rows if r.get("ok")]
    breadth = {}
    for r in rows:
        c = r["cat"]
        a, t = breadth.get(c, (0, 0))
        breadth[c] = (a + (1 if r["wst"] == "بالا" else 0), t + 1)
    wide = {c for c, (a, t) in breadth.items() if t and a / t >= 0.5}

    def tier(r):
        """۱ = سیگنالِ کامل · ۲ = نیمه‌سیگنال · ۰ = هیچ.

        پلهٔ دوم را مصطفی خواست، و داده پشتش هست: کلوزِ **نیمهٔ بالای**
        باکسِ هفتگی مزیتِ +۰٫۳۳ واحد و ۶۴٪ مثبت دارد (n=۷۵۱) — کمتر از
        «بالای باکس» (+۱٫۰۶) ولی روشن بهتر از نیمهٔ پایین (−۰٫۸۸).
        سینرژی دقیقاً همین‌جا بود و هیچ‌جا دیده نمی‌شد.
        """
        if r["value_bn"] < MIN_VALUE_BN or r.get("park"):
            return 0
        # فیلترِ ماهِ جاری: مقاومتی که از اولِ ماه ساخته شده.
        # قاعدهٔ نقران بود — «از ابتدای ماه فعلی یک مقاومت ایجاد کرده
        # بالای عدد». ولی «داخلِ باکس» یکجا رد کردن زیادی سخت‌گیر بود:
        # سینرژی با کلوزِ **نیمهٔ بالای** باکسِ ماهِ جاری حذف می‌شد، در
        # حالی که مقاومتی بالای سرش نبود — وسطِ ناحیه بود.
        # همان تفکیکی که روی باکسِ هفتگی اندازه گرفتیم اینجا هم اعمال
        # می‌شود: نیمهٔ بالا رد نمی‌شود، نیمهٔ پایین و «زیر» رد می‌شوند.
        # ⚠️ این تفکیک روی باکسِ **هفتگی** اندازه‌گیری شده، نه روی ماهِ
        # جاری. یک‌شکل بودنِ قاعده است، نه اندازه‌گیریِ مستقل — و خودِ
        # فیلترِ ماهِ جاری هم شاهدِ محکمی ندارد (t از ۰٫۹۷ به ۰٫۸۴).
        if (REQUIRE_CUR_MONTH
                and r.get("cur4") not in ("بالا", "نیمهٔ بالا", "؟")):
            return 0
        if not (r["cat"] in wide or norm(r["sym"]) in NORM_EXEMPT):
            return 0
        if r["mst"] != "بالا":
            return 0
        if r["wst"] == "بالا":
            return 1
        if r["w4"] == "نیمهٔ بالا":
            return 2
        return 0

    for r in rows:
        r["tier"] = tier(r)
    elig = [r for r in rows if r["tier"] == 1]
    half = [r for r in rows if r["tier"] == 2]
    # از هر دسته بزرگ‌ترین. اگر دسته‌ای سیگنالِ کامل نداشت،
    # نیمه‌سیگنالش می‌آید — با **نصفِ وزن**، چون مزیتش هم حدودِ
    # یک‌سومِ سیگنالِ کامل است.
    best = {}
    for r in elig:
        c = r["cat"]
        if c not in best or r["value_bn"] > best[c]["value_bn"]:
            best[c] = r
    for r in half:
        c = r["cat"]
        if c not in best:
            best[c] = r
    picks = sorted(best.values(), key=lambda r: -r["value_bn"])

    # ── چرخشِ پر: هرگز نقد نشو ──────────────────────────────────────
    # این مهم‌ترین تغییرِ کلِ پروژه است و از اندازه‌گیری آمد، نه سلیقه.
    #
    # تجزیهٔ ۳۴۸ هفتهٔ عیار: هفته‌های «زیرِ باکس» هم **مثبت**اند
    # (+۰٫۴۵٪). و چرخهٔ فروش-و-خریدِ بعدی، در ۴۹ چرخه، میانه **+۱٫۷٪
    # گران‌تر** خرید — دو سومِ مواقع بالاتر. یعنی سیگنالِ فروش دیر
    # می‌رسد: کف را می‌فروشی و برگشت را بالاتر می‌خری.
    #
    # هزارتا واحد عیار، ۸ سال: هولد ۱۰۰۰ · ماهانه ۶۳۳ · هفتگی ۱۴۷.
    # ولی چرخشِ پر روی جهانِ چهارتاییِ خودش، ۶۱ هفته: **۲٬۲۱۲ واحد**.
    #
    # پس اگر هیچ نمادی واجد شرط نبود، **نقد نمی‌مانیم** — سبدِ هم‌وزنِ
    # نقدشونده‌ترین‌های همان جهان نگه داشته می‌شود.
    if not picks:
        pool = [r for r in rows
                if r["value_bn"] >= MIN_VALUE_BN and not r.get("park")]
        pool.sort(key=lambda r: -r["value_bn"])
        picks = pool[:4]
        for r in picks:
            r["tier"] = 3               # «پرکننده» — سیگنال نیست
    if not picks:
        return elig, []
    # نیمه‌سیگنال نصفِ وزن می‌گیرد — مزیتش هم حدودِ یک‌سوم است
    units = sum(1.0 if r["tier"] in (1, 3) else 0.5 for r in picks)
    book = []
    for r in picks:
        w = min(MAX_WEIGHT, MAX_INVESTED / units
                * (1.0 if r["tier"] in (1, 3) else 0.5))
        # باندی که استاپش داخلِ نوسانِ یک روز نمی‌نشیند. باکسِ هفتگی
        # میانهٔ پهنایش ۱٫۴۲٪ است و دامنهٔ یک روز ۲٫۶۲٪، پس استاپِ
        # هفتگیِ زیر ۱٪ عملاً داخلِ نویز می‌نشیند و باندِ ماهانه
        # برداشته می‌شود.
        band = "week" if r["week"]["risk_pct"] >= 1.0 else "month"
        z = r[band]
        amt = capital * w / 100
        book.append({**r, "band": band, "z": z, "w": w,
                     "amt": amt, "units": amt / z["aim"],
                     "loss": amt * z["risk_pct"] / 100})
    return elig, book


# ══ ۴. آلارم ════════════════════════════════════════════════════════
def alarms(rows, book):
    """آلارمِ ورود و خروج.

    مصطفی: «آلارمِ ورود و خروج بذار. امروز اگه آلارم فعال بود من
    سینرژی رو خریده بودم.»

    ورود: نمادی که در نوارِ خرید است — یعنی قیمت رسیده به ناحیه‌ای
          که باید بخری، نه اینکه فقط واجدِ شرط باشد.
    خروج: نمادی که **داری** و کلوزش زیرِ باکسِ هفتگی یا ماهانه رفته.
          این همان «سیگنالِ جهتِ عکس» است.
    """
    buy, sell = [], []
    for r in book:
        z = r["z"]
        if z["state"] == "در نوار":
            buy.append((r["sym"], z["aim"], z["stop"], z["risk_pct"],
                        r.get("tier", 1)))
    # آلارمِ فروش **دیگر «نقد شو» نیست، «عوض کن» است.** اندازه‌گیری
    # نشان داد نقد شدن روی سیگنالِ باکس تعدادِ واحد را کم می‌کند
    # (عیار: ۱۰۰۰ → ۱۴۷ در هشت سال). آن‌چه کار می‌کند، رفتن روی
    # نمادی است که بالای باکسش است — بدونِ اینکه پول از بازار بیرون
    # برود.
    for r in rows:
        if not r.get("ok"):
            continue
        n = norm(r["sym"])
        if n not in NORM_HOLD:
            continue
        if r["wst"] == "زیر" or r["mst"] == "زیر":
            which = []
            if r["mst"] == "زیر":
                which.append("ماهانه")
            if r["wst"] == "زیر":
                which.append("هفتگی")
            sell.append((r["sym"], r["close"], " و ".join(which),
                         NORM_HOLD[n]))
    return buy, sell


def alarm_text(buy, sell, stamp):
    """متنِ آلارم — همان چیزی که به تلگرام می‌رود و بالای صفحه می‌آید."""
    L = []
    if sell:
        L.append("<b>🔄 آلارمِ جابه‌جایی</b> (نقد نشو — عوض کن)")
        for sym, px, which, units in sell:
            L.append(f"• <b>{sym}</b> — کلوز {px:,.0f} زیرِ باکسِ "
                     f"{which} · {units:,} واحد داری")
    if buy:
        L.append("<b>🟢 آلارمِ خرید — الان در نوار</b>")
        for sym, aim, stop, risk, tier in buy:
            tag = "" if tier == 1 else " (نیمه‌سیگنال)"
            L.append(f"• <b>{sym}</b>{tag} ورود {aim:,.0f} | "
                     f"استاپ {stop:,.0f} | ریسک {risk:.1f}٪")
    if not L:
        L.append("امروز نه آلارمِ خرید هست نه فروش.")
    return f"<b>بورس — {stamp}</b>\n" + "\n".join(L)


# ══ ۴ب. تلگرام ══════════════════════════════════════════════════════
def telegram(text):
    tok = os.environ.get("TELEGRAM_BOT_TOKEN")
    cid = os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not cid:
        print("\n  تلگرام تنظیم نشده (TELEGRAM_BOT_TOKEN / "
              "TELEGRAM_CHAT_ID). رد شد.")
        return False
    data = urllib.parse.urlencode(
        {"chat_id": cid, "text": text, "parse_mode": "HTML"}).encode()
    try:
        with urllib.request.urlopen(
                f"https://api.telegram.org/bot{tok}/sendMessage",
                data=data, timeout=30) as r:
            return r.status == 200
    except Exception as e:                           # noqa: BLE001
        print("  خطای تلگرام:", e)
        return False


# ══ ۵. صفحه ═════════════════════════════════════════════════════════
def html(rows, book, capital, stamp, last_date, buy=(), sell=()):
    """داشبورد — با همان فرمتِ فایلی که مصطفی فرستاد.

    `dashboard_monthly.html` او: تمِ تیره، تب‌های قرصی، کاشیِ آمار،
    چیپ‌های فیلترِ دسته، و جدولی با ستون‌های «حدضرر / حدسود / ریسک /
    موفقیت». پالت و کلاس‌ها عیناً از همان فایل برداشته شده:

        #0f1419 پس‌زمینه · #1a2332 کارت · #2d3a4f خط
        #e7ecf3 متن · #8b9cb3 کم‌رنگ
        #3dd68c سبز · #63b3ed آبی · #ecc94b زرد · #f56565 قرمز

    چیزی که اضافه شده و در فایلِ او نبود: **نقطهٔ ورود**. آنجا فقط
    حدضرر و حدسود بود؛ ورود روی کلوز فرض می‌شد. اندازه‌گیری نشان داد
    ورود روی سقفِ باکس t=۱٫۳۵ می‌دهد و ۳٪ بالاترش t=۵٫۴۱، پس نقطهٔ
    ورود ستونِ جداست و ستونِ «آلارم» می‌گوید قیمت الان به آن رسیده یا نه.
    """
    last_wd = last_date.weekday()
    ok_rows = [r for r in rows if r.get("ok")]
    book_syms = {r["sym"] for r in book}
    inv = sum(r["w"] for r in book)
    risk = sum(r["loss"] for r in book)
    hot = [r for r in ok_rows if r["week"]["state"] == "در نوار"
           or r["month"]["state"] == "در نوار"]

    def n(x, d=0):
        return f"{x:,.{d}f}" if x == x else "—"

    BADGE = {"بالا": "b-g", "داخل": "b-y", "زیر": "b-r", "؟": "b-m"}
    ZB = {"در نوار": "b-g", "زیر نوار": "b-m", "بالای نوار": "b-y"}

    def bdg(v, mp=None):
        return f'<span class="badge {(mp or BADGE).get(v, "b-m")}">{v}</span>'

    def bar(pct, cls="g"):
        w = max(0, min(100, pct))
        return (f'<div class="bar-wrap"><div class="bar {cls}" '
                f'style="width:{w:.0f}%"></div></div>')

    def wr(r, hz):
        k = wr_key(r)
        v = (WINRATE[hz].get(k) or WINRATE["week"].get(k)) if k else None
        return v or (0, 0, 0.0)

    def flagcell(r):
        """سه تارگتِ میله و پرچم، هرکدام که هنوز نخورده."""
        fs = r.get("flags") or []
        if not fs:
            return '<span class="sub">—</span>'
        return " ".join(
            f'<span class="flag" title="پرچمِ {f["scale"]} — '
            f'شکست {f["at"]} · استاپ {f["stop"]:,.0f}">'
            f'{f["scale"]} {n(f["target"])} '
            f'<b class="g">+{f["up_pct"]:.0f}٪</b></span>'
            for f in fs)

    def thin(r):
        """نمادِ کم‌حجم در جدول می‌ماند ولی علامت می‌خورد — در دفتر
        نمی‌آید و مصطفی باید بداند چرا."""
        if r["value_bn"] >= MIN_VALUE_BN:
            return ""
        return (f'<span class="thin" title="ارزشِ معاملات '
                f'{r["value_bn"]:.0f} م.ر — زیرِ {MIN_VALUE_BN:.0f}">'
                f'کم‌حجم</span>')

    def alarm(z):
        if z["state"] == "در نوار":
            return '<span class="badge b-g">🔔 در نوار</span>'
        if z["state"] == "زیر نوار":
            return (f'<span class="badge b-m">{z["dist_pct"]:+.1f}٪ تا نوار'
                    f'</span>')
        return '<span class="badge b-y">بالای نوار</span>'

    # ── تبِ ۱: سیگنال — رتبه‌بندی‌شده ──
    def sigrow(i, r, key):
        z = r[key]
        nn, win, avg = wr(r, key)
        return (f'<tr data-s="{r["sym"]}" data-c="{r["cat"]}">'
                f'<td class="td">{i}</td>'
                f'<td class="td sym">{r["sym"]}{thin(r)}</td>'
                f'<td class="td">{alarm(z)}</td>'
                f'<td class="td n">{n(r["close"])}</td>'
                f'<td class="td n hi">{n(z["aim"])}</td>'
                f'<td class="td n r">{n(z["stop"])}</td>'
                f'<td class="td n g">{n(z["target"])}</td>'
                f'<td class="td n">{z["risk_pct"]:.1f}٪</td>'
                f'<td class="td n">{n(nn)}</td>'
                f'<td class="td n">{win}٪ {bar(win)}</td>'
                f'<td class="td n {"g" if avg > 0 else "r"}">{avg:+.2f}٪</td>'
                f'<td class="td">{bdg(r["mst"])}</td>'
                f'<td class="td">{bdg(r["wst"])}</td>'
                f'<td class="td">{flagcell(r)}</td></tr>')

    # مصطفی: «طراحی نمی‌کنی که صندوق‌ها تفکیک شده باشن، این‌جوری
    # صندوق‌ها ردیفی‌ان.» پس جدول دیگر یک فهرستِ صافِ ۱۳۴تایی نیست —
    # هر دسته سرفصلِ خودش را دارد و رتبه **داخل دسته** شمرده می‌شود.
    # ترتیبِ دسته‌ها از قانونِ طبقهٔ دارایی (CLAUDE.md §۳) می‌آید:
    # اثرِ جریانِ پول روی اهرمی بیشترین است، روی طلا کمترین.
    CAT_ORDER = ["اهرمی", "طلا", "نقره", "کالایی", "سهامی",
                 "بخشی", "مختلط", "صندوق_در_صندوق", "املاک",
                 "شاخصی"]

    def cat_rank(c):
        return CAT_ORDER.index(c) if c in CAT_ORDER else len(CAT_ORDER)

    def in_band(r, key):
        return r[key]["state"] == "در نوار"

    def sigtab(key):
        by = {}
        for r in ok_rows:
            by.setdefault(r["cat"], []).append(r)
        out = []
        for c in sorted(by, key=lambda c: (cat_rank(c), c)):
            rs = sorted(by[c], key=lambda r: (
                0 if in_band(r, key) else
                1 if r[key]["state"] == "زیر نوار" else 2,
                0 if r["value_bn"] >= MIN_VALUE_BN else 1,
                r[key]["risk_pct"]))
            hot = sum(1 for r in rs if in_band(r, key))
            liq = sum(1 for r in rs if r["value_bn"] >= MIN_VALUE_BN)
            out.append(
                f'<tr class="grp" data-c="{c}"><td class="td" colspan="14">'
                f'<span class="gname">{"بدون دسته" if c == "؟" else c}</span>'
                f'<span class="gmeta">{len(rs)} نماد · '
                f'<b class="g">{hot}</b> در نوار · '
                f'{liq} با حجمِ کافی</span></td></tr>')
            out += [sigrow(i, r, key) for i, r in enumerate(rs, 1)]
        return "".join(out)

    # ── بنرِ آلارم، بالای همه‌چیز ──
    def _albox():
        if not buy and not sell:
            return ('<div class="alarm quiet">🔕 امروز نه آلارمِ خرید '
                    'هست نه فروش.</div>')
        rowsh = []
        for sym, px, which, units in sell:
            rowsh.append(
                f'<div class="al al-s"><b>🔴 بفروش — {sym}</b>'
                f'<span>کلوز {n(px)} زیرِ باکسِ {which} · '
                f'{units:,} واحد داری</span></div>')
        for sym, aim, stop, risk, tier in buy:
            tag = "" if tier == 1 else " · نیمه‌سیگنال"
            rowsh.append(
                f'<div class="al al-b"><b>🟢 بخر — {sym}</b>'
                f'<span>ورود {n(aim)} · استاپ {n(stop)} · '
                f'ریسک {risk:.1f}٪{tag}</span></div>')
        return f'<div class="alarm">{"".join(rowsh)}</div>'

    alarm_box = _albox()

    SIGH = ("رتبه|نماد|آلارم|کلوز|نقطهٔ ورود|حدضرر|حدسود|ریسک|"
            "n دسته|موفقیتِ دسته|میانگین بازده|ماهانه|هفتگی|"
            "تارگتِ میله و پرچم")

    # ── تبِ ۲: دفتر ──
    bk = "".join(
        f'<tr data-s="{r["sym"]}" data-c="{r["cat"]}">'
        f'<td class="td sym">{r["sym"]}</td><td class="td">{r["cat"]}</td>'
        f'<td class="td">{"هفتگی" if r["band"] == "week" else "ماهانه"}</td>'
        f'<td class="td n">{n(r["close"])}</td>'
        f'<td class="td n hi">{n(r["z"]["aim"])}</td>'
        f'<td class="td n r">{n(r["z"]["stop"])}</td>'
        f'<td class="td n g">{n(r["z"]["target"])}</td>'
        f'<td class="td n">{r["z"]["risk_pct"]:.1f}٪</td>'
        f'<td class="td n">{r["w"]:.0f}٪</td>'
        f'<td class="td n">{n(r["amt"] / 1e6)}</td>'
        f'<td class="td n">{n(r["units"])}</td>'
        f'<td class="td n r">{n(r["loss"] / 1e6)}</td>'
        f'<td class="td">{alarm(r["z"])}</td></tr>' for r in book)
    bk += (f'<tr class="dim"><td class="td sym">نقد</td>'
           f'<td class="td" colspan="7"></td>'
           f'<td class="td n"><b>{100 - inv:.0f}٪</b></td>'
           f'<td class="td n">{n(capital * (100 - inv) / 100 / 1e6)}</td>'
           f'<td class="td" colspan="3"></td></tr>')

    # ── تبِ ۴: وضعیت همهٔ نمادها ──
    def why(r):
        fb = r.get("fallback") or []
        tag = f" ({'/'.join(fb)})" if fb else ""
        if not r.get("ok"):
            return ("b-y", r.get("reason", "؟"))
        if r["sym"] in book_syms:
            return ("b-g", "در دفتر" + tag)
        if r["mst"] != "بالا":
            return ("b-r", "زیرِ ماه قبل")
        if r["wst"] != "بالا":
            return ("b-r", "زیرِ هفتگی")
        if REQUIRE_CUR_MONTH and r["cur_st"] not in ("بالا", "؟"):
            return ("b-r", "زیرِ ماهِ جاری")
        if r["value_bn"] < MIN_VALUE_BN:
            return ("b-m", f"حجمِ کم ({r['value_bn']:,.0f})")
        return ("b-m", "واجد شرط، بزرگ‌ترینِ دسته نیست" + tag)

    allr = "".join(
        (lambda k, t: (
            f'<tr data-s="{r["sym"]}" data-c="{r["cat"]}">'
            f'<td class="td sym">{r["sym"]}</td>'
            f'<td class="td">{r["cat"]}</td>'
            f'<td class="td n">{n(r["close"])}</td>'
            f'<td class="td">{bdg(r.get("mst", "؟"))}</td>'
            f'<td class="td">{bdg(r.get("cur_st", "؟"))}</td>'
            f'<td class="td">{bdg(r.get("wst", "؟"))}</td>'
            f'<td class="td n">{n(r["value_bn"])}</td>'
            f'<td class="td"><span class="badge {k}">{t}</span></td></tr>'))
        (*why(r)) for r in sorted(rows, key=lambda x: -x.get("value_bn", 0)))

    # ── تبِ ۵: بک‌تست ──
    def bt(hz, title, note):
        w = WINRATE[hz]
        bn, bwin, bavg = w["_base"]
        rr = "".join(
            f'<tr><td class="td sym">{k}</td><td class="td n">{v[0]:,}</td>'
            f'<td class="td n">{v[1]}٪ {bar(v[1])}</td>'
            f'<td class="td n {"g" if v[2] > 0 else "r"}">{v[2]:+.2f}٪</td>'
            f'<td class="td n {"g" if v[1] - bwin > 0 else "r"}">'
            f'{v[1] - bwin:+d} واحد</td></tr>'
            for k, v in w.items() if k != "_base")
        return (f'<h3>{title}</h3><div class="sub">{note} — پایه: '
                f'{bwin}٪ مثبت · {bavg:+.2f}٪ · n={bn:,}</div>'
                f'<div class="wrap"><table class="table"><thead><tr>'
                + "".join(f'<th class="th{" n" if i else ""}">{c}</th>'
                          for i, c in enumerate(
                              ["وضعیتِ باکس", "n", "موفقیت",
                               "میانگین بازده", "نسبت به پایه"]))
                + f'</tr></thead><tbody>{rr}</tbody></table></div>')

    cats = sorted({r["cat"] for r in rows})
    chips = ('<span class="chip on" data-c="*">همه</span>'
             + "".join(f'<span class="chip" data-c="{c}">{c}</span>'
                       for c in cats))
    tiles = "".join(
        f'<div class="stat"><div class="k">{k}</div>'
        f'<div class="v {cl}">{v}</div><div class="d">{d}</div></div>'
        for k, v, d, cl in [
            ("در دفتر", f"{len(book)}", f"{inv:.0f}٪ در بازار", ""),
            ("نقد", f"{100 - inv:.0f}٪",
             f"{n(capital * (100 - inv) / 100 / 1e6)} م.ر", ""),
            ("🔔 در نوار خرید", f"{len(hot)}", f"از {len(ok_rows)} نماد", "g"),
            ("ریسکِ کل", f"{risk / capital * 100:.2f}٪",
             "اگر همه استاپ بخورند", "r"),
            ("سرمایه", f"{n(capital / 1e9, 1)}", "میلیارد ریال", ""),
        ])
    cal = "".join(
        f'<tr class="{"now" if k == last_wd else ""}">'
        f'<td class="dy">{"►" if k == last_wd else ""} {nm}</td>'
        f'<td>{ev}</td><td class="nt2">{note if k == last_wd else ""}</td>'
        f'</tr>' for k, nm, ev, note in WEEK_PLAN)

    def thead(spec):
        return "".join(
            f'<th class="th{" n" if i >= 3 else ""}">{c}</th>'
            for i, c in enumerate(spec.split("|")))

    return f"""<!doctype html><html lang="fa" dir="rtl"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>داشبورد ریسک و بازده — {stamp}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;600;700;900&display=swap">
<style>
:root{{--bg:#0f1419;--card:#1a2332;--card2:#1f2c3d;--th:#243044;
--border:#2d3a4f;--text:#e7ecf3;--muted:#8b9cb3;--green:#3dd68c;
--blue:#63b3ed;--yellow:#ecc94b;--red:#f56565}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);
font-family:Vazirmatn,"Segoe UI",system-ui,sans-serif;font-size:15px;
line-height:1.6}}
.page{{max-width:1400px;margin:0 auto;padding:22px 16px 50px}}
h1{{font-size:1.7rem;font-weight:900;margin:0 0 4px}}
h3{{font-size:1.05rem;margin:22px 0 4px;font-weight:700}}
.sub{{color:var(--muted);font-size:.85rem;margin-bottom:20px}}
.cal{{border:1px solid var(--border);border-left:3px solid var(--yellow);
border-radius:12px;background:var(--card);padding:12px 16px;margin-bottom:20px}}
.cal table{{width:100%;border-collapse:collapse;font-size:.82rem}}
.cal td{{padding:4px 8px;border-bottom:1px solid var(--border)}}
.cal tr:last-child td{{border-bottom:none}}
.cal tr.now td{{background:rgba(61,214,140,.12);font-weight:700}}
.cal td.dy{{width:90px;color:var(--muted)}}
.cal tr.now td.dy{{color:var(--green)}}
.cal td.nt2{{color:var(--muted);font-weight:400;font-size:.78rem}}
.cal .mn{{color:var(--muted);font-size:.8rem;margin-top:7px;
padding-top:7px;border-top:1px solid var(--border)}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));
gap:12px;margin-bottom:24px}}
.stat{{background:var(--card);border:1px solid var(--border);
border-radius:12px;padding:14px 16px}}
.stat .k{{color:var(--muted);font-size:.78rem}}
.stat .v{{font-size:1.7rem;font-weight:900;font-variant-numeric:tabular-nums;
line-height:1.3}}
.stat .d{{color:var(--muted);font-size:.75rem}}
.tabs{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}}
.tab{{background:var(--card);border:1px solid var(--border);
color:var(--text);padding:8px 16px;border-radius:20px;cursor:pointer;
font:inherit;font-size:.85rem;font-weight:600}}
.tab.on{{background:var(--blue);border-color:var(--blue);color:#0f1419}}
.filters{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px;
align-items:center}}
.chip{{padding:4px 12px;border-radius:12px;font-size:.8rem;
border:1px solid var(--border);cursor:pointer;background:var(--card);
color:var(--muted)}}
.chip.on{{background:var(--th);color:var(--text);border-color:var(--blue)}}
#q{{margin-inline-start:auto;padding:5px 12px;border-radius:12px;
border:1px solid var(--border);background:var(--card);color:var(--text);
font:inherit;font-size:.8rem;min-width:170px}}
.panel{{display:none}} .panel.on{{display:block}}
.wrap{{overflow-x:auto;border-radius:12px;border:1px solid var(--border)}}
.table{{width:100%;border-collapse:collapse;font-size:.85rem;
background:var(--card);font-variant-numeric:tabular-nums}}
.th{{text-align:right;padding:10px 12px;background:var(--th);
color:var(--muted);font-weight:600;white-space:nowrap}}
.td{{padding:9px 12px;border-top:1px solid var(--border);white-space:nowrap}}
.th.n,.td.n{{text-align:left}}
.td.sym{{font-weight:700}}
.td.hi{{color:var(--blue);font-weight:700}}
tr.dim .td{{color:var(--muted)}}
tr.hide{{display:none}}
tr.grp .td{{background:var(--th);border-top:2px solid var(--blue);
padding:8px 12px}}
.gname{{font-weight:700;font-size:.95rem;color:var(--text)}}
.gmeta{{color:var(--muted);font-size:.78rem;margin-inline-start:12px}}
.alarm{{margin:16px 0;display:flex;flex-direction:column;gap:8px}}
.alarm.quiet{{padding:13px 16px;border-radius:12px;background:var(--card);
border:1px solid var(--border);color:var(--muted);font-size:.85rem}}
.al{{display:flex;justify-content:space-between;align-items:center;
gap:14px;padding:13px 16px;border-radius:12px;background:var(--card);
flex-wrap:wrap}}
.al b{{font-size:1rem}} .al span{{color:var(--muted);font-size:.85rem}}
.al-b{{border:1px solid var(--green);
box-shadow:inset 3px 0 0 var(--green)}}
.al-s{{border:1px solid var(--red);box-shadow:inset 3px 0 0 var(--red)}}
.flag{{display:inline-block;margin-inline-end:5px;padding:1px 6px;
border-radius:6px;background:var(--th);font-size:.7rem;
color:var(--muted);white-space:nowrap}}
.thin{{display:inline-block;margin-inline-start:6px;padding:1px 6px;
border-radius:6px;background:var(--th);color:var(--muted);
font-size:.68rem;font-weight:600}}
.g{{color:var(--green);font-weight:600}}
.r{{color:var(--red);font-weight:600}}
.badge{{display:inline-block;padding:2px 8px;border-radius:8px;
font-size:.75rem;font-weight:600}}
.b-g{{background:rgba(61,214,140,.15);color:var(--green)}}
.b-r{{background:rgba(245,101,101,.15);color:var(--red)}}
.b-y{{background:rgba(236,201,75,.15);color:var(--yellow)}}
.b-m{{background:var(--th);color:var(--muted)}}
.bar-wrap{{height:8px;background:#243044;border-radius:4px;overflow:hidden;
min-width:60px;display:inline-block;vertical-align:middle;
margin-inline-start:6px}}
.bar{{height:100%;border-radius:4px;background:var(--green)}}
.note{{border:1px solid var(--border);border-left:3px solid var(--blue);
background:var(--card);padding:11px 15px;border-radius:12px;margin:14px 0;
font-size:.82rem;color:var(--muted)}}
.note b{{color:var(--text)}}
.ft{{margin-top:34px;padding-top:15px;border-top:1px solid var(--border);
font-size:.78rem;color:var(--muted);max-width:72ch}}
@media(max-width:560px){{.td,.th{{padding:7px 8px;font-size:.78rem}}
#q{{margin-inline-start:0;width:100%}}}}
</style></head><body><div class="page">

<h1>داشبورد ریسک و بازده — صندوق‌های ETF</h1>
<div class="sub">کلوز {stamp} ({WD[last_wd]}) · {len(rows)} نماد بررسی شد
· {len(ok_rows)} نماد با باکسِ معتبر</div>

{alarm_box}

<div class="cal"><table><tbody>{cal}</tbody></table>
<div class="mn">ماهانه: {month_note(last_date)}</div></div>

<div class="stats">{tiles}</div>

<div class="tabs">
  <button class="tab on" data-t="p1">سیگنال ماهانه</button>
  <button class="tab" data-t="p2">سیگنال هفتگی</button>
  <button class="tab" data-t="p3">دفترِ پیشنهادی</button>
  <button class="tab" data-t="p4">وضعیت همهٔ نمادها</button>
  <button class="tab" data-t="p5">بک‌تست</button>
</div>

<div class="filters">{chips}
  <input id="q" type="search" placeholder="جست‌وجوی نماد…"></div>

<div class="panel on" id="p1">
  <div class="sub">باکس از ماه میلادیِ کامل‌شدهٔ قبل. <b>نقطهٔ ورود</b>
  سقفِ باکس ‎+۳٪ است، نه خودِ سقف — در بک‌تست ورود روی سقف t=۱٫۳۵ داد و
  ۳٪ بالاتر t=۵٫۴۱. ستونِ آلارم می‌گوید قیمت الان چقدر تا آن فاصله دارد.
  <br><b>n دسته</b> و <b>موفقیتِ دسته</b> عددِ خودِ نماد نیست — بک‌تست
  روی کلِ دسته بسته شده، پس همهٔ نمادهای یک دسته یک عدد دارند.
  نمادِ <span class="thin">کم‌حجم</span> در دفتر نمی‌آید: ارزشِ معاملاتش
  زیرِ {MIN_VALUE_BN:.0f} میلیارد ریال است و پرشدنِ سفارش تضمین نیست.</div>
  <div class="wrap"><table class="table"><thead><tr>{thead(SIGH)}</tr>
  </thead><tbody>{sigtab("month")}</tbody></table></div>
</div>

<div class="panel" id="p2">
  <div class="sub">باکس از هفتهٔ کامل‌شدهٔ قبل (یکشنبه تا شنبه).
  نقطهٔ ورود سقفِ باکس ‎+۰٫۵٪ — باکس هفتگی یک‌سومِ ماهانه پهناست، پس
  ۳٪ بالاتر آنجا خراب می‌کند (−۰٫۰۵۳R).</div>
  <div class="wrap"><table class="table"><thead><tr>{thead(SIGH)}</tr>
  </thead><tbody>{sigtab("week")}</tbody></table></div>
</div>

<div class="panel" id="p3">
  <div class="sub">از هر دسته فقط <b>یکی</b>، و آن بزرگ‌ترین بر اساس
  ارزشِ معاملاتِ روزانه. زیر {MIN_VALUE_BN:.0f} میلیارد در روز حذف شده.</div>
  <div class="wrap"><table class="table"><thead><tr>
  {thead("نماد|دسته|باند|کلوز|نقطهٔ ورود|حدضرر|حدسود|ریسک|وزن|"
         "مبلغ (م.ر)|تعداد واحد|ضرر اگر استاپ|آلارم")}
  </tr></thead><tbody>{bk}</tbody></table></div>
  <div class="note"><b>اگر همه استاپ بخورند: {risk / capital * 100:.2f}٪
  سرمایه</b> ({n(risk / 1e6)} میلیون ریال). باندِ هر نماد خودکار انتخاب
  می‌شود: هفتگی، مگر اینکه ریسکِ هفتگی زیر ۱٪ باشد — آن‌وقت استاپ داخلِ
  نوسانِ یک روز می‌نشیند و باندِ ماهانه برداشته می‌شود.</div>
</div>

<div class="panel" id="p4">
  <div class="sub">هر {len(rows)} نماد. ستونِ آخر می‌گوید چرا در دفتر
  هست یا نیست — <b>هیچ نمادی بی‌صدا نمی‌افتد</b>.</div>
  <div class="wrap"><table class="table"><thead><tr>
  {thead("نماد|دسته|کلوز|ماه قبل|ماه جاری|هفتگی|حجم (م‌ر/روز)|وضعیت")}
  </tr></thead><tbody>{allr}</tbody></table></div>
</div>

<div class="panel" id="p5">
  {bt("month", "بک‌تست ماهانه",
      "بازدهِ ماهِ پیشِ رو بر اساس وضعیتِ باکس در روزِ تصمیم. ۱۲۱ نماد، ۱۱ ماه")}
  {bt("week", "بک‌تست هفتگی",
      "همان با افقِ هفتهٔ پیشِ رو. ۱۲۱ نماد، ۴۲ هفته")}
  <div class="note"><b>این اعداد توصیف‌اند، نه پیش‌بینی.</b> دورهٔ
  اندازه‌گیری ۱۱ ماه بوده و رژیمش صعودی — میانگین ماهانهٔ اهرم +۱۲٫۸۹٪
  در برابر +۲٫۸۷٪ در ۱۹ ماه قبلش.</div>
</div>

<p class="ft"><b>این توصیهٔ مالی نیست.</b> خوانشِ قاعده‌های خودت روی
داده است. لغزش مدل نشده: روی صندوقِ صف‌دار ممکن است اصلاً در نقطهٔ ورود
پر نشوی.</p>
</div>

<script>
(function(){{
  var nrm = function(x){{ return x
    .replace(/ي/g,'ی').replace(/ك/g,'ک')
    .replace(/‌/g,'').replace(/ /g,''); }};
  var tabs = document.querySelectorAll('.tab');
  tabs.forEach(function(b){{
    b.addEventListener('click', function(){{
      tabs.forEach(function(x){{ x.classList.remove('on'); }});
      document.querySelectorAll('.panel').forEach(function(p){{
        p.classList.remove('on'); }});
      b.classList.add('on');
      document.getElementById(b.dataset.t).classList.add('on');
    }});
  }});
  var cat = '*', q = document.getElementById('q');
  function apply(){{
    var v = nrm(q.value.trim());
    document.querySelectorAll('tr[data-s]').forEach(function(tr){{
      var okC = cat === '*' || tr.dataset.c === cat;
      var okQ = v === '' || nrm(tr.dataset.s).indexOf(v) >= 0;
      tr.classList.toggle('hide', !(okC && okQ));
    }});
    // سرفصلِ دسته‌ای که هیچ ردیفِ دیده‌شده‌ای ندارد باید برود،
    // وگرنه بعد از جست‌وجو یک ستونِ سرفصلِ تنها می‌ماند
    document.querySelectorAll('tr.grp').forEach(function(g){{
      var t = g.parentNode, n = 0, x = g.nextElementSibling;
      while (x && !x.classList.contains('grp')){{
        if (x.dataset.s && !x.classList.contains('hide')) n++;
        x = x.nextElementSibling;
      }}
      g.classList.toggle('hide', n === 0);
    }});
  }}
  document.querySelectorAll('.chip').forEach(function(c){{
    c.addEventListener('click', function(){{
      document.querySelectorAll('.chip').forEach(function(x){{
        x.classList.remove('on'); }});
      c.classList.add('on'); cat = c.dataset.c; apply();
    }});
  }});
  q.addEventListener('input', apply);
}})();
</script>
</body></html>"""


# ══ ۶. اجرا ═════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, default=0,
                    help="سرمایه به ریال؛ ۰ یعنی از data_bourse/capital.txt")
    ap.add_argument("--telegram", action="store_true")
    ap.add_argument("--no-open", dest="open", action="store_false")
    ap.add_argument("--no-ticks", dest="ticks", action="store_false",
                    help="برای نمادهایی که باکسِ هفتگی‌شان دره ندارد، "
                         "ریزمعاملات را نگیر (سریع‌تر ولی ۴۰٪ نماد با "
                         "باکسِ جایگزینِ ضعیف‌تر می‌مانند)")
    ap.add_argument("--sample", action="store_true",
                    help="یک روزِ ریزمعاملات را خام ذخیره کن، برای وقتی "
                         "که پارسر جواب نمی‌دهد")
    ap.add_argument("--probe", action="store_true",
                    help="منابعِ درون‌روزی را امتحان کن و گزارش بده")
    ap.add_argument("--max-weight", type=float, default=None,
                    help="سقفِ وزنِ هر نماد؛ پیش‌فرض ۳۴")
    ap.add_argument("--max-invested", type=float, default=None,
                    help="سقفِ سرمایهٔ در بازار؛ پیش‌فرض ۱۰۰")
    ap.add_argument("--no-curmonth", dest="curmonth", action="store_false",
                    help="شرطِ «ماه جاری هم بالا باشد» را خاموش کن")
    ap.add_argument("--offline", action="store_true",
                    help="دانلود نکن، از دادهٔ ذخیره‌شده استفاده کن")
    args = ap.parse_args()
    if args.probe:
        return probe()
    if args.sample:
        return sample()
    global REQUIRE_CUR_MONTH, MAX_INVESTED, MAX_WEIGHT
    if args.max_invested is not None:
        MAX_INVESTED = args.max_invested
    if args.max_weight is not None:
        MAX_WEIGHT = args.max_weight
    REQUIRE_CUR_MONTH = args.curmonth

    print("=" * 64)
    print("  بورس — تک‌فایل")
    print("=" * 64)

    if not args.offline:
        print("\n[۱/۴] پیدا کردن نمادها از دیدبان بازار...")
        try:
            ins = discover()
        except Exception as e:                       # noqa: BLE001
            print(f"\n  ✗ {e}")
            print("\n  اگر پیام بالا دربارهٔ شبکه است، اینترنت یا فیلترشکن")
            print("  را چک کن. اگر دربارهٔ کلیدهاست، همان متن را برای من")
            print("  بفرست تا پارسر را درست کنم.")
            print("\n  فعلاً با --offline روی دادهٔ قبلی کار کن.")
            return 1
        print(f"      {len(ins)} نماد شناخته شد")
        DATA.mkdir(exist_ok=True)
        (DATA / "inscodes.json").write_text(
            json.dumps(ins, ensure_ascii=False), encoding="utf-8")

        print(f"\n[۲/۴] دانلود تاریخچه...")
        ok = fail = 0
        for i, (sym, code) in enumerate(sorted(ins.items()), 1):
            if norm(sym) in NORM_FIXED:
                continue
            try:
                rows = fetch_symbol(sym, code)
                if len(rows) >= MIN_DAYS:
                    save(sym, rows)
                    ok += 1
                else:
                    fail += 1
            except Exception:                        # noqa: BLE001
                fail += 1
            if i % 20 == 0:
                print(f"      {i}/{len(ins)}...")
            time.sleep(0.25)
        print(f"      {ok} نماد ذخیره شد، {fail} تا نشد")
    else:
        print("\n[۱-۲/۴] حالت آفلاین — از دادهٔ ذخیره‌شده")

    print("\n[۳/۴] محاسبهٔ باکس‌ها و نوارها...")
    ins_map = {}
    imf = DATA / "inscodes.json"
    if imf.exists():
        try:
            ins_map = json.loads(imf.read_text(encoding="utf-8"))
        except ValueError:
            ins_map = {}
    # TSETMC گاهی یک نماد را با نیم‌فاصله و گاهی بی‌آن برمی‌گرداند، پس
    # «دارا یکم.csv» و «دارایکم.csv» هر دو ذخیره می‌شوند و نماد **دو بار**
    # در جدول می‌آمد. کلیدِ یکتا نامِ نرمال‌شده است؛ از میانِ فایل‌های
    # هم‌نام آن که تاریخچهٔ بلندتری دارد می‌ماند.
    best = {}
    for p in sorted(DATA.glob("*.csv")):
        sym = p.stem
        if sym == "capital" or norm(sym) in NORM_FIXED:
            continue
        k = norm(sym)
        cur = best.get(k)
        if cur is None or p.stat().st_size > cur.stat().st_size:
            best[k] = p

    rows = []
    for p in sorted(best.values()):
        sym = p.stem
        r = analyse(sym, load(sym), ins_map.get(sym),
                    allow_ticks=not args.offline and args.ticks)
        if r:
            rows.append(r)
    if not rows:
        print("      هیچ نمادی دادهٔ کافی نداشت.")
        return 1
    # ── صندوقِ «پارکِ پول» را از سیگنال‌ها بیرون بگذار ──────────────
    # مصطفی: «صندوق درآمد ثابت به درد نمی‌خوره، تو سیگنال‌ها نیارش…
    # زیتون، شیلد و اینا بازدهی‌هاشون کمه، فقط به درد پارکِ پول
    # می‌خوره.»
    #
    # با اسم نمی‌شود شناختشان — زیتون و شیلد در دستهٔ «مختلط» بودند و
    # در فهرستِ درآمد ثابت نبودند. ولی با **نوسان** بی‌خطا جدا می‌شوند.
    # اندازه‌گیری روی ۱۳۵ نماد: میانهٔ نوسانِ روزانه ۲٫۱۹٪، و اینها ته
    # فهرست‌اند — گارانتی ۰٫۲۱٪ · زیتون ۰٫۳۱٪ · انار ۰٫۳۹٪ ·
    # مختلط ۰٫۴۵٪ · شیلد ۰٫۵۹٪ — در حالی که بازدهِ کلشان ۱۹–۴۱٪ است
    # در برابر ۱۰۰٪+ بازار.
    #
    # آستانه **نسبی** است نه عددِ ثابت (بند ۰ قانون ۳): یک‌سومِ میانهٔ
    # خودِ جهانِ نمادها. با دادهٔ امروز یعنی ۰٫۷۳٪.
    vols = sorted(r["vol"] for r in rows if r.get("vol"))
    if vols:
        med = vols[len(vols) // 2]
        cut = med / 3.0
        npark = 0
        for r in rows:
            if r.get("vol") is not None and r["vol"] < cut:
                r["park"] = True
                r["reason"] = r.get("reason") or "پارکِ پول"
                npark += 1
        if npark:
            print(f"      {npark} صندوقِ پارکِ پول کنار گذاشته شد "
                  f"(نوسانِ زیر {cut:.2f}٪ · میانهٔ بازار {med:.2f}٪)")

    stamp = max(r["date"] for r in rows)
    print(f"      {len(rows)} نماد · کلوز {stamp}")

    capfile = DATA / "capital.txt"
    capital = args.capital
    if not capital and capfile.exists():
        try:
            capital = float(capfile.read_text(encoding="utf-8").strip()
                            .replace(",", ""))
        except ValueError:
            capital = 0
    if not capital:
        capital = 1_000_000_000
        capfile.parent.mkdir(exist_ok=True)
        capfile.write_text(str(int(capital)), encoding="utf-8")
        print(f"\n      سرمایه تنظیم نشده — فعلاً یک میلیارد فرض شد.")
        print(f"      عدد واقعی را در {capfile} بنویس.")

    elig, book = build_book(rows, capital)
    hot = [r for r in rows if r.get("ok")
           and (r["week"]["state"] == "در نوار"
                or r["month"]["state"] == "در نوار")]

    print("\n[۴/۴] ساخت صفحه...")
    y, mo, dd = (int(x) for x in stamp.split("-"))
    last_date = date(y, mo, dd)
    buy, sell = alarms(rows, book)
    OUT.write_text(html(rows, book, capital, stamp, last_date,
                        buy, sell),
                   encoding="utf-8")
    print(f"      {OUT}")

    print("\n" + "=" * 64)
    print(f"  امروز {stamp} است — {WD[last_date.weekday()]}")
    print("=" * 64)
    wd = last_date.weekday()
    print()
    for k, nm, ev, note in WEEK_PLAN:
        mark = "►" if k == wd else " "
        print(f"  {mark} {nm:<10} {ev}")
        if k == wd and note:
            print(f"    {'':<11}{note}")
    print(f"\n  ماهانه: {month_note(last_date)}")

    print("\n" + "=" * 64)
    print("  سفارشِ امروز")
    print("=" * 64)
    if book:
        print(f"\n  {'نماد':<10}{'باند':<8}{'ورود':>12}{'استاپ':>12}"
              f"{'تارگت':>12}{'ریسک':>7}{'تعداد':>13}")
        print("  " + "-" * 74)
        for r in book:
            z = r["z"]
            print(f"  {r['sym']:<10}"
                  f"{'هفتگی' if r['band']=='week' else 'ماهانه':<8}"
                  f"{z['aim']:>12,.0f}{z['stop']:>12,.0f}"
                  f"{z['target']:>12,.0f}{z['risk_pct']:>6.1f}٪"
                  f"{r['units']:>13,.0f}")
        print(f"\n  نقد: {100-sum(r['w'] for r in book):.0f}٪")
    else:
        print("\n  امروز هیچ نمادی واجد شرط نیست — همه نقد.")

    from collections import Counter
    why = Counter()
    for r in rows:
        if not r.get("ok"):
            why["باکس ساخته نشد"] += 1
        elif r["mst"] != "بالا":
            why["زیرِ ماه قبل"] += 1
        elif r["wst"] != "بالا":
            why["زیرِ هفتگی"] += 1
        elif REQUIRE_CUR_MONTH and r["cur_st"] not in ("بالا", "؟"):
            why["زیرِ ماهِ جاری"] += 1
        elif r["value_bn"] < MIN_VALUE_BN:
            why["حجمِ کم"] += 1
        else:
            why["واجد شرط"] += 1
    print(f"\n  {len(rows)} نماد بررسی شد — هیچ‌کدام بی‌صدا حذف نشد:")
    for k, v in why.most_common():
        print(f"     {k:<20} {v:>4}")

    # ── باکسِ هفتگی از کجا آمد ─────────────────────────────────────
    # این را باید **بلند** گفت. اگر TSETMC شکلِ XML را عوض کند،
    # parse_ticks صفر تیک می‌خواند، مسیرِ ساعتی بی‌صدا شکست می‌خورد و
    # همهٔ نمادها می‌افتند روی «ناحیهٔ ارزش» — تعریفی که در بک‌تستِ
    # ماهانه p=۰٫۱۰۶ داد، یعنی از تصادف جدا نمی‌شود. بدونِ این چند خط،
    # خروجی عادی به نظر می‌رسد در حالی که سیگنال مرده است.
    src = Counter()
    for r in rows:
        if not r.get("ok"):
            continue
        fb = r.get("fallback") or []
        if "هفتگی←ساعتی" in fb:
            src["درهٔ حجمی روی کندلِ ساعتی"] += 1
        elif "هفتگی" in fb:
            src["ناحیهٔ ارزش (ضعیف‌تر)"] += 1
        else:
            src["درهٔ حجمی روی کندلِ روزانه"] += 1
    if src:
        print("\n  باکسِ هفتگی از کجا آمد:")
        for k, v in src.most_common():
            print(f"     {k:<28} {v:>4}")
    weak = src.get("ناحیهٔ ارزش (ضعیف‌تر)", 0)
    ok_n = sum(src.values())
    if ok_n and weak / ok_n >= 0.30:
        print(f"\n  ⚠️  {weak} از {ok_n} نماد روی «ناحیهٔ ارزش» افتاده‌اند.")
        if not (not args.offline and args.ticks):
            print("      مسیرِ ریزمعاملات خاموش است. بدونِ --no-ticks اجرا کن.")
        elif not src.get("درهٔ حجمی روی کندلِ ساعتی"):
            print("      و مسیرِ ساعتی **هیچ** باکسی نساخت — یعنی تیکی"
                  " خوانده نشده.")
            print("      `python bourse.py --sample` را بزن و خروجی‌اش را"
                  " برایم بفرست؛")
            print("      احتمالاً TSETMC شکلِ XML را عوض کرده.")

    print(f"\n  {len(hot)} نماد در نوار خرید · {len(elig)} واجد شرط")

    # ── آلارم ──
    if buy or sell:
        print("\n" + "=" * 64)
        print("  🔔 آلارم")
        print("=" * 64)
        for sym, px, which, units in sell:
            print(f"  🔄 عوض کن {sym:<10} کلوز {px:>12,.0f} زیرِ باکسِ "
                  f"{which} · {units:,} واحد")
        if sell:
            print("     ↳ نقد نشو. پولش را ببر روی نمادی که بالای"
                  " باکسش است (فهرستِ زیر).")
        for sym, aim, stop, risk, tier in buy:
            tag = "" if tier == 1 else " (نیمه)"
            print(f"  🟢 خرید  {sym:<10} ورود {aim:>12,.0f} · "
                  f"استاپ {stop:,.0f} · ریسک {risk:.1f}٪{tag}")
    else:
        print("\n  🔕 امروز نه آلارمِ خرید هست نه فروش.")

    if args.telegram:
        txt = alarm_text(buy, sell, stamp)
        if book:
            txt += "\n\n<b>سفارشِ امروز</b>"
            for r in book:
                z = r["z"]
                txt += (f"\n• <b>{r['sym']}</b> ورود {z['aim']:,.0f} | "
                        f"استاپ {z['stop']:,.0f} | "
                        f"ریسک {z['risk_pct']:.1f}%")
        txt += "\n\nخوانشِ قاعده‌های خودت روی داده، نه توصیهٔ مالی."
        print("\n  تلگرام:", "رفت" if telegram(txt) else "نرفت")

    if args.open:
        try:
            webbrowser.open(OUT.as_uri())
        except Exception:                            # noqa: BLE001
            pass
    print("\n" + "=" * 64)
    print(f"  تمام. صفحه: {OUT}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
