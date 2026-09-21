# -*- coding: utf-8 -*-
"""تست آفلاین پارسر TSETMC — با پاسخ ساختگی به شکل مستند."""
import sys, json, types
sys.path.insert(0, "tools")
import fetch_tsetmc as F

SAMPLE = {"closingPriceDaily": [
    {"insCode": "17914401175772326", "dEven": 20260918, "hEven": 122959,
     "priceFirst": 69000, "priceMax": 70100, "priceMin": 68500,
     "pClosing": 69540, "pDrCotVal": 69800, "priceYesterday": 68900,
     "zTotTran": 41233, "qTotTran5J": 512345678, "qTotCap": 3.5e13},
    {"insCode": "17914401175772326", "dEven": 20260920, "hEven": 122959,
     "priceFirst": 69600, "priceMax": 71200, "priceMin": 69100,
     "pClosing": 70586, "pDrCotVal": 70900, "priceYesterday": 69540,
     "zTotTran": 39001, "qTotTran5J": 498765432, "qTotCap": 3.4e13},
    # ردیف خراب: باید رد شود نه اینکه برنامه را بیندازد
    {"insCode": "x", "dEven": 20260921, "pClosing": 0},
    {"insCode": "x", "dEven": None, "pClosing": 100},
]}

ALT = {"closingPriceDaily": [
    {"dEven": 20260920, "pf": 100, "pmx": 110, "pmn": 95, "pc": 104,
     "qtj": 1000},
]}

BAD = {"somethingElse": []}
NOCLOSE = {"closingPriceDaily": [{"dEven": 20260920, "zzz": 1}]}

def run(name, blob, expect_rows=None, expect_err=None):
    F._get = lambda url, timeout=30, tries=4: blob
    try:
        rows = F.fetch_history("x")
    except RuntimeError as e:
        if expect_err and expect_err in str(e):
            print(f"  ✓ {name}: خطای درست داد — {str(e).splitlines()[0][:60]}")
            return True
        print(f"  ✗ {name}: خطای نامنتظر — {e}")
        return False
    if expect_err:
        print(f"  ✗ {name}: باید خطا می‌داد ولی {len(rows)} ردیف برگرداند")
        return False
    if expect_rows is not None and len(rows) != expect_rows:
        print(f"  ✗ {name}: {len(rows)} ردیف، انتظار {expect_rows}")
        return False
    print(f"  ✓ {name}: {len(rows)} ردیف")
    return True

print("پارسر TSETMC — تست آفلاین\n")
ok = True
ok &= run("پاسخ استاندارد", SAMPLE, expect_rows=2)
ok &= run("املای کوتاه فیلدها", ALT, expect_rows=1)
ok &= run("ساختار ناشناخته", BAD, expect_err="ساختار پاسخ شناخته نشد")
ok &= run("بدون ستون قیمت", NOCLOSE, expect_err="ستون قیمت پایانی پیدا نشد")

# محتوای ردیف‌ها درست است؟
F._get = lambda url, timeout=30, tries=4: SAMPLE
rows = F.fetch_history("x")
exp = {"date": "2026-09-18", "open": 69000.0, "high": 70100.0,
       "low": 68500.0, "close": 69540.0, "volume": 512345678.0}
if rows[0] == exp:
    print("  ✓ نگاشت ستون‌ها درست — pClosing به close رفت، نه pDrCotVal")
else:
    print(f"  ✗ نگاشت غلط:\n     گرفتیم {rows[0]}\n     انتظار {exp}")
    ok = False
if rows[0]["date"] < rows[1]["date"]:
    print("  ✓ مرتب‌سازی صعودی")
else:
    print("  ✗ مرتب‌سازی غلط"); ok = False

# نوشتن و خواندن دوباره با همان لودری که بک‌تست استفاده می‌کند
from pathlib import Path
tmp = Path("/tmp/claude-0/-home-user-hayati/b39b98cb-0ef5-5174-b992-4a6d824e9b1b/scratchpad/_t.csv")
F.write_csv(tmp, rows)
from monthly_backtest import load_daily
back = load_daily(tmp)
if len(back) == 2 and abs(back[-1][1].c - 70586) < 1e-6:
    print("  ✓ خروجی با load_daily بک‌تست خوانده می‌شود")
else:
    print(f"  ✗ load_daily نخواند: {back}"); ok = False

print("\n" + ("✓ همه گذشت" if ok else "✗ مشکل هست"))
sys.exit(0 if ok else 1)
