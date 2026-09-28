# -*- coding: utf-8 -*-
"""چینشِ پرتفو در برابرِ کهربا — چند واحد بیشتر، با چه اندازهٔ خرید؟

مصطفی:

> «اگر ما این شیوه را برای سهام‌های پرتفو و مابقیِ صندوق‌های واجد
> شرایط به کار بگیریم، در ماهانه و هفتگی چقدر پرتفوی خود را نسبت به
> کهربا می‌توانیم بهبود ببخشیم؟ یعنی چینشِ پرتفو به چه نحوی باشد که
> بشود از صندوقِ کهربا بیشتر بازدهی گرفت، و مقدارِ خریدمان در خریدِ
> آن نمادها طبقِ بک‌تست به چه مقدار باشد، و چه مقدار با آن خریدها
> می‌شود بازدهیِ بیشتری کسب کرد؟»

## معیار

**تعدادِ واحدِ کهربا**، نه ریال. هولدِ کهربا = ۱٫۰۰ به‌تعریف. عددِ
۱٫۲۰ یعنی ۲۰٪ واحدِ بیشتر از اینکه از اول کهربا می‌خریدی و می‌نشستی.

`docs/18` نشان داد سنجشِ ریالی در تورمِ ایران تقریباً بی‌معناست.

## چه چیزی جارو می‌شود

    N        چند نماد هم‌زمان (۱ تا ۸)
    سقفِ وزن ۲۰٪ تا ۱۰۰٪
    افق     تصمیمِ هفتگی یا ماهانه
    فیلترِ کهربا  روشن/خاموش

## قیدها

- کارمزد روی **گردشِ واقعی**: `cost × Σ|Δw| / 2`
- بدونِ لوک‌اهد: باکس از دورهٔ کاملِ قبل، تصمیم روی کلوزِ **روزِ
  تصمیم** (اولین جلسهٔ دوره)
- «هرگز نقد نشو»: اگر هیچ نمادی واجد شرط نبود، **کهربا** نگه داشته
  می‌شود — نه نقد. (`docs/30`)
"""
import argparse
import itertools
import statistics
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from monthly_backtest import load_daily, is_fixed_income, norm  # noqa: E402
from vp_box import make_box, state  # noqa: E402

BENCH = "کهربا"


def periods(days, mode, anchor=6):
    b = defaultdict(list)
    for d in days:
        k = ((d.year, d.month) if mode == "month"
             else d - timedelta(days=(d.weekday() - anchor) % 7))
        b[k].append(d)
    return [(k, b[k]) for k in sorted(b)]


def run(data, cl, syms, ps, mode, n_max, wcap, cost, kind,
        bench_filter, look=40):
    """خروجی: (نسبتِ واحدِ کهربا، میانگینِ گردش، سهمِ زمانِ در بازار)"""
    bench = cl[BENCH]
    eq = 1.0
    w = {}
    turn_tot, nper = 0.0, 0
    for i in range(1, len(ps)):
        pk, pdays = ps[i - 1]
        ck, cdays = ps[i]
        if len(pdays) < 3 or not cdays:
            continue
        dec = cdays[0]              # کلوزِ روزِ تصمیم
        end = cdays[-1]
        st, ret, bx = {}, {}, {}
        for s in syms:
            v, c = data[s], cl[s]
            if dec not in v or end not in v:
                continue
            prev = [v[d] for d in pdays if d in v]
            if len(prev) < 3:
                continue
            box = make_box(kind, prev, ref_price=prev[-1].c)
            if box is None:
                continue
            st[s] = state(c[dec], box)
            ret[s] = c[end] / c[dec]
            # مازادِ دنباله‌دار نسبت به کهربا
            hist = sorted(d for d in c if d <= dec)
            bh = sorted(d for d in bench if d <= dec)
            if len(hist) > look and len(bh) > look:
                bx[s] = ((c[hist[-1]] / c[hist[-1 - look]])
                         - (bench[bh[-1]] / bench[bh[-1 - look]])) * 100
        if BENCH not in ret:
            continue
        nper += 1
        up = [s for s in syms if st.get(s) == "بالا"]
        if bench_filter:
            up = [s for s in up if bx.get(s, 0.0) >= 0]
        up = [s for s in up if s in ret]
        # رتبه: مازادِ دنباله‌دار، بزرگ‌تر بهتر
        up.sort(key=lambda s: -bx.get(s, 0.0))
        up = up[:n_max]
        if up:
            each = min(wcap, 1.0 / len(up))
            tgt = {s: each for s in up}
            rest = 1.0 - sum(tgt.values())
            if rest > 0.001:                 # باقی‌مانده → کهربا
                tgt[BENCH] = tgt.get(BENCH, 0.0) + rest
        else:
            tgt = {BENCH: 1.0}               # هیچ‌کدام واجد شرط نبود
        turn = sum(abs(tgt.get(s, 0) - w.get(s, 0))
                   for s in set(tgt) | set(w))
        turn_tot += turn
        eq *= (1 - cost / 100.0 * turn / 2)
        eq *= sum(tgt.get(s, 0) * ret.get(s, 1.0) for s in tgt)
        w = tgt
    if not nper:
        return None
    # نسبت به هولدِ کهربا
    d0 = ps[1][1][0]
    d1 = ps[-1][1][-1]
    hold = bench[d1] / bench[d0]
    return eq / hold, turn_tot / nper, nper


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_bourse")
    ap.add_argument("--cost", type=float, default=0.55)
    ap.add_argument("--kind", default="valley_first")
    ap.add_argument("--min-days", type=int, default=100)
    args = ap.parse_args()

    raw, cl = {}, {}
    for f in sorted(Path(args.data).glob("*.csv")):
        if f.stem == "capital" or is_fixed_income(norm(f.stem)):
            continue
        r = load_daily(f)
        if len(r) >= args.min_days:
            raw[f.stem] = {d: b for d, b in r}
            cl[f.stem] = {d: b.c for d, b in r}
    if BENCH not in raw:
        print(f"{BENCH} نیست."); return 1
    # فقط روزهایی که کهربا هم دارد
    bdays = set(raw[BENCH])
    syms = [s for s in raw if len(set(raw[s]) & bdays) >= args.min_days]
    days = sorted(bdays)
    print(f"\n  {len(syms)} نماد · {len(days)} روز "
          f"({days[0]} تا {days[-1]}) · کارمزد {args.cost}٪")
    print(f"  معیار: **تعدادِ واحدِ {BENCH}**. هولدِ {BENCH} = ۱٫۰۰\n")

    for mode, fa in (("week", "هفتگی"), ("month", "ماهانه")):
        ps = periods(days, mode)
        print(f"  ══ تصمیمِ {fa} · {len(ps)} دوره ══")
        print(f"  {'N':>3}{'سقفِ وزن':>10}{'فیلتر':>8}"
              f"{'واحدِ کهربا':>13}{'گردش':>8}")
        print("  " + "─" * 46)
        best = None
        for n_max, wcap, bf in itertools.product(
                (1, 2, 3, 4, 6, 8), (0.25, 0.34, 0.50, 1.00), (True, False)):
            if wcap * n_max < 0.99 and n_max > 1:
                pass
            out = run(raw, cl, syms, ps, mode, n_max, wcap, args.cost,
                      args.kind, bf)
            if not out:
                continue
            ratio, turn, _n = out
            if best is None or ratio > best[0]:
                best = (ratio, n_max, wcap, bf, turn)
        # جدول را فقط برای بهترین سقفِ وزن نشان بده تا خوانا بماند
        for n_max in (1, 2, 3, 4, 6, 8):
            for bf in (True, False):
                row = None
                for wcap in (0.25, 0.34, 0.50, 1.00):
                    out = run(raw, cl, syms, ps, mode, n_max, wcap,
                              args.cost, args.kind, bf)
                    if out and (row is None or out[0] > row[0]):
                        row = (out[0], wcap, out[1])
                if row:
                    mark = " ★" if best and abs(row[0] - best[0]) < 1e-9 else ""
                    print(f"  {n_max:>3}{row[1]:>9.0%}"
                          f"{'روشن' if bf else 'خاموش':>8}"
                          f"{row[0]:>13.3f}{row[2]:>8.2f}{mark}")
        if best:
            r, n_max, wcap, bf, turn = best
            print(f"\n  بهترین: {n_max} نماد · سقفِ وزن {wcap:.0%} · "
                  f"فیلتر {'روشن' if bf else 'خاموش'}")
            print(f"  → {r:.3f} برابرِ هولدِ {BENCH} "
                  f"({(r - 1) * 100:+.1f}٪ واحدِ بیشتر) · "
                  f"گردشِ {turn:.2f} در دوره\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
