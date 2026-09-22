# -*- coding: utf-8 -*-
"""به کدام سطح واکنش نشان داده می‌شود: خودِ ناحیه، یا کندل‌های مرتبط با آن؟

حرف مصطفی: «بازار بعضی مواقع به خود ناحیه نمی‌رسد، به آن کندل‌هایی که به
آن ناحیه مرتبط هستند واکنش نشان می‌دهد در پولبک. یعنی یک ناحیه تشکیل شده،
یک کندلی به آن ناحیه مرتبط بوده و قیمت رفته بالا، و وقتی در پولبک می‌خواهد
واکنش نشان بدهد به آن کندل‌ها اولویت بیشتری می‌دهد تا محدوده.»

این یک فرضیهٔ قابل‌آزمون است و مستقیماً به عددِ «حمایت خالی» وصل است:
۶۲٫۷٪ سیگنال‌های ماهانه اصلاً پولبک نزدند. اگر حق با او باشد، بخشی از آن
۶۲٫۷٪ در واقع پولبک **زده** — فقط نه تا خودِ سقفِ باکس، بلکه تا سطحِ
کندل‌هایی که باکس را ساخته‌اند و کمی بالاترند.

پنج تعریفِ «سطحِ ورود» آزمون می‌شود، همه روی همان سیگنال‌ها:

  box_top      سقف باکس — تعریف فعلی، بند ۱
  touch_low    کمترین LOW در میان کندل‌هایی که باکس را لمس کرده‌اند
  touch_close  کمترین CLOSE همان کندل‌ها
  last_touch   LOW آخرین کندلی که باکس را لمس کرده (نزدیک‌ترین به حال)
  box_top_1p   سقف باکس + ۱٪، به‌عنوان گروه کنترلِ «فقط بالاتر»

`box_top_1p` عمداً هست: اگر هر سطحِ بالاترِ باکس بهتر جواب بدهد، یافته
دربارهٔ «کندل‌های مرتبط» نیست، دربارهٔ «هر سطحی که زودتر لمس می‌شود» است.

    python3 tools/reaction.py --window week
    python3 tools/reaction.py --window month
"""
import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

from monthly_backtest import load_daily, is_fixed_income, norm
from vp_box import make_box, state
from calendar_wk import week_key_for

SAT = week_key_for(5)
LEVELS = ("box_top", "touch_low", "touch_close", "last_touch", "box_top_1p")


def entry_levels(bars, box):
    """پنج سطحِ ورود از روی کندل‌های دورهٔ ساختِ باکس."""
    lo, hi = box
    # کندلی «باکس را لمس کرده» که رنجش با باکس اشتراک دارد
    touch = [b for b in bars if b.l <= hi and b.h >= lo]
    out = {"box_top": hi, "box_top_1p": hi * 1.01}
    if touch:
        out["touch_low"] = min(b.l for b in touch)
        out["touch_close"] = min(b.c for b in touch)
        out["last_touch"] = touch[-1].l
    return out


def trade(fwd, entry, stop, target):
    """۱:۱ روی کندل‌های پیشِ رو. خروجی: 'تارگت'/'استاپ'/'هم‌کندل'/'خالی'."""
    for b in fwd:
        hit_e = b.l <= entry
        if not hit_e:
            continue
        # از همان کندل به بعد
        idx = fwd.index(b)
        for c in fwd[idx:]:
            if c.l <= stop and c.h >= target:
                return "هم‌کندل"
            if c.l <= stop:
                return "استاپ"
            if c.h >= target:
                return "تارگت"
        return "باز"
    return "خالی"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_auto")
    ap.add_argument("--kind", default="valley_first")
    ap.add_argument("--window", choices=("week", "month"), default="week")
    ap.add_argument("--min-days", type=int, default=40)
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args()

    res = {k: defaultdict(int) for k in LEVELS}
    gap = {k: [] for k in LEVELS}       # فاصلهٔ درصدیِ سطح تا کلوزِ ورود
    seen, fps = set(), {}
    nsig = 0

    for p in sorted(Path(args.data).glob("*.csv")):
        sym = p.stem.replace("_daily", "").replace("_", " ")
        rows = load_daily(p)
        if len(rows) < args.min_days or is_fixed_income(sym):
            continue
        fp = tuple((d.isoformat(), round(b.c, 6)) for d, b in rows)
        if fp in fps or norm(sym) in seen:
            continue
        fps[fp] = 1
        seen.add(norm(sym))

        by = defaultdict(list)
        for d, b in rows:
            by[SAT(d) if args.window == "week" else (d.year, d.month)].append(b)
        ks = sorted(by)
        for i in range(len(ks) - 1):
            prev, fwd = by[ks[i]], by[ks[i + 1]]
            if len(prev) < 3 or len(fwd) < 2:
                continue
            box = make_box(args.kind, prev, prev[-1].c)
            if box is None:
                continue
            px = fwd[0].c
            if state(px, box) != "بالا":
                continue
            nsig += 1
            lv = entry_levels(prev, box)
            height = box[1] - box[0]
            for k in LEVELS:
                e = lv.get(k)
                if e is None or e <= 0:
                    continue
                r = trade(fwd[1:], e, box[0], e + height)
                res[k][r] += 1
                gap[k].append((px - e) / px * 100)

    print("=" * 78)
    w = "هفتگی" if args.window == "week" else "ماهانه"
    print(f"سطحِ واکنش — پنجرهٔ {w} · {nsig:,} سیگنال · {len(seen)} نماد")
    print("=" * 78)
    print(f"\n{'سطح ورود':<14}{'خالی':>8}{'تارگت':>8}{'استاپ':>8}"
          f"{'هم‌کندل':>9}{'باز':>6}{'پر شد':>8}{'برد':>8}{'فاصله':>9}")
    print("─" * 78)
    rowsj = {}
    for k in LEVELS:
        d = res[k]
        tot = sum(d.values())
        if not tot:
            continue
        filled = tot - d["خالی"]
        decided = d["تارگت"] + d["استاپ"]
        win = d["تارگت"] / decided * 100 if decided else float("nan")
        g = statistics.median(gap[k]) if gap[k] else float("nan")
        print(f"{k:<14}{d['خالی']/tot*100:>7.1f}٪{d['تارگت']:>8}"
              f"{d['استاپ']:>8}{d['هم‌کندل']:>9}{d['باز']:>6}"
              f"{filled/tot*100:>7.1f}٪{win:>7.1f}٪{g:>8.2f}٪")
        rowsj[k] = {"n": tot, "empty_pct": d["خالی"] / tot * 100,
                    "target": d["تارگت"], "stop": d["استاپ"],
                    "same_bar": d["هم‌کندل"], "open": d["باز"],
                    "fill_pct": filled / tot * 100, "win": win,
                    "median_gap": g}

    bt, tl = rowsj.get("box_top"), rowsj.get("touch_low")
    ctl = rowsj.get("box_top_1p")
    if bt and tl:
        print("\n" + "─" * 78)
        print("حکم")
        print("─" * 78)
        print(f"  «سقف باکس»  : {bt['fill_pct']:.1f}٪ پر شد، "
              f"برد {bt['win']:.1f}٪")
        print(f"  «کف کندل‌های لمس‌کننده»: {tl['fill_pct']:.1f}٪ پر شد، "
              f"برد {tl['win']:.1f}٪")
        print(f"  اختلافِ پرشدن: {tl['fill_pct']-bt['fill_pct']:+.1f} واحد")
        print(f"  اختلافِ برد  : {tl['win']-bt['win']:+.1f} واحد")
        if ctl:
            print(f"\n  گروه کنترل «سقف باکس +۱٪»: {ctl['fill_pct']:.1f}٪ پر، "
                  f"برد {ctl['win']:.1f}٪")
            print("  اگر کنترل هم مثل touch_low بهتر شد، یافته دربارهٔ")
            print("  «کندل‌های مرتبط» نیست — دربارهٔ «هر سطح بالاتر» است.")

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps({"window": args.window, "signals": nsig,
                        "levels": rowsj}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(f"\nJSON: {Path(args.json_out).resolve()}")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
