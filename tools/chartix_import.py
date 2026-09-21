# -*- coding: utf-8 -*-
"""تبدیل خروجی درون‌روزی چارتیکس (m5/m15) به کندل روزانه.

چرا این لازم است: دادهٔ روزانهٔ `data_auto` فقط ۱۵۰ کندل است — حدود ۱۱ ماه.
فایل‌های درون‌روزی چارتیکس تا ۲۰۲۴ عقب می‌روند. جمع‌کردنشان به روز، تاریخ را
دو تا سه برابر می‌کند، و کمبودِ **تعمیم‌پذیری** دقیقاً همان چیزی است که با
داده‌ٔ بیشتر حل می‌شود.

⚠️ یک قید که باید دیده شود: کلوزِ آخرین کندلِ روز **آخرین معامله** است، نه
**قیمت پایانی**. قیمت پایانی میانگین وزنی است و همان چیزی است که TSETMC و
دادهٔ روزانه گزارش می‌کنند. این دو یکی نیستند. `--check` روی دورهٔ هم‌پوشانی
مقایسه می‌کند تا اندازهٔ اختلاف معلوم شود، نه اینکه فرض شود صفر است.

    python3 tools/chartix_import.py --in پوشه --out data_intraday
    python3 tools/chartix_import.py --in پوشه --check data_auto
"""
import argparse
import csv
import re
import statistics
from collections import OrderedDict
from pathlib import Path

# نام فایل چارتیکس → نام نمادی که در دادهٔ روزانه هست
ALIAS = {
    "ahrm": "اهرم",
    "sinrzhi": "سینرژی",
    "aiar": "عیار",
    "bidar": "بیدار",
    "doaiks": "دوایکس",
    "goldbar": "گواهی_شمش_طلا",
    "coppercthd": "مس",
    "fx": "نفت_برنت",          # FX_UKOIL → پس از حذف UKOIL
    "fx_ukoil": "نفت_برنت",
    "ukoil": "نفت_برنت",
    "oanda_xagusd": "اونس_نقره",
    "xagusd": "اونس_نقره",
    "oanda_xauusd": "اونس_طلا",
    "silverbar": "گواهی_شمش_نقره",
    "usdtirt": "تتر",
    "tdt": "دلار",
    "shakhs_kl": "شاخص_کل",
    "shakhs_kl_ghimt_hm_ozn": "شاخص_هم‌وزن",
    "shakhs_kl_ghimt_hm_ozn_": "شاخص_هم‌وزن",
    "xauusd": "اونس_طلا",
    "silverbar": "گواهی_شمش_نقره",
    "gold18": "طلای_۱۸_عیار",
    "usd": "دلار",
    "usdt": "تتر",
}


TF_TOKENS = {"1D", "1W", "1M", "H1", "H4", "D1", "W1", "MN1"}


def _is_tf(part):
    p = part.strip()
    if p.upper() in TF_TOKENS:
        return True
    return len(p) > 1 and p[0].lower() == "m" and p[1:].isdigit()


def sym_of(stem):
    """`bidar_tadil_m15_CHARTIX` → `بیدار`، `sinrzhi_1D_CHARTIX` → `سینرژی`.

    تکه‌های نام جدا می‌شوند و هرچه تایم‌فریم یا برچسب است دور ریخته می‌شود.
    قبلاً با `replace` روی رشته بود و `_1D_` وسط نام را نمی‌گرفت، پس
    `sinrzhi_1D` می‌شد `sinrzhid` و هر تایم‌فریم یک «نماد» جدا می‌ساخت.
    «تدیل» یعنی تعدیل‌شده.
    """
    parts = [p for p in stem.split("_") if p]
    keep = [p for p in parts
            if not _is_tf(p)
            and p.lower() not in ("chartix", "tadil", "adj", "1")]
    # نام فایل گاهی فاصله و پرانتز دارد («shakhs kl ghimt (hm ozn)»),
    # پس کلید نرمال می‌شود تا با ALIAS بخواند.
    key = "_".join(keep).lower()
    key = re.sub(r"[()\[\]]", "", key)
    key = re.sub(r"[\s_]+", "_", key).strip("_")
    return ALIAS.get(key, key)


def to_daily(path):
    """OHLCV روزانه از کندل‌های درون‌روزی. خروجی: OrderedDict تاریخ→dict."""
    days = OrderedDict()
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            d = (r.get("<DTYYYYMMDD>") or "").strip()
            if len(d) != 8 or not d.isdigit():
                continue
            try:
                o, h = float(r["<OPEN>"]), float(r["<HIGH>"])
                lo, c = float(r["<LOW>"]), float(r["<CLOSE>"])
                v = float(r.get("<VOL>") or 0)
            except (TypeError, ValueError, KeyError):
                continue
            if c <= 0:
                continue
            if d not in days:
                days[d] = {"open": o, "high": h, "low": lo, "close": c,
                           "volume": v, "bars": 1}
            else:
                e = days[d]
                e["high"] = max(e["high"], h)
                e["low"] = min(e["low"], lo)
                e["close"] = c          # آخرین کندل روز
                e["volume"] += v
                e["bars"] += 1
    return days


def tf_of(stem):
    """تایم‌فریم را از نام فایل بیرون می‌کشد: `sinrzhi_1D_CHARTIX` → `1D`."""
    for part in stem.split("_"):
        if _is_tf(part):
            return (part.upper() if part.upper() in TF_TOKENS
                    else part.lower())
    return "?"


def pick_best(files, want_tf="1D"):
    """برای هر نماد یک فایل انتخاب می‌کند.

    اگر خودِ چارتیکس فایل `1D` داده باشد، همان بهتر است: کندل روزانهٔ آمادهٔ
    منبع، نه چیزی که ما از درون‌روزی سرهم کرده‌ایم. وگرنه بزرگ‌ترین
    تایم‌فریمِ موجود جمع می‌شود به روز.
    """
    cand = {}
    for f in files:
        days = to_daily(f)
        if not days:
            continue
        cand.setdefault(sym_of(f.stem), []).append((tf_of(f.stem), f, days))

    best = {}
    for sym, lst in cand.items():
        exact = [x for x in lst if x[0].upper() == want_tf.upper()]
        pool = exact if (exact and want_tf.lower() != "auto") else lst
        tf, f, days = max(pool, key=lambda x: len(x[2]))
        best[sym] = (f, days, tf)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True,
                    help="پوشهٔ CSVهای چارتیکس")
    ap.add_argument("--glob", default="**/*CHARTIX*.csv",
                    help="بازگشتی است — بعضی خروجی‌های چارتیکس csv/ و txt/ و "
                         "prn/ جدا دارند")
    ap.add_argument("--tf", default="1D",
                    help="تایم‌فریمی که برداشته شود: 1D یا H4 یا H1 یا m15… . "
                         "«auto» یعنی هر چه بیشترین روز را بدهد")
    ap.add_argument("--out", default=None,
                    help="پوشهٔ خروجی روزانه؛ ندهید یعنی فقط گزارش")
    ap.add_argument("--check", default=None,
                    help="پوشهٔ دادهٔ روزانهٔ موجود، برای مقایسهٔ هم‌پوشانی")
    args = ap.parse_args()

    files = sorted(Path(args.inp).glob(args.glob))
    if not files:
        print(f"فایلی با الگوی {args.glob} پیدا نشد.")
        return 1

    best = pick_best(files, args.tf)
    empty = [f.name for f in files if not to_daily(f)]
    if empty:
        print(f"⚠️ {len(empty)} فایل خالی بود (فقط سرستون):")
        for n in empty:
            print(f"    {n}")
        print()

    print(f"{'نماد':<14}{'تایم‌فریم':<10}{'منبع':<30}{'روز':>6}  بازه")
    for sym, (f, days, tf) in sorted(best.items()):
        ds = list(days)
        mark = "" if tf.upper() == args.tf.upper() else "  ←جمع‌شده"
        print(f"{sym:<14}{tf:<10}{f.name:<30}{len(days):>6}  "
              f"{ds[0]} تا {ds[-1]}{mark}")

    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        for sym, (_, days, _tf) in best.items():
            p = out / f"{sym}_daily.csv"
            with p.open("w", encoding="utf-8", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["date", "open", "high", "low", "close", "volume"])
                for d, e in days.items():
                    w.writerow([f"{d[:4]}-{d[4:6]}-{d[6:]}",
                                f"{e['open']:g}", f"{e['high']:g}",
                                f"{e['low']:g}", f"{e['close']:g}",
                                f"{e['volume']:g}"])
        print(f"\nنوشته شد: {out.resolve()}  ({len(best)} فایل)")

    if args.check:
        print("\n" + "─" * 72)
        print("مقایسهٔ هم‌پوشانی — کلوزِ آخرین کندل در برابر کلوزِ دادهٔ روزانه")
        print("  اولی «آخرین معامله» است، دومی معمولاً «قیمت پایانی» (میانگین")
        print("  وزنی). اگر اختلاف بزرگ باشد، این دو را نباید به هم چسباند.\n")
        base = Path(args.check)
        print(f"  {'نماد':<12}{'روز مشترک':>10}{'میانه|Δ|':>10}"
              f"{'میانگین|Δ|':>12}{'بیشینه|Δ|':>11}{'>۱٪':>7}")
        for sym, (_, days, _tf) in sorted(best.items()):
            bp = base / f"{sym}_daily.csv"
            if not bp.exists():
                print(f"  {sym:<12}— دادهٔ روزانه ندارد")
                continue
            daily = {}
            with bp.open(encoding="utf-8-sig", newline="") as fh:
                for r in csv.DictReader(fh):
                    try:
                        daily[r["date"].replace("-", "")] = float(r["close"])
                    except (KeyError, ValueError):
                        pass
            diffs = [abs(days[d]["close"] - c) / c * 100
                     for d, c in daily.items() if d in days and c > 0]
            if not diffs:
                print(f"  {sym:<12}— روز مشترکی نبود")
                continue
            over = sum(1 for x in diffs if x > 1.0)
            print(f"  {sym:<12}{len(diffs):>10}{statistics.median(diffs):>10.2f}"
                  f"{statistics.mean(diffs):>12.2f}{max(diffs):>11.2f}"
                  f"{over:>7}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
