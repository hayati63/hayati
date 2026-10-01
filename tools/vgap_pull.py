# -*- coding: utf-8 -*-
"""پولبک به باکسِ خلای حجمیِ شکسته — چیزی که مصطفی روی دوایکس دید.

او نوشت:

> «الان روی دوایکس دیدم در تایم‌فریمِ دیلی یا هفتگی دارد پولبک می‌زند
> به آن کندلی که شکسته، و این می‌تواند به ما قطعیتی بدهد که مثلاً چند
> درصد پایین‌تر یک حمایتِ قوی وجود دارد. به‌خصوص اگر در هفتگی باشد که
> عالی.»

`tools/vgap.py` **وضعیت** را سنجید (بالا/داخل/زیر). این یکی **رویداد**
را می‌سنجد، که چیزِ دیگری است:

    دوره‌ی قبل بالای باکس بسته بود  (شکست تأیید شده)
    این دوره کفش خورد به باکس       (low ≤ سقفِ باکس)   ← پولبک
    → بازدهِ n دورهٔ بعد از همین کلوز چقدر است؟

و سه چیز که بدونشان عدد بی‌معناست (بند ۰ قانون ۲):

  ۱. **نرخ پایهٔ همان دوره.** بازار ایران بالا می‌رود؛ +۳٪ سیگنال نیست.
  ۲. **گروه کنترلِ هم‌شکل:** «بالای باکس، ولی پولبک **نزد**». اگر
     پولبک‌زده و پولبک‌نزده یکی باشند، پولبک حرفی ندارد و فقط
     «بالای باکس بودن» مهم است.
  ۳. **آزمونِ جایگشتِ درون‌دوره‌ای** برای p.

⚠️ بدونِ لوک‌اهد: باکس فقط از کندل‌هایی ساخته می‌شود که **دو دوره**
قبل‌تر بسته‌اند (کندلِ خلا + کندلِ تأییدکننده)، و دورهٔ ناقصِ جاری
کنار گذاشته می‌شود.
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
from vgap import resample  # noqa: E402


def label(bars, i, max_dist):
    """برچسبِ کندلِ i نسبت به آخرین خلای حجمیِ **قبل از** آن.

    خلا در ایندکس g وقتی معلوم می‌شود که g+1 بسته باشد، پس برای تصمیم
    روی کندلِ i فقط g ≤ i−2 مجاز است.
    """
    g = None
    for j in range(1, i - 1):
        if bars[j].v < bars[j - 1].v and bars[j].v < bars[j + 1].v:
            g = j
    if g is None:
        return None
    lo, hi = bars[g].l, bars[g].h
    prev = bars[i - 1].c
    if prev <= hi:                       # شکستِ رو به بالا تأیید نشده
        return None
    if max_dist is not None and (prev / hi - 1) * 100 > max_dist:
        return None                      # باکس آن‌قدر دور است که حمایت نیست
    return "پولبک" if bars[i].l <= hi else "بدونِ پولبک"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_auto")
    ap.add_argument("--tf", default="week,day")
    ap.add_argument("--horizon", type=int, default=1)
    ap.add_argument("--max-dist", type=float, default=25.0,
                    help="اگر قیمت بیش از این درصد از باکس دور است، "
                         "رد کن؛ منفی یعنی بی‌قید")
    ap.add_argument("--min-bars", type=int, default=40,
                    help="کمینهٔ کندل در آن تایم‌فریم")
    ap.add_argument("--iters", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    md = None if args.max_dist < 0 else args.max_dist

    rnd = random.Random(args.seed)
    files = sorted(Path(args.data).glob("*_daily.csv"))
    if not files:
        print(f"فایلی در {args.data} نیست.")
        return 1

    print(f"\n  دادهٔ {args.data} · افقِ {args.horizon} کندل · "
          f"سقفِ فاصله {'بی‌قید' if md is None else f'{md:.0f}٪'}")

    for tf in args.tf.split(","):
        fa = {"day": "دیلی", "week": "هفتگی", "month": "ماهانه"}[tf]
        per = defaultdict(list)
        persym = defaultdict(lambda: defaultdict(list))
        nsym = 0
        for f in files:
            sym = norm(f.stem.replace("_daily", ""))
            if is_fixed_income(sym):
                continue
            rows = resample(load_daily(f), tf)
            if len(rows) < args.min_bars:
                continue
            nsym += 1
            bars = [b for _d, b in rows]
            # دورهٔ ناقصِ جاری کنار می‌رود
            if tf != "day":
                rows, bars = rows[:-1], bars[:-1]
            for i in range(3, len(bars) - args.horizon):
                lb = label(bars, i, md)
                if lb is None:
                    continue
                r = (bars[i + args.horizon].c / bars[i].c - 1) * 100
                per[rows[i][0]].append((lb, r))
                persym[f.stem.replace("_daily", "")][lb].append(r)

        if not per:
            print(f"\n  {fa}: داده‌ای نشد.")
            continue

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
            es = []
            for _k, xs in per.items():
                if len(xs) < 3:
                    continue
                sel = [r for st_, r in xs if st_ == want]
                if not sel:
                    continue
                base = statistics.mean([r for _s, r in xs])
                es.append(statistics.mean(sel) - base)
            return statistics.mean(es) if es else 0.0

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
        print(f"  نرخ پایه (همهٔ بالای باکس) {statistics.mean(allr):+.2f}٪ · "
              f"{sum(1 for x in allr if x > 0) / len(allr) * 100:.0f}٪ مثبت")
        print(f"  {'وضعیت':<14}{'n':>7}{'میانگین':>10}{'مثبت':>8}"
              f"{'مزیت':>9}{'p':>9}")
        print("  " + "─" * 58)
        got = {}
        for want in ("پولبک", "بدونِ پولبک"):
            v = [r for xs in per.values() for s, r in xs if s == want]
            if not v:
                continue
            got[want] = v
            e = edge_real(want)
            hits = sum(1 for _ in range(args.iters) if edge_perm(want) >= e)
            p = (hits + 1) / (args.iters + 1)
            star = " ★" if p < 0.05 else ""
            print(f"  {want:<14}{len(v):>7}{statistics.mean(v):>+9.2f}٪"
                  f"{sum(1 for x in v if x > 0) / len(v) * 100:>7.0f}٪"
                  f"{e:>+8.2f}{p:>9.4f}{star}")

        # ── کنترلِ هم‌شکل: پولبک در برابر بدونِ پولبک ──────────────
        if len(got) == 2:
            a, b = got["پولبک"], got["بدونِ پولبک"]
            d = statistics.mean(a) - statistics.mean(b)
            va = statistics.pvariance(a) / len(a)
            vb = statistics.pvariance(b) / len(b)
            t = d / ((va + vb) ** 0.5) if va + vb else 0.0
            print(f"\n  پولبک منهای بدونِ پولبک: {d:+.2f} واحد · t={t:+.2f}")
            print("  (همین ستون مهم است — نه مقایسه با نرخ پایه، چون هر دو"
                  " گروه\n   بالای باکس‌اند و مزیتِ «بالای باکس بودن» را"
                  " مشترک دارند.)")

        # ── پایداری روی نمادها ─────────────────────────────────────
        wins = 0
        tot = 0
        for sym, g in sorted(persym.items()):
            if len(g.get("پولبک", [])) < 5 or len(g.get("بدونِ پولبک", [])) < 5:
                continue
            tot += 1
            if statistics.mean(g["پولبک"]) > statistics.mean(g["بدونِ پولبک"]):
                wins += 1
        if tot:
            print(f"  در {wins} از {tot} نماد پولبک بهتر بوده.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
