#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تتر و دلار: کلوزِ روزِ ناحیه یا کلوزِ روزِ بعد؟ — قاعده‌های ۸۹ و ۹۰.

> «حالا من یک روز بعد از ناحیه که تشکیل میشه رو دارم ملاک قرار میدم…
> من میگم نه، **کلوزِ روزِ بعدش مهمه برای ما، نه اون روز.** حالا این
> رو میخوام بری تو بک‌تست برای من بگیری ببینی کدوم.» — پیام ۸۸
> «میخوام ببینم که اولویت رو تتر قرار بدیم یا دلار.» — پیام ۸۸

هفتهٔ محرک‌ها **دوشنبه** می‌بندد (پیام ۵۲ و ۸۱)، پس لنگرِ هفته سه‌شنبه
است. باکس از هفتهٔ کامل‌شدهٔ قبل. دو حکم:

    الف = کلوزِ **خودِ روزی** که ناحیه بسته شد   (نظرِ من)
    ب  = کلوزِ **روزِ بعد**                       (نظرِ او)

    python tools/drv_decide.py
    python tools/drv_decide.py --syms تتر دلار طلای_۱۸_عیار
"""
from __future__ import annotations
import argparse
import csv
import pathlib
import statistics
import sys
from collections import defaultdict
from datetime import date

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import bourse as B                                    # noqa: E402

DRV_WEEK_ANCHOR = 1          # سه‌شنبه — چون هفته دوشنبه می‌بندد


def wk(d):
    return d.fromordinal(d.toordinal() - (d.weekday() - DRV_WEEK_ANCHOR) % 7)


def load_drv(name):
    f = B.DRV_DIR / f"{name}_daily.csv"
    if not f.exists():
        return []
    out = []
    with f.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                out.append({"d": date.fromisoformat(str(r["date"])[:10]),
                            "h": float(r["high"]), "l": float(r["low"]),
                            "c": float(r["close"]),
                            "v": float(r.get("volume") or 0) or 1.0})
            except (KeyError, TypeError, ValueError):
                continue
    out.sort(key=lambda b: b["d"])
    return out


def stat(x):
    if not x:
        return "n=0", 0.0
    pos = sum(1 for r in x if r > 0) / len(x) * 100
    return (f"n={len(x):>4} · {pos:>5.1f}٪ مثبت · "
            f"{statistics.mean(x) * 100:+6.2f}٪"), pos


def run(name):
    bars = load_drv(name)
    if len(bars) < 60:
        print(f"\n{name}: دادهٔ کافی نیست ({len(bars)} روز)")
        return None
    g = defaultdict(list)
    for r in bars:
        g[wk(r["d"])].append(r)
    ks = sorted(g)
    A, Bb, base = [], [], []
    for i in range(2, len(ks)):
        box = B.make_box(g[ks[i - 1]])
        if box is None:
            continue
        _lo, hi = box
        prev, cur = g[ks[i - 1]], g[ks[i]]
        c0, c1 = prev[-1]["c"], cur[-1]["c"]
        if c0 <= 0:
            continue
        ret = c1 / c0 - 1
        base.append(ret)
        if prev[-1]["c"] > hi:          # الف · کلوزِ روزِ ناحیه
            A.append(ret)
        if cur[0]["c"] > hi:            # ب · کلوزِ روزِ بعد
            Bb.append(ret)
    if not base:
        return None
    bp = sum(1 for r in base if r > 0) / len(base) * 100
    sa, pa = stat(A)
    sb, pb = stat(Bb)
    print(f"\n{'═' * 66}")
    print(f"  {name.replace('_', ' ')} · {len(ks)} هفته · "
          f"نرخِ پایه {bp:.1f}٪ مثبت · "
          f"{statistics.mean(base) * 100:+.2f}٪")
    print("═" * 66)
    print(f"  الف · کلوزِ روزِ ناحیه   {sa}   مزیت {pa - bp:+5.1f} واحد")
    print(f"  ب  · کلوزِ روزِ بعد     {sb}   مزیت {pb - bp:+5.1f} واحد")
    win = "ب · روزِ بعد" if pb - bp > pa - bp else "الف · روزِ ناحیه"
    print(f"  → برنده: **{win}**")
    return {"name": name, "weeks": len(ks), "base": bp,
            "a": pa - bp, "b": pb - bp, "nb": len(Bb)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--syms", nargs="*",
                    default=["تتر", "دلار", "طلای_۱۸_عیار"])
    a = ap.parse_args()
    print("=" * 66)
    print("  حکم روی کلوزِ روزِ ناحیه یا روزِ بعد؟ — قاعدهٔ ۸۹")
    print("  هفتهٔ محرک‌ها دوشنبه می‌بندد، پس لنگر سه‌شنبه است")
    print("=" * 66)
    res = [r for r in (run(s) for s in a.syms) if r]
    if len(res) > 1:
        print(f"\n{'═' * 66}\n  قاعدهٔ ۹۰ · اولویت کدام است؟\n{'═' * 66}")
        print(f"  {'محرک':<16}{'مزیتِ ب':>10}{'n':>7}{'هفته':>8}")
        for r in sorted(res, key=lambda x: -x["b"]):
            print(f"  {r['name'].replace('_', ' '):<16}"
                  f"{r['b']:>9.1f}{r['nb']:>7}{r['weeks']:>8}")
        top = max(res, key=lambda x: x["b"])
        print(f"\n  → اولویت: **{top['name'].replace('_', ' ')}** "
              f"({top['b']:+.1f} واحد روی {top['weeks']} هفته)")
    print("\n  ⚠️ نمونه بزرگ است ولی همه در یک اقتصاد تورمی‌اند: نرخِ")
    print("     پایهٔ ۵۷–۶۰٪ مثبت خودش نشانهٔ روندِ صعودیِ بلندمدتِ")
    print("     ریال است. مزیت نسبت به همان پایه سنجیده شده، نه صفر.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
