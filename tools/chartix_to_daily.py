# -*- coding: utf-8 -*-
"""اکسپورتِ ۱D چارتیکس → فرمتِ `data_auto` تا همهٔ ابزارها بخوانندش.

مصطفی اکسپورت‌های بلندتر را یکی‌یکی می‌فرستد (سینرژی از ۲۰۲۴، عیار از
۲۰۱۸). هر بار دستی تبدیل کردنشان اشتباه‌آور است، پس این یک‌بار نوشته
شد.

    python tools/chartix_to_daily.py <دایرکتوری یا فایل> --out data_long

سربرگِ چارتیکس: `<DTYYYYMMDD>,<TIME>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<VOL>`
خروجی: `date,open,high,low,close,volume` — همانی که `load_daily`
می‌خواند.

**کندل‌های تختِ عرضهٔ اولیه حذف می‌شوند.** صندوقِ تازه‌عرضه چند روز با
قیمتِ ثابت و حجمِ عظیم معامله می‌شود (سینرژی سه روز روی ۱۰٬۰۰۰ با ۹۸
میلیون حجم). آن‌ها قیمتِ بازار نیستند و پروفایلِ حجمی را خراب می‌کنند.
"""
import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

# نامِ فایلِ چارتیکس لاتین است؛ نگاشت به نامِ فارسیِ نماد
NAME = {
    "sinrzhi": "سینرژی", "aiar": "عیار", "khrba": "کهربا",
    "nhal": "نهال", "nqran": "نقران", "ahrm": "اهرم",
    "mwj": "موج", "narnj": "نارنج", "dwayks": "دوایکس",
    "twan": "توان", "bidar": "بیدار", "tmshk": "تمشک",
    "doaiks": "دوایکس", "dwaiks": "دوایکس", "kahroba": "کهربا",
    "moj": "موج", "khrb": "کهربا",
    "coppercthd": "گواهی مس", "goldbar": "گواهی شمش طلا",
}


def convert(src, out_dir, min_rows=60):
    rows = []
    with Path(src).open(encoding="utf-8-sig", newline="") as fh:
        rd = csv.reader(fh)
        head = next(rd, None)
        if not head:
            return None
        for r in rd:
            if len(r) < 7:
                continue
            try:
                d = datetime.strptime(r[0].strip(), "%Y%m%d").date()
                o, h, l, c = (float(r[2]), float(r[3]),
                              float(r[4]), float(r[5]))
                v = float(r[6])
            except ValueError:
                continue
            if h <= 0 or c <= 0:
                continue
            rows.append((d, o, h, l, c, v))
    if len(rows) < min_rows:
        return None
    rows.sort()

    # کندلِ تختِ ابتدای عرضه را بینداز — قیمتِ بازار نیست
    i = 0
    while i < len(rows) and rows[i][1] == rows[i][2] == rows[i][3] == rows[i][4]:
        i += 1
    rows = rows[i:]
    if len(rows) < min_rows:
        return None

    stem = Path(src).stem.replace("_1D_CHARTIX", "").replace("_CHARTIX", "")
    sym = NAME.get(stem.lower(), stem)
    out = Path(out_dir) / f"{sym}_daily.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "open", "high", "low", "close", "volume"])
        for d, o, h, l, c, v in rows:
            w.writerow([d.isoformat(), o, h, l, c, v])
    return sym, len(rows), rows[0][0], rows[-1][0], i


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="+")
    ap.add_argument("--out", default="data_long")
    args = ap.parse_args()

    files = []
    for s in args.src:
        p = Path(s)
        if p.is_dir():
            files += sorted(p.rglob("*1D*.csv"))
        elif p.suffix.lower() == ".csv":
            files.append(p)
    if not files:
        print("فایلِ ۱D پیدا نشد.")
        return 1

    for f in files:
        res = convert(f, args.out)
        if not res:
            print(f"  {f.name}: کندلِ کافی نداشت")
            continue
        sym, n, a, b, drop = res
        note = f" · {drop} کندلِ تخت حذف شد" if drop else ""
        print(f"  {sym:<10} {n:>5} کندل · {a} تا {b}{note}")
    print(f"\nخروجی در {args.out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
