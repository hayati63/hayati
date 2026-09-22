# -*- coding: utf-8 -*-
"""کلوزِ کدام روز تصمیم می‌گیرد — روز اولِ هفته، یا روز دوم؟

سؤال مصطفی: «صندوق‌های بورسی شنبه بسته می‌شود، ناحیه مشخص می‌شود، و
کلوزِ روزِ بعد — کلوزِ یکشنبه — جهتِ بازار تا هفتهٔ آینده را مشخص می‌کند.
اگر این مبنای ساخت این استراتژی بوده درسته، اگر غیر اینه اشتباه.»

سیستم فعلاً روی **روز اول** تصمیم می‌گیرد (شنبه). او می‌گوید **روز دوم**
(یکشنبه). این یک اختلافِ یک‌روزه است و اندازه‌گیری‌شدنی.

آزمون: باکس از هفتهٔ کامل‌شدهٔ قبل. وضعیت (بالا/داخل/زیر) روی کلوزِ روز
k ارزیابی می‌شود، و بازده از همان کلوز تا پایان هفته سنجیده می‌شود.
k=۱ یعنی شنبه، k=۲ یکشنبه، k=۳ دوشنبه.

هر k افقِ کوتاه‌تری دارد، پس بازدهِ خام قابلِ مقایسه نیست. معیار
**مزیت درون‌هفته‌ای** است: بازدهِ گروهِ «بالا» منهای بازدهِ همهٔ نمادهای
همان هفته در همان افق. آن قابلِ مقایسه است.

    python3 tools/decision_day.py --anchor sat
    python3 tools/decision_day.py --anchor mon --data data/drivers_daily
"""
import argparse
import json
import random
import statistics
from collections import defaultdict
from pathlib import Path

from monthly_backtest import load_daily, is_fixed_income, norm
from vp_box import make_box, state
from calendar_wk import week_key_for

ANCHOR = {"sat": 5, "mon": 0}


def build(data_dir, glob, kind, anchor, max_k):
    """obs[k] = [(هفته، نماد، وضعیت، بازده تا پایان هفته), ...]"""
    obs = {k: [] for k in range(1, max_k + 1)}
    wk = week_key_for(anchor)
    seen, fps = set(), {}
    for p in sorted(Path(data_dir).glob(glob)):
        sym = p.stem.replace("_daily", "").replace("_", " ")
        rows = load_daily(p)
        if len(rows) < 40 or is_fixed_income(sym):
            continue
        fp = tuple((d.isoformat(), round(b.c, 6)) for d, b in rows)
        if fp in fps or norm(sym) in seen:
            continue
        fps[fp] = 1
        seen.add(norm(sym))

        by = defaultdict(list)
        for d, b in rows:
            by[wk(d)].append((d, b))
        ks = sorted(by)
        for i in range(len(ks) - 1):
            wa, wb = ks[i], ks[i + 1]
            if (wb - wa).days != 7:
                continue
            prev, fwd = by[wa], by[wb]
            if len(prev) < 3:
                continue
            box = make_box(kind, [x for _, x in prev], prev[-1][1].c)
            if box is None:
                continue
            last = fwd[-1][1].c
            for k in range(1, max_k + 1):
                if len(fwd) < k + 1:      # باید بعد از روز k دستِ‌کم
                    continue              # یک روز باقی بماند
                px = fwd[k - 1][1].c
                if px <= 0:
                    continue
                obs[k].append((wb, sym, state(px, box), (last - px) / px * 100))
    return obs


def edge(rows, iters, seed=7):
    """مزیتِ درون‌هفته‌ایِ گروه «بالا»، با آزمون جایگشت."""
    by_w = defaultdict(list)
    for w, _, st, r in rows:
        by_w[w].append((st, r))
    diffs, usable = [], []
    for w, xs in by_w.items():
        sel = [r for st, r in xs if st == "بالا"]
        allr = [r for _, r in xs]
        if len(sel) < 3 or len(allr) < 5:
            continue
        diffs.append(statistics.mean(sel) - statistics.mean(allr))
        usable.append((len(sel), allr))
    if len(diffs) < 3:
        return None
    m = statistics.mean(diffs)
    rng = random.Random(seed)
    hits = sum(
        1 for _ in range(iters)
        if statistics.mean(
            [statistics.mean(rng.sample(a, n)) - statistics.mean(a)
             for n, a in usable]) >= m)
    sel = [r for _, _, st, r in rows if st == "بالا"]
    allr = [r for *_, r in rows]
    sd = statistics.stdev(diffs) if len(diffs) > 1 else 0
    return {"weeks": len(diffs), "edge": m, "p": (hits + 1) / (iters + 1),
            "t": (m / (sd / len(diffs) ** 0.5)) if sd else 0.0,
            "n": len(sel), "avg": statistics.mean(sel),
            "base": statistics.mean(allr),
            "win": sum(1 for r in sel if r > 0) / len(sel) * 100,
            "base_win": sum(1 for r in allr if r > 0) / len(allr) * 100}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_auto")
    ap.add_argument("--glob", default="*.csv")
    ap.add_argument("--kind", default="valley_first")
    ap.add_argument("--anchor", choices=("sat", "mon"), default="sat")
    ap.add_argument("--max-k", type=int, default=4)
    ap.add_argument("--iters", type=int, default=20000)
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args()

    obs = build(args.data, args.glob, args.kind, ANCHOR[args.anchor],
                args.max_k)
    DAY = (["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه",
            "شنبه", "یکشنبه"])
    a = ANCHOR[args.anchor]

    print("=" * 76)
    print(f"روزِ تصمیم — لنگرِ هفته: {DAY[a]}  ·  تعریف: {args.kind}")
    print("=" * 76)
    print(f"\n{'روز':<16}{'مشاهده':>9}{'هفته':>7}{'نرخ پایه':>10}"
          f"{'نرخ برد':>10}{'مزیت':>9}{'t':>7}{'p':>9}")
    print("─" * 76)
    out = {}
    for k in range(1, args.max_k + 1):
        if not obs[k]:
            continue
        e = edge(obs[k], args.iters)
        if e is None:
            print(f"  روز {k}: هفتهٔ کافی نبود")
            continue
        nm = f"روز {k} ({DAY[(a + k - 1) % 7]})"
        star = " ★" if e["p"] < 0.05 else ""
        print(f"{nm:<16}{e['n']:>9,}{e['weeks']:>7}{e['base_win']:>9.1f}٪"
              f"{e['win']:>9.1f}٪{e['edge']:>+9.3f}{e['t']:>7.2f}"
              f"{e['p']:>9.4f}{star}")
        out[k] = e

    if len(out) >= 2:
        best = max(out, key=lambda k: out[k]["edge"])
        print("\n" + "─" * 76)
        print(f"  بیشترین مزیت: **روز {best} ({DAY[(a + best - 1) % 7]})**"
              f"  {out[best]['edge']:+.3f} واحد · p={out[best]['p']:.4f}")
        if 1 in out and 2 in out:
            d = out[2]["edge"] - out[1]["edge"]
            print(f"\n  روز ۲ منهای روز ۱: {d:+.3f} واحد درصد")
            if abs(d) < 0.05:
                print("  → عملاً یکی‌اند. انتخابِ روز فرقی نمی‌کند.")
            elif d > 0:
                print("  → روز ۲ بهتر است. حرفِ مصطفی درست.")
            else:
                print("  → روز ۱ بهتر است. سیستم همان‌طور که هست درست.")
        print("\n  یادآوری: افقِ روزهای بعدی کوتاه‌تر است، پس بازدهِ خام")
        print("  قابل مقایسه نیست — «مزیت» است که مقایسه‌شدنی است، چون")
        print("  در همان افق با همهٔ نمادهای همان هفته سنجیده می‌شود.")

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps({"anchor": args.anchor, "days": out},
                       ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nJSON: {Path(args.json_out).resolve()}")
    print("=" * 76)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
