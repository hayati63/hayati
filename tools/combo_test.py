# -*- coding: utf-8 -*-
"""آیا «ماهانه مثبت **و** هفتگی مثبت» بهتر از هرکدام به‌تنهایی است؟

این ایده باید **اندازه گرفته شود، نه فرض**. بند ۳ `CLAUDE.md` خویشاوند
نزدیکش را قبلاً رد کرده:

    هم‌جهت بودن هر سه حمایت | هر سه بالا ۶۸٫۸٪/+۰٫۴۰۰R ·
    فقط هفتگی ۷۵٫۰٪/+۰٫۵۰۰R · **t=۰٫۱۴ p=۰٫۸۹**

یعنی آنجا «هم‌جهت بودن» چیزی اضافه نکرد. پس اینجا هم پیش‌فرض این است که
اضافه نمی‌کند، مگر داده خلافش را نشان بدهد.

**واحد مشاهده: هفته.** باکس ماهانه از ماه قبل، باکس هفتگی از هفتهٔ قبل، و
بازده هفتهٔ پیشِ رو. چرا هفته: ورودِ ماهانه فقط ۱۲ بار در سال تصمیم است،
ولی سؤال «امروز کدام نماد را بخرم» هفتگی است.

هیچ لوک‌اهدی نیست: هر دو باکس از دوره‌های **کامل‌شده** می‌آیند.
"""
import argparse
import json
import random
import statistics
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from monthly_backtest import load_daily, is_fixed_income, norm
from vp_box import make_box, state
from weekly_backtest import week_key


def build(data_dir, glob, kind, min_days, include_fixed):
    """هر مشاهده: یک نماد در یک هفته، با وضعیت ماهانه و هفتگی‌اش."""
    obs = []
    fps, norms = {}, {}
    for p in sorted(Path(data_dir).glob(glob)):
        name = p.stem.replace("_daily", "").replace("_", " ")
        rows = load_daily(p)
        if len(rows) < 40:
            continue
        fp = tuple((d.isoformat(), round(b.c, 6)) for d, b in rows)
        if fp in fps or norm(name) in norms:
            continue
        fps[fp] = norms[norm(name)] = name
        if is_fixed_income(name) and not include_fixed:
            continue

        by_m, by_w = defaultdict(list), defaultdict(list)
        for d, b in rows:
            by_m[(d.year, d.month)].append((d, b))
            if d.weekday() not in (3, 4):
                by_w[week_key(d)].append((d, b))

        ws = sorted(by_w)
        for i in range(len(ws) - 1):
            wa, wb = ws[i], ws[i + 1]
            if (wb - wa).days != 7:
                continue
            prev_w, fwd = by_w[wa], by_w[wb]
            if len(prev_w) < min_days or len(fwd) < 2:
                continue
            entry = fwd[0][1].c
            ret = (fwd[-1][1].c - entry) / entry * 100.0

            wbox = make_box(kind, [x for _, x in prev_w], prev_w[-1][1].c)
            if wbox is None:
                continue

            # ماهِ کامل‌شدهٔ قبل از هفته‌ای که واردش می‌شویم
            first = fwd[0][0]
            pm = ((first.year - 1, 12) if first.month == 1
                  else (first.year, first.month - 1))
            if pm not in by_m or len(by_m[pm]) < 5:
                continue
            mbox = make_box(kind, [x for _, x in by_m[pm]],
                            by_m[pm][-1][1].c)
            if mbox is None:
                continue

            obs.append({"w": wb, "sym": name, "ret": ret,
                        "wst": state(entry, wbox),
                        "mst": state(entry, mbox)})
    return obs


def edges(by_w, pick):
    """میانگینِ هفتگیِ [بازده گروه هدف − بازده همهٔ نمادهای همان هفته]."""
    out = []
    for rows in by_w.values():
        sel = [r["ret"] for r in rows if pick(r)]
        if len(sel) < 3 or len(rows) < 5:
            continue
        out.append(statistics.mean(sel)
                   - statistics.mean([r["ret"] for r in rows]))
    return out


def perm_p(by_w, pick, n_iter, seed=42):
    obs = edges(by_w, pick)
    if len(obs) < 2:
        return None, None, 0
    obs_mean = statistics.mean(obs)
    rng = random.Random(seed)
    usable = [(len([r for r in rows if pick(r)]), [r["ret"] for r in rows])
              for rows in by_w.values()
              if len(rows) >= 5 and len([r for r in rows if pick(r)]) >= 3]
    if len(usable) < 2:
        return obs_mean, None, len(obs)
    hits = 0
    for _ in range(n_iter):
        diffs = [statistics.mean(rng.sample(rets, k)) - statistics.mean(rets)
                 for k, rets in usable]
        if statistics.mean(diffs) >= obs_mean:
            hits += 1
    return obs_mean, (hits + 1) / (n_iter + 1), len(obs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_auto")
    ap.add_argument("--glob", default="*.csv")
    ap.add_argument("--kind", default="valley_first")
    ap.add_argument("--min-days", type=int, default=3)
    ap.add_argument("--iters", type=int, default=20000)
    ap.add_argument("--include-fixed", action="store_true")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args()

    obs = build(args.data, args.glob, args.kind, args.min_days,
                args.include_fixed)
    if not obs:
        print("مشاهده‌ای ساخته نشد.")
        return 1

    by_w = defaultdict(list)
    for o in obs:
        by_w[o["w"]].append(o)
    allr = [o["ret"] for o in obs]
    base = statistics.mean(allr)
    base_win = sum(1 for r in allr if r > 0) / len(allr) * 100

    print("=" * 76)
    print(f"ترکیب ماهانه × هفتگی — تعریف باکس: {args.kind}")
    print(f"مشاهده: {len(obs):,} (نماد×هفته)  ·  هفته: {len(by_w)}"
          f"  ·  نماد: {len({o['sym'] for o in obs})}")
    print(f"نرخ پایه: {base:+.2f}٪ بازده هفتگی · {base_win:.1f}٪ مثبت")
    print("=" * 76)

    # جدول ۳×۳ — هر ترکیب، بدون فرض
    print("\nجدول کامل: وضعیت ماهانه (سطر) × وضعیت هفتگی (ستون)")
    print("  هر خانه: میانگین بازده هفتهٔ بعد ٪ · (n)\n")
    sts = ["بالا", "داخل", "زیر"]
    hdr = "ماهانه / هفتگی"
    print(f"  {hdr:<18}" + "".join(f"{s:>16}" for s in sts)
          + f"{'جمع سطر':>16}")
    for m in sts:
        row = f"  {m:<18}"
        for w in sts:
            sel = [o["ret"] for o in obs if o["mst"] == m and o["wst"] == w]
            row += (f"{statistics.mean(sel):>+9.2f} ({len(sel):>4})"
                    if len(sel) >= 20 else f"{'—':>16}")
        rs = [o["ret"] for o in obs if o["mst"] == m]
        row += (f"{statistics.mean(rs):>+9.2f} ({len(rs):>4})"
                if len(rs) >= 20 else f"{'—':>16}")
        print(row)
    row = f"  {'جمع ستون':<18}"
    for w in sts:
        cs = [o["ret"] for o in obs if o["wst"] == w]
        row += (f"{statistics.mean(cs):>+9.2f} ({len(cs):>4})"
                if len(cs) >= 20 else f"{'—':>16}")
    print(row)

    # آزمون: آیا ترکیب از تک‌تکشان بهتر است؟
    print("\n" + "─" * 76)
    print(f"آزمون جایگشت — برچسب داخل هر هفته به‌هم ریخته"
          f" ({args.iters:,} بار)\n")
    cands = [
        ("فقط هفتگی بالا", lambda r: r["wst"] == "بالا"),
        ("فقط ماهانه بالا", lambda r: r["mst"] == "بالا"),
        ("هر دو بالا", lambda r: r["wst"] == "بالا" and r["mst"] == "بالا"),
        ("هفتگی بالا، ماهانه نه",
         lambda r: r["wst"] == "بالا" and r["mst"] != "بالا"),
        ("ماهانه بالا، هفتگی نه",
         lambda r: r["mst"] == "بالا" and r["wst"] != "بالا"),
    ]
    print(f"  {'گروه':<24}{'n':>8}{'مثبت':>8}{'میانگین':>10}"
          f"{'هفته':>7}{'مزیت':>9}{'p':>9}")
    out = {}
    for label, pick in cands:
        sel = [o["ret"] for o in obs if pick(o)]
        if len(sel) < 20:
            print(f"  {label:<24}{len(sel):>8}  — کم")
            continue
        edge, p, n_w = perm_p(by_w, pick, args.iters)
        win = sum(1 for r in sel if r > 0) / len(sel) * 100
        star = " ★" if (p is not None and p < 0.05) else ""
        out[label] = {"n": len(sel), "win": win,
                      "avg": statistics.mean(sel), "weeks": n_w,
                      "edge": edge, "p": p}
        print(f"  {label:<24}{len(sel):>8}{win:>7.1f}٪"
              f"{statistics.mean(sel):>+9.2f}٪{n_w:>7}"
              f"{(edge if edge is not None else float('nan')):>+9.2f}"
              f"{(f'{p:.4f}' if p is not None else '—'):>9}{star}")

    # سؤال اصلی: ترکیب منهای هفتگیِ تنها
    both = out.get("هر دو بالا")
    wonly = out.get("فقط هفتگی بالا")
    monly = out.get("فقط ماهانه بالا")
    print("\n" + "─" * 76)
    print("سؤال اصلی: آیا تأیید ماهانه چیزی **اضافه** می‌کند؟\n")
    if both and wonly:
        d = both["edge"] - wonly["edge"]
        print(f"  مزیت «هر دو بالا»        {both['edge']:>+7.2f} واحد٪")
        print(f"  مزیت «فقط هفتگی بالا»    {wonly['edge']:>+7.2f} واحد٪")
        print(f"  {'اختلاف':<24}{d:>+7.2f} واحد٪")
        # تفاوت مستقیم: داخل هفته‌هایی که هر دو گروه ≥۳ عضو دارند
        pair = []
        for rows in by_w.values():
            a = [r["ret"] for r in rows
                 if r["wst"] == "بالا" and r["mst"] == "بالا"]
            b = [r["ret"] for r in rows
                 if r["wst"] == "بالا" and r["mst"] != "بالا"]
            if len(a) >= 3 and len(b) >= 3:
                pair.append(statistics.mean(a) - statistics.mean(b))
        if len(pair) >= 5:
            m = statistics.mean(pair)
            se = statistics.stdev(pair) / len(pair) ** 0.5
            t = m / se if se else float("nan")
            print(f"\n  مقایسهٔ مستقیم، داخل هر هفته:")
            print(f"    «هفتگی بالا + ماهانه بالا» منهای «هفتگی بالا + ماهانه نه»")
            print(f"    میانگین {m:>+6.2f} واحد٪ · خطای معیار {se:.2f}"
                  f" · t={t:+.2f} · روی {len(pair)} هفته")
            verdict = ("**تأیید ماهانه چیزی اضافه می‌کند**" if t > 2
                       else "**تأیید ماهانه چیزی اضافه نمی‌کند**"
                       if abs(t) < 2 else "**تأیید ماهانه بدتر می‌کند**")
            print(f"\n  حکم: {verdict} (آستانه |t|≥۲)")
            out["_interaction"] = {"mean": m, "se": se, "t": t,
                                   "weeks": len(pair)}
        else:
            print("\n  هفتهٔ کافی برای مقایسهٔ مستقیم نبود.")
    print("\n  یادآوری: بند ۳ CLAUDE.md «هم‌جهت بودن هر سه حمایت» را با")
    print("  t=۰٫۱۴ و p=۰٫۸۹ رد کرده. این آزمون همان سؤال است، یک پله ساده‌تر.")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps({
            "kind": args.kind, "n_obs": len(obs), "weeks": len(by_w),
            "symbols": len({o["sym"] for o in obs}),
            "base_avg": base, "base_win": base_win,
            "iters": args.iters, "groups": out,
            "grid": {m: {w: (lambda s: {"n": len(s),
                                        "avg": statistics.mean(s) if s else None})
                         ([o["ret"] for o in obs
                           if o["mst"] == m and o["wst"] == w])
                     for w in sts} for m in sts},
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nJSON: {Path(args.json_out).resolve()}")
    print("\n" + "=" * 76)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
