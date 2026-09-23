# -*- coding: utf-8 -*-
"""ساخت چهار آرایهٔ داشبورد مستقیماً از `data_auto`.

چرا این لازم شد: `portfolio_dashboard.py` ورودی‌اش `dashboard_monthly.html`
بود، که از اسکریپت خودِ مصطفی می‌آید. اگر آن فایل کنار `refresh.bat` نباشد،
مرحلهٔ داشبورد بی‌صدا رد می‌شود و **هیچ `portfolio.html` ساخته نمی‌شود**.

این فایل همان چهار آرایه را از دادهٔ روزانه می‌سازد، پس زنجیرهٔ روزانه به
هیچ اسکریپت بیرونی وابسته نیست.

    python3 tools/build_from_data.py --data data_auto --out bridge.html
    python3 tools/portfolio_dashboard.py --in bridge.html --out portfolio.html
"""
import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

from monthly_backtest import load_daily, is_fixed_income, norm
from vp_box import make_box, state

OPEN_MONTH = "تا امروز"
ST = {"بالا": "سبز", "داخل": "داخل", "زیر": "قرمز"}


def categories(root):
    """دستهٔ هر نماد از خروجیِ قبلی، اگر باشد."""
    cat = {}
    p = root / "data/extracted/TODAY.json"
    if p.exists():
        for r in json.loads(p.read_text(encoding="utf-8")):
            cat[norm(r["نماد"])] = r["دسته"]
    return cat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_auto")
    ap.add_argument("--glob", default="*.csv")
    ap.add_argument("--kind", default="valley_first")
    ap.add_argument("--out", default="bridge.html")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    cat = categories(root)

    series, fps, norms = {}, {}, {}
    for p in sorted(Path(args.data).glob(args.glob)):
        name = p.stem.replace("_daily", "").replace("_", " ")
        rows = load_daily(p)
        if len(rows) < 20:
            continue
        fp = tuple((d.isoformat(), round(b.c, 6)) for d, b in rows)
        if fp in fps or norm(name) in norms:
            continue
        fps[fp] = norms[norm(name)] = name
        series[name] = rows

    today, trades = [], []
    per_sym = defaultdict(list)

    for name, rows in series.items():
        c = cat.get(norm(name), "سهامی")
        by_m = defaultdict(list)
        for d, b in rows:
            by_m[(d.year, d.month)].append((d, b))
        ms = sorted(by_m)
        if len(ms) < 3:
            continue

        # ── معاملات: باکس ماه قبل، بازده ماه بعد ──
        for i in range(len(ms) - 1):
            a, b = ms[i], ms[i + 1]
            nxt = (a[0] + 1, 1) if a[1] == 12 else (a[0], a[1] + 1)
            if b != nxt or len(by_m[a]) < 5 or len(by_m[b]) < 2:
                continue
            box = make_box(args.kind, [x for _, x in by_m[a]],
                           by_m[a][-1][1].c)
            if not box:
                continue
            fwd = by_m[b]
            entry, exit_ = fwd[0][1].c, fwd[-1][1].c
            if state(entry, box) != "بالا":
                continue
            is_last = (b == ms[-1])
            ret = (exit_ - entry) / entry * 100
            trades.append({
                "نماد": name, "دسته": c,
                "ماه_خروج": OPEN_MONTH if is_last else f"{b[0]}-{b[1]:02d}",
                "بازده٪": round(ret, 2),
                "ریسک_ورود٪": round((entry - box[0]) / entry * 100, 2),
            })
            per_sym[name].append(ret)

        # ── وضعیت امروز ──
        cur, prev = by_m[ms[-1]], by_m[ms[-2]]
        if len(prev) < 5 or not cur:
            continue
        close = cur[-1][1].c
        pbox = make_box(args.kind, [x for _, x in prev], prev[-1][1].c)
        cbox = (make_box(args.kind, [x for _, x in cur], close)
                if len(cur) >= 3 else None)
        if not pbox:
            continue
        row = {
            "نماد": name, "دسته": c,
            "تاریخ": f"{cur[-1][0]:%Y-%m-%d}", "کلوز": close,
            "لو_قبل": round(pbox[0], 2), "های_قبل": round(pbox[1], 2),
            "ریسک_قبل": round((close - pbox[0]) / close * 100, 2),
            "وضعیت_قبل": ST.get(state(close, pbox), "داخل"),
        }
        if cbox:
            row.update({
                "لو_جاری": round(cbox[0], 2), "های_جاری": round(cbox[1], 2),
                "ریسک_جاری": round((close - cbox[0]) / close * 100, 2)
                if close > cbox[1] else (
                    round((close - cbox[0]) / close * 100, 2)
                    if close < cbox[0] else 0.0),
                "وضعیت_جاری": ST.get(state(close, cbox), "داخل"),
            })
        else:
            row.update({"لو_جاری": row["لو_قبل"], "های_جاری": row["های_قبل"],
                        "ریسک_جاری": 0.0, "وضعیت_جاری": "داخل"})
        today.append(row)

    # نام فیلدها باید دقیقاً همانی باشد که analyse() می‌خواند:
    # «تعداد» و «موفقیت٪»، نه «تعداد_معامله» و «نرخ_برد٪».
    summary = [{"نماد": s, "دسته": cat.get(norm(s), "سهامی"),
                "تعداد": len(v),
                "میانگین_بازده٪": round(statistics.mean(v), 2),
                "موفقیت٪": round(sum(1 for x in v if x > 0) / len(v) * 100, 1)}
               for s, v in per_sym.items() if v]

    today.sort(key=lambda r: r["نماد"])
    summary.sort(key=lambda r: r["نماد"])

    html = ("<!doctype html><meta charset=utf-8>\n<script>\n"
            f"const TODAY = {json.dumps(today, ensure_ascii=False)};\n"
            f"const TRADES = {json.dumps(trades, ensure_ascii=False)};\n"
            f"const SUMMARY = {json.dumps(summary, ensure_ascii=False)};\n"
            "const SIGNALS = [];\n</script>\n")
    Path(args.out).write_text(html, encoding="utf-8")

    closed = [t for t in trades if t["ماه_خروج"] != OPEN_MONTH]
    print(f"نماد {len(today)} · معامله {len(trades)} "
          f"(بسته {len(closed)}، باز {len(trades)-len(closed)})")
    if today:
        print(f"تاریخ داده: {max(r['تاریخ'] for r in today)}")
    print(f"نوشته شد: {Path(args.out).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
