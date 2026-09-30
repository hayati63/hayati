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
import bisect
import csv
import gzip
import io
import json
import math
import os
import random
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

# ── حالتِ سهام ──────────────────────────────────────────────────────
# مصطفی: «اگر بتونی برای کل سهام‌هایی که تو بورس هست و حجم می‌خورند،
# مثل وبملت و سهم‌های بزرگ، این استراتژی را هم بک‌تست بگیری و یک
# داشبوردِ جدا بسازی.»
#
# سه چیز **باید** فرق کند وگرنه عددها غلط‌اند:
#
# ۱. **کارمزد.** بند ۹ راهنما: صندوق ۰٫۵۵٪ رفت‌وبرگشت، سهام ~۱٫۲٪ —
#    و همان‌جا نوشته «با کارمزدِ واقعیِ سهام شاراک و سقاین هم منفی
#    می‌شوند. مزیت روی صندوقِ اهرمی محکم است و روی سهام نازک.»
# ۲. **جدولِ نرخِ برد.** WINRATE پایین از بک‌تستِ ۱۲۱ **صندوق** آمده.
#    گذاشتنش کنارِ یک سهم یعنی نشان دادنِ آمارِ یک جهان به جهانِ دیگر.
#    در حالتِ سهام، جدول از خودِ دادهٔ سهام ساخته می‌شود.
# ۳. **دسته‌بندی.** جدولِ CATEGORY همه‌اش صندوق است، پس همهٔ سهام‌ها
#    «بدون دسته» می‌شدند. گروهِ صنعت از دیدبان خوانده می‌شود و اگر
#    نبود، ردهٔ ارزشِ معاملات جایش می‌نشیند.
STOCK = False             # با --stocks روشن می‌شود
LIVE_STATE = False        # با --now: وضعیت روی آخرین کلوز، نه روزِ تصمیم
# "valley" = ردیفِ دره (انتخابِ مصطفی) · "poc" = ناحیهٔ پرحجمِ حولِ POC
BOX_KIND = "valley"
COST_FUND = 0.55
COST_STOCK = 1.20
# سهمِ سرمایه که در حالتِ --all به چرخشِ سهام می‌رسد.
# صفر است و دلیلش اندازه‌گیری است، نه سلیقه — docs/34.
STOCK_SHARE = 0.0
# اوراقِ بدهی که در دیدبان می‌آیند ولی سهم نیستند. عمداً **کوتاه**
# است: هر پیشوندی که اضافه کنم ممکن است سهمِ واقعی را بی‌صدا بیندازد
# بیرون، و بی‌صدا افتادن دقیقاً همان چیزی است که مصطفی روی نهال گرفت.
# فیلترِ اصلی ارزشِ معاملات است، و اجرا فهرستِ نهایی را چاپ می‌کند تا
# اگر چیزِ عجیبی تویش بود با چشم دیده شود.
NOT_STOCK_PREFIX = ("اخزا", "اراد", "افاد", "مرابحه", "سلف", "مشارکت")
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
# سقفِ وزنِ هر نماد. اندازه‌گیری‌شده: با N=۶ عملاً ۱۶٫۷٪ می‌شود و سقف
# فقط وقتی می‌بندد که کمتر از ۴ نماد واجد شرط باشند — آن‌وقت باقی‌مانده
# روی کهربا می‌نشیند.
MAX_WEIGHT = 25.0
# تعدادِ نمادِ هم‌زمان. ۶ و ۸ تنها چینش‌هایی بودند که در هر دو نیمهٔ
# پنجره از کهربا جلو زدند؛ ۶ بهتر (۱٫۱۵۲ در برابر ۱٫۱۲۰).
MAX_PICKS = 6
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


def backtest_universe(data, iters=2000, seed=7):
    """جدولِ نرخِ برد را **از خودِ داده** بساز — برای جهانی که
    WINRATE دربارهٔ آن حرفی ندارد (سهام).

    گذاشتنِ جدولِ صندوق‌ها کنارِ یک سهم، عددِ یک جهان را به جهانِ
    دیگر نسبت می‌دهد. پس در حالتِ سهام جدول دوباره ساخته می‌شود، با
    **همان** تعریف‌های `analyse()` (همان make_box، همان state، همان
    wr_key) تا قابلِ مقایسه بماند.

    و مثل همیشه (بند ۰ قانون ۲): کنارِ هر سطر **نرخ پایهٔ همان دوره**
    و p از آزمونِ جایگشتِ درون‌دوره‌ای می‌آید. جایگشت برچسبِ وضعیت را
    داخلِ هر هفته/ماه به‌هم می‌ریزد، پس حرکتِ کلِ بازار در آن دوره
    ثابت می‌ماند و سؤال فقط این است: «آیا باکس نمادهای بهتری از
    تصادف انتخاب می‌کند؟»

    خروجی: {"week": {...}, "month": {...}} هم‌شکلِ WINRATE، به‌علاوهٔ
    کلیدِ "_p" با p هر سطر.
    """
    rnd = random.Random(seed)
    out = {}
    for hz in ("week", "month"):
        per = defaultdict(list)          # {دوره: [(برچسب، بازده)]}
        for sym, rows in data.items():
            if len(rows) < MIN_DAYS:
                continue
            by_m, by_w = defaultdict(list), defaultdict(list)
            for b in rows:
                by_m[(b["d"].year, b["d"].month)].append(b)
                by_w[week_key(b["d"])].append(b)
            ms, ws = sorted(by_m), sorted(by_w)
            ks = ws if hz == "week" else ms
            by = by_w if hz == "week" else by_m
            if len(ks) < 4 or len(ms) < 3:
                continue
            for i in range(2, len(ks) - 1):
                cur = by[ks[i]]
                if not cur:
                    continue
                d, px = cur[-1]["d"], cur[-1]["c"]
                if px <= 0:
                    continue
                # ── باکسِ هفتگی: هفتهٔ کاملِ قبل ──────────────────
                pw = None
                for j in range(len(ws) - 1, -1, -1):
                    if by_w[ws[j]] and by_w[ws[j]][-1]["d"] < d:
                        pw = by_w[ws[j]]
                        break
                # ── باکسِ ماهانه: ماهِ کاملِ قبل ────────────────────
                mk = (d.year, d.month)
                pm = None
                if mk in by_m:
                    idx = ms.index(mk)
                    if idx > 0:
                        pm = by_m[ms[idx - 1]]
                if not pw or not pm or len(pw) < 3 or len(pm) < 3:
                    continue
                wb = make_box(pw) or value_area_box(pw)
                mb = make_box(pm) or value_area_box(pm)
                if wb is None or mb is None:
                    continue
                cmb = [b for b in by_m[mk] if b["d"] <= d]
                cb = ((make_box(cmb) or value_area_box(cmb))
                      if len(cmb) >= 3 else None)
                key = wr_key({"mst": state(px, mb), "wst": state(px, wb),
                              "cur_st": state(px, cb) if cb else "؟"})
                if key is None:
                    continue
                nxt = by[ks[i + 1]]
                if not nxt:
                    continue
                per[ks[i]].append((key, (nxt[-1]["c"] / px - 1) * 100))

        allr = [r for xs in per.values() for _k, r in xs]
        if not allr:
            out[hz] = {}
            continue
        tab = {"_base": (len(allr),
                         round(sum(1 for x in allr if x > 0) / len(allr) * 100),
                         round(statistics.mean(allr), 2))}
        # ساختارِ فشرده برای جایگشت — یک بار، نه در هر تکرار
        packed = []
        for _k, xs in per.items():
            if len(xs) < 3:
                continue
            rs = [r for _s, r in xs]
            cnt = defaultdict(int)
            for st_, _r in xs:
                cnt[st_] += 1
            packed.append((rs, statistics.mean(rs), dict(cnt)))
        ps = {}
        for key in {k for xs in per.values() for k, _r in xs}:
            v = [r for xs in per.values() for k, r in xs if k == key]
            if len(v) < 20:
                continue
            tab[key] = (len(v),
                        round(sum(1 for x in v if x > 0) / len(v) * 100),
                        round(statistics.mean(v), 2))
            es = []
            for _k2, xs in per.items():
                sel = [r for k, r in xs if k == key]
                if not sel or len(xs) < 3:
                    continue
                es.append(statistics.mean(sel)
                          - statistics.mean([r for _s, r in xs]))
            if not es:
                continue
            real = statistics.mean(es)
            ge = 0
            for _ in range(iters):
                fake = []
                for rs, mu, cnt in packed:
                    k2 = cnt.get(key, 0)
                    if not k2:
                        continue
                    fake.append(sum(rnd.sample(rs, k2)) / k2 - mu)
                if fake and statistics.mean(fake) >= real:
                    ge += 1
            ps[key] = round((ge + 1) / (iters + 1), 4)
        tab["_p"] = ps
        out[hz] = tab
    return out


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
# ── پرتفوی واقعی، از دو حسابِ کارگزاری (۱۴۰۵/۰۷/۰۶) ────────────────
# حسابِ «مصطفی حیاتی وادقانی» ستونِ مانده را مستقیم می‌دهد؛ حسابِ
# «منا محمدی» تعداد ندارد، پس از بهای تمام شده ÷ میانگین خرید درآمد —
# هر پنج قلم به عددِ صحیح رسید، که یعنی خوانش درست است.
#
#   نماد      مصطفی      منا      مجموع
#   نقران    452,604       —     452,604
#   سینرژی   334,888    78,164   413,052
#   کهربا    219,141       —     219,141
#   نهال     115,046       —     115,046
#   عیار      20,444    13,000    33,444
#   دوایکس       529     4,535     5,064
#   وسپه           —       416       416
#   فباهنر         1       —           1
#   شکربن          —         1         1
HOLDING = {"نقران": 452604, "سینرژی": 413052, "کهربا": 219141,
           "نهال": 115046, "عیار": 33444, "دوایکس": 5064,
           "وسپه": 416, "فباهنر": 1, "شکربن": 1}
NORM_HOLD = {norm(k): v for k, v in HOLDING.items()}
# نقدِ بند ۷ راهنما. اگر عوض شد، یا اینجا، یا data_bourse/capital.txt
# قدرتِ خریدِ حسابِ مصطفی. حسابِ منا نقدش معلوم نیست.
CASH = 11_588_547_959

# ── نمادهای پرتفو که **صندوق نیستند** ──────────────────────────────
# سمازن، شاراک، سقاین و فباهنر سهم‌اند. `discover()` فقط نمادهایی را
# نگه می‌دارد که در جدولِ CATEGORY باشند، و آن جدول همه‌اش صندوق است —
# پس این چهار تا هیچ‌وقت قیمت نمی‌گیرند و سرمایه همیشه کم‌برآورد
# می‌ماند. insCodeها از بند ۷ راهنما می‌آید.
#
# ⚠️ این‌ها فقط برای **ارزش‌گذاری** گرفته می‌شوند، نه برای سیگنال:
# استراتژی روی صندوق اعتبارسنجی شده و بند ۹ راهنما می‌گوید با کارمزدِ
# واقعیِ سهام (~۱٫۲٪) مزیت روی سهام منفی می‌شود.
# سمازن، شاراک و سقاین دیگر در پرتفو نیستند. مانده‌ها: فباهنر (۱ واحد)
# و وسپه و شکربن که insCode ندارم — ولی جمعاً ۳٫۱ میلیون ریال‌اند،
# یعنی ۰٫۰۰۲٪ پرتفو. نبودنشان عدد را عوض نمی‌کند، و برنامه هم
# بی‌صدا ردشان نمی‌کند: نامشان با هشدار چاپ می‌شود.
HOLD_INS = {"فباهنر": "66772024744156373"}


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


def discover_stocks(min_value_bn=None):
    """نمادهای **سهام** از دیدبان: (نام → insCode، نام → گروهِ صنعت).

    `discover()` فقط چیزهایی را نگه می‌دارد که در جدولِ CATEGORY
    باشند — و آن جدول همه‌اش صندوق است. اینجا برعکس: هر چیزی که
    صندوقِ شناخته‌شده و اوراق نیست، و حجم می‌خورد.

    ⚠️ این تابع از این کانتینر **تست نشده** — TSETMC اینجا ۴۰۳ می‌دهد.
    پس مثل `discover()` خودتشخیص است: اگر هیچ نمادی درنیامد، کلیدهای
    واقعیِ پاسخ را چاپ می‌کند به‌جای اینکه خالی برگردد.
    """
    d = get(WATCH)
    rows = d if isinstance(d, list) else (
        d.get("marketwatch") or d.get("MarketWatch") or [])
    SYM_KEYS = ("lva", "lVal18AFC", "symbol", "Symbol", "lva18", "l18")
    INS_KEYS = ("insCode", "InsCode", "inscode", "insCode18")
    # گروهِ صنعت. TSETMC بینِ نسخه‌ها اسمش را عوض کرده و از اینجا
    # نمی‌شود دید کدامش زنده است، پس چندتا امتحان می‌شود.
    SEC_KEYS = ("lSecVal", "LSecVal", "lsecval", "sector",
                "Sector", "cs", "CS")
    PX_KEYS = ("pcl", "pClosing", "pdv", "pDrCotVal")
    VOL_KEYS = ("qtj", "qTotTran5J", "vol", "zTotTran")
    mv = MIN_VALUE_BN if min_value_bn is None else min_value_bn

    def pick(r, keys):
        for k in keys:
            v = r.get(k)
            if v not in (None, "", 0):
                return v
        return None

    allsym = set()
    cand = []
    for r in rows:
        sym = pick(r, SYM_KEYS)
        ins = pick(r, INS_KEYS)
        if not sym or not ins:
            continue
        sym = str(sym).strip()
        allsym.add(sym)
        cand.append((sym, str(ins).strip(), pick(r, SEC_KEYS),
                     pick(r, PX_KEYS), pick(r, VOL_KEYS)))

    out, sec, thin, dropped = {}, {}, 0, 0
    for sym, ins, sc, px, vol in cand:
        k = norm(sym)
        if k in NORM_CAT or k in NORM_FIXED:      # صندوق یا درآمد ثابت
            dropped += 1
            continue
        if any(sym.startswith(x) for x in NOT_STOCK_PREFIX):
            dropped += 1
            continue
        # حقِ تقدم: «وبملتح» وقتی «وبملت» هم در فهرست است
        if sym.endswith("ح") and sym[:-1] in allsym:
            dropped += 1
            continue
        try:
            v_bn = float(px) * float(vol) / 1e9
        except (TypeError, ValueError):
            v_bn = 0.0
        if v_bn < mv:
            thin += 1
            continue
        out[sym] = ins
        if sc:
            sec[sym] = str(sc).strip()

    if not out:
        keys = sorted(rows[0].keys()) if rows else []
        raise RuntimeError(
            f"از {len(rows)} ردیفِ دیدبان هیچ سهمی درنیامد "
            f"(حدِ ارزش {mv:.0f} م.ر).\n"
            f"  کلیدهای واقعیِ پاسخ: {', '.join(keys[:30])}\n"
            "  این متن را بفرست تا پارسر را درست کنم، یا "
            "--min-value را کم کن.")
    print(f"      {len(out)} سهم · {dropped} صندوق/اوراق کنار رفت · "
          f"{thin} زیرِ {mv:.0f} م.ر")
    if sec:
        print(f"      گروهِ صنعت خوانده شد ({len(set(sec.values()))} گروه)")
    else:
        print("      ⚠️  گروهِ صنعت در پاسخ نبود — "
              "دسته‌بندی با ردهٔ ارزشِ معاملات")
    return out, sec


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
    """باکس حجمی. دو تعریف، با `BOX_KIND` انتخاب می‌شود.

    **پیش‌فرض `valley`** — ردیفِ دره، خودش. انتخابِ مصطفی و همان بند ۱
    راهنما: «از ۳ شروع می‌شود و بالا می‌رود تا اولین درهٔ حجمی ظاهر
    شود.» عددهای پایین خلافش را نشان می‌دادند؛ گفتم و او تصمیم گرفت.

    **`poc`** — بازهٔ پیوستهٔ پرحجم حولِ POC، محدود به دره‌ها.

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

    POC در هر دو افق هم بهتر جدا می‌کند و هم هندسهٔ سالم‌تری دارد —
    **ولی این اندازه‌گیری روی کندلِ روزانه بود.** بند ۱ راهنما پروفایلِ
    هفتگی را روی H1 می‌خواهد، و با پروفایلِ ریزتر دره جای دیگری می‌افتد
    و پهنای دو تعریف به هم نزدیک می‌شود. پس این جدول **تجدیدِ
    اندازه‌گیری می‌خواهد** حالا که مسیرِ H1 اصلی شده.
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
            if BOX_KIND == "valley":
                # ── ردیفِ دره، خودش ────────────────────────────────
                # مصطفی: «ما باید بر اساسِ ردیفِ دره کلاً بچینیم. از
                # شمارهٔ سه شروع می‌کنیم به بالا، اولین دره می‌شود.
                # این اصولِ کلیِ ما بود.» — بند ۱ راهنما.
                #
                # ⚠️ اندازه‌گیریِ من خلافش را نشان داده بود (باکسِ POC
                # مزیتِ +۱٫۷۲ در برابر +۰٫۷۶ و R برابرِ +۰٫۳۳۳ در برابر
                # +۰٫۱۷۱). عدد را گفتم، انتخاب با اوست و این پیش‌فرض
                # شد. با --box poc برمی‌گردد.
                v0 = valleys[0]
                return (r_lo + v0 * step, r_lo + (v0 + 1) * step)
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


# ── کندلِ سازندهٔ ناحیه — استراتژیِ سومِ مصطفی ──────────────────────
# مصطفی: «گاهی قیمت‌ها تا نزدیکیِ محدوده می‌آیند و واکنش می‌دهند به
# کندلی که به ناحیه در ارتباط هست.»
#
# یعنی سطحِ واکنش لزوماً خودِ مرزِ باکس نیست؛ کندلی که ناحیه را ساخته
# جای دقیق‌تری است. اندازه‌گیری شد (`tools/reaction.py`, `docs/35`)
# روی ۱٬۶۸۴ سیگنالِ هفتگی و ۵۴۳ ماهانه، با هندسهٔ یکسان برای همه و
# بوت‌استرپِ خوشه‌ای روی نماد:
#
#   هفتگی   کلوزِ کندلِ سازنده   Δبرد +۶٫۳  بازهٔ +۱٫۲ تا +۱۱٫۴  ۲٪ برعکس
#   ماهانه  سقفِ کندلِ سازنده    Δبرد +۱۱٫۶ بازهٔ +۵٫۴ تا +۱۷٫۶  ۰٪ برعکس
#   کنترل «سقفِ باکس +۱٪»       هفتگی +۰٫۹ با ۳۵٪ برعکس ← هیچ
#
# گروهِ کنترل مهم است: اگر «هر سطحِ بالاتر» هم همین‌قدر بهتر می‌شد،
# یافته دربارهٔ کندل نبود. نشد — پس هست.
def zone_candle(bars, box):
    """کندلی که بیشترین حجم را به بازهٔ باکس داده.

    سهمِ هر کندل به نسبتِ هم‌پوشانیِ دامنه‌اش با باکس حساب می‌شود —
    همان قاعدهٔ پخشِ حجمِ `make_box`, نه «کلِ حجم در ردیفِ کلوز».
    """
    if not box or not bars:
        return None
    lo, hi = box
    best, bv = None, 0.0
    for b in bars:
        if b["l"] > hi or b["h"] < lo:
            continue
        br = b["h"] - b["l"]
        share = (b["v"] if br <= 0
                 else b["v"] * max(0.0, min(hi, b["h"])
                                   - max(lo, b["l"])) / br)
        if share > bv:
            best, bv = b, share
    if best is None:
        return None
    # ── کندلِ ساعتی کلیدِ "d" **ندارد** ───────────────────────────
    # `ticks_to_h1()` فقط h/l/c/v می‌سازد. باکسِ هفتگی در مسیرِ زنده
    # از همان کندل‌های ساعتی ساخته می‌شود، پس `best["d"]` آنجا
    # KeyError می‌دهد و **کلِ جهانِ صندوق** می‌خوابد.
    #
    # این باگ در کانتینرِ من هرگز فعال نشد چون شبکه بسته است و مسیرِ
    # ریزمعاملات اجرا نمی‌شود — فقط روی ماشینِ مصطفی با دادهٔ زنده
    # درآمد. نوشتنِ `hasattr(best["d"], …)` نوعِ کلید را چک می‌کرد
    # ولی **بودنش** را نه.
    d = best.get("d")
    return {"low": best["l"], "close": best["c"], "high": best["h"],
            "date": (d.isoformat() if hasattr(d, "isoformat")
                     else str(d) if d is not None else "—")}


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


# ── خلای حجمِ عمودی — استراتژیِ دومِ مصطفی ──────────────────────────
# «هرگاه یک کندل حجمش از دو کندلِ کنارش کمتر باشد، آن می‌رود توی باکس.
# بالای آن کلوز داد → روند شروع شده. زیرش کلوز داد → می‌فروشیم.»
#
# این با باکسِ POC فرق دارد: آنجا حجمِ **افقی** (پروفایل روی قیمت)،
# اینجا حجمِ **عمودی** (میلهٔ حجمِ هر کندل).
#
# اندازه‌گیری روی ۲٬۸۵۷ مشاهدهٔ هفتگی، ۱۱۲ نماد:
#
#   POC      خلا      n     میانگین   مزیت
#   بالا     بالا    ۸۵۱     +۳٫۴۱٪   +۱٫۱۵
#   بالا     زیر      ۵۰     +۱٫۸۱٪   +۰٫۰۹   ← وتو، t=۲٫۱۴
#   داخل     بالا    ۷۶۹     +۲٫۹۹٪   +۰٫۶۳   ← اینجا طلاست
#   داخل     زیر     ۳۸۷     +۰٫۴۴٪   −۱٫۹۹
#
# سه نتیجه، و فقط یکی‌شان به درد می‌خورد:
#
# ❌ به‌عنوان **تأییدیه** روی سیگنالِ موجود: هیچ. POC بالا به‌تنهایی
#    +۳٫۴۸٪ می‌دهد، با تأییدِ خلا +۳٫۴۱٪. تفاوتی نیست.
# ⚠️ به‌عنوان **وتو**: واقعی ولی نازک — n=۵۰.
# ✅ به‌عنوان **سیگنالِ مستقل آنجا که POC ساکت است**: قوی.
#    وقتی POC «داخل» است، خلای حجمی جهت را می‌گوید: +۲٫۹۹٪ در برابر
#    +۰٫۴۴٪، اختلاف +۲٫۵۵ واحد با t=+۶٫۵۵ روی n=۷۶۹ و ۳۸۷.
#
# و این ۴۰٪ مواردی است که سیستمِ فعلی هیچ حرفی ندارد.
def poc_band_box(bars):
    """باکسِ POC، مستقل از BOX_KIND.

    `make_box` پیش‌فرضش ردیفِ دره است (انتخابِ مصطفی). ولی آزمونِ
    بازگشتِ درون‌هفته اندازه‌گیری‌شده فقط با باکسِ **پهن** کار می‌کند،
    چون چیزی که می‌سنجد شکستِ ناحیه است نه محلِ استاپ. پس این تابع
    همیشه POC می‌دهد.
    """
    global BOX_KIND
    old = BOX_KIND
    BOX_KIND = "poc"
    try:
        return make_box(bars)
    finally:
        BOX_KIND = old


VGAP_MAX_DIST = 25.0
# همان قرارداد برای سطحِ واکنش: سطحی که ۲۵٪ دورتر است
# جوابِ «کجا واکنش می‌دهد؟» نیست، یک عددِ تاریخی است.
REACT_MAX_DIST = 25.0


def vgap_levels(rows, px):
    """حمایت/مقاومتِ خلای حجمی در سه تایم‌فریم.

    مصطفی روی دوایکس گرفتش: «یک باکس در حجم عمودی تشکیل شده، به بالا
    شکسته، و الان در حالِ پولبک زدن به باکس است. این می‌تواند به ما
    قطعیت بدهد که چند درصد پایین‌تر یک حمایتِ قوی وجود دارد.»

    برای هر تایم‌فریم، آخرین خلای حجمی و فاصلهٔ درصدیِ قیمت تا آن:
      قیمت بالای باکس → سقفِ باکس **حمایت** است، فاصله مثبت
      قیمت داخلِ باکس → در حالِ پولبک، همان‌جاست
      قیمت زیرِ باکس  → کفِ باکس **مقاومت** است، فاصله منفی
    """
    out = {}
    for tf, fa in (("d", "دیلی"), ("w", "هفتگی"), ("m", "ماهانه")):
        if tf == "d":
            bars = rows
        else:
            b = OrderedDict()
            for r in rows:
                d = r["d"]
                k = ((d.year, d.month) if tf == "m" else week_key(d))
                e = b.get(k)
                if e is None:
                    b[k] = {"h": r["h"], "l": r["l"],
                            "c": r["c"], "v": r["v"]}
                else:
                    e["h"] = max(e["h"], r["h"])
                    e["l"] = min(e["l"], r["l"])
                    e["c"] = r["c"]
                    e["v"] += r["v"]
            # دورهٔ **جاری** ناقص است: حجمش هنوز کامل نشده و سقف/کفش
            # می‌تواند تا آخرِ هفته جابه‌جا شود. باکسِ POC هم (بند ۲
            # CLAUDE.md) فقط از دورهٔ کامل‌شده ساخته می‌شود؛ اینجا هم
            # همان. سطلِ آخر را می‌اندازیم.
            bars = list(b.values())[:-1]
        g = None
        for i in range(1, len(bars) - 1):
            if (bars[i]["v"] < bars[i - 1]["v"]
                    and bars[i]["v"] < bars[i + 1]["v"]):
                g = i
        if g is None:
            continue
        lo, hi = bars[g]["l"], bars[g]["h"]
        st = "بالا" if px > hi else "زیر" if px < lo else "داخل"
        dist = ((px / hi - 1) * 100 if st == "بالا"
                else (px / lo - 1) * 100 if st == "زیر" else 0.0)
        # ── چندمین بار است که قیمت به این ناحیه برمی‌گردد ──────────
        # اندازه‌گیری شد (docs/25): لمسِ دوم و بعد از آن بدتر است —
        # روی طلا +۰٫۵۰ واحد (t=۲٫۰۱) و روی بقیهٔ بازار +۰٫۴۸ واحد
        # (t=۳٫۲۶) به نفعِ بارِ اول. سازوکارش هم ساده است: باکس با
        # کلوزِ زیرِ کفش می‌میرد، پس لمسِ مکرر یعنی قیمت دارد همان‌جا
        # می‌چرخد — و چرخش بازدهِ کمتری دارد.
        touch = 0
        for j in range(g + 2, len(bars)):
            if bars[j]["l"] <= hi:
                touch += 1
            if bars[j]["c"] < lo:
                break
        # حمایتی که ۹۷٪ پایین‌تر است حمایت نیست. سؤالِ مصطفی «چند درصد
        # پایین‌تر حمایت هست» بود؛ عددِ بزرگ جوابِ آن سؤال نیست، فقط
        # جدول را شلوغ می‌کند. از VGAP_MAX_DIST بیشتر → نشان نده.
        if abs(dist) > VGAP_MAX_DIST:
            continue
        out[fa] = {"lo": lo, "hi": hi, "st": st, "dist": dist,
                   "touch": touch}
    return out


# ── حکمِ خلای حجمی — قاعدهٔ اصلیِ مصطفی ─────────────────────────────
# «مبنای اصلیِ این استراتژی کندلِ **هفتگی** هست و **ماهانه**… هرگاه
#  ناحیهٔ خلا حجمی شکل گرفت، هرگاه کلوزِ روزِ بعد بالا یا پایینِ
#  ناحیه بود، مبنای تصمیم‌گیریِ ما خواهد بود.»
#
# کدی که تا امروز اجرا می‌شد **هیچ‌کدامِ این دو را نداشت**:
# `vgap_state()` روی سریِ **دیلی** بسته می‌شد و کلوزِ **امروز** را
# می‌سنجید. فرقش روی موج (کلوزِ ۲۰۲۶-۰۹-۲۰):
#
#     دیلی، کلوزِ امروز   ناحیه ۹۰٬۵۱۱–۹۴٬۱۳۱ → زیر     ← کدِ قبلی
#     هفتگی، روزِ تصمیم   ناحیه ۶۹٬۵۳۸–۸۴٬۶۴۱ → **بالا** ← درست
#
# یعنی همان نمادی که او «شکستِ ناحیه» می‌دید، کد «زیر» می‌خواند و
# سیگنالش را یک پله پایین می‌آورد.
#
# ## دو چیزی که اندازه‌گیری به قاعده اضافه کرد
#
# (`tools/vgap_decide.py`، ۱۱۹ نماد، ۳٬۷۲۵ هفته، نرخ پایه +۱٫۹۱٪)
#
# ۱. **حکم باید هر دوره دوباره خوانده شود، نه یک‌بار و برای همیشه.**
#    اگر حکم را روی کلوزِ همان یک کندلِ بعدِ ناحیه قفل کنیم و تا
#    ناحیهٔ بعدی نگه داریم، **برعکس** می‌شود: «زیر» مزیتِ +۰٫۷۷ با
#    p=۰٫۰۰۵۲ می‌دهد. علتش کهنگی است — حکمِ چند هفته پیش دربارهٔ
#    امروز حرفی ندارد. پس حکم روی **کلوزِ روزِ تصمیمِ همین دوره** در
#    برابرِ **آخرین ناحیهٔ تأییدشده** خوانده می‌شود.
# ۲. **ناحیهٔ دور تصمیم نیست.** میانهٔ فاصلهٔ ناحیهٔ ماهانه تا قیمت
#    ۲۷٪ است (بیشینه ۱۵۵٪). ناحیه‌ای که ۲۷٪ پایین‌تر است همه را
#    «بالا» نشان می‌دهد و هیچ تفکیکی نمی‌کند. با قیدِ فاصله جهت
#    درست می‌شود:
#
#      ناحیهٔ هفتگی تا ۱۰٪ دور   بالا ۶۹٫۴٪ مثبت · زیر ۵۰٫۸٪
#      بدونِ قیدِ فاصله          بالا ۶۵٫۴٪ مثبت · زیر ۵۱٫۰٪
VGAP_NEAR = 10.0          # ناحیهٔ دورتر از این، حکم نمی‌دهد


def _tf_bars(rows, tf):
    """کندل‌های تجمیع‌شده به تایم‌فریم، با اولین کلوزِ هر دوره."""
    if tf == "d":
        return [{**r, "k": r["d"], "first": r["c"]} for r in rows]
    b = OrderedDict()
    for r in rows:
        d = r["d"]
        k = (d.year, d.month) if tf == "m" else week_key(d)
        e = b.get(k)
        if e is None:
            b[k] = {"d": d, "k": k, "h": r["h"], "l": r["l"],
                    "c": r["c"], "v": r["v"], "first": r["c"]}
        else:
            e["h"] = max(e["h"], r["h"])
            e["l"] = min(e["l"], r["l"])
            e["c"] = r["c"]
            e["v"] += r["v"]
            e["d"] = d
    return list(b.values())


def vgap_verdict(rows, tf, near=None):
    """حکمِ خلای حجمی در یک تایم‌فریم، به قاعدهٔ مصطفی.

    خروجی: lo، hi، verdict (بالا/داخل/زیر)، dec (کلوزی که حکم را
    ساخت)، dec_d (تاریخش)، broke (بعدش کلوزی کاملاً زیرِ ناحیه
    داده؟)، dist، age (چند دوره از ناحیه گذشته).

    **بدونِ لوک‌اهد:** ناحیهٔ `g` فقط وقتی تأیید می‌شود که دورهٔ
    `g+1` بسته شده باشد (چون دره بودن به حجمِ `g+1` بند است). پس در
    دورهٔ `i` فقط ناحیه‌هایی به کار می‌آیند که `g + 1 < i`.
    """
    nr = VGAP_NEAR if near is None else near
    bars = _tf_bars(rows, tf)
    if len(bars) < 4:
        return None
    i = len(bars) - 1                    # دورهٔ جاری
    z = None
    for j in range(1, len(bars) - 1):
        if (bars[j]["v"] < bars[j - 1]["v"]
                and bars[j]["v"] < bars[j + 1]["v"] and j + 1 < i):
            z = j
    if z is None:
        return None
    lo, hi = bars[z]["l"], bars[z]["h"]
    if lo <= 0 or hi <= 0:
        return None
    # ── کلوزِ روزِ تصمیم ──────────────────────────────────────────
    # «کلوزِ روزِ بعد» یعنی اولین کلوزِ دورهٔ جاری — همان چیزی که
    # DECIDE_FUND برای باکسِ POC اندازه‌گیری کرده بود (یکشنبه،
    # ‎+۰٫۳۸۸ با p=۰٫۰۰۰۳). با --now کلوزِ امروز می‌شود.
    dec = bars[i]["c"] if LIVE_STATE else bars[i]["first"]
    v = "بالا" if dec > hi else "زیر" if dec < lo else "داخل"
    dist = ((dec / hi - 1) * 100 if v == "بالا"
            else (dec / lo - 1) * 100 if v == "زیر" else 0.0)
    if abs(dist) > nr:
        v = "دور"                        # ناحیه هست ولی تصمیم نیست
    # حد ضررِ خودِ او: «یک کندلِ دیلی پایینِ ناحیه کاملاً کلوز بدهد»
    broke = any(r["c"] < lo for r in rows if r["d"] > bars[z + 1]["d"])
    return {"lo": lo, "hi": hi, "verdict": v, "dec": dec,
            "dec_d": bars[i]["d"].isoformat(), "broke": broke,
            "dist": dist, "age": i - z, "zone_d": bars[z]["d"].isoformat()}


def vgap_all(rows):
    """حکمِ هر سه تایم‌فریم + حکمِ نهایی.

    **هفتگی مبناست، ماهانه تأییدکننده، دیلی فقط خبر.** خودِ او:
    «مبنای اصلیِ این استراتژی کندلِ هفتگی هست و ماهانه.»
    """
    out = {}
    for tf, fa in (("m", "ماهانه"), ("w", "هفتگی"), ("d", "دیلی")):
        v = vgap_verdict(rows, tf)
        if v:
            out[fa] = v
    w = (out.get("هفتگی") or {}).get("verdict")
    m = (out.get("ماهانه") or {}).get("verdict")
    if w in ("بالا", "زیر"):
        final = w
    elif w == "داخل":
        final = "داخل"
    elif m in ("بالا", "زیر"):
        final = m                        # هفتگی حکم ندارد → ماهانه
    else:
        final = "؟"
    out["حکم"] = final
    out["مبنا"] = ("هفتگی" if w in ("بالا", "زیر", "داخل")
                   else "ماهانه" if m in ("بالا", "زیر") else "—")
    return out


def vgap_state(rows, px):
    """وضعیتِ کلوز نسبت به آخرین خلای حجمیِ تأییدشده."""
    g = None
    for i in range(1, len(rows) - 1):
        if (rows[i]["v"] < rows[i - 1]["v"]
                and rows[i]["v"] < rows[i + 1]["v"]):
            g = i
    if g is None or g + 1 >= len(rows) - 1:
        return "؟"
    lo, hi = rows[g]["l"], rows[g]["h"]
    return "بالا" if px > hi else "زیر" if px < lo else "داخل"


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
    (5, "شنبه", "هفتهٔ بورس بسته می‌شود",
     "باکس قفل شد — فردا تکلیف روشن می‌شود"),
    (6, "یکشنبه", "🔔 سیگنالِ نمادهای بورسی",
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
    # ── کلوزِ **روزِ تصمیم**، نه آخرین کلوز ────────────────────────
    # مصطفی، چند بار: «گفتیم روز بعدش مهمه — کلوزِ یکشنبه. نه آن روزی
    # که باکس تشکیل می‌شود. ما کلوزِ روزِ تصمیم برایمان مهم است.»
    #
    # و روی سینرژی گرفتش. باکسِ هفتگی ۶۴٬۷۱۹–۶۷٬۳۲۰ بود:
    #   کلوزِ یکشنبه ۲۰ سپتامبر  ۶۶٬۹۲۶ → داخلِ باکس  → سیگنال
    #   کلوزِ سه‌شنبه ۲۲ سپتامبر ۶۴٬۵۵۴ → زیرِ باکس   → حذف
    # یعنی اجرای سه‌شنبه سیگنالی را که یکشنبه صادر شده بود گم می‌کرد.
    #
    # `DECIDE_FUND` اندازه‌گیری شده (+۰٫۶۵۲ واحد، p=۰٫۰۰۰۳) و ثبت شده
    # بود، ولی فقط در **تقویمِ نمایشی** استفاده می‌شد — محاسبه همچنان
    # روی `rows[-1]` بود. این همان باگ است.
    #
    # روزِ تصمیم = **اولین جلسهٔ دورهٔ جاری**. برای هفته یکشنبه است
    # (week_key لنگرِ یکشنبه دارد)، برای ماه اولین روزِ معاملاتیِ ماه.
    # اگر آن روز تعطیل بود، اولین جلسه‌ای که باز بوده.
    dec_w = by_w[ws[-1]][0]["c"] if by_w[ws[-1]] else px
    dec_m = by_m[ms[-1]][0]["c"] if by_m[ms[-1]] else px
    dec_wd = by_w[ws[-1]][0]["d"] if by_w[ws[-1]] else rows[-1]["d"]
    dec_md = by_m[ms[-1]][0]["d"] if by_m[ms[-1]] else rows[-1]["d"]
    if LIVE_STATE:                       # با --now به رفتارِ قبلی برگرد
        dec_w = dec_m = px
        dec_wd = dec_md = rows[-1]["d"]
    base.update({"dec_w": dec_w, "dec_m": dec_m,
                 "dec_wd": dec_wd.isoformat(), "dec_md": dec_md.isoformat()})
    vols = sorted(b["v"] for b in rows[-20:])
    mv = vols[len(vols) // 2] if vols else 0
    base.update({"med_vol": mv, "value_bn": mv * px / 1e9,
                 "wbars": len(by_w[ws[-2]]), "mbars": len(by_m[ms[-2]])})
    mb = make_box(by_m[ms[-2]])
    fb = []                                  # کدام باکس با جایگزین ساخته شد
    # ── باکسِ هفتگی: **اول ساعتی، بعد روزانه** ─────────────────────
    # بند ۱ راهنما: «پروفایل روی تایم‌فریمِ پایین‌تر از دورهٔ باکس —
    # باکسِ هفتگی با H1.» و بند ۴ بین‌بندی روی کندلِ روزانه را جزوِ دو
    # اشتباهِ قبلی ثبت کرده که تصحیحش مزیت را از +۰٫۰۵۹ به +۰٫۳۶۲ برد.
    #
    # قبلاً ساعتی فقط **جایگزین** بود: اگر روزانه دره پیدا نمی‌کرد.
    # یعنی در ۶۰٪ نمادها همچنان روزانه بین‌بندی می‌شد — همان اشتباهِ
    # بند ۴، فقط کم‌رنگ‌تر.
    #
    # مصطفی روی عیار گرفتش: او در ۵ ردیف دره دید، کد تا ۹ ردیف رفت.
    # علتش همین است — با ۵ کندلِ روزانه پروفایل درشت است:
    #     ۵ ردیف روزانه: [19 23 31 15 12]  ← دره‌ای نیست
    # با ~۱۲۰ کندلِ ساعتی پروفایل ریز است و دره زود ظاهر می‌شود.
    wb = None
    wbars_used = by_w[ws[-2]]
    if allow_ticks and ins:
        wdays = sorted({b["d"] for b in by_w[ws[-2]]})
        h1 = []
        for d in wdays:
            h1.extend(get_h1(sym, ins, d, quiet=True))
        if len(h1) >= 8:
            wb = make_box(h1)
            if wb is not None:
                base["h1bars"] = len(h1)
                # کندلِ سازندهٔ ناحیه هم از همان پروفایلی می‌آید که
                # باکس از آن ساخته شد — وگرنه دو چیزِ ناهم‌خوان.
                wbars_used = h1
    if wb is None:
        wb = make_box(by_w[ws[-2]])
        if wb is not None and allow_ticks:
            # ساعتی در دسترس بود ولی نشد — باید دیده شود، نه بی‌صدا
            fb.append("هفتگی←روزانه")
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
    # ── بازگشتِ درون‌هفته ──────────────────────────────────────────
    # مصطفی: «اگر بورس در هفته پایینِ ناحیه کلوز داده و ناحیه را در
    # طیِ هفته به بالا بشکند، باید سیگنالِ خرید صادر کنیم.»
    #
    # اندازه‌گیری شد (`tools/midweek.py`، ۱۱۲ نماد، ۴۵ هفته) و جوابش
    # **به تعریفِ باکس وابسته است**:
    #
    #   باکس        بازگشت در برابرِ «بدونِ بازگشت»
    #   ردیفِ دره    −۰٫۵۸ واحد · t=−۱٫۳۳   ← هیچ
    #   باکسِ POC    +۱٫۴۳ واحد · t=+۳٫۹۳   ← واقعی
    #
    # سازوکارش روشن است: ردیفِ دره میانهٔ ۱٫۴٪ پهناست، پس «کلوز بالای
    # آن» تکانِ بی‌معناست؛ باکسِ POC ~۹٪ پهناست و عبور از سقفش شکستِ
    # واقعی است. پس این آزمون **همیشه با باکسِ POC** انجام می‌شود،
    # مستقل از BOX_KIND — چون چیزی که می‌سنجد شکستِ ناحیه است، نه
    # محلِ استاپ.
    #
    # و دو کلوزِ پشتِ هم لازم است (t از ۳٫۲۱ به ۳٫۹۳ و نرخِ مثبت از
    # ۶۷٪ به ۷۳٪ می‌رود).
    #
    # ⚠️ ولی از سیگنالِ اصلی **ضعیف‌تر** است (−۰٫۹۷ واحد، t=−۲٫۹۲) و
    # تا افقِ ۲۰ روز محو می‌شود. پس **نیمه‌سیگنال** است نه سیگنالِ
    # کامل — همان پله‌ای که برای «نیمهٔ بالای باکس» هم داریم.
    midweek = False
    cw = by_w[ws[-1]]
    if len(cw) >= 3:
        pb = poc_band_box(by_w[ws[-2]])
        # گیت هم با **همان** باکس سنجیده می‌شود. اگر «بالا بود؟» را با
        # ردیفِ دره بپرسیم و «عبور کرد؟» را با POC، دو ناحیهٔ متفاوت
        # مقایسه شده‌اند و جواب بی‌معناست.
        if pb is not None and state(dec_w, pb) != "بالا":
            run = 0
            for b in cw[1:]:
                run = run + 1 if b["c"] > pb[1] else 0
                if run >= 2:
                    midweek = True
                    break
    base["midweek"] = midweek

    # ── سیگنالی که استاپش **از قبل خورده** مرده است ────────────────
    # این عیبِ مستقیمِ اصلاحِ «روزِ تصمیم» بود و مصطفی روی دفترِ سهام
    # گرفتش: وبملت کلوز ۱٬۴۴۴ با استاپِ ۱٬۵۵۶، شپنا ۱۲٬۴۰۰ با استاپِ
    # ۱۳٬۸۲۵، فملی ۲۴٬۳۱۰ با استاپِ ۲۶٬۳۱۰ — هر سه در دفترِ پیشنهادی،
    # هر سه با قیمتی که همین حالا زیرِ حدضررشان است.
    #
    # علتش: وضعیت درست روی کلوزِ یکشنبه حساب می‌شد، ولی هیچ‌جا چک
    # نمی‌شد که از یکشنبه تا امروز قیمت از کفِ باکس رد شده یا نه.
    # سیگنال روی کاغذ زنده می‌ماند در حالی که در عمل مرده است.
    #
    # قاعده: **کفِ باکس همان استاپ است.** اگر کلوزِ امروز زیرِ آن است،
    # آن سیگنال دیگر قابلِ اجرا نیست، هر چه کلوزِ روزِ تصمیم گفته باشد.
    #
    # ⚠️ «زیرِ استاپ» با «داخلِ باکس» فرق دارد و این تفکیک لازم است،
    # وگرنه سینرژی دوباره حذف می‌شود: کلوزش ۶۴٬۵۵۴ بود و کفِ باکس
    # ۶۳٬۸۵۲ — داخلِ باکس، پولبک، نه استاپ‌خورده.
    # ⚠️ «زیرِ باکس» با «استاپ‌خورده» یکی نیست و قاطی کردنشان نصفِ
    # جهان را بی‌خود علامت‌دار می‌کرد. نمادی که در روزِ تصمیم هم زیرِ
    # باکس بوده اصلاً سیگنال نداده — وضعیتش در ستونِ «هفتگی» پیداست.
    # مرده آن است که در روزِ تصمیم **سیگنال داده** و از آن موقع تا
    # امروز از کفِ باکس رد شده.
    w_dead = state(dec_w, wb) != "زیر" and px < wb[0]
    m_dead = state(px, mb) != "زیر" and px < mb[0]
    return {**base, "ok": True, "reason": "",
            "w_dead": w_dead, "m_dead": m_dead,
            "flags": flag_targets(rows, px),
            "w4": state4(dec_w, wb), "m4": state4(px, mb),
            # حکمِ خلای حجمی به قاعدهٔ خودش: **هفتگی مبنا، ماهانه
            # تأییدکننده**، روی کلوزِ روزِ تصمیم. `vgap` قدیمی که
            # روی سریِ دیلی و کلوزِ امروز بسته می‌شد فقط برای
            # سازگاریِ نمایش مانده و دیگر **تصمیم نمی‌گیرد**.
            "vg": vgap_all(rows),
            "vgv": vgap_all(rows)["حکم"],
            "vgap": vgap_state(rows, px),
            "vlev": vgap_levels(rows, px),
            "hist": {b["d"]: b["c"] for b in rows[-140:]},
            # فقط **هفتگی** روی کلوزِ روزِ تصمیم است. دو تای دیگر نه:
            #  · باکسِ ماهِ جاری اگر با کلوزِ اولِ ماه سنجیده شود بی‌معنی
            #    است — آن باکس هنوز تقریباً خالی است. کارش دیدنِ مقاومتی
            #    است که **از اول ماه تا حالا** ساخته شده.
            #  · وضعیتِ ماهانه هم تا آخرِ ماه تصمیمی ندارد (بند ۲: «فقط
            #    پایان ماه»)، و فریز کردنش یعنی سه هفته عددِ کهنه.
            # اندازه‌گیریِ `decision_day.py` هم فقط دربارهٔ هفته بود.
            "mst": state(px, mb), "wst": state(dec_w, wb),
            "cur_box": cur, "cur_st": state(px, cur) if cur else "؟",
            "cur4": state4(px, cur) if cur else "؟",
            "month": zone(mb, px, BAND["month"]),
            "week": zone(wb, px, BAND["week"]),
            # سطحِ واکنش — کندلی که ناحیه را ساخته. افقِ هفتگی روی
            # **کلوز** و ماهانه روی **سقفِ** آن کندل اندازه‌گیری شد.
            "react_w": zone_candle(wbars_used, wb),
            "react_m": zone_candle(by_m[ms[-2]], mb)}


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
    # تا داشبورد هم بتواند بگوید «دسته‌اش منفی است»، بدونِ بازسازیِ
    # همین محاسبه در جای دوم.
    for r in rows:
        r["cat_wide"] = r["cat"] in wide

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
        # ── از کهربا عقب است → سیگنال نکن ─────────────────────────
        # قاعدهٔ خودِ مصطفی. پنجره اندازه‌گیری شد نه حدس (بالای فایل).
        if BENCH_FILTER and r.get("bx") is not None and r["bx"] < 0:
            return 0
        # استاپِ هر دو افق خورده → اصلاً قابلِ اجرا نیست
        if r.get("w_dead") and r.get("m_dead"):
            return 0
        if r["wst"] == "بالا":
            # وتوی خلای حجمی: بالای باکسِ POC ولی زیرِ خلای حجمی،
            # مزیتش از +۱٫۱۵ به +۰٫۰۹ می‌افتد (t=۲٫۱۴). نازک است
            # (n=۵۰) پس فقط از پلهٔ ۱ به ۲ می‌بردش، نه حذفِ کامل.
            #
            # ⚠️ این وتو تا امروز از سریِ **دیلی** و کلوزِ **امروز**
            # می‌آمد. مصطفی روی موج گرفتش: «موج درسته قیمت زیرِ خلا
            # حجمی کلوز داده اما امروز ناحیهٔ حجمیِ خودش را شکسته.»
            # حق داشت — دیلیِ موج «زیر» بود و هفتگی‌اش «بالا»، و
            # مبنای اعلام‌شدهٔ خودش هفتگی است. حالا از `vgv` می‌آید.
            return 2 if r.get("vgv") == "زیر" else 1
        if r["w4"] == "نیمهٔ بالا":
            return 2
        # POC ساکت است ولی خلای حجمی بالاست → نیمه‌سیگنال.
        # +۲٫۹۹٪ در برابر +۰٫۴۴٪، t=+۶٫۵۵ روی n=۷۶۹.
        if r["wst"] == "داخل" and r.get("vgv") == "بالا":
            return 2
        # و حکمِ خلای حجمی به‌تنهایی هم نیمه‌سیگنال است، حتی اگر
        # باکسِ POC ساکت باشد. قاعدهٔ اعلام‌شدهٔ خودِ اوست و
        # اندازه‌گیری هم جهتش را تأیید می‌کند: ناحیهٔ هفتگیِ تا ۱۰٪
        # دور، «بالا» ۶۹٫۴٪ مثبت در برابرِ «زیر» ۵۰٫۸٪ (n=۱٬۱۸۴ و
        # ۵۵۷، نرخ پایه ۶۳٫۳٪). مزیتِ میانگین نازک است (+۰٫۱۶ واحد)
        # پس پلهٔ ۲ می‌گیرد نه ۱.
        if r.get("vgv") == "بالا" and r["wst"] != "زیر":
            return 2
        # بازگشتِ درون‌هفته — نیمه‌سیگنال، طبقِ اندازه‌گیری
        if r.get("midweek"):
            return 2
        return 0

    for r in rows:
        r["tier"] = tier(r)
    elig = [r for r in rows if r["tier"] == 1]
    half = [r for r in rows if r["tier"] == 2]
    # از هر دسته بزرگ‌ترین. اگر دسته‌ای سیگنالِ کامل نداشت،
    # نیمه‌سیگنالش می‌آید — با **نصفِ وزن**، چون مزیتش هم حدودِ
    # یک‌سومِ سیگنالِ کامل است.
    # ── انتخاب: N نمادِ برتر بر اساسِ مازادِ کهربا ──────────────────
    # قاعدهٔ قبلی «بزرگ‌ترینِ هر دسته» بود، با استدلالِ تنوع. اندازه‌گیری
    # شد (`tools/vs_bench.py`، ۳۵ هفته، معیارِ **واحدِ کهربا**):
    #
    #   مازادِ کهربا، بدونِ قید        ۱٫۱۵۲
    #   حداکثر ۲ از هر دسته           ۱٫۱۰۵
    #   حداکثر ۱ از هر دسته           ۱٫۰۱۳
    #   بزرگ‌ترینِ دسته (قاعدهٔ قبلی)  ۰٫۸۷۳   ← از کهربا **می‌بازد**
    #
    # هر قیدِ تنوع ضرر می‌دهد، و قاعدهٔ قبلی ۲۸ واحد عقب‌تر از رتبه‌بندیِ
    # مازاد است. کفِ نقدشوندگی (MIN_VALUE_BN) جای آن قید را می‌گیرد.
    #
    # و آزمونِ نیمه‌به‌نیمه: فقط N=۶ و N=۸ در **هر دو** نیمهٔ پنجره از
    # کهربا جلو زدند. چینش‌های متمرکز (۱ تا ۴) در نیمهٔ اول باختند —
    # یعنی بردشان از یک پنجرهٔ خوش‌شانس بود.
    #
    # ── و محورِ دومِ اولویت: محرکِ جهانیِ خودِ نماد ──────────────────
    # مصطفی: «بازارهای جهانی تأثیرپذیرش را مدّ نظر قرار بده، و
    # همچنین میزان بازدهی که به طور میانگین داشته‌اند اولویت باشد.»
    # اندازه‌گیری شد (`tools/driver_rank.py`, `docs/33`). امتیاز
    # می‌شود «مازادِ کهربا + پاسخِ محرک» — و **نه** دروازه:
    #
    #   مازاد به‌تنهایی        ۱٫۱۵۲   صدکِ ۹۸ از ترتیبِ تصادفی
    #   مازاد + پاسخِ محرک     ۱٫۱۹۱   صدکِ ۹۹٫۵
    #   حذفِ محرکِ منفی        ۱٫۰۶۴   ← حذف در هر شکلی ضرر داد
    #
    # و در **هر ۱۲** ترکیبِ (N، سقفِ وزن) که جارو شد، و در هر دو
    # نیمهٔ پنجره، نسخهٔ با محرک جلو بود. یک سلولِ خوش‌شانس نیست.
    pool = elig + [r for r in half if r not in elig]
    pool.sort(key=lambda r: (-(pick_score(r) if pick_score(r) is not None
                               else -1e9), -r["value_bn"]))
    picks = pool[:MAX_PICKS]

    # ── نمادی که **داری** و حکمش هنوز «بالا»ست، فروخته نمی‌شود ─────
    # مصطفی روی نهال گرفتش: «چرا برای نهال سیگنال خروج صادر کردی؟
    # امروز که روزِ تعیین‌کنندهٔ آن نماد است بالای ناحیهٔ حجمی کلوز
    # داده.» حق داشت، و ریشه‌اش جای دیگری بود: نهال **استاپ نخورده
    # بود** — بالای هر دو باکس و بالای هر سه ناحیهٔ خلای حجمی. در
    # فهرستِ فروش آمده بود چون رتبه‌بندی پنج نمادِ دیگر را جلوترش
    # گذاشته بود و چرخش هرچه بیرونِ شش‌تای اول باشد را می‌فروشد.
    #
    # این خلافِ قاعدهٔ اعلام‌شدهٔ خودش است: «ما فقط در صورتی
    # می‌فروشیم که زیرِ باکس بسته شود.» پس قاعدهٔ خروج بر
    # رتبه‌بندی **مقدم** است — نمادی که داری و حکمش «بالا»ست و
    # شکسته نشده، در دفتر می‌ماند حتی اگر رتبه‌اش هفتم باشد.
    #
    # هزینه‌اش هم روشن است و پنهان نمی‌شود: دفتر می‌تواند از
    # MAX_PICKS بیشتر شود، پس وزنِ هر قلم کمتر می‌شود. در ازایش
    # گردش — که ۱۹۱٪ در روز بود — می‌افتد.
    # شرطِ نگه داشتن **شرطِ ورود نیست، شرطِ نبودِ خروج است.** این
    # تفکیک را نداشتن، ریشهٔ ایرادِ نهال بود: نهال بالای هر دو باکس و
    # بالای هر سه ناحیهٔ خلای حجمی بود، ولی `tier=0` گرفته بود چون
    # **فیلترِ کهربا** ۷٫۳ واحد عقب‌تر دیده بودش. آن فیلتر قاعدهٔ
    # **انتخاب** است («از بین نمادهایی که انتخاب کردی… اگر از بازدهیِ
    # کهربا پایین‌تر است سیگنال نکن») و هیچ‌وقت قرار نبود چیزی را
    # **بفروشد**. همین‌طور عیار (−۰٫۹) و سینرژی (−۰٫۷).
    def no_exit(r):
        vg = r.get("vg") or {}
        if vg.get("حکم") == "زیر":
            return False
        if (vg.get("هفتگی") or {}).get("broke"):
            return False
        if r["wst"] == "زیر" or r["mst"] == "زیر":
            return False
        if r.get("w_dead") and r.get("m_dead"):
            return False
        return True

    held = {norm(k) for k in (holdings_load()[0] or {})}
    if held:
        keep = [r for r in rows
                if norm(r["sym"]) in held
                and r not in picks
                and no_exit(r)]
        for r in keep:
            r["kept"] = True            # در جدول علامت می‌خورد
            if not r.get("tier"):
                r["tier"] = 2           # نگه‌داشتنی، با نصفِ وزن
        picks = picks + keep

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
    # ⚠️ ولی «نقد نماندن» یعنی **نگه داشتن**، نه **خریدن**. پیاده‌سازیِ
    # قبلی این دو را یکی گرفته بود و همهٔ ایرادهایی که مصطفی گرفت از
    # همین‌جا آمد: پرحجم‌ترین‌ها برداشته می‌شدند بدونِ هیچ چکِ وضعیت،
    # بعد برایشان نقطهٔ ورود و حدضرر نشان داده می‌شد انگار سیگنال‌اند.
    # فملی و وبملت و شپنا با کلوزِ زیرِ حدضرر، و پالایش که زیرِ باکسِ
    # ماهِ جاری بود، همه از این مسیر وارد می‌شدند.
    #
    # دو چیز عوض شد:
    #   ۱. انتخاب با **کیفیتِ وضعیت** است نه فقط حجم — بالای باکس
    #      بهتر از داخل، داخل بهتر از زیر؛ حجم فقط تساوی را می‌شکند.
    #   ۲. پرکننده در جدول و در آلارم **نگه‌دار** علامت می‌خورد و
    #      نقطهٔ ورود نشان نمی‌دهد. خریدنش پیشنهاد نمی‌شود.
    if not picks:
        def quality(r):
            rank = {"بالا": 0, "داخل": 1, "زیر": 2}
            return (rank.get(r["wst"], 3) + rank.get(r["mst"], 3),
                    -r["value_bn"])
        pool = [r for r in rows
                if r["value_bn"] >= MIN_VALUE_BN and not r.get("park")]
        pool.sort(key=quality)
        picks = pool[:4]
        for r in picks:
            r["tier"] = 3               # «پرکننده» — نگه‌دار، نه خرید
    if not picks:
        return elig, []
    # ── باقی‌ماندهٔ بودجه → **خودِ کهربا** ──────────────────────────
    # فیلترِ مبنا + سقفِ وزنِ هر نماد می‌تواند بیشترِ پول را نقد بگذارد،
    # که خلافِ قاعدهٔ اندازه‌گیری‌شدهٔ «هرگز نقد نشو» است.
    #
    # جوابِ درست از خودِ هدف می‌آید: معیار **تعدادِ واحدِ کهرباست**.
    # اگر هیچ نمادی بهتر از کهربا نیست، کهربا را نگه دار — آن‌وقت
    # دست‌کم هم‌پای مبنا می‌مانی. نقد ماندن یعنی عقب افتادن از آن.
    #
    # سقفِ MAX_WEIGHT روی این ردیف اعمال نمی‌شود: نگه داشتنِ مبنا
    # شرط‌بندیِ متمرکز نیست، حالتِ خنثی است.
    bench_fill = 0.0
    if not STOCK:
        u0 = sum(1.0 if r["tier"] in (1, 3) else 0.5 for r in picks)
        used = sum(min(MAX_WEIGHT, MAX_INVESTED / u0
                       * (1.0 if r["tier"] in (1, 3) else 0.5))
                   for r in picks) if u0 else 0.0
        rest = MAX_INVESTED - used
        if rest > 1.0:
            bench_fill = rest
            if not any(norm(r["sym"]) == norm(BENCH) for r in picks):
                br = next((r for r in rows
                           if norm(r["sym"]) == norm(BENCH)), None)
                if br is not None:
                    picks.append({**br, "tier": 4})
                else:
                    bench_fill = 0.0

    # نیمه‌سیگنال نصفِ وزن می‌گیرد — مزیتش هم حدودِ یک‌سوم است
    units = sum(1.0 if r["tier"] in (1, 3) else 0.5
                for r in picks if r["tier"] != 4)
    book = []
    for r in picks:
        w = (bench_fill if r["tier"] == 4 else
             min(MAX_WEIGHT, MAX_INVESTED / units
                 * (1.0 if r["tier"] in (1, 3) else 0.5)))
        # اگر خودِ مبنا سیگنالِ واقعی هم هست، باقی‌مانده رویش اضافه
        # می‌شود — نه یک ردیفِ دوم، که در جدول گیج‌کننده بود.
        if r["tier"] != 4 and norm(r["sym"]) == norm(BENCH):
            w += bench_fill
            bench_fill = 0.0
        # باندی که استاپش داخلِ نوسانِ یک روز نمی‌نشیند. باکسِ هفتگی
        # میانهٔ پهنایش ۱٫۴۲٪ است و دامنهٔ یک روز ۲٫۶۲٪، پس استاپِ
        # هفتگیِ زیر ۱٪ عملاً داخلِ نویز می‌نشیند و باندِ ماهانه
        # برداشته می‌شود.
        # ── و باندی که استاپش **از قبل نخورده** ───────────────────
        # بدونِ این، نمادی که افقِ هفتگی‌اش مرده ولی ماهانه‌اش زنده
        # است، باز هم با نوارِ هفتگی وارد دفتر می‌شد و استاپی نشان
        # می‌داد که قیمت از آن رد شده.
        live = [b for b in ("week", "month") if not r.get(f"{b[0]}_dead")]
        if not live:
            continue
        band = ("week" if ("week" in live
                           and r["week"]["risk_pct"] >= 1.0)
                else ("month" if "month" in live else "week"))
        z = r[band]
        amt = capital * w / 100
        # پرکننده: **نگه‌دار**، نه خرید. قیمتِ مرجعش کلوزِ امروز است
        # نه نقطهٔ ورود، چون ورودی در کار نیست.
        hold_only = r["tier"] in (3, 4)
        ref = r["close"] if hold_only else z["aim"]
        book.append({**r, "band": band, "z": z, "w": w,
                     "hold_only": hold_only,
                     "amt": amt, "units": amt / ref,
                     "loss": 0.0 if hold_only
                     else amt * z["risk_pct"] / 100})
    return elig, book


def positions(rows, units, px):
    """پوزیشن‌های فعلی — حد ضرر و حد سود، **هر روز آپدیت‌شده**.

    مصطفی: «حد ضرر و حد سودمان باید در پایانِ هر روز آپدیت بشود.
    حد ضرر می‌شود هرگاه یک کندلِ دیلی پایینِ ناحیه کاملاً کلوز بدهد،
    پس فردای آن روز فروشنده خواهیم بود.»

    سه چیز اندازه‌گیری شد (`tools/exitrule.py`، ۱۱۲ نماد):

    ۱. **خروج درست است.** زیرِ کفِ باکس بازدهِ ۵ روزِ بعد +۰٫۲۲٪ با
       ۵۰٪ مثبت، در برابر +۳٫۲۸٪ با ۷۳٪ بالای کف — اختلافِ ۳٫۰۶ واحد
       با t=−۲۲٫۳۶.
    ۲. **صبر کردن هزینه دارد.** خروج فردا ۰٫۱۹ واحد بدتر از امروز، و
       صبر برای پولبک ۰٫۳۰ واحد بدتر (۳٬۴۱۲ رویداد).
    ۳. ولی +۰٫۲۲٪ **منفی نیست**. یعنی خروج باید **چرخش** باشد نه نقد
       شدن — همان آلارمِ «عوض کن».

    پس هر دو سطح نشان داده می‌شود: کلوزِ امروز (بهترین از نظرِ عدد) و
    کفِ باکس (جایی که در عمل می‌شود فروخت، چون در صفِ فروش کلوز در
    دسترس نیست — بند ۸ راهنما).
    """
    out = []
    for r in rows:
        if not r.get("ok"):
            continue
        u = None
        for k, v in units.items():
            if norm(k) == norm(r["sym"]):
                u = v
                break
        if not u:
            continue
        c = px.get(norm(r["sym"])) or r["close"]
        wz, mz = r["week"], r["month"]
        # «کندلِ دیلی کاملاً زیرِ ناحیه» — دو تعریف، هر دو اندازه‌گیری
        # شدند و هر دو کار می‌کنند؛ کلوز حساس‌تر است (۳٬۴۱۲ رویداد در
        # برابر ۲٬۶۲۱) و مزیتش هم بیشتر.
        below = c < wz["stop"]
        out.append({
            "sym": r["sym"], "units": u, "px": c,
            "value": u * c,
            "zone_lo": wz["stop"], "zone_hi": wz["lo"],
            "wst": r["wst"], "mst": r["mst"],
            "below": below,
            "dist_stop": (c / wz["stop"] - 1) * 100 if wz["stop"] else 0,
            # ── دو اصلِ حد سود ────────────────────────────────────
            # مصطفی: «حد سود می‌بایست بر دو اصل فعال بشود.» و جای
            # دیگر: «مگر قرار نشد حد سود مصادف بشه با وقتی که باکسِ
            # هفتگی خلاف صادر بشه؟»
            #
            # اصلِ ۱ = شکستِ ناحیه. همان کفِ باکس، همان حد ضرر — برای
            #   پوزیشنی که در سود است، خروج روی شکستِ ناحیه سیو سود است.
            # اصلِ ۲ = تارگتِ میله و پرچم، اگر هنوز نخورده باشد.
            #
            # تارگتِ ۱:۱ عمداً اینجا نیست: از **نوارِ ورود** حساب
            # می‌شود و برای پوزیشنی که از نوار گذشته، عددی پشتِ سر
            # است. نشان دادنش گمراه‌کننده بود.
            "flag": next((f for f in (r.get("flags") or [])
                          if f["target"] > c), None),
            "bx": r.get("bx"),
        })
    out.sort(key=lambda x: -x["value"])
    return out


def risk_report(book, pos, capital, comp=None):
    """ریسک منیجر — **گزارش‌گر**، نه قیدگذار. و دلیلش اندازه‌گیری است.

    مصطفی: «ریسک منیجر هم اضافه می‌شود.»

    سه شکلِ استانداردِ ریسک منیجر سنجیده شد (۳۵ هفته، معیارِ واحدِ
    کهربا) و **هر سه ضرر دادند**:

      وزن‌دهی
        هم‌وزن                 ۱٫۱۵۲   (نیمه‌ها ۱٫۰۲۹ / ۱٫۱۲۸)
        وارونِ جذرِ ریسک        ۱٫۰۸۰   (۱٫۰۰۳ / ۱٫۰۸۶)
        وارونِ ریسک            ۱٫۰۳۴   (۰٫۹۸۹ / ۱٫۰۵۴)  ← نیمهٔ اول را می‌بازد

      سقفِ ریسکِ هر نماد
        زیرِ ۳٪  ۰٫۸۳۴ · زیرِ ۵٪  ۰٫۸۱۳ · زیرِ ۸٪  ۰٫۸۱۴ · بی‌قید ۱٫۱۵۲

      سقفِ ریسکِ کلِ سبد        واحد    بیشینه افت
        ۲٪                     ۰٫۹۶۴    −۱۶٫۹٪
        ۵٪                     ۱٫۰۴۵     −۹٫۵٪
        بی‌قید                 ۱٫۱۵۲     −۷٫۲٪   ← هم بهتر، هم کم‌افت‌تر

    آخری غیرشهودی است و علتش روشن: سقفِ ریسک پول را می‌برد روی کهربا،
    و خودِ کهربا در این پنجره افتِ بیشتری از سبدِ شش‌تایی داشت. یعنی
    «کم کردنِ ریسک» با این تعریف، ریسکِ واقعی را **زیاد** کرد.

    پس قیدی که اندازه‌گیری تأییدش نکرده تحمیل نمی‌شود. آن‌چه می‌ماند
    **دیدن** است: اگر همهٔ استاپ‌ها بخورند چقدر می‌بازی، کدام قلم
    سنگین‌ترین ریسک را دارد، و چقدر متمرکزی.

    با `--risk-cap N` می‌شود سقف گذاشت — ولی هزینه‌اش چاپ می‌شود.
    """
    out = {"lines": []}
    if book:
        tot = sum(r["w"] * r["z"]["risk_pct"] / 100 for r in book
                  if not r.get("hold_only"))
        out["port_risk"] = tot
        out["rial"] = capital * tot / 100
        worst = max((r for r in book if not r.get("hold_only")),
                    key=lambda r: r["w"] * r["z"]["risk_pct"], default=None)
        out["worst"] = worst
        cc = defaultdict(float)
        for r in book:
            cc[r["cat"]] += r["w"]
        out["conc"] = max(cc.items(), key=lambda kv: kv[1]) if cc else None
        out["cats"] = dict(cc)
    # افتِ واقعی از تاریخچهٔ قطب‌نما
    if comp and comp.get("hist"):
        vals = [float(x["port"]) for x in comp["hist"] if x.get("port")]
        peak, dd = 0.0, 0.0
        for v in vals:
            peak = max(peak, v)
            if peak:
                dd = min(dd, v / peak - 1)
        out["dd"] = dd * 100
        out["dd_n"] = len(vals)
    return out


def audit(rows, book):
    """بازرسِ دفتر — هر اجرا، قبل از اینکه چیزی نشان داده شود.

    مصطفی: «من دونه‌دونه اینا رو چک کنم؟ خودت نمی‌تونی تشخیص بدی؟»

    حق دارد. تا اینجا هر باگِ این دسته را **او** پیدا کرده بود: پالایش
    که زیرِ حمایتِ هفتگی بود و در جدول مثبت نشان داده می‌شد، فملی و
    وبملت و شپنا که کلوزشان زیرِ حدضررشان بود و در دفترِ پیشنهادی
    آمده بودند. هر بار یک مسیرِ تازه.

    پس به‌جای وصلهٔ موردی، **ثابت‌های دفتر** اینجا نوشته می‌شوند و هر
    اجرا سنجیده. هر ردیفی که نقضشان کند از دفتر بیرون می‌رود و با نام
    چاپ می‌شود — نه بی‌صدا، چون بی‌صدا بودن همان چیزی است که این همه
    وقت گرفت.

    خروجی: (دفترِ پاک‌شده، فهرستِ نقض‌ها)
    """
    bad = []
    clean = []
    for r in book:
        z, band = r["z"], r["band"]
        px = r["close"]
        why = []
        # پرکننده (tier 3) عمداً سیگنال نیست — قاعدهٔ «هرگز نقد نشو».
        # پس شرط‌های وضعیت درباره‌اش معنا ندارند و فقط باید مطمئن شد
        # که مثلِ سیگنال **نمایش داده نمی‌شود**.
        if r.get("tier") in (3, 4):
            if not r.get("hold_only"):
                bad.append((r["sym"],
                            ["پرکننده بدونِ علامتِ «نگه‌دار» — "
                             "مثلِ سیگنال نمایش داده می‌شود"]))
            else:
                clean.append(r)
            continue
        # ── ردیفِ «نگه‌داشته» فقط با شرطِ **خروج** سنجیده می‌شود ──
        # دو دسته ثابت اینجا قاطی بودند و ایرادِ نهال از همین آمد:
        #   · شرطِ **ورود**  — فیلترِ کهربا، فیلترِ ماهِ جاری، پهنای
        #     دسته، کفِ نقدشوندگی. این‌ها می‌گویند «نخر».
        #   · شرطِ **خروج**  — کلوزِ زیرِ ناحیه، استاپِ خورده، هندسهٔ
        #     خراب. این‌ها می‌گویند «بفروش».
        # نمادی که **داری** و هیچ شرطِ خروجی نخورده، با شرطِ ورود
        # فروخته نمی‌شود. نقران دقیقاً همین‌جا می‌افتاد: بالای هر دو
        # باکس، ناحیهٔ خلای حجمی سالم، ولی «ماهِ جاری زیر» بیرونش
        # می‌انداخت. مصطفی: «ما فقط در صورتی می‌فروشیم که زیرِ باکس
        # بسته شود.»
        kept = bool(r.get("kept"))
        # ۱. قیمت نباید زیرِ حدضرر باشد — استاپی که خورده استاپ نیست
        if px < z["stop"]:
            why.append(f"کلوز {px:,.0f} زیرِ حدضرر {z['stop']:,.0f}")
        # ۲. سیگنالِ همان باند نباید مرده باشد
        if r.get(band[0] + "_dead"):
            why.append(f"سیگنالِ {band} بعد از روزِ تصمیم مرده")
        # ۳. وضعیتِ باکس باید با حضور در دفتر بخواند
        if r["mst"] == "زیر" or (not kept and r["mst"] != "بالا"):
            why.append(f"ماهانه «{r['mst']}» است نه بالا")
        if r["wst"] == "زیر":
            why.append("هفتگی «زیر» است")
        # حکمِ خلای حجمی — قاعدهٔ اعلام‌شدهٔ خودش
        if (r.get("vg") or {}).get("حکم") == "زیر":
            why.append("حکمِ خلای حجمی «زیر» است")
        # ۴. هندسه باید سالم باشد
        if not (z["stop"] < z["aim"] < z["target"]):
            why.append(f"هندسهٔ خراب: استاپ {z['stop']:,.0f} · "
                       f"ورود {z['aim']:,.0f} · تارگت {z['target']:,.0f}")
        # ۵. نقدشوندگی و پارکِ پول — شرطِ **ورود**
        if not kept:
            if r["value_bn"] < MIN_VALUE_BN:
                why.append(f"ارزشِ معاملات {r['value_bn']:,.0f} زیرِ حد")
            if r.get("park"):
                why.append("صندوقِ پارکِ پول")
            # ۶. فیلترِ ماهِ جاری — شرطِ **ورود**، نه خروج
            if (REQUIRE_CUR_MONTH
                    and r.get("cur4") not in ("بالا", "نیمهٔ بالا", "؟")):
                why.append(f"ماهِ جاری «{r.get('cur4')}» است")
        if why:
            bad.append((r["sym"], why))
        else:
            clean.append(r)
    return clean, bad


# ══ ۳.۵ قطب‌نما — سنجش در برابر کهربا ═══════════════════════════════
# مصطفی: «می‌خواهم هر روز درآمدِ مازادم را نسبت به صندوقِ کهربا بسنجم…
# یک قطب‌نمای هوشمند که انحرافِ ما را هر روز نشان بدهد… از فردا هر روز
# سود یا ضررِ روزانه را نشان بده.»
#
# چرا کهربا مبنای درستی است: صندوقِ طلاست و بند ۱۸ docs نشان داد سنجشِ
# ریالی در تورمِ ایران تقریباً بی‌معناست. «۳۰٪ سود» وقتی طلا ۴۰٪ رفته
# یعنی عقب‌ماندگی. پس مبنا یک دارایی است، نه ریال.
#
# سه فایل در data_bourse/ نگه داشته می‌شود:
#   baseline.json  لنگر: تاریخ، قیمتِ کهربا، سرمایهٔ آن روز
#   holdings.json  سبدِ فعلی (با --adopt از دفتر پر می‌شود)
#   track.csv      یک ردیف در روز — تاریخچه‌ای که نمودار از آن می‌آید
BENCH = "کهربا"
# ── و در حالتِ سهام، مبنا **شاخص** است ─────────────────────────────
# مصطفی: «یک داشبورد جدا فقط برای تمامی سهام هم می‌بایست ساخته شود
# که ملاکِ تصمیم‌گیریِ آن بر اساس شاخص کل و شاخص کل هم‌وزن خواهد
# بود.»
#
# کدامشان؟ اندازه‌گیری شد (`tools/bench_pick.py`, `docs/34`) روی ۷۷
# صندوقِ سهامی/شاخصی — نزدیک‌ترین پروکسیِ موجود به جهانِ سهام، چون
# دادهٔ خودِ سهام در مخزن نیست. هفتگی، معیارِ هولدِ شاخص کل = ۱٫۰۰:
#
#   شاخصِ **خودِ نماد** ۰٫۹۰۶   ← بهترین
#   کهربا               ۰٫۸۸۶
#   شاخص هم‌وزن         ۰٫۸۷۱
#   شاخص کل             ۰٫۸۷۰
#   ترتیبِ تصادفی       ۰٫۸۳۲
#
# پس مبنا **یکی نیست**: هر نماد در برابرِ شاخصی سنجیده می‌شود که
# اندازه‌گیریِ محرک گفته با آن حرکت می‌کند — بزرگ‌ها با شاخص کل،
# میان‌رده‌ها با هم‌وزن. نمادِ بی‌محرک به شاخص کل برمی‌گردد.
#
# ⚠️ ولی سرِ اصلِ ماجرا: **هر چهار گزینه زیرِ ۱٫۰۰اند.** یعنی در آن
# جهان، این چرخش از هولدِ شاخص کل عقب می‌ماند. جزئیات و دلیلش
# (کارمزدِ ۱٫۲٪ × گردشِ ~۱٫۵ در هفته) در `docs/34`.
BENCH_STOCK = "شاخص کل"
BENCH_IDX = {"شاخص کل": "شاخص_کل", "شاخص هم‌وزن": "شاخص_هم‌وزن"}
# محرکی که «شاخص» است → همان مبنای آن نماد
IDX_DRV = {"شاخص_کل": "شاخص کل", "شاخص_هم‌وزن": "شاخص هم‌وزن"}
_IDX_CACHE = {}


def idx_series(name):
    """سریِ روزانهٔ یک شاخص، از data/drivers_daily. {تاریخ: کلوز}."""
    k = BENCH_IDX.get(name, name)
    if k not in _IDX_CACHE:
        f = DRV_DIR / f"{k}_daily.csv"
        ser = {}
        if f.exists():
            with f.open(encoding="utf-8-sig", newline="") as fh:
                for row in csv.DictReader(fh):
                    try:
                        ser[date.fromisoformat(str(row["date"])[:10])] = \
                            float(row["close"])
                    except (KeyError, TypeError, ValueError):
                        continue
        _IDX_CACHE[k] = ser
    return _IDX_CACHE[k]


def idx_bars(name):
    """کندل‌های روزانهٔ یک شاخص، به فرمتِ make_box."""
    k = BENCH_IDX.get(name, name)
    f = DRV_DIR / f"{k}_daily.csv"
    out = []
    if not f.exists():
        return out
    with f.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                out.append({
                    "d": date.fromisoformat(str(row["date"])[:10]),
                    "h": float(row["high"]), "l": float(row["low"]),
                    "c": float(row["close"]),
                    "v": float(row.get("volume") or 0) or 1.0})
            except (KeyError, TypeError, ValueError):
                continue
    out.sort(key=lambda b: b["d"])
    return out


# ── وضعیتِ بازار: شاخص کل و هم‌وزن ─────────────────────────────────
# مصطفی برای داشبوردِ سهام: «ملاکِ تصمیم‌گیریِ آن بر اساس شاخص کل و
# شاخص کل هم‌وزن خواهد بود.»
#
# ⚠️ این **سیگنالِ ورود نیست** و نباید بشود. بند ۳ راهنما، فهرستِ
# ردشده‌ها: «باکس روی شاخص کل به‌عنوان ورود — فقط سیگنال ریسک.» پس
# اینجا فقط خوانده و نشان داده می‌شود؛ هیچ نمادی به خاطرش حذف
# نمی‌شود.
def idx_regime():
    """{شاخص: {افق: (وضعیت، فاصلهٔ ٪، کف، سقف، کلوز)}}"""
    out = {}
    for nm in BENCH_IDX:
        bars = idx_bars(nm)
        if len(bars) < 40:
            continue
        px = bars[-1]["c"]
        by_m, by_w = defaultdict(list), defaultdict(list)
        for b in bars:
            by_m[(b["d"].year, b["d"].month)].append(b)
            by_w[week_key(b["d"])].append(b)
        hz = {}
        for fa, grp in (("ماهانه", by_m), ("هفتگی", by_w)):
            ks = sorted(grp)
            if len(ks) < 2:
                continue
            box = make_box(grp[ks[-2]])        # دورهٔ **کامل‌شدهٔ** قبل
            if not box:
                continue
            lo, hi = box
            st = state(px, box)
            d = ((px - hi) / hi * 100 if st == "بالا"
                 else (px - lo) / lo * 100 if st == "زیر" else 0.0)
            hz[fa] = (st, d, lo, hi, px)
        # دیلی: باکس از **روزِ کامل‌شدهٔ قبل** ساختنی نیست (یک کندل)،
        # پس پنجرهٔ پنج‌روزهٔ قبل از امروز.
        if len(bars) >= 11:
            box = make_box(bars[-6:-1])
            if box:
                lo, hi = box
                st = state(px, box)
                d = ((px - hi) / hi * 100 if st == "بالا"
                     else (px - lo) / lo * 100 if st == "زیر" else 0.0)
                hz["دیلی"] = (st, d, lo, hi, px)
        # ── و حکمِ خلای حجمیِ خودِ شاخص ─────────────────────────
        # مصطفی: «برای شاخص کل هم‌وزن امروز ناحیهٔ حجمیِ هفتگی‌اش را
        # به بالا شکسته، پس سیگنالِ خرید برای فردا می‌بایست صادر
        # شود.» شاخص نماد نیست و خریدنی نیست، ولی **مبنای تصمیمِ
        # داشبوردِ سهام** است، پس حکمش باید دیده شود.
        vg = vgap_all(bars)
        if hz:
            out[nm] = {"hz": hz, "date": bars[-1]["d"].isoformat(),
                       "px": px, "vg": vg,
                       "d1": (px / bars[-2]["c"] - 1) * 100
                       if len(bars) > 1 else 0.0}
    return out


def bench_for(r):
    """مبنای این نماد: در حالتِ صندوق کهربا، در حالتِ سهام شاخصِ خودش."""
    if not STOCK:
        return BENCH
    d = r.get("drv")
    return IDX_DRV.get(d, BENCH_STOCK)

# ── فیلترِ مبنا: نمادی که از کهربا عقب است سیگنال نمی‌شود ───────────
# مصطفی: «از بین نمادهایی که انتخاب کردی برو تو گذشته ببین میزان
# بازدهی‌شان چقدر بوده و اگر از بازدهیِ کهربا پایین‌تر است سیگنال
# نکن.»
#
# ولی **طولِ پنجره را نباید حدس زد**. اندازه‌گیری روی ۱۲۳ نماد و ۱۵۰
# روز، مقایسهٔ مقطعیِ درون‌روز (جلوزده‌ها در برابر عقب‌مانده‌ها در
# همان روز، که حرکتِ کلِ بازار را خنثی می‌کند):
#
#   نگاه   افقِ ۵ روز   ۱۰ روز   ۲۰ روز
#   ۲۰      −۳٫۷۹      −۶٫۳۷    −۵٫۰۶    ← **برعکس** عمل می‌کند
#   ۴۰      +۰٫۹۸      +۱٫۰۳    +۱٫۷۰    ← تنها پنجرهٔ پایدار
#   ۶۰      +۱٫۷۲      +۳٫۱۲    −۸٫۲۰    ← ناپایدار
#
# برنده‌های ۲۰ روزه شدیداً برمی‌گردند. اگر پنجره را حدس زده بودم
# احتمالش زیاد بود که همان ۲۰ را بردارم و فیلتر ضرر بدهد.
#
# ⚠️ پنجره‌ها هم‌پوشان‌اند و نمادها هم‌بسته، پس t بزرگ‌نمایی دارد.
# چیزی که قابلِ اتکاست **جهت** است، نه عددِ t.
BENCH_LOOK = 40
BENCH_FILTER = True


def bench_excess(rows, look=None):
    """مازادِ بازدهِ هر نماد نسبت به کهربا در `look` روزِ گذشته.

    روی **پنجرهٔ هم‌پوشان** حساب می‌شود، نه بازهٔ کاملِ هر نماد —
    وگرنه نمادی که تاریخچه‌اش از جای دیگری شروع شده با بازهٔ دیگری
    مقایسه می‌شود و عدد بی‌معنا می‌شود.
    """
    lk = look or BENCH_LOOK
    # مبنا: در حالتِ صندوق یک سریِ مشترک (کهربا)، در حالتِ سهام
    # **سریِ خودِ نماد** — هر کدام در برابرِ شاخصی که با آن حرکت
    # می‌کند. `docs/34`.
    kb = None
    if not STOCK:
        for r in rows:
            if norm(r["sym"]) == norm(BENCH):
                kb = r.get("hist")
                break
        if not kb:
            return
    for r in rows:
        h = r.get("hist")
        if not h:
            continue
        if STOCK:
            r["bench"] = bench_for(r)
            kb = idx_series(r["bench"])
            if not kb:
                continue
        days = sorted(set(h) & set(kb))
        if len(days) < lk + 1:
            continue
        d0, d1 = days[-lk - 1], days[-1]
        if h[d0] <= 0 or kb[d0] <= 0:
            continue
        r["bx"] = ((h[d1] / h[d0]) - (kb[d1] / kb[d0])) * 100


# ── محرکِ جهانی: کدام بازار این نماد را حرکت می‌دهد ────────────────
# مصطفی: «انتخاب بین چند سیگنال منظورم این هست که بازارهای جهانی
# تأثیرپذیرش را مدّ نظر قرار بده، و همچنین میزان بازدهی که به طور
# میانگین داشته‌اند اولویت باشد.»
#
# دو محور است. محورِ دوم (بازدهیِ تاریخی) همان `bx` بالاست و از قبل
# کار می‌کرد. محورِ اول اینجا اندازه‌گیری شد — `tools/driver_rank.py`,
# `docs/33`. خلاصهٔ آنچه درآمد:
#
#   هفتگی، ۳۵ دوره، معیارِ واحدِ کهربا، N=۶ · سقفِ وزن ۲۵٪
#     مازادِ کهربا به‌تنهایی (قاعدهٔ قبلی)   ۱٫۱۵۲   نیمه‌ها ۱٫۰۲۹ / ۱٫۱۲۸
#     مازاد + **پاسخِ محرک** (نگاهِ ۱۰ روز) ۱٫۱۹۱   نیمه‌ها ۱٫۰۴۵ / ۱٫۱۵۰
#     فقط شتابِ محرک                        ۱٫۱۴۵
#     حذفِ نمادی که محرکش منفی است          ۱٫۰۶۴   ← **بدتر**
#     حذفِ نمادی که محرکش زیرِ باکس است     ۱٫۰۵۶   ← **بدتر**
#
# پس محرک **دروازه نیست، وزنه است.** حذف‌کردن بر اساسِ محرک در هر
# شکلی ضرر داد؛ اضافه‌کردنش به امتیاز سود داد.
#
# «پاسخِ محرک» = شتابِ ۱۰ روزهٔ محرک × حساسیتِ اندازه‌گیری‌شدهٔ نماد.
# یعنی صندوق طلایی با همبستگیِ ۰٫۹۴ کلِ حرکتِ طلا را می‌گیرد و
# سینرژی با ۰٫۳۳ یک‌سومِ حرکتِ دلار را — نه اینکه هر دو یکی باشند.
#
# ⚠️ شواهد **جهت‌دار است، نه محکم**: rho درون‌دوره‌ای فقط +۰٫۰۳
# (p=۰٫۶۱، ۶۳۲ مشاهده)، و پنجرهٔ داده ۳۵ هفته است. ماهانه اصلاً از
# ترتیبِ تصادفی جدا نشد (۴۵٪ بذرهای تصادفی بهتر بودند).
DRV_DIR = HERE / "data" / "drivers_daily"
# محرک‌هایی که به وقتِ نیویورک/لندن بسته می‌شوند: کلوزِ روزِ d آن‌ها
# ساعتِ ۱۲:۳۰ تهرانِ همان روز هنوز منتشر نشده. پس فقط روزِ **قبل**.
DRV_GLOBAL = {"اونس_طلا", "اونس_نقره", "نفت_برنت", "مس"}
DRV_LOOK = 10             # نگاهِ شتابِ محرک، اندازه‌گیری‌شده
DRV_MIN_CORR = 0.15       # زیرِ این، نماد «بی‌محرکِ روشن» می‌ماند
DRV_STALE = 5             # اختلافِ روزِ مجاز با کلوزِ نمادها


def drv_load():
    """محرک‌ها از data/drivers_daily. خروجی: {نام: {تاریخ: کلوز}}."""
    out = {}
    if not DRV_DIR.exists():
        return out
    for f in sorted(DRV_DIR.glob("*_daily.csv")):
        ser = {}
        try:
            with f.open(encoding="utf-8-sig", newline="") as fh:
                for row in csv.DictReader(fh):
                    try:
                        d = date.fromisoformat(str(row["date"])[:10])
                        c = float(row["close"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if c > 0:
                        ser[d] = c
        except OSError:
            continue
        if len(ser) >= 200:
            out[f.stem[:-6]] = ser
    return out


def _drv_prev(ks, d, strict):
    i = (bisect.bisect_left(ks, d) if strict else bisect.bisect_right(ks, d))
    return ks[i - 1] if i else None


def _drv_pairs(dser, fdays, strict):
    """بازدهِ محرک روی **همان بازهٔ تقویمیِ** هر روزِ معاملاتیِ نماد.

    همبستگیِ سادهٔ هم‌روز کار نمی‌کند: هفتهٔ ایران شنبه تا چهارشنبه
    است و هفتهٔ جهانی دوشنبه تا جمعه، پس نصفِ نمونه می‌سوزد. و اونس
    شبانه حرکت می‌کند و تهران صبح واکنش می‌دهد — جهتِ درست «محرکِ
    تا قبل از امروز → بازدهِ امروز» است.
    """
    ks = sorted(dser)
    out, fd = {}, sorted(fdays)
    for i in range(1, len(fd)):
        a = _drv_prev(ks, fd[i - 1], strict)
        b = _drv_prev(ks, fd[i], strict)
        if a is None or b is None or a == b:
            continue
        out[fd[i]] = math.log(dser[b] / dser[a])
    return out


def _corr(a, b, need=60):
    ks = sorted(set(a) & set(b))
    if len(ks) < need:
        return None
    x, y = [a[k] for k in ks], [b[k] for k in ks]
    mx = sum(x) / len(x)
    my = sum(y) / len(y)
    sx = math.sqrt(sum((v - mx) ** 2 for v in x))
    sy = math.sqrt(sum((v - my) ** 2 for v in y))
    if sx <= 0 or sy <= 0:
        return None
    return sum((u - mx) * (v - my) for u, v in zip(x, y)) / (sx * sy)


def drv_attach(rows, look=None):
    """به هر ردیف محرکش، حساسیتش، و «پاسخِ محرک» را می‌چسباند.

    هیچ نمادی به خاطرِ محرک حذف نمی‌شود — اندازه‌گیری گفت حذف ضرر
    می‌دهد. فقط امتیازِ انتخاب جابه‌جا می‌شود و ستونش نشان داده
    می‌شود.
    """
    lk = look or DRV_LOOK
    drv = drv_load()
    if not drv:
        return {"ok": False, "why": f"پوشهٔ {DRV_DIR.name} نیست"}
    fresh = max(max(v) for v in drv.values())
    stamp = max((r["date"] for r in rows if r.get("date")), default="")
    lag = None
    if stamp:
        try:
            lag = (date.fromisoformat(stamp) - fresh).days
        except ValueError:
            lag = None
    # شتابِ هر محرک، یک‌بار
    mom, dd = {}, {}
    for k, ser in drv.items():
        ks = sorted(ser)
        dd[k] = ks[-1]
        if len(ks) > lk:
            mom[k] = (ser[ks[-1]] / ser[ks[-1 - lk]] - 1) * 100
    for r in rows:
        h = r.get("hist")
        if not h or len(h) < 70:
            continue
        sr = {}
        ds = sorted(h)
        for i in range(1, len(ds)):
            a, b = ds[i - 1], ds[i]
            if h[a] > 0 and h[b] > 0:
                sr[b] = math.log(h[b] / h[a])
        best, bc = None, 0.0
        for k, ser in drv.items():
            c = _corr(sr, _drv_pairs(ser, set(h), k in DRV_GLOBAL))
            if c is not None and abs(c) > abs(bc):
                best, bc = k, c
        if best is None or abs(bc) < DRV_MIN_CORR:
            r["drv"] = None
            r["drv_corr"] = bc
            continue
        r["drv"] = best
        r["drv_corr"] = bc
        r["drv_mom"] = mom.get(best)
        if r["drv_mom"] is not None:
            r["drv_resp"] = r["drv_mom"] * bc
    return {"ok": True, "n": len(drv), "date": fresh.isoformat(),
            "lag": lag, "look": lk,
            "stale": lag is not None and lag > DRV_STALE,
            "mom": mom, "dates": {k: v.isoformat() for k, v in dd.items()}}


def pick_score(r):
    """امتیازِ انتخاب: مازادِ کهربا + پاسخِ محرک.

    اگر محرکی اندازه‌گیری نشد، فقط مازاد — همان رفتارِ قبلی.
    """
    bx = r.get("bx")
    if bx is None:
        return None
    return bx + (r.get("drv_resp") or 0.0)


def holdings_load():
    """سبدِ فعلی: از فایل، وگرنه از ثابتِ HOLDING بالای فایل.

    فایل را `--adopt` می‌نویسد، بعد از اینکه سفارشِ دفتر را اجرا کردی.
    این‌طوری برای به‌روز کردنِ پرتفو لازم نیست کدِ پایتون را دست بزنی.
    """
    f = DATA / "holdings.json"
    if f.exists():
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            return d.get("units", {}), float(d.get("cash", 0))
        except (ValueError, TypeError):
            pass
    return dict(HOLDING), float(CASH)


def holdings_save(units, cash):
    DATA.mkdir(exist_ok=True)
    (DATA / "holdings.json").write_text(
        json.dumps({"units": units, "cash": cash},
                   ensure_ascii=False, indent=1), encoding="utf-8")


def port_value(units, cash, px):
    """ارزشِ روزِ سبد. (ارزش، فهرستِ نمادهای بی‌قیمت)"""
    tot, miss = float(cash), []
    for sym, u in units.items():
        c = px.get(norm(sym))
        if c is None:
            miss.append(sym)
            continue
        tot += u * c
    return tot, miss


def compass(px, units, cash, stamp):
    """قطب‌نما: پرتفو در برابرِ کهربا، از روزِ لنگر تا امروز.

    بازدهِ مبنا = همان مبلغِ روزِ لنگر، اگر تماماً کهربا خریده بودی.
    مازاد = پرتفو منهای آن. هم ریالی، هم درصدی.

    ⚠️ روزِ اول همه‌چیز صفر است و باید صفر باشد — تاریخچه‌ای نیست که
    از آن پیشرفت درآید. عددِ واقعی از فردا شروع می‌شود.
    """
    bpx = px.get(norm(BENCH))
    if bpx is None:
        return None
    pv, miss = port_value(units, cash, px)
    bf = DATA / "baseline.json"
    base = None
    if bf.exists():
        try:
            base = json.loads(bf.read_text(encoding="utf-8"))
        except ValueError:
            base = None
    if not base or not base.get("bench_px"):
        base = {"date": stamp, "bench": BENCH, "bench_px": bpx,
                "capital": pv}
        DATA.mkdir(exist_ok=True)
        bf.write_text(json.dumps(base, ensure_ascii=False, indent=1),
                      encoding="utf-8")

    bench_val = base["capital"] * (bpx / base["bench_px"])
    # ── معیارِ اصلی: **تعدادِ واحدِ کهربا** ─────────────────────────
    # مصطفی: «می‌خواهیم هر روز نسبت به صندوقِ کهربا بسنجیم که توانستیم
    # تعدادِ واحدهامان را نسبت به آن افزایش بدهیم یا نه.»
    #
    # این از مازادِ ریالی دقیق‌تر بیان می‌کند چه اتفاقی افتاده: اگر کلِ
    # پرتفو را امروز بفروشی، چند واحد کهربا می‌خری؟ و آن عدد از روزِ
    # لنگر بیشتر شده یا کمتر؟ ریال بالا و پایین می‌رود، این نه.
    u_now = pv / bpx
    u_base = base["capital"] / base["bench_px"]
    out = {"date": stamp, "base_date": base["date"],
           "base_capital": base["capital"], "base_bench_px": base["bench_px"],
           "bench_px": bpx, "port": pv, "bench": bench_val,
           "excess_rial": pv - bench_val,
           "excess_pct": (pv / bench_val - 1) * 100 if bench_val else 0.0,
           "port_pct": (pv / base["capital"] - 1) * 100,
           "bench_pct": (bpx / base["bench_px"] - 1) * 100,
           "units_now": u_now, "units_base": u_base,
           "units_d": u_now - u_base,
           "units_pct": (u_now / u_base - 1) * 100 if u_base else 0.0,
           "missing": miss, "first_day": base["date"] == stamp}

    # ── تاریخچه: یک ردیف در روز، بدونِ تکرار ──────────────────────
    tf = DATA / "track.csv"
    hist = []
    if tf.exists():
        with tf.open(encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                if r.get("date") and r["date"] != stamp:
                    hist.append(r)
    prev = hist[-1] if hist else None
    out["day_pnl"] = (pv - float(prev["port"])) if prev else 0.0
    out["day_pct"] = ((pv / float(prev["port"]) - 1) * 100
                      if prev and float(prev["port"]) else 0.0)
    out["day_bench_pct"] = ((bpx / float(prev["bench_px"]) - 1) * 100
                            if prev and float(prev.get("bench_px") or 0)
                            else 0.0)
    row = {"date": stamp, "port": f"{pv:.0f}", "bench_px": f"{bpx:.0f}",
           "units": f"{u_now:.2f}",
           "bench": f"{bench_val:.0f}",
           "excess_rial": f"{pv - bench_val:.0f}",
           "excess_pct": f"{out['excess_pct']:.4f}"}
    hist.append(row)
    with tf.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(row))
        w.writeheader()
        for r in hist:
            w.writerow({k: r.get(k, "") for k in row})
    out["hist"] = hist[-40:]

    # انحرافِ معیارِ مازادِ روزانه — «قطب‌نما» فقط جهت نیست، پراکندگی
    # هم هست. با کمتر از ۵ روز عدد نمی‌دهد چون بی‌معناست.
    ex = [float(r["excess_pct"]) for r in hist if r.get("excess_pct")]
    d = [ex[i] - ex[i - 1] for i in range(1, len(ex))]
    out["sd"] = statistics.pstdev(d) if len(d) >= 5 else None
    out["days"] = len(hist)
    return out


def rebalance(units, cash, book, px, capital):
    """از سبدِ فعلی به سبدِ هدف — دقیقاً چه بفروش و چه بخر.

    مصطفی: «پرتفوم را دقیق بگو با چه مبلغی بفروشم.» پس ستونِ مبلغ
    اجباری است، نه فقط تعدادِ واحد.

    **اول فروش، بعد خرید** — بند ۲ راهنما: «پول آزادشده منبعِ خریدِ
    همان صبح است.»
    """
    want = {}
    for r in book:
        c = px.get(norm(r["sym"]))
        if c:
            want[r["sym"]] = (capital * r["w"] / 100) / c
    sells, buys, noprice = [], [], []
    for sym, u in units.items():
        c = px.get(norm(sym))
        if c is None:
            # بی‌صدا ردش نکن — این همان الگویی است که سه بار گرفت.
            noprice.append(sym)
            continue
        tgt = 0.0
        for w, wu in want.items():
            if norm(w) == norm(sym):
                tgt = wu
                break
        if u - tgt > max(1.0, u * 0.02):          # زیرِ ۲٪ اختلاف را دست نزن
            sells.append({"sym": sym, "units": u - tgt, "px": c,
                          "amt": (u - tgt) * c, "all": tgt <= 0})
    for sym, wu in want.items():
        c = px.get(norm(sym))
        if c is None:
            continue
        have = 0.0
        for s2, u2 in units.items():
            if norm(s2) == norm(sym):
                have = u2
                break
        if wu - have > max(1.0, wu * 0.02):
            buys.append({"sym": sym, "units": wu - have, "px": c,
                         "amt": (wu - have) * c, "new": have <= 0})
    sells.sort(key=lambda x: -x["amt"])
    buys.sort(key=lambda x: -x["amt"])
    return sells, buys, noprice


# ══ ۳.۶ واحدِ کهربا — هدفِ نهایی ═══════════════════════════════════
# مصطفی: «دیروز سینرژی ۷ درصد مثبت بود، کهربا ۳ درصد. این اختلافِ
# تعدادِ واحد را باید هر روز نشان بدهی — و همچنین هفتگی و ماهانه.
# تعدادِ واحدِ بیشترِ **هر نماد** نسبت به کهربا، و **مجموعِ همهٔ
# نمادها** روزانه، هفتگی و ماهانه. این هدفِ غایی و نهاییِ من از
# انجامِ معامله روی همهٔ نمادهاست.»
#
# ## تعریف
#
# اگر نمادی r_s درصد رفته و کهربا r_b، آن نماد این‌قدر واحدِ کهرباىِ
# بیشتر به تو داده:
#
#     (۱ + r_s) ÷ (۱ + r_b) − ۱
#
# مثالِ خودش روی دادهٔ ۲۰۲۶-۰۹-۲۰: سینرژی از ۶۳٬۴۹۹ به ۶۶٬۹۲۶ یعنی
# +۵٫۴۰٪، کهربا از ۲۲۶٬۹۹۸ به ۲۲۷٬۸۹۹ یعنی +۰٫۴۰٪ →
# ۱٫۰۵۴۰ ÷ ۱٫۰۰۴۰ − ۱ = **+۴٫۹۸٪ واحدِ بیشتر**.
#
# و برای **کلِ پرتفو** همان کار روی ارزشِ سبد انجام می‌شود:
#
#     واحدِ کهربا در هر روز = ارزشِ سبد ÷ قیمتِ کهربا
#
# پس مازاد = نسبتِ این عدد بین دو تاریخ. این دقیقاً «تعدادِ واحد»
# است، نه بازدهِ ریالی — و بند ۱۸ docs نشان داد سنجشِ ریالی در تورمِ
# ایران تقریباً بی‌معناست.
#
# ## سه افق
#
#   روزانه  کلوزِ امروز در برابرِ کلوزِ جلسهٔ قبل
#   هفتگی   کلوزِ امروز در برابرِ **آخرین کلوزِ هفتهٔ کامل‌شدهٔ قبل**
#   ماهانه  کلوزِ امروز در برابرِ **آخرین کلوزِ ماهِ میلادیِ قبل**
#
# لنگرِ هفتگی و ماهانه عمداً «۵ روز پیش» و «۳۰ روز پیش» نیست — بند ۲
# راهنما تصمیم را روی همین مرزها می‌گذارد، پس سنجش هم باید همان‌جا
# باشد وگرنه عددِ گزارش با عددِ تصمیم نمی‌خواند.
UNIT_HZ = (("روزانه", "d"), ("هفتگی", "w"), ("ماهانه", "m"))


def _anchor_date(days, hz):
    """تاریخِ مبنای هر افق — بدونِ لوک‌اهد، از خودِ تقویم."""
    if not days:
        return None
    last = days[-1]
    if hz == "d":
        return days[-2] if len(days) > 1 else None
    if hz == "w":
        wk = week_key(last)
        prev = [d for d in days if week_key(d) < wk]
        return prev[-1] if prev else None
    cur = (last.year, last.month)
    prev = [d for d in days if (d.year, d.month) < cur]
    return prev[-1] if prev else None


def bench_units(rows, units=None, px=None):
    """مازادِ «تعدادِ واحدِ کهربا» — هر نماد و کلِ پرتفو، سه افق.

    خروجی:
      {"sym": [{sym, cat, held, d, w, m, …}], "port": {d, w, m},
       "dates": {افق: (تاریخِ مبنا، تاریخِ پایان)}}

    نمادی که در یک افق دادهٔ کافی ندارد، آن خانه‌اش None می‌ماند —
    صفر نمی‌شود، چون صفر یعنی «هم‌پای کهربا» و آن حرفِ دیگری است.
    """
    kb = None
    for r in rows:
        if norm(r["sym"]) == norm(BENCH):
            kb = r.get("hist")
            break
    if not kb:
        return None
    bd = sorted(kb)
    anch = {}
    for fa, hz in UNIT_HZ:
        a = _anchor_date(bd, hz)
        if a is not None:
            anch[hz] = (a, bd[-1])
    if not anch:
        return None

    def gain(h, hz):
        """(۱+r_نماد) ÷ (۱+r_کهربا) − ۱، بر حسبِ درصد."""
        if hz not in anch:
            return None
        a, b = anch[hz]
        # نماد باید در **هر دو** تاریخ کلوز داشته باشد، وگرنه عدد
        # مقایسهٔ دو بازهٔ متفاوت است.
        if a not in h or b not in h or h[a] <= 0 or kb[a] <= 0:
            return None
        return ((h[b] / h[a]) / (kb[b] / kb[a]) - 1) * 100

    held = {norm(k): v for k, v in (units or {}).items() if v}
    out = []
    for r in rows:
        h = r.get("hist")
        if not h:
            continue
        row = {"sym": r["sym"], "cat": r.get("cat", "؟"),
               "held": held.get(norm(r["sym"]), 0),
               "close": r.get("close"), "bx": r.get("bx"),
               "self": norm(r["sym"]) == norm(BENCH)}
        ok = False
        for _fa, hz in UNIT_HZ:
            g = gain(h, hz)
            row[hz] = g
            ok = ok or g is not None
        if ok:
            out.append(row)
    out.sort(key=lambda x: -(x.get("d") if x.get("d") is not None
                             else -1e9))

    # ── کلِ پرتفو ──────────────────────────────────────────────────
    # ارزشِ سبد در هر تاریخ، با **همان تعدادِ واحدِ امروز** — یعنی
    # «اگر این سبد را از آن تاریخ نگه داشته بودم». اگر قیمتِ یک قلم
    # در آن تاریخ نباشد از کلِ محاسبهٔ آن افق بیرون می‌ماند و نامش
    # چاپ می‌شود؛ بی‌صدا صفر گرفتنش یعنی عددِ غلط.
    hist = {norm(r["sym"]): r["hist"] for r in rows if r.get("hist")}
    port, miss = {}, {}
    for _fa, hz in UNIT_HZ:
        if hz not in anch:
            continue
        a, b = anch[hz]
        va = vb = 0.0
        gone = []
        for k, u in held.items():
            h = hist.get(k)
            if not h or a not in h or b not in h:
                gone.append(k)
                continue
            va += u * h[a]
            vb += u * h[b]
        if va > 0 and kb[a] > 0:
            port[hz] = ((vb / va) / (kb[b] / kb[a]) - 1) * 100
        if gone:
            miss[hz] = gone
    return {"sym": out, "port": port, "miss": miss,
            "dates": {hz: (a.isoformat(), b.isoformat())
                      for hz, (a, b) in anch.items()}}


# ══ ۳.۷ تغییرِ امروز نسبت به دیروز ═════════════════════════════════
# مصطفی: «اگر نمادی خلا حجمی را شکسته، یا نمادی حد ضرر خورده، یا
# خریدی باید به پرتفو اضافه کنم را **هر روز** باید به من نشان بدهی.»
#
# «شکسته» و «خورده» فعلِ گذشته‌اند، یعنی **تغییر** — نه وضعیت. نمادی
# که سه هفته است زیرِ ناحیه است امروز چیزی را نشکسته. پس وضعیتِ هر
# اجرا ذخیره می‌شود و اجرای بعد با آن مقایسه.
#
# فایل: data_bourse/state.json — یک عکسِ ساده از وضعیتِ هر نماد.
def state_load():
    f = DATA / "state.json"
    if f.exists():
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            return d.get("stamp"), d.get("sym", {})
        except (ValueError, TypeError):
            pass
    return None, {}


def state_save(stamp, rows, book):
    bk = {norm(r["sym"]) for r in book}
    d = {"stamp": stamp, "sym": {}}
    for r in rows:
        if not r.get("ok"):
            continue
        d["sym"][norm(r["sym"])] = {
            "vgv": (r.get("vg") or {}).get("حکم"),
            "wst": r.get("wst"), "mst": r.get("mst"),
            "wd": bool(r.get("w_dead")), "md": bool(r.get("m_dead")),
            "book": norm(r["sym"]) in bk,
            "close": r.get("close")}
    DATA.mkdir(exist_ok=True)
    (DATA / "state.json").write_text(
        json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


# هر رویداد: (اولویت، برچسب، رنگ، توضیح)
EV = {
    "vg_break": (0, "شکستِ خلای حجمی ↓", "r",
                 "حکمِ خلای حجمی از بالا/داخل به **زیر** رفت — "
                 "قاعدهٔ خروجِ خودت"),
    "stop": (0, "استاپ خورد", "r",
             "کلوز از کفِ باکس رد شد؛ سیگنالِ آن افق مرده است"),
    "wst_down": (1, "زیرِ باکسِ هفتگی", "r",
                 "وضعیتِ هفتگی به «زیر» رفت"),
    "mst_down": (1, "زیرِ باکسِ ماهانه", "r",
                 "وضعیتِ ماهانه به «زیر» رفت"),
    "out": (2, "از دفتر خارج شد", "y",
            "دیروز در دفتر بود، امروز نیست"),
    "vg_back": (3, "بازگشت بالای خلای حجمی ↑", "g",
                "حکمِ خلای حجمی به **بالا** برگشت"),
    "wst_up": (4, "بالای باکسِ هفتگی", "g",
               "وضعیتِ هفتگی به «بالا» رفت"),
    "mst_up": (4, "بالای باکسِ ماهانه", "g",
               "وضعیتِ ماهانه به «بالا» رفت"),
    "in": (5, "واردِ دفتر شد", "g",
           "امروز در دفترِ پیشنهادی آمده و دیروز نبود"),
}


def state_diff(rows, book, units=None, stamp=None):
    """چه چیزی **امروز** عوض شد — نه اینکه وضعیت چیست.

    خروجی: (تاریخِ مقایسه، [رویداد]). اگر عکسِ دیروز نباشد فهرست خالی
    است و تاریخ None — و این را باید گفت، نه اینکه «هیچ تغییری نبود»
    نشان داد. آن دو یکی نیستند.
    """
    prev_stamp, prev = state_load()
    if not prev:
        return None, []
    # ── آیا دوره نو شده؟ ──────────────────────────────────────────
    # اولین جلسهٔ هفته که می‌شود، باکسِ هفتگی از نو ساخته می‌شود و
    # ده‌ها نماد **هم‌زمان** حالتشان عوض می‌شود. آن خبر نیست، تقویم
    # است. بارِ اول که این را ساختم ۳۰ ردیفِ «⛔ زیرِ باکسِ هفتگی»
    # پشتِ سرِ هم چاپ شد و کلِ صفحه را بی‌فایده کرد.
    new_w = new_m = False
    try:
        a = date.fromisoformat(prev_stamp) if prev_stamp else None
        b = date.fromisoformat(stamp) if stamp else None
        if a and b:
            new_w = week_key(a) != week_key(b)
            new_m = (a.year, a.month) != (b.year, b.month)
    except (TypeError, ValueError):
        pass
    bk = {norm(r["sym"]) for r in book}
    held = {norm(k) for k, v in (units or {}).items() if v}
    out = []
    for r in rows:
        if not r.get("ok"):
            continue
        k = norm(r["sym"])
        o = prev.get(k)
        if not o:
            continue
        now = {"vgv": (r.get("vg") or {}).get("حکم"),
               "wst": r.get("wst"), "mst": r.get("mst"),
               "wd": bool(r.get("w_dead")), "md": bool(r.get("m_dead")),
               "book": k in bk}
        ev = []
        if o.get("vgv") in ("بالا", "داخل") and now["vgv"] == "زیر":
            ev.append("vg_break")
        if o.get("vgv") == "زیر" and now["vgv"] == "بالا":
            ev.append("vg_back")
        if (now["wd"] and not o.get("wd")) or (now["md"]
                                              and not o.get("md")):
            ev.append("stop")
        # وقتی باکس نو شده، جابه‌جاییِ حالت را **خبر** حساب نکن —
        # مگر روی نمادی که داری یا در دفتر است، که آنجا هرطور شده
        # باید ببینی‌اش.
        care = k in held or now["book"] or o.get("book")
        if not new_w or care:
            if o.get("wst") != "زیر" and now["wst"] == "زیر":
                ev.append("wst_down")
            if o.get("wst") == "زیر" and now["wst"] == "بالا":
                ev.append("wst_up")
        if not new_m or care:
            if o.get("mst") != "زیر" and now["mst"] == "زیر":
                ev.append("mst_down")
            if o.get("mst") == "زیر" and now["mst"] == "بالا":
                ev.append("mst_up")
        if now["book"] and not o.get("book"):
            ev.append("in")
        if o.get("book") and not now["book"]:
            ev.append("out")
        for e in ev:
            pri, lab, col, why = EV[e]
            if new_w and e in ("wst_down", "wst_up"):
                lab += " (باکسِ هفتگی نو شد)"
            if new_m and e in ("mst_down", "mst_up"):
                lab += " (باکسِ ماهانه نو شد)"
            # رویدادی که روی نمادی افتاده که **داری**، یک پله
            # فوری‌تر است — همان چیزی که باید امروز کاری برایش کنی.
            out.append({"sym": r["sym"], "cat": r.get("cat", "؟"),
                        "ev": e, "lab": lab, "col": col, "why": why,
                        "pri": pri - (1 if k in held else 0),
                        "held": k in held,
                        "close": r.get("close"),
                        "was": o.get("close"),
                        "units": (units or {}).get(r["sym"], 0)})
    out.sort(key=lambda x: (x["pri"], not x["held"], x["sym"]))
    return prev_stamp, out


def diff_split(dif, book):
    """(آنچه امروز کارِ توست، بقیهٔ جهان).

    رویدادی روی نمادی که نه داری و نه در دفتر است، **خبر** است نه
    کار. جدا نگه داشتنشان تنها راهی است که فهرستِ کار خوانا بماند.
    """
    bk = {norm(r["sym"]) for r in book}
    mine = [e for e in dif if e["held"] or norm(e["sym"]) in bk]
    rest = [e for e in dif if not (e["held"] or norm(e["sym"]) in bk)]
    return mine, rest


# ── بک‌تستِ همین معیار ─────────────────────────────────────────────
# «تو بک‌تست‌ها هم باید این استراتژی کار کند و نشان دهد میانگین چند
# درصد، چه هفتگی و چه ماهانه، پرتفو را نسبت به کهربا بیشتر کرده‌ایم.»
# بازسازی: `python3 tools/unit_gain.py`
UNIT_BT = (
    '<div class="note"><b>و همین معیار در بک‌تست</b> — ۱۰۱ نماد، '
    '۲۰۲۶-۰۱-۱۴ تا ۲۰۲۶-۰۹-۲۰، N=۶، سقفِ وزن ۲۵٪، کارمزد ۰٫۵۵٪، '
    'بعد از کارمزد:'
    '<table class="table" style="margin-top:8px"><thead><tr>'
    '<th class="th">افق</th><th class="th n">کلِ پنجره</th>'
    '<th class="th n">میانگینِ هر دوره</th>'
    '<th class="th n">سالانه (تعمیم)</th>'
    '<th class="th n">دوره‌های جلو</th>'
    '<th class="th n">کنترلِ تصادفی</th></tr></thead><tbody>'
    '<tr><td class="td sym">هفتگی · ۳۴ دوره</td>'
    '<td class="td n g">+۱۹٫۰۹٪</td><td class="td n g">+۰٫۵۱۵٪</td>'
    '<td class="td n g">+۳۰٫۶٪</td><td class="td n">۴۴٫۸٪</td>'
    '<td class="td n sub">+۰٫۰۶۲٪ · ۱٪ بهتر</td></tr>'
    '<tr><td class="td sym">ماهانه · ۸ دوره</td>'
    '<td class="td n g">+۳۷٫۶۶٪</td><td class="td n g">+۴٫۰۷۶٪</td>'
    '<td class="td n g">+۶۱٫۵٪</td><td class="td n">۶۲٫۵٪</td>'
    '<td class="td n sub">+۲٫۱۲۵٪ · ۲٪ بهتر</td></tr>'
    '</tbody></table>'
    '<b>⚠️ مزیت دم‌کلفت است، نه یکنواخت.</b> در افقِ هفتگی '
    '<b>میانهٔ</b> دوره ‎−۰٫۲۱٪ است و فقط <b>۴۴٫۸٪</b> از هفته‌ها جلو '
    'بوده‌اند — یعنی هفتهٔ معمولی کمی عقب است و چند هفتهٔ خیلی خوب '
    '(بهترین ‎+۲۰٫۱٪) کلِ کار را می‌سازند. ماهانه یکنواخت‌تر است '
    '(میانه ‎+۳٫۹۱٪، ۶۲٫۵٪ جلو) ولی فقط ۸ دوره دارد.'
    '<br>کنترلِ ترتیبِ تصادفی نشان می‌دهد این از **رتبه‌بندی** می‌آید '
    'نه فقط از فیلتر: ۱٪ و ۲٪ از بذرهای تصادفی بهتر بودند.'
    '<br>⚠️ هارنسِ بک‌تست هستهٔ قاعده را دارد ولی دو افزودهٔ تازه — '
    'قاعدهٔ «نگه‌داشته» و حکمِ خلای حجمی — را ندارد، پس کفِ کارِ '
    'سیستمِ امروز است نه سقفش. و پنجره <b>یک رژیمِ بازار</b> است.'
    '</div>')


# ══ ۴. آلارم ════════════════════════════════════════════════════════
def alarms(rows, book, units=None):
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
        # ⚠️ از **سبدِ واقعی** بخوان نه از ثابتِ HOLDING. حالا که سبد
        # با --adopt در فایل نوشته می‌شود، NORM_HOLD می‌تواند کهنه
        # باشد و آلارمِ فروش روی نمادی که دیگر نداری روشن شود — یا
        # بدتر، روی نمادی که داری روشن **نشود**.
        held = ({norm(k): v for k, v in units.items()} if units
                else NORM_HOLD)
        if n not in held:
            continue
        if r["wst"] == "زیر" or r["mst"] == "زیر":
            which = []
            if r["mst"] == "زیر":
                which.append("ماهانه")
            if r["wst"] == "زیر":
                which.append("هفتگی")
            sell.append((r["sym"], r["close"], " و ".join(which),
                         held[n]))
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
def html(rows, book, capital, stamp, last_date, buy=(), sell=(),
         comp=None, sells=(), buys=(), nopx=(), pos=(), rr=None,
         drv=None, bu=None, dif=None, dstamp=None):
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
        """⚠️ افق‌ها **قاطی نمی‌شوند.**

        قبلاً این بود:
            v = WINRATE[hz].get(k) or WINRATE["week"].get(k)
        یعنی اگر جدولِ ماهانه سطری برای این وضعیت نداشت، بی‌صدا از
        جدولِ **هفتگی** پر می‌شد. در خروجیِ ۲۲ سپتامبرِ مصطفی همین
        افتاده بود: در پنلِ ماهانه n=۹۸۴ و n=۲۴۲ دیده می‌شد که هر دو
        عددِ جدولِ هفتگی‌اند («هر سه بالا» و «هر سه زیر» در جدولِ
        ماهانه اصلاً سطر ندارند).

        عددِ هفتگی زیرِ عنوانِ «بک‌تستِ ماهانه» یعنی افقِ اشتباه به
        نمادِ درست نسبت داده شود. حالا اگر سطر نیست، **هیچ** نشان
        داده می‌شود.
        """
        k = wr_key(r)
        v = WINRATE.get(hz, {}).get(k) if k else None
        return v or (0, 0, 0.0)

    def btcell(nn, win, avg):
        """بک‌تستِ سطلِ وضعیت — سه عددِ یک واقعیت، در یک ستون.

        قبلاً سه ستونِ جدا بود و با اضافه شدنِ «حمایتِ خلای حجمی»
        جدول از صفحه بیرون می‌زد. n و نرخِ برد و میانگین هر سه از یک
        سطرِ جدولِ بک‌تست می‌آیند، پس کنار هم درست‌ترند.
        """
        if not nn:
            return ('<span class="sub" title="جدولِ بک‌تستِ این افق '
                    'سطری برای وضعیتِ امروزِ این نماد ندارد. عمداً از '
                    'جدولِ افقِ دیگر پر نمی‌شود.">—</span>')
        cls = "g" if avg > 0 else "r"
        return (f'<span class="bt" title="n={nn:,} مشاهده در همین وضعیت">'
                f'{win}٪ {bar(win)} '
                f'<b class="{cls}">{avg:+.2f}٪</b> '
                f'<i class="sub">n={n(nn)}</i></span>')

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

    def vlevcell(r):
        """حکمِ خلای حجمی — **مبنای تصمیمِ خودِ مصطفی**.

        «مبنای اصلیِ این استراتژی کندلِ هفتگی هست و ماهانه… هرگاه
        ناحیهٔ خلا حجمی شکل گرفت، هرگاه کلوزِ روزِ بعد بالا یا پایینِ
        ناحیه بود، مبنای تصمیم‌گیریِ ما خواهد بود.»

        تا امروز این سلول فاصلهٔ قیمت تا ناحیه را نشان می‌داد و حکم
        را از سریِ **دیلی** می‌گرفت. حالا حکم از **هفتگی** می‌آید،
        روی کلوزِ روزِ تصمیم، و ماهانه تأییدکننده است.
        """
        vg = r.get("vg") or {}
        if not vg or vg.get("حکم") in (None, "؟"):
            return '<span class="sub">— — —</span>'
        fin = vg.get("حکم")
        cls = {"بالا": "vv-u", "زیر": "vv-d"}.get(fin, "vv-i")
        mark = {"بالا": "✓", "زیر": "✕"}.get(fin, "~")
        out = [f'<span class="vv {cls}" title="حکمِ نهایی بر اساسِ '
               f'{vg.get("مبنا")} — قاعدهٔ اعلام‌شدهٔ خودت: هفتگی '
               f'مبناست، ماهانه تأییدکننده، دیلی فقط خبر.">'
               f'{mark}</span>']
        # ترتیب: «اول باید مانت باشه، بعد هفته، بعد دی»
        for fa in ("ماهانه", "هفتگی", "دیلی"):
            v = vg.get(fa)
            if not v:
                out.append('<span class="vl vl-n" title="'
                           f'{fa}: خلای حجمی‌ای پیدا نشد">'
                           f'{fa[0]} —</span>')
                continue
            vd = v["verdict"]
            c2 = ("vl-u" if vd == "بالا" else "vl-d" if vd == "زیر"
                  else "vl-n" if vd == "دور" else "vl-i")
            txt = (f"{fa[0]} {v['dist']:+.1f}٪" if vd in ("بالا", "زیر")
                   else f"{fa[0]} دور" if vd == "دور"
                   else f"{fa[0]} داخل")
            why = ("ناحیه بیش از "
                   f"{VGAP_NEAR:.0f}٪ دور است، پس حکم نمی‌دهد — "
                   "میانهٔ فاصلهٔ ناحیهٔ ماهانه ۲۷٪ است و آن‌قدر دور "
                   "همه را «بالا» نشان می‌دهد"
                   if vd == "دور" else
                   f"کلوزِ روزِ تصمیم {n(v['dec'])} در برابرِ ناحیه")
            out.append(
                f'<span class="vl {c2}" title="{fa}: ناحیهٔ '
                f'{n(v["lo"])}–{n(v["hi"])} که در {v["zone_d"]} شکل '
                f'گرفت ({v["age"]} دوره پیش) · {why} → {vd}'
                + ("‌ · ⛔ بعدش کلوزی کاملاً زیرِ ناحیه داده"
                   if v.get("broke") else "")
                + f'">{txt}</span>')
        return "".join(out)

    def gate(r):
        """چرا این نماد در دفتر نیست — **داخلِ جدولِ سیگنال**.

        مصطفی روی پالایش گرفتش: «چرا سیگنال شده؟ هم زیرِ حجمِ ماهانهٔ
        فعلی‌اش است هم زیرِ هفتگی‌اش.» پالایش `cur_st = زیر` داشت و
        از دفتر بیرون بود — ولی در جدولِ سیگنال رتبهٔ ۳ و ۵ نشسته بود
        بدونِ هیچ علامتی. تبِ «وضعیت همهٔ نمادها» دلیلش را داشت، ولی
        چیزی که خوانده می‌شود این جدول است.

        همان درسِ نهال، از جهتِ عکس: آنجا بی‌صدا **حذف** می‌شد، اینجا
        بی‌صدا **وارد** می‌شود.
        """
        if r["sym"] in book_syms:
            return ('<span class="gate gate-mw" title="کلوزِ روزِ تصمیم '
                    'زیرِ باکس بود ولی دو کلوزِ پشتِ هم بالای سقف داد. '
                    'اندازه‌گیری: +۱٫۴۳ واحد بهتر از بازنگشتن (t=+۳٫۹۳) '
                    'ولی ۰٫۹۷ واحد ضعیف‌تر از سیگنالِ اصلی — پس '
                    'نیمه‌سیگنال.">بازگشتِ درون‌هفته</span>'
                    if r.get("midweek") else "")
        why_ = None
        if r["value_bn"] < MIN_VALUE_BN or r.get("park"):
            why_ = None                      # نشانِ «کم‌حجم» خودش هست
        elif (REQUIRE_CUR_MONTH
              and r.get("cur4") not in ("بالا", "نیمهٔ بالا", "؟")):
            why_ = "زیرِ ماهِ جاری"
        elif r["mst"] != "بالا":
            why_ = "زیرِ ماه قبل"
        elif r["wst"] == "زیر":
            why_ = "زیرِ هفتگی"
        elif (BENCH_FILTER and r.get("bx") is not None and r["bx"] < 0):
            why_ = f'{r["bx"]:+.0f} واحد عقبِ {BENCH}'
        elif not (r.get("cat_wide", True)
                  or norm(r["sym"]) in NORM_EXEMPT):
            why_ = "دسته‌اش منفی است"
        else:
            # ── واجد شرط ولی انتخاب نشده ──────────────────────────
            # مصطفی روی نهال پرسید «چرا سیگنال نیست؟» و جواب این بود
            # که هیچ شرطی را رد نکرده — فقط سینرژی با ۴٫۵ برابر حجم
            # اسلاتِ «کالایی» را گرفته. ولی نهال هیچ نشانی نمی‌گرفت و
            # از روی جدول با یک نمادِ داخلِ دفتر فرقی نداشت.
            # همان درسِ نهال، بارِ سوم.
            sc = pick_score(r)
            return ('<span class="gate gate-ok" title="همهٔ شرط‌ها را '
                    'دارد ولی در دفتر نیامد: دفتر '
                    f'{MAX_PICKS} نماد می‌گیرد و رتبه‌بندی روی '
                    '«مازادِ کهربا + پاسخِ محرک» است'
                    + (f' — امتیازِ این نماد {sc:+.1f}.'
                       if sc is not None else '.')
                    + ' قیدِ تنوع عمداً نیست: اندازه‌گیری نشان داد '
                    'هر قیدِ تنوع از کهربا عقب می‌اندازد (docs/32).">'
                    f'واجد شرط، خارج از {MAX_PICKS} نمادِ برتر</span>')
        # وقتی دلیل «کم‌حجم» است، نشانِ خودش هست و why_ خالی می‌ماند.
        # بدونِ این چک، برچسبِ «None» روی ۳۴۰ ردیف چاپ می‌شد — همان
        # جنسِ باگی که مصطفی روی فملی و پالایش گرفت.
        if not why_:
            return ""
        return (f'<span class="gate" title="در دفترِ پیشنهادی نیامد: '
                f'{why_}">{why_}</span>')

    def thin(r):
        """نمادِ کم‌حجم در جدول می‌ماند ولی علامت می‌خورد — در دفتر
        نمی‌آید و مصطفی باید بداند چرا."""
        if r["value_bn"] >= MIN_VALUE_BN:
            return ""
        return (f'<span class="thin" title="ارزشِ معاملات '
                f'{r["value_bn"]:.0f} م.ر — زیرِ {MIN_VALUE_BN:.0f}">'
                f'کم‌حجم</span>')

    def alarm(z, dead=False):
        # سیگنالی که استاپش خورده باید **در خودِ جدول** علامت بخورد،
        # نه فقط از دفتر بیرون برود. مصطفی جدول را می‌خواند، و یک ردیف
        # با کلوزِ زیرِ استاپ و بدونِ علامت یعنی پیشنهادِ خرید.
        if dead:
            return ('<span class="badge b-r" title="کلوزِ امروز زیرِ '
                    'حدضررِ این باند است — سیگنال دیگر قابلِ اجرا '
                    'نیست">⛔ استاپ خورده</span>')
        if z["state"] == "در نوار":
            return '<span class="badge b-g">🔔 در نوار</span>'
        if z["state"] == "زیر نوار":
            return (f'<span class="badge b-m">{z["dist_pct"]:+.1f}٪ تا نوار'
                    f'</span>')
        return '<span class="badge b-y">بالای نوار</span>'

    # ── تبِ ۱: سیگنال — رتبه‌بندی‌شده ──
    def drvcell(r):
        """محرکِ نماد، حساسیتش، و پاسخِ امروزِ آن محرک.

        این ستون **دروازه نیست**. اندازه‌گیری (`docs/33`) گفت حذف بر
        اساسِ محرک در هر شکلی ضرر می‌دهد — ولی اضافه‌کردنش به امتیازِ
        انتخاب سود می‌دهد. پس اینجا فقط دیده می‌شود، و در دفتر روی
        ترتیب اثر می‌گذارد.
        """
        k = r.get("drv")
        if not k:
            c = r.get("drv_corr")
            t = (f"بیشترین همبستگی {c:+.2f} بود، زیرِ آستانهٔ "
                 f"{DRV_MIN_CORR:.2f}" if c else "اندازه‌گیری نشد")
            return f'<span class="sub" title="{t}">—</span>'
        nm = k.replace("_", " ")
        cc = r.get("drv_corr") or 0.0
        m, resp = r.get("drv_mom"), r.get("drv_resp")
        if m is None:
            return (f'<span class="dv dv-n" title="حساسیت {cc:+.2f} · '
                    f'شتابِ محرک در دسترس نیست">{nm}</span>')
        cls = "dv-u" if (resp or 0) > 0 else "dv-d" if (resp or 0) < 0 else "dv-n"
        return (f'<span class="dv {cls}" title="{nm} در '
                f'{DRV_LOOK} روزِ گذشته {m:+.1f}٪ · حساسیتِ '
                f'اندازه‌گیری‌شدهٔ {r["sym"]} به آن {cc:+.2f} · '
                f'پاسخ = {m:+.1f} × {cc:+.2f} = {resp:+.2f}">'
                f'{nm} <b>{resp:+.1f}</b></span>')

    def reactcell(r, key):
        """سطحِ واکنش: کندلی که ناحیه را ساخته.

        مصطفی: «گاهی قیمت‌ها تا نزدیکیِ محدوده می‌آیند و واکنش
        می‌دهند به کندلی که به ناحیه در ارتباط هست.»

        اندازه‌گیری (`docs/35`) گفت کدام لبهٔ آن کندل: هفتگی
        **کلوز**، ماهانه **سقف**. پس همان برجسته می‌شود و دوتای
        دیگر در توضیحِ سلول می‌مانند.
        """
        rc = r.get("react_w" if key == "week" else "react_m")
        if not rc:
            return '<span class="sub">—</span>'
        main = "close" if key == "week" else "high"
        fa = {"low": "کف", "close": "کلوز", "high": "سقف"}
        lv = rc[main]
        px = r["close"] or 0
        d = (lv - px) / px * 100 if px else 0.0
        tipall = " · ".join(f"{fa[k]} {n(rc[k])}"
                            for k in ("low", "close", "high"))
        if abs(d) > REACT_MAX_DIST:
            return (f'<span class="sub" title="کندلِ {rc["date"]} — '
                    f'{tipall}. {abs(d):.0f}٪ دور است، پس نقشهٔ '
                    f'معامله نیست.">— <i>{d:+.0f}٪</i></span>')
        # زیرِ قیمت = حمایتی که ممکن است پولبک آنجا برگردد
        cls = "vl-u" if d <= 0 else "vl-d"
        tip = " · ".join(f"{fa[k]} {n(rc[k])}" for k in ("low", "close", "high"))
        return (f'<span class="vl {cls}" title="کندلِ {rc["date"]} — '
                f'{tip}. اندازه‌گیری‌شده برای این افق: '
                f'{fa[main]}">{n(lv)} <b>{d:+.1f}٪</b></span>')

    def kept(r):
        """نمادی که **داری** و هیچ شرطِ خروجی نخورده.

        «ما فقط در صورتی می‌فروشیم که زیرِ باکس بسته شود.» پس این
        ردیف در دفتر مانده نه چون رتبه‌اش بالا بوده، بلکه چون دلیلی
        برای فروختنش نیست. فیلترهای **ورود** (کهربا، ماهِ جاری،
        پهنای دسته) روی آن اعمال نمی‌شوند.
        """
        if not r.get("kept"):
            return ""
        return ('<span class="gate gate-mw" title="در پرتفو داری و '
                'هیچ شرطِ خروجی نخورده — حکمِ خلای حجمی «بالا»، '
                'بالای هر دو باکس، استاپ نخورده. فیلترهای ورود '
                'اینجا اعمال نمی‌شوند چون قاعدهٔ فروشِ تو «کلوزِ '
                'زیرِ باکس» است، نه «عقب‌بودن از کهربا».">'
                'نگه‌داشته</span>')

    def sigrow(i, r, key):
        z = r[key]
        nn, win, avg = wr(r, key)
        return (f'<tr data-s="{r["sym"]}" data-c="{r["cat"]}">'
                f'<td class="td">{i}</td>'
                f'<td class="td sym">{r["sym"]}{thin(r)}{kept(r)}'
                f'{gate(r)}</td>'
                f'<td class="td">{alarm(z, r.get(key[0] + "_dead"))}</td>'
                f'<td class="td n">{n(r["close"])}</td>'
                f'<td class="td n hi">{n(z["aim"])}</td>'
                f'<td class="td">{reactcell(r, key)}</td>'
                f'<td class="td n r">{n(z["stop"])}</td>'
                f'<td class="td n g">{n(z["target"])}</td>'
                f'<td class="td n">{z["risk_pct"]:.1f}٪</td>'
                f'<td class="td n">{btcell(nn, win, avg)}</td>'
                f'<td class="td">{bdg(r["mst"])}</td>'
                f'<td class="td">{bdg(r["wst"])}</td>'
                f'<td class="td">{vlevcell(r)}</td>'
                f'<td class="td">{drvcell(r)}</td>'
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
                1 if r.get(key[0] + "_dead") else 0,
                0 if in_band(r, key) else
                1 if r[key]["state"] == "زیر نوار" else 2,
                0 if r["value_bn"] >= MIN_VALUE_BN else 1,
                r[key]["risk_pct"]))
            hot = sum(1 for r in rs if in_band(r, key))
            liq = sum(1 for r in rs if r["value_bn"] >= MIN_VALUE_BN)
            out.append(
                f'<tr class="grp" data-c="{c}"><td class="td" colspan="15">'
                f'<span class="gname">{"بدون دسته" if c == "؟" else c}</span>'
                f'<span class="gmeta">{len(rs)} نماد · '
                f'<b class="g">{hot}</b> در نوار · '
                f'{liq} با حجمِ کافی</span></td></tr>')
            out += [sigrow(i, r, key) for i, r in enumerate(rs, 1)]
        return "".join(out)

    # ── تبِ محرک‌های جهانی ────────────────────────────────────────
    # مصطفی این را خواست: «بازارهای جهانی تأثیرپذیرش را مدّ نظر قرار
    # بده.» اندازه‌گیری شد و جوابش اینجاست — با عددش، نه با ادعا.
    def _drvbox():
        if not drv or not drv.get("ok"):
            return ('<div class="note">محرک‌ها خوانده نشدند'
                    f' ({drv.get("why") if drv else "—"}). رتبه‌بندیِ '
                    'دفتر فقط با مازادِ کهرباست.</div>')
        mom = drv.get("mom") or {}
        dts = drv.get("dates") or {}
        # چند نماد به هر محرک وصل است — بدونِ این، «نفت +۳٪» معلوم
        # نیست روی کدام ردیفِ دفتر اثر دارد.
        cnt = defaultdict(list)
        for r in rows:
            if r.get("drv"):
                cnt[r["drv"]].append(r["sym"])
        cards = []
        for k in sorted(mom, key=lambda k: -abs(mom[k])):
            m = mom[k]
            cls = "g" if m > 0 else "r" if m < 0 else ""
            who = cnt.get(k) or []
            ex = "، ".join(who[:4]) + (f" +{len(who) - 4}"
                                       if len(who) > 4 else "")
            cards.append(
                f'<div class="drvc"><div class="nm">'
                f'{k.replace("_", " ")}</div>'
                f'<div class="mv {cls}">{m:+.2f}٪</div>'
                f'<div class="sb">{DRV_LOOK} روزِ گذشته · '
                f'تا {dts.get(k, "—")}</div>'
                f'<div class="sb">{len(who)} نماد'
                + (f" — {ex}" if who else "") + '</div></div>')
        warn = ""
        if drv.get("stale"):
            warn = ('<div class="feebox">⚠️ دادهٔ محرک '
                    f'<b>{drv["lag"]} روز</b> از کلوزِ نمادها عقب است '
                    f'(محرک تا {drv["date"]}، نمادها تا {stamp}). '
                    'ستونِ «پاسخ» کهنه است. فایل‌های '
                    '<code>data/drivers_daily/</code> را از چارتیکس '
                    'دوباره export کن.</div>')
        return (warn + '<div class="drvgrid">' + "".join(cards)
                + '</div>')

    # ── نوارِ وضعیتِ بازار: شاخص کل و هم‌وزن ───────────────────────
    # در حالتِ سهام این «ملاکِ تصمیم‌گیری» است که مصطفی خواست. در
    # حالتِ صندوق هم بی‌ربط نیست — اهرمی‌ها با همین دو شاخص حرکت
    # می‌کنند. ولی در هیچ‌کدام **فیلتر نیست**: بند ۳ راهنما باکس روی
    # شاخص را فقط «سیگنالِ ریسک» می‌داند، و همان‌جا ماند.
    def _idxbox():
        reg = idx_regime()
        if not reg:
            return ""
        cards = []
        for nm, v in reg.items():
            cells = []
            for fa in ("ماهانه", "هفتگی", "دیلی"):
                h = v["hz"].get(fa)
                if not h:
                    cells.append(f'<span class="vl vl-n" title="{fa}: '
                                 f'باکسی ساخته نشد — درهٔ حجمی نبود">'
                                 f'{fa[0]} —</span>')
                    continue
                st, d, lo, hi, _px = h
                cl2 = ("vl-u" if st == "بالا" else
                       "vl-d" if st == "زیر" else "vl-i")
                txt = (f"{fa[0]} {d:+.1f}٪" if st != "داخل"
                       else f"{fa[0]} داخل")
                cells.append(
                    f'<span class="vl {cl2}" title="{fa}: {st} · '
                    f'باکس {n(lo)}–{n(hi)} از دورهٔ کامل‌شدهٔ قبل">'
                    f'{txt}</span>')
            dcl2 = "g" if v["d1"] >= 0 else "r"
            vg = v.get("vg") or {}
            vrow = ""
            if vg.get("حکم") not in (None, "؟"):
                vc = {"بالا": "vl-u", "زیر": "vl-d"}.get(vg["حکم"], "vl-i")
                parts = []
                for fa in ("ماهانه", "هفتگی", "دیلی"):
                    x = vg.get(fa)
                    if not x:
                        continue
                    c3 = ("vl-u" if x["verdict"] == "بالا"
                          else "vl-d" if x["verdict"] == "زیر"
                          else "vl-n" if x["verdict"] == "دور" else "vl-i")
                    parts.append(
                        f'<span class="vl {c3}" title="{fa}: ناحیهٔ '
                        f'{n(x["lo"])}–{n(x["hi"])} · کلوزِ روزِ تصمیم '
                        f'{n(x["dec"])} → {x["verdict"]}">'
                        f'{fa[0]} {x["verdict"]}</span>')
                vrow = ('<div class="sb" style="margin-top:6px">'
                        f'<span class="vl {vc}" title="حکمِ خلای حجمی '
                        f'بر اساسِ {vg.get("مبنا")}">خلای حجمی: '
                        f'<b>{vg["حکم"]}</b></span>' + "".join(parts)
                        + '</div>')
            cards.append(
                f'<div class="drvc"><div class="nm">{nm}</div>'
                f'<div class="mv {dcl2}">{n(v["px"])} '
                f'<span style="font-size:.8rem">{v["d1"]:+.2f}٪</span></div>'
                f'<div class="sb" style="margin-top:6px">{"".join(cells)}'
                f'</div>{vrow}<div class="sb">تا {v["date"]}</div></div>')
        lead = ('<b>ملاکِ تصمیم‌گیریِ این داشبورد.</b> '
                if STOCK else '<b>زمینهٔ بازار.</b> ')
        return ('<div class="note">' + lead
                + 'وضعیتِ شاخص نسبت به باکسِ دورهٔ کامل‌شدهٔ قبلِ خودش. '
                  '<b>این سیگنالِ ورود نیست</b> — بند ۳ راهنما باکس روی '
                  'شاخص را فقط «سیگنالِ ریسک» می‌داند و هیچ نمادی به '
                  'خاطرش حذف نمی‌شود. وقتی هر سه افق زیرند، اندازهٔ '
                  'پوزیشن را خودت کوچک کن؛ برنامه این کار را نمی‌کند.'
                  '</div><div class="drvgrid">' + "".join(cards)
                + '</div>')

    # ── تبِ «واحدِ کهربا» — هدفِ نهایی ─────────────────────────────
    # «تعدادِ واحدِ بیشترِ هر نماد نسبت به کهربا و مجموعِ همهٔ نمادها،
    # روزانه، هفتگی و ماهانه. این هدفِ غایی و نهاییِ من است.»
    def _unitbox():
        if not bu:
            return ('<div class="note">مبنا (کهربا) در این جهان نیست، '
                    'پس مازادِ واحد حساب نشد.</div>')
        dts = bu.get("dates") or {}
        port = bu.get("port") or {}

        def tile(fa, hz):
            v = port.get(hz)
            a = dts.get(hz)
            if v is None:
                return (f'<div class="stat"><div class="k">{fa}</div>'
                        f'<div class="v sub">—</div>'
                        f'<div class="s">دادهٔ کافی نیست</div></div>')
            cls = "g" if v > 0 else "r" if v < 0 else ""
            word = "جلو ▲" if v > 0 else "عقب ▼" if v < 0 else "هم‌پا"
            return (f'<div class="stat"><div class="k">{fa}</div>'
                    f'<div class="v {cls}">{v:+.2f}٪</div>'
                    f'<div class="s">{word}'
                    + (f' · از {a[0]}' if a else '') + '</div></div>')

        tiles = "".join(tile(fa, hz) for fa, hz in UNIT_HZ)

        def cell(v):
            if v is None:
                return '<td class="td n sub">—</td>'
            cls = "g" if v > 0 else "r" if v < 0 else ""
            return f'<td class="td n {cls}">{v:+.2f}٪</td>'

        def tbl(rs, head, empty):
            if not rs:
                return f'<h3>{head}</h3><div class="sub">{empty}</div>'
            body = "".join(
                f'<tr data-s="{r["sym"]}" data-c="{r["cat"]}">'
                f'<td class="td sym">{r["sym"]}'
                + ('<span class="gate gate-mw">مبنا</span>'
                   if r["self"] else "")
                + f'</td><td class="td">{r["cat"]}</td>'
                f'<td class="td n">{n(r["held"]) if r["held"] else "—"}</td>'
                + cell(r["d"]) + cell(r["w"]) + cell(r["m"])
                + f'<td class="td n">'
                + (f'{r["bx"]:+.1f}' if r.get("bx") is not None else "—")
                + '</td></tr>'
                for r in rs)
            # سرصفحه اینجا ساخته می‌شود نه با thead(): آن تابع
            # پایین‌تر در همین html() تعریف می‌شود و در این نقطه
            # هنوز وجود ندارد. (و پایتون ۳٫۱۱ رشتهٔ چندخطی داخلِ
            # f-string را هم نمی‌پذیرد.)
            cols = ("نماد", "دسته", "واحدِ من", "روزانه", "هفتگی",
                    "ماهانه", "مازادِ ۴۰ روزه")
            uh = "".join(
                f'<th class="th{" n" if i >= 3 else ""}">{c}</th>'
                for i, c in enumerate(cols))
            return (f'<h3>{head}</h3><div class="wrap">'
                    f'<table class="table"><thead><tr>{uh}'
                    f'</tr></thead><tbody>{body}</tbody></table></div>')

        mine = [r for r in bu["sym"] if r["held"]]
        rest = [r for r in bu["sym"] if not r["held"]][:40]
        warn = ""
        gone = set()
        for v in (bu.get("miss") or {}).values():
            gone |= set(v)
        if gone:
            warn = ('<div class="feebox">⚠️ قیمتِ <b>'
                    + "، ".join(sorted(gone))
                    + '</b> در این جهان نیست، پس از <b>مجموعِ پرتفو</b> '
                    'بیرون مانده — عددِ کل کم‌برآورد است. در حالتِ '
                    '<code>--all</code> یا اجرای آنلاین می‌آیند.</div>')
        return (
            '<div class="sub"><b>این عدد هدفِ نهایی است، نه بازدهِ '
            'ریالی.</b> اگر نمادی r<sub>s</sub> درصد رفته و کهربا '
            'r<sub>b</sub>، تعدادِ واحدِ کهرباىِ بیشتری که به تو داده '
            'برابر است با <code>(۱+r<sub>s</sub>) ÷ (۱+r<sub>b</sub>) '
            '− ۱</code>.'
            '<br>روزِ ' + (dts.get("d") or ["—"])[0] + ' → '
            + (dts.get("d") or ["—", "—"])[1] +
            ': سینرژی ‎+۵٫۴۰٪ و کهربا ‎+۰٫۴۰٪ بود، یعنی '
            '۱٫۰۵۴۰ ÷ ۱٫۰۰۴۰ − ۱ = <b class="g">+۴٫۹۸٪ واحدِ بیشتر</b>.'
            '<br>لنگرِ <b>هفتگی</b> آخرین کلوزِ هفتهٔ کامل‌شدهٔ قبل است و '
            'لنگرِ <b>ماهانه</b> آخرین کلوزِ ماهِ میلادیِ قبل — نه «۵ روز '
            'پیش» و «۳۰ روز پیش». بند ۲ راهنما تصمیم را روی همین مرزها '
            'می‌گذارد، پس سنجش هم همان‌جاست. در <b>اولین جلسهٔ هفته</b> '
            'عددِ روزانه و هفتگی یکی می‌شوند و این درست است.'
            '<br>ستونِ <b>مازادِ ۴۰ روزه</b> همان معیاری است که '
            'رتبه‌بندیِ دفتر روی آن بسته می‌شود — «میانگینِ بازدهیِ '
            'گذشتهٔ آن نماد» که خواستی.</div>'
            + warn
            + '<h3>مجموعِ پرتفو در برابرِ ' + BENCH + '</h3>'
            + f'<div class="stats">{tiles}</div>'
            + UNIT_BT
            + tbl(mine, "نمادهای پرتفوی من",
                  "هیچ نمادی از پرتفو در این جهان نیست.")
            + tbl(rest, "بقیهٔ جهان — ۴۰ نمادِ برترِ روزانه", "—"))

    # ── تبِ ۰: تصمیمِ امروز ────────────────────────────────────────
    # مصطفی: «چرا نصفه کار می‌کنی؟ اگر نمادی خلا حجمی را شکسته، یا
    # نمادی حد ضرر خورده، یا خریدی باید به پرتفو اضافه کنم را هر روز
    # باید نشان بدهی.»
    #
    # حق دارد. این سه چیز در سه تبِ مختلف بودند و هیچ‌جا یک فهرستِ
    # «امروز چه کار کنم» نبود. اینجا همه‌چیز در **یک** صفحه، به
    # ترتیبِ اجرا: اول فروش، بعد خرید (بند ۲ راهنما).
    def _todaybox():
        blocks = []

        # ۱ ── چه چیزی امروز عوض شد ────────────────────────────────
        if dif is None or not dstamp:
            blocks.append(
                '<div class="note"><b>عکسِ دیروز موجود نیست</b>، پس '
                '«چه چیزی امروز عوض شد» قابلِ محاسبه نیست. این با '
                '«هیچ تغییری نبود» یکی نیست. از اجرای بعد این بخش '
                'پر می‌شود — وضعیتِ امروز همین حالا در '
                '<code>data_bourse/state.json</code> ذخیره شد.</div>')
        elif not dif:
            blocks.append(
                f'<div class="note">از {dstamp} تا {stamp} '
                '<b>هیچ نمادی</b> وضعیتش عوض نشد — نه شکستِ ناحیه، '
                'نه استاپ، نه ورود یا خروج از دفتر.</div>')
        else:
            mine, world = diff_split(dif, book)
            urgent = [e for e in mine if e["pri"] <= 1]
            rest = [e for e in mine if e["pri"] > 1]
            world = world[:40]

            def evrow(e):
                pc = (((e["close"] / e["was"]) - 1) * 100
                      if e.get("was") else None)
                cls = {"r": "b-r", "g": "b-g", "y": "b-y"}[e["col"]]
                return (
                    f'<tr data-s="{e["sym"]}" data-c="{e["cat"]}">'
                    f'<td class="td sym">{e["sym"]}'
                    + ('<span class="gate gate-mw">داری</span>'
                       if e["held"] else "")
                    + f'</td><td class="td">'
                    f'<span class="badge {cls}" title="{e["why"]}">'
                    f'{e["lab"]}</span></td>'
                    f'<td class="td n">{n(e["close"])}</td>'
                    f'<td class="td n">'
                    + ("—" if pc is None else
                       f'<span class="{"g" if pc >= 0 else "r"}">'
                       f'{pc:+.2f}٪</span>')
                    + '</td><td class="td n">'
                    + (n(e["units"]) if e["units"] else "—")
                    + '</td></tr>')

            eh = "".join(f'<th class="th{" n" if i >= 2 else ""}">{c}</th>'
                         for i, c in enumerate(
                             ("نماد", "چه شد", "کلوز", "تغییر", "واحدِ من")))

            def evtbl(rs, head, cls=""):
                if not rs:
                    return ""
                return (f'<h3{cls}>{head}</h3><div class="wrap">'
                        f'<table class="table"><thead><tr>{eh}</tr></thead>'
                        f'<tbody>{"".join(evrow(e) for e in rs)}'
                        f'</tbody></table></div>')

            blocks.append(
                f'<div class="sub">مقایسه با آخرین اجرا '
                f'(<b>{dstamp}</b> → <b>{stamp}</b>). فقط چیزهایی که '
                f'<b>عوض شده‌اند</b> اینجا می‌آیند — نمادی که سه هفته '
                f'است زیرِ ناحیه است امروز چیزی را نشکسته.</div>'
                + ('' if (urgent or rest) else
                   '<div class="note">روی نمادهای <b>من</b> و '
                   '<b>دفتر</b> هیچ تغییری نبود.</div>')
                + evtbl(urgent, "⛔ فوری — نمادهای من و دفتر")
                + evtbl(rest, "تغییرات روی نمادهای من و دفتر")
                + evtbl(world, "بقیهٔ جهان — فقط خبر، نه کار"))

        # ۲ ── بفروش ───────────────────────────────────────────────
        srows = []
        for sym, px2, which, u in sell:
            srows.append(
                f'<tr><td class="td sym">{sym}</td>'
                f'<td class="td"><span class="badge b-r">🔄 عوض کن'
                f'</span></td><td class="td n">{n(px2)}</td>'
                f'<td class="td n">{n(u)}</td>'
                f'<td class="td">کلوز زیرِ باکسِ {which}</td></tr>')
        for x in sells:
            srows.append(
                f'<tr><td class="td sym">{x["sym"]}</td>'
                f'<td class="td"><span class="badge b-y">کم کن</span>'
                f'</td><td class="td n">{n(x["px"])}</td>'
                f'<td class="td n">{n(x["units"])}</td>'
                f'<td class="td">رسیدن به وزنِ هدف · '
                f'{n(x["amt"] / 1e6)} م.ر</td></tr>')
        sh = "".join(f'<th class="th{" n" if i in (2, 3) else ""}">{c}</th>'
                     for i, c in enumerate(
                         ("نماد", "کار", "قیمت", "واحد", "چرا")))
        blocks.append(
            '<h3>۱ — اول بفروش</h3>'
            + ('<div class="sub">امروز فروشی نیست.</div>' if not srows
               else f'<div class="wrap"><table class="table"><thead>'
                    f'<tr>{sh}</tr></thead><tbody>{"".join(srows)}'
                    f'</tbody></table></div>'))

        # ۳ ── بخر ─────────────────────────────────────────────────
        brows = []
        for x in buys:
            r0 = next((b for b in book
                       if norm(b["sym"]) == norm(x["sym"])), None)
            z = (r0 or {}).get("z") or {}
            tag = "جدید" if x["new"] else "اضافه کن"
            cls = "b-g" if x["new"] else "b-y"
            brows.append(
                f'<tr data-s="{x["sym"]}"><td class="td sym">{x["sym"]}'
                f'</td><td class="td"><span class="badge {cls}">'
                f'🟢 {tag}</span></td>'
                f'<td class="td n">{n(x["px"])}</td>'
                f'<td class="td n">{n(x["units"])}</td>'
                f'<td class="td n">{n(x["amt"] / 1e6)}</td>'
                f'<td class="td n hi">'
                + (n(z["aim"]) if z.get("aim") else "—")
                + '</td><td class="td n r">'
                + (n(z["stop"]) if z.get("stop") else "—")
                + '</td><td class="td n">'
                + (f'{z["risk_pct"]:.1f}٪' if z.get("risk_pct") else "—")
                + '</td></tr>')
        bh = "".join(f'<th class="th{" n" if i >= 2 else ""}">{c}</th>'
                     for i, c in enumerate(
                         ("نماد", "کار", "قیمت", "واحد", "مبلغ (م.ر)",
                          "نقطهٔ ورود", "حدضرر", "ریسک")))
        blocks.append(
            '<h3>۲ — بعد بخر</h3>'
            '<div class="sub">بند ۲ راهنما: پولِ آزادشدهٔ فروش منبعِ '
            'خریدِ همان صبح است.</div>'
            + ('<div class="sub">امروز خریدی نیست.</div>' if not brows
               else f'<div class="wrap"><table class="table"><thead>'
                    f'<tr>{bh}</tr></thead><tbody>{"".join(brows)}'
                    f'</tbody></table></div>'))

        # ۴ ── دست نزن ─────────────────────────────────────────────
        touched = {norm(x["sym"]) for x in list(sells) + list(buys)}
        keep = [r for r in book
                if norm(r["sym"]) not in touched and r.get("kept")]
        if keep:
            blocks.append(
                '<h3>۳ — دست نزن</h3><div class="sub">این‌ها را '
                '<b>داری</b>، هیچ شرطِ خروجی نخورده‌اند و وزنشان هم '
                'درست است. «ما فقط در صورتی می‌فروشیم که زیرِ باکس '
                'بسته شود.»<br>'
                + "، ".join(f'<b>{r["sym"]}</b>' for r in keep)
                + '</div>')
        if nopx:
            blocks.append(
                f'<div class="feebox">⚠️ قیمتِ <b>{"، ".join(nopx)}</b> '
                f'در این جهان نیست، پس در هیچ‌کدام از فهرست‌های بالا '
                f'نیستند و تکلیفشان <b>روشن نشده</b>. با '
                f'<code>--all</code> یا اجرای آنلاین می‌آیند.</div>')
        return "".join(blocks)

    # ── سبدِ هفتگی در برابرِ سبدِ ماهانه ───────────────────────────
    # «پرتفو هدف … بر اساس هفتگی و ماهانه». بند ۲ راهنما سه سبد
    # تعریف می‌کند (دیلی ۱۰٪ · هفتگی ۳۰٪ · هستهٔ ماهانه ۶۰٪) ولی
    # دفتر این سهم‌ها را **تحمیل نمی‌کند** — باندِ هر نماد بر اساسِ
    # سالم بودنِ استاپش انتخاب می‌شود. پس عددِ واقعی را نشان می‌دهم
    # و کنارش عددِ بند ۲ را، تا فاصله دیده شود نه پنهان.
    def _bandbox():
        if not book:
            return ""
        g = {"week": [], "month": []}
        for r in book:
            g.setdefault(r.get("band", "week"), []).append(r)
        tot = sum(r["w"] for r in book) or 1.0

        def part(key, fa, target, note):
            rs = g.get(key) or []
            if not rs:
                return (f'<div class="drvc"><div class="nm">{fa}</div>'
                        f'<div class="mv sub">—</div>'
                        f'<div class="sb">هیچ قلمی روی این نوار نیست'
                        f'</div></div>')
            w = sum(r["w"] for r in rs)
            names = "، ".join(r["sym"] for r in rs)
            gap = w - target
            cls = "g" if abs(gap) <= 10 else "r"
            return (f'<div class="drvc"><div class="nm">{fa}</div>'
                    f'<div class="mv">{w:.0f}٪</div>'
                    f'<div class="sb">بند ۲ می‌گوید <b>{target:.0f}٪</b> '
                    f'· <span class="{cls}">{gap:+.0f} واحد</span></div>'
                    f'<div class="sb" style="margin-top:6px">'
                    f'{len(rs)} قلم — {names}</div>'
                    f'<div class="sb">{note}</div></div>')

        return (
            '<div class="sub"><b>سبدِ هفتگی و سبدِ ماهانه.</b> باندِ هر '
            'نماد خودکار انتخاب می‌شود: نوارِ هفتگی اگر ریسکش دستِ‌کم '
            '۱٪ باشد، وگرنه نوارِ ماهانه — چون باکسِ هفتگی میانهٔ '
            'پهنایش ۱٫۴۲٪ است و دامنهٔ یک روز ۲٫۶۲٪، پس استاپِ هفتگیِ '
            'زیر ۱٪ داخلِ نویزِ یک کندل می‌نشیند.'
            '<br>⚠️ <b>سهم‌های بند ۲ تحمیل نمی‌شوند.</b> آن بند '
            'دیلی ۱۰٪ · هفتگی ۳۰٪ · هستهٔ ماهانه ۶۰٪ می‌گوید؛ دفتر '
            'وزن را از رتبه‌بندی می‌گیرد نه از سبد. فاصله‌اش اینجا '
            'دیده می‌شود. اگر می‌خواهی تحمیل شود بگو — قابلِ اضافه '
            'کردن است، ولی <b>اندازه‌گیری نشده</b> و هر قیدی که تا '
            'حالا تست شد از کهربا عقب انداخت (docs/32).</div>'
            '<div class="drvgrid">'
            + part("month", "نوارِ ماهانه", 60.0,
                   "تا پایانِ ماهِ میلادی ثابت است")
            + part("week", "نوارِ هفتگی", 30.0,
                   "تا ۷ روزِ دیگر ثابت است")
            + '</div>')

    # ── بنرِ آلارم، بالای همه‌چیز ──
    def _albox():
        if not buy and not sell:
            return ('<div class="alarm quiet">🔕 امروز نه آلارمِ خرید '
                    'هست نه فروش.</div>')
        rowsh = []
        for sym, px, which, units in sell:
            rowsh.append(
                f'<div class="al al-s"><b>🔄 عوض کن — {sym}</b>'
                f'<span>کلوز {n(px)} زیرِ باکسِ {which} · '
                f'{units:,} واحد داری — <b>نقد نشو</b>، ببر روی '
                f'نمادی که بالای باکسش است</span></div>')
        for sym, aim, stop, risk, tier in buy:
            tag = "" if tier == 1 else " · نیمه‌سیگنال"
            rowsh.append(
                f'<div class="al al-b"><b>🟢 بخر — {sym}</b>'
                f'<span>ورود {n(aim)} · استاپ {n(stop)} · '
                f'ریسک {risk:.1f}٪{tag}</span></div>')
        return f'<div class="alarm">{"".join(rowsh)}</div>'

    alarm_box = _albox()
    drv_box = _drvbox()
    idx_box = _idxbox()
    DRVN = (drv or {}).get('n', 0)

    # ── قطب‌نما ───────────────────────────────────────────────────
    # شکل از کارِ داده می‌آید: یک عددِ سرخط (مازادِ امروز) + یک سری
    # زمانی تک‌خطی. سری تک‌خطی است، پس راهنمای رنگ لازم ندارد —
    # عنوان خودش نامش را می‌گوید.
    #
    # رنگ اینجا **وضعیت** است نه دسته‌بندی (جلو/عقب)، و قاعدهٔ رنگِ
    # وضعیت این است که هیچ‌وقت تنها حاملِ معنا نباشد. پس کنارِ هر
    # عددِ سبز یا قرمز، کلمه و جهت هم می‌آید: «جلو ▲» / «عقب ▼».
    def _compass():
        if not comp:
            return ""
        ex, rial = comp["excess_pct"], comp["excess_rial"]
        up = ex >= 0
        cls = "g" if up else "r"
        word = "جلو" if up else "عقب"
        arrow = "▲" if up else "▼"
        if comp["first_day"]:
            return (f'<div class="compass"><div class="cmp-h">'
                    f'قطب‌نما — در برابرِ {BENCH}</div>'
                    f'<div class="sub">امروز روزِ <b>لنگر</b> است '
                    f'({comp["date"]}). کلِ پرتفو امروز '
                    f'<b>{n(comp["units_base"])} واحدِ {BENCH}</b> است — '
                    f'سؤال از فردا این است که این عدد بیشتر می‌شود یا '
                    f'کمتر. سرمایهٔ مبنا '
                    f'{n(comp["base_capital"] / 1e9, 1)} میلیارد ریال · '
                    f'{BENCH} {n(comp["base_bench_px"])} ریال.<br>'
                    f'عددِ مازاد از <b>فردا</b> معنا پیدا می‌کند — امروز '
                    f'صفر است و باید صفر باشد.</div></div>')

        # ── نمودار: خطِ مازادِ تجمعی، با خطِ صفرِ مرجع ──────────────
        pts = [float(r["excess_pct"]) for r in comp["hist"]
               if r.get("excess_pct")]
        spark = ""
        if len(pts) >= 2:
            # نسبتِ viewBox نزدیکِ نسبتِ واقعیِ جعبه باشد وگرنه
            # preserveAspectRatio وسط‌چین می‌کند و نمودار باریک می‌ماند.
            W, H, PAD = 1200, 120, 26
            lo, hi = min(pts + [0.0]), max(pts + [0.0])
            rng = (hi - lo) or 1.0
            xs = [PAD + i * (W - 2 * PAD) / (len(pts) - 1)
                  for i in range(len(pts))]
            ys = [H - PAD - (v - lo) / rng * (H - 2 * PAD) for v in pts]
            zy = H - PAD - (0.0 - lo) / rng * (H - 2 * PAD)
            line = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}"
                            for i, (x, y) in enumerate(zip(xs, ys)))
            area = (line + f" L{xs[-1]:.1f},{zy:.1f} "
                    f"L{xs[0]:.1f},{zy:.1f} Z")
            col = "var(--green)" if up else "var(--red)"
            dots = "".join(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7" fill="transparent">'
                f'<title>{comp["hist"][i]["date"]}: {v:+.2f}٪</title>'
                f'</circle>'
                for i, (x, y, v) in enumerate(zip(xs, ys, pts)))
            spark = (
                f'<svg class="spark" viewBox="0 0 {W} {H}" '
                f'role="img" aria-label="مازادِ تجمعی نسبت به {BENCH}">'
                f'<path d="{area}" fill="{col}" opacity=".13"/>'
                f'<line x1="{PAD}" y1="{zy:.1f}" x2="{W - PAD}" '
                f'y2="{zy:.1f}" stroke="var(--muted)" stroke-width="1" '
                f'stroke-dasharray="3 3"/>'
                f'<path d="{line}" fill="none" stroke="{col}" '
                f'stroke-width="2" stroke-linejoin="round" '
                f'stroke-linecap="round"/>'
                f'<circle cx="{xs[-1]:.1f}" cy="{ys[-1]:.1f}" r="4.5" '
                f'fill="{col}" stroke="var(--card)" stroke-width="2"/>'
                # برچسبِ انتخابی: فقط بیشینه، کمینه و نقطهٔ آخر —
                # نه عدد روی هر نقطه.
                f'<text x="{PAD}" y="{PAD - 9}" class="sv" direction="ltr">'
                f'{hi:+.1f}٪</text>'
                f'<text x="{PAD}" y="{H - 7}" class="sv" direction="ltr">'
                f'{lo:+.1f}٪</text>'
                f'<text x="{xs[-1]:.1f}" y="{max(15, ys[-1] - 13):.1f}" '
                f'class="sv se" direction="ltr" text-anchor="end">'
                f'{pts[-1]:+.2f}٪</text>'
                f'{dots}</svg>'
                f'<div class="sub sprk-l"><span>صفر = هم‌پای {BENCH}</span>'
                f'<span>{comp["hist"][0]["date"]} → '
                f'{comp["hist"][-1]["date"]}</span></div>')

        sd = ("" if comp["sd"] is None else
              f'<div class="stat"><div class="k">انحرافِ معیارِ روزانه</div>'
              f'<div class="v">{comp["sd"]:.2f}</div>'
              f'<div class="d">واحدِ درصد · پراکندگیِ مازاد</div></div>')
        dex = comp["day_pct"] - comp["day_bench_pct"]
        return (
            f'<div class="compass"><div class="cmp-h">'
            f'قطب‌نما — در برابرِ {BENCH} · از {comp["base_date"]} '
            f'({comp["days"]} روز)</div>'
            f'<div class="stats cmp-s">'
            f'<div class="stat"><div class="k">واحدِ {BENCH}</div>'
            f'<div class="v {cls}" dir="ltr">'
            f'{comp["units_d"]:+,.0f}</div>'
            f'<div class="d">{word} · '
            f'{n(comp["units_base"])} ← {n(comp["units_now"])} واحد '
            f'({comp["units_pct"]:+.2f}٪)</div></div>'
            f'<div class="stat"><div class="k">مازادِ ریالی</div>'
            f'<div class="v {cls}" dir="ltr">{ex:+.2f}٪ {arrow}</div>'
            f'<div class="d">{word} · {n(rial / 1e6)} میلیون ریال</div></div>'
            f'<div class="stat"><div class="k">سود/زیانِ امروز</div>'
            f'<div class="v {"g" if comp["day_pnl"] >= 0 else "r"}" dir="ltr">'
            f'<span dir="ltr">{n(comp["day_pnl"] / 1e6)}</span></div>'
            f'<div class="d">میلیون ریال · {comp["day_pct"]:+.2f}٪ '
            f'({dex:+.2f} واحد نسبت به {BENCH})</div></div>'
            f'<div class="stat"><div class="k">پرتفو</div>'
            f'<div class="v">{n(comp["port"] / 1e9, 1)}</div>'
            f'<div class="d">میلیارد ریال · {comp["port_pct"]:+.2f}٪ '
            f'از لنگر</div></div>'
            f'<div class="stat"><div class="k">{BENCH} (مبنا)</div>'
            f'<div class="v">{n(comp["bench"] / 1e9, 1)}</div>'
            f'<div class="d">میلیارد ریال · {comp["bench_pct"]:+.2f}٪ '
            f'از لنگر</div></div>{sd}</div>{spark}</div>')

    compass_box = _compass()

    def _orders():
        """دقیقاً چه بفروش و چه بخر — با مبلغ، نه فقط تعداد."""
        if not sells and not buys:
            return ('<div class="sub">سبدِ فعلی با سبدِ هدف یکی است — '
                    'کاری لازم نیست.</div>')
        def tbl(rows_, kind):
            if not rows_:
                return ""
            head = "▼ فروش" if kind == "s" else "▲ خرید"
            tot = sum(x["amt"] for x in rows_)
            body = "".join(
                f'<tr><td class="td sym">{x["sym"]}'
                + ('<span class="gate gate-ok">کلِ موجودی</span>'
                   if kind == "s" and x["all"] else
                   '<span class="gate gate-ok">جدید</span>'
                   if kind == "b" and x.get("new") else "")
                + f'</td><td class="td n">{n(x["units"])}</td>'
                f'<td class="td n">{n(x["px"])}</td>'
                f'<td class="td n {"r" if kind == "s" else "g"}">'
                f'<b>{n(x["amt"] / 1e6)}</b></td></tr>'
                for x in rows_)
            return (f'<h3>{head}</h3><div class="wrap"><table class="table">'
                    f'<thead><tr><th class="th">نماد</th>'
                    f'<th class="th n">واحد</th><th class="th n">قیمت</th>'
                    f'<th class="th n">مبلغ (میلیون ریال)</th></tr></thead>'
                    f'<tbody>{body}<tr class="dim"><td class="td sym">جمع'
                    f'</td><td class="td"></td><td class="td"></td>'
                    f'<td class="td n"><b>{n(tot / 1e6)}</b></td></tr>'
                    f'</tbody></table></div>')
        warn = ("" if not nopx else
                f'<div class="feebox">⚠️ قیمتِ '
                f'<b>{"، ".join(nopx)}</b> پیدا نشد، پس در این فهرست '
                f'نیستند. این‌ها سهم‌اند نه صندوق؛ در اجرای آنلاین '
                f'قیمتشان گرفته می‌شود. تا آن موقع تکلیفشان روشن '
                f'نیست.</div>')
        return (warn + f'<div class="sub"><b>ترتیب: اول فروش، بعد خرید.</b> '
                f'بند ۲ راهنما — پولِ آزادشده منبعِ خریدِ همان صبح است. '
                f'مبلغ‌ها به قیمتِ کلوزِ {stamp} است؛ در پیش‌گشایش '
                f'تعداد را با قیمتِ همان لحظه دوباره حساب کن.'
                f'<br>بعد از اجرای واقعی یک بار '
                f'<code>python bourse.py --adopt</code> را بزن تا قطب‌نما '
                f'از فردا همین سبد را دنبال کند.</div>'
                + _turnbox() + tbl(sells, "s") + tbl(buys, "b"))

    def _turnbox():
        """هزینهٔ گردش، **قبل از** اجرا.

        قاعدهٔ انتخاب هیسترزیس ندارد؛ نمادی که از رتبهٔ ۶ به ۷ بیفتد
        کاملاً فروخته می‌شود. بک‌تست همین است و هزینهٔ گردش در عددش
        هست (`cost × Σ|Δw| / 2`) — ولی روی کاغذ دیده نمی‌شد.
        """
        sv = sum(x["amt"] for x in sells)
        bv = sum(x["amt"] for x in buys)
        if not (sv or bv) or capital <= 0:
            return ""
        fee = (COST_STOCK if STOCK else COST_FUND)
        cost_r = (sv + bv) * fee / 2 / 100
        tr = (sv + bv) / capital * 100
        big = ('<br>⚠️ <b>این یک چرخشِ کامل است.</b> اگر بخشی از فروش '
               'و خرید در <b>یک دسته</b>\u200cاند، داری کارمزد می‌دهی تا '
               'همان ریسک را نگه داری. قاعدهٔ انتخاب عمداً هیسترزیس '
               'ندارد و بک‌تست هم همین‌طور بسته شده — ولی تصمیمِ '
               'اجرا با توست.' if tr > 120 else "")
        cls = "feebox" if tr > 120 else "note"
        return (f'<div class="{cls}">گردشِ امروز <b>{n(tr, 0)}٪</b> '
                f'سرمایه ({n((sv + bv) / 1e6)} میلیون ریال). کارمزدش '
                f'~<b>{n(cost_r / 1e6)}</b> میلیون ریال = '
                f'<b>{cost_r / capital * 100:.2f}٪</b> سرمایه، با '
                f'{fee}٪ رفت‌وبرگشت.{big}</div>')

    orders_box = _orders()

    def _positions():
        """پوزیشن‌های فعلی — حد ضرر و حد سود، آپدیتِ هر روز."""
        if not pos:
            return '<div class="sub">سبدی ثبت نشده است.</div>'
        hit = [x for x in pos if x["below"]]
        top = ""
        if hit:
            names = "، ".join(x["sym"] for x in hit)
            top = ('<div class="feebox">⛔ <b>کندلِ دیلی زیرِ ناحیه '
                   f'بسته: {names}</b> — فردا فروشنده‌ایم.<br>'
                   'اندازه‌گیری (۳٬۴۱۲ رویداد): صبر تا فردا ۰٫۱۹ واحد و '
                   'صبر برای پولبک ۰٫۳۰ واحد بدتر از خروجِ همین امروز '
                   'است. ولی خروج <b>چرخش</b> است نه نقد شدن — زیرِ کفِ '
                   'باکس بازدهِ ۵ روزِ بعد ‎+۰٫۲۲٪ است، یعنی صفر، نه '
                   'منفی.</div>')
        rows_ = "".join(
            '<tr data-s="{sym}" data-c="{cat}">'
            '<td class="td sym">{sym}{mk}</td>'
            '<td class="td n">{u}</td><td class="td n">{px}</td>'
            '<td class="td n r">{lo}</td>'
            '<td class="td n {dc}">{ds:+.1f}٪</td>'
            '<td class="td n g">{tg}</td>'
            '<td class="td n">{bx}</td></tr>'.format(
                sym=x["sym"], cat="",
                mk=('<span class="gate">⛔ زیرِ ناحیه</span>'
                    if x["below"] else ""),
                u=n(x["units"]), px=n(x["px"]), lo=n(x["zone_lo"]),
                dc="r" if x["below"] else "g", ds=x["dist_stop"],
                tg=(f'{n(x["flag"]["target"])} '
                    f'<span class="sub">({x["flag"]["up_pct"]:+.0f}٪ · '
                    f'{x["flag"]["scale"]})</span>' if x["flag"]
                    else '<span class="sub">شکستِ ناحیه</span>'),
                bx=("—" if x.get("bx") is None
                    else f'<b class="{"g" if x["bx"] >= 0 else "r"}">'
                         f'{x["bx"]:+.0f}</b>'))
            for x in pos)
        return (top + '<div class="sub"><b>حد سود دو اصل دارد.</b> '
                '۱) <b>شکستِ ناحیه</b> — همان حد ضرر؛ برای پوزیشنی که '
                'در سود است، خروج روی شکستِ ناحیه یعنی سیو سود. '
                '۲) <b>تارگتِ میله و پرچم</b>، اگر هنوز نخورده باشد. '
                'تارگتِ ۱:۱ عمداً اینجا نیست: از نوارِ <i>ورود</i> حساب '
                'می‌شود و برای پوزیشنی که از نوار گذشته عددی پشتِ سر '
                f'است.<br>ستونِ آخر مازادِ {BENCH_LOOK} روزه نسبت به '
                f'{BENCH} است — منفی یعنی این قلم از مبنا عقب است.'
                '</div>'
                '<div class="wrap"><table class="table"><thead><tr>'
                '<th class="th">نماد</th><th class="th n">واحد</th>'
                '<th class="th n">کلوز</th><th class="th n">حد ضرر</th>'
                '<th class="th n">فاصله</th>'
                '<th class="th n">حد سود (پرچم)</th>'
                f'<th class="th n">در برابرِ {BENCH}</th>'
                f'</tr></thead><tbody>{rows_}</tbody></table></div>')

    positions_box = _positions()

    def _risk():
        if not rr or rr.get("port_risk") is None:
            return ""
        w2 = rr.get("worst")
        c2 = rr.get("conc")
        tiles2 = [
            ("اگر همهٔ استاپ‌ها بخورند", f'{rr["port_risk"]:.2f}٪',
             f'{n(rr["rial"] / 1e6)} میلیون ریال', "r"),
        ]
        if w2:
            tiles2.append(
                ("سنگین‌ترین قلم", w2["sym"],
                 f'وزنِ {w2["w"]:.0f}٪ × ریسکِ '
                 f'{w2["z"]["risk_pct"]:.1f}٪ = '
                 f'{w2["w"] * w2["z"]["risk_pct"] / 100:.2f}٪', ""))
        if c2:
            tiles2.append(("تمرکز", f'{c2[1]:.0f}٪',
                           f'در دستهٔ «{c2[0]}»',
                           "r" if c2[1] >= 60 else ""))
        if rr.get("dd") is not None and rr.get("dd_n", 0) >= 3:
            tiles2.append(("بیشینه افتِ واقعی", f'{rr["dd"]:.1f}٪',
                           f'{rr["dd_n"]} روز تاریخچه', "r"))
        body = "".join(
            f'<div class="stat"><div class="k">{k}</div>'
            f'<div class="v {cl2}" dir="ltr">{v}</div>'
            f'<div class="d">{d2}</div></div>'
            for k, v, d2, cl2 in tiles2)
        return (f'<div class="stats">{body}</div>'
                '<div class="feebox">⚠️ <b>هیچ قیدِ ریسکی تحمیل نشده، و '
                'دلیلش اندازه‌گیری است.</b> سه شکلِ استانداردِ ریسک '
                'منیجر روی ۳۵ هفته سنجیده شد و هر سه ضرر دادند '
                '(معیار: واحدِ کهربا، هولدِ کهربا = ۱٫۰۰):<br>'
                '· وزن‌دهیِ وارونِ ریسک: ۱٫۱۵۲ → ۱٫۰۳۴<br>'
                '· سقفِ ریسکِ هر نماد ۵٪: ۱٫۱۵۲ → ۰٫۸۱۳<br>'
                '· سقفِ ریسکِ کلِ سبد ۵٪: ۱٫۱۵۲ → ۱٫۰۴۵ — و بیشینه افت '
                'از ‎−۷٫۲٪ به ‎−۹٫۵٪ <b>بدتر</b> شد.<br>'
                'آخری غیرشهودی است: سقف پول را می‌برد روی کهربا، و '
                'کهربا در این پنجره افتِ بیشتری از سبدِ شش‌تایی داشت. '
                'یعنی «کم کردنِ ریسک» با این تعریف ریسکِ واقعی را زیاد '
                'کرد. با <code>--risk-cap N</code> می‌شود تحمیلش کرد.'
                '</div>')

    risk_box = _risk()

    UNIV = "سهامِ بورس" if STOCK else "صندوق‌های ETF"
    BTSRC = (f"از خودِ همین {len(ok_rows)} سهم ساخته شد، در همین اجرا."
             if STOCK else "۱۲۱ صندوق، ۴۲ هفته و ۱۱ ماه.")
    SRC = ("<b>در این صفحه جدول از خودِ همین سهام ساخته شده</b>، "
           "نه از صندوق‌ها — وگرنه آمارِ یک جهان کنارِ جهانِ دیگر "
           "می‌نشست. p هر سطر در خروجیِ ترمینال چاپ می‌شود."
           if STOCK else
           "منبعش بک‌تستِ ۱۲۱ صندوق روی ۴۲ هفته و ۱۱ ماه است.")
    # ⚠️ مهم‌ترین جملهٔ این صفحه در حالتِ سهام. بند ۹ راهنما:
    # «اعداد بازده سالانه با ۰٫۵۵٪ رفت‌وبرگشت حساب شده‌اند. با کارمزد
    # واقعی سهام (~۱٫۲٪) شاراک و سقاین هم منفی می‌شوند. مزیت روی
    # صندوق اهرمی محکم است و روی سهام نازک.»
    FEEBOX = ("" if not STOCK else
              '<div class="feebox">⚠️ <b>کارمزدِ سهام ~۱٫۲٪ '
              'رفت‌وبرگشت است، بیش از دو برابرِ صندوق (۰٫۵۵٪).</b> '
              'مزیتِ این استراتژی روی سهام <b>نازک</b> است و این '
              'کارمزد می‌تواند کلش را بخورد — بند ۹ راهنما. '
              'ستونِ «بک‌تستِ وضعیت» بازدهِ <b>ناخالص</b> است؛ برای '
              'هر رفت‌وبرگشت ۱٫۲ واحد از آن کم کن. سطری که مزیتش '
              'زیرِ ۱٫۲ واحد است، بعد از کارمزد چیزی نمی‌ماند.'
              '<br><br>و حالا عددش هم هست (<code>docs/34</code>). '
              'همین چرخش روی ۷۷ صندوقِ سهامی، ۳۵ هفته، معیارِ '
              '<b>هولدِ شاخص کل = ۱٫۰۰</b>:'
              '<br>&nbsp;&nbsp;کارمزدِ ۰٪ → <b class="g">۱٫۱۸۲</b>'
              '&nbsp;·&nbsp; ۰٫۵۵٪ (صندوق) → <b class="g">۱٫۰۷۵</b>'
              '&nbsp;·&nbsp; ۱٫۲۰٪ (سهام) → <b class="r">۰٫۹۵۹</b>'
              '&nbsp;·&nbsp; ۲٪ → <b class="r">۰٫۸۳۴</b>'
              '<br>نقطهٔ سربه‌سر حدودِ <b>۰٫۸–۰٫۹٪</b> است و گردش '
              'حدودِ ۱٫۵ در هفته. در هر چهار حالت قاعده از '
              '<b>ترتیبِ تصادفی</b> جلوتر است — یعنی مهارت واقعی '
              'است و آنچه می‌بازد به <b>کارمزد</b> می‌بازد نه به '
              'تصادف. نتیجهٔ عملی: اگر همین قاعده را می‌خواهی، از '
              'راهِ <b>صندوق</b> اجرا کن نه از راهِ سهام.'
              '<br><br>⚠️ این روی صندوق‌های سهامی اندازه‌گیری شده، نه '
              'روی خودِ سهام — دادهٔ سهام در مخزن نیست. پروکسی است، '
              'نه خودِ جهان.</div>')

    # بعد از thead، چون جدولِ واحد از آن استفاده می‌کند
    unit_box = _unitbox()
    today_box = _todaybox()
    band_box = _bandbox()

    SIGH = ("رتبه|نماد|آلارم|کلوز|نقطهٔ ورود|سطحِ واکنش|حدضرر|حدسود|ریسک|"
            "بک‌تستِ وضعیت|ماهانه|هفتگی|"
            "حکمِ خلای حجمی|محرک (پاسخ)|تارگتِ میله و پرچم")

    # ── تبِ ۲: دفتر ──
    def bkrow(r):
        # پرکننده نقطهٔ ورود و حدضرر و تارگت **ندارد** — نگه‌دار است
        # نه خرید. نشان دادنِ آن سه عدد برایش همان چیزی بود که فملی و
        # وبملت را با کلوزِ زیرِ حدضرر در دفتر نشان می‌داد.
        ho = r.get("hold_only")
        kp = r.get("kept")
        z = r["z"]
        dash = '<span class="sub">—</span>'
        rk = dash if ho else f'{z["risk_pct"]:.1f}٪'
        return (
            f'<tr data-s="{r["sym"]}" data-c="{r["cat"]}">'
            f'<td class="td sym">{r["sym"]}'
            + ('<span class="gate gate-ok" title="سیگنال نیست. هیچ '
               'نمادی واجد شرط نبود و قاعدهٔ «هرگز نقد نشو» این را '
               'نگه می‌دارد. نخر — فقط اگر داری، نگه دار.">'
               'نگه‌دار، نه خرید</span>' if ho else "")
            + f'</td><td class="td">{r["cat"]}</td>'
            f'<td class="td">'
            + ("—" if ho else ("هفتگی" if r["band"] == "week" else "ماهانه"))
            + f'</td><td class="td n">{n(r["close"])}</td>'
            f'<td class="td n hi">{dash if ho else n(z["aim"])}</td>'
            f'<td class="td n r">{dash if ho else n(z["stop"])}</td>'
            f'<td class="td n g">{dash if ho else n(z["target"])}</td>'
            f'<td class="td n">{rk}</td>'
            f'<td class="td n">{r["w"]:.0f}٪</td>'
            f'<td class="td n">{n(r["amt"] / 1e6)}</td>'
            f'<td class="td n">{n(r["units"])}</td>'
            f'<td class="td n r">{dash if ho else n(r["loss"] / 1e6)}</td>'
            f'<td class="td">'
            + ('<span class="badge b-m">نگه‌دار</span>' if ho
               else alarm(z, r.get(r["band"][0] + "_dead")))
            + '</td></tr>')

    bk = "".join(bkrow(r) for r in book)
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
        if r.get("w_dead") and r.get("m_dead"):
            return ("b-r", "استاپ خورده")
        if BENCH_FILTER and r.get("bx") is not None and r["bx"] < 0:
            return ("b-r", f'عقبِ {BENCH} ({r["bx"]:+.0f})')
        if r["mst"] != "بالا":
            return ("b-r", "زیرِ ماه قبل")
        if r["wst"] != "بالا":
            return ("b-r", "زیرِ هفتگی")
        if REQUIRE_CUR_MONTH and r["cur_st"] not in ("بالا", "؟"):
            return ("b-r", "زیرِ ماهِ جاری")
        if r["value_bn"] < MIN_VALUE_BN:
            return ("b-m", f"حجمِ کم ({r['value_bn']:,.0f})")
        return ("b-m", "واجد شرط، خارج از فهرستِ برتر" + tag)

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
        w = WINRATE.get(hz) or {}
        if "_base" not in w:
            return (f'<h3>{title}</h3><div class="sub">جدولِ بک‌تست برای '
                    f'این جهان ساخته نشد (دادهٔ کم). عمداً جدولِ جهانِ '
                    f'دیگری نشان داده نمی‌شود.</div>')
        bn, bwin, bavg = w["_base"]
        ps = w.get("_p") or {}
        # ستونِ p: بدونِ آن، «۷۵٪ برد» در بازاری که ۶۴٪ روزها مثبت است
        # شبیهِ سیگنال به نظر می‌رسد. بند ۰ قانون ۲.
        rr = "".join(
            f'<tr><td class="td sym">{k}</td><td class="td n">{v[0]:,}</td>'
            f'<td class="td n">{v[1]}٪ {bar(v[1])}</td>'
            f'<td class="td n {"g" if v[2] > 0 else "r"}">{v[2]:+.2f}٪</td>'
            f'<td class="td n {"g" if v[1] - bwin > 0 else "r"}">'
            f'{v[1] - bwin:+d} واحد</td>'
            f'<td class="td n">'
            + (f'<b class="g">{ps[k]:.4f} ★</b>' if k in ps and ps[k] < 0.05
               else f'{ps[k]:.4f}' if k in ps else '—')
            + '</td></tr>'
            for k, v in sorted(w.items(),
                               key=lambda kv: -kv[1][1]
                               if isinstance(kv[1], tuple) else 0)
            if not k.startswith("_"))
        tail = ("" if not ps else
                '<div class="sub">★ یعنی از نرخ پایهٔ همان دوره جدا شد '
                '(آزمونِ جایگشتِ درون‌دوره‌ای). بدونِ ★، عددِ برد '
                '<b>سیگنال نیست</b> — در بازاری که '
                f'{bwin}٪ دوره‌ها مثبت است، برد بالا خودبه‌خود '
                'می‌آید.</div>')
        return (f'<h3>{title}</h3><div class="sub">{note} — پایه: '
                f'{bwin}٪ مثبت · {bavg:+.2f}٪ · n={bn:,}</div>'
                f'<div class="wrap"><table class="table"><thead><tr>'
                + "".join(f'<th class="th{" n" if i else ""}">{c}</th>'
                          for i, c in enumerate(
                              ["وضعیتِ باکس", "n", "موفقیت",
                               "میانگین بازده", "نسبت به پایه", "p"]))
                + f'</tr></thead><tbody>{rr}</tbody></table></div>{tail}')

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
.compass{{margin:16px 0;padding:16px 18px;border-radius:14px;
background:var(--card);border:1px solid var(--border)}}
.cmp-h{{font-weight:700;font-size:.95rem;margin-bottom:12px;
color:var(--text)}}
.cmp-s{{margin:0 0 6px}}
.spark{{width:100%;height:130px;display:block;margin-top:10px}}
.spark .sv{{fill:var(--muted);font-size:13px;font-weight:600}}
.spark .se{{fill:var(--text)}}
.stat .v[dir="ltr"]{{direction:ltr;unicode-bidi:isolate}}
.sprk-l{{display:flex;justify-content:space-between;
font-size:.72rem;margin-top:4px}}
.feebox{{margin:14px 0;padding:13px 16px;border-radius:12px;
background:rgba(245,101,101,.08);border:1px solid var(--red);
font-size:.88rem;line-height:1.9;color:var(--text)}}
.bt{{display:inline-flex;align-items:center;gap:6px;white-space:nowrap}}
.bt i{{font-style:normal;font-size:.72rem}}
.vl{{display:inline-block;margin-inline-end:3px;padding:2px 5px;
border-radius:5px;font-size:.66rem;font-weight:600;white-space:nowrap;
min-width:36px;text-align:center}}
.vl-n{{background:#1d2637;color:#3d4a60}}
.vv{{display:inline-block;margin-inline-end:5px;width:18px;height:18px;
line-height:19px;text-align:center;border-radius:5px;font-weight:800;
font-size:.78rem;vertical-align:middle}}
.vv-u{{background:var(--green);color:#0b1220}}
.vv-i{{background:var(--yellow);color:#0b1220}}
.vv-d{{background:var(--red);color:#0b1220}}
.dv{{display:inline-block;padding:2px 6px;border-radius:6px;
font-size:.68rem;font-weight:600;white-space:nowrap}}
.dv-n{{background:var(--th);color:var(--muted)}}
.dv-u{{background:rgba(61,214,140,.13);color:var(--green)}}
.dv-d{{background:rgba(245,101,101,.13);color:var(--red)}}
.drvgrid{{display:grid;grid-template-columns:repeat(auto-fill,
minmax(210px,1fr));gap:10px;margin:14px 0}}
.drvc{{background:var(--card);border:1px solid var(--border);
border-radius:12px;padding:12px 14px}}
.drvc .nm{{font-size:.82rem;font-weight:700;color:var(--text)}}
.drvc .mv{{font-size:1.25rem;font-weight:800;margin-top:4px}}
.drvc .sb{{font-size:.7rem;color:var(--muted);margin-top:3px}}
.vl-u{{background:rgba(61,214,140,.15);color:var(--green)}}
.vl-i{{background:rgba(236,201,75,.18);color:var(--yellow)}}
.vl-d{{background:rgba(245,101,101,.15);color:var(--red)}}
.flag{{display:inline-block;margin-inline-end:5px;padding:1px 6px;
border-radius:6px;background:var(--th);font-size:.7rem;
color:var(--muted);white-space:nowrap}}
.gate{{display:inline-block;margin-inline-start:6px;padding:1px 6px;
border-radius:6px;background:rgba(245,101,101,.13);color:var(--red);
font-size:.66rem;font-weight:600;white-space:nowrap}}
.gate-ok{{background:rgba(236,201,75,.15);color:var(--yellow)}}
.gate-mw{{background:rgba(99,179,237,.15);color:var(--blue)}}
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

<h1>داشبورد ریسک و بازده — {UNIV}</h1>{FEEBOX}
<div class="sub">کلوز {stamp} ({WD[last_wd]}) · {len(rows)} نماد بررسی شد
· {len(ok_rows)} نماد با باکسِ معتبر</div>

{alarm_box}

{idx_box}

{compass_box}

<div class="cal"><table><tbody>{cal}</tbody></table>
<div class="mn">ماهانه: {month_note(last_date)}</div></div>

<div class="stats">{tiles}</div>

<div class="tabs">
  <button class="tab on" data-t="p0">★ تصمیمِ امروز</button>
  <button class="tab" data-t="p1">سیگنال ماهانه</button>
  <button class="tab" data-t="p2">سیگنال هفتگی</button>
  <button class="tab" data-t="p3">دفترِ پیشنهادی</button>
  <button class="tab" data-t="p10">واحدِ کهربا</button>
  <button class="tab" data-t="p7">پوزیشن‌های من</button>
  <button class="tab" data-t="p8">ریسک منیجر</button>
  <button class="tab" data-t="p6">خرید و فروشِ امروز</button>
  <button class="tab" data-t="p9">محرک‌های جهانی</button>
  <button class="tab" data-t="p4">وضعیت همهٔ نمادها</button>
  <button class="tab" data-t="p5">بک‌تست</button>
</div>

<div class="filters">{chips}
  <input id="q" type="search" placeholder="جست‌وجوی نماد…"></div>

<div class="panel on" id="p0">{today_box}</div>

<div class="panel" id="p1">
  <div class="sub"><b>وضعیتِ هفتگی روی کلوزِ <i>روزِ تصمیم</i> حساب
  می‌شود</b> — اولین جلسهٔ هفتهٔ جاری (یکشنبه)، نه آخرین کلوز.
  اندازه‌گیری شد: مزیتِ کلوزِ یکشنبه ‎+۰٫۶۵۲ واحد با p=۰٫۰۰۰۳،
  بهترین از چهار روزِ هفته. بدونِ این، اجرای سه‌شنبه سیگنالی را که
  یکشنبه صادر شده بود گم می‌کرد. ستونِ <b>کلوز</b> و ستونِ
  <b>آلارم</b> همچنان قیمتِ <i>امروز</i>اند. با <code>--now</code>
  به رفتارِ قبلی برمی‌گردد.
  <br><b>حدسود و خروج — دو چیزِ متفاوت‌اند.</b> مصطفی: «مگر قرار نشد
  حد سود مصادف بشود با وقتی که باکسِ هفتگی خلاف صادر بشود؟» درست است،
  و قاعدهٔ خودِ اوست: «ما فقط در صورتی می‌فروشیم که زیرِ باکس بسته
  شود.» پس <b>خروجِ واقعی همان حدضرر است</b> — وقتی کلوز زیرِ کفِ
  باکسِ هفتگی برود، آلارمِ <span class="badge b-r">🔄 عوض کن</span>
  روشن می‌شود. ستونِ <b>حدسود</b> تارگتِ هندسهٔ ۱:۱ است (ورود +
  اندازهٔ ریسک) و فقط <i>مرجعِ بک‌تست</i> است، نه قاعده‌ای که او
  اجرا می‌کند؛ اعدادِ R همه با همان حساب شده‌اند.
  <br>باکس از ماه میلادیِ کامل‌شدهٔ قبل. <b>نقطهٔ ورود</b>
  سقفِ باکس ‎+۳٪ است، نه خودِ سقف — در بک‌تست ورود روی سقف t=۱٫۳۵ داد و
  ۳٪ بالاتر t=۵٫۴۱. ستونِ آلارم می‌گوید قیمت الان چقدر تا آن فاصله دارد.
  <br><b>بک‌تستِ وضعیت</b> عددِ خودِ نماد نیست — بک‌تست روی
  <i>سطلِ وضعیت</i> بسته شده (هر سه بالا · فقط هفتگی · هفتگی زیر …)، پس
  هر نمادی که امروز در همان وضعیت است همان عدد را می‌گیرد. {SRC}
  <br><b>تریگرِ حجمی</b> استراتژیِ دومِ توست و فقط **تریگر** است —
  ریسک، نرخِ برد، نقطهٔ ورود و حدضرر همه از باکسِ <i>حجمی افقی</i>
  می‌آیند و این ستون هیچ‌کدامشان را عوض نمی‌کند. نشانِ اولِ سلول
  حکمِ کلی است: <span class="vv vv-u">✓</span> هر سه بالا ·
  <span class="vv vv-i">~</span> در یکی پولبک ·
  <span class="vv vv-d">✕</span> دستِ‌کم یکی زیر. بعدش ماهانه، هفتگی و
  دیلی با فاصلهٔ درصدی. تعریفش: کندلی که حجمش از دو
  کندلِ کنارش کمتر بوده باکس می‌شود. <span class="vl vl-u">ه −۴٪</span>
  یعنی در تایمِ هفتگی بالای آن باکسیم و ۴٪ پایین‌تر حمایت است؛
  <span class="vl vl-i">ه پولبکِ ۱</span> یعنی همین حالا داخلِ باکس
  است و این <b>اولین</b> برگشت به آن ناحیه است (عدد = چندمین لمس؛
  لمسِ دوم به بعد اندازه‌گیری‌شده ضعیف‌تر است، ‎−۰٫۵ واحد، docs/25) —
  <b>این سیگنالِ خرید نیست</b>: پولبک به باکسِ شکسته بک‌تست شد و از
  «بالای باکس ولی بدونِ پولبک» ‎−۱٫۳۲ واحد هفتگی و ‎−۰٫۳۴ واحد دیلی
  <i>بدتر</i> است (docs/24)؛
  <span class="vl vl-d">ه +۲٪</span> یعنی زیرِ باکسیم و ۲٪ بالاتر مقاومت.
  هفتگی اول می‌آید چون قابل‌اتکاترین است. باکس از دورهٔ
  <b>کامل‌شدهٔ</b> قبل ساخته می‌شود و حمایتی که بیش از
  {VGAP_MAX_DIST:.0f}٪ دور است نشان داده نمی‌شود — جوابِ «چند درصد
  پایین‌تر؟» نیست.
  <br>نمادِ <span class="thin">کم‌حجم</span> در دفتر نمی‌آید: ارزشِ معاملاتش
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
  {band_box}
  <div class="sub"><b>{MAX_PICKS}</b> نمادِ برتر بر اساسِ
  <b>مازادِ {BENCH} + پاسخِ محرک</b>. زیر {MIN_VALUE_BN:.0f} میلیارد
  در روز حذف شده.
  <br><b>قیدِ تنوع عمداً نیست.</b> قاعدهٔ قبلی «از هر دسته یکی، و آن
  بزرگ‌ترین» بود؛ اندازه‌گیری شد و باخت: بی‌قید ۱٫۱۵۲ · حداکثر ۲ از
  هر دسته ۱٫۱۰۵ · حداکثر ۱ از هر دسته ۱٫۰۱۳ · بزرگ‌ترینِ دسته
  <span class="r">۰٫۸۷۳</span> (واحدِ {BENCH}، ۳۵ هفته، docs/32).
  کفِ نقدشوندگی جای آن قید را می‌گیرد. ولی این یعنی سبد می‌تواند
  کاملاً در یک دسته بنشیند — بالای همین جدول اگر چنین شد گفته
  می‌شود.</div>
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

<div class="panel" id="p7">{positions_box}</div>

<div class="panel" id="p9">
  <div class="sub"><b>محرک هر نماد اندازه‌گیری شده، نه برچسب‌خورده.</b>
  همبستگیِ بازدهِ روزانهٔ نماد با هر یک از {DRVN} سری، روی همان
  پنجرهٔ داده؛ بزرگ‌ترین به اسمش می‌خورد و زیرِ {DRV_MIN_CORR:.2f}
  «بی‌محرک» می‌ماند. جهتِ محاسبه <i>محرکِ تا قبل از امروز ← بازدهِ
  امروز</i> است: اونس و نفت شبانه حرکت می‌کنند و تهران صبح واکنش
  می‌دهد، پس کلوزِ هم‌روزشان ساعتِ تصمیم اصلاً منتشر نشده.
  <br><b>این دروازه نیست، وزنه است.</b> اندازه‌گیری روی ۳۵ هفته،
  معیارِ واحدِ کهربا، N=۶ · سقفِ وزن ۲۵٪:
  <br>&nbsp;&nbsp;مازادِ کهربا به‌تنهایی (قاعدهٔ قبلی) <b>۱٫۱۵۲</b>
  &nbsp;·&nbsp; مازاد + <b>پاسخِ محرک</b> <b class="g">۱٫۱۹۱</b>
  &nbsp;·&nbsp; فقط شتابِ محرک ۱٫۱۴۵
  &nbsp;·&nbsp; <span class="r">حذفِ نمادی که محرکش منفی است ۱٫۰۶۴</span>
  &nbsp;·&nbsp; <span class="r">حذفِ محرکِ زیرِ باکس ۱٫۰۵۶</span>
  <br>حذف در هر شکلی ضرر داد؛ اضافه‌کردن به امتیاز سود داد. و در
  <b>هر ۱۲</b> ترکیبِ (N، سقفِ وزن) که جارو شد — و در هر دو نیمهٔ
  پنجره — نسخهٔ با محرک جلو بود. در برابرِ ۲۰۰ ترتیبِ تصادفی:
  قاعدهٔ قبلی صدکِ ۹۸، با محرک صدکِ ۹۹٫۵.
  <br>⚠️ <b>شواهد جهت‌دار است، نه محکم.</b> rho درون‌دوره‌ای فقط
  ‎+۰٫۰۳ با p=۰٫۶۱ روی ۶۳۲ مشاهده، و پنجره ۳۵ هفته است. روی
  <b>ماهانه</b> هیچ‌کدام از ترتیبِ تصادفی جدا نشد (۴۵٪ بذرهای تصادفی
  از قاعده بهتر بودند، ۹ دوره) — پس در تصمیمِ ماهانه به این ستون
  تکیه نکن. بازسازی: <code>python3 tools/driver_rank.py</code>،
  شرحِ کامل در <code>docs/33</code>.</div>
  {drv_box}
</div>

<div class="panel" id="p10">{unit_box}</div>

<div class="panel" id="p8">{risk_box}</div>

<div class="panel" id="p6">{orders_box}</div>

<div class="panel" id="p5">
  {bt("month", "بک‌تست ماهانه",
      "بازدهِ ماهِ پیشِ رو بر اساس وضعیتِ باکس در روزِ تصمیم. " + BTSRC)}
  {bt("week", "بک‌تست هفتگی",
      "همان با افقِ هفتهٔ پیشِ رو. " + BTSRC)}
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



# ══ ۵.۵ اجرای ترکیبی — یک دستور، هر دو جهان ═════════════════════════
# مصطفی: «برای گزارش‌گیری همه چیز را باید روزانه بزنم — هم صندوق‌های
# ETF و هم کلیهٔ سهام‌ها و هم پرتفوی روزانهٔ هدف.»
#
# تا حالا دو دستورِ جدا بود و **یک اشکالِ جدی داشت**: هر اجرا سرمایه
# را از همان پرتفو حساب می‌کرد و دفترِ خودش را روی ۱۰۰٪ آن می‌بست.
# اگر هر دو را دنبال می‌کردی، ۲۰۰٪ سرمایه‌گذاری می‌شدی. اینجا یک
# سرمایهٔ واحد بین دو جهان تقسیم می‌شود.
#
# **سهمِ سهام پیش‌فرض صفر است، و این حدس نیست.** `docs/34`: همان
# چرخش روی ۷۷ صندوقِ سهامی، معیارِ هولدِ شاخص کل = ۱٫۰۰ —
#
#     کارمزدِ ۰٪ → ۱٫۱۸۲ · ۰٫۵۵٪ (صندوق) → ۱٫۰۷۵
#     کارمزدِ ۱٫۲٪ (سهام) → ۰٫۹۵۹ · ۲٪ → ۰٫۸۳۴
#
# یعنی چرخشِ سهام با کارمزدِ واقعی از **هولدِ شاخص** عقب می‌ماند. پس
# بودجهٔ چرخش به صندوق‌ها می‌رود. سهام‌هایی که **داری** همچنان هر روز
# حد ضرر و حد سود می‌گیرند و اگر زیرِ ناحیه بسته شوند آلارمِ خروج
# می‌خورند — فقط پولِ تازه رویشان نمی‌رود. با --stock-share N
# می‌شود عوضش کرد.
SNAP_KEYS = ("stamp", "capital", "cash", "units", "book", "pos",
             "buy", "sell", "sells", "buys", "nopx", "px", "compass")


def snap_write(path, stamp, capital, units, cash, book, pos,
               buy, sell, sells, buys, nopx, px, comp, bu=None,
               dif=None, dstamp=None):
    """عکسِ یک اجرا — چیزی که گزارشِ ترکیبی لازم دارد، نه بیشتر.

    ردیف‌های دفتر پر از کلیدهای داخلی‌اند (hist، flags، z…) که در
    JSON یا بزرگ‌اند یا سریال‌ناپذیر. فقط آنچه گزارش می‌خواند بیرون
    می‌رود.
    """
    def bk(r):
        z = r.get("z") or {}
        return {"sym": r["sym"], "cat": r.get("cat", "؟"),
                "tier": r.get("tier"), "band": r.get("band"),
                "w": r.get("w"), "amt": r.get("amt"),
                "units": r.get("units"), "loss": r.get("loss"),
                "hold_only": bool(r.get("hold_only")),
                "close": r.get("close"), "bx": r.get("bx"),
                "drv": r.get("drv"), "drv_resp": r.get("drv_resp"),
                "aim": z.get("aim"), "stop": z.get("stop"),
                "target": z.get("target"),
                "risk_pct": z.get("risk_pct")}

    data = {
        "universe": "سهام" if STOCK else "صندوق",
        "bench": BENCH, "cost": COST_STOCK if STOCK else COST_FUND,
        "stamp": stamp, "capital": capital, "cash": cash,
        "units": {k: v for k, v in units.items()},
        "book": [bk(r) for r in book],
        "pos": [{k: v for k, v in x.items() if k != "flag"}
                | {"flag": (x.get("flag") or {}).get("target")}
                for x in pos],
        "buy": [list(x) for x in buy],
        "sell": [list(x) for x in sell],
        "sells": [{k: v for k, v in x.items()} for x in sells],
        "buys": [{k: v for k, v in x.items()} for x in buys],
        "nopx": list(nopx),
        "px": {k: v for k, v in px.items()},
        "compass": {k: v for k, v in (comp or {}).items()
                    if k != "hist"},
        "units_vs_bench": bu,
        "diff": dif, "diff_from": dstamp,
    }
    f = Path(path)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data, ensure_ascii=False, indent=1,
                            default=str), encoding="utf-8")


def run_all(argv, stock_share, open_pages=True, adopt=False):
    """هر دو جهان، یکی بعدِ دیگری، بعد یک گزارشِ ترکیبی.

    زیرفرایند است نه فراخوانیِ درون‌فرایندی، چون `main()` ده‌ها
    گلوبال می‌گذارد (STOCK، DATA، OUT، BENCH، WINRATE…). اجرای دوباره
    در همان فرایند یعنی نشتِ حالتِ اجرای اول به دومی — همان جنس
    باگی که تا حالا سه بار از این پروژه درآمده.
    """
    import subprocess
    here = Path(__file__).resolve()
    snaps = {}
    for tag, extra, out in (
            ("صندوق", [], HERE / "data_bourse" / "snap.json"),
            ("سهام", ["--stocks"], HERE / "data_stocks" / "snap.json")):
        print("\n" + "█" * 64)
        print(f"  █  جهانِ {tag}")
        print("█" * 64)
        cmd = [sys.executable, str(here)] + argv + extra + [
            "--export", str(out), "--no-open"]
        r = subprocess.run(cmd)
        if r.returncode == 0 and out.exists():
            try:
                snaps[tag] = json.loads(out.read_text(encoding="utf-8"))
            except ValueError:
                print(f"  ⚠️  عکسِ جهانِ {tag} خوانده نشد.")
        else:
            print(f"  ⚠️  جهانِ {tag} کامل نشد "
                  f"(کدِ خروج {r.returncode}) — از گزارشِ ترکیبی "
                  f"کنار می‌ماند.")
    if not snaps:
        print("\n  هیچ‌کدام از دو جهان نتیجه نداد.")
        return 1
    return combined(snaps, stock_share, open_pages, adopt)


def combined(snaps, stock_share=None, open_pages=False,
             adopt=False):
    """گزارشِ ترکیبی — یک سرمایه، یک پرتفوی هدف، یک فهرستِ خرید و فروش."""
    share = STOCK_SHARE if stock_share is None else stock_share
    share = max(0.0, min(100.0, share))
    fu, st = snaps.get("صندوق"), snaps.get("سهام")
    lines = []

    def out(t=""):
        print(t)
        lines.append(t)

    # ── سرمایه: **یکی**، نه دو تا ──────────────────────────────────
    # هر اجرا سرمایه را از همان پرتفو حساب می‌کند، پس هر دو تقریباً
    # یک عدد می‌دهند. بزرگ‌ترش را می‌گیریم چون اجرای صندوق قیمتِ
    # سهم‌ها را ندارد و کم‌برآورد می‌کند (همان هشدارِ «قیمتِ وسپه…
    # پیدا نشد»).
    caps = [x["capital"] for x in snaps.values() if x.get("capital")]
    capital = max(caps) if caps else 0.0
    stamp = max(x["stamp"] for x in snaps.values())

    out("\n" + "=" * 64)
    out("  گزارشِ روزانهٔ ترکیبی — هر دو جهان، یک سرمایه")
    out("=" * 64)
    out(f"\n  کلوز {stamp} · سرمایهٔ واحد "
        f"{capital / 1e9:,.1f} میلیارد ریال")
    for tag, x in snaps.items():
        out(f"    جهانِ {tag:<7} مبنا {x['bench']:<10} "
            f"کارمزد {x['cost']}٪ · {len(x['book'])} ردیفِ دفتر")

    # ── چه چیزی امروز عوض شد، از هر دو جهان ────────────────────────
    anyd = False
    for tag, x in snaps.items():
        df, ds = x.get("diff"), x.get("diff_from")
        if not ds:
            continue
        if not anyd:
            out("\n" + "=" * 64)
            out("  چه چیزی امروز عوض شد")
            out("=" * 64)
            anyd = True
        bk = {norm(r["sym"]) for r in (x.get("book") or [])}
        mine = [e for e in (df or [])
                if e.get("held") or norm(e["sym"]) in bk]
        rest = [e for e in (df or []) if e not in mine]
        out(f"\n  ── جهانِ {tag} · {ds} → {x['stamp']} ──")
        if not mine:
            out("    روی نمادهای من و دفتر: هیچ تغییری نبود.")
        for e in mine:
            mark = {"r": "⛔", "y": "⚠️ ", "g": "🟢"}[e["col"]]
            pc = ((e["close"] / e["was"] - 1) * 100
                  if e.get("was") else None)
            out(f"    {mark} {e['sym']:<11}{e['lab']:<34}"
                f"{e['close']:>12,.0f}"
                + (f"  {pc:+.2f}٪" if pc is not None else "")
                + (" (داری)" if e.get("held") else ""))
        if rest:
            bad = sum(1 for e in rest if e["col"] == "r")
            out(f"    بقیهٔ جهان: {len(rest)} تغییر ({bad} منفی) — "
                f"در تبِ «تصمیمِ امروز».")
    if not anyd:
        out("\n  (عکسِ دیروز نبود، پس «چه چیزی عوض شد» حساب نشد — "
            "از اجرای بعد.)")

    # ── تقسیمِ سرمایه بینِ دو جهان ─────────────────────────────────
    out("\n" + "-" * 64)
    out(f"  تقسیمِ سرمایه: صندوق {100 - share:.0f}٪ · "
        f"سهام {share:.0f}٪")
    if share == 0:
        out("  سهمِ سهام صفر است و این حدس نیست — docs/34:")
        out("    کارمزدِ ۰٪ → ۱٫۱۸۲ · ۰٫۵۵٪ (صندوق) → ۱٫۰۷۵")
        out("    کارمزدِ ۱٫۲٪ (سهام) → ۰٫۹۵۹ · ۲٪ → ۰٫۸۳۴")
        out("    (معیار: هولدِ شاخص کل = ۱٫۰۰، ۷۷ صندوقِ سهامی، ۳۵ هفته)")
        out("  یعنی چرخشِ سهام با کارمزدِ واقعی از هولدِ شاخص عقب")
        out("  می‌ماند. پس پولِ تازه روی سهام نمی‌رود.")
        out("  ⚠️ ولی سهامی که **داری** حذف نشده — پایین‌تر هر روز")
        out("     حد ضرر و حد سود می‌گیرد. با --stock-share N عوض کن.")

    # ── پرتفوی هدفِ ترکیبی ─────────────────────────────────────────
    rows = []
    for tag, x, sh in (("صندوق", fu, 100 - share), ("سهام", st, share)):
        if not x or sh <= 0:
            continue
        tot = sum(r["w"] or 0 for r in x["book"]) or 1.0
        for r in x["book"]:
            rows.append({**r, "univ": tag,
                         "w2": (r["w"] or 0) / tot * sh})
    rows.sort(key=lambda r: -r["w2"])
    if rows:
        out("\n" + "=" * 64)
        out("  پرتفوی هدفِ امروز — ترکیبی")
        out("=" * 64)
        out(f"\n  {'نماد':<11}{'جهان':<8}{'وزن':>7}{'مبلغ (م.ر)':>13}"
            f"{'ورود':>12}{'استاپ':>11}{'ریسک':>7}")
        out("  " + "-" * 62)
        for r in rows:
            amt = capital * r["w2"] / 100
            if r["hold_only"]:
                out(f"  {r['sym']:<11}{r['univ']:<8}{r['w2']:>6.1f}٪"
                    f"{amt / 1e6:>13,.0f}"
                    f"{'نگه‌دار، نه خرید':>31}")
            else:
                out(f"  {r['sym']:<11}{r['univ']:<8}{r['w2']:>6.1f}٪"
                    f"{amt / 1e6:>13,.0f}{r['aim'] or 0:>12,.0f}"
                    f"{r['stop'] or 0:>11,.0f}"
                    f"{r['risk_pct'] or 0:>6.1f}٪")
        tw = sum(r["w2"] for r in rows)
        rk = sum(capital * r["w2"] / 100 * (r["risk_pct"] or 0) / 100
                 for r in rows if not r["hold_only"])
        out("  " + "-" * 62)
        out(f"  {'جمع':<11}{'':<8}{tw:>6.1f}٪"
            f"{capital * tw / 100 / 1e6:>13,.0f}")
        out(f"  نقد: {100 - tw:.1f}٪ · اگر همهٔ استاپ‌ها بخورند: "
            f"{rk / capital * 100:.2f}٪ سرمایه "
            f"({rk / 1e6:,.0f} میلیون ریال)")

    # ── از سبدِ فعلی به سبدِ هدفِ **ترکیبی** ────────────────────────
    # این بخش دلیلِ اصلیِ وجودِ --all است. فهرستِ خرید و فروشِ هر
    # اجرا روی سرمایهٔ کاملِ خودش بسته می‌شود، پس دنبال‌کردنِ هر دو
    # یعنی دو برابر خرید. اینجا یک‌بار، روی سبدِ ترکیبی.
    units, px = {}, {}
    for x in snaps.values():
        for k, v in (x.get("units") or {}).items():
            units[k] = max(units.get(k, 0), v)
        for k, v in (x.get("px") or {}).items():
            px.setdefault(k, v)
    tgt = {norm(r["sym"]): r for r in rows}
    sells, buys, nopx = [], [], []
    for sym, u in units.items():
        k = norm(sym)
        pxx = px.get(k)
        if not pxx:
            nopx.append(sym)
            continue
        want = (capital * tgt[k]["w2"] / 100 / pxx) if k in tgt else 0.0
        if u - want > max(1.0, u * 0.02):
            d = u - want
            sells.append((sym, d, pxx, d * pxx, want <= 0))
    for k, r in tgt.items():
        pxx = px.get(k) or r.get("aim") or r.get("close")
        if not pxx or r["hold_only"]:
            continue
        have = next((u for sm, u in units.items() if norm(sm) == k), 0)
        want = capital * r["w2"] / 100 / pxx
        if want - have > max(1.0, want * 0.02):
            d = want - have
            buys.append((r["sym"], d, pxx, d * pxx, have <= 0))
    if sells or buys:
        out("\n" + "=" * 64)
        out("  از سبدِ فعلی به سبدِ هدف — یک فهرست، نه دو تا")
        out("=" * 64)
        out("  ترتیب: **اول فروش، بعد خرید** — پولِ آزادشده منبعِ "
            "خریدِ همان صبح است.")
        for ttl, lst, mark in (("▼ فروش", sells, "کلِ موجودی"),
                               ("▲ خرید", buys, "جدید")):
            if not lst:
                continue
            out(f"\n  {ttl:<14}{'واحد':>14}{'قیمت':>12}"
                f"{'مبلغ (م.ر)':>14}")
            out("  " + "-" * 56)
            for sym, u, pxx, amt, full in lst:
                out(f"  {sym:<14}{u:>14,.0f}{pxx:>12,.0f}"
                    f"{amt / 1e6:>14,.0f}"
                    + (f" ({mark})" if full else ""))
            out(f"  {'جمع':<14}{'':>14}{'':>12}"
                f"{sum(x[3] for x in lst) / 1e6:>14,.0f}")
        sv = sum(x[3] for x in sells)
        bv = sum(x[3] for x in buys)
        if capital > 0:
            # کارمزد به تفکیکِ جهان: سهم ۱٫۲٪، صندوق ۰٫۵۵٪
            def fee_of(sym):
                r = tgt.get(norm(sym))
                return (COST_STOCK if (r and r["univ"] == "سهام")
                        else COST_FUND)
            cost = sum(x[3] * fee_of(x[0]) / 2 / 100
                       for x in sells + buys)
            out(f"\n  گردشِ امروز: {(sv + bv) / 1e6:,.0f} میلیون ریال "
                f"= {(sv + bv) / capital * 100:.0f}٪ سرمایه")
            out(f"  کارمزدش: ~{cost / 1e6:,.0f} میلیون ریال "
                f"({cost / capital * 100:.2f}٪ سرمایه)")
            if (sv + bv) / capital > 1.2:
                out("  ⚠️  چرخشِ کامل است. قاعدهٔ انتخاب هیسترزیس "
                    "ندارد و بک‌تست هم")
                out("      همین‌طور بسته شده — ولی اگر فروش و خرید "
                    "در یک دسته‌اند،")
                out("      داری کارمزد می‌دهی تا همان ریسک را نگه "
                    "داری. خودت ببین.")
        if nopx:
            out(f"\n  ⚠️  قیمتِ {'، '.join(nopx)} در هیچ‌کدام از دو "
                f"جهان نبود — در فهرستِ بالا نیستند.")

    # ── پوزیشن‌های من، از هر دو جهان ───────────────────────────────
    allpos, seen = [], set()
    for tag, x in snaps.items():
        for pz in (x.get("pos") or []):
            k = norm(pz["sym"])
            if k in seen:
                continue
            seen.add(k)
            allpos.append({**pz, "univ": tag})
    allpos.sort(key=lambda x: -(x.get("value") or 0))
    if allpos:
        out("\n" + "=" * 64)
        out("  پوزیشن‌های من — حد ضرر و حد سودِ امروز (هر دو جهان)")
        out("=" * 64)
        out(f"\n  {'نماد':<11}{'جهان':<8}{'ارزش (م.ر)':>12}"
            f"{'کلوز':>11}{'حد ضرر':>11}{'فاصله':>8}   حد سود")
        out("  " + "-" * 76)
        for x in allpos:
            fl = (f"{x['flag']:,.0f} (پرچم)" if x.get("flag")
                  else "شکستِ ناحیه")
            warn = " ⛔" if x.get("below") else ""
            out(f"  {x['sym']:<11}{x['univ']:<8}"
                f"{(x.get('value') or 0) / 1e6:>12,.0f}"
                f"{x['px']:>11,.0f}{x['zone_lo']:>11,.0f}"
                f"{x['dist_stop']:>+7.1f}٪   {fl}{warn}")
        gone = [x for x in allpos if x.get("below")]
        if gone:
            out(f"\n  ⛔ {len(gone)} قلم زیرِ ناحیه بسته — "
                f"فردا در پولبک فروشنده: "
                + "، ".join(x["sym"] for x in gone))
            out("     نقد نشو؛ پولش روی نمادی که بالای باکسش است.")

    # ── مازادِ واحدِ کهربا، از هر دو جهان ───────────────────────────
    # هدفِ نهاییِ خودش، پس در گزارشِ ترکیبی هم باید باشد.
    bus = [(t, x.get("units_vs_bench")) for t, x in snaps.items()
           if x.get("units_vs_bench")]
    if bus:
        out("\n" + "=" * 64)
        out("  تعدادِ واحدِ کهربا — مازادِ من")
        out("=" * 64)
        for t, bu in bus:
            d = bu.get("dates") or {}
            out(f"\n  ── جهانِ {t} ──")
            for fa, hz in UNIT_HZ:
                v = (bu.get("port") or {}).get(hz)
                a = d.get(hz)
                if v is None:
                    out(f"    {fa:<8}—")
                    continue
                w = "جلو ▲" if v > 0 else "عقب ▼" if v < 0 else "هم‌پا"
                out(f"    {fa:<8}{v:>+7.2f}٪  {w:<7}"
                    + (f"از {a[0]} تا {a[1]}" if a else ""))
            mine = [r for r in (bu.get("sym") or []) if r.get("held")]
            if mine:
                out(f"\n    {'نماد':<11}{'روزانه':>9}{'هفتگی':>9}"
                    f"{'ماهانه':>9}{'۴۰ روزه':>10}")
                out("    " + "-" * 48)
                for r in mine:
                    def f(x):
                        return "—" if x is None else f"{x:+.2f}"
                    bxs = ("—" if r.get("bx") is None
                           else f"{r['bx']:+.1f}")
                    out(f"    {r['sym']:<11}{f(r['d']):>9}"
                        f"{f(r['w']):>9}{f(r['m']):>9}{bxs:>10}")
        out("\n  تعریف: (۱+بازدهِ نماد) ÷ (۱+بازدهِ کهربا) − ۱")
        out("  بک‌تستِ همین معیار (python3 tools/unit_gain.py):")
        out("    هفتگی  +۱۹٫۰۹٪ کلِ پنجره · +۰٫۵۱۵٪ هر دوره · "
            "۴۴٫۸٪ دوره‌ها جلو")
        out("    ماهانه +۳۷٫۶۶٪ کلِ پنجره · +۴٫۰۷۶٪ هر دوره · "
            "۶۲٫۵٪ دوره‌ها جلو")
        out("    ⚠️ میانهٔ هفتگی −۰٫۲۱٪ است — مزیت دم‌کلفت است، "
            "نه یکنواخت.")

    # ── آلارم‌های ترکیبی ───────────────────────────────────────────
    ab = [(t, *b) for t, x in snaps.items() for b in (x.get("buy") or [])]
    asl = [(t, *b) for t, x in snaps.items() for b in (x.get("sell") or [])]
    out("\n" + "=" * 64)
    out("  🔔 آلارمِ امروز — هر دو جهان")
    out("=" * 64)
    if not ab and not asl:
        out("\n  🔕 نه آلارمِ خرید هست نه فروش.")
    for t, sym, px, which, u in asl:
        out(f"\n  🔄 عوض کن  {sym} ({t}) — کلوز {px:,.0f} زیرِ "
            f"باکسِ {which} · {u:,} واحد")
    for t, sym, aim, stop, risk, tier in ab:
        if t == "سهام" and share == 0:
            out(f"\n  🟡 {sym} (سهام) سیگنال است ولی سهمِ سهام صفر "
                f"است — ورود {aim:,.0f} · استاپ {stop:,.0f}")
            continue
        tag = "" if tier == 1 else " (نیمه)"
        out(f"\n  🟢 بخر  {sym} ({t}) — ورود {aim:,.0f} · "
            f"استاپ {stop:,.0f} · ریسک {risk:.1f}٪{tag}")

    out("\n" + "=" * 64)
    out("  این خوانشِ قاعده‌های خودت روی داده است، نه توصیهٔ مالی.")
    out("=" * 64)
    out("\n  داشبوردها:")
    for tag, f in (("صندوق", HERE / "dashboard.html"),
                   ("سهام", HERE / "dashboard_stocks.html")):
        if f.exists():
            out(f"    {tag:<8}{f}")

    # ── ثبتِ سبدِ ترکیبی ──────────────────────────────────────────
    if adopt and rows:
        nu = {}
        for r in rows:
            k = r["sym"]
            pxx = px.get(norm(k)) or r.get("close")
            if pxx:
                nu[k] = round(capital * r["w2"] / 100 / pxx)
        # قلم‌هایی که هنوز داری ولی در هدف نیستند صفر می‌شوند؛
        # قلم‌هایی که قیمتشان پیدا نشد **دست‌نخورده** می‌مانند،
        # چون صفر کردنشان یعنی ادعای فروشی که نشده.
        for sym, u in units.items():
            if norm(sym) not in tgt and norm(sym) not in px:
                nu[sym] = u
        inv = sum(r["w2"] for r in rows)
        holdings_save(nu, capital * max(0.0, 100 - inv) / 100)
        out("\n" + "=" * 64)
        out("  سبدِ ترکیبی ثبت شد — data_bourse/holdings.json")
        out("=" * 64)
        for k, v in sorted(nu.items(), key=lambda x: -x[1]):
            out(f"    {k:<12}{v:>14,} واحد")
        out("\n  ⚠️ این عدد **سبدِ هدف** است، نه آنچه واقعاً پر شد.")
        out("     اگر سفارشی نخورد یا جزئی پر شد، فایل را دستی")
        out("     درست کن — وگرنه قطب‌نما و مازادِ واحد از فردا غلط")
        out("     می‌شوند.")

    rep = HERE / "گزارشِ-روزانه.txt"
    rep.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  گزارشِ متنی: {rep}")
    if open_pages:
        # هر دو صفحه باز می‌شوند، نه یکی. زیرفرایندها با --no-open
        # اجرا شده‌اند تا وسطِ کار مرورگر باز نشود.
        for f in (HERE / "dashboard.html", HERE / "dashboard_stocks.html"):
            if f.exists():
                try:
                    webbrowser.open(f.as_uri())
                except Exception:                    # noqa: BLE001
                    pass
    return 0


# ══ ۶. اجرا ═════════════════════════════════════════════════════════
def main():
    global REQUIRE_CUR_MONTH, MAX_INVESTED, MAX_WEIGHT
    global STOCK, DATA, OUT, MIN_VALUE_BN, WINRATE, LIVE_STATE, BOX_KIND
    global BENCH_FILTER, BENCH_LOOK, BENCH
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
    ap.add_argument("--all", dest="run_all", action="store_true",
                    help="هر دو جهان را پشتِ سرِ هم بزن (صندوق‌ها و "
                         "سهام) و یک **گزارشِ ترکیبی** با یک سرمایهٔ "
                         "واحد بساز — نه دو تا")
    ap.add_argument("--stock-share", type=float, default=None,
                    help="درصدِ سرمایه که به چرخشِ سهام برسد در حالتِ "
                         "--all. پیش‌فرض ۰، و دلیلش اندازه‌گیری است "
                         "(docs/34): با کارمزدِ ۱٫۲٪ چرخشِ سهام از "
                         "هولدِ شاخص عقب می‌ماند.")
    ap.add_argument("--export", default=None,
                    help="عکسِ این اجرا را در یک فایلِ JSON بنویس "
                         "(دفتر، پوزیشن‌ها، آلارم‌ها) — --all از "
                         "همین استفاده می‌کند")
    ap.add_argument("--stocks", action="store_true",
                    help="به‌جای صندوق‌ها، **سهام** را بگیر؛ دادهٔ جدا "
                         "(data_stocks/)، خروجیِ جدا "
                         "(dashboard_stocks.html)، و جدولِ نرخِ برد از "
                         "خودِ سهام ساخته می‌شود نه از صندوق‌ها")
    ap.add_argument("--min-value", type=float, default=None,
                    help=f"کمینهٔ ارزشِ معاملاتِ روزانه به میلیارد ریال؛ "
                         f"پیش‌فرض {MIN_VALUE_BN:.0f}")
    ap.add_argument("--iters", type=int, default=2000,
                    help="تکرارِ آزمونِ جایگشت در حالتِ سهام")
    ap.add_argument("--box", choices=("valley", "poc"), default="valley",
                    help="valley = ردیفِ دره (پیش‌فرض) · "
                         "poc = ناحیهٔ پرحجمِ حولِ POC")
    ap.add_argument("--no-bench-filter", dest="benchf",
                    action="store_false",
                    help=f"فیلترِ «از {BENCH} عقب نباشد» را خاموش کن")
    ap.add_argument("--bench-look", type=int, default=BENCH_LOOK,
                    help=f"پنجرهٔ مقایسه با {BENCH}؛ پیش‌فرض "
                         f"{BENCH_LOOK} روز (اندازه‌گیری‌شده — ۲۰ روز "
                         f"برعکس عمل می‌کند)")
    ap.add_argument("--risk-cap", type=float, default=0.0,
                    help="سقفِ ریسکِ کلِ سبد به درصد؛ ۰ یعنی بی‌قید "
                         "(پیش‌فرض — اندازه‌گیری‌شده)")
    ap.add_argument("--adopt", action="store_true",
                    help="سفارشِ امروز را به‌عنوانِ سبدِ فعلی ثبت کن "
                         "(بعد از اجرای واقعیِ معاملات)")
    ap.add_argument("--rebase", action="store_true",
                    help="لنگرِ قطب‌نما را به امروز منتقل کن")
    ap.add_argument("--now", action="store_true",
                    help="وضعیت را روی **آخرین** کلوز حساب کن، نه روی "
                         "کلوزِ روزِ تصمیم (رفتارِ قبلی)")
    ap.add_argument("--offline", action="store_true",
                    help="دانلود نکن، از دادهٔ ذخیره‌شده استفاده کن")
    args = ap.parse_args()
    if args.probe:
        return probe()
    if args.sample:
        return sample()
    if args.max_invested is not None:
        MAX_INVESTED = args.max_invested
    if args.max_weight is not None:
        MAX_WEIGHT = args.max_weight
    REQUIRE_CUR_MONTH = args.curmonth

    # ── --all: هر دو جهان، بعد یک گزارشِ ترکیبی ────────────────────
    # قبل از هر کارِ دیگری، چون این اجرا خودش دو زیرفرایند می‌سازد و
    # نباید گلوبال‌های اینجا را دست بزند.
    if args.run_all:
        # --adopt عمداً اینجاست: اگر به زیرفرایندها برود، اجرای
        # صندوق سبدِ صندوق را ثبت می‌کند و اجرای سهام سبدِ سهام را،
        # در **دو فایلِ جدا** — و مدلِ «یک پرتفو، یک سرمایه» می‌شکند.
        # سبدِ ترکیبی آخرِ کار یک‌جا ثبت می‌شود.
        drop = {"--all", "--stocks", "--export", "--no-open",
                "--stock-share", "--adopt"}
        passthru, skip = [], False
        for a in sys.argv[1:]:
            if skip:
                skip = False
                continue
            if a in drop:
                skip = a in ("--export", "--stock-share")
                continue
            if a.split("=")[0] in drop:
                continue
            passthru.append(a)
        return run_all(passthru, args.stock_share, args.open,
                       args.adopt)

    STOCK = args.stocks
    LIVE_STATE = args.now
    BOX_KIND = args.box
    BENCH_FILTER = args.benchf
    BENCH_LOOK = args.bench_look
    if args.min_value is not None:
        MIN_VALUE_BN = args.min_value
    if STOCK:
        # جهانِ جدا، دادهٔ جدا، خروجیِ جدا. قاطی شدنشان یعنی جدولِ
        # صندوق‌ها کنارِ سهم بنشیند — همان چیزی که نباید بشود.
        DATA = HERE / "data_stocks"
        OUT = HERE / "dashboard_stocks.html"
        # و مبنای سنجش هم عوض می‌شود: کهربا صندوق طلاست و در جهانِ
        # سهام مرجعِ بی‌ربطی است. مصطفی: «ملاکِ تصمیم‌گیریِ آن بر
        # اساس شاخص کل و شاخص کل هم‌وزن خواهد بود.»
        BENCH = BENCH_STOCK
    if args.rebase:
        # بعد از تعیینِ DATA، وگرنه در حالتِ سهام پوشهٔ صندوق‌ها را
        # پاک می‌کرد.
        for f in ("baseline.json", "track.csv"):
            (DATA / f).unlink(missing_ok=True)
        print("      لنگرِ قطب‌نما پاک شد — از امروز دوباره شروع می‌شود.")

    print("=" * 64)
    print("  بورس — تک‌فایل" + ("  ·  حالتِ سهام" if STOCK else ""))
    print("=" * 64)

    if not args.offline:
        print("\n[۱/۴] پیدا کردن نمادها از دیدبان بازار...")
        sectors = {}
        try:
            ins, sectors = (discover_stocks(MIN_VALUE_BN) if STOCK
                            else (discover(), {}))
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
        if STOCK:
            (DATA / "sectors.json").write_text(
                json.dumps(sectors, ensure_ascii=False), encoding="utf-8")
            print("      فهرستِ سهام: "
                  + "، ".join(sorted(ins)[:25])
                  + (f" … (+{len(ins) - 25})" if len(ins) > 25 else ""))

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

        # قیمتِ نمادهای غیرصندوقیِ پرتفو — فقط برای ارزش‌گذاری
        hpx = {}
        for sym, code in HOLD_INS.items():
            if norm(sym) not in NORM_HOLD:
                continue
            try:
                hr = fetch_symbol(sym, code)
                if hr:
                    hpx[sym] = hr[-1]["c"]
            except Exception:                        # noqa: BLE001
                pass
            time.sleep(0.25)
        if hpx:
            (DATA / "hold_px.json").write_text(
                json.dumps(hpx, ensure_ascii=False), encoding="utf-8")
            print(f"      قیمتِ {len(hpx)} نمادِ غیرصندوقیِ پرتفو گرفته شد")
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
    wrong = 0
    for p in sorted(DATA.glob("*.csv")):
        sym = p.stem
        if sym == "capital" or norm(sym) in NORM_FIXED:
            continue
        # نگهبانِ اختلاطِ دو جهان: اگر فایلِ صندوقی در پوشهٔ سهام
        # جا مانده باشد (یا برعکس)، بی‌صدا به‌عنوانِ عضوِ آن جهان
        # تحلیل می‌شد و جدولِ بک‌تست هم آلوده می‌شد.
        if STOCK and norm(sym) in NORM_CAT:
            wrong += 1
            continue
        k = norm(sym)
        cur = best.get(k)
        if cur is None or p.stat().st_size > cur.stat().st_size:
            best[k] = p

    if wrong:
        print(f"      {wrong} فایلِ صندوقی در {DATA.name} نادیده گرفته شد "
              f"(جهانِ سهام است).")
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

    # ── دستهٔ سهام: گروهِ صنعت، وگرنه ردهٔ ارزشِ معاملات ────────────
    # جدولِ CATEGORY همه‌اش صندوق است، پس بدونِ این همهٔ سهام‌ها در یک
    # گروهِ «بدون دسته» می‌افتادند و تفکیکی که مصطفی خواسته بود از بین
    # می‌رفت («صندوق‌ها تفکیک شده باشن، این‌جوری ردیفی‌ان»).
    if STOCK:
        sf = DATA / "sectors.json"
        sec = {}
        if sf.exists():
            try:
                sec = {norm(k): v for k, v in
                       json.loads(sf.read_text(encoding="utf-8")).items()}
            except ValueError:
                sec = {}
        if sec:
            for r in rows:
                r["cat"] = sec.get(norm(r["sym"]), "سایر")
        else:
            vals = sorted((r["value_bn"] for r in rows if r["value_bn"]),
                          reverse=True)
            if vals:
                t1 = vals[len(vals) // 3]
                t2 = vals[2 * len(vals) // 3]
                for r in rows:
                    v = r["value_bn"]
                    r["cat"] = ("درشت" if v >= t1 else
                                "متوسط" if v >= t2 else "کوچک")

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
        # ── در جهانِ سهام، درآمد ثابت اصلاً نباید باشد ───────────────
        # مصطفی: «صندوق‌های درآمد ثابت هم آوردی جزوشون. بزرگ هستند ولی
        # از سهام جداشان کن، اینها غیرواقعی‌اند.»
        #
        # `FIXED_INCOME` یک فهرستِ اسمی است و کامل نیست — بورسِ ایران
        # ده‌ها صندوقِ درآمد ثابت دارد و ارزشِ معاملاتشان هم بالاست،
        # پس از فیلترِ حجم رد می‌شوند و بالای جدول می‌نشینند.
        #
        # فیلترِ درست همان قاعدهٔ **نسبیِ** نوسان است (بند ۰ قانون ۳)
        # که زیتون و شیلد را هم گرفت. در حالتِ صندوق فقط از دفتر کنار
        # می‌روند و در جدول می‌مانند (تا بدانی کجایند)؛ در حالتِ سهام
        # اصلاً عضوِ جهان نیستند، پس **حذف** می‌شوند.
        if STOCK and npark:
            gone = sorted(r["sym"] for r in rows if r.get("park"))
            rows = [r for r in rows if not r.get("park")]
            print(f"      از جهانِ سهام حذف شدند: "
                  + "، ".join(gone[:18])
                  + (f" … (+{len(gone) - 18})" if len(gone) > 18 else ""))
            if not rows:
                print("      هیچ سهمی نماند — --min-value را کم کن.")
                return 1

    # ── در حالتِ سهام، جدولِ نرخِ برد را از خودِ سهام بساز ───────────
    # WINRATE از بک‌تستِ ۱۲۱ **صندوق** آمده. نشان دادنش کنارِ وبملت
    # یعنی آمارِ یک جهان را به جهانِ دیگر نسبت دادن. پس دوباره ساخته
    # می‌شود، با همان تعریف‌ها، و p هر سطر هم چاپ می‌شود.
    if STOCK:
        print("\n      بک‌تستِ سهام (ممکن است چند دقیقه طول بکشد)...")
        hist = {r["sym"]: load(r["sym"]) for r in rows if r.get("ok")}
        hist = {k: v for k, v in hist.items() if len(v) >= MIN_DAYS}
        tab = backtest_universe(hist, iters=args.iters)
        if tab.get("week") and tab.get("month"):
            WINRATE = tab
            print(f"      جدول از {len(hist)} سهم ساخته شد.")
            for hz, fa in (("week", "هفتگی"), ("month", "ماهانه")):
                t = tab[hz]
                b = t.get("_base")
                if not b:
                    continue
                print(f"\n      ── {fa} · نرخ پایه {b[2]:+.2f}٪ · "
                      f"{b[1]}٪ مثبت · n={b[0]:,} ──")
                print(f"      {'وضعیت':<18}{'n':>7}{'برد':>7}"
                      f"{'میانگین':>10}{'مزیت':>9}{'p':>9}")
                for k, v in sorted(t.items(),
                                   key=lambda kv: -(kv[1][1]
                                                    if isinstance(kv[1], tuple)
                                                    else 0)):
                    if k.startswith("_"):
                        continue
                    pv = t.get("_p", {}).get(k)
                    star = " ★" if pv is not None and pv < 0.05 else ""
                    print(f"      {k:<18}{v[0]:>7,}{v[1]:>6}٪"
                          f"{v[2]:>+9.2f}٪{v[2] - b[2]:>+9.2f}"
                          f"{(f'{pv:.4f}' if pv is not None else '—'):>9}"
                          f"{star}")
            print("\n      ★ = از نرخ پایهٔ همان دوره جدا شد "
                  "(آزمونِ جایگشتِ درون‌دوره‌ای).")
            print("      بدونِ ★ یعنی از تصادف جدا نشد — "
                  "عددِ برد به‌تنهایی سیگنال نیست.")
        else:
            print("      ⚠️  بک‌تست نشد (دادهٔ کم). "
                  "جدولِ صندوق‌ها **استفاده نمی‌شود**.")
            WINRATE = {"week": {}, "month": {}}

    stamp = max(r["date"] for r in rows)
    print(f"      {len(rows)} نماد · کلوز {stamp}")

    # نقشهٔ قیمتِ امروز — قطب‌نما و فهرستِ خرید/فروش هر دو لازمش دارند
    PX = {norm(r["sym"]): r["close"] for r in rows}
    if STOCK:
        # شاخص «نماد» نیست و در دیدبان قیمت ندارد، ولی قطب‌نما یک
        # عددِ مبنا لازم دارد. سطحِ شاخص از همان سریِ روزانه می‌آید.
        for nm in BENCH_IDX:
            ser = idx_series(nm)
            if ser:
                PX[norm(nm)] = ser[max(ser)]
    hpf = DATA / "hold_px.json"
    if hpf.exists():
        try:
            for k, v in json.loads(hpf.read_text(encoding="utf-8")).items():
                PX[norm(k)] = v
        except ValueError:
            pass

    capfile = DATA / "capital.txt"
    capital = args.capital
    if not capital and capfile.exists():
        try:
            capital = float(capfile.read_text(encoding="utf-8").strip()
                            .replace(",", ""))
        except ValueError:
            capital = 0
    if not capital:
        # ── سرمایه را از خودِ پرتفو حساب کن، نه یک عددِ ساختگی ──────
        # قبلاً اینجا «یک میلیارد» فرض می‌شد و بی‌صدا رد می‌شد. ولی
        # capital مخرجِ «ریسکِ کل» و «نقد» است، پس عددِ ساختگی یعنی دو
        # کاشیِ داشبورد غلط — و غلط‌بودنشان از روی صفحه معلوم نیست.
        # حالا: ارزشِ روزِ آنچه داریم + نقد.
        px = {r["sym"]: r["close"] for r in rows}
        hf = DATA / "hold_px.json"
        if hf.exists():
            try:
                px.update(json.loads(hf.read_text(encoding="utf-8")))
            except ValueError:
                pass
        hu, hc = holdings_load()
        have, miss = port_value(hu, 0.0, PX)
        capital = have + hc
        capfile.parent.mkdir(exist_ok=True)
        capfile.write_text(str(int(capital)), encoding="utf-8")
        print(f"\n      سرمایه از پرتفو حساب شد: "
              f"{have / 1e9:,.1f} سهام + {hc / 1e9:,.1f} نقد "
              f"= {capital / 1e9:,.1f} میلیارد ریال")
        if miss:
            # نمادِ غیرصندوقی در دیدبانِ صندوق‌ها نیست، پس ارزشش
            # شمرده نشده و سرمایه **کم‌برآورد** است. سکوت نکن.
            print(f"      ⚠️  قیمتِ {'، '.join(miss)} پیدا نشد — "
                  f"سرمایه کم‌برآورد است.")
            print(f"      عددِ درست را در {capfile} بنویس یا "
                  f"--capital بده.")

    # محرک **قبل از** مبنا، چون در حالتِ سهام مبنای هر نماد از
    # محرکِ اندازه‌گیری‌شده‌اش می‌آید (`bench_for`).
    DRV = drv_attach(rows)
    if not DRV.get("ok"):
        print(f"      ⚠️  محرک‌ها خوانده نشدند ({DRV.get('why')}) — "
              f"رتبه‌بندی فقط با مازادِ کهرباست.")
    else:
        nd = sum(1 for r in rows if r.get("drv"))
        print(f"      محرک‌ها: {DRV['n']} سری تا {DRV['date']} · "
              f"{nd} از {len(rows)} نماد محرکِ روشن دارند")
        if DRV.get("stale"):
            print(f"      ⚠️  دادهٔ محرک {DRV['lag']} روز از کلوزِ "
                  f"نمادها عقب است — «پاسخِ محرک» کهنه است.")
    bench_excess(rows)
    if STOCK:
        nb = defaultdict(int)
        for r in rows:
            if r.get("bench"):
                nb[r["bench"]] += 1
        if nb:
            print("      مبنای سنجش: "
                  + " · ".join(f"{k} {v}" for k, v in sorted(nb.items())))
    elig, book = build_book(rows, capital)

    # ── بازرس: هیچ ردیفی که ثابت‌های دفتر را نقض کند نباید رد شود ──
    book, bad = audit(rows, book)
    if bad:
        print("\n" + "!" * 64)
        print(f"  ⛔ بازرس {len(bad)} ردیف را از دفتر بیرون انداخت:")
        for sym, why in bad:
            print(f"     {sym}")
            for w in why:
                print(f"       ↳ {w}")
        print("  این یعنی یک مسیر در build_book درست کار نکرده.")
        print("  همین متن را بفرست تا ریشه‌اش را پیدا کنم.")
        print("!" * 64)
    else:
        print(f"      بازرسِ دفتر: {len(book)} ردیف، همه سالم ✓")
    hot = [r for r in rows if r.get("ok")
           and (r["week"]["state"] == "در نوار"
                or r["month"]["state"] == "در نوار")]

    print("\n[۴/۴] ساخت صفحه...")
    y, mo, dd = (int(x) for x in stamp.split("-"))
    last_date = date(y, mo, dd)
    # ── قطب‌نما و فهرستِ خرید/فروش ─────────────────────────────────
    hu, hc = holdings_load()
    comp = compass(PX, hu, hc, stamp)
    sells, buys, nopx = rebalance(hu, hc, book, PX, capital)
    pos = positions(rows, hu, PX)
    # سقفِ اختیاریِ ریسکِ کلِ سبد. پیش‌فرض خاموش است، چون اندازه‌گیری
    # نشان داد هم بازده و هم افتِ سرمایه را بدتر می‌کند.
    if args.risk_cap:
        pr = sum(r["w"] * r["z"]["risk_pct"] / 100 for r in book
                 if not r.get("hold_only"))
        if pr > args.risk_cap:
            k = args.risk_cap / pr
            bfill = 0.0
            for r in book:
                if r.get("hold_only"):
                    continue
                cut = r["w"] * (1 - k)
                r["w"] -= cut
                bfill += cut
                r["amt"] = capital * r["w"] / 100
                r["units"] = r["amt"] / r["z"]["aim"]
                r["loss"] = r["amt"] * r["z"]["risk_pct"] / 100
            print(f"\n      ⚠️  سقفِ ریسکِ {args.risk_cap:.1f}٪ اعمال شد "
                  f"({pr:.1f}٪ → {args.risk_cap:.1f}٪).")
            print("      اندازه‌گیری: این کار در ۳۵ هفته هم بازده را کم")
            print("      کرد (۱٫۱۵۲ → ۱٫۰۴۵) و هم افتِ سرمایه را بیشتر")
            print("      (−۷٫۲٪ → −۹٫۵٪). با حذفِ --risk-cap برمی‌گردد.")

    if args.adopt:
        # سفارشِ دفتر را به‌عنوانِ سبدِ فعلی ثبت کن — بعد از اینکه
        # واقعاً اجرایش کردی. از فردا قطب‌نما همین را دنبال می‌کند.
        nu = {r["sym"]: round(r["units"]) for r in book}
        inv = sum(r["w"] for r in book)
        holdings_save(nu, capital * max(0.0, 100 - inv) / 100)
        print("\n      ✓ سبد ثبت شد در " + str(DATA / "holdings.json"))
        print("      ⚠️ این **سبدِ هدف** است، نه آنچه واقعاً پر شد.")
        print("         اگر سفارشی نخورد یا جزئی پر شد، فایل را دستی")
        print("         درست کن — وگرنه قطب‌نما و مازادِ واحد از فردا")
        print("         غلط می‌شوند.")
        for k, v in nu.items():
            print(f"        {k:<10}{v:>14,} واحد")

    # ── مازادِ واحدِ کهربا — هدفِ نهایی ─────────────────────────────
    BU = bench_units(rows, hu)
    if BU:
        print("\n" + "=" * 64)
        print(f"  تعدادِ واحدِ {BENCH} — مازادِ من")
        print("=" * 64)
        d = BU["dates"]
        print("\n  مجموعِ پرتفو:")
        for fa, hz in UNIT_HZ:
            v = BU["port"].get(hz)
            a = d.get(hz)
            if v is None:
                print(f"    {fa:<8}—  (دادهٔ کافی نیست)")
                continue
            w = "جلو ▲" if v > 0 else "عقب ▼" if v < 0 else "هم‌پا"
            print(f"    {fa:<8}{v:>+7.2f}٪  {w:<7}"
                  + (f"از {a[0]} تا {a[1]}" if a else ""))
        mine = [r for r in BU["sym"] if r["held"]]
        if mine:
            print(f"\n  به تفکیکِ نماد  ({'، '.join(fa for fa, _ in UNIT_HZ)}):")
            print(f"    {'نماد':<11}{'واحدِ من':>13}{'روزانه':>9}"
                  f"{'هفتگی':>9}{'ماهانه':>9}{'۴۰ روزه':>10}")
            print("    " + "-" * 60)
            for r in mine:
                def f(x):
                    return "—" if x is None else f"{x:+.2f}"
                bxs = ("—" if r.get("bx") is None else f"{r['bx']:+.1f}")
                print(f"    {r['sym']:<11}{r['held']:>13,}"
                      f"{f(r['d']):>9}{f(r['w']):>9}{f(r['m']):>9}"
                      f"{bxs:>10}")
        gone = set()
        for v in (BU.get("miss") or {}).values():
            gone |= set(v)
        if gone:
            print(f"\n  ⚠️  {'، '.join(sorted(gone))} در این جهان "
                  f"قیمت ندارند و از **مجموع** بیرون ماندند —")
            print("      عددِ کل کم‌برآورد است. با --all یا آنلاین می‌آیند.")
        print("\n  تعریف: (۱+بازدهِ نماد) ÷ (۱+بازدهِ کهربا) − ۱")
        print(f"  لنگرِ هفتگی = آخرین کلوزِ هفتهٔ کامل‌شدهٔ قبل · "
              f"ماهانه = آخرین کلوزِ ماهِ قبل")

    # ── چه چیزی امروز عوض شد ───────────────────────────────────────
    DSTAMP, DIF = state_diff(rows, book, hu, stamp)
    if DIF:
        print("\n" + "=" * 64)
        print(f"  چه چیزی عوض شد — {DSTAMP} → {stamp}")
        print("=" * 64)
        mine, rest = diff_split(DIF, book)
        if not mine:
            print("\n  روی نمادهای من و دفتر: هیچ تغییری نبود.")
        for e in mine:
            mark = {"r": "⛔", "y": "⚠️ ", "g": "🟢"}[e["col"]]
            hold = " (داری)" if e["held"] else ""
            pc = ((e["close"] / e["was"] - 1) * 100
                  if e.get("was") else None)
            # n() داخلِ html() تعریف شده، اینجا نیست
            print(f"  {mark} {e['sym']:<11}{e['lab']:<34}"
                  f"{e['close']:>12,.0f}"
                  + (f"  {pc:+.2f}٪" if pc is not None else "")
                  + hold)
        if rest:
            bad = sum(1 for e in rest if e["col"] == "r")
            good = sum(1 for e in rest if e["col"] == "g")
            print(f"\n  بقیهٔ جهان: {len(rest)} تغییر "
                  f"({bad} منفی · {good} مثبت) — در تبِ «تصمیمِ امروز».")
    elif DSTAMP:
        print(f"\n  ✓ از {DSTAMP} تا {stamp} هیچ نمادی وضعیتش عوض نشد.")
    else:
        print("\n  (عکسِ دیروز نبود، پس «چه چیزی عوض شد» حساب نشد — "
              "از اجرای بعد.)")
    state_save(stamp, rows, book)

    rr = risk_report(book, pos, capital, comp)
    buy, sell = alarms(rows, book, hu)
    OUT.write_text(html(rows, book, capital, stamp, last_date,
                        buy, sell, comp, sells, buys, nopx, pos, rr,
                        DRV, BU, DIF, DSTAMP),
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
            if r.get("hold_only"):
                # پرکننده: نه ورودی، نه استاپی. چاپِ آن سه عدد همان
                # چیزی بود که در ترمینال هم پیشنهادِ خرید می‌نمود.
                print(f"  {r['sym']:<10}{'نگه‌دار':<8}"
                      f"{'—':>12}{'—':>12}{'—':>12}{'—':>7}"
                      f"{r['units']:>13,.0f}")
            else:
                print(f"  {r['sym']:<10}"
                      f"{'هفتگی' if r['band']=='week' else 'ماهانه':<8}"
                      f"{z['aim']:>12,.0f}{z['stop']:>12,.0f}"
                      f"{z['target']:>12,.0f}{z['risk_pct']:>6.1f}٪"
                      f"{r['units']:>13,.0f}")
        if any(r.get("hold_only") for r in book):
            print("\n  ⚠️  امروز هیچ نمادی واجد شرطِ خرید نیست.")
            print("      ردیف‌های «نگه‌دار» سیگنال نیستند — قاعدهٔ")
            print("      «هرگز نقد نشو» آن‌ها را نگه می‌دارد. نخر.")
        # ── آهنگِ آپدیت ────────────────────────────────────────────
        # مصطفی: «پرتفوی هدفِ روزانه ساخته می‌شود بر اساسِ نواحی هفتگی
        # و ماهانه، که ماهانه فقط در پایانِ ماه است ولی هفتگی می‌بایست
        # آپدیت شود.» این را صریح بنویس تا معلوم باشد کدام عدد تا کی
        # ثابت می‌ماند.
        nw = len([r for r in book if r["band"] == "week"])
        nm = len(book) - nw
        nxt_w = (DECIDE_FUND - last_date.weekday()) % 7 or 7
        print(f"\n  آهنگِ آپدیت: {nw} قلم روی نوارِ **هفتگی** "
              f"(تا {nxt_w} روزِ دیگر ثابت) · "
              f"{nm} قلم روی نوارِ **ماهانه** (تا پایانِ ماه ثابت).")
        print("  پرتفوی هدف هر روز بازسازی می‌شود، ولی نوارِ ماهانه فقط")
        print("  اولِ ماهِ میلادی عوض می‌شود — بند ۲ راهنما.")
        cash_pct = max(0.0, 100 - sum(r["w"] for r in book))
        print(f"\n  نقد: {cash_pct:.0f}٪")
        # ── تمرکزِ دسته ────────────────────────────────────────────
        # قاعدهٔ انتخاب دیگر «یکی از هر دسته» نیست (اندازه‌گیری نشان داد
        # آن قید ضرر می‌دهد)، پس ممکن است کلِ دفتر یک دسته شود. این
        # شرط‌بندیِ متمرکز است و باید **دیده** شود، نه اینکه در جدول
        # پنهان بماند.
        from collections import Counter as _C
        cc = _C()
        for r in book:
            cc[r["cat"]] += r["w"]
        if cc:
            top, tw = cc.most_common(1)[0]
            if tw >= 60:
                print(f"\n  ⚠️  {tw:.0f}٪ دفتر در یک دسته است: «{top}».")
                print("      قاعدهٔ انتخاب عمداً قیدِ تنوع ندارد — اندازه‌گیری")
                print("      نشان داد هر قیدِ تنوع از کهربا عقب می‌اندازد")
                print("      (۱٫۰۱۳ با قیدِ «یکی از هر دسته» در برابرِ ۱٫۱۵۲).")
                print("      ولی این یعنی کلِ سبد یک شرط است. خودت ببین.")

    # ── پوزیشن‌های فعلی: حد ضرر و حد سود ──────────────────────────
    if pos:
        print("\n" + "=" * 64)
        print("  پوزیشن‌های فعلی — حد ضرر و حد سود (آپدیتِ امروز)")
        print("=" * 64)
        hit = [x for x in pos if x["below"]]
        if hit:
            print("\n  ⛔ کندلِ دیلی زیرِ ناحیه بسته — فردا فروشنده‌ایم:")
            for x in hit:
                print(f"     {x['sym']:<10} کلوز {x['px']:>12,.0f} · "
                      f"کفِ ناحیه {x['zone_lo']:>12,.0f} "
                      f"({x['dist_stop']:+.1f}٪)")
            print("     اندازه‌گیری: صبر تا فردا ۰٫۱۹ واحد و صبر برای")
            print("     پولبک ۰٫۳۰ واحد بدتر از خروجِ همین امروز است.")
            print("     ولی خروج = **چرخش**، نه نقد شدن.")
        print(f"\n  {'نماد':<10}{'واحد':>13}{'کلوز':>12}"
              f"{'حد ضرر':>12}{'فاصله':>8}   حد سود (پرچم)")
        print("  " + "-" * 84)
        for x in pos:
            mark = " <" if x["below"] else ""
            fl = x["flag"]
            tgt = ("{:,.0f}  ({:+.0f}% . {})".format(
                fl["target"], fl["up_pct"], fl["scale"])
                if fl else "-- شکستِ ناحیه")
            print(f"  {x['sym']:<10}{x['units']:>13,.0f}{x['px']:>12,.0f}"
                  f"{x['zone_lo']:>12,.0f}{x['dist_stop']:>+7.1f}٪   "
                  f"{tgt:<26}{mark}")
        print("\n  حد سود دو اصل دارد:")
        print("    ۱. شکستِ ناحیه — همان حد ضرر. برای پوزیشنی که در")
        print("       سود است، خروج روی شکستِ ناحیه یعنی سیو سود.")
        print("    ۲. تارگتِ میله و پرچم، اگر هنوز نخورده باشد.")
        print("  تارگتِ ۱:۱ اینجا نیست: از نوارِ ورود حساب می‌شود و")
        print("  برای پوزیشنی که از نوار گذشته عددی پشتِ سر است.")

    # ── ریسک منیجر ────────────────────────────────────────────────
    if rr.get("port_risk") is not None:
        print("\n" + "=" * 64)
        print("  ریسک منیجر")
        print("=" * 64)
        print(f"\n  اگر همهٔ استاپ‌ها بخورند: "
              f"{rr['port_risk']:.2f}٪ سرمایه = "
              f"{rr['rial'] / 1e6:,.0f} میلیون ریال")
        w = rr.get("worst")
        if w:
            print(f"  سنگین‌ترین قلم: {w['sym']} — وزنِ {w['w']:.0f}٪ × "
                  f"ریسکِ {w['z']['risk_pct']:.1f}٪ = "
                  f"{w['w'] * w['z']['risk_pct'] / 100:.2f}٪ سرمایه")
        c = rr.get("conc")
        if c:
            print(f"  تمرکز: {c[1]:.0f}٪ در دستهٔ «{c[0]}»")
        if rr.get("dd") is not None and rr.get("dd_n", 0) >= 3:
            print(f"  بیشینه افتِ واقعی تا حالا: {rr['dd']:.1f}٪ "
                  f"({rr['dd_n']} روز)")
        print("\n  ⚠️ هیچ قیدِ ریسکی تحمیل نشده، و دلیلش اندازه‌گیری است:")
        print("     وزن‌دهیِ وارونِ ریسک   ۱٫۱۵۲ → ۱٫۰۳۴")
        print("     سقفِ ریسکِ هر نماد ۵٪   ۱٫۱۵۲ → ۰٫۸۱۳")
        print("     سقفِ ریسکِ کلِ سبد ۵٪    ۱٫۱۵۲ → ۱٫۰۴۵، و افت از")
        print("                            −۷٫۲٪ به −۹٫۵٪ **بدتر** شد")
        print("     سقف پول را می‌برد روی کهربا، و کهربا در این پنجره")
        print("     افتِ بیشتری از سبدِ شش‌تایی داشت. با --risk-cap N")
        print("     می‌شود تحمیلش کرد.")

    # ── دقیقاً چه بفروش، چه بخر ───────────────────────────────────
    if sells or buys:
        print("\n" + "=" * 64)
        print("  از سبدِ فعلی به سبدِ هدف")
        print("=" * 64)
        print("  ترتیب: **اول فروش، بعد خرید** — پولِ آزادشده منبعِ "
              "خریدِ همان صبح است.\n")
        if sells:
            print(f"  ▼ فروش{'':<6}{'واحد':>14}{'قیمت':>12}"
                  f"{'مبلغ (م.ر)':>14}")
            print("  " + "-" * 60)
            for x in sells:
                tag = " (کلِ موجودی)" if x["all"] else ""
                print(f"  {x['sym']:<12}{x['units']:>14,.0f}"
                      f"{x['px']:>12,.0f}{x['amt']/1e6:>14,.0f}{tag}")
            print(f"  {'جمعِ فروش':<12}{'':>14}{'':>12}"
                  f"{sum(x['amt'] for x in sells)/1e6:>14,.0f}")
        if buys:
            print(f"\n  ▲ خرید{'':<6}{'واحد':>14}{'قیمت':>12}"
                  f"{'مبلغ (م.ر)':>14}")
            print("  " + "-" * 60)
            for x in buys:
                tag = " (جدید)" if x["new"] else ""
                print(f"  {x['sym']:<12}{x['units']:>14,.0f}"
                      f"{x['px']:>12,.0f}{x['amt']/1e6:>14,.0f}{tag}")
            print(f"  {'جمعِ خرید':<12}{'':>14}{'':>12}"
                  f"{sum(x['amt'] for x in buys)/1e6:>14,.0f}")
        # ── هزینهٔ گردش، **قبل از** اجرا ───────────────────────
        # قاعدهٔ انتخاب هیسترزیس ندارد: نمادی که از رتبهٔ ۶ به ۷
        # بیفتد کاملاً فروخته می‌شود. بک‌تست همین را دارد و هزینه‌اش
        # را هم حساب کرده (`cost × Σ|Δw| / 2`) — یعنی عددِ ۱٫۱۹۱
        # **خالص** است. ولی روی کاغذ دیده نمی‌شد. حالا می‌شود.
        sv = sum(x["amt"] for x in sells)
        bv = sum(x["amt"] for x in buys)
        if (sv or bv) and capital > 0:
            fee = (COST_STOCK if STOCK else COST_FUND) / 2 / 100
            cost_r = (sv + bv) * fee
            print(f"\n  گردشِ امروز: {(sv + bv)/1e6:,.0f} میلیون ریال "
                  f"= {(sv + bv)/capital*100:.0f}٪ سرمایه")
            print(f"  کارمزدش: ~{cost_r/1e6:,.0f} میلیون ریال "
                  f"({cost_r/capital*100:.2f}٪ سرمایه، با "
                  f"{COST_STOCK if STOCK else COST_FUND}٪ رفت‌وبرگشت)")
            if (sv + bv) / capital > 1.2:
                print("  ⚠️  این یک چرخشِ کامل است. قاعدهٔ انتخاب "
                      "هیسترزیس ندارد —")
                print("      بک‌تست هم همین‌طور بسته شده و هزینهٔ "
                      "گردش در عددش هست.")
                print("      ولی اگر بخشی از فروش و خرید در **یک "
                      "دسته**اند،")
                print("      عملاً داری هزینه می‌دهی تا همان ریسک "
                      "را نگه داری. خودت ببین.")
        if nopx:
            print(f"\n  ⚠️  قیمتِ {'، '.join(nopx)} پیدا نشد، پس در "
                  f"فهرستِ بالا نیستند.")
            print("      این‌ها سهم‌اند نه صندوق؛ در اجرای آنلاین "
                  "قیمتشان گرفته می‌شود.")
            print("      تا آن موقع تکلیفشان در این فهرست روشن نیست.")
        print("\n  بعد از اجرای واقعی، یک بار بزن:  "
              "python bourse.py --adopt")
        print("  تا قطب‌نما از فردا همین سبد را دنبال کند.")

    # ── قطب‌نما ───────────────────────────────────────────────────
    if comp:
        print("\n" + "=" * 64)
        print(f"  قطب‌نما — در برابرِ {BENCH}")
        print("=" * 64)
        if comp["first_day"]:
            print(f"\n  امروز روزِ **لنگر** است ({comp['date']}).")
            print(f"  کلِ پرتفو امروز = {comp['units_base']:,.0f} واحدِ "
                  f"{BENCH}. سؤال از فردا این است که این عدد")
            print("  بیشتر می‌شود یا کمتر.")
            print(f"  سرمایهٔ مبنا {comp['base_capital']/1e9:,.1f} "
                  f"میلیارد ریال · {BENCH} "
                  f"{comp['base_bench_px']:,.0f} ریال")
            print("  عددِ مازاد از **فردا** معنا پیدا می‌کند؛ امروز صفر")
            print("  است و باید صفر باشد.")
        else:
            sign = "جلو" if comp["excess_rial"] >= 0 else "عقب"
            ud = comp["units_d"]
            print(f"\n  ══ تعدادِ واحدِ {BENCH} ══")
            print(f"  روزِ لنگر   {comp['units_base']:>14,.0f} واحد")
            print(f"  امروز      {comp['units_now']:>14,.0f} واحد")
            print(f"  تغییر      {ud:>+14,.0f} واحد "
                  f"({comp['units_pct']:+.2f}٪)  ← "
                  f"{'بیشتر شد ✓' if ud >= 0 else 'کمتر شد ✗'}")
            print(f"\n  از {comp['base_date']} تا {comp['date']} "
                  f"({comp['days']} روز)\n")
            print(f"  {'پرتفو':<14}{comp['port']/1e9:>10,.2f} م‌لیارد"
                  f"{comp['port_pct']:>+10.2f}٪")
            print(f"  {BENCH:<14}{comp['bench']/1e9:>10,.2f} م‌لیارد"
                  f"{comp['bench_pct']:>+10.2f}٪")
            print("  " + "-" * 46)
            print(f"  {'مازاد':<14}"
                  f"{comp['excess_rial']/1e9:>+10,.2f} م‌لیارد"
                  f"{comp['excess_pct']:>+10.2f}٪   ← {sign}")
            print(f"\n  امروز: {comp['day_pnl']/1e6:>+,.0f} م.ر "
                  f"({comp['day_pct']:+.2f}٪) · "
                  f"{BENCH} {comp['day_bench_pct']:+.2f}٪ · "
                  f"مازادِ امروز {comp['day_pct']-comp['day_bench_pct']:+.2f}"
                  f" واحد")
            if comp["sd"] is not None:
                print(f"  انحرافِ معیارِ مازادِ روزانه: {comp['sd']:.2f} واحد")
        if comp["missing"]:
            print(f"\n  ⚠️  قیمتِ {'، '.join(comp['missing'])} پیدا نشد — "
                  f"ارزشِ پرتفو کم‌برآورد است.")
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
                if r.get("hold_only"):
                    txt += (f"\n• <b>{r['sym']}</b> — نگه‌دار "
                            f"(سیگنالِ خرید نیست)")
                else:
                    txt += (f"\n• <b>{r['sym']}</b> ورود {z['aim']:,.0f} | "
                            f"استاپ {z['stop']:,.0f} | "
                            f"ریسک {z['risk_pct']:.1f}%")
        txt += "\n\nخوانشِ قاعده‌های خودت روی داده، نه توصیهٔ مالی."
        print("\n  تلگرام:", "رفت" if telegram(txt) else "نرفت")

    if args.export:
        snap_write(args.export, stamp, capital, hu, hc, book, pos,
                   buy, sell, sells, buys, nopx, PX, comp, BU,
                   DIF, DSTAMP)
        print(f"      عکسِ اجرا: {args.export}")

    if args.open and not args.export:
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
