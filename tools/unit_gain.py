# -*- coding: utf-8 -*-
"""میانگینِ **چند درصد** واحدِ کهرباىِ بیشتر، هفتگی و ماهانه.

مصطفی:

> «تو بک‌تست‌ها هم باید این استراتژی کار کند و نشان دهد میانگین چند
> درصد — چه بر اساس هفتگی و چه بر اساس ماهانه — ما درصدِ پرتفومان را
> نسبت به کهربا بیشتر کرده‌ایم. این هدفِ غایی و نهاییِ من از انجامِ
> معامله روی همهٔ نمادهاست.»

تا حالا فقط **نسبتِ کل** گزارش می‌شد (۱٫۱۹۱ یعنی ۱۹٫۱٪ واحدِ بیشتر در
کلِ پنجره). این ابزار همان را به زبانِ دوره می‌گوید: در هر هفته، و در
هر ماه، به‌طور میانگین چند درصد واحدِ بیشتر.

و کنارش **کنترلِ ترتیبِ تصادفی** می‌آید، چون بند ۰ قاعدهٔ ۲ راهنما
می‌گوید عددِ تنها بی‌معناست: اگر ترتیبِ تصادفی هم همین‌قدر بدهد، آنچه
کار کرده «فیلتر» است نه «رتبه‌بندی».

⚠️ این هارنس هستهٔ قاعده را دارد (بالای باکس، فیلترِ کهربا، رتبه‌بندی
با مازاد + پاسخِ محرک، N نماد، سقفِ وزن، «هرگز نقد نشو»، کارمزد روی
گردشِ واقعی) ولی دو افزودهٔ تازه را **ندارد**: قاعدهٔ «نگه‌داشته»
(`docs/36`) و حکمِ خلای حجمی. پس عددش کفِ کارِ سیستمِ امروز است، نه
سقفش.

    python3 tools/unit_gain.py
"""
import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import driver_rank as D                                       # noqa: E402
from monthly_backtest import load_daily, is_fixed_income, norm  # noqa: E402


def stats(v, ratio, n_span):
    """آمارِ دوره‌ای.

    ⚠️ عددِ سرخط **نسبتِ کلِ پنجره** است، نه حاصل‌ضربِ مازادِ دوره‌ها.
    نسخهٔ اولِ این ابزار دومی را چاپ می‌کرد و ۱۳ واحد بیش‌برآورد
    می‌داد: در دوره‌هایی که تصمیم ممکن نبود (کهربا یا نمادها آن هفته
    کندلِ قابلِ استفاده نداشتند) سبد نگه داشته می‌شد ولی کهربا حرکت
    می‌کرد، و آن دوره‌ها از حاصل‌ضرب بیرون می‌ماندند در حالی که در
    مخرجِ نسبت هستند. ۱٫۱۹۱ درست است، ۱٫۳۲۷ غلط بود.
    """
    o = {"total": (ratio - 1) * 100, "n_span": n_span,
         "geo": ((ratio ** (1.0 / n_span)) - 1) * 100 if n_span else 0.0}
    if v:
        o.update({"n": len(v), "mean": statistics.fmean(v),
                  "med": statistics.median(v),
                  "win": sum(1 for x in v if x > 0) / len(v) * 100,
                  "best": max(v), "worst": min(v)})
    return o


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_bourse")
    ap.add_argument("--drivers", default="data/drivers_daily")
    ap.add_argument("--cost", type=float, default=0.55)
    ap.add_argument("--kind", default="valley_first")
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--wcap", type=float, default=0.25)
    ap.add_argument("--seeds", type=int, default=100)
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    raw, cl = {}, {}
    for f in sorted((root / args.data).glob("*.csv")):
        if f.stem in ("capital", "track") or is_fixed_income(norm(f.stem)):
            continue
        r = load_daily(f)
        if len(r) >= 100:
            raw[f.stem] = {d: b for d, b in r}
            cl[f.stem] = {d: b.c for d, b in r}
    if D.BENCH not in raw:
        print(f"{D.BENCH} نیست."); return 1
    drv = D.load_drivers(str(root / args.drivers))
    dcl = {k: {d: b.c for d, b in v.items()} for k, v in drv.items()}
    dmap = D.driver_map(cl, dcl)
    bd = set(raw[D.BENCH])
    syms = [s for s in raw if len(set(raw[s]) & bd) >= 100]
    days = sorted(bd)
    print(f"\n  {len(syms)} نماد · {days[0]} تا {days[-1]} · "
          f"N={args.n} · سقفِ وزن {args.wcap:.0%} · کارمزد {args.cost}٪")
    print(f"  معیار: **درصدِ واحدِ {D.BENCH}ىِ بیشتر در هر دوره**، "
          f"بعد از کارمزد.\n")

    for mode, fa, per_yr in (("week", "هفتگی", 52), ("month", "ماهانه", 12)):
        ps = D.periods(days, mode)
        n_span = len(ps) - 1
        each = []
        out = D.run(raw, cl, syms, ps, mode, dmap, dcl, kind=args.kind,
                    cost=args.cost, n_max=args.n, wcap=args.wcap,
                    dlook=10, rank="beta_bx", log=each)
        if not out:
            continue
        st = stats(each, out[0], n_span)
        rs = []
        for sd in range(args.seeds):
            o2 = D.run(raw, cl, syms, ps, mode, dmap, dcl, kind=args.kind,
                       cost=args.cost, n_max=args.n, wcap=args.wcap,
                       rank="rand", blend=float(sd))
            if o2:
                rs.append((o2[0] ** (1.0 / n_span) - 1) * 100)
        print(f"  ══ تصمیمِ {fa} · {n_span} دوره ══")
        print(f"    کلِ پنجره               {st['total']:>+8.2f}٪ "
              f"واحدِ {D.BENCH}ىِ بیشتر")
        print(f"    ⇒ میانگینِ هر دوره      {st['geo']:>+8.3f}٪  "
              f"(میانگینِ هندسی، روی هر {n_span} دوره)")
        ann = ((1 + st["geo"] / 100) ** per_yr - 1) * 100
        print(f"    ⇒ سالانه (تعمیم)       {ann:>+8.1f}٪")
        if "med" in st:
            print(f"\n    توزیعِ {st['n']} دوره‌ای که تصمیم ممکن بود:")
            print(f"      میانه                {st['med']:>+8.3f}٪")
            print(f"      دوره‌هایی که جلو بود   {st['win']:>7.1f}٪")
            print(f"      بهترین / بدترین      {st['best']:>+8.2f}٪ / "
                  f"{st['worst']:+.2f}٪")
        if rs:
            rs.sort()
            m = statistics.fmean(rs)
            better = sum(1 for v in rs if v >= st["geo"]) / len(rs)
            print(f"\n    کنترلِ ترتیبِ تصادفی  {m:>+8.3f}٪ در هر دوره "
                  f"(بازه {rs[0]:+.3f} تا {rs[-1]:+.3f})")
            print(f"      → {better:.0%} از بذرها از قاعده بهتر بودند")
        print()

    print("  ⚠️ پنجره یک رژیمِ بازار است، نه همهٔ رژیم‌ها (docs §۷).")
    print("  ⚠️ «سالانه» تعمیمِ میانگینِ دوره است، نه بازدهِ مشاهده‌شده.")
    print("  ⚠️ میانه از میانگین خیلی کمتر است ⇒ مزیت **دم‌کلفت** است:")
    print("     چند دورهٔ خیلی خوب کار را می‌سازند، نه همهٔ دوره‌ها.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
