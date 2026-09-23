# -*- coding: utf-8 -*-
"""واکنشِ **بارِ اول** به ناحیهٔ خلای حجمی — ادعای مصطفی دربارهٔ طلا.

او بعد از دیدنِ نتیجهٔ `docs/24` گفت:

> «به پولبک می‌توانی توجه نکنی… اینجا فقط می‌تواند تأییدیهٔ روندِ مثبت
> یا نزولی را بگیرد. ولی روی صندوق‌های طلا من خیلی تست کردم — روی
> خیلی از صندوق‌های طلا مثل عیار و کهربا — به‌عنوانِ ناحیهٔ
> حمایتی/مقاومتی **یک بار** واکنش را می‌دهد، معمولاً وقتی بهشان برسد.»

این با آزمونِ `docs/24` **یکی نیست** و آنجا اندازه‌گیری نشده بود. سه
فرقِ اساسی:

| | docs/24 | اینجا |
|---|---|---|
| جهان | همهٔ نمادها با هم | **فقط طلا** (و بقیه به‌عنوانِ کنترل) |
| لمس‌ها | همه در یک کاسه | **شمارهٔ لمس**: اول / دوم / سوم به بعد |
| معیار | بازدهِ n کندلِ بعد | **واکنشِ همان کندل** + دوامِ ناحیه + بازده |

آزمونِ قبلی می‌توانست ادعای او را پنهان کند: اگر بارِ اول واکنش بدهد
و بارهای بعد ندهند، میانگینِ همه‌شان چیزی نشان نمی‌دهد.

## تعریف‌ها

    باکس: آخرین خلای حجمیِ تأییدشده (کندلِ g با v[g] < v[g±1])؛
          چون تأییدش به کندلِ g+1 است، برای تصمیم روی i باید g+1 < i
    شکست: کلوزِ بعد از تأیید، بالای سقفِ باکس
    لمس:  کندلی که کفش ≤ سقفِ باکس می‌آید (از بالا وارد ناحیه می‌شود)
    شمارهٔ لمس: از ۱ شروع، با هر باکسِ تازه ریست می‌شود

    واکنشِ کندل  = کلوزِ همان کندل دوباره بالای سقفِ باکس بست
    ناحیه دوام آورد = کفِ کندل زیرِ **کفِ** باکس نرفت
    بازده         = کلوزِ کندلِ بعد نسبت به کلوزِ کندلِ لمس

دورهٔ ناقصِ جاری (هفته/ماهِ نیمه‌تمام) کنار می‌رود — حجمش کامل نیست.
"""
import argparse
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from monthly_backtest import load_daily, is_fixed_income, norm  # noqa: E402
from vgap import resample  # noqa: E402

ITERS = 2000

GOLD = ("ریتون زر زرفام زروان زرگر زریران زمرد طلا عیار قلک گلد قیراط "
        "لیان مثقال مهرگلد میراث ناب نفیس نگین فارس همیان کهربا گلدا "
        "گلدیس گنج گوهر").split()
NORM_GOLD = {norm(x) for x in GOLD}


def touches(bars, horizon):
    """([(شمارهٔ لمس، واکنش؟، دوام؟، بازده)], [ایندکسِ کندلِ لمس])"""
    out, idx = [], []
    g = None            # ایندکسِ باکسِ فعال
    broke = False       # شکستِ رو به بالا تأیید شده؟
    cnt = 0             # چندمین لمس از این باکس
    for i in range(2, len(bars) - horizon):
        # باکسِ تازه؟ کندلِ i-2 وقتی i-1 بسته شد خلا بودنش معلوم شد
        j = i - 2
        if (j >= 1 and bars[j].v < bars[j - 1].v
                and bars[j].v < bars[j + 1].v and j != g):
            g, broke, cnt = j, False, 0
        if g is None:
            continue
        lo, hi = bars[g].l, bars[g].h
        if not broke:
            if bars[i - 1].c > hi:
                broke = True
            continue
        if bars[i].l > hi:              # نرسید به ناحیه
            continue
        cnt += 1
        out.append((cnt,
                    bars[i].c > hi,                       # واکنشِ کندل
                    bars[i].l >= lo,                      # ناحیه دوام آورد
                    (bars[i + horizon].c / bars[i].c - 1) * 100))
        idx.append(i)
        if bars[i].c < lo:              # ناحیه شکست — باکس مرد
            g, broke, cnt = None, False, 0
    return out, idx


# ── معیارِ دومی که لازم شد ───────────────────────────────────────────
# «واکنش» روی چارت یعنی کندل فتیله می‌زند توی ناحیه و بالاتر می‌بندد.
# بازدهِ کندلِ بعد این را نمی‌سنجد. معیارِ درست، **جای کلوز در دامنهٔ
# همان کندل** است:  (close − low) / (high − low).
#
# ولی خودش به‌تنهایی بی‌معناست: هر کندلی که عمیق افتاده باشد، به‌طور
# میانگین بالاتر از کفش می‌بندد — این خاصیتِ کندل است نه خاصیتِ ناحیه.
# پس کنترل باید **هم‌عمق** باشد: کندل‌هایی که همان‌قدر زیرِ کلوزِ قبلی
# رفته‌اند ولی هیچ باکسی آنجا نبوده. مقایسه داخلِ هر دهکِ عمق انجام
# می‌شود و بعد وزن‌دار جمع می‌شود.
def cpr(b):
    rng = b.h - b.l
    return (b.c - b.l) / rng if rng > 0 else 0.5


def depth_matched(bars, hit_idx):
    """(واکنشِ لمس‌ها، واکنشِ کنترلِ هم‌عمق، n) — هر دو ۰ تا ۱."""
    hits, ctrl = [], []
    for i in range(1, len(bars)):
        pc = bars[i - 1].c
        if pc <= 0:
            continue
        d = (pc - bars[i].l) / pc * 100
        if d <= 0:
            continue
        (hits if i in hit_idx else ctrl).append((d, cpr(bars[i])))
    return hits, ctrl


def pooled(hits, ctrl, nq=10):
    """میانگینِ اختلافِ واکنش، داخلِ دهک‌های عمق."""
    if len(hits) < 10 or len(ctrl) < 50:
        return None
    ds = sorted(d for d, _ in ctrl)
    cuts = [ds[int(len(ds) * k / nq)] for k in range(1, nq)]

    def q(d):
        k = 0
        while k < len(cuts) and d > cuts[k]:
            k += 1
        return k

    hb, cb = defaultdict(list), defaultdict(list)
    for d, c in hits:
        hb[q(d)].append(c)
    for d, c in ctrl:
        cb[q(d)].append(c)
    def diff(hbx):
        num = den = 0.0
        for k, v in hbx.items():
            if len(cb.get(k, [])) < 5:
                continue
            num += len(v) * (statistics.mean(v) - statistics.mean(cb[k]))
            den += len(v)
        return (num / den, int(den)) if den else None

    real = diff(hb)
    if real is None:
        return None
    # ── p با جایگشتِ **داخلِ هر دهکِ عمق** ──────────────────────────
    # عمق ثابت می‌ماند و فقط برچسبِ «اینجا باکس بود» جابه‌جا می‌شود،
    # پس آنچه می‌ماند فقط اثرِ خودِ ناحیه است.
    rnd = random.Random(11)
    hits_n = {k: len(v) for k, v in hb.items()}
    pool = {k: [c for c in cb.get(k, [])] + list(v) for k, v in hb.items()}
    ge = 0
    for _ in range(ITERS):
        fake = {k: rnd.sample(pool[k], n) for k, n in hits_n.items()
                if len(pool[k]) >= n}
        d = diff(fake)
        if d and d[0] >= real[0]:
            ge += 1
    return real[0], real[1], (ge + 1) / (ITERS + 1)


def show(title, rows, base):
    if not rows:
        print(f"\n  {title}: لمسی نشد.")
        return
    by = defaultdict(list)
    for c, react, held, r in rows:
        by[1 if c == 1 else 2 if c == 2 else 3].append((react, held, r))
    print(f"\n  ══ {title} ══")
    print(f"  نرخ پایهٔ همان نمادها (همهٔ کندل‌ها): {base:+.2f}٪")
    print(f"  {'لمس':<10}{'n':>7}{'واکنشِ کندل':>13}{'دوامِ ناحیه':>13}"
          f"{'بازدهِ بعد':>12}{'مزیت':>8}")
    print("  " + "─" * 63)
    for k in (1, 2, 3):
        v = by.get(k)
        if not v:
            continue
        nm = {1: "بارِ اول", 2: "بارِ دوم", 3: "سوم به بعد"}[k]
        rs = [r for _a, _b, r in v]
        print(f"  {nm:<10}{len(v):>7}"
              f"{sum(1 for a, _b, _r in v if a) / len(v) * 100:>12.0f}٪"
              f"{sum(1 for _a, b, _r in v if b) / len(v) * 100:>12.0f}٪"
              f"{statistics.mean(rs):>+11.2f}٪"
              f"{statistics.mean(rs) - base:>+8.2f}")
    a = [r for _c, _x, _y, r in rows if _c == 1]
    b = [r for _c, _x, _y, r in rows if _c >= 2]
    if len(a) > 5 and len(b) > 5:
        d = statistics.mean(a) - statistics.mean(b)
        va = statistics.pvariance(a) / len(a)
        vb = statistics.pvariance(b) / len(b)
        t = d / ((va + vb) ** 0.5) if va + vb else 0.0
        ra = sum(1 for c, x, _y, _r in rows if c == 1 and x) / len(a) * 100
        rb = sum(1 for c, x, _y, _r in rows if c >= 2 and x) / len(b) * 100
        print(f"\n  اول منهای بعدی‌ها: بازده {d:+.2f} واحد (t={t:+.2f}) · "
              f"واکنشِ کندل {ra - rb:+.0f} واحدِ درصد")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_auto")
    ap.add_argument("--tf", default="day,week")
    ap.add_argument("--horizon", type=int, default=1)
    ap.add_argument("--min-bars", type=int, default=40)
    ap.add_argument("--syms", default=None,
                    help="فهرستِ نماد با کاما؛ پیش‌فرض: طلا در برابر بقیه")
    args = ap.parse_args()

    files = sorted(Path(args.data).glob("*_daily.csv"))
    if not files:
        print(f"فایلی در {args.data} نیست.")
        return 1
    want = ({norm(x.strip()) for x in args.syms.split(",")}
            if args.syms else None)

    print(f"\n  دادهٔ {args.data} · افقِ {args.horizon} کندل")
    for tf in args.tf.split(","):
        fa = {"day": "دیلی", "week": "هفتگی", "month": "ماهانه"}[tf]
        buckets = defaultdict(list)
        react = defaultdict(lambda: ([], []))
        first = defaultdict(lambda: ([], []))
        allret = defaultdict(list)
        nsym = defaultdict(set)
        for f in files:
            name = f.stem.replace("_daily", "")
            k = norm(name)
            if is_fixed_income(k):
                continue
            if want is not None and k not in want:
                continue
            rows = resample(load_daily(f), tf)
            if len(rows) < args.min_bars:
                continue
            bars = [b for _d, b in rows]
            if tf != "day":
                bars = bars[:-1]        # دورهٔ ناقصِ جاری
            grp = ("طلا" if k in NORM_GOLD else "بقیهٔ بازار") \
                if want is None else name
            nsym[grp].add(name)
            tr, ti = touches(bars, args.horizon)
            buckets[grp] += tr
            h, c = depth_matched(bars, set(ti))
            react[grp][0].extend(h)
            react[grp][1].extend(c)
            f1 = {i for (cnt, *_), i in zip(tr, ti) if cnt == 1}
            h1, c1 = depth_matched(bars, f1)
            first[grp][0].extend(h1)
            first[grp][1].extend(c1)
            allret[grp] += [(bars[i + args.horizon].c / bars[i].c - 1) * 100
                            for i in range(len(bars) - args.horizon)]
        print(f"\n{'═' * 66}\n  تایم‌فریمِ {fa}\n{'═' * 66}")
        for grp in sorted(buckets, key=lambda g: (g != "طلا", g)):
            base = statistics.mean(allret[grp]) if allret[grp] else 0.0
            show(f"{grp} · {len(nsym[grp])} نماد", buckets[grp], base)
            print("  واکنشِ هم‌عمق (جای کلوز در دامنهٔ کندل، نسبت به "
                  "کندلِ هم‌عمقِ بدونِ باکس):")
            for lbl, pool in (("همهٔ لمس‌ها", react[grp]),
                              ("فقط بارِ اول", first[grp])):
                pr = pooled(*pool)
                if not pr:
                    print(f"    {lbl:<14}     — کم‌شمار")
                    continue
                d, nn, pv = pr
                print(f"    {lbl:<14}{d * 100:+6.1f} واحدِ درصد · "
                      f"n={nn:,} · p={pv:.4f}"
                      f"{'  ★' if pv < 0.05 else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
