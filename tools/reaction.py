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
LEVELS = ("box_top", "touch_low", "touch_close", "last_touch",
          "poc_low", "poc_close", "poc_high", "box_top_1p")
FA = {"box_top": "سقفِ باکس", "touch_low": "کفِ کندل‌های لمس‌کننده",
      "touch_close": "کمینهٔ کلوزِ همان‌ها",
      "last_touch": "کفِ آخرین کندلِ لمس‌کننده",
      "poc_low": "کفِ کندلِ سازندهٔ ناحیه",
      "poc_close": "کلوزِ کندلِ سازندهٔ ناحیه",
      "poc_high": "سقفِ کندلِ سازندهٔ ناحیه",
      "box_top_1p": "سقفِ باکس +۱٪ (کنترل)"}


def entry_levels(bars, box):
    """سطوحِ ورود از روی کندل‌های دورهٔ ساختِ باکس.

    `poc_*` دقیق‌ترین خوانشِ حرفِ مصطفی است: **آن** کندلی که ناحیه را
    ساخته، نه هر کندلی که لمسش کرده. سهمِ حجمِ هر کندل از بازهٔ باکس
    به نسبتِ هم‌پوشانی حساب می‌شود (همان قاعدهٔ پخشِ حجم در
    `vp_box`), و کندلی که بیشترین سهم را داده «کندلِ سازندهٔ ناحیه»
    است.
    """
    lo, hi = box
    # کندلی «باکس را لمس کرده» که رنجش با باکس اشتراک دارد
    touch = [b for b in bars if b.l <= hi and b.h >= lo]
    out = {"box_top": hi, "box_top_1p": hi * 1.01}
    if touch:
        out["touch_low"] = min(b.l for b in touch)
        out["touch_close"] = min(b.c for b in touch)
        out["last_touch"] = touch[-1].l
        best, bv = None, 0.0
        for b in touch:
            br = b.h - b.l
            share = (b.v if br <= 0
                     else b.v * max(0.0, min(hi, b.h) - max(lo, b.l)) / br)
            if share > bv:
                best, bv = b, share
        if best is not None:
            out["poc_low"] = best.l
            out["poc_close"] = best.c
            out["poc_high"] = best.h
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



def _bootstrap(per, a, b, iters=4000, seed=5):
    """بوت‌استرپِ خوشه‌ایِ اختلافِ (نرخِ برد، نرخِ پرشدن) بینِ دو سطح.

    خوشه = نماد. سیگنال‌های یک نماد هم‌بسته‌اند، پس نمونه‌گیری روی
    نماد است. خروجی: (اختلافِ واقعی، بازهٔ ۵–۹۵٪، سهمِ بازنمونه‌هایی
    که علامتشان برعکس است).
    """
    import random
    syms = [k for k in per if per[k].get(a) and per[k].get(b)]
    if len(syms) < 8:
        return None

    def stat(pool):
        o = {}
        for k in (a, b):
            t = sum(r.count("تارگت") for r in pool[k])
            st = sum(r.count("استاپ") for r in pool[k])
            n = sum(len(r) for r in pool[k])
            f = n - sum(r.count("خالی") for r in pool[k])
            o[k] = (t / (t + st) * 100 if t + st else None,
                    f / n * 100 if n else None)
        if o[a][0] is None or o[b][0] is None:
            return None
        return o[b][0] - o[a][0], o[b][1] - o[a][1]

    def pool_of(ss):
        o = {a: [], b: []}
        for x in ss:
            for k in (a, b):
                o[k].append(per[x][k])
        return o

    real = stat(pool_of(syms))
    if real is None:
        return None
    rnd = random.Random(seed)
    dw, df, flip = [], [], 0
    for _ in range(iters):
        ss = [rnd.choice(syms) for _ in syms]
        v = stat(pool_of(ss))
        if v is None:
            continue
        dw.append(v[0])
        df.append(v[1])
        if (v[0] > 0) != (real[0] > 0):
            flip += 1
    if not dw:
        return None
    dw.sort()
    df.sort()
    return {"win": real[0], "fill": real[1], "n_sym": len(syms),
            "win_lo": dw[int(.05 * len(dw))],
            "win_hi": dw[int(.95 * len(dw))],
            "fill_lo": df[int(.05 * len(df))],
            "fill_hi": df[int(.95 * len(df))],
            "flip": flip / len(dw)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_auto")
    ap.add_argument("--kind", default="valley_first")
    ap.add_argument("--window", choices=("week", "month"), default="week")
    ap.add_argument("--min-days", type=int, default=40)
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args()

    res = {k: defaultdict(int) for k in LEVELS}
    # برای بوت‌استرپِ خوشه‌ای: نتیجهٔ هر سطح، خوشه‌بندی‌شده به نماد.
    # سیگنال‌های یک نماد مستقل نیستند؛ بوت‌استرپِ ساده t را بزرگ‌نمایی
    # می‌کند. پس نمونه‌گیری روی **نماد** است نه روی معامله.
    per = defaultdict(lambda: defaultdict(list))
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
                # ── استاپ باید **زیرِ** ورود باشد ────────────────
                # نسخهٔ قبلیِ این ابزار استاپ را همیشه کفِ باکس
                # می‌گذاشت. ولی کفِ کندلِ لمس‌کننده معمولاً **پایین‌تر
                # از کفِ باکس** است، پس ورود زیرِ استاپ می‌افتاد و
                # معامله در همان لحظه «استاپ» می‌خورد. عددِ ۵٫۷٪
                # بردِ touch_low نتیجهٔ همین بود — ایرادِ آزمون، نه
                # یافته. حالا هندسه برای همه یکسان است: استاپ یک
                # ارتفاعِ باکس زیرِ ورود، تارگت یک ارتفاع بالا.
                st_ = min(box[0], e - height) if e < box[0] else box[0]
                if st_ >= e:
                    continue
                r = trade(fwd[1:], e, st_, e + (e - st_))
                res[k][r] += 1
                gap[k].append((px - e) / px * 100)
                per[sym][k].append(r)

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

    # ── مقایسهٔ خوشه‌ای با خطِ پایه ────────────────────────────────
    print("\n" + "─" * 78)
    print("مقایسه با «سقفِ باکس» — بوت‌استرپِ خوشه‌ای روی نماد")
    print("─" * 78)
    print(f"{'سطح ورود':<30}{'Δبرد':>8}{'بازهٔ ۵–۹۵٪':>20}"
          f"{'Δپرشدن':>10}{'علامتِ برعکس':>14}")
    for k in LEVELS:
        if k == "box_top":
            continue
        bs = _bootstrap(per, "box_top", k)
        if not bs:
            continue
        rng = f"{bs['win_lo']:+.1f} تا {bs['win_hi']:+.1f}"
        print(f"{FA.get(k, k):<30}{bs['win']:>+8.1f}{rng:>20}"
              f"{bs['fill']:>+9.1f}{bs['flip']:>13.0%}")
    print("\nΔ مثبت یعنی بهتر از سقفِ باکس. «علامتِ برعکس» سهمِ "
          "بازنمونه‌هایی است\nکه جهت را عوض کردند — هرچه کمتر، یافته "
          "پایدارتر. بالای ۱۰٪ یعنی\nاز تصادف جدا نشد.")

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
