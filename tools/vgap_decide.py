# -*- coding: utf-8 -*-
"""قاعدهٔ مصطفی دربارهٔ خلای حجمی — دقیقاً همان‌طور که گفت.

> «هرگاه ناحیهٔ خلا حجمی شکل گرفت، هرگاه **کلوزِ روزِ بعد** بالا یا
> پایینِ ناحیه بود، مبنای تصمیم‌گیریِ ما خواهد بود.»
> «مبنای اصلیِ این استراتژی کندلِ **هفتگی** هست و **ماهانه**.»

کدی که تا امروز اجرا می‌شد هیچ‌کدامِ این دو را نداشت:

  * `vgap_state()` روی سریِ **دیلی** بسته می‌شد، نه هفتگی/ماهانه.
  * و کلوزِ **امروز** را با ناحیه می‌سنجید، نه کلوزِ **روزِ بعد از
    تشکیلِ ناحیه**.

فرقش روی موج (کلوزِ ۲۰۲۶-۰۹-۲۰):

    دیلی، کلوزِ امروز      ناحیه ۹۰٬۵۱۱–۹۴٬۱۳۱ → **زیر**
    هفتگی، کلوزِ تصمیم     ناحیه ۶۹٬۵۳۸–۸۴٬۶۴۱ · کلوزِ ۰۹-۱۹ =
                           ۸۹٬۲۷۱ → **بالا**

یعنی همان نمادی که او «شکستِ ناحیه» می‌بیند، کد «زیر» می‌خواند و
سیگنالش را یک پله پایین می‌آورد.

اینجا چهار تعریف با هم سنجیده می‌شوند، همه روی یک جهان و یک افق،
با نرخ پایه و آزمونِ جایگشتِ درون‌دوره‌ای (CLAUDE.md بند ۰ قاعدهٔ ۲):

    now_d    کلوزِ امروز در برابرِ ناحیهٔ **دیلی**   ← کدِ فعلی
    now_w    کلوزِ امروز در برابرِ ناحیهٔ **هفتگی**
    dec_w    کلوزِ **روزِ بعد از ناحیه**، هفتگی      ← قاعدهٔ مصطفی
    dec_m    همان، ماهانه

    python3 tools/vgap_decide.py --tf week
"""
import argparse
import random
import statistics
import sys
from collections import OrderedDict, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bourse as B                                        # noqa: E402

FA = {"m": "ماهانه", "w": "هفتگی", "d": "دیلی"}


def agg(rows, tf):
    """کندل‌های تجمیع‌شده، با کلید دوره."""
    if tf == "d":
        return [dict(r, k=r["d"]) for r in rows]
    b = OrderedDict()
    for r in rows:
        d = r["d"]
        k = (d.year, d.month) if tf == "m" else B.week_key(d)
        e = b.get(k)
        if e is None:
            b[k] = {"d": d, "k": k, "h": r["h"], "l": r["l"],
                    "c": r["c"], "v": r["v"]}
        else:
            e["h"] = max(e["h"], r["h"])
            e["l"] = min(e["l"], r["l"])
            e["c"] = r["c"]
            e["v"] += r["v"]
            e["d"] = d
    return list(b.values())


def zones(bars):
    """هر خلای حجمیِ تأییدشده: (اندیسِ ناحیه، کف، سقف)."""
    out = []
    for i in range(1, len(bars) - 1):
        if (bars[i]["v"] < bars[i - 1]["v"]
                and bars[i]["v"] < bars[i + 1]["v"]):
            out.append((i, bars[i]["l"], bars[i]["h"]))
    return out


def states(rows, tf, mode):
    """dict[اندیسِ کندلِ دیلی] = وضعیت، بدونِ لوک‌اهد.

    `mode="now"`  کلوزِ همان روز در برابرِ آخرین ناحیهٔ تأییدشده
    `mode="dec"`  حکمِ **کلوزِ روزِ بعد از ناحیه**، تا ناحیهٔ بعدی
    """
    bars = agg(rows, tf)
    zs = zones(bars)
    if not zs:
        return {}
    # نگاشتِ کندلِ دیلی → اندیسِ دوره
    per = {}
    if tf == "d":
        for i, b in enumerate(bars):
            per[b["d"]] = i
    else:
        kx = {b["k"]: i for i, b in enumerate(bars)}
        for r in rows:
            k = ((r["d"].year, r["d"].month) if tf == "m"
                 else B.week_key(r["d"]))
            if k in kx:
                per[r["d"]] = kx[k]
    # اولین کلوزِ دیلی بعد از بسته شدنِ هر دوره، و اولین کلوزِ هر دوره
    tfk = tf
    first_of, first_after = {}, {}
    for r in rows:
        i = per.get(r["d"])
        if i is None:
            continue
        first_of.setdefault(i, r["c"])
        # ناحیهٔ g وقتی تأیید می‌شود که دورهٔ g+1 بسته شود؛ اولین
        # کلوزِ بعدش در دورهٔ g+2 است.
        if i >= 2:
            first_after.setdefault((tfk, i - 2), r["c"])
    out = {}
    for r in rows:
        i = per.get(r["d"])
        if i is None:
            continue
        # ناحیه‌ای که در آن لحظه **تأیید شده** بود: g+1 <= i-1 برای
        # دوره‌های کامل‌شده. یعنی g <= i-2.
        z = None
        for g, lo, hi in zs:
            if g + 1 <= i - 1:
                z = (g, lo, hi)
            else:
                break
        if z is None:
            continue
        g, lo, hi = z
        if mode == "now":
            c = r["c"]
        elif mode == "dec":
            # کلوزِ **دورهٔ بعدی** (هفتهٔ بعد / ماهِ بعد)
            c = bars[g + 1]["c"]
        elif mode == "dec1":
            # کلوزِ **اولین روزِ معاملاتی بعد از تأیید شدنِ ناحیه** —
            # یعنی روزِ بعد، به معنای روز نه دوره. ناحیه وقتی تأیید
            # می‌شود که دورهٔ g+1 بسته شود؛ اولین کلوزِ بعد از آن.
            c = first_after.get((tfk, g))
            if c is None:
                continue
        elif mode == "decday":
            # کلوزِ **اولین روزِ دورهٔ جاری** در برابرِ آخرین ناحیهٔ
            # تأییدشده — هر دوره دوباره خوانده می‌شود، همان قاعدهٔ
            # DECIDE_FUND که برای باکسِ POC اندازه‌گیری شده بود.
            c = first_of.get(i)
            if c is None:
                continue
        out[r["d"]] = ("بالا" if c > hi else "زیر" if c < lo else "داخل")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_bourse")
    ap.add_argument("--tf", choices=("week", "month"), default="week")
    ap.add_argument("--iters", type=int, default=5000)
    ap.add_argument("--min-days", type=int, default=100)
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    d = root / args.data
    data = {}
    for f in sorted(d.glob("*.csv")):
        if f.stem in ("capital", "track"):
            continue
        r = B.load(f.stem)
        if len(r) >= args.min_days:
            data[f.stem] = r
    print(f"\n  {len(data)} نماد · افقِ {args.tf}")

    DEFS = (("now_d", "کلوزِ امروز × ناحیهٔ دیلی  (کدِ فعلی)", "d", "now"),
            ("now_w", "کلوزِ امروز × ناحیهٔ هفتگی", "w", "now"),
            ("dec_w", "کلوزِ دورهٔ بعد × هفتگی", "w", "dec"),
            ("dec1_w", "اولین کلوزِ بعد از تأییدِ ناحیه × هفتگی",
             "w", "dec1"),
            ("decday_w", "کلوزِ روزِ تصمیمِ هر هفته × ناحیهٔ هفتگی",
             "w", "decday"),
            ("decday_m", "کلوزِ روزِ تصمیمِ هر ماه × ناحیهٔ ماهانه",
             "m", "decday"))

    # افقِ بازده: هفتهٔ بعد یا ماهِ بعد، روی کلوزِ دورهٔ تصمیم
    obs = defaultdict(list)          # (تعریف، وضعیت) → [(دوره، بازده)]
    base = defaultdict(list)
    for sym, rows in data.items():
        bars = agg(rows, "w" if args.tf == "week" else "m")
        if len(bars) < 4:
            continue
        st = {k: states(rows, tf, md) for k, _fa, tf, md in DEFS}
        for i in range(1, len(bars) - 1):
            dd = bars[i]["d"]                 # آخرین روزِ دورهٔ i
            ret = (bars[i + 1]["c"] / bars[i]["c"] - 1) * 100
            base[bars[i]["k"]].append(ret)
            for k, _fa, _tf, _md in DEFS:
                s = st[k].get(dd)
                if s:
                    obs[(k, s)].append((bars[i]["k"], ret))

    allret = [v for vs in base.values() for v in vs]
    b_mean = statistics.fmean(allret)
    b_pos = sum(1 for v in allret if v > 0) / len(allret) * 100
    print(f"  نرخ پایه: {b_mean:+.2f}٪ · {b_pos:.1f}٪ مثبت · "
          f"n={len(allret):,}\n")
    print(f"  {'تعریف':<40}{'وضعیت':<7}{'n':>7}{'مثبت':>7}"
          f"{'میانگین':>10}{'مزیت':>9}{'p':>8}")
    print("  " + "─" * 88)

    by_per = {k: vs for k, vs in base.items()}
    for k, fa, _tf, _md in DEFS:
        for s in ("بالا", "داخل", "زیر"):
            v = obs.get((k, s))
            if not v or len(v) < 30:
                continue
            rs = [x[1] for x in v]
            m = statistics.fmean(rs)
            pos = sum(1 for x in rs if x > 0) / len(rs) * 100
            # جایگشتِ درون‌دوره‌ای: برچسب داخلِ هر دوره به‌هم می‌ریزد
            cnt = defaultdict(int)
            for p, _ in v:
                cnt[p] += 1
            rnd = random.Random(7)
            hit = 0
            for _ in range(args.iters):
                tot, n = 0.0, 0
                for p, c in cnt.items():
                    pool = by_per.get(p) or []
                    if len(pool) < c:
                        continue
                    tot += sum(rnd.sample(pool, c))
                    n += c
                if n and tot / n >= m:
                    hit += 1
            pv = (hit + 1) / (args.iters + 1)
            star = " ★" if pv < 0.05 else ""
            print(f"  {fa:<40}{s:<7}{len(rs):>7,}{pos:>6.1f}٪"
                  f"{m:>+9.2f}٪{m - b_mean:>+9.2f}{pv:>8.4f}{star}")
        print()
    print("  ★ = از نرخ پایهٔ همان دوره جدا شد.")
    print("  «مزیت» واحدِ درصد است نسبت به نرخ پایه.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
