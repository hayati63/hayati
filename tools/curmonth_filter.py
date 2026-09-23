# -*- coding: utf-8 -*-
"""شرطِ سوم: باکسِ ماهِ **جاری** هم باید مثبت باشد؟

مصطفی روی نقران گرفت: «از ابتدای ماه فعلی تا الان یک مقاومت ایجاد کرده
بالای عدد، ولی هفته‌اش مثبت است. ما گفتیم نمادهایی را پیدا می‌کنیم که
هم هفته و هم ماهشان مثبت باشد — ماه فعلی هم یک بازهٔ حمایتی و مقاومتی
ساخته، پس باید جفتش مثبت باشد.»

و خودش قید را هم گفت: «صد در صد نیست تا وقتی ماه بسته بشه.»

⚠️ این با یافتهٔ قبلی در تضاد به نظر می‌رسد: باکسِ ماهِ جاری به‌تنهایی
با کنترلِ ماه × روزِ ماه مزیتش +۰٫۰۱ واحد با t=+۰٫۰۶ درآمد، یعنی از
تصادف جدا نشد. ولی آن آزمون آن را **جایگزین** می‌سنجید؛ این یکی آن را
**شرطِ سوم روی دو شرطِ موجود** می‌سنجد. دو سؤال متفاوت‌اند.

بدون لوک‌اهد: باکسِ ماهِ جاری فقط از کندل‌های **تا همان روزِ تصمیم**
ساخته می‌شود، نه کلِ ماه.

    python3 tools/curmonth_filter.py
"""
import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

from monthly_backtest import load_daily, is_fixed_income, norm
from vp_box import make_box, state
from weekly_backtest import week_key


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_auto")
    ap.add_argument("--kind", default="valley_first")
    ap.add_argument("--min-cur", type=int, default=3,
                    help="کمینه کندلِ ماهِ جاری تا روزِ تصمیم")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args()

    rows_out = []
    seen, fps = set(), {}
    for p in sorted(Path(args.data).glob("*.csv")):
        sym = p.stem.replace("_daily", "").replace("_", " ")
        rows = load_daily(p)
        if len(rows) < 40 or is_fixed_income(sym):
            continue
        fp = tuple((d.isoformat(), round(b.c, 6)) for d, b in rows)
        if fp in fps or norm(sym) in seen:
            continue
        fps[fp] = 1
        seen.add(norm(sym))

        by_m, by_w = defaultdict(list), defaultdict(list)
        for d, b in rows:
            by_m[(d.year, d.month)].append((d, b))
            by_w[week_key(d)].append((d, b))
        ws = sorted(by_w)
        for i in range(len(ws) - 1):
            wa, wb = ws[i], ws[i + 1]
            if (wb - wa).days != 7:
                continue
            prev_w, fwd = by_w[wa], by_w[wb]
            if len(prev_w) < 3 or len(fwd) < 2:
                continue
            dd, bar = fwd[0]                     # روزِ تصمیم
            px = bar.c
            ret = (fwd[-1][1].c - px) / px * 100

            wbox = make_box(args.kind, [x for _, x in prev_w], prev_w[-1][1].c)
            if wbox is None:
                continue
            pm = ((dd.year - 1, 12) if dd.month == 1
                  else (dd.year, dd.month - 1))
            if pm not in by_m or len(by_m[pm]) < 5:
                continue
            mbox = make_box(args.kind, [x for _, x in by_m[pm]],
                            by_m[pm][-1][1].c)
            if mbox is None:
                continue

            # ماهِ جاری، **فقط تا روزِ تصمیم** — بدون لوک‌اهد
            cur_bars = [b for d2, b in by_m.get((dd.year, dd.month), [])
                        if d2 <= dd]
            cbox = (make_box(args.kind, cur_bars, cur_bars[-1].c)
                    if len(cur_bars) >= args.min_cur else None)

            rows_out.append({
                "w": wb, "sym": sym, "ret": ret,
                "m": state(px, mbox), "wk": state(px, wbox),
                "c": state(px, cbox) if cbox else "—"})

    if not rows_out:
        print("مشاهده‌ای ساخته نشد.")
        return 1

    by_w = defaultdict(list)
    for o in rows_out:
        by_w[o["w"]].append(o)

    def edge(pick):
        """مزیتِ درون‌هفته‌ای بر همهٔ نمادهای همان هفته."""
        ds = []
        for xs in by_w.values():
            sel = [o["ret"] for o in xs if pick(o)]
            if len(sel) < 3 or len(xs) < 5:
                continue
            ds.append(statistics.mean(sel)
                      - statistics.mean([o["ret"] for o in xs]))
        if len(ds) < 3:
            return None
        m = statistics.mean(ds)
        sd = statistics.stdev(ds) if len(ds) > 1 else 0
        return {"weeks": len(ds), "edge": m,
                "t": (m / (sd / len(ds) ** 0.5)) if sd else 0.0}

    base = statistics.mean([o["ret"] for o in rows_out])
    print("=" * 78)
    print(f"شرطِ سوم — باکسِ ماهِ جاری  ·  {len(rows_out):,} مشاهده"
          f"  ·  {len(by_w)} هفته  ·  {len(seen)} نماد")
    print(f"نرخ پایه: {base:+.2f}٪ بازده هفتگی")
    print("=" * 78)

    both = lambda o: o["m"] == "بالا" and o["wk"] == "بالا"    # noqa: E731
    cands = [
        ("ماه قبل + هفتگی (فعلی)", both),
        ("  + ماه جاری بالا", lambda o: both(o) and o["c"] == "بالا"),
        ("  + ماه جاری داخل", lambda o: both(o) and o["c"] == "داخل"),
        ("  + ماه جاری زیر", lambda o: both(o) and o["c"] == "زیر"),
    ]
    print(f"\n{'گروه':<26}{'n':>7}{'مثبت':>8}{'میانگین':>10}"
          f"{'مزیت':>9}{'t':>7}{'هفته':>7}")
    print("─" * 78)
    out = {}
    for label, pick in cands:
        sel = [o["ret"] for o in rows_out if pick(o)]
        if len(sel) < 20:
            print(f"{label:<26}{len(sel):>7}   — کم")
            continue
        e = edge(pick)
        win = sum(1 for r in sel if r > 0) / len(sel) * 100
        print(f"{label:<26}{len(sel):>7,}{win:>7.1f}٪"
              f"{statistics.mean(sel):>+9.2f}٪"
              f"{(e['edge'] if e else float('nan')):>+9.3f}"
              f"{(e['t'] if e else float('nan')):>7.2f}"
              f"{(e['weeks'] if e else 0):>7}")
        out[label.strip()] = {"n": len(sel), "win": win,
                              "avg": statistics.mean(sel), **(e or {})}

    a = out.get("ماه قبل + هفتگی (فعلی)")
    b = out.get("+ ماه جاری بالا")
    c = out.get("+ ماه جاری زیر")
    if a and b:
        print("\n" + "─" * 78)
        print("حکم")
        print("─" * 78)
        d = b["edge"] - a["edge"]
        print(f"  افزودنِ «ماه جاری بالا»: {d:+.3f} واحد درصد")
        print(f"  و {a['n'] - b['n']:,} مشاهده از {a['n']:,} حذف می‌شود "
              f"({(a['n']-b['n'])/a['n']*100:.0f}٪ کمتر سیگنال)")
        if c:
            print(f"\n  گروهی که ماه جاری‌شان **زیر** است: n={c['n']}، "
                  f"میانگین {c['avg']:+.2f}٪")
            if "edge" in c:
                print(f"  مزیت {c['edge']:+.3f} در برابر «بالا» "
                      f"{b['edge']:+.3f} — اختلاف {b['edge']-c['edge']:+.3f}")
            else:
                print("  ⚠️ مزیتش **محاسبه‌شدنی نیست**: هیچ هفته‌ای دستِ‌کم")
                print("  ۳ عضو در این گروه ندارد. یعنی دربارهٔ همین حالتی که")
                print("  نقران در آن است، داده‌ای برای حکم دادن نداریم.")
        if abs(d) < 0.05:
            print("\n  → شرطِ سوم عملاً چیزی اضافه نمی‌کند.")
        elif d > 0:
            print("\n  → شرطِ سوم مزیت را بالا می‌برد.")
        else:
            print("\n  → شرطِ سوم مزیت را **پایین** می‌آورد.")

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nJSON: {Path(args.json_out).resolve()}")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
