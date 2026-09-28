# -*- coding: utf-8 -*-
"""وقتی چند نماد هم‌زمان سیگنال می‌شوند، کدام اول؟

مصطفی:

> «انتخاب بین چند سیگنال منظورم این هست که بازارهای جهانی
> تأثیرپذیرش را مدّ نظر قرار بده، و همچنین میزان بازدهی که به طور
> میانگین داشته‌اند اولویت باشد.»

دو محورِ اولویت است، نه یکی:

  ۱. **محرکِ جهانیِ خودِ آن نماد**
  ۲. **بازدهیِ تاریخی** — مازادِ دنباله‌دار نسبت به کهربا

## جوابی که درآمد

**محرک دروازه نیست، وزنه است.** حذف در هر پنج شکلش ضرر داد؛
اضافه‌کردن به امتیاز سود داد. شرحِ کامل در `docs/33`.

    مازاد + پاسخِ محرک (۱۰ روز)   ۱٫۱۹۱   ← پذیرفته شد
    مازادِ کهربا به‌تنهایی        ۱٫۱۵۲
    حذفِ نمادی که محرکش منفی است  ۱٫۰۶۴
    حذفِ محرکِ زیرِ باکس          ۱٫۰۵۶

## روش

- محرکِ هر نماد **اندازه‌گیری** می‌شود نه برچسب‌گذاری.
- **بدونِ لوک‌اهد.** حالتِ محرکِ جهانی فقط از روزهای **قبل از** روزِ
  تصمیم خوانده می‌شود — اونس و نفت به وقتِ نیویورک بسته می‌شوند.
- معیار **تعدادِ واحدِ کهرباست**، نه ریال (`docs/18`).
- سه کنترل: نیمه‌به‌نیمه، ترتیبِ تصادفی، و آزمونِ مقطعیِ جایگشتی.

    python3 tools/driver_rank.py
"""
import argparse
import math
import statistics
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from monthly_backtest import load_daily, is_fixed_income, norm  # noqa: E402
from vp_box import make_box, state  # noqa: E402

BENCH = "کهربا"
DRV_DIR = "data/drivers_daily"
# محرک‌هایی که به وقتِ نیویورک/لندن بسته می‌شوند. کلوزِ روزِ d آن‌ها
# ساعتِ ۱۲:۳۰ تهرانِ همان روز هنوز منتشر نشده.
GLOBAL = {"اونس_طلا", "اونس_نقره", "نفت_برنت", "مس"}


def load_drivers(path):
    out = {}
    for f in sorted(Path(path).glob("*_daily.csv")):
        name = f.stem[:-6]
        r = load_daily(f)
        if len(r) >= 300:
            out[name] = {d: b for d, b in r}
    return out


def rets(cl):
    """بازدهِ لگاریتمیِ روزانه، کلید = روزِ دوم."""
    o = {}
    ks = sorted(cl)
    for i in range(1, len(ks)):
        a, b = ks[i - 1], ks[i]
        if cl.get(a, 0) > 0 and cl.get(b, 0) > 0:
            o[b] = math.log(cl[b] / cl[a])
    return o


def _last(ks, d, strict):
    """آخرین روزِ محرک قبل از (یا تا) d — جست‌وجوی دودویی."""
    import bisect
    i = bisect.bisect_left(ks, d) if strict else bisect.bisect_right(ks, d)
    return ks[i - 1] if i else None


def drv_rets(dcl, fdays, strict):
    """بازدهِ محرک روی **همان بازهٔ تقویمیِ** هر روزِ معاملاتیِ نماد.

    چرا نه همبستگیِ ساده: هفتهٔ ایران شنبه تا چهارشنبه است و هفتهٔ
    جهانی دوشنبه تا جمعه — اشتراکشان سه روز است و نصفِ نمونه
    می‌سوزد. و مهم‌تر: اونس شبانه حرکت می‌کند و تهران صبح واکنش
    می‌دهد، پس جهتِ درست «محرکِ **تا قبل از** امروز → بازدهِ امروز»
    است، نه کلوزِ هم‌زمان که اصلاً در دسترس نیست.
    """
    ks = sorted(dcl)
    o, fd = {}, sorted(fdays)
    for i in range(1, len(fd)):
        p, d = fd[i - 1], fd[i]
        a, b = _last(ks, p, strict), _last(ks, d, strict)
        if a is None or b is None or a == b:
            continue
        if dcl[a] > 0 and dcl[b] > 0:
            o[d] = math.log(dcl[b] / dcl[a])
    return o


def corr(a, b, need=80):
    ks = sorted(set(a) & set(b))
    if len(ks) < need:
        return None, len(ks)
    x = [a[k] for k in ks]
    y = [b[k] for k in ks]
    mx, my = statistics.fmean(x), statistics.fmean(y)
    sx = math.sqrt(sum((v - mx) ** 2 for v in x))
    sy = math.sqrt(sum((v - my) ** 2 for v in y))
    if sx <= 0 or sy <= 0:
        return None, len(ks)
    c = sum((u - mx) * (v - my) for u, v in zip(x, y)) / (sx * sy)
    return c, len(ks)


def driver_map(cl, dcl, floor=0.15):
    """برای هر نماد، محرکی که بیشترین همبستگیِ **باتأخیر** را دارد."""
    out = {}
    for s, c in cl.items():
        sr = rets(c)
        best = (None, 0.0, 0)
        for k, v in dcl.items():
            dv = drv_rets(v, set(c), k in GLOBAL)
            cc, n = corr(sr, dv)
            if cc is not None and abs(cc) > abs(best[1]):
                best = (k, cc, n)
        out[s] = best if abs(best[1]) >= floor else (None, best[1], best[2])
    return out


def periods(days, mode, anchor=6):
    b = defaultdict(list)
    for d in days:
        k = ((d.year, d.month) if mode == "month"
             else d - timedelta(days=(d.weekday() - anchor) % 7))
        b[k].append(d)
    return [(k, b[k]) for k in sorted(b)]


def drv_box_state(dv, pdays, dec, name, kind):
    """حالتِ محرک نسبت به باکسِ دورهٔ کاملِ قبلِ **خودش**.

    شتاب تعریفِ من بود؛ این تعریفِ خودِ سیستم است (CLAUDE.md بند ۱).
    """
    prev = [dv[d] for d in sorted(dv) if d in set(pdays)]
    if len(prev) < 3:
        return None
    box = make_box(kind, prev, ref_price=prev[-1].c)
    if box is None:
        return None
    ks = [d for d in dv if (d < dec if name in GLOBAL else d <= dec)]
    if not ks:
        return None
    return state(dv[max(ks)].c, box)


def drv_signal(dcl, dec, name, look):
    """شتابِ محرک تا **قبل از** روزِ تصمیم. خروجی: درصد، یا None."""
    ks = [d for d in dcl if (d < dec if name in GLOBAL else d <= dec)]
    if len(ks) < look + 1:
        return None
    ks.sort()
    a, b = dcl[ks[-1 - look]], dcl[ks[-1]]
    if a <= 0:
        return None
    return (b / a - 1) * 100


BOXRANK = {"بالا": 0, "داخل": 1, "زیر": 2, None: 1}


def run(raw, cl, syms, ps, mode, dmap, dcl, kind, cost,
        n_max=6, wcap=0.25, look=40, dlook=20, rank="bx",
        blend=1.0, lo=None, hi=None, drv=None):
    """خروجی: (نسبتِ واحدِ کهربا، گردش، تعدادِ دوره)"""
    bench = cl[BENCH]
    eq, w = 1.0, {}
    turn_tot, nper = 0.0, 0
    rng = ps[lo:hi] if (lo is not None or hi is not None) else ps
    for i in range(1, len(rng)):
        _pk, pdays = rng[i - 1]
        _ck, cdays = rng[i]
        if len(pdays) < 3 or not cdays:
            continue
        dec, end = cdays[0], cdays[-1]
        st, ret, bx, ds = {}, {}, {}, {}
        dbox = {}
        if drv and rank.startswith("box"):
            for k, v in drv.items():
                dbox[k] = drv_box_state(v, pdays, dec, k, kind)
        for s in syms:
            v, c = raw[s], cl[s]
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
            hist = sorted(d for d in c if d <= dec)
            bh = sorted(d for d in bench if d <= dec)
            if len(hist) > look and len(bh) > look:
                bx[s] = ((c[hist[-1]] / c[hist[-1 - look]])
                         - (bench[bh[-1]] / bench[bh[-1 - look]])) * 100
            dn = dmap.get(s, (None,))[0]
            if dn:
                if rank.startswith("box"):
                    ds[s] = dbox.get(dn)
                else:
                    g = drv_signal(dcl[dn], dec, dn, dlook)
                    if g is not None:
                        ds[s] = g
        if BENCH not in ret:
            continue
        nper += 1
        up = [s for s in syms if st.get(s) == "بالا" and s in ret]
        up = [s for s in up if bx.get(s, 0.0) >= 0]

        if rank == "bx":
            up.sort(key=lambda s: -bx.get(s, 0.0))
        elif rank == "drv":
            up.sort(key=lambda s: -ds.get(s, -1e9))
        elif rank == "gate":                 # محرکِ منفی → حذف
            up = [s for s in up if ds.get(s, 0.0) >= 0]
            up.sort(key=lambda s: -bx.get(s, 0.0))
        elif rank == "tier":                 # اول محرکِ مثبت، بعد مازاد
            up.sort(key=lambda s: (0 if ds.get(s, 0.0) >= 0 else 1,
                                   -bx.get(s, 0.0)))
        elif rank == "blend":                # امتیازِ ترکیبی
            up.sort(key=lambda s: -(bx.get(s, 0.0)
                                    + blend * ds.get(s, 0.0)))
        elif rank == "beta":                 # شتابِ محرک × حساسیت
            up.sort(key=lambda s: -(ds.get(s, 0.0)
                                    * dmap.get(s, (None, 0.0))[1]))
        elif rank == "beta_bx":              # مازاد + پاسخِ محرک
            up.sort(key=lambda s: -(bx.get(s, 0.0) + blend * ds.get(s, 0.0)
                                    * dmap.get(s, (None, 0.0))[1]))
        elif rank == "box_gate":             # محرکِ زیرِ باکس → حذف
            up = [s for s in up if ds.get(s) != "زیر"]
            up.sort(key=lambda s: -bx.get(s, 0.0))
        elif rank == "box_only":             # فقط محرکِ بالای باکس
            up = [s for s in up if ds.get(s) == "بالا"]
            up.sort(key=lambda s: -bx.get(s, 0.0))
        elif rank == "box_tier":             # محرکِ بالاتر اول
            up.sort(key=lambda s: (BOXRANK.get(ds.get(s), 1),
                                   -bx.get(s, 0.0)))
        elif rank == "rand":                 # کنترل: ترتیبِ تصادفی
            import random as _r
            _g = _r.Random(hash((blend, dec)) & 0xffffffff)
            _g.shuffle(up)
        else:
            raise SystemExit(f"rank ناشناخته: {rank}")
        up = up[:n_max]

        if up:
            each = min(wcap, 1.0 / len(up))
            tgt = {s: each for s in up}
            rest = 1.0 - sum(tgt.values())
            if rest > 0.001:
                tgt[BENCH] = tgt.get(BENCH, 0.0) + rest
        else:
            tgt = {BENCH: 1.0}
        turn = sum(abs(tgt.get(s, 0) - w.get(s, 0))
                   for s in set(tgt) | set(w))
        turn_tot += turn
        eq *= (1 - cost / 100.0 * turn / 2)
        eq *= sum(tgt.get(s, 0) * ret.get(s, 1.0) for s in tgt)
        w = tgt
    if not nper:
        return None
    d0, d1 = rng[1][1][0], rng[-1][1][-1]
    hold = bench[d1] / bench[d0]
    return eq / hold, turn_tot / nper, nper



# ── آزمونِ مقطعی: در هر دوره، بینِ نامزدها ─────────────────────────
# شبیه‌سازیِ پرتفو فقط ۳۵ دورهٔ هفتگی و ۹ دورهٔ ماهانه دارد — برای
# جدا کردنِ قاعده از شانس کم است. اینجا **هر نامزد در هر دوره** یک
# مشاهده است: آیا در همان دوره، نامزدی که محرکش قوی‌تر بوده بازدهِ
# بهتری داد؟ مقایسه درون‌دوره‌ای است، پس حرکتِ کلِ بازار خنثی می‌شود.
def spearman(x, y):
    n = len(x)
    if n < 3:
        return None

    def rk(v):
        o = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[o[j + 1]] == v[o[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[o[k]] = avg
            i = j + 1
        return r

    a, b = rk(x), rk(y)
    ma, mb = statistics.fmean(a), statistics.fmean(b)
    sa = math.sqrt(sum((v - ma) ** 2 for v in a))
    sb = math.sqrt(sum((v - mb) ** 2 for v in b))
    if sa <= 0 or sb <= 0:
        return None
    return sum((u - ma) * (v - mb) for u, v in zip(a, b)) / (sa * sb)


def cross(raw, cl, syms, ps, mode, dmap, dcl, kind, look, dlook,
         iters=2000, seed=11):
    """rho درون‌دوره‌ایِ هر محور با بازدهِ دورهٔ بعد + p جایگشتی."""
    import random
    bench = cl[BENCH]
    obs = []                      # [(بازده، bx، شتابِ محرک، پاسخ)]
    for i in range(1, len(ps)):
        _pk, pdays = ps[i - 1]
        _ck, cdays = ps[i]
        if len(pdays) < 3 or not cdays:
            continue
        dec, end = cdays[0], cdays[-1]
        grp = []
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
            hist = sorted(d for d in c if d <= dec)
            bh = sorted(d for d in bench if d <= dec)
            if len(hist) <= look or len(bh) <= look:
                continue
            b = ((c[hist[-1]] / c[hist[-1 - look]])
                 - (bench[bh[-1]] / bench[bh[-1 - look]])) * 100
            if b < 0:
                continue
            dn, cc = dmap.get(s, (None, 0.0))[:2]
            g = drv_signal(dcl[dn], dec, dn, dlook) if dn else None
            if g is None:
                continue
            grp.append(((c[end] / c[dec] - 1) * 100, b, g, g * cc))
        if len(grp) >= 4:
            obs.append(grp)
    if not obs:
        return None
    names = ("مازادِ کهربا", "شتابِ محرک", "پاسخِ محرک (شتاب×حساسیت)")
    out = []
    for j, nm in enumerate(names, start=1):
        rs = [spearman([g[j] for g in grp], [g[0] for g in grp])
              for grp in obs]
        rs = [r for r in rs if r is not None]
        if not rs:
            continue
        m = statistics.fmean(rs)
        rnd = random.Random(seed + j)
        hit = 0
        for _ in range(iters):
            sh = []
            for grp in obs:
                xv = [g[j] for g in grp]
                rnd.shuffle(xv)
                r = spearman(xv, [g[0] for g in grp])
                if r is not None:
                    sh.append(r)
            if sh and abs(statistics.fmean(sh)) >= abs(m):
                hit += 1
        out.append((nm, m, (hit + 1) / (iters + 1), len(rs),
                    sum(len(g) for g in obs)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_bourse")
    ap.add_argument("--drivers", default=DRV_DIR)
    ap.add_argument("--cost", type=float, default=0.55)
    ap.add_argument("--kind", default="valley_first")
    ap.add_argument("--min-days", type=int, default=100)
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--wcap", type=float, default=0.25)
    ap.add_argument("--map-only", action="store_true")
    ap.add_argument("--dlook", type=int, default=10)
    ap.add_argument("--iters", type=int, default=2000)
    ap.add_argument("--seeds", type=int, default=40)
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
    drv = load_drivers(args.drivers)
    dcl = {k: {d: b.c for d, b in v.items()} for k, v in drv.items()}
    bdays = set(raw[BENCH])
    syms = [s for s in raw if len(set(raw[s]) & bdays) >= args.min_days]
    days = sorted(bdays)
    print(f"\n  {len(syms)} نماد · {len(days)} روز "
          f"({days[0]} تا {days[-1]}) · {len(drv)} محرک")

    dmap = driver_map(cl, dcl)
    byd = defaultdict(list)
    for s, (k, c, n) in dmap.items():
        byd[k].append((abs(c), s, c))
    print("\n  ══ محرکِ اندازه‌گیری‌شدهٔ هر نماد "
          "(همبستگیِ بازدهِ روزانه) ══")
    for k in sorted(byd, key=lambda x: (x is None, -len(byd[x]))):
        v = sorted(byd[k], reverse=True)
        nm = k if k else "— بی‌محرکِ روشن (زیرِ ۰٫۱۵)"
        top = " · ".join(f"{s} {c:+.2f}" for _a, s, c in v[:6])
        print(f"  {nm:<18} {len(v):>3} نماد   {top}")
    if args.map_only:
        return 0

    for mode, fa in (("week", "هفتگی"), ("month", "ماهانه")):
        ps = periods(days, mode)
        half = len(ps) // 2
        print(f"\n  ══ تصمیمِ {fa} · {len(ps)} دوره · "
              f"N={args.n} · سقفِ وزن {args.wcap:.0%} ══")
        print(f"  {'رتبه‌بندی':<26}{'نگاهِ محرک':>10}"
              f"{'واحدِ کهربا':>13}{'نیمهٔ ۱':>9}{'نیمهٔ ۲':>9}{'گردش':>8}")
        print("  " + "─" * 76)
        rows = []
        for rank, fa2 in (("bx", "مازادِ کهربا (فعلی)"),
                          ("drv", "فقط شتابِ محرک"),
                          ("gate", "حذفِ محرکِ منفی"),
                          ("tier", "محرکِ مثبت اول"),
                          ("blend", "امتیازِ ترکیبی"),
                          ("beta", "فقط پاسخِ محرک"),
                          ("beta_bx", "مازاد + پاسخِ محرک"),
                          ("box_gate", "حذفِ محرکِ زیرِ باکس"),
                          ("box_only", "فقط محرکِ بالای باکس"),
                          ("box_tier", "محرکِ بالاتر اول (باکس)")):
            for dlook in ((0,) if rank == "bx" or rank.startswith("box")
                          else (5, 10, 20, 40)):
                kw = dict(kind=args.kind, cost=args.cost, n_max=args.n,
                          wcap=args.wcap, dlook=max(dlook, 1), rank=rank,
                          drv=drv)
                a = run(raw, cl, syms, ps, mode, dmap, dcl, **kw)
                b = run(raw, cl, syms, ps, mode, dmap, dcl,
                        hi=half + 1, **kw)
                c = run(raw, cl, syms, ps, mode, dmap, dcl,
                        lo=half, **kw)
                if not a:
                    continue
                rows.append((a[0], fa2, dlook, b[0] if b else float("nan"),
                             c[0] if c else float("nan"), a[1]))
        base = next((r for r in rows if r[1] == "مازادِ کهربا (فعلی)"),
                    None)
        for r in sorted(rows, key=lambda x: -x[0]):
            mark = ""
            if (base and r[0] > base[0]
                    and r[3] > base[3] and r[4] > base[4]):
                mark = " ★"
            dl = "—" if not r[2] else f"{r[2]} روز"
            print(f"  {r[1]:<26}{dl:>10}{r[0]:>13.3f}"
                  f"{r[3]:>9.3f}{r[4]:>9.3f}{r[5]:>8.2f}{mark}")
        if base:
            print(f"\n  خطِ پایه (رتبه‌بندیِ فعلی): {base[0]:.3f} · "
                  f"نیمه‌ها {base[3]:.3f} / {base[4]:.3f}")
            print("  ★ = هم در کل و هم در **هر دو نیمه** از خطِ پایه جلو")
        # ── کنترلِ تصادفی ──────────────────────────────────────────
        # بدونِ این، عددِ خطِ پایه معلوم نیست از **رتبه‌بندی** آمده یا
        # فقط از «۶ نمادِ واجد شرط داشتن». CLAUDE.md بند ۰ قاعدهٔ ۲.
        rr = []
        for sd in range(args.seeds):
            o = run(raw, cl, syms, ps, mode, dmap, dcl, kind=args.kind,
                    cost=args.cost, n_max=args.n, wcap=args.wcap,
                    rank="rand", blend=float(sd))
            if o:
                rr.append(o[0])
        if rr and base:
            rr.sort()
            win = sum(1 for v in rr if v >= base[0]) / len(rr)
            print(f"  کنترلِ ترتیبِ تصادفی ({len(rr)} بذر): "
                  f"میانگین {statistics.fmean(rr):.3f} · "
                  f"بازه {rr[0]:.3f}–{rr[-1]:.3f} · "
                  f"{win:.0%} از بذرها از خطِ پایه بهترند")
        cr = cross(raw, cl, syms, ps, mode, dmap, dcl, args.kind,
                   40, args.dlook, iters=args.iters)
        if cr:
            print(f"\n  ── آزمونِ مقطعی (نگاهِ محرک {args.dlook} روز) ──")
            print(f"  {'محور':<28}{'rho درون‌دوره':>14}{'p':>9}"
                  f"{'دوره':>7}{'مشاهده':>9}")
            for nm, m, pv, nd, no in cr:
                print(f"  {nm:<28}{m:>+14.3f}{pv:>9.3f}{nd:>7}{no:>9}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
