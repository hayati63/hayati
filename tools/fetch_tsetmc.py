# -*- coding: utf-8 -*-
"""دانلود روزانه از TSETMC — روی **ماشین خودت**، نه از کانتینر ابری.

چرا اینجا اجرا نمی‌شود: دروازهٔ شبکهٔ این کانتینر به `cdn.tsetmc.com` جواب
۴۰۳ می‌دهد (منع سیاست، نه خطای DNS یا TLS). هیچ کلید و لاگینی این را عوض
نمی‌کند. ولی از مرورگر و از ویندوز خودت کار می‌کند — بند ۵ `CLAUDE.md`.

چرا TSETMC و نه چارتیکس: فید چارتیکس سوکتی است، پس خودکارسازی‌اش یعنی
شبیه‌سازی مرورگر. TSETMC یک GET ساده است و **کل تاریخچه** را می‌دهد، نه
۱۵۰ کندل. همان چیزی که برای بک‌تست منظم لازم است.

    python3 tools/fetch_tsetmc.py --discover        # یک‌بار: ساخت فهرست نماد
    python3 tools/fetch_tsetmc.py                   # هر روز: به‌روزرسانی
    python3 tools/fetch_tsetmc.py --symbols اهرم,موج --force

⚠️ این فایل در این کانتینر **تست نشده** چون شبکه‌اش بسته است. برای همین
هر پاسخ نامنتظر را با کلیدهای واقعی‌اش چاپ می‌کند به‌جای اینکه بی‌صدا رد شود.
"""
import argparse
import csv
import gzip
import io
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

BASE = "https://cdn.tsetmc.com/api"
HIST = BASE + "/ClosingPrice/GetClosingPriceDailyList/{ins}/0"
WATCH = (BASE + "/ClosingPrice/GetMarketWatch?market=0&paperTypes[0]=1"
         "&paperTypes[1]=8&showTraded=false&withBestLimits=false")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")

# نگاشت نامِ فیلد → چیزی که ما لازم داریم. TSETMC بعضی جاها املای متفاوت
# دارد، پس چند اسم برای هر ستون پذیرفته می‌شود.
FIELDS = {
    "date":   ("dEven",),
    "open":   ("priceFirst", "pf"),
    "high":   ("priceMax", "pmx"),
    "low":    ("priceMin", "pmn"),
    # pClosing قیمت **پایانی** است (میانگین وزنی) — همانی که استراتژی
    # رویش بسته شده. pDrCotVal آخرین معامله است.
    "close":  ("pClosing", "pc"),
    "last":   ("pDrCotVal", "pdv"),
    "volume": ("qTotTran5J", "qtj"),
    "value":  ("qTotCap", "qtc"),
}


def _get(url, timeout=30, tries=4):
    """GET با backoff. TSETMC گاهی ۴۰۳ موقت می‌دهد؛ ارزش تکرار دارد."""
    last = None
    for i in range(tries):
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip",
            "Referer": "https://www.tsetmc.com/",
        })
        try:
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=timeout,
                                        context=ctx) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode("utf-8", "replace"))
        except (urllib.error.URLError, urllib.error.HTTPError,
                TimeoutError, json.JSONDecodeError, OSError) as e:
            last = e
            if i < tries - 1:
                time.sleep(2 ** i)
    raise RuntimeError(f"شکست بعد از {tries} تلاش: {url}\n  {last}")


def _pick(row, key):
    for name in FIELDS[key]:
        if name in row:
            return row[name]
    return None


def fetch_history(ins):
    """تاریخچهٔ کامل روزانهٔ یک نماد. خروجی: فهرست dict مرتب بر تاریخ."""
    blob = _get(HIST.format(ins=ins))
    rows = None
    for k in ("closingPriceDaily", "ClosingPriceDaily", "closingPrices"):
        if isinstance(blob, dict) and k in blob:
            rows = blob[k]
            break
    if rows is None:
        keys = list(blob)[:12] if isinstance(blob, dict) else type(blob)
        raise RuntimeError(
            f"ساختار پاسخ شناخته نشد برای ins={ins}.\n"
            f"  کلیدهای واقعی: {keys}\n"
            f"  این یعنی TSETMC فرمتش را عوض کرده — FIELDS را به‌روز کنید.")
    if rows and not any(n in rows[0] for n in FIELDS["close"]):
        raise RuntimeError(
            f"ستون قیمت پایانی پیدا نشد برای ins={ins}.\n"
            f"  کلیدهای ردیف: {sorted(rows[0])[:20]}")

    out = []
    for r in rows:
        d = _pick(r, "date")
        c = _pick(r, "close")
        if not d or not c:
            continue
        d = str(int(d))
        if len(d) != 8:
            continue
        try:
            o = float(_pick(r, "open") or c)
            h = float(_pick(r, "high") or c)
            lo = float(_pick(r, "low") or c)
            c = float(c)
            v = float(_pick(r, "volume") or 0)
        except (TypeError, ValueError):
            continue
        if c <= 0:
            continue
        out.append({"date": f"{d[:4]}-{d[4:6]}-{d[6:]}", "open": o,
                    "high": h, "low": lo, "close": c, "volume": v})
    out.sort(key=lambda x: x["date"])
    return out


def discover(out_path, min_len=2):
    """فهرست نماد → insCode از GetMarketWatch.

    بند ۵ CLAUDE.md: `lva` نماد است، `lvc` نام شرکت. فقط صندوق و سهم
    (paperTypes 1 و 8) خواسته شده.
    """
    blob = _get(WATCH, timeout=60)
    rows = None
    for k in ("marketwatch", "MarketWatch", "value"):
        if isinstance(blob, dict) and k in blob:
            rows = blob[k]
            break
    if rows is None:
        keys = list(blob)[:12] if isinstance(blob, dict) else type(blob)
        raise RuntimeError(f"ساختار GetMarketWatch شناخته نشد. کلیدها: {keys}")

    seen, n = {}, 0
    for r in rows:
        ins = str(r.get("insCode") or r.get("InsCode") or "").strip()
        sym = str(r.get("lva") or r.get("symbol") or "").strip()
        name = str(r.get("lvc") or "").strip()
        if not ins or len(sym) < min_len:
            continue
        if sym in seen:
            continue
        seen[sym] = (ins, name)
        n += 1

    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["نماد", "insCode", "نام"])
        for sym, (ins, name) in sorted(seen.items()):
            w.writerow([sym, ins, name])
    print(f"فهرست نماد نوشته شد: {p.resolve()}  ({n} نماد)")
    print("حالا ستون سوم را نگاه کنید و هرکدام را نمی‌خواهید پاک کنید،")
    print("یا با --symbols فقط همان‌هایی را که می‌خواهید بکشید.")
    return 0


def load_symbols(path):
    rows = {}
    p = Path(path)
    if not p.exists():
        return rows
    with p.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            sym = (r.get("نماد") or r.get("symbol") or "").strip()
            ins = (r.get("insCode") or r.get("ins") or "").strip()
            if sym and ins:
                rows[sym] = ins
    return rows


def write_csv(path, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "open", "high", "low", "close", "volume"])
        for r in rows:
            w.writerow([r["date"], f"{r['open']:g}", f"{r['high']:g}",
                        f"{r['low']:g}", f"{r['close']:g}",
                        f"{r['volume']:g}"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols-file", default="data/symbols.csv")
    ap.add_argument("--symbols", default=None,
                    help="فقط این نمادها، با کاما")
    ap.add_argument("--out", default="data_auto")
    ap.add_argument("--discover", action="store_true",
                    help="فهرست نماد→insCode را از GetMarketWatch بساز")
    ap.add_argument("--sleep", type=float, default=0.8,
                    help="فاصله بین درخواست‌ها؛ کمترش نکنید، rate-limit دارد")
    ap.add_argument("--force", action="store_true",
                    help="حتی اگر فایل امروز به‌روز است دوباره بکش")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    sym_file = (Path(args.symbols_file) if Path(args.symbols_file).is_absolute()
                else root / args.symbols_file)
    out_dir = (Path(args.out) if Path(args.out).is_absolute()
               else root / args.out)

    if args.discover:
        return discover(sym_file)

    symbols = load_symbols(sym_file)
    if not symbols:
        print(f"فهرست نماد خالی است: {sym_file}")
        print("اول یک‌بار اجرا کنید:  python tools/fetch_tsetmc.py --discover")
        return 1
    if args.symbols:
        want = {s.strip() for s in args.symbols.split(",") if s.strip()}
        symbols = {k: v for k, v in symbols.items() if k in want}
        missing = want - set(symbols)
        if missing:
            print(f"⚠️ در فهرست نبود: {'، '.join(sorted(missing))}")

    out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    ok = skip = fail = 0
    new_days = 0
    errors = []

    print(f"{len(symbols)} نماد  →  {out_dir}\n")
    for i, (sym, ins) in enumerate(sorted(symbols.items()), 1):
        fn = out_dir / f"{sym.replace('/', '_')}_daily.csv"
        if fn.exists() and not args.force:
            try:
                tail = fn.read_text(encoding="utf-8").strip().splitlines()[-1]
                if tail.split(",")[0] >= today:
                    skip += 1
                    continue
            except (OSError, IndexError):
                pass
        try:
            rows = fetch_history(ins)
            if not rows:
                raise RuntimeError("تاریخچه خالی برگشت")
            before = 0
            if fn.exists():
                try:
                    before = sum(1 for _ in fn.open(encoding="utf-8")) - 1
                except OSError:
                    before = 0
            write_csv(fn, rows)
            new_days += max(0, len(rows) - before)
            ok += 1
            print(f"  [{i:>3}/{len(symbols)}] {sym:<14} {len(rows):>5} روز"
                  f"  {rows[0]['date']} تا {rows[-1]['date']}")
        except (RuntimeError, OSError) as e:
            fail += 1
            errors.append((sym, str(e).splitlines()[0]))
            print(f"  [{i:>3}/{len(symbols)}] {sym:<14} ✗ {e}",
                  file=sys.stderr)
        time.sleep(args.sleep)

    print(f"\nگرفته شد {ok} · رد شد {skip} (امروز به‌روز بود) · شکست {fail}")
    if new_days:
        print(f"{new_days} کندل تازه اضافه شد.")
    if errors:
        print("\nشکست‌ها:")
        for sym, msg in errors[:15]:
            print(f"    {sym:<14} {msg}")
    return 1 if (fail and not ok) else 0


if __name__ == "__main__":
    raise SystemExit(main())
