# -*- coding: utf-8 -*-
"""باکس هفتگی روی H1 در برابر باکس هفتگی روی کندل روزانه.

**چرا این فایل هست.** مصطفی روی دلار گرفت که باکس هفتگیِ ما «زیر» می‌گوید
در حالی که چارت H1 او «بالا» نشان می‌دهد. علت این است که با کندل روزانه یک
هفته فقط ۵ تا ۷ کندل دارد و پروفایلِ حجمی روی ۷ کندل یعنی یک هیستوگرام
۳ردیفه — دره‌اش هرجا بیفتد تصادفی است. بند ۱ `CLAUDE.md` از اول گفته بود
پروفایل هفتگی باید روی **H1** ساخته شود.

این اسکریپت همان باکس را روی هر دو ورودی می‌سازد و اختلاف را می‌شمارد،
تا «H1 مهم است» از حرف به عدد تبدیل شود.

    python3 tools/h1_box.py --h1 data/chartix_h1 --daily data/drivers_daily
"""
import argparse
import csv
import statistics
from collections import defaultdict, OrderedDict
from datetime import date
from pathlib import Path

from vp_box import Bar, make_box, state
from chartix_import import sym_of
from monthly_backtest import load_daily
from weekly_backtest import week_key


def load_intraday(path):
    """کندل‌های درون‌روزی → dict[تاریخ] = [Bar, ...] به ترتیب زمان."""
    days = OrderedDict()
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            d = (r.get("<DTYYYYMMDD>") or "").strip()
            if len(d) != 8 or not d.isdigit():
                continue
            try:
                h, lo = float(r["<HIGH>"]), float(r["<LOW>"])
                c, v = float(r["<CLOSE>"]), float(r.get("<VOL>") or 0)
            except (TypeError, ValueError, KeyError):
                continue
            if c <= 0:
                continue
            dt = date(int(d[:4]), int(d[4:6]), int(d[6:]))
            days.setdefault(dt, []).append(Bar(h, lo, c, v))
    return days


def weeks_of(days):
    """dict[شنبهٔ هفته] = [(تاریخ، [Bar...]), ...]"""
    out = defaultdict(list)
    for d in sorted(days):
        out[week_key(d)].append((d, days[d]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--h1", default="data/chartix_h1")
    ap.add_argument("--daily", default="data/drivers_daily")
    ap.add_argument("--kind", default="valley_first")
    ap.add_argument("--min-h1", type=int, default=20,
                    help="کمینه کندل H1 در هفته برای ساخت باکس")
    args = ap.parse_args()

    h1_files = sorted(Path(args.h1).glob("*.csv"))
    if not h1_files:
        print(f"هیچ فایل H1 در {args.h1} نیست.")
        return 1

    print("=" * 78)
    print(f"باکس هفتگی — H1 در برابر روزانه  ·  تعریف: {args.kind}")
    print("=" * 78)

    agree = disagree = 0
    rows_out = []
    for p in h1_files:
        sym = sym_of(p.stem)
        dp = Path(args.daily) / f"{sym}_daily.csv"
        if not dp.exists():
            print(f"\n{sym}: فایل روزانه نیست ({dp.name})")
            continue

        h1_days = load_intraday(p)
        h1_weeks = weeks_of(h1_days)

        drows = load_daily(dp)
        d_weeks = defaultdict(list)
        for d, b in drows:
            d_weeks[week_key(d)].append((d, b))

        common = sorted(set(h1_weeks) & set(d_weeks))
        if len(common) < 3:
            print(f"\n{sym}: هفتهٔ مشترک کافی نیست ({len(common)})")
            continue

        print(f"\n{sym}  ·  {len(common)} هفتهٔ مشترک "
              f"({common[0]} تا {common[-1]})")
        print(f"  {'هفته':<12}{'کلوزِ بعد':>13}"
              f"{'باکس روزانه':>24}{'حالت':>7}"
              f"{'باکس H1':>24}{'حالت':>7}   ")
        print("  " + "─" * 88)

        sa = sd = 0
        wid_d, wid_h = [], []
        for i in range(len(common) - 1):
            wa, wb = common[i], common[i + 1]
            if (wb - wa).days != 7:
                continue
            # قیمتی که تصمیم رویش گرفته می‌شود: کلوزِ اولین روزِ هفتهٔ بعد
            nxt = d_weeks[wb]
            if not nxt:
                continue
            px = nxt[0][1].c

            db = make_box(args.kind, [b for _, b in d_weeks[wa]],
                          d_weeks[wa][-1][1].c)
            hb_bars = [b for _, bars in h1_weeks[wa] for b in bars]
            if len(hb_bars) < args.min_h1:
                continue
            hb = make_box(args.kind, hb_bars, hb_bars[-1].c)
            if db is None or hb is None:
                continue

            sd_, sh_ = state(px, db), state(px, hb)
            if sd_ == sh_:
                sa += 1
            else:
                sd += 1
            wid_d.append((db[1] - db[0]) / db[0] * 100)
            wid_h.append((hb[1] - hb[0]) / hb[0] * 100)

            if i >= len(common) - 7:      # فقط شش هفتهٔ آخر چاپ می‌شود
                mark = "  ←اختلاف" if sd_ != sh_ else ""
                print(f"  {str(wa):<12}{px:>13,.0f}"
                      f"{f'{db[0]:,.0f}–{db[1]:,.0f}':>24}{sd_:>7}"
                      f"{f'{hb[0]:,.0f}–{hb[1]:,.0f}':>24}{sh_:>7}{mark}")

        tot = sa + sd
        if not tot:
            continue
        agree += sa
        disagree += sd
        print(f"  ── {sym}: {sd} اختلاف از {tot} هفته "
              f"({sd/tot*100:.0f}٪)  ·  میانهٔ پهنا: روزانه "
              f"{statistics.median(wid_d):.2f}٪ · H1 "
              f"{statistics.median(wid_h):.2f}٪")
        rows_out.append((sym, tot, sd, statistics.median(wid_d),
                         statistics.median(wid_h)))

    if not rows_out:
        print("\nهیچ مقایسه‌ای ساخته نشد.")
        return 1

    tot = agree + disagree
    print("\n" + "=" * 78)
    print("جمع")
    print("=" * 78)
    print(f"  {'نماد':<16}{'هفته':>7}{'اختلاف':>9}{'٪':>7}"
          f"{'پهنا روزانه':>14}{'پهنا H1':>11}")
    for sym, n, d, wd, wh in rows_out:
        print(f"  {sym:<16}{n:>7}{d:>9}{d/n*100:>6.0f}٪"
              f"{wd:>13.2f}٪{wh:>10.2f}٪")
    print(f"\n  اختلاف کل: {disagree} از {tot} هفته "
          f"({disagree/tot*100:.1f}٪)")
    print("\n  اگر این عدد کوچک بود، H1 فقط دقت را بالا می‌برد.")
    print("  اگر بزرگ بود، هر عددی که با کندل روزانه گرفته‌ایم مشکوک است.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
