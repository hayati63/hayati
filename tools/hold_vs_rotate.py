#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""هولد در برابر چرخش — قاعده‌های ۵۵، ۵۸، ۵۹، ۹۲.

سه سؤالِ صریحِ خودش که تا امروز جوابِ عددی نگرفته بود:

  ۵۵ (پیام ۱۰۹/۱۱۰) «فقط عیار رو در یک سال تست بگیر: **هولدش کنی
     چقدر** سود میده، و **بر اساس استراتژی خرید و فروش کنی چقدر**.»
  ۵۹ (پیام ۱۰۹) دو سناریو: «(الف) پنجاه درصد طلا پنجاه درصد سهام، و
     **داخلِ** هر کدام نوسان بگیریم تا تعدادِ واحد زیاد شود · (ب) نه،
     **بچرخونیم** — از یک بازار کامل خارج بشیم و داخلِ بازارِ دیگه‌ای.»
  ۵۸ و ۹۲ (پیام ۱۰۳) «اینا باید **نسبتی** هم داشته باشه… **اون نسبتِ
     بهینه** رو هم باید به من بگی. پنجاه‌پنجاه؟ هفتاد‌سی؟»

قاعدهٔ خروج همان قاعدهٔ خودش است و هیچ چیز دیگری:

    «اگر بالای باکس باز شد ماهانه یا هفتگی اصلا نیاز نیست بفروشیم…
     **ما فقط در صورتی میفروشیم که زیر باکس باز شه. همین.**»  [۱۱۰]

پس در این بک‌تست: بالای باکس → داخل بازار · زیرِ باکس → بیرون. حد سود
نیست، تارگت نیست، آستانهٔ درصدی نیست — چون او نگفته.

    python tools/hold_vs_rotate.py
    python tools/hold_vs_rotate.py --tf m --cost 0.55
"""
from __future__ import annotations
import argparse
import pathlib
import statistics
import sys
from collections import defaultdict

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import bourse as B                                    # noqa: E402

GOLD = {"طلا", "نقره", "کالایی"}
EQ = {"اهرمی", "سهامی", "بخشی", "شاخصی", "مختلط"}


def periods(rows, tf):
    """کندل‌های تجمیع‌شده + کلوزِ روزِ تصمیمِ هر دوره."""
    g = defaultdict(list)
    for r in rows:
        k = (r["d"].year, r["d"].month) if tf == "m" else B.week_key(r["d"])
        g[k].append(r)
    ks = sorted(g)
    return ks, g


def strat_series(rows, tf):
    """(دوره، بازدهِ نماد، داخلِ بازار بودیم؟) — قاعدهٔ خودش.

    باکس از دورهٔ **کامل‌شدهٔ قبل**. حکم روی **کلوزِ روزِ تصمیم** —
    اولین جلسهٔ دورهٔ جاری، چون هفته شنبه می‌بندد و یکشنبه تصمیم است.
    بدونِ لوک‌اهد: تصمیمِ دورهٔ i فقط از باکسِ i−1 و کلوزِ روزِ اولِ i.
    """
    ks, g = periods(rows, tf)
    out = []
    for i in range(2, len(ks)):
        box = B.make_box(g[ks[i - 1]])
        if box is None:
            box = B.value_area_box(g[ks[i - 1]])
        if box is None:
            continue
        lo, hi = box
        cur = g[ks[i]]
        dec = cur[0]["c"]                  # کلوزِ روزِ تصمیم
        c0, c1 = g[ks[i - 1]][-1]["c"], cur[-1]["c"]
        if c0 <= 0:
            continue
        ret = c1 / c0 - 1
        out.append((ks[i], ret, dec > hi))
    return out


def compound(seq, cost):
    """بازدهِ مرکب با کارمزد روی هر **تغییرِ وضعیت**."""
    v, prev = 1.0, False
    for _k, ret, inn in seq:
        if inn != prev:
            v *= (1 - cost / 100)
        if inn:
            v *= (1 + ret)
        prev = inn
    return v - 1


def hold(seq):
    v = 1.0
    for _k, ret, _i in seq:
        v *= (1 + ret)
    return v - 1


def sleeve_series(per_sym, cats):
    """سبدِ هم‌وزنِ یک طبقه: هر دوره میانگینِ بازدهِ نمادهای داخلِ بازار.

    سناریوی الف — «داخلِ هر کدام نوسان بگیریم». اگر در یک دوره هیچ
    نمادِ آن طبقه بالای باکسش نبود، آن دوره نقد است (بازدهِ صفر).
    """
    by_k = defaultdict(list)
    for sym, seq in per_sym.items():
        if B.NORM_CAT.get(B.norm(sym)) not in cats:
            continue
        for k, ret, inn in seq:
            by_k[k].append((ret, inn))
    out = []
    for k in sorted(by_k):
        ins = [r for r, i in by_k[k] if i]
        out.append((k, statistics.mean(ins) if ins else 0.0, bool(ins)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", choices=["w", "m"], default="w")
    ap.add_argument("--cost", type=float, default=0.55,
                    help="کارمزدِ رفت‌وبرگشت ٪ (صندوق ۰٫۵۵، سهام ۱٫۲)")
    ap.add_argument("--min-periods", type=int, default=12)
    a = ap.parse_args()
    fa = "هفتگی" if a.tf == "w" else "ماهانه"

    per_sym = {}
    for p in sorted((HERE / "data_bourse").glob("*.csv")):
        rows = B.load(p.stem)
        if len(rows) < 60:
            continue
        seq = strat_series(rows, a.tf)
        if len(seq) >= a.min_periods:
            per_sym[p.stem] = seq

    print("=" * 74)
    print(f"  هولد در برابر چرخش — افقِ {fa} · کارمزد {a.cost}٪")
    print(f"  قاعدهٔ خروج: «فقط در صورتی می‌فروشیم که زیرِ باکس بسته شود»")
    print("=" * 74)
    print(f"  {len(per_sym)} نماد · "
          f"{min(len(s) for s in per_sym.values())}–"
          f"{max(len(s) for s in per_sym.values())} دوره\n")

    # ── قاعدهٔ ۵۵ · تک‌نماد ───────────────────────────────────────
    print("  ── قاعدهٔ ۵۵ · هر نماد: هولد در برابر استراتژی ──")
    print(f"  {'نماد':<14}{'دوره':>5}{'هولد':>10}{'استراتژی':>11}"
          f"{'اختلاف':>10}{'در بازار':>10}")
    rowsout, wins = [], 0
    for sym, seq in sorted(per_sym.items()):
        h, st = hold(seq), compound(seq, a.cost)
        inn = sum(1 for _k, _r, i in seq if i) / len(seq) * 100
        rowsout.append((sym, len(seq), h, st, st - h, inn))
        wins += st > h
    WATCH = ["عیار", "کهربا", "نهال", "نقران", "سینرژی", "اهرم",
             "موج", "دوایکس", "بیدار", "توان"]
    for sym, n, h, st, d, inn in rowsout:
        if sym in WATCH:
            mk = "▲" if d > 0 else "▼"
            print(f"  {sym:<14}{n:>5}{h * 100:>9.1f}٪{st * 100:>10.1f}٪"
                  f"{d * 100:>9.1f}٪{mk}{inn:>8.0f}٪")
    med_h = statistics.median(r[2] for r in rowsout)
    med_s = statistics.median(r[3] for r in rowsout)
    print(f"\n  میانهٔ همهٔ {len(rowsout)} نماد: هولد {med_h * 100:+.1f}٪ · "
          f"استراتژی {med_s * 100:+.1f}٪ · "
          f"اختلاف {(med_s - med_h) * 100:+.1f} واحد")
    print(f"  استراتژی در {wins} از {len(rowsout)} نماد از هولد جلو زد "
          f"({wins / len(rowsout) * 100:.0f}٪)")

    # ── قاعدهٔ ۵۹ · دو سناریو ─────────────────────────────────────
    g = sleeve_series(per_sym, GOLD)
    e = sleeve_series(per_sym, EQ)
    ks = sorted(set(k for k, _, _ in g) & set(k for k, _, _ in e))
    gm = {k: (r, i) for k, r, i in g}
    em = {k: (r, i) for k, r, i in e}
    print("\n  ── قاعدهٔ ۵۹ · دو سناریو ──")

    def scen_a(w):
        """الف: نسبتِ ثابت w طلا، داخلِ هر سبد نوسان."""
        v, pg, pe = 1.0, False, False
        for k in ks:
            rg, ig = gm[k]
            re_, ie = em[k]
            if ig != pg:
                v *= (1 - a.cost / 100 * w)
            if ie != pe:
                v *= (1 - a.cost / 100 * (1 - w))
            v *= (1 + w * (rg if ig else 0) + (1 - w) * (re_ if ie else 0))
            pg, pe = ig, ie
        return v - 1

    def scen_b():
        """ب: چرخشِ کامل — هر دوره سبدی که بازدهش بیشتر بوده."""
        v, prev = 1.0, None
        for k in ks:
            rg, ig = gm[k]
            re_, ie = em[k]
            pick = ("g" if ig and (not ie or rg >= re_)
                    else "e" if ie else None)
            if pick != prev:
                v *= (1 - a.cost / 100)
            v *= (1 + (rg if pick == "g" else re_ if pick == "e" else 0))
            prev = pick
        return v - 1

    def hold_mix(w):
        v = 1.0
        for k in ks:
            v *= (1 + w * gm[k][0] + (1 - w) * em[k][0])
        return v - 1

    print(f"  {len(ks)} دورهٔ مشترک\n")
    print(f"  {'':<28}{'بازده':>10}")
    print(f"  {'الف · ۵۰/۵۰ با نوسانِ داخلی':<28}"
          f"{scen_a(0.5) * 100:>9.1f}٪")
    print(f"  {'ب · چرخشِ کامل بین بازارها':<28}{scen_b() * 100:>9.1f}٪")
    print(f"  {'کنترل · هولدِ ۵۰/۵۰':<28}{hold_mix(0.5) * 100:>9.1f}٪")
    print(f"  {'کنترل · هولدِ فقط طلا':<28}{hold_mix(1.0) * 100:>9.1f}٪")
    print(f"  {'کنترل · هولدِ فقط سهام':<28}{hold_mix(0.0) * 100:>9.1f}٪")

    # ── قاعدهٔ ۵۸ و ۹۲ · نسبتِ بهینه ──────────────────────────────
    print("\n  ── قاعدهٔ ۵۸ و ۹۲ · نسبتِ بهینه ──")
    print(f"  {'طلا٪':>6}{'سهام٪':>7}{'سناریو الف':>13}{'هولد':>11}")
    best = None
    for pct in range(0, 101, 10):
        w = pct / 100
        sa, hm = scen_a(w), hold_mix(w)
        print(f"  {pct:>6}{100 - pct:>7}{sa * 100:>12.1f}٪"
              f"{hm * 100:>10.1f}٪")
        if best is None or sa > best[1]:
            best = (pct, sa)
    print(f"\n  بهترین نسبت در این پنجره: **{best[0]}٪ طلا / "
          f"{100 - best[0]}٪ سهام** → {best[1] * 100:+.1f}٪")
    print("\n  ⚠️ یک پنجرهٔ بازار است، نه قاعدهٔ ابدی. نسبتِ بهینهٔ")
    print("     گذشته‌نگر همیشه بازدهِ بالاتر را نشان می‌دهد چون روی")
    print("     همان داده انتخاب شده. عددِ قابلِ اتکا «الف در برابرِ")
    print("     هولد» است، نه خودِ نسبت.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
