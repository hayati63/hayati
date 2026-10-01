# -*- coding: utf-8 -*-
"""بازگشتِ درون‌هفته — سیگنال است یا نویز؟

مصطفی: «هرگاه مثلِ الان که بورس در هفته پایینِ ناحیه کلوز داده، اگر
ناحیه را در طیِ هفته به بالا بشکند، ما می‌بایست سیگنالِ خرید صادر
کنیم. در موردِ بقیه هم صادق است.»

سیستمِ فعلی فقط کلوزِ **روزِ تصمیم** (اولین جلسهٔ هفته) را می‌بیند.
اگر آن زیر باکس بود، کلِ هفته سیگنالی نیست — حتی اگر سه‌شنبه قیمت
برگردد بالای ناحیه. این همان چیزی است که او می‌گوید جا می‌افتد.

## آزمون

    باکس = هفتهٔ کاملِ قبل
    کلوزِ روزِ تصمیم **بالای** باکس نبود  → کاندیدِ بازگشت
    کلوزی در همان هفته بالای سقفِ باکس    → «بازگشت»
    هیچ کلوزی بالا نرفت                   → گروهِ کنترلِ هم‌شکل

بازده از **همان کلوزِ عبور** به بعد، چون همان‌جا می‌خری.

کنترل عمداً «کاندید ولی بدونِ بازگشت» است، نه نرخ پایهٔ بازار: هر دو
گروه هفته‌شان زیرِ باکس شروع شده، پس آنچه می‌ماند فقط اثرِ خودِ
بازگشت است.

و برای مقایسه، «بالا از همان روزِ تصمیم» هم گزارش می‌شود — سیگنالِ
موجود. اگر بازگشت از آن بدتر باشد، ارزشِ اضافه شدن ندارد.
"""
import argparse
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from monthly_backtest import load_daily, is_fixed_income, norm  # noqa: E402
from vp_box import make_box, state  # noqa: E402


def weeks(rows, anchor=6):
    from datetime import timedelta
    b = defaultdict(list)
    for d, bar in rows:
        b[d - timedelta(days=(d.weekday() - anchor) % 7)].append((d, bar))
    return [(k, b[k]) for k in sorted(b)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_bourse")
    ap.add_argument("--kind", default="valley_first")
    ap.add_argument("--confirm", type=int, default=1,
                    help="چند کلوزِ پشتِ هم بالای سقف لازم است")
    ap.add_argument("--fwd", type=int, default=5,
                    help="افقِ بازده، روزِ معاملاتی")
    args = ap.parse_args()

    files = sorted(Path(args.data).glob("*.csv"))
    if not files:
        files = sorted(Path(args.data).glob("*_daily.csv"))
    # {دوره: [(برچسب، بازده)]} — کنترلِ درون‌دوره‌ای
    per = defaultdict(list)
    nsym = 0
    for f in files:
        sym = f.stem.replace("_daily", "")
        if is_fixed_income(norm(sym)) or sym == "capital":
            continue
        rows = load_daily(f)
        if len(rows) < 80:
            continue
        flat = rows
        idx = {d: i for i, (d, _b) in enumerate(flat)}
        ws = weeks(rows)
        if len(ws) < 5:
            continue
        nsym += 1
        for i in range(1, len(ws) - 1):
            prev = [b for _d, b in ws[i - 1][1]]
            cur = ws[i][1]
            if len(prev) < 3 or not cur:
                continue
            box = make_box(args.kind, prev, ref_price=prev[-1].c)
            if box is None:
                continue
            lo, hi = box
            dec_d, dec_b = cur[0]
            st = state(dec_b.c, box)

            def fwd(d):
                j = idx.get(d)
                if j is None or j + args.fwd >= len(flat):
                    return None
                a, b2 = flat[j][1].c, flat[j + args.fwd][1].c
                return (b2 / a - 1) * 100 if a > 0 else None

            if st == "بالا":
                r = fwd(dec_d)
                if r is not None:
                    per[ws[i][0]].append(("روزِ تصمیم بالا", r))
                continue
            # کاندیدِ بازگشت: روزِ تصمیم بالا نبود
            cross = None
            run = 0
            for d, b in cur[1:]:
                run = run + 1 if b.c > hi else 0
                if run >= args.confirm:
                    cross = d
                    break
            if cross is not None:
                r = fwd(cross)
                if r is not None:
                    per[ws[i][0]].append(("بازگشتِ درون‌هفته", r))
            else:
                r = fwd(cur[-1][0])
                if r is not None:
                    per[ws[i][0]].append(("بدونِ بازگشت", r))

    allr = [r for xs in per.values() for _k, r in xs]
    if not allr:
        print("داده‌ای نشد.")
        return 1
    print(f"\n  {nsym} نماد · {len(per)} هفته · {len(allr):,} مشاهده · "
          f"افقِ {args.fwd} روز · باکسِ {args.kind}")
    print(f"  نرخ پایه {statistics.mean(allr):+.2f}٪ · "
          f"{sum(1 for x in allr if x > 0) / len(allr) * 100:.0f}٪ مثبت\n")
    print(f"  {'گروه':<22}{'n':>7}{'میانگین':>10}{'مثبت':>8}{'مزیت':>9}")
    print("  " + "─" * 58)
    base = statistics.mean(allr)
    g = {}
    for k in ("روزِ تصمیم بالا", "بازگشتِ درون‌هفته", "بدونِ بازگشت"):
        v = [r for xs in per.values() for kk, r in xs if kk == k]
        if not v:
            continue
        g[k] = v
        print(f"  {k:<22}{len(v):>7}{statistics.mean(v):>+9.2f}٪"
              f"{sum(1 for x in v if x > 0) / len(v) * 100:>7.0f}٪"
              f"{statistics.mean(v) - base:>+8.2f}")
    # ── کنترلِ هم‌شکل: بازگشت در برابرِ بدونِ بازگشت ──────────────
    if "بازگشتِ درون‌هفته" in g and "بدونِ بازگشت" in g:
        a, b = g["بازگشتِ درون‌هفته"], g["بدونِ بازگشت"]
        d = statistics.mean(a) - statistics.mean(b)
        t = d / ((statistics.pvariance(a) / len(a)
                  + statistics.pvariance(b) / len(b)) ** 0.5)
        print(f"\n  بازگشت منهای بدونِ بازگشت: {d:+.2f} واحد · t={t:+.2f}")
        print("  (هر دو گروه هفته‌شان زیرِ باکس شروع شده — این مقایسهٔ"
              " درست است.)")
    if "بازگشتِ درون‌هفته" in g and "روزِ تصمیم بالا" in g:
        a, b = g["بازگشتِ درون‌هفته"], g["روزِ تصمیم بالا"]
        d = statistics.mean(a) - statistics.mean(b)
        t = d / ((statistics.pvariance(a) / len(a)
                  + statistics.pvariance(b) / len(b)) ** 0.5)
        print(f"  بازگشت منهای سیگنالِ موجود: {d:+.2f} واحد · t={t:+.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
