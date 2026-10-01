# -*- coding: utf-8 -*-
"""قاعدهٔ خروج — «کندلِ دیلی کاملاً زیرِ ناحیه کلوز بدهد».

مصطفی: «حد ضرر می‌شود هرگاه یک کندلِ دیلی پایینِ ناحیه کاملاً کلوز
بدهد، پس ما فردای آن روز فروشنده خواهیم بود، در پولبک یا در فاصلهٔ
کمی از ناحیه.»

دو ابهام که با اندازه‌گیری حل می‌شود نه حدس:

  ۱. «کاملاً زیر» یعنی **کلوز** زیرِ کفِ باکس، یا **کلِ کندل** (حتی
     سقفش) زیرِ کف؟
  ۲. «فردای آن روز» یعنی چقدر بدتر از «همین امروز»؟ صبر کردن برای
     پولبک هزینه دارد یا سود؟

## آزمون

ناحیه = باکسِ هفتگیِ هفتهٔ کاملِ قبل (همان که آلارمِ فروش از آن
می‌آید). فرض: پوزیشنِ خرید داریم.

    رویداد   کلوزِ امروز زیرِ کفِ باکس (یا کلِ کندل زیرِ کف)
    خروجِ ۰   همین امروز، روی کلوز
    خروجِ ۱   فردا، روی کلوز
    خروجِ ۲   فردا، اگر به ناحیه پولبک زد روی کفِ باکس؛ وگرنه کلوزِ فردا

بازدهِ هر کدام از کلوزِ **امروز** تا نقطهٔ خروج. عددِ منفی‌تر یعنی
صبر کردن ضرر داده.
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
    args = ap.parse_args()

    rows_by = {"کلوز زیرِ کف": defaultdict(list),
               "کلِ کندل زیرِ کف": defaultdict(list)}
    nsym = 0
    for f in sorted(Path(args.data).glob("*.csv")):
        if f.stem == "capital" or is_fixed_income(norm(f.stem)):
            continue
        rows = load_daily(f)
        if len(rows) < 80:
            continue
        nsym += 1
        ws = weeks(rows)
        # نقشهٔ روز → باکسِ هفتگیِ معتبر برای آن روز
        box_of = {}
        for i in range(1, len(ws)):
            prev = [b for _d, b in ws[i - 1][1]]
            if len(prev) < 3:
                continue
            bx = make_box(args.kind, prev, ref_price=prev[-1].c)
            if bx is None:
                continue
            for d, _b in ws[i][1]:
                box_of[d] = bx
        for i in range(len(rows) - 3):
            d, b = rows[i]
            bx = box_of.get(d)
            if bx is None:
                continue
            lo = bx[0]
            for lbl, hit in (("کلوز زیرِ کف", b.c < lo),
                             ("کلِ کندل زیرِ کف", b.h < lo)):
                if not hit:
                    continue
                today = b.c
                nd, nb = rows[i + 1]
                r0 = 0.0
                r1 = (nb.c / today - 1) * 100
                # پولبک: اگر فردا سقفش به کفِ باکس رسید، همان‌جا بفروش
                r2 = ((lo / today - 1) * 100 if nb.h >= lo
                      else (nb.c / today - 1) * 100)
                rows_by[lbl][d].append((r0, r1, r2))

    for lbl, per in rows_by.items():
        v = [x for xs in per.values() for x in xs]
        if len(v) < 30:
            print(f"\n  {lbl}: کم‌شمار ({len(v)})")
            continue
        print(f"\n  ══ {lbl} · {nsym} نماد · {len(v):,} رویداد ══")
        print(f"  {'خروج':<28}{'میانگین':>10}{'بهتر از امروز':>16}")
        print("  " + "─" * 56)
        for j, name in enumerate(("همین امروز (روی کلوز)",
                                  "فردا (روی کلوز)",
                                  "فردا، در پولبک به کفِ باکس")):
            m = statistics.mean(x[j] for x in v)
            print(f"  {name:<28}{m:>+9.2f}٪{m:>+15.2f}")
        a = [x[1] for x in v]
        c = [x[2] for x in v]
        d = statistics.mean(c) - statistics.mean(a)
        t = d / ((statistics.pvariance(c) / len(c)
                  + statistics.pvariance(a) / len(a)) ** 0.5)
        print(f"\n  پولبک منهای کلوزِ فردا: {d:+.2f} واحد · t={t:+.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
