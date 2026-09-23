# -*- coding: utf-8 -*-
"""خلای حجمِ عمودی — استراتژیِ دومِ مصطفی.

به زبانِ خودش:

> «هرگاه یک کندل، حجمش از دو کندلِ کنارش کمتر باشد، آن می‌رود توی
> باکس — یک خلای حجمِ عمودی. هرگاه قیمت بالای آن باکس کلوز داد، روندِ
> حرکتی شروع شده؛ صبر می‌کنیم و در پولبک خریدمان را می‌کنیم. هرگاه
> زیرِ آن باکس کلوز داد، در پولبک می‌فروشیم.»

## فرقش با استراتژیِ اول

| | استراتژیِ اول | این یکی |
|---|---|---|
| حجم | **افقی** — پروفایل روی قیمت | **عمودی** — میلهٔ حجمِ هر کندل |
| باکس | ناحیهٔ پرحجم حولِ POC | دامنهٔ **یک کندل** با حجمِ کمینهٔ محلی |
| دوره | هفته یا ماهِ کامل | هر جا که چنین کندلی پیدا شود |

دو چیزِ کاملاً متفاوت‌اند و می‌توانند هم‌زمان استفاده شوند — که
دقیقاً چیزی است که او می‌خواهد: این یکی به‌عنوان **تریگر** کنارِ آن.

## تعریفِ دقیقی که پیاده شد

    کندلِ i خلای حجمی است اگر:  vol[i] < vol[i-1]  و  vol[i] < vol[i+1]
    باکس = (low[i], high[i])
    وضعیت = بالا / داخل / زیر، نسبت به کلوزِ امروز و **آخرین** خلای
            حجمیِ قبل از امروز

⚠️ کندلِ i تا کندلِ i+1 بسته نشود، خلا بودنش معلوم نیست. پس باکس از
**دو کندل بعد** قابلِ استفاده است — لوک‌اهد ندارد.

## معیار

همان کنترلِ همیشگی (بند ۰ قانون ۲): مزیت نسبت به نرخ پایهٔ **همان
دوره**، با آزمونِ جایگشتِ درون‌دوره‌ای.
"""
import argparse
import random
import statistics
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from monthly_backtest import load_daily, is_fixed_income, norm  # noqa: E402


def vgap_boxes(bars):
    """ایندکسِ کندل‌هایی که حجمشان کمینهٔ محلی است."""
    out = []
    for i in range(1, len(bars) - 1):
        if bars[i].v < bars[i - 1].v and bars[i].v < bars[i + 1].v:
            out.append(i)
    return out


def state_at(bars, gaps, i):
    """وضعیتِ کلوزِ کندلِ i نسبت به آخرین خلای حجمیِ **تأییدشده**.

    خلای کندلِ g وقتی تأیید می‌شود که g+1 بسته شده باشد، پس فقط
    خلاهایی به کار می‌آیند که g + 1 < i.
    """
    g = None
    for x in gaps:
        if x + 1 < i:
            g = x
        else:
            break
    if g is None:
        return None, None
    lo, hi = bars[g].l, bars[g].h
    c = bars[i].c
    st = "بالا" if c > hi else "زیر" if c < lo else "داخل"
    return st, (lo, hi)


def resample(rows, mode):
    """کندلِ روزانه → هفتگی یا ماهانه."""
    if mode == "day":
        return rows
    b = defaultdict(list)
    for d, bar in rows:
        k = ((d.year, d.month) if mode == "month"
             else d - timedelta(days=(d.weekday() - 6) % 7))
        b[k].append((d, bar))

    class B:
        __slots__ = ("h", "l", "c", "v")

    out = []
    for k in sorted(b):
        xs = [x for _d, x in b[k]]
        o = B()
        o.h = max(x.h for x in xs)
        o.l = min(x.l for x in xs)
        o.c = xs[-1].c
        o.v = sum(x.v for x in xs)
        out.append((b[k][-1][0], o))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_long")
    ap.add_argument("--tf", default="day,week,month")
    ap.add_argument("--horizon", type=int, default=1,
                    help="بازده روی چند کندلِ بعد")
    ap.add_argument("--iters", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rnd = random.Random(args.seed)
    files = sorted(Path(args.data).glob("*_daily.csv"))
    if not files:
        print(f"فایلی در {args.data} نیست.")
        return 1

    for tf in args.tf.split(","):
        fa = {"day": "دیلی", "week": "هفتگی", "month": "ماهانه"}[tf]
        # {دوره: [(وضعیت، بازده)]} برای کنترلِ درون‌دوره‌ای
        per = defaultdict(list)
        nsym = 0
        for f in files:
            sym = norm(f.stem.replace("_daily", ""))
            if is_fixed_income(sym):
                continue
            rows = resample(load_daily(f), tf)
            if len(rows) < 40:
                continue
            nsym += 1
            bars = [b for _d, b in rows]
            gaps = vgap_boxes(bars)
            if not gaps:
                continue
            for i in range(2, len(bars) - args.horizon):
                st, _bx = state_at(bars, gaps, i)
                if st is None:
                    continue
                r = (bars[i + args.horizon].c / bars[i].c - 1) * 100
                per[rows[i][0]].append((st, r))

        if not per:
            print(f"\n  {fa}: داده‌ای نشد.")
            continue

        # ── ساختارِ فشرده، یک بار ──────────────────────────────────
        # نسخهٔ اول برای هر تکرارِ جایگشت کلِ تاپل‌ها را بازمی‌ساخت و
        # روی ۴۰۰۰ تکرار تایم‌اوت می‌شد. اینجا هر دوره یک بار به
        # (فهرستِ بازده، میانگین، شمارشِ هر برچسب) تبدیل می‌شود و
        # جایگشت فقط یک نمونه‌گیریِ بدونِ جایگذاری است.
        packed = []
        for _k, xs in per.items():
            if len(xs) < 3:
                continue
            rs = [r for _s, r in xs]
            cnt = defaultdict(int)
            for st_, _r in xs:
                cnt[st_] += 1
            packed.append((rs, statistics.mean(rs), dict(cnt)))

        def edge_real(want):
            es, n = [], 0
            for _k, xs in per.items():
                if len(xs) < 3:
                    continue
                sel = [r for st_, r in xs if st_ == want]
                if not sel:
                    continue
                base = statistics.mean([r for _s, r in xs])
                es.append(statistics.mean(sel) - base)
                n += len(sel)
            return (statistics.mean(es) if es else 0.0), n

        def edge_perm(want):
            es = []
            for rs, mu, cnt in packed:
                k = cnt.get(want, 0)
                if not k:
                    continue
                sel = rnd.sample(rs, k)
                es.append(sum(sel) / k - mu)
            return statistics.mean(es) if es else 0.0

        allr = [r for xs in per.values() for _s, r in xs]
        print(f"\n  ══ {fa} · {nsym} نماد · {len(allr):,} مشاهده ══")
        print(f"  نرخ پایه {statistics.mean(allr):+.2f}٪ · "
              f"{sum(1 for x in allr if x > 0) / len(allr) * 100:.0f}٪ مثبت")
        print(f"  {'وضعیت':<8}{'n':>7}{'میانگین':>10}{'مثبت':>8}"
              f"{'مزیت':>9}{'p':>9}")
        print("  " + "─" * 52)
        for want in ("بالا", "داخل", "زیر"):
            v = [r for xs in per.values() for s, r in xs if s == want]
            if not v:
                continue
            e, _n = edge_real(want)
            hits = sum(1 for _ in range(args.iters)
                       if edge_perm(want) >= e)
            p = (hits + 1) / (args.iters + 1)
            star = " ★" if p < 0.05 else ""
            print(f"  {want:<8}{len(v):>7}{statistics.mean(v):>+9.2f}٪"
                  f"{sum(1 for x in v if x > 0) / len(v) * 100:>7.0f}٪"
                  f"{e:>+8.2f}{p:>9.4f}{star}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
