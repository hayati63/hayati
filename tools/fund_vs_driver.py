# -*- coding: utf-8 -*-
"""باکسِ خودِ صندوق، یا باکسِ محرک؟ و آیا محرک روی صندوق چیزی اضافه می‌کند؟

سؤال مصطفی: «صندوق‌ها چی می‌گن؟ اگر باکس ماهانه محقق باشه و هفتگی هم
کلوزش بالا باشه، آیا روند هفتگیِ صندوق مثبت بوده؟ یا باید بر اساس تتر و
دلار سنجیده بشن؟ الان تتر ماه قبل مثبت، ماه فعلی مثبت، هفتگی زیر بسته؛
دلار همش مثبت. سه مدل داریم. کدوم روش بازدهی بهتری داره؟»

سه چیزِ جدا اندازه گرفته می‌شود، همه روی **بازدهِ هفتهٔ پیشِ روی صندوق**:

  الف) فقط باکسِ خودِ صندوق        (ماه قبل × ماه جاری × هفتگی)
  ب)  فقط باکسِ محرک              (دلار، تتر، طلای ۱۸ — هر کدام جدا)
  ج)  ترکیب: محرک **روی** باکسِ صندوق چیزی اضافه می‌کند؟

بندِ (ج) سؤالِ اصلی است. اگر صندوقی که خودش هر سه باکسش مثبت است، با
محرکِ مثبت بهتر از محرکِ منفی نباشد، آن‌وقت نگاه‌کردن به تتر وقت تلف
کردن است.

    python3 tools/fund_vs_driver.py
"""
import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

from monthly_backtest import load_daily, is_fixed_income, norm
from vp_box import make_box, state
from calendar_wk import week_key_for
from weekly_backtest import week_key as fund_week

LINKED = {"طلا", "نقره", "کالا_کشاورزی"}
DRIVERS = [("دلار", "دلار", 0), ("تتر", "تتر", 0),
           ("طلای ۱۸", "طلای_۱۸_عیار", 0)]


def fund_obs(data_dir, kind, cats):
    """هر مشاهده: صندوق × هفته، با سه وضعیتش و بازدهِ هفتهٔ بعد."""
    out, seen, fps = [], set(), {}
    for p in sorted(Path(data_dir).glob("*.csv")):
        sym = p.stem.replace("_daily", "").replace("_", " ")
        if cats.get(norm(sym)) not in LINKED or is_fixed_income(sym):
            continue
        rows = load_daily(p)
        if len(rows) < 40:
            continue
        fp = tuple((d.isoformat(), round(b.c, 6)) for d, b in rows)
        if fp in fps or norm(sym) in seen:
            continue
        fps[fp] = 1
        seen.add(norm(sym))
        by_m, by_w = defaultdict(list), defaultdict(list)
        for d, b in rows:
            by_m[(d.year, d.month)].append((d, b))
            by_w[fund_week(d)].append((d, b))
        ks = sorted(by_w)
        for i in range(len(ks) - 1):
            wa, wb = ks[i], ks[i + 1]
            if (wb - wa).days != 7:
                continue
            prev, fwd = by_w[wa], by_w[wb]
            if len(prev) < 3 or len(fwd) < 2:
                continue
            dd, bar = fwd[0]
            px = bar.c
            if px <= 0:
                continue
            wbox = make_box(kind, [x for _, x in prev], prev[-1][1].c)
            pm = ((dd.year - 1, 12) if dd.month == 1
                  else (dd.year, dd.month - 1))
            if wbox is None or pm not in by_m or len(by_m[pm]) < 5:
                continue
            mbox = make_box(kind, [x for _, x in by_m[pm]],
                            by_m[pm][-1][1].c)
            if mbox is None:
                continue
            cur = [b for d2, b in by_m.get((dd.year, dd.month), [])
                   if d2 <= dd]
            cbox = make_box(kind, cur, cur[-1].c) if len(cur) >= 3 else None
            out.append({
                "w": wb, "d0": dd, "sym": sym,
                "ret": (fwd[-1][1].c - px) / px * 100,
                "m": state(px, mbox), "wk": state(px, wbox),
                "c": state(px, cbox) if cbox else "؟"})
    return out, len(seen)


def driver_by_day(path, anchor, kind):
    """dict[روزِ تصمیم] = (ماه قبل، ماه جاری، هفتگی) محرک."""
    rows = load_daily(path)
    wk = week_key_for(anchor)
    by_m, by_w = defaultdict(list), defaultdict(list)
    for d, b in rows:
        by_m[(d.year, d.month)].append((d, b))
        by_w[wk(d)].append((d, b))
    ks = sorted(by_w)
    out = {}
    for i in range(len(ks) - 1):
        wa, wb = ks[i], ks[i + 1]
        if (wb - wa).days != 7:
            continue
        prev, fwd = by_w[wa], by_w[wb]
        if len(prev) < 3 or not fwd:
            continue
        wbox = make_box(kind, [x for _, x in prev], prev[-1][1].c)
        dd, bar = fwd[0]
        px = bar.c
        pm = ((dd.year - 1, 12) if dd.month == 1
              else (dd.year, dd.month - 1))
        if wbox is None or pm not in by_m or len(by_m[pm]) < 5:
            continue
        mbox = make_box(kind, [x for _, x in by_m[pm]], by_m[pm][-1][1].c)
        cur = [b for d2, b in by_m.get((dd.year, dd.month), []) if d2 <= dd]
        cbox = make_box(kind, cur, cur[-1].c) if len(cur) >= 3 else None
        if mbox is None:
            continue
        out[dd] = (state(px, mbox),
                   state(px, cbox) if cbox else "؟",
                   state(px, wbox))
    return out


def cell(rows, pick, by_w, min_n=25):
    """میانگین، نرخ برد، و مزیتِ درون‌هفته‌ای."""
    sel = [o["ret"] for o in rows if pick(o)]
    if len(sel) < min_n:
        return None
    ds = []
    for xs in by_w.values():
        s = [o["ret"] for o in xs if pick(o)]
        if len(s) < 2 or len(xs) < 4:
            continue
        ds.append(statistics.mean(s) - statistics.mean([o["ret"] for o in xs]))
    edge = statistics.mean(ds) if len(ds) >= 3 else None
    t = None
    if len(ds) > 2:
        sd = statistics.stdev(ds)
        t = (edge / (sd / len(ds) ** 0.5)) if sd else None
    return {"n": len(sel), "avg": statistics.mean(sel),
            "win": sum(1 for r in sel if r > 0) / len(sel) * 100,
            "edge": edge, "t": t, "weeks": len(ds)}


def row(label, c, width=30):
    if c is None:
        return f"  {label:<{width}}  — نمونهٔ کم"
    e = f"{c['edge']:>+8.2f}" if c["edge"] is not None else f"{'—':>8}"
    t = f"{c['t']:>6.2f}" if c["t"] is not None else f"{'—':>6}"
    return (f"  {label:<{width}}{c['n']:>7,}{c['win']:>7.0f}٪"
            f"{c['avg']:>+9.2f}٪{e}{t}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_auto")
    ap.add_argument("--drivers", default="data/drivers_daily")
    ap.add_argument("--kind", default="valley_first")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    cats = {}
    tp = root / "data/extracted/TODAY.json"
    if tp.exists():
        for r in json.loads(tp.read_text(encoding="utf-8")):
            cats[norm(r["نماد"])] = r["دسته"]

    obs, nsym = fund_obs(args.data, args.kind, cats)
    if not obs:
        print("مشاهده‌ای ساخته نشد.")
        return 1
    by_w = defaultdict(list)
    for o in obs:
        by_w[o["w"]].append(o)
    base = statistics.mean([o["ret"] for o in obs])
    bwin = sum(1 for o in obs if o["ret"] > 0) / len(obs) * 100

    HDR = (f"  {'':<30}{'n':>7}{'مثبت':>8}{'میانگین':>10}"
           f"{'مزیت':>8}{'t':>6}")
    print("=" * 82)
    print(f"صندوق‌های دلاری (طلا، نقره، کالا) — {len(obs):,} مشاهده"
          f" · {len(by_w)} هفته · {nsym} نماد")
    print(f"نرخ پایه: {base:+.2f}٪ · {bwin:.0f}٪ مثبت")
    print("=" * 82)

    # ── الف) باکسِ خودِ صندوق ──
    print("\n" + "─" * 82)
    print("الف) فقط باکسِ خودِ صندوق")
    print("─" * 82)
    print(HDR)
    A = {
        "هر سه بالا (ماه قبل+جاری+هفتگی)":
            lambda o: o["m"] == "بالا" and o["c"] == "بالا" and o["wk"] == "بالا",
        "ماه قبل + هفتگی بالا":
            lambda o: o["m"] == "بالا" and o["wk"] == "بالا",
        "فقط هفتگی بالا": lambda o: o["wk"] == "بالا",
        "فقط ماه قبل بالا": lambda o: o["m"] == "بالا",
        "هفتگی زیر": lambda o: o["wk"] == "زیر",
        "هر سه زیر":
            lambda o: o["m"] == "زیر" and o["c"] == "زیر" and o["wk"] == "زیر",
    }
    res = {}
    for k, f in A.items():
        c = cell(obs, f, by_w)
        res[f"الف|{k}"] = c
        print(row(k, c))

    # ── ب و ج) محرک‌ها ──
    both = lambda o: o["m"] == "بالا" and o["wk"] == "بالا"     # noqa: E731
    for dname, dfile, anchor in DRIVERS:
        dp = Path(args.drivers) / f"{dfile}_daily.csv"
        if not dp.exists():
            continue
        st = driver_by_day(dp, anchor, args.kind)
        days = sorted(st)

        def dstate(o, idx):
            cand = [d for d in days if d <= o["d0"]]
            return st[cand[-1]][idx] if cand else "؟"

        print("\n" + "─" * 82)
        print(f"ب) فقط باکسِ {dname}  (صندوق نادیده گرفته می‌شود)")
        print("─" * 82)
        print(HDR)
        for lbl, idx in (("ماه قبلِ ", 0), ("ماه جاریِ ", 1), ("هفتگیِ ", 2)):
            for s in ("بالا", "زیر"):
                k = f"{lbl}{dname} = {s}"
                c = cell(obs, lambda o, i=idx, ss=s: dstate(o, i) == ss, by_w)
                res[f"ب|{k}"] = c
                print(row(k, c))

        print("\n" + "─" * 82)
        print(f"ج) صندوق «ماه قبل + هفتگی بالا»  ×  هفتگیِ {dname}")
        print("─" * 82)
        print(HDR)
        cs = {}
        for s in ("بالا", "زیر"):
            k = f"صندوق بالا  +  {dname} هفتگی {s}"
            c = cell(obs, lambda o, ss=s: both(o) and dstate(o, 2) == ss,
                     by_w)
            cs[s] = c
            res[f"ج|{k}"] = c
            print(row(k, c))
        a, b = cs.get("بالا"), cs.get("زیر")
        if a and b:
            print(f"\n    اختلاف (بالا منهای زیر): "
                  f"{a['avg'] - b['avg']:+.2f} واحد میانگین")
            print(f"    → محرکِ {dname} روی باکسِ صندوق "
                  + ("چیزی اضافه می‌کند" if a["avg"] - b["avg"] > 0.5
                     else "چیزی اضافه نمی‌کند"))

    print("\n" + "=" * 82)
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(res, ensure_ascii=False, indent=1,
                       default=lambda x: None), encoding="utf-8")
        print(f"JSON: {Path(args.json_out).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
