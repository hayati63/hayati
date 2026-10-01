# -*- coding: utf-8 -*-
"""مبنای داشبوردِ سهام: کهربا، شاخص کل، هم‌وزن، یا شاخصِ خودِ نماد؟

مصطفی:

> «یک داشبورد جدا فقط برای تمامی سهام هم می‌بایست ساخته شود که
> ملاکِ تصمیم‌گیریِ آن بر اساس شاخص کل و شاخص کل هم‌وزن خواهد بود.»

در داشبوردِ صندوق‌ها مبنا **کهرباست** و دو کار می‌کند: فیلتر
(نمادی که از مبنا عقب است سیگنال نمی‌شود، `docs/30`) و رتبه‌بندی
(`docs/32`, `docs/33`). برای سهام، مبنا باید شاخص باشد. ولی کدام؟

چهار گزینه اینجا سنجیده می‌شود:

    کهربا              همان که هست
    شاخص کل            یک مبنای واحد برای همه
    شاخص هم‌وزن        یک مبنای واحد برای همه
    شاخصِ خودِ نماد    هر نماد در برابرِ شاخصی که با آن حرکت می‌کند
                       (از نقشهٔ اندازه‌گیری‌شدهٔ `driver_rank.py`)

## ⚠️ محدودیتی که باید بدانی

دادهٔ سهام در این مخزن نیست (`data_stocks/` خالی است — از TSETMC
زنده ساخته می‌شود). پس این آزمون روی **صندوق‌های سهامی** بسته
می‌شود: همان ۷۷ صندوقی که محرکشان اندازه‌گیری شد و شاخص کل یا
هم‌وزن درآمد. این نزدیک‌ترین پروکسیِ موجود به جهانِ سهام است، نه
خودِ آن. عددها را با همین قید بخوان.

    python3 tools/bench_pick.py
"""
import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import driver_rank as D                                     # noqa: E402
from monthly_backtest import load_daily, is_fixed_income, norm  # noqa: E402
from vp_box import make_box, state                          # noqa: E402

IDX = ("شاخص_کل", "شاخص_هم‌وزن")


def run(raw, cl, syms, ps, bench, dmap, kind, cost,
        n_max=6, wcap=0.25, look=40, rank="bx", drvmom=None,
        lo=None, hi=None, cash_ok=False, seed=0):
    """`bench`: سریِ مبنا (dict) یا "self" برای شاخصِ خودِ نماد.

    خروجی: نسبت به هولدِ **شاخص کل** — تا هر چهار گزینه با یک خط‌کش
    سنجیده شوند. مبنای فیلتر عوض می‌شود، معیارِ داوری نه.
    """
    import random
    yard = cl["__yard__"]
    eq, w = 1.0, {}
    nper = 0
    rng = ps[lo:hi] if (lo is not None or hi is not None) else ps
    for i in range(1, len(rng)):
        _a, pdays = rng[i - 1]
        _b, cdays = rng[i]
        if len(pdays) < 3 or not cdays:
            continue
        dec, end = cdays[0], cdays[-1]
        ret, bx, ds = {}, {}, {}
        for s in syms:
            v, c = raw[s], cl[s]
            if dec not in v or end not in v:
                continue
            prev = [v[d] for d in pdays if d in v]
            if len(prev) < 3:
                continue
            box = make_box(kind, prev, ref_price=prev[-1].c)
            if box is None or state(c[dec], box) != "بالا":
                continue
            ret[s] = c[end] / c[dec]
            bs = dmap[s][0] if bench == "self" else None
            b = bench if bench != "self" else cl.get("__idx__" + str(bs))
            if not b:
                continue
            hist = sorted(d for d in c if d <= dec)
            bh = sorted(d for d in b if d <= dec)
            if len(hist) <= look or len(bh) <= look:
                continue
            bx[s] = ((c[hist[-1]] / c[hist[-1 - look]])
                     - (b[bh[-1]] / b[bh[-1 - look]])) * 100
            if drvmom is not None:
                g = D.drv_signal(drvmom[dmap[s][0]], dec, dmap[s][0], 10)
                if g is not None:
                    ds[s] = g * dmap[s][1]
        nper += 1
        up = [s for s in ret if bx.get(s, -1e9) >= 0]
        if rank == "rand":
            random.Random(seed * 997 + nper).shuffle(up)
        else:
            up.sort(key=lambda s: -(bx.get(s, 0.0) + ds.get(s, 0.0)))
        up = up[:n_max]
        if up:
            each = min(wcap, 1.0 / len(up))
            tgt = {s: each for s in up}
            rest = 1.0 - sum(tgt.values())
            if rest > 0.001 and not cash_ok:
                # «هرگز نقد نشو» در جهانِ سهام معادلِ کهربا ندارد؛
                # باقی‌مانده وزنِ شاخص می‌گیرد (ETF شاخصی).
                tgt["__yard__"] = tgt.get("__yard__", 0.0) + rest
        else:
            tgt = {} if cash_ok else {"__yard__": 1.0}
        turn = sum(abs(tgt.get(s, 0) - w.get(s, 0))
                   for s in set(tgt) | set(w))
        eq *= (1 - cost / 100.0 * turn / 2)
        eq *= (sum(tgt.get(s, 0) * ret.get(s, 1.0) for s in tgt)
               + max(0.0, 1 - sum(tgt.values())))
        w = tgt
    if not nper:
        return None
    d0, d1 = rng[1][1][0], rng[-1][1][-1]
    yk = sorted(yard)
    a = max(d for d in yk if d <= d0)
    b = max(d for d in yk if d <= d1)
    return eq / (yard[b] / yard[a])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_bourse")
    ap.add_argument("--drivers", default="data/drivers_daily")
    ap.add_argument("--cost", type=float, default=1.20)
    ap.add_argument("--kind", default="valley_first")
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--wcap", type=float, default=0.25)
    ap.add_argument("--seeds", type=int, default=100)
    args = ap.parse_args()

    raw, cl = {}, {}
    for f in sorted(Path(args.data).glob("*.csv")):
        if f.stem == "capital" or is_fixed_income(norm(f.stem)):
            continue
        r = load_daily(f)
        if len(r) >= 100:
            raw[f.stem] = {d: b for d, b in r}
            cl[f.stem] = {d: b.c for d, b in r}
    drv = D.load_drivers(args.drivers)
    dcl = {k: {d: b.c for d, b in v.items()} for k, v in drv.items()}
    dmap = D.driver_map(cl, dcl)
    # جهانِ آزمون: فقط نمادهایی که محرکشان **شاخص** است
    syms = [s for s in cl if dmap.get(s, (None,))[0] in IDX]
    days = sorted(set(cl["کهربا"]))
    cl["__yard__"] = dcl["شاخص_کل"]
    for k in IDX:
        cl["__idx__" + k] = dcl[k]
    print(f"\n  جهانِ آزمون: {len(syms)} صندوقِ سهامی/شاخصی "
          f"(محرکشان شاخص است) · {len(days)} روز")
    nk = sum(1 for s in syms if dmap[s][0] == "شاخص_کل")
    print(f"  {nk} با شاخص کل · {len(syms) - nk} با هم‌وزن · "
          f"کارمزد {args.cost}٪ (سهام)")
    print(f"  معیارِ داوریِ همه: **هولدِ شاخص کل = ۱٫۰۰**\n")

    opts = [("کهربا", dcl if False else cl["کهربا"]),
            ("شاخص کل", dcl["شاخص_کل"]),
            ("شاخص هم‌وزن", dcl["شاخص_هم‌وزن"]),
            ("شاخصِ خودِ نماد", "self")]
    for mode, fa in (("week", "هفتگی"), ("month", "ماهانه")):
        ps = D.periods(days, mode)
        half = len(ps) // 2
        print(f"  ══ تصمیمِ {fa} · {len(ps)} دوره · N={args.n} ══")
        print(f"  {'مبنای فیلتر و رتبه':<22}{'شاخص کل':>10}"
              f"{'نیمهٔ ۱':>9}{'نیمهٔ ۲':>9}{'+محرک':>9}")
        print("  " + "─" * 60)
        for nm, b in opts:
            kw = dict(kind=args.kind, cost=args.cost, n_max=args.n,
                      wcap=args.wcap)
            a = run(raw, cl, syms, ps, b, dmap, **kw)
            h1 = run(raw, cl, syms, ps, b, dmap, hi=half + 1, **kw)
            h2 = run(raw, cl, syms, ps, b, dmap, lo=half, **kw)
            g = run(raw, cl, syms, ps, b, dmap, drvmom=dcl, **kw)
            if a is None:
                continue
            print(f"  {nm:<22}{a:>10.3f}{h1:>9.3f}{h2:>9.3f}{g:>9.3f}")
        rr = []
        for sd in range(args.seeds):
            o = run(raw, cl, syms, ps, dcl["شاخص_کل"], dmap,
                    kind=args.kind, cost=args.cost, n_max=args.n,
                    wcap=args.wcap, rank="rand", seed=sd + 1)
            if o:
                rr.append(o)
        if rr:
            rr.sort()
            print(f"  {'کنترلِ ترتیبِ تصادفی':<22}"
                  f"{statistics.fmean(rr):>10.3f}"
                  f"{'':>9}{'':>9}   ۵–۹۵٪ {rr[int(.05*len(rr))]:.3f}"
                  f"–{rr[int(.95*len(rr))]:.3f}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
