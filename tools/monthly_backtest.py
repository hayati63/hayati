# -*- coding: utf-8 -*-
"""
بک‌تست باکس حجمی ماهانه — با نرخ پایه.

چیزی که این اسکریپت از `dashboard_monthly.py` متفاوت انجام می‌دهد:

  ۱. **نرخ پایه** را حساب می‌کند. بازده شرطی بدون گروه کنترل عدد نیست.
     (قاعدهٔ ۲ در CLAUDE.md)
  ۲. گزارش **ماه‌به‌ماه** می‌دهد، نه استخر درهم. ۶۱۵ معامله روی ۱۴۵ نماد در
     ۶ ماه یعنی ۶ مشاهدهٔ مستقل، نه ۶۱۵ تا — همهٔ نمادها یک بازار را معامله
     می‌کنند و بازده‌شان همبسته است.
  ۳. صندوق درآمد ثابت را جدا می‌کند. قیمتشان تقریباً یکنواخت بالا می‌رود، پس
     در هر تست «یک ماه نگه دار» نزدیک ۱۰۰٪ برد می‌دهند و میانگین را باد می‌کنند.
  ۴. نماد تکراری و برخورد نام را حذف می‌کند.
  ۵. هر دو تعریف باکس را کنار هم می‌سنجد.

اجرا:
    python3 tools/monthly_backtest.py --data data_auto
    python3 tools/monthly_backtest.py --data data_auto --box value_area
"""

import argparse
import csv
import math
import re
import statistics
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vp_box import Bar, state, valley_box, value_area_box  # noqa: E402


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


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    for a, b in _NORM.items():
        s = s.replace(a, b)
    return re.sub(r"[\s_\-]+", "", s)


def is_fixed_income(name: str) -> bool:
    n = norm(name)
    return any(norm(k) in n for k in FIXED_KEYS)


def load_daily(path: Path):
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
        c_o = pick("open", "o", "pf")
        c_h = pick("high", "h", "pmax")
        c_l = pick("low", "l", "pmin")
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
            h = num(c_h, c)
            l = num(c_l, c)
            v = num(c_v, 0.0) or 0.0
            if h < l:
                h, l = l, h
            _ = num(c_o, c)
            rows.append((dt.date(), Bar(h, l, c, v)))

    rows.sort(key=lambda x: x[0])
    return rows


def month_key(d):
    return (d.year, d.month)


def welch_t(a, b):
    if len(a) < 2 or len(b) < 2:
        return float("nan")
    va, vb = statistics.variance(a), statistics.variance(b)
    se = math.sqrt(va / len(a) + vb / len(b))
    if se == 0:
        return float("nan")
    return (statistics.mean(a) - statistics.mean(b)) / se


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="پوشهٔ CSVهای روزانه")
    ap.add_argument("--glob", default="*_daily.csv")
    ap.add_argument("--box", choices=["valley", "value_area"], default="valley")
    ap.add_argument("--min-rows", type=int, default=3)
    ap.add_argument("--max-rows", type=int, default=20)
    ap.add_argument("--min-bars", type=int, default=8, help="حداقل کندل در ماه باکس")
    args = ap.parse_args()

    data_dir = Path(args.data)
    files = sorted(data_dir.glob(args.glob))
    if not files:
        print(f"هیچ فایلی با الگوی {args.glob} در {data_dir} نبود.")
        return 1

    # ─── بارگذاری + حذف تکراری ───
    series = {}
    fingerprints = {}
    collisions = []
    for p in files:
        name = p.name
        for suf in ("_daily.csv", ".csv"):
            if name.endswith(suf):
                name = name[: -len(suf)]
                break
        rows = load_daily(p)
        if len(rows) < 20:
            continue
        fp = hash(tuple((d.isoformat(), round(b.c, 6)) for d, b in rows))
        if fp in fingerprints:
            collisions.append((name, fingerprints[fp]))
            continue
        fingerprints[fp] = name
        key = norm(name)
        if key in series:
            collisions.append((name, "نام یکسان پس از نرمال‌سازی"))
            continue
        series[key] = (name, rows)

    print("=" * 66)
    print(f"باکس: {args.box}  |  نماد یکتا: {len(series)}  |  فایل: {len(files)}")
    if collisions:
        print(f"حذف‌شده به‌خاطر تکرار/برخورد: {len(collisions)}")
        for a, b in collisions[:12]:
            print(f"    {a}  ≡  {b}")
    print("=" * 66)

    # ─── ساخت مشاهدات ───
    # هر مشاهده: (ماهِ تصمیم، نماد، وضعیت، بازده همان ماه)
    obs = []
    for _, (name, rows) in series.items():
        fixed = is_fixed_income(name)
        by_month = defaultdict(list)
        for d, b in rows:
            by_month[month_key(d)].append((d, b))
        months = sorted(by_month)

        for i in range(len(months) - 1):
            m_box, m_fwd = months[i], months[i + 1]
            # ماه‌ها باید پشت‌سرهم باشند
            y, mo = m_box
            nxt = (y + 1, 1) if mo == 12 else (y, mo + 1)
            if m_fwd != nxt:
                continue

            box_bars = [b for _, b in by_month[m_box]]
            if len(box_bars) < args.min_bars:
                continue
            fwd = by_month[m_fwd]
            if len(fwd) < 2:
                continue

            if args.box == "valley":
                vb = valley_box(box_bars, args.min_rows, args.max_rows)
                box = (vb[0], vb[1]) if vb else None
            else:
                box = value_area_box(box_bars)
            if box is None:
                continue

            entry = fwd[0][1].c           # کلوز اولین روز معاملاتی ماه بعد
            exit_ = fwd[-1][1].c          # کلوز آخرین روز همان ماه
            ret = (exit_ - entry) / entry * 100.0
            obs.append(
                {
                    "month": m_fwd,
                    "sym": name,
                    "fixed": fixed,
                    "st": state(entry, box),
                    "ret": ret,
                }
            )

    if not obs:
        print("هیچ مشاهده‌ای ساخته نشد — دادهٔ ماهانه کافی نیست.")
        return 1

    months = sorted({o["month"] for o in obs})
    print(f"\nمشاهده: {len(obs)}  |  ماه متمایز: {len(months)}"
          f"  ({months[0][0]}/{months[0][1]} تا {months[-1][0]}/{months[-1][1]})")
    print(f"⚠️  n مؤثر ≈ {len(months)} (ماه)، نه {len(obs)} — نمادها هم‌زمان و همبسته‌اند.\n")

    def report(rows, title):
        if not rows:
            return
        base = [o["ret"] for o in rows]
        print("─" * 66)
        print(f"{title}   (n={len(base)})")
        print(f"  نرخ پایه (بدون هیچ شرطی): "
              f"{sum(1 for r in base if r > 0)/len(base)*100:5.1f}٪ مثبت"
              f"  |  میانگین {statistics.mean(base):+6.2f}٪")
        for st in ("بالا", "داخل", "زیر"):
            sel = [o["ret"] for o in rows if o["st"] == st]
            if not sel:
                continue
            others = [o["ret"] for o in rows if o["st"] != st]
            t = welch_t(sel, others)
            win = sum(1 for r in sel if r > 0) / len(sel) * 100
            edge_w = win - (sum(1 for r in base if r > 0) / len(base) * 100)
            edge_r = statistics.mean(sel) - statistics.mean(base)
            print(f"  {st:5} n={len(sel):5}  برد {win:5.1f}٪ ({edge_w:+5.1f} واحد)"
                  f"  میانگین {statistics.mean(sel):+6.2f}٪ ({edge_r:+5.2f})"
                  f"  t={t:+5.2f}")

    report([o for o in obs if not o["fixed"]], "بدون درآمد ثابت")
    report([o for o in obs if o["fixed"]], "فقط درآمد ثابت")
    report(obs, "همه (مثل dashboard_monthly.py)")

    # ─── ماه‌به‌ماه: تست صادقانه روی سری ماهانه ───
    print("\n" + "─" * 66)
    print("ماه‌به‌ماه — «بالا» در برابر نرخ پایهٔ همان ماه (بدون درآمد ثابت)")
    print(f"  {'ماه':>9} {'n':>5} {'پایه٪':>8} {'بالا٪':>8} {'مزیت':>7}")
    diffs = []
    for m in months:
        rows = [o for o in obs if o["month"] == m and not o["fixed"]]
        up = [o["ret"] for o in rows if o["st"] == "بالا"]
        if len(rows) < 5 or len(up) < 3:
            continue
        b = statistics.mean([o["ret"] for o in rows])
        u = statistics.mean(up)
        diffs.append(u - b)
        print(f"  {m[0]}/{m[1]:02d} {len(rows):5} {b:+8.2f} {u:+8.2f} {u-b:+7.2f}")

    if len(diffs) >= 2:
        md = statistics.mean(diffs)
        sd = statistics.stdev(diffs)
        t = md / (sd / math.sqrt(len(diffs))) if sd > 0 else float("nan")
        print(f"\n  مزیت میانگین ماهانه: {md:+.2f} واحد درصد"
              f"  |  انحراف {sd:.2f}  |  t={t:+.2f}  (df={len(diffs)-1})")
        print("  ← این t با n=تعداد ماه حساب شده. عددی که با n=تعداد معامله")
        print("     بگیرید چند برابر بزرگ‌تر و **غلط** است.")
    else:
        print("\n  ماه کافی برای تست معنادار نیست. حداقل ۲۴ ماه لازم است.")

    print("\n" + "=" * 66)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
