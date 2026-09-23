# -*- coding: utf-8 -*-
"""آیا «زیر باکسِ ماهِ جاری» بقیهٔ همان ماه را پیش‌بینی می‌کند؟

این سؤال با بک‌تست ماهانه یکی **نیست**. آنجا باکس از ماه قبل ساخته می‌شود و
بازده کل ماه بعد اندازه گرفته می‌شود. اینجا باکس از کندل‌های **همین ماه تا
امروز** ساخته می‌شود و بازده از امروز تا کلوز همین ماه اندازه گرفته می‌شود —
یعنی دقیقاً همان چراغی که داشبورد در طول ماه نشان می‌دهد.

بدون لوک‌اهد: باکس روز d فقط کندل‌های ≤ d را می‌بیند.
"""
import argparse
import json
import statistics
import random
from collections import defaultdict
from pathlib import Path

from monthly_backtest import load_daily, is_fixed_income, norm
from vp_box import make_box, state, BOX_KINDS


def collect(data_dir, glob, kind, min_bars, include_fixed):
    """مشاهدات (ماه، نماد، روز، حالت، بازده تا پایان ماه)."""
    obs = []
    seen = {}
    for p in sorted(Path(data_dir).glob(glob)):
        name = p.name
        for suf in ("_daily.csv", ".csv"):
            if name.endswith(suf):
                name = name[: -len(suf)]
                break
        rows = load_daily(p)
        if len(rows) < 20:
            continue
        fp = tuple((d.isoformat(), round(b.c, 6)) for d, b in rows)
        if fp in seen or norm(name) in {norm(s) for s in seen.values()}:
            continue
        seen[fp] = name
        if is_fixed_income(name) and not include_fixed:
            continue

        by_month = defaultdict(list)
        for d, b in rows:
            by_month[(d.year, d.month)].append((d, b))

        for m, days in sorted(by_month.items()):
            if len(days) < min_bars + 2:
                continue
            eom = days[-1][1].c
            for i in range(min_bars - 1, len(days) - 1):
                bars = [b for _, b in days[: i + 1]]
                c = bars[-1].c
                box = make_box(kind, bars, c)
                if box is None:
                    continue
                st = state(c, box)
                obs.append({"month": m, "sym": name, "day": i + 1,
                            "st": st, "ret": (eom - c) / c * 100.0})
    return obs


def month_edge(by_month, target):
    out = []
    for rows in by_month.values():
        sel = [r["ret"] for r in rows if r["st"] == target]
        if len(sel) < 3 or len(rows) < 5:
            continue
        out.append(statistics.mean(sel) - statistics.mean([r["ret"] for r in rows]))
    return out


def permutation_p(by_month, target, n_iter, seed=42):
    obs = month_edge(by_month, target)
    if len(obs) < 2:
        return None, None
    obs_mean = statistics.mean(obs)
    rng = random.Random(seed)
    usable = [(len([r for r in rows if r["st"] == target]),
               [r["ret"] for r in rows])
              for rows in by_month.values()
              if len(rows) >= 5 and len([r for r in rows if r["st"] == target]) >= 3]
    if len(usable) < 2:
        return obs_mean, None
    hits = 0
    for _ in range(n_iter):
        diffs = [statistics.mean(rng.sample(rets, k)) - statistics.mean(rets)
                 for k, rets in usable]
        if statistics.mean(diffs) >= obs_mean:
            hits += 1
    return obs_mean, (hits + 1) / (n_iter + 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_auto")
    ap.add_argument("--glob", default="*.csv")
    ap.add_argument("--kind", default="valley_first", choices=list(BOX_KINDS))
    ap.add_argument("--min-bars", type=int, default=6,
                    help="کمینه کندل لازم در ماه قبل از اینکه باکس معنی بدهد")
    ap.add_argument("--iters", type=int, default=20000)
    ap.add_argument("--include-fixed", action="store_true")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args()

    obs = collect(args.data, args.glob, args.kind, args.min_bars,
                  args.include_fixed)
    if not obs:
        print("مشاهده‌ای ساخته نشد.")
        return 1

    by_month = defaultdict(list)
    for o in obs:
        by_month[o["month"]].append(o)

    print("=" * 72)
    print(f"تعریف باکس: {args.kind}   کمینه کندل: {args.min_bars}")
    n_sym = len({o["sym"] for o in obs})
    print(f"مشاهده: {len(obs):,}  |  نماد: {n_sym}  |  ماه: {len(by_month)}")
    print("هر مشاهده = یک نماد در یک روز. بازده = از کلوز آن روز تا کلوز پایان ماه.")
    print("=" * 72)

    allr = [o["ret"] for o in obs]
    base = statistics.mean(allr)
    base_win = sum(1 for r in allr if r > 0) / len(allr) * 100
    print(f"\nنرخ پایه — همهٔ مشاهده‌ها: میانگین {base:+.2f}٪ · "
          f"مثبت {base_win:.1f}٪  (n={len(allr):,})")

    print(f"\n{'حالت':<8}{'n':>8}{'مثبت٪':>9}{'میانگین٪':>11}"
          f"{'مزیت':>9}{'میانه٪':>9}")
    for st in ("بالا", "داخل", "زیر"):
        sel = [o["ret"] for o in obs if o["st"] == st]
        if not sel:
            continue
        w = sum(1 for r in sel if r > 0) / len(sel) * 100
        print(f"{st:<8}{len(sel):>8,}{w:>9.1f}{statistics.mean(sel):>11.2f}"
              f"{statistics.mean(sel) - base:>+9.2f}{statistics.median(sel):>9.2f}")

    # ── کنترل افق: همان مقایسه، داخل هر سلولِ (ماه × روزِ ماه) ──
    # هرچه دیرتر در ماه، افق تا کلوز کوتاه‌تر است. اگر یک حالت سیستماتیک
    # دیرتر بیفتد، عدد خام را همان افق می‌سازد نه سیگنال. اینجا ماه و روز
    # هر دو ثابت می‌مانند و تنها متغیر، حالت باکس است.
    print("\n" + "─" * 72)
    print("کنترل افق — مقایسه فقط داخل هر (ماه × روزِ ماه)")
    print("  یعنی فقط نمادهایی که در یک روزِ یکسان از یک ماهِ یکسان‌اند.\n")
    print(f"  {'حالت':<8}{'میانگین روزِ ماه':>18}{'سلول':>7}{'n':>8}"
          f"{'مزیت واحد٪':>13}{'خطای معیار':>12}{'t':>8}")
    cells = defaultdict(list)
    for o in obs:
        cells[(o["month"], o["day"])].append(o)
    cellout = {}
    for st in ("بالا", "داخل", "زیر"):
        sel_all = [o for o in obs if o["st"] == st]
        if not sel_all:
            continue
        diffs, n_c, n_o = [], 0, 0
        for rows in cells.values():
            sel = [r["ret"] for r in rows if r["st"] == st]
            if len(sel) < 3 or len(rows) < 8:
                continue
            diffs.append(statistics.mean(sel)
                         - statistics.mean([r["ret"] for r in rows]))
            n_c += 1
            n_o += len(sel)
        if not diffs:
            continue
        m = statistics.mean(diffs)
        se = (statistics.stdev(diffs) / len(diffs) ** 0.5
              if len(diffs) > 1 else None)
        t = m / se if se else None
        cellout[st] = {"cells": n_c, "n": n_o, "edge": m, "se": se, "t": t,
                       "mean_day": statistics.mean([o["day"] for o in sel_all])}
        print(f"  {st:<8}{cellout[st]['mean_day']:>18.1f}{n_c:>7}{n_o:>8,}"
              f"{m:>+13.2f}{(se if se else float('nan')):>12.2f}"
              f"{(t if t else float('nan')):>+8.2f}")
    print("\n  اگر «میانگین روزِ ماه» بین حالت‌ها نزدیک باشد، افق مقصر نیست.")
    print("  این جدول ماه و افق هر دو را کنترل می‌کند، جدول خام هیچ‌کدام را، و")
    print("  جایگشتِ زیر فقط ماه را. اگر علامتِ یک حالت بین این سه عوض شد، آن")
    print("  برآورد ناپایدار است — عددش را نباید خواند.")

    print("\n" + "─" * 72)
    print(f"تست جایگشت — برچسب داخل هر ماه به‌هم ریخته ({args.iters:,} بار)")
    print("  پوچ: حالت باکسِ جاری نماد بهتری از تصادف انتخاب نمی‌کند.\n")
    print(f"  {'حالت':<8}{'ماه':>5}{'مزیت واحد٪':>13}{'p':>9}")
    out = {}
    for st in ("بالا", "داخل", "زیر"):
        edge, p = permutation_p(by_month, st, args.iters)
        if edge is None:
            continue
        n_m = len(month_edge(by_month, st))
        sel = [o["ret"] for o in obs if o["st"] == st]
        out[st] = {"months": n_m, "edge": edge, "p": p, "n": len(sel),
                   "avg": statistics.mean(sel) if sel else None,
                   "win": (sum(1 for r in sel if r > 0) / len(sel) * 100)
                   if sel else None}
        ps = "—" if p is None else f"{p:.4f}"
        star = " ★" if (p is not None and p < 0.05) else ""
        print(f"  {st:<8}{n_m:>5}{edge:>+13.2f}{ps:>9}{star}")
    print("\n  p برای «زیر» یک‌طرفه و رو به **بالا** است: اگر «زیر» واقعاً بد")
    print("  باشد p بزرگ درمی‌آید، نه کوچک. برای دیدن «زیرِ بد» به ستون مزیت")
    print("  نگاه کنید که باید منفی باشد.")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps({
            "window": "باکس از کندل‌های همین ماه تا امروز، بازده تا پایان همین ماه",
            "kind": "intramonth", "box": args.kind,
            "min_bars": args.min_bars, "iters": args.iters,
            "p_floor": 1 / (args.iters + 1),
            "n_obs": len(obs), "symbols": n_sym, "months": len(by_month),
            "base_avg": base, "base_win": base_win,
            "states": out, "cells": cellout,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nJSON: {Path(args.json_out).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
