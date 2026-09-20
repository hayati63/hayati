# -*- coding: utf-8 -*-
"""
بک‌تست باکس حجمی ماهانه — چهار تعریف باکس، کنار نرخ پایه.

چیزی که این اسکریپت از `dashboard_monthly.py` متفاوت انجام می‌دهد:

  ۱. **نرخ پایه.** بازده شرطی بدون گروه کنترل عدد نیست. (قاعدهٔ ۲ در CLAUDE.md)
  ۲. **تست جایگشت.** با ۱۴۵ نماد همبسته روی ۶ ماه، t معمولی معنا ندارد.
     برچسب‌ها را داخل هر ماه به‌هم می‌ریزیم و توزیع پوچ را می‌سازیم؛ این
     حرکت کل بازار در آن ماه را ثابت نگه می‌دارد و فقط می‌پرسد «آیا باکس
     نمادهای بهتری از تصادف انتخاب می‌کند؟»
  ۳. **هندسهٔ ۱:۱ خود CLAUDE.md** — ورود روی پولبک به سقف باکس، استاپ زیر کف،
     تارگت به اندازهٔ ارتفاع باکس. نرخ «حمایت خالی» هم گزارش می‌شود.
  ۴. تفکیک درآمد ثابت، حذف نماد تکراری و برخورد نام.
  ۵. عرض باکس هر تعریف — انگشت‌نگاریِ اینکه کدام تعریف واقعاً اجرا می‌شود.

اجرا:
    python3 tools/monthly_backtest.py --data data_auto
    python3 tools/monthly_backtest.py --data data_auto --kinds valley_first,value_area
"""

import argparse
import csv
import math
import random
import re
import statistics
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vp_box import BOX_KINDS, Bar, make_box, state  # noqa: E402


# صندوق درآمد ثابت و اخزا — همان فهرست backtest_auto_nofixed.py
FIXED_KEYS = [
    "ثابت", "درآمد", "ياقوت", "یاقوت", "کارا", "كارا", "اعتماد", "همای", "هماي",
    "آوند", "اوند", "کمند", "كمند", "فیروزا", "فيروزا", "گنجینه", "گنجينه",
    "افران", "آرامش", "ارامش", "پاداش", "بلوط", "زمرد", "آکام", "اكام", "آكام",
    "ارمغان", "اوصتا", "ثبات", "بازده", "همگام", "پایدار", "پايدار", "آلا",
    "آکورد", "اكورد", "آكورد", "اعتبار", "خزانه", "آسال", "آفاق", "سام", "کاج",
    "كاج", "ماکان", "ماكان", "رایبد", "رايبد", "گارانتی", "گارانتي", "هیبرید",
    "هيبريد", "تمشک", "تمشك", "سیناد", "سيناد", "سیمانیا", "سيمانيا", "بلد",
    "اخزا", "تسه", "ضمان", "مختلط", "کلید", "كليد", "همسنگ", "کاردان", "كاردان",
]

_NORM = {"ي": "ی", "ك": "ک", "ة": "ه", "‌": ""}


def norm(s):
    s = unicodedata.normalize("NFKC", s)
    for a, b in _NORM.items():
        s = s.replace(a, b)
    return re.sub(r"[\s_\-]+", "", s)


def is_fixed_income(name):
    n = norm(name)
    return any(norm(k) in n for k in FIXED_KEYS)


def load_daily(path):
    """CSV روزانه با ستون‌های منعطف. خروجی: فهرست (date, Bar) مرتب."""
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rd = csv.DictReader(fh)
        if not rd.fieldnames:
            return rows
        cols = {c.strip().lower().strip("<>"): c for c in rd.fieldnames}

        def pick(*names):
            for nm in names:
                if nm in cols:
                    return cols[nm]
            return None

        c_date = pick("date", "dtyyyymmdd", "tarikh") or rd.fieldnames[0]
        c_h, c_l = pick("high", "h", "pmax"), pick("low", "l", "pmin")
        c_c = pick("close", "c", "pc", "pl", "final", "adjclose")
        c_v = pick("volume", "vol", "tvol")
        if not c_c:
            return rows

        for r in rd:
            raw = str(r.get(c_date, "")).strip()
            dt = None
            for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
                try:
                    dt = datetime.strptime(raw[: len(fmt) + 4].strip(), fmt)
                    break
                except ValueError:
                    continue
            if dt is None:
                continue

            def num(col, default=None):
                if not col:
                    return default
                try:
                    return float(str(r.get(col, "")).replace(",", ""))
                except (TypeError, ValueError):
                    return default

            c = num(c_c)
            if c is None or c <= 0:
                continue
            h, l = num(c_h, c), num(c_l, c)
            v = num(c_v, 0.0) or 0.0
            if h < l:
                h, l = l, h
            rows.append((dt.date(), Bar(h, l, c, v)))

    rows.sort(key=lambda x: x[0])
    return rows


def geometry_trade(box, fwd_bars):
    """هندسهٔ ۱:۱ خود CLAUDE.md، روی کندل‌های روزانهٔ ماه بعد.

    ورود روی پولبک به سقف باکس. استاپ کف باکس. تارگت به اندازهٔ ارتفاع باکس
    بالای سقف. اگر پولبک نزند «حمایت خالی» است و معامله‌ای نیست.

    خروجی: (نتیجه, بازده بر حسب R) — نتیجه یکی از
    'خالی' / 'تارگت' / 'استاپ' / 'پایان ماه'
    """
    lo, hi = box
    height = hi - lo
    if height <= 0:
        return ("خالی", None)
    target = hi + height

    entered = False
    for _, b in fwd_bars:
        if not entered:
            if b.l <= hi:                      # پولبک خورد
                entered = True
                # همان روز ممکن است استاپ هم بخورد؛ بدبینانه اول استاپ
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
    last = fwd_bars[-1][1].c
    return ("پایان ماه", (last - hi) / height)


def welch_t(a, b):
    if len(a) < 2 or len(b) < 2:
        return float("nan")
    va, vb = statistics.variance(a), statistics.variance(b)
    se = math.sqrt(va / len(a) + vb / len(b))
    return (statistics.mean(a) - statistics.mean(b)) / se if se else float("nan")


def month_edge(rows_by_month, target_state):
    """میانگینِ ماهانهٔ [بازده حالت هدف − بازده همهٔ نمادهای همان ماه]."""
    diffs = []
    for rows in rows_by_month.values():
        sel = [r["ret"] for r in rows if r["st"] == target_state]
        if len(sel) < 3 or len(rows) < 5:
            continue
        diffs.append(statistics.mean(sel) - statistics.mean([r["ret"] for r in rows]))
    return diffs


def permutation_p(rows_by_month, target_state, n_iter=5000, seed=42):
    """توزیع پوچ با به‌هم‌ریختن برچسب حالت **داخل هر ماه**.

    این کار حرکت کل بازار در آن ماه و تعداد سیگنال‌های آن ماه را ثابت نگه
    می‌دارد؛ تنها چیزی که تصادفی می‌شود این است که کدام نماد برچسب گرفت.
    """
    obs = month_edge(rows_by_month, target_state)
    if len(obs) < 2:
        return None, None
    obs_mean = statistics.mean(obs)

    rng = random.Random(seed)
    usable = [
        (len([r for r in rows if r["st"] == target_state]), [r["ret"] for r in rows])
        for rows in rows_by_month.values()
        if len(rows) >= 5 and len([r for r in rows if r["st"] == target_state]) >= 3
    ]
    if len(usable) < 2:
        return obs_mean, None

    hits = 0
    for _ in range(n_iter):
        diffs = []
        for k, rets in usable:
            pick = rng.sample(rets, k)
            diffs.append(statistics.mean(pick) - statistics.mean(rets))
        if statistics.mean(diffs) >= obs_mean:
            hits += 1
    return obs_mean, (hits + 1) / (n_iter + 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="پوشهٔ CSVهای روزانه")
    ap.add_argument("--glob", default="*_daily.csv")
    ap.add_argument("--kinds", default=",".join(BOX_KINDS))
    ap.add_argument("--min-rows", type=int, default=3)
    ap.add_argument("--max-rows", type=int, default=20)
    ap.add_argument("--min-bars", type=int, default=8, help="حداقل کندل در ماه باکس")
    ap.add_argument("--include-fixed", action="store_true",
                    help="درآمد ثابت را هم داخل تحلیل اصلی بیاور (پیش‌فرض: جدا)")
    ap.add_argument("--iters", type=int, default=5000)
    args = ap.parse_args()

    kinds = [k.strip() for k in args.kinds.split(",") if k.strip()]
    for k in kinds:
        if k not in BOX_KINDS:
            print(f"تعریف ناشناخته: {k}. یکی از {BOX_KINDS}")
            return 1

    files = sorted(Path(args.data).glob(args.glob))
    if not files:
        print(f"هیچ فایلی با الگوی {args.glob} در {args.data} نبود.")
        return 1

    # ─── بارگذاری + حذف تکراری و برخورد ───
    series, fingerprints, collisions, thin = {}, {}, [], []
    for p in files:
        name = p.name
        for suf in ("_daily.csv", ".csv"):
            if name.endswith(suf):
                name = name[: -len(suf)]
                break
        rows = load_daily(p)
        if len(rows) < 20:
            thin.append((name, len(rows)))
            continue
        fp = hash(tuple((d.isoformat(), round(b.c, 6)) for d, b in rows))
        if fp in fingerprints:
            collisions.append((name, fingerprints[fp], "سری قیمت یکسان"))
            continue
        fingerprints[fp] = name
        key = norm(name)
        if key in series:
            collisions.append((name, series[key][0], "نام یکسان پس از نرمال‌سازی"))
            continue
        series[key] = (name, rows)

    print("=" * 72)
    print(f"فایل: {len(files)}  |  نماد یکتا: {len(series)}"
          f"  |  کم‌داده (<20 کندل): {len(thin)}")
    if collisions:
        print(f"حذف‌شده — تکرار یا برخورد: {len(collisions)}")
        for a, b, why in collisions[:15]:
            print(f"    {a}  ≡  {b}   ({why})")
    print("=" * 72)

    # ─── ساخت مشاهدات برای هر تعریف ───
    per_kind = {k: [] for k in kinds}
    widths = {k: [] for k in kinds}
    geom = {k: [] for k in kinds}

    for _, (name, rows) in series.items():
        fixed = is_fixed_income(name)
        by_month = defaultdict(list)
        for d, b in rows:
            by_month[(d.year, d.month)].append((d, b))
        months = sorted(by_month)

        for i in range(len(months) - 1):
            m_box, m_fwd = months[i], months[i + 1]
            y, mo = m_box
            if m_fwd != ((y + 1, 1) if mo == 12 else (y, mo + 1)):
                continue

            box_bars = [b for _, b in by_month[m_box]]
            if len(box_bars) < args.min_bars:
                continue
            fwd = by_month[m_fwd]
            if len(fwd) < 2:
                continue

            # قیمت مرجع = کلوز آخرین روز ماهِ باکس. در دسترس بوده، پس لوک‌اهد نیست.
            ref = box_bars[-1].c
            entry = fwd[0][1].c
            ret = (fwd[-1][1].c - entry) / entry * 100.0

            for k in kinds:
                box = make_box(k, box_bars, ref, args.min_rows, args.max_rows)
                if box is None:
                    continue
                st = state(entry, box)
                per_kind[k].append(
                    {"month": m_fwd, "sym": name, "fixed": fixed, "st": st, "ret": ret}
                )
                widths[k].append((box[1] - box[0]) / entry * 100.0)
                if st == "بالا" and not fixed:
                    outcome, r = geometry_trade(box, fwd)
                    geom[k].append((outcome, r))

    any_rows = next((v for v in per_kind.values() if v), None)
    if not any_rows:
        print("هیچ مشاهده‌ای ساخته نشد — دادهٔ ماهانه کافی نیست.")
        return 1

    months_all = sorted({o["month"] for v in per_kind.values() for o in v})
    print(f"\nماه متمایز: {len(months_all)}"
          f"  ({months_all[0][0]}/{months_all[0][1]:02d} تا"
          f" {months_all[-1][0]}/{months_all[-1][1]:02d})")
    print(f"⚠️  n مؤثر ≈ {len(months_all)} (ماه). نمادها هم‌زمان یک بازار را")
    print("    معامله می‌کنند، پس تعداد معامله n نیست.\n")

    # ─── عرض باکس: انگشت‌نگاری تعریف ───
    print("─" * 72)
    print("عرض باکس (٪ از قیمت) — با عرض باکس‌های داشبورد فعلی مقایسه کنید")
    print(f"  {'تعریف':<16} {'میانه':>8} {'میانگین':>9} {'n':>7}")
    for k in kinds:
        w = widths[k]
        if not w:
            continue
        print(f"  {k:<16} {statistics.median(w):>7.2f}٪ {statistics.mean(w):>8.2f}٪"
              f" {len(w):>7}")
    print("  (کهربا در داشبورد فعلی ۱٫۳۸٪ · زیتون ۰٫۴۷٪ · تمشک ۰٫۵۳٪)")

    # ─── جدول اصلی ───
    for label, want_fixed in (("بدون درآمد ثابت", False), ("فقط درآمد ثابت", True)):
        print("\n" + "─" * 72)
        print(label)
        print(f"  {'تعریف':<16} {'پایه٪':>7} {'بالا n':>7} {'برد':>7} {'مزیت':>7}"
              f" {'میانگین':>9} {'t':>6}")
        for k in kinds:
            rows = [o for o in per_kind[k] if o["fixed"] == want_fixed]
            if len(rows) < 10:
                continue
            base = [o["ret"] for o in rows]
            base_win = sum(1 for r in base if r > 0) / len(base) * 100
            sel = [o["ret"] for o in rows if o["st"] == "بالا"]
            if len(sel) < 5:
                print(f"  {k:<16} {base_win:>6.1f}٪  — کمتر از ۵ سیگنال")
                continue
            others = [o["ret"] for o in rows if o["st"] != "بالا"]
            win = sum(1 for r in sel if r > 0) / len(sel) * 100
            print(f"  {k:<16} {base_win:>6.1f}٪ {len(sel):>7}"
                  f" {win:>6.1f}٪ {win-base_win:>+6.1f} "
                  f"{statistics.mean(sel):>+8.2f}٪ {welch_t(sel, others):>+6.2f}")
        if not want_fixed:
            print("  ستون «مزیت» را بخوانید، نه ستون «برد».")

    # ─── تست جایگشت ───
    print("\n" + "─" * 72)
    print(f"تست جایگشت — برچسب «بالا» داخل هر ماه به‌هم ریخته ({args.iters} بار)")
    print("  پوچ: باکس نماد بهتری از تصادف انتخاب نمی‌کند.")
    print(f"\n  {'تعریف':<16} {'ماه':>5} {'مزیت واحد٪':>12} {'p':>8}")
    for k in kinds:
        rows = [o for o in per_kind[k] if not o["fixed"]]
        by_m = defaultdict(list)
        for o in rows:
            by_m[o["month"]].append(o)
        edge, p = permutation_p(by_m, "بالا", args.iters)
        if edge is None:
            print(f"  {k:<16} — ماه کافی نیست")
            continue
        n_m = len(month_edge(by_m, "بالا"))
        ps = "—" if p is None else f"{p:.4f}"
        star = " ★" if (p is not None and p < 0.05) else ""
        print(f"  {k:<16} {n_m:>5} {edge:>+11.2f} {ps:>8}{star}")
    print("\n  p بالای ۰٫۰۵ یعنی از تصادف قابل تفکیک نیست.")
    print(f"  با {len(months_all)} ماه، کمترین p ممکن حدود {1/(len(months_all)+1):.2f}")
    print("  است — یعنی حتی سیگنال واقعی هم با این تعداد ماه اثبات نمی‌شود.")

    # ─── هندسهٔ ۱:۱ ───
    print("\n" + "─" * 72)
    print("هندسهٔ ۱:۱ خود CLAUDE.md (ورود روی پولبک، بدون درآمد ثابت)")
    print(f"  {'تعریف':<16} {'سیگنال':>7} {'خالی':>7} {'تارگت':>7} {'استاپ':>7}"
          f" {'میانگین R':>10}")
    for k in kinds:
        g = geom[k]
        if not g:
            continue
        empty = sum(1 for o, _ in g if o == "خالی")
        tp = sum(1 for o, _ in g if o == "تارگت")
        sl = sum(1 for o, _ in g if o == "استاپ")
        rs = [r for _, r in g if r is not None]
        avg = statistics.mean(rs) if rs else float("nan")
        print(f"  {k:<16} {len(g):>7} {empty/len(g)*100:>6.0f}٪"
              f" {tp:>7} {sl:>7} {avg:>+10.3f}")
    print("  «خالی» = حمایت خالی: پولبک نخورد، پس ورودی نبود.")

    print("\n" + "=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
