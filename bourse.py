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
MAX_WEIGHT = 20.0         # سقف وزن هر نماد
# سقفِ کلِ سرمایهٔ در بازار. بک‌تستِ رو به جلو نشان داد تمرکز در این
# ۱۱ ماه ضرر داشت، و نقد گزینهٔ واقعی است — نه باقی‌ماندهٔ محاسبه.
MAX_INVESTED = 60.0
MIN_DAYS = 40

CATEGORY = {
    "املاک": "ارزش مسکن امین شهر دانیک عمارت دی مالک آتیه کاخ کاشانه کلید",
    "اهرمی": "اهرم بیدار توان جهش دوآیکس دوایکس شتاب موج نارنج پیشران",
    "بخشی": "امگا بانکا بانکدار بانکو بانکیا بنکر بنکوداریوش بهین رو تخت گاز خودران دارا یکم دارایکم دارونو دلتا رسانا رویین سمان سورنافود سیمانا سیمانو پالایش پتروآبان پتروآگاه پتروسورین پتروصبا پتروفارس پتروما پتروپاداش پناه پولاد چاشنی چتر",
    "سهامی": "آبنوس آتیمس آس آساس آمیتیس آوا آوان آوید آگاس ابتکار ارزش اطلس اعتبارسهام افق ملت الماس امتیاز انار اوج اکستریم اکسیژن بذر برلیان بزرگ تاراز ترمه تکپاد تیام ثروت ساز سینرژی پادا پرتو پرتوسا پیروز",
    "شاخصی": "آرام فیروزه هم تراز هم وزن همسنگ هوشمند وبازار کاردان",
    "صندوق_در_صندوق": "تمشک خوشه صنم",
    "طلا": "ریتون زر زرفام زروان زرگر زریران زمرد طلا عیار قلک گلد قیراط لیان مثقال مهرگلد میراث ناب نفیس نگین فارس همیان کهربا گلدا گلدیس گنج گوهر",
    "مختلط": "آسام آفرین زیتون شیلد صنوین ضمان مختلط هیبرید گارانتی",
    "نقره": "سیلور سیمین سیگلو نقرابی نقران نقرسا نقرفام نقرین پلاتا",
    "کالا_کشاورزی": "سافرون نهال",
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


# ══ ۲. باکس حجمی ════════════════════════════════════════════════════
def make_box(bars, min_rows=3, max_rows=20):
    """باکس = **اولین درهٔ حجمی از پایین**. بند ۱ راهنما.

    این پورتِ کلمه‌به‌کلمهٔ `tools/vp_box.py` است، که خودش وفادار به
    `lvn_clarity_cascade.pine` است و بیت‌به‌بیت با آن تطبیق داده شده.
    چهار ریزه‌کاری که اگر رعایت نشوند جواب عوض می‌شود:

      • دامنه از High/Low کلِ پنجره گرفته می‌شود، نه از Close
      • حجمِ هر کندل به نسبتِ هم‌پوشانی بینِ ردیف‌ها **پخش** می‌شود،
        نه اینکه کلش در ردیفِ Close بنشیند
      • کندلی با دامنهٔ صفر، کلِ حجمش در یک ردیف می‌نشیند
      • دره فقط روی ردیف‌های **میانی** (۱ تا rows−۲) شمرده می‌شود

    و خودِ باکس **یک ردیف** است — همان ردیفِ دره — نه بازه‌ای حولِ
    پرحجم‌ترین ردیف. (اولین بار این را اشتباه نوشتم و صفر درصد با نسخهٔ
    مرجع می‌خواند.)

    تعداد ردیف ثابت نیست: از ۳ بالا می‌رود تا اولین دره ظاهر شود.
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
            bot = r_lo + valleys[0] * step
            return (bot, bot + step)
    return None


def state(px, box):
    if box is None:
        return "؟"
    if px > box[1]:
        return "بالا"
    if px < box[0]:
        return "زیر"
    return "داخل"


def week_key(d):
    """هفتهٔ بورس ایران: شنبه تا چهارشنبه."""
    back = (d.weekday() - 5) % 7
    return d.fromordinal(d.toordinal() - back)


# ── تقویمِ تصمیم ────────────────────────────────────────────────────
# مصطفی: «صندوق‌های بورسی شنبه بسته می‌شود، ناحیه مشخص می‌شود، و کلوزِ
# یکشنبه جهت را تعیین می‌کند. تتر و دلار یکشنبه بسته می‌شوند و کلوزِ
# دوشنبه تصمیم‌گیرنده است.»
#
# اندازه‌گیری شد (`tools/decision_day.py`، مزیتِ درون‌هفته‌ای):
#
#   صندوق‌های بورسی، لنگرِ شنبه
#     روز ۱ شنبه      +۰٫۲۸۹ واحد   p=۰٫۰۰۰۳
#     روز ۲ یکشنبه    +۰٫۳۸۸ واحد   p=۰٫۰۰۰۳   ← بهترین
#     روز ۳ دوشنبه    +۰٫۲۹۵ واحد   p=۰٫۰۰۰۳
#
#   محرک‌ها (دلار، تتر، طلای ۱۸)، لنگرِ دوشنبه
#     روز ۱ دوشنبه    +۰٫۲۹۴ واحد   t=۳٫۸۲   p=۰٫۰۰۰۳   ← بهترین
#     روز ۲ سه‌شنبه   +۰٫۱۲۱ واحد   t=۱٫۸۰
#
# هر دو حرفش درست بود. تفاوتِ یکشنبه با شنبه کوچک است (+۰٫۰۹۹ واحد)
# ولی در همان جهتی است که او گفت.
DECIDE_FUND = 6      # یکشنبه — روز دومِ هفتهٔ بورس
DECIDE_DRIVER = 0    # دوشنبه — روز اولِ هفتهٔ جهانی
WD = ("دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه")


def today_says(last_date):
    """کلوزِ این روز چه تصمیمی را می‌سازد؟"""
    wd = last_date.weekday()
    out = []
    if wd == DECIDE_FUND:
        out.append(("صندوق‌های بورسی", "کلوزِ امروز تصمیم‌گیرنده است",
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
            "state": st}


# ══ ۳. تحلیل ════════════════════════════════════════════════════════
def analyse(sym, rows):
    if len(rows) < MIN_DAYS:
        return None
    by_m, by_w = defaultdict(list), defaultdict(list)
    for b in rows:
        by_m[(b["d"].year, b["d"].month)].append(b)
        by_w[week_key(b["d"])].append(b)
    ms, ws = sorted(by_m), sorted(by_w)
    if len(ms) < 2 or len(ws) < 2:
        return None
    px = rows[-1]["c"]
    mb = make_box(by_m[ms[-2]])
    wb = make_box(by_w[ws[-2]])
    if mb is None or wb is None:
        return None
    # باکسِ ماهِ **جاری** (تا امروز). مصطفی این ستون را در داشبورد قبلی
    # داشت و می‌خواهدش. ولی یک قید دارد که باید دیده شود: این باکس روی
    # دوره‌ای ساخته می‌شود که حجمش هنوز کامل نشده، و وقتی اندازه گرفتیم
    # (کنترلِ ماه × روزِ ماه) مزیتش +۰٫۰۱ واحد با t=+۰٫۰۶ درآمد — یعنی
    # از تصادف جدا نمی‌شود. پس **خبر** است، نه سیگنال.
    cur = make_box(by_m[ms[-1]]) if len(by_m[ms[-1]]) >= 3 else None
    vols = sorted(b["v"] for b in rows[-20:])
    mv = vols[len(vols) // 2] if vols else 0
    return {"sym": DISPLAY.get(norm(sym), sym),
            "cat": NORM_CAT.get(norm(sym), "؟"),
            "close": px, "date": rows[-1]["d"].isoformat(),
            "mst": state(px, mb), "wst": state(px, wb),
            "cur_box": cur, "cur_st": state(px, cur),
            "month": zone(mb, px, BAND["month"]),
            "week": zone(wb, px, BAND["week"]),
            "med_vol": mv, "value_bn": mv * px / 1e9}


def build_book(rows, capital):
    """واجد شرط: بالای هر دو باکس. از هر دسته فقط بزرگ‌ترین.

    **پهنای دسته.** اگر از ده صندوق طلا هشت تا زیر باکسِ هفتگی باشند،
    آن دو تای دیگر سیگنال نیستند — عقب‌افتاده‌اند. پس دسته‌ای که کمتر
    از نصفِ اعضایش بالای باکس هفتگی است کنار گذاشته می‌شود.
    """
    breadth = {}
    for r in rows:
        c = r["cat"]
        a, t = breadth.get(c, (0, 0))
        breadth[c] = (a + (1 if r["wst"] == "بالا" else 0), t + 1)
    wide = {c for c, (a, t) in breadth.items() if t and a / t >= 0.5}

    elig = [r for r in rows
            if r["mst"] == "بالا" and r["wst"] == "بالا"
            and r["value_bn"] >= MIN_VALUE_BN
            and (r["cat"] in wide or norm(r["sym"]) in NORM_EXEMPT)]
    best = {}
    for r in elig:
        c = r["cat"]
        if c not in best or r["value_bn"] > best[c]["value_bn"]:
            best[c] = r
    picks = sorted(best.values(), key=lambda r: -r["value_bn"])
    if not picks:
        return elig, []
    w = min(MAX_WEIGHT, MAX_INVESTED / len(picks))
    book = []
    for r in picks:
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


# ══ ۴. تلگرام ═══════════════════════════════════════════════════════
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
def html(rows, book, capital, stamp, last_date):
    last_wd = last_date.weekday()
    says = today_says(last_date)
    cal_html = "".join(
        f'<div class="t">{"🔔 " if who != "—" else ""}{who}'
        f'{" — " + what if who != "—" else what}</div>'
        f'<div class="d">{act}</div>' for who, what, act in says)
    cal_html += (
        '<div class="q"><b>تقویمِ تصمیم، اندازه‌گیری‌شده:</b> '
        'صندوق‌های بورسی هفته‌شان شنبه تا چهارشنبه است و '
        '<b>کلوزِ یکشنبه</b> تصمیم‌گیرنده — مزیت ‎+۰٫۳۸۸ واحد در برابر '
        '‎+۰٫۲۸۹ برای شنبه. تتر و دلار و طلای ۱۸ هفته‌شان دوشنبه تا '
        'یکشنبه است و <b>کلوزِ دوشنبه</b> تصمیم‌گیرنده — ‎+۰٫۲۹۴ واحد '
        'با t=۳٫۸۲، در برابر ‎+۰٫۱۲۱ برای سه‌شنبه.</div>')
    def n(x, d=0):
        return f"{x:,.{d}f}" if x == x else "—"

    PILL = {"بالا": "up", "داخل": "flat", "زیر": "down", "؟": "warn"}
    ZP = {"در نوار": "up", "زیر نوار": "flat", "بالای نوار": "down"}
    inv = sum(r["w"] for r in book)
    risk = sum(r["loss"] for r in book)

    def zrow(r, key):
        z, st = r[key], (r["mst"] if key == "month" else r["wst"])
        live = z["state"] == "در نوار"
        cur = ""
        if key == "month":
            cb = r["cur_box"]
            cur = (f'<td class="n">{n(cb[0])}–{n(cb[1])}</td>'
                   f'<td><span class="p {PILL.get(r["cur_st"],"warn")}">'
                   f'{r["cur_st"]}</span></td>') if cb else \
                  '<td class="n">—</td><td>—</td>'
        return (f'<tr class="{"" if live else "dim"}"><td class="s">{r["sym"]}</td>'
                f'<td class="n">{n(r["close"])}</td>'
                f'<td><span class="p {PILL.get(st,"warn")}">{st}</span></td>'
                + cur
                + f'<td class="n">{n(z["lo"])}–{n(z["hi"])}</td>'
                f'<td class="n"><b>{n(z["aim"])}</b></td>'
                f'<td class="n">{n(z["stop"])}</td>'
                f'<td class="n">{n(z["target"])}</td>'
                f'<td class="n">{z["risk_pct"]:.1f}٪</td>'
                f'<td><span class="p {ZP.get(z["state"],"flat")}">'
                f'{z["state"]}</span></td></tr>')

    def sorter(key):
        return sorted(rows, key=lambda r: (
            0 if r[key]["state"] == "در نوار" else
            1 if r[key]["state"] == "زیر نوار" else 2,
            r[key]["risk_pct"]))

    bk = "".join(
        f'<tr><td class="s">{r["sym"]}</td>'
        f'<td>{"هفتگی" if r["band"]=="week" else "ماهانه"}</td>'
        f'<td>{r["cat"]}</td><td class="n">{n(r["close"])}</td>'
        f'<td class="n"><b>{n(r["z"]["aim"])}</b></td>'
        f'<td class="n">{n(r["z"]["stop"])}</td>'
        f'<td class="n">{n(r["z"]["target"])}</td>'
        f'<td class="n">{r["z"]["risk_pct"]:.1f}٪</td>'
        f'<td class="n">{r["w"]:.0f}٪</td>'
        f'<td class="n">{n(r["amt"]/1e6)}</td>'
        f'<td class="n">{n(r["units"])}</td>'
        f'<td class="n">{n(r["value_bn"])}</td>'
        f'<td><span class="p {ZP.get(r["z"]["state"],"flat")}">'
        f'{r["z"]["state"]}</span></td></tr>' for r in book)
    bk += (f'<tr class="dim"><td class="s">نقد</td><td colspan="7"></td>'
           f'<td class="n"><b>{100-inv:.0f}٪</b></td>'
           f'<td class="n">{n(capital*(100-inv)/100/1e6)}</td>'
           f'<td colspan="3"></td></tr>')

    return f"""<!doctype html><html lang="fa" dir="rtl"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>بورس — {stamp}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;700;900&display=swap">
<style>
:root{{--bg:#EEF1F5;--sf:#fff;--sk:#F6F8FA;--ink:#141E29;--mut:#5B6874;
--ln:#D5DDE5;--br:#8A6512;--up:#0B6E4F;--upb:#DFF1E9;--fl:#66727E;
--flb:#E8ECF0;--dn:#A32A21;--dnb:#FAE3E1;--wn:#8A5A00;--wnb:#FBF0DB}}
@media(prefers-color-scheme:dark){{:root{{--bg:#0C1117;--sf:#141C25;
--sk:#101821;--ink:#E3EAF1;--mut:#95A2AF;--ln:#25313C;--br:#D6A93A;
--up:#45C28F;--upb:#10281F;--fl:#8A96A2;--flb:#1B242E;--dn:#EE7365;
--dnb:#2E1715;--wn:#D9A445;--wnb:#2A2113}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font-size:15px;
line-height:1.7;font-family:Vazirmatn,"Segoe UI",system-ui,sans-serif}}
.w{{max-width:1150px;margin:0 auto;padding:26px 16px 50px}}
h1{{font-size:32px;font-weight:900;margin:0;letter-spacing:-.02em}}
.st{{color:var(--mut);font-size:13px}}
h2{{font-size:18px;margin:0;font-weight:700}}
section{{margin-top:36px}}
.hd{{display:flex;align-items:baseline;gap:12px;border-bottom:2px solid
var(--br);padding-bottom:6px;margin-bottom:8px}}
.hd .x{{margin-inline-start:auto;font-size:12px;color:var(--mut)}}
.nt{{color:var(--mut);font-size:13px;margin:8px 0 14px;max-width:70ch}}
.tb{{overflow-x:auto;background:var(--sf);border:1px solid var(--ln);
border-radius:9px}}
table{{border-collapse:collapse;width:100%;font-size:13px;
font-variant-numeric:tabular-nums}}
th,td{{padding:8px 10px;text-align:right;white-space:nowrap;
border-bottom:1px solid var(--ln)}}
thead th{{background:var(--sk);font-size:11px;color:var(--mut);font-weight:700}}
tbody tr:last-child td{{border-bottom:none}}
td.s{{font-weight:700}} td.n,th.n{{text-align:left}}
tr.dim td{{color:var(--mut)}}
.p{{display:inline-block;padding:1px 8px;border-radius:11px;
font-size:11px;font-weight:700}}
.up{{background:var(--upb);color:var(--up)}}
.flat{{background:var(--flb);color:var(--fl)}}
.down{{background:var(--dnb);color:var(--dn)}}
.warn{{background:var(--wnb);color:var(--wn)}}
.box{{border-inline-start:3px solid var(--br);background:var(--sf);
padding:12px 15px;border-radius:0 8px 8px 0;margin:14px 0;
font-size:13px;color:var(--mut)}}
.box b{{color:var(--ink)}}
.cal{{margin-top:18px;border:2px solid var(--br);border-radius:10px;
background:var(--sf);padding:14px 18px}}
.cal .t{{font-size:17px;font-weight:900}}
.cal .d{{font-size:13px;color:var(--mut);margin-top:3px}}
.cal .q{{font-size:12px;color:var(--mut);margin-top:9px;
padding-top:9px;border-top:1px solid var(--ln)}}
.ft{{margin-top:40px;padding-top:16px;border-top:1px solid var(--ln);
font-size:12px;color:var(--mut);max-width:70ch}}
</style></head><body><div class="w">

<h1>سفارشِ امروز</h1>
<div class="st">کلوز {stamp} ({WD[last_wd]}) · سرمایه
{n(capital/1e9,1)} میلیارد ریال · {len(rows)} نماد بررسی شد</div>

<div class="cal">{cal_html}</div>

<section><div class="hd"><h2>دفتر</h2>
<span class="x">{len(book)} نماد · {inv:.0f}٪ در بازار</span></div>
<p class="nt">از هر دسته فقط <b>یکی</b>، و آن بزرگ‌ترین بر اساس ارزشِ
معاملاتِ روزانه — اعضای یک دسته همگرایی بالایی دارند، پس دو تا برداشتن
ریسک را پخش نمی‌کند و فقط نقدشوندگی را بدتر می‌کند. نمادهای زیر
{MIN_VALUE_BN:.0f} میلیارد در روز حذف شده‌اند.</p>
<div class="tb"><table><thead><tr><th>نماد</th><th>باند</th><th>دسته</th>
<th class="n">کلوز</th><th class="n">ورود</th><th class="n">استاپ</th>
<th class="n">تارگت</th><th class="n">ریسک</th><th class="n">وزن</th>
<th class="n">مبلغ (م.ر)</th><th class="n">تعداد واحد</th>
<th class="n">حجم (میلیارد/روز)</th><th>وضعیت</th></tr></thead>
<tbody>{bk}</tbody></table></div>
<div class="box"><b>اگر همه استاپ بخورند: {risk/capital*100:.2f}٪ سرمایه</b>
({n(risk/1e6)} میلیون ریال).<br>
باندِ هر نماد خودکار انتخاب می‌شود: هفتگی، مگر اینکه ریسکِ هفتگی زیر ۱٪
باشد — آن‌وقت استاپ داخلِ نوسانِ یک روز می‌نشیند و باندِ ماهانه
برداشته می‌شود.</div></section>

<section><div class="hd"><h2>داشبورد ماهانه</h2>
<span class="x">نوار: سقفِ باکس تا +۴٪ · هدف +۳٪</span></div>
<p class="nt">ستونِ «ماه قبل» باکسِ ماه میلادیِ کامل‌شده است — همان که
تصمیم رویش گرفته می‌شود. ستونِ «ماهِ جاری» چراغِ زندهٔ ماهِ در جریان است:
<b>خبر است، نه سیگنال</b> — وقتی با کنترلِ ماه × روزِ ماه اندازه گرفته
شد، مزیتش ‎+۰٫۰۱ واحد با t=+۰٫۰۶ درآمد، یعنی از تصادف جدا نشد. حجم تا
پایان دوره کامل نمی‌شود، پس باکسِ وسطِ دوره معتبر نیست.<br>
ورود روی خودِ سقفِ باکس t=۱٫۳۵ داد؛ ورودِ ۳٪ بالاتر t=۵٫۴۱.</p>
<div class="tb"><table><thead><tr><th>نماد</th><th class="n">کلوز</th>
<th>ماه قبل</th><th class="n">باکسِ ماهِ جاری</th><th>جاری</th>
<th class="n">نوار</th><th class="n">ورود</th>
<th class="n">استاپ</th><th class="n">تارگت</th><th class="n">ریسک</th>
<th>وضعیت</th></tr></thead><tbody>
{"".join(zrow(r, "month") for r in sorter("month"))}
</tbody></table></div></section>

<section><div class="hd"><h2>داشبورد هفتگی</h2>
<span class="x">نوار: سقفِ باکس تا +۲٪ · هدف +۰٫۵٪</span></div>
<p class="nt">باکس از هفتهٔ کامل‌شدهٔ قبل، شنبه تا چهارشنبه. باکس هفتگی
یک‌سومِ ماهانه پهناست، پس نوارش باریک‌تر است — ۳٪ بالاتر آنجا خراب
می‌کند (‎−۰٫۰۵۳R).</p>
<div class="tb"><table><thead><tr><th>نماد</th><th class="n">کلوز</th>
<th>باکس</th><th class="n">نوار</th><th class="n">ورود</th>
<th class="n">استاپ</th><th class="n">تارگت</th><th class="n">ریسک</th>
<th>وضعیت</th></tr></thead><tbody>
{"".join(zrow(r, "week") for r in sorter("week"))}
</tbody></table></div></section>

<p class="ft"><b>این توصیهٔ مالی نیست.</b> خوانشِ قاعده‌های خودت روی
داده است. اعدادِ بک‌تست از ۱۱ ماهی می‌آیند که رژیمِ معمولی نبوده —
میانگین ماهانهٔ اهرم ‎+۱۲٫۸۹٪ در برابر ‎+۲٫۸۷٪ در ۱۹ ماه قبلش. و
لغزش مدل نشده: روی صندوقِ صف‌دار ممکن است اصلاً در قیمتِ نوار پر نشوی.
</p></div></body></html>"""


# ══ ۶. اجرا ═════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, default=0,
                    help="سرمایه به ریال؛ ۰ یعنی از data_bourse/capital.txt")
    ap.add_argument("--telegram", action="store_true")
    ap.add_argument("--no-open", dest="open", action="store_false")
    ap.add_argument("--offline", action="store_true",
                    help="دانلود نکن، از دادهٔ ذخیره‌شده استفاده کن")
    args = ap.parse_args()

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
    rows = []
    for p in sorted(DATA.glob("*.csv")):
        sym = p.stem
        if norm(sym) in NORM_FIXED:
            continue
        r = analyse(sym, load(sym))
        if r:
            rows.append(r)
    if not rows:
        print("      هیچ نمادی دادهٔ کافی نداشت.")
        return 1
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
    hot = [r for r in rows
           if r["week"]["state"] == "در نوار" or r["month"]["state"] == "در نوار"]

    print("\n[۴/۴] ساخت صفحه...")
    y, mo, dd = (int(x) for x in stamp.split("-"))
    last_date = date(y, mo, dd)
    OUT.write_text(html(rows, book, capital, stamp, last_date),
                   encoding="utf-8")
    print(f"      {OUT}")

    print("\n" + "=" * 64)
    print(f"  امروز {stamp} است — {WD[last_date.weekday()]}")
    print("=" * 64)
    for who, what, act in today_says(last_date):
        if who == "—":
            print(f"\n  {what}")
            print(f"  {act}")
        else:
            print(f"\n  🔔 {who}: {what}")
            print(f"     {act}")

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

    print(f"\n  {len(hot)} نماد در نوار خرید · {len(elig)} واجد شرط")

    if args.telegram:
        lines = [f"<b>سفارشِ امروز</b> — {stamp}"]
        if book:
            for r in book:
                z = r["z"]
                lines.append(
                    f"• <b>{r['sym']}</b> ورود {z['aim']:,.0f} | "
                    f"استاپ {z['stop']:,.0f} | ریسک {z['risk_pct']:.1f}%")
        else:
            lines.append("امروز نمادی واجد شرط نیست.")
        lines.append("")
        lines.append("خوانشِ قاعده‌های خودت روی داده، نه توصیهٔ مالی.")
        print("\n  تلگرام:", "رفت" if telegram("\n".join(lines)) else "نرفت")

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
