# -*- coding: utf-8 -*-
"""محرکِ واقعیِ هر نماد را از همبستگی دربیاور، نه از برچسبِ دسته.

مصطفی: «صندوق‌های مثل سینرژی جزو صندوق‌های سهامی نیست، جزو صندوق‌های
انرژی و نفت و گاز هست که بیشترش بر اساس نفت برنت هست.» و راست می‌گفت —
`data/extracted/TODAY.json` سینرژی را «سهامی» زده، پس `EXPOSURE` محرکش را
شاخص کل گذاشته بود.

به‌جای اینکه یکی‌یکی دستی درست کنیم، همبستگیِ **بازده روزانه** هر نماد را
با هر محرک حساب می‌کنیم و می‌گوییم کدام محرک واقعاً حرکتش را توضیح می‌دهد.
برچسب فروشنده یک ادعاست؛ این یک اندازه‌گیری است.

    python3 tools/attribute.py --min-days 60
    python3 tools/attribute.py --only سینرژی,عیار,زیتون,شیلد

نکتهٔ تقویم: بازده‌ها روی **تاریخ‌های مشترک** هم‌تراز می‌شوند. اونس و نفت
دوشنبه تا جمعه‌اند و صندوق‌ها شنبه تا چهارشنبه، پس اشتراکشان دوشنبه تا
چهارشنبه است — همبستگی روی همان سه روز حساب می‌شود، که کمتر از حالت
ایده‌آل است ولی بدونِ لغزشِ تاریخ.
"""
import argparse
import json
import math
import statistics
from pathlib import Path

from monthly_backtest import load_daily, norm
from breadth import DRIVER_FILE, NAME


def rets(rows):
    """dict[تاریخ] = بازده درصدی همان روز."""
    out = {}
    for i in range(1, len(rows)):
        p0, p1 = rows[i - 1][1].c, rows[i][1].c
        if p0 > 0:
            out[rows[i][0]] = (p1 - p0) / p0 * 100
    return out


def corr(a, b):
    ks = sorted(set(a) & set(b))
    if len(ks) < 20:
        return None, len(ks)
    xs, ys = [a[k] for k in ks], [b[k] for k in ks]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None, len(ks)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return cov / (sx * sy), len(ks)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_auto")
    ap.add_argument("--drivers", default="data/drivers_daily")
    ap.add_argument("--min-days", type=int, default=60)
    ap.add_argument("--only", default=None,
                    help="فقط این نمادها، با کاما جدا")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    cat = {}
    tp = root / "data/extracted/TODAY.json"
    if tp.exists():
        for r in json.loads(tp.read_text(encoding="utf-8")):
            cat[norm(r["نماد"])] = r["دسته"]

    drv = {}
    for did, fn in list(DRIVER_FILE.items()) + [("xau", "اونس_طلا")]:
        p = Path(args.drivers) / f"{fn}_daily.csv"
        if p.exists():
            drv[did] = rets(load_daily(p))
    if not drv:
        print("محرکی نیست.")
        return 1

    only = ({norm(s.strip()) for s in args.only.split(",")}
            if args.only else None)

    out, seen = [], set()
    for p in sorted(Path(args.data).glob("*.csv")):
        sym = p.stem.replace("_daily", "").replace("_", " ")
        if only and norm(sym) not in only:
            continue
        if norm(sym) in seen:
            continue
        rows = load_daily(p)
        if len(rows) < args.min_days:
            continue
        seen.add(norm(sym))
        r = rets(rows)
        cs = []
        for did, dr in drv.items():
            c, n = corr(r, dr)
            if c is not None:
                cs.append((abs(c), c, did, n))
        if not cs:
            continue
        cs.sort(reverse=True)
        best = cs[0]
        out.append({"sym": sym, "cat": cat.get(norm(sym), "؟"),
                    "best": best[2], "r": best[1], "n": best[3],
                    "all": {d: round(c, 3) for _, c, d, _ in cs}})

    if not out:
        print("هیچ نمادی واجد شرط نشد.")
        return 1

    # چه محرکی برای دستهٔ برچسب‌خورده «طبیعی» است — تا ناهماهنگی دیده شود
    NATURAL = {"طلا": {"xau", "dollar", "gold18", "cert_gold"},
               "نقره": {"xag", "dollar", "cert_silver"},
               "اهرمی": {"tedpix", "eqwt"}, "سهامی": {"tedpix", "eqwt"},
               "شاخصی": {"tedpix", "eqwt"}, "بانکی": {"tedpix", "eqwt"},
               "مختلط": {"tedpix", "eqwt"}, "املاک": {"tedpix", "eqwt"},
               "بخشی": {"tedpix", "eqwt", "oil", "copper", "dollar"},
               "کالا": {"xau", "dollar", "oil", "copper"},
               "صندوق_در_صندوق": {"tedpix", "eqwt"}}

    print("=" * 78)
    print("محرکِ غالبِ هر نماد — از همبستگیِ بازده روزانه")
    print("=" * 78)
    print(f"\n{'نماد':<12}{'دستهٔ برچسب':<14}{'محرک غالب':<16}"
          f"{'r':>7}{'روز':>6}   دومی")
    print("─" * 78)
    out.sort(key=lambda r: (r["best"], -abs(r["r"])))
    mism = []
    for r in out:
        nat = NATURAL.get(r["cat"], set())
        bad = nat and r["best"] not in nat
        second = sorted(r["all"].items(), key=lambda kv: -abs(kv[1]))[1:2]
        s2 = (f"{NAME.get(second[0][0], second[0][0])} {second[0][1]:+.2f}"
              if second else "—")
        flag = "  ⚠" if bad else ""
        print(f"{r['sym']:<12}{r['cat']:<14}"
              f"{NAME.get(r['best'], r['best']):<16}{r['r']:>+7.2f}"
              f"{r['n']:>6}   {s2}{flag}")
        if bad:
            mism.append(r)

    if mism:
        print(f"\n⚠️ {len(mism)} نماد محرکِ غالبش با دسته‌اش نمی‌خواند:")
        for r in mism:
            print(f"   {r['sym']} — برچسب «{r['cat']}» ولی "
                  f"{NAME.get(r['best'], r['best'])} r={r['r']:+.2f}")
        print("\n   این‌ها در EXPOSURE محرکِ غلط می‌گیرند. `OVERRIDE` در")
        print("   tools/drivers.py جای اصلاحشان است.")

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nJSON: {Path(args.json_out).resolve()}")
    print("\n" + "=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
