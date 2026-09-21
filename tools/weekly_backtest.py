# -*- coding: utf-8 -*-
"""بک‌تست هفتگی — همان آزمون ماهانه، روی دورهٔ هفته.

چرا این مهم است: بند ۳ `CLAUDE.md` پولبک هفتگی را قوی‌ترین قاعدهٔ تأییدشده ثبت
کرده (۷۰٫۲٪ · +۰٫۴۰۹R · t=۹٫۹۱ · n=۴۲۹). ولی آن عدد با نرخ پایه مقایسه نشده
بود. اینجا همان کنترل ماهانه اجرا می‌شود: جایگشتِ برچسب **داخل هر هفته**.

و یک مزیت ساختاری دارد: ۱۱ ماه داده یعنی ~۹ ماهِ قابل‌استفاده، ولی همان داده
~۴۰ هفتهٔ قابل‌استفاده می‌دهد. تعداد دورهٔ مستقل چهار برابر می‌شود، و n مؤثرِ
آزمون جایگشت همان تعداد دوره است، نه تعداد معامله.

**هفته = شنبه تا چهارشنبه** — بند ۰ قانون ۱. در دادهٔ `data_auto` این
تأیید شد: صفر کندل پنجشنبه یا جمعه در ۱۳۶ نماد، و ۸۳٪ هفته‌ها چهارشنبه
بسته‌اند (۱۷٪ سه‌شنبه، وقتی چهارشنبه تعطیل رسمی بوده).

⚠️ **ولی این تقویم فقط برای صندوق‌های بورسی است.** دلار و تتر و طلای ۱۸ عیار
تقویم دیگری دارند — هفتهٔ آن‌ها روز دیگری بسته می‌شود. یعنی وقتی از «کلوز
هفته» حرف می‌زنیم، باید بگوییم کلوزِ کدام تقویم. `--calendar` این را برای هر
نماد از خود داده درمی‌آورد و چاپ می‌کند، به‌جای اینکه فرض کند.

⚠️ قید جدی: بند ۱ می‌گوید پروفایل هفتگی باید روی **H1** ساخته شود. اینجا از
کندل روزانه استفاده می‌شود، یعنی هر هفته حدود ۵ کندل. پروفایلِ ۵ کندلی خیلی
درشت است. عددها را با این قید بخوانید؛ برای تصحیح، H1 همهٔ نمادها لازم است.
"""
import argparse
import json
import random
import statistics
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from monthly_backtest import load_daily, is_fixed_income, norm, welch_t
from vp_box import BOX_KINDS, make_box, state


def week_key(d):
    """کلیدِ هفته = تاریخِ شنبهٔ همان هفته.

    weekday(): دوشنبه۰ … شنبه۵ یکشنبه۶. هفتهٔ بازار ایران شنبه شروع می‌شود،
    پس تا شنبهٔ قبلی عقب می‌رویم.
    """
    back = (d.weekday() - 5) % 7
    sat = d - timedelta(days=back)
    # load_daily گاهی datetime می‌دهد گاهی date؛ کلید باید یک جنس باشد
    return sat.date() if hasattr(sat, "date") else sat


WD = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]


def calendar_of(rows):
    """تقویمِ واقعیِ یک نماد، از خود داده.

    خروجی: (روزهای معاملاتی، روزی که هفته معمولاً با آن بسته می‌شود، سهمش).
    این حدس نیست — شمارش است. اگر نمادی پنجشنبه معامله داشته باشد اینجا
    پیدا می‌شود و تقویمش با صندوق‌های بورسی یکی نیست.
    """
    days = defaultdict(int)
    ends = defaultdict(int)
    by_w = defaultdict(list)
    for d, _ in rows:
        days[d.weekday()] += 1
        back = (d.weekday() - 5) % 7
        by_w[d - timedelta(days=back)].append(d)
    for v in by_w.values():
        if len(v) >= 3:
            ends[max(v).weekday()] += 1
    if not ends:
        return sorted(days), None, 0.0
    top = max(ends, key=lambda k: ends[k])
    return sorted(days), top, ends[top] / sum(ends.values()) * 100


def month_edge(by_period, target):
    out = []
    for rows in by_period.values():
        sel = [r["ret"] for r in rows if r["st"] == target]
        if len(sel) < 3 or len(rows) < 5:
            continue
        out.append(statistics.mean(sel)
                   - statistics.mean([r["ret"] for r in rows]))
    return out


def permutation_p(by_period, target, n_iter, seed=42):
    obs = month_edge(by_period, target)
    if len(obs) < 2:
        return None, None
    obs_mean = statistics.mean(obs)
    rng = random.Random(seed)
    usable = [(len([r for r in rows if r["st"] == target]),
               [r["ret"] for r in rows])
              for rows in by_period.values()
              if len(rows) >= 5
              and len([r for r in rows if r["st"] == target]) >= 3]
    if len(usable) < 2:
        return obs_mean, None
    hits = 0
    for _ in range(n_iter):
        diffs = [statistics.mean(rng.sample(rets, k)) - statistics.mean(rets)
                 for k, rets in usable]
        if statistics.mean(diffs) >= obs_mean:
            hits += 1
    return obs_mean, (hits + 1) / (n_iter + 1)


def geometry(box, fwd):
    """همان هندسهٔ ۱:۱ بند ۱، روی کندل‌های هفتهٔ بعد."""
    lo, hi = box
    h = hi - lo
    if h <= 0:
        return ("خالی", None)
    target = hi + h
    entered = False
    for _, b in fwd:
        if not entered:
            if b.l <= hi:
                entered = True
                if b.l <= lo:
                    return ("استاپ", -1.0)
                if b.h >= target:
                    return ("تارگت", 1.0)
            continue
        if b.l <= lo:
            return ("استاپ", -1.0)
        if b.h >= target:
            return ("تارگت", 1.0)
    if not entered:
        return ("خالی", None)
    return ("پایان هفته", (fwd[-1][1].c - hi) / h)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_auto")
    ap.add_argument("--glob", default="*.csv")
    ap.add_argument("--kinds", default=",".join(BOX_KINDS))
    ap.add_argument("--min-days", type=int, default=3,
                    help="کمینه روزِ معاملاتی در یک هفته تا باکس معنی بدهد")
    ap.add_argument("--iters", type=int, default=20000)
    ap.add_argument("--include-fixed", action="store_true")
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--calendar", action="store_true",
                    help="تقویم واقعی هر نماد را هم چاپ کن")
    args = ap.parse_args()

    kinds = [k.strip() for k in args.kinds.split(",") if k.strip()]

    # ── بارگذاری، با همان حذف تکراری بک‌تست ماهانه ──
    series, fps, norms = {}, {}, {}
    for p in sorted(Path(args.data).glob(args.glob)):
        name = p.name
        for suf in ("_daily.csv", ".csv"):
            if name.endswith(suf):
                name = name[: -len(suf)]
                break
        name = name.replace("_", " ")
        rows = load_daily(p)
        if len(rows) < 30:
            continue
        fp = tuple((d.isoformat(), round(b.c, 6)) for d, b in rows)
        if fp in fps or norm(name) in norms:
            continue
        fps[fp] = norms[norm(name)] = name
        series[name] = rows

    per_kind = {k: [] for k in kinds}
    geom = {k: [] for k in kinds}
    widths = {k: [] for k in kinds}
    weeks_all = set()
    thin_weeks = 0

    for name, rows in series.items():
        fixed = is_fixed_income(name)
        if fixed and not args.include_fixed:
            continue
        by_w = defaultdict(list)
        for d, b in rows:
            if d.weekday() in (3, 4):      # پنجشنبه و جمعه
                continue
            by_w[week_key(d)].append((d, b))
        ws = sorted(by_w)
        for i in range(len(ws) - 1):
            a, b = ws[i], ws[i + 1]
            if (b - a).days != 7:          # هفتهٔ پشت‌سرهم نبود
                continue
            box_days, fwd = by_w[a], by_w[b]
            if len(box_days) < args.min_days or len(fwd) < 2:
                thin_weeks += 1
                continue
            bars = [x for _, x in box_days]
            entry = fwd[0][1].c
            ret = (fwd[-1][1].c - entry) / entry * 100.0
            weeks_all.add(b)
            for k in kinds:
                box = make_box(k, bars, bars[-1].c)
                if box is None:
                    continue
                widths[k].append((box[1] - box[0]) / entry * 100)
                per_kind[k].append({"w": b, "sym": name,
                                    "st": state(entry, box), "ret": ret})
                geom[k].append(geometry(box, fwd))

    if not weeks_all:
        print("هیچ هفتهٔ قابل‌استفاده‌ای ساخته نشد.")
        return 1

    ws = sorted(weeks_all)
    print("=" * 74)
    print(f"نماد: {len(series)}  |  هفتهٔ متمایز: {len(ws)}"
          f"  ({ws[0]} تا {ws[-1]})")
    print(f"هفتهٔ کم‌روز (<{args.min_days} روز) که رد شد: {thin_weeks}")
    print("هفته = شنبه تا چهارشنبه (بند ۰ قانون ۱)")
    print("=" * 74)

    # ── تقویم واقعی، از داده ──
    cal = {s2: calendar_of(r) for s2, r in series.items()}
    end_hist = defaultdict(int)
    odd_days = defaultdict(list)
    for s2, (dys, top, _) in cal.items():
        if top is not None:
            end_hist[top] += 1
        for wd in dys:
            if wd in (3, 4):
                odd_days[wd].append(s2)
    print("\nتقویمِ اندازه‌گیری‌شده (نه فرض‌شده):")
    for wd, n2 in sorted(end_hist.items(), key=lambda kv: -kv[1]):
        print(f"  هفته با {WD[wd]} بسته می‌شود — {n2} نماد")
    if odd_days:
        for wd, syms in odd_days.items():
            print(f"  ⚠️ {len(syms)} نماد {WD[wd]} هم معامله دارند: "
                  + "، ".join(syms[:6]))
    else:
        print("  هیچ نمادی پنجشنبه یا جمعه معامله ندارد.")
    print("\n  دلار، تتر و طلای ۱۸ در این داده **نیستند**. تقویم آن‌ها فرق")
    print("  می‌کند و وقتی دادهٔ آن‌ها برسد همین‌جا اندازه گرفته می‌شود.")
    if args.calendar:
        print(f"\n  {'نماد':<16}{'پایانِ هفته':<12}{'سهم':>7}  روزهای معاملاتی")
        for s2 in sorted(cal):
            dys, top, share = cal[s2]
            print(f"  {s2:<16}{(WD[top] if top is not None else '—'):<12}"
                  f"{share:>6.0f}٪  " + "،".join(WD[w][:2] for w in dys))

    print("\n⚠️ پروفایل روی کندل **روزانه** ساخته شده، نه H1. بند ۱ می‌گوید")
    print("   باکس هفتگی با H1. هر هفته اینجا فقط ~۵ کندل دارد، پس پروفایل")
    print("   درشت است. عددها را با این قید بخوانید.")

    print("\n" + "─" * 74)
    print(f"عرض باکس (٪ از قیمت ورود)")
    print(f"  {'تعریف':<16}{'میانه':>9}{'میانگین':>10}{'n':>8}")
    for k in kinds:
        if widths[k]:
            print(f"  {k:<16}{statistics.median(widths[k]):>8.2f}٪"
                  f"{statistics.mean(widths[k]):>9.2f}٪{len(widths[k]):>8}")

    print("\n" + "─" * 74)
    print(f"  {'تعریف':<16}{'پایه٪':>7}{'بالا n':>8}{'برد':>8}{'مزیت':>7}"
          f"{'میانگین':>10}{'t':>7}")
    for k in kinds:
        rows_ = per_kind[k]
        if not rows_:
            continue
        base = [o["ret"] for o in rows_]
        bw = sum(1 for r in base if r > 0) / len(base) * 100
        sel = [o["ret"] for o in rows_ if o["st"] == "بالا"]
        oth = [o["ret"] for o in rows_ if o["st"] != "بالا"]
        if len(sel) < 5:
            continue
        win = sum(1 for r in sel if r > 0) / len(sel) * 100
        print(f"  {k:<16}{bw:>6.1f}٪{len(sel):>8}{win:>7.1f}٪"
              f"{win-bw:>+7.1f}{statistics.mean(sel):>+9.2f}٪"
              f"{welch_t(sel, oth):>+7.2f}")
    print("  ستون «مزیت» را بخوانید، نه ستون «برد».")

    print("\n" + "─" * 74)
    print(f"تست جایگشت — برچسب «بالا» داخل هر هفته به‌هم ریخته"
          f" ({args.iters:,} بار)")
    print(f"  {'تعریف':<16}{'هفته':>7}{'مزیت واحد٪':>13}{'p':>9}")
    perm = {}
    for k in kinds:
        by_w2 = defaultdict(list)
        for o in per_kind[k]:
            by_w2[o["w"]].append(o)
        edge, p = permutation_p(by_w2, "بالا", args.iters)
        if edge is None:
            print(f"  {k:<16}— هفتهٔ کافی نیست")
            continue
        n_w = len(month_edge(by_w2, "بالا"))
        sel = [o["ret"] for o in per_kind[k] if o["st"] == "بالا"]
        allr = [o["ret"] for o in per_kind[k]]
        perm[k] = {"weeks": n_w, "edge": edge, "p": p, "n_signal": len(sel),
                   "avg": statistics.mean(sel) if sel else None,
                   "win": (sum(1 for x in sel if x > 0) / len(sel) * 100)
                   if sel else None,
                   "base_win": (sum(1 for x in allr if x > 0) / len(allr) * 100)
                   if allr else None,
                   "width_med": statistics.median(widths[k]) if widths[k] else None}
        star = " ★" if (p is not None and p < 0.05) else ""
        print(f"  {k:<16}{n_w:>7}{edge:>+13.2f}"
              f"{(f'{p:.4f}' if p is not None else '—'):>9}{star}")
    print(f"\n  کف p = ۱/(تکرار+۱) = {1/(args.iters+1):.5f}")
    print(f"  n مؤثر = {len(ws)} هفته، نه تعداد معامله.")

    print("\n" + "─" * 74)
    print("هندسهٔ ۱:۱ — ورود روی پولبک به سقف باکس")
    print(f"  {'تعریف':<16}{'سیگنال':>8}{'خالی':>8}{'تارگت':>8}"
          f"{'استاپ':>8}{'میانگین R':>11}")
    geom_out = {}
    for k in kinds:
        g = geom[k]
        if not g:
            continue
        rs = [r for _, r in g if r is not None]
        e = sum(1 for o, _ in g if o == "خالی")
        tp = sum(1 for o, _ in g if o == "تارگت")
        sl = sum(1 for o, _ in g if o == "استاپ")
        avg = statistics.mean(rs) if rs else float("nan")
        geom_out[k] = {"n": len(g), "empty": e / len(g) * 100, "target": tp,
                       "stop": sl, "avg_r": avg}
        print(f"  {k:<16}{len(g):>8}{e/len(g)*100:>7.0f}٪{tp:>8}{sl:>8}"
              f"{avg:>+11.3f}")
    print("\n  بند ۳ CLAUDE.md برای همین قاعده ۷۰٫۲٪ و +۰٫۴۰۹R ثبت کرده")
    print("  (n=۴۲۹، ۱۱ از ۱۲ نماد مثبت) — ولی بدون نرخ پایه. ستون بالا با")
    print("  همان نرخ پایه‌ای که اینجا حساب شد مقایسه‌شدنی است.")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps({
            "window": "باکس از هفتهٔ قبل، بازده کل هفتهٔ بعد",
            "kind": "prev_week", "profile_tf": "روزانه (باید H1 باشد)",
            "weeks": len(ws), "span": [str(ws[0]), str(ws[-1])],
            "calendar": {WD[wd]: n2 for wd, n2 in end_hist.items()},
            "thursday_friday_symbols": sum(len(v) for v in odd_days.values()),
            "symbols": len(series), "iters": args.iters,
            "p_floor": 1 / (args.iters + 1),
            "perm": perm, "geom": geom_out,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nJSON: {Path(args.json_out).resolve()}")

    print("\n" + "=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
