# -*- coding: utf-8 -*-
"""همه‌چیز بر حسبِ **طلا**، نه ریال.

مصطفی: «تغییرات را بر اساس تورم، بر اساس طلا می‌سنجند. کل جهان هم بر
اساس طلا سنجیده می‌شود. می‌خواهم ببینم بازدهی‌مان نسبت به بازدهیِ
یک‌سالهٔ طلا چقدر بیشتر می‌شود. این برای من از همه‌چیز مهم‌تر است. من
یک بازدهیِ ۲۰٪ بالاتر از بازدهیِ یک‌سالهٔ طلا مد نظرم هست.»

## چرا این تنها معیارِ درست است

بازدهِ ریالی در اقتصادِ تورمی بی‌معناست. اگر سبد +۱۲۶٪ بدهد و طلا هم
+۱۲۶٪ برود، هیچ‌چیز به دست نیاورده‌ای — فقط همان مقدار طلا را داری.

پس همهٔ منحنی‌های سرمایه بر قیمتِ طلای ۱۸ عیار **تقسیم** می‌شوند.
واحدِ حساب می‌شود «گرمِ طلا»، نه ریال. طلا در این مقیاس همیشه صاف
است (بازدهِ صفر) و هر چیزی بالای صفر یعنی واقعاً جلو زده‌ای.

هدفِ او: **+۲۰ واحد بالای طلا در یک سال.**

دادهٔ طلا: `data/gold/Gold18_1D_CHARTIX.csv` — اکسپورتِ چارتیکس که
خودش فرستاد، از ۲۰۱۴/۱۱ تا امروز.
"""
import argparse
import csv as _csv
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from monthly_backtest import load_daily, is_fixed_income, norm  # noqa: E402
from vp_box import make_box, state  # noqa: E402

GOLD = Path("data/gold/Gold18_1D_CHARTIX.csv")


def load_gold(path=GOLD):
    """{تاریخ: قیمتِ طلای ۱۸} از اکسپورتِ چارتیکس."""
    out = {}
    with Path(path).open(encoding="utf-8-sig", newline="") as fh:
        rd = _csv.reader(fh)
        next(rd, None)
        for r in rd:
            if len(r) < 6:
                continue
            try:
                d = datetime.strptime(r[0].strip(), "%Y%m%d").date()
                out[d] = float(r[5])
            except ValueError:
                continue
    return out


def gold_at(gold, d):
    """قیمتِ طلا در تاریخِ d، یا نزدیک‌ترین روزِ قبلش (تعطیلی)."""
    for k in range(0, 12):
        v = gold.get(d - timedelta(days=k))
        if v:
            return v
    return None


def build(files, anchor, kind, only):
    grid = defaultdict(dict)
    for f in files:
        sym = norm(f.stem.replace("_daily", ""))
        if is_fixed_income(sym):
            continue
        if only is not None and sym not in only:
            continue
        rows = load_daily(f)
        if len(rows) < 80:
            continue
        buck = defaultdict(list)
        for d, b in rows:
            buck[d - timedelta(days=(d.weekday() - anchor) % 7)].append((d, b))
        ks = sorted(buck)
        for i in range(1, len(ks)):
            prev = [b for _d, b in buck[ks[i - 1]]]
            cur = buck[ks[i]]
            if len(prev) < 3 or not cur:
                continue
            box = make_box(kind, prev, ref_price=prev[-1].c)
            if box is None:
                continue
            ref = prev[-1].c
            grid[ks[i]][sym] = (state(ref, box), cur[-1][1].c / ref,
                                statistics.median(
                                    [b.v * b.c for _d, b in cur]) or 0.0,
                                cur[-1][0])
    return grid, sorted(grid)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_auto")
    ap.add_argument("--gold", default=str(GOLD))
    ap.add_argument("--kind", default="poc_band")
    ap.add_argument("--cost", type=float, default=0.55)
    ap.add_argument("--topn", type=int, default=6)
    ap.add_argument("--wcap", type=float, default=0.34)
    ap.add_argument("--week-anchor", type=int, default=6)
    ap.add_argument("--syms", default=None)
    args = ap.parse_args()

    only = ({norm(x) for x in args.syms.split(",") if x.strip()}
            if args.syms else None)
    gold = load_gold(args.gold)
    if not gold:
        print(f"دادهٔ طلا خوانده نشد: {args.gold}")
        return 1

    files = sorted(Path(args.data).glob("*.csv"))
    grid, keys = build(files, args.week_anchor, args.kind, only)
    if len(keys) < 4:
        print("دورهٔ کافی نیست.")
        return 1

    # نرخِ طلا در ابتدا و انتهای هر هفته
    g0 = gold_at(gold, keys[0])
    last_day = max(grid[keys[-1]][s][3] for s in grid[keys[-1]])
    g1 = gold_at(gold, last_day)
    if not g0 or not g1:
        print("قیمتِ طلا برای این بازه پیدا نشد.")
        return 1

    eq = {"هولد": 1.0, "نقدشو": 1.0, "چرخش": 1.0}
    w = {"نقدشو": {}, "چرخش": {}}
    heldset = set()
    for k in keys:
        day = grid[k]
        syms = sorted(day)
        eq["هولد"] *= statistics.mean([day[s][1] for s in syms])
        up = sorted([s for s in syms if day[s][0] == "بالا"],
                    key=lambda s: -day[s][2])[:args.topn]

        def step(name, target):
            old = w[name]
            turn = sum(abs(target.get(s, 0) - old.get(s, 0))
                       for s in set(old) | set(target))
            eq[name] *= (1 - args.cost / 100.0 * turn / 2)
            g = sum(target.get(s, 0) * day[s][1] for s in syms)
            eq[name] *= g + 1 - sum(target.values())
            w[name] = target

        for s in list(heldset):
            if s not in day or day[s][0] == "زیر":
                heldset.discard(s)
        heldset.update(s for s in syms if day[s][0] == "بالا")
        slot = 1.0 / max(1, len(syms))
        step("نقدشو", {s: slot for s in heldset})
        step("چرخش", ({s: min(1.0 / len(up), args.wcap) for s in up}
                      if up else {}))

    gr = g1 / g0
    days = (last_day - keys[0]).days or 1
    yr = 365.0 / days

    print(f"\n  دوره: {keys[0]} تا {last_day}  ({days} روز)")
    print(f"  طلای ۱۸: {g0:,.0f} → {g1:,.0f}  =  "
          f"{(gr - 1) * 100:+.1f}٪ ریالی\n")
    print(f"  {'راه':<12}{'ریالی':>10}{'بر حسبِ طلا':>14}"
          f"{'سالانه‌شدهٔ طلایی':>18}")
    print("  " + "─" * 56)
    for name in ("هولد", "نقدشو", "چرخش"):
        rial = (eq[name] - 1) * 100
        ing = (eq[name] / gr - 1) * 100            # چند درصد بیشتر از طلا
        ann = ((eq[name] / gr) ** yr - 1) * 100
        print(f"  {name:<12}{rial:>9.0f}٪{ing:>+13.1f}٪{ann:>+17.1f}٪")
    print(f"  {'طلا (مبنا)':<12}{(gr - 1) * 100:>9.0f}٪"
          f"{0.0:>+13.1f}٪{0.0:>+17.1f}٪")

    best = max(("هولد", "نقدشو", "چرخش"), key=lambda n: eq[n])
    ann_best = ((eq[best] / gr) ** yr - 1) * 100
    print(f"\n  بهترین: **{best}** · {ann_best:+.1f} واحد بالای طلا "
          f"در سال")
    print(f"  هدفِ تو +۲۰ واحد بود → "
          f"{'✅ رسیده' if ann_best >= 20 else '❌ نرسیده'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
