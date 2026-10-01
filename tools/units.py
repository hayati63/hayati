# -*- coding: utf-8 -*-
"""هزار واحد عیار اولِ سال — آخرِ سال چند واحد؟

مصطفی، با قاعده‌ای که خودش دقیق کرد:

> «اگر بالای باکس باز شد، ماهانه یا هفتگی، اصلاً نیاز نیست بفروشیم.
> بیاییم روی حمایت بخریم چون شاید برنگردد روی حمایت و ما جا بمانیم.
> ما فقط در صورتی می‌فروشیم که زیرِ باکس باز شود. همین.»

پس:

    کلوزِ دوره **بالای** باکس  → بخر / نگه دار  (روی همان کلوز، بدونِ
                                 انتظارِ پولبک)
    کلوزِ دوره **زیرِ** باکس   → بفروش
    **داخلِ** باکس            → دست نگه دار

و معیار، آن‌طور که او می‌خواهد: **تعدادِ واحد**، نه ریال.

با ۱۰۰۰ واحد شروع می‌کنیم. در هولد تا آخر ۱۰۰۰ واحد می‌ماند — ارزشش
بالا و پایین می‌رود ولی تعداد ثابت است. در استراتژی، هر بار که
بفروشی و پایین‌تر بخری تعداد بیشتر می‌شود، و هر بار که بفروشی و
بالاتر بخری کمتر.

**این معیارِ درستی است** و دقیقاً همان سؤالِ اوست: آیا این کار
تعدادِ واحدم را زیاد می‌کند؟
"""
import argparse
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from monthly_backtest import load_daily  # noqa: E402
from vp_box import make_box, state  # noqa: E402


def periods(rows, mode, anchor=6):
    b = defaultdict(list)
    for d, bar in rows:
        k = ((d.year, d.month) if mode == "month"
             else d - timedelta(days=(d.weekday() - anchor) % 7))
        b[k].append((d, bar))
    return [(k, b[k]) for k in sorted(b)]


def simulate(rows, mode, cost, start_units=1000.0):
    """خروجی: (واحدِ پایانی، تعدادِ فروش، سهمِ زمانِ در سهم)"""
    ps = periods(rows, mode)
    if len(ps) < 3:
        return None
    units = start_units
    cash = 0.0
    holding = True                 # از اول سهم داریم
    sells = 0
    inn = tot = 0
    for i in range(1, len(ps)):
        prev = [b for _d, b in ps[i - 1][1]]
        cur = ps[i][1]
        if len(prev) < 3 or not cur:
            continue
        box = make_box("poc_band", prev, ref_price=prev[-1].c)
        if box is None:
            tot += 1
            if holding:
                inn += 1
            continue
        ref = prev[-1].c
        st = state(ref, box)
        tot += 1

        if holding and st == "زیر":
            cash = units * ref * (1 - cost / 100.0)
            units = 0.0
            holding = False
            sells += 1
        elif not holding and st == "بالا":
            units = cash * (1 - cost / 100.0) / ref
            cash = 0.0
            holding = True
        if holding:
            inn += 1
    # ته دوره اگر نقدیم، با قیمتِ آخر به واحد برگردان تا قابلِ مقایسه شود
    if not holding:
        units = cash / rows[-1][1].c
    return units, sells, (inn / tot * 100 if tot else 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sym", default="عیار")
    ap.add_argument("--data", default="data_long")
    ap.add_argument("--cost", type=float, default=0.55)
    args = ap.parse_args()

    rows = load_daily(Path(args.data) / f"{args.sym}_daily.csv")
    print(f"\n  {args.sym} · {rows[0][0]} تا {rows[-1][0]} · "
          f"کارمزد {args.cost}٪")
    print(f"  شروع: **۱۰۰۰ واحد**. در هولد تا آخر ۱۰۰۰ می‌ماند.\n")

    byy = defaultdict(list)
    for d, b in rows:
        byy[d.year].append((d, b))

    for mode, fa in (("week", "هفتگی"), ("month", "ماهانه")):
        print(f"  ══ تصمیمِ {fa} ══")
        print(f"  {'سال':<7}{'واحدِ پایانی':>13}{'تغییر':>9}"
              f"{'فروش':>7}{'در سهم':>9}   نتیجه")
        print("  " + "─" * 58)
        tot = 1000.0
        for y in sorted(byy):
            yr = byy[y]
            if len(yr) < 60:
                continue
            out = simulate(yr, mode, args.cost)
            if not out:
                continue
            u, s, sh = out
            tot *= u / 1000.0
            v = "بهتر ✓" if u > 1000 else "بدتر"
            print(f"  {y:<7}{u:>13.0f}{(u / 1000 - 1) * 100:>+8.1f}٪"
                  f"{s:>7}{sh:>8.0f}٪   {v}")
        print(f"  {'مرکب':<7}{tot:>13.0f}"
              f"{(tot / 1000 - 1) * 100:>+8.1f}٪\n")

    out = simulate(rows, "week", args.cost)
    out2 = simulate(rows, "month", args.cost)
    print(f"  ── کلِ دوره یک‌جا (بدونِ تقسیم به سال) ──")
    print(f"     هولد               ۱۰۰۰ واحد")
    print(f"     استراتژیِ هفتگی    {out[0]:.0f} واحد"
          f"  ({(out[0] / 1000 - 1) * 100:+.0f}٪)")
    print(f"     استراتژیِ ماهانه   {out2[0]:.0f} واحد"
          f"  ({(out2[0] / 1000 - 1) * 100:+.0f}٪)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
