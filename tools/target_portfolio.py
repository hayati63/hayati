# -*- coding: utf-8 -*-
"""پرتفوی هدف — امتیاز هر نماد، وزنش، و فاصله تا پرتفوی فعلی.

همه‌چیز از `data_auto` می‌آید، نه از رونویسی داشبورد. هر روز می‌شود اجرایش
کرد؛ عددها با کلوزِ همان روز به‌روز می‌شوند.

**دو باکس، دو کار.** این تفکیک عمدی است و در `docs/REVIEW` اندازه گرفته شده:

  باکس ماه قبل   →  **سیگنال**: چه چیزی بخریم. مزیت +۰٫۷۶ واحد٪، p=۰٫۰۰۰۴.
  باکس ماه جاری  →  **استاپ**: کجا بیرون بیاییم. به‌عنوان سیگنال مزیتی
                    نداشت (+۰٫۰۱)، ولی نزدیک‌ترین حمایتِ ساختاری است و
                    فاصله تا آن، همان چیزی است که سایز را تعیین می‌کند.

**امتیاز** سه تکه دارد:
  ۱. سابقهٔ خود نماد (میانگین بازده ماه‌های «بالای باکس»)، منقبض‌شده به
     میانگین گروهش — تا نمادی با ۲ ماه سابقه مثل نمادی با ۹ ماه وزن نگیرد.
  ۲. جای فعلی نسبت به باکس ماه قبل.
  ۳. جریمهٔ نقدشوندگی، اگر خروج بیش از یک روز طول بکشد.

**سایز** = امتیاز ÷ بیشینهٔ(ریسک، کف) با سقف روی هر نماد و هر گروه.
تقسیم بر ریسک عمدی است: دادهٔ خودتان می‌گوید بازده با ریسک بالا می‌رود ولی
**بازده به ازای هر واحد ریسک پایین می‌آید** — جدول `--why` این را نشان می‌دهد.
"""
import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

from monthly_backtest import load_daily, is_fixed_income, norm
from vp_box import make_box, state
from drivers import group_of, EXPOSURE

# دو عاملی که واقعاً از هم جدا حرکت می‌کنند. داخل مجموعهٔ سهام همبستگی بالای
# ۰٫۹ است، پس سهامی و شاخصی و اهرمی و بخشی **یک شرط‌بندی‌اند**، نه چهار تا.
FACTOR = {
    "طلا": "فلزات", "نقره": "فلزات", "فلزی": "فلزات",
    "کالا_کشاورزی": "کالا",
    "املاک": "املاک",
}


def factor_of(group):
    return FACTOR.get(group, "سهام‌محور")

FIXED_HINT = ("درآمد", "ثابت", "کوتاه", "سپر", "اعتماد", "پاداش")


def load_universe(data_dir, glob, min_bars):
    """نماد → کندل‌های روزانه، با حذف تکراری و برخورد نام."""
    out, seen_fp, seen_norm = {}, {}, {}
    for p in sorted(Path(data_dir).glob(glob)):
        name = p.name
        for suf in ("_daily.csv", ".csv"):
            if name.endswith(suf):
                name = name[: -len(suf)]
                break
        name = name.replace("_", " ")
        rows = load_daily(p)
        if len(rows) < min_bars:
            continue
        fp = tuple((d.isoformat(), round(b.c, 6)) for d, b in rows)
        if fp in seen_fp or norm(name) in seen_norm:
            continue
        seen_fp[fp] = seen_norm[norm(name)] = name
        out[name] = rows
    return out


def monthly_frames(rows):
    by_m = defaultdict(list)
    for d, b in rows:
        by_m[(d.year, d.month)].append((d, b))
    return by_m


def symbol_record(rows, kind, min_rows, max_rows):
    """سابقهٔ نماد + وضعیت امروز، هر دو از یک منبع."""
    by_m = monthly_frames(rows)
    ms = sorted(by_m)
    if len(ms) < 3:
        return None

    hist = []
    for i in range(len(ms) - 1):
        a, b = ms[i], ms[i + 1]
        nxt = (a[0] + 1, 1) if a[1] == 12 else (a[0], a[1] + 1)
        if b != nxt or len(by_m[a]) < 5 or len(by_m[b]) < 2:
            continue
        bars = [x for _, x in by_m[a]]
        box = make_box(kind, bars, bars[-1].c, min_rows, max_rows)
        if box is None:
            continue
        fwd = by_m[b]
        entry, exit_ = fwd[0][1].c, fwd[-1][1].c
        hist.append({"m": b, "st": state(entry, box),
                     "ret": (exit_ - entry) / entry * 100.0})

    cur_m = ms[-1]
    prev_m = ms[-2]
    prev_bars = [x for _, x in by_m[prev_m]]
    cur_bars = [x for _, x in by_m[cur_m]]
    if len(prev_bars) < 5 or not cur_bars:
        return None
    close = cur_bars[-1].c
    last_d = by_m[cur_m][-1][0]

    pbox = make_box(kind, prev_bars, prev_bars[-1].c, min_rows, max_rows)
    cbox = (make_box(kind, cur_bars, close, min_rows, max_rows)
            if len(cur_bars) >= 3 else None)

    vols = [b.v for _, b in rows[-20:] if b.v]
    return {
        "close": close, "date": last_d, "hist": hist,
        "pbox": pbox, "cbox": cbox,
        "pst": state(close, pbox) if pbox else "—",
        "cst": state(close, cbox) if cbox else "—",
        # ریسک سیگنال: فاصله تا کف باکسی که سیگنال از آن آمده
        "prisk": (close - pbox[0]) / close * 100 if pbox else None,
        # ریسک استاپ: فاصله تا نزدیک‌ترین حمایت ساختاری امروز
        "crisk": (close - cbox[0]) / close * 100 if cbox else None,
        "med_vol": statistics.median(vols) if vols else None,
        "months": len(by_m),
    }


def shrink(raw, n, prior, k):
    """جیمز-استاین سادهٔ وزن‌دار: n کم یعنی نزدیک‌تر به میانگین گروه."""
    return (n * raw + k * prior) / (n + k)


def _fill(members, budget, max_weight, max_group, per_symbol_cap=None):
    """وزن‌دهی نسبت‌به‌`raw_w` زیر سقف نماد و سقف گروه، با پرکردن تدریجی.

    هرچه به سقف بخورد ثابت می‌شود و بقیه روی باقی‌ماندهٔ بودجه دوباره
    نسبت‌گیری می‌شوند. سقف گروه اعضای تثبیت‌شده را هم می‌شمارد، وگرنه نمادی
    که زودتر به سقف وزن خورد از جمع گروه بیرون می‌ماند و سقف می‌شکند.

    اگر سقف‌ها اجازه ندهند بودجه تمام مصرف شود، باقی‌مانده نقد می‌ماند —
    شکستن سقف بدتر از نقد نگه‌داشتن است.
    """
    # سقف‌ها درصدِ **کل سبد**اند، نه درصدِ سلّه. مقیاس‌کردنشان با بودجهٔ
    # سلّه، سقف را داخل سلّهٔ کوچک‌تر بی‌معنا تنگ می‌کند و سبد را بی‌دلیل
    # نقد نگه می‌دارد.
    cap_g = min(max_group, budget)
    per_symbol_cap = per_symbol_cap or {}

    def cap_of(r):
        return min(max_weight, budget, per_symbol_cap.get(r["sym"], 1e9))
    fixed, left = {}, float(budget)
    for _ in range(200):
        free = [r for r in members if r["sym"] not in fixed]
        if not free or left <= 1e-9:
            break
        tot = sum(r["raw_w"] for r in free)
        if tot <= 0:
            break
        prop = {r["sym"]: left * r["raw_w"] / tot for r in free}

        hit = [r for r in free if prop[r["sym"]] > cap_of(r) + 1e-9]
        if hit:
            for r in hit:
                fixed[r["sym"]] = cap_of(r)
            left = budget - sum(fixed.values())
            continue

        gs = defaultdict(float)
        for r in members:
            gs[r["group"]] += (fixed[r["sym"]] if r["sym"] in fixed
                               else prop.get(r["sym"], 0.0))
        over = [g for g, v in gs.items() if v > cap_g + 1e-9]
        if over:
            g = max(over, key=lambda g: gs[g])
            scale = cap_g / gs[g]
            for r in members:
                if r["group"] != g:
                    continue
                cur = (fixed[r["sym"]] if r["sym"] in fixed
                       else prop.get(r["sym"], 0.0))
                fixed[r["sym"]] = cur * scale
            left = budget - sum(fixed.values())
            continue

        for r in free:
            fixed[r["sym"]] = prop[r["sym"]]
        break
    return fixed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_auto")
    ap.add_argument("--glob", default="*.csv")
    ap.add_argument("--holdings", default="data/holdings.txt")
    ap.add_argument("--liquidity", default="data/liquidity.json")
    ap.add_argument("--capital", type=float, default=None,
                    help="سرمایه به ریال؛ ندهید یعنی ارزش پرتفوی فعلی")
    ap.add_argument("--core", type=float, default=60.0,
                    help="سهم هستهٔ ماهانه از کل سرمایه (٪). CLAUDE.md بند ۲: "
                         "ماهانه ۶۰٪ · هفتگی ۳۰٪ · دیلی ۱۰٪. این ابزار فقط "
                         "هسته را می‌چیند؛ ۱۰۰ یعنی کل سرمایه")
    ap.add_argument("--kind", default="valley_first")
    ap.add_argument("--min-rows", type=int, default=3)
    ap.add_argument("--max-rows", type=int, default=20)
    ap.add_argument("--min-bars", type=int, default=40)
    ap.add_argument("--n", type=int, default=12, help="حداکثر تعداد پوزیشن")
    ap.add_argument("--w-eq", type=float, default=56.0,
                    help="وزن سلّهٔ سهام‌محور (٪). بقیه به فلزات می‌رود. "
                         "۵۶ از وزن کمینه‌واریانس روی دادهٔ خودتان می‌آید؛ "
                         "۱۰۰ یعنی سلّه‌بندی را خاموش کن")
    ap.add_argument("--max-weight", type=float, default=12.0)
    ap.add_argument("--max-group", type=float, default=35.0)
    ap.add_argument("--risk-floor", type=float, default=1.5,
                    help="کف ریسک در سایزینگ (٪) — جلوی استاپ ۰٫۱٪ را می‌گیرد")
    ap.add_argument("--max-exit-days", type=float, default=2.0)
    ap.add_argument("--participation", type=float, default=0.20,
                    help="چند درصد از حجم یک روز را خودت می‌توانی باشی")
    ap.add_argument("--min-n", type=int, default=3,
                    help="کمینه تعداد ماهِ «بالای باکس» در سابقه؛ کمتر از این "
                         "یعنی امتیاز عمدتاً تصادف است")
    ap.add_argument("--shrink-k", type=float, default=3.0)
    ap.add_argument("--include-fixed", action="store_true")
    ap.add_argument("--categories", default=None,
                    help="JSON دستهٔ نمادها؛ پیش‌فرض data/extracted/TODAY.json "
                         "کنار خود مخزن، نه کنار پوشهٔ جاری")
    ap.add_argument("--why", action="store_true",
                    help="جدول ریسک در برابر بازده را هم چاپ کن")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args()

    uni = load_universe(args.data, args.glob, args.min_bars)
    if not uni:
        print(f"دادهٔ کافی در {args.data} نبود.")
        return 1

    liq = {}
    lp = Path(args.liquidity)
    if lp.exists() and lp.suffix == ".json":
        liq = json.loads(lp.read_text(encoding="utf-8")).get("rows", {})

    holds = {}
    hp = Path(args.holdings)
    if hp.exists():
        import re
        for line in hp.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^(.+?)[\s,،\t]+([\d.,]+)$", line)
            if m:
                try:
                    k = m.group(1).strip()
                    holds[k] = holds.get(k, 0) + float(
                        m.group(2).replace(",", "").replace("،", ""))
                except ValueError:
                    pass

    # ── ساخت رکورد هر نماد ──
    recs = {}
    for sym, rows in uni.items():
        if is_fixed_income(sym) and not args.include_fixed:
            continue
        r = symbol_record(rows, args.kind, args.min_rows, args.max_rows)
        if r:
            r["sym"] = sym
            recs[sym] = r
    if not recs:
        print("هیچ نمادی رکورد کامل نداد.")
        return 1

    # ── گروه هر نماد ──
    # مسیر پیش‌فرض نسبت به ریشهٔ مخزن حل می‌شود، نه پوشهٔ جاری. قبلاً نسبی
    # بود و اجرا از داخل tools/ بی‌صدا شکست می‌خورد: همه‌چیز «سهامی» می‌شد و
    # سقف گروه هیچ‌وقت فعال نمی‌شد.
    root = Path(__file__).resolve().parent.parent
    tp = Path(args.categories) if args.categories else root / "data/extracted/TODAY.json"
    cat = {}
    if tp.exists():
        for row in json.loads(tp.read_text(encoding="utf-8")):
            cat[norm(row["نماد"])] = row["دسته"]
    else:
        print(f"⚠️ فایل دسته‌ها پیدا نشد: {tp}")
    missing = []
    for sym, r in recs.items():
        c = cat.get(norm(sym))
        if c is None:
            missing.append(sym)
            c = "سهامی"
        r["cat"] = c
        r["group"] = group_of(sym, c)
    if missing:
        print(f"⚠️ {len(missing)} نماد دسته نداشت و «سهامی» فرض شد: "
              + "، ".join(missing[:8]) + ("…" if len(missing) > 8 else ""))

    # ── میانگین گروه، برای انقباض ──
    gsum = defaultdict(list)
    for r in recs.values():
        up = [h["ret"] for h in r["hist"] if h["st"] == "بالا"]
        r["n_up"] = len(up)
        r["raw"] = statistics.mean(up) if up else None
        r["win"] = (sum(1 for x in up if x > 0) / len(up) * 100) if up else None
        if r["raw"] is not None:
            gsum[r["group"]].append(r["raw"])
    gmean = {g: statistics.mean(v) for g, v in gsum.items() if v}
    allmean = statistics.mean([x for v in gsum.values() for x in v]) or 0.0

    # ── نرخ پایه: بازده همهٔ نماد-ماه‌ها، برای خواندن «مزیت» ──
    allret = [h["ret"] for r in recs.values() for h in r["hist"]]
    base = statistics.mean(allret) if allret else 0.0

    for r in recs.values():
        prior = gmean.get(r["group"], allmean)
        r["score_hist"] = (shrink(r["raw"], r["n_up"], prior, args.shrink_k)
                           if r["raw"] is not None else prior)
        ld = liq.get(r["sym"]) or liq.get(r["sym"].replace(" ", "_")) or {}
        r["exit_days"] = ld.get("exit_days")
        r["med_value"] = ld.get("med_value")

    # ── امتیاز نهایی ──
    for r in recs.values():
        s = r["score_hist"] - base          # مزیت نسبت به نرخ پایه
        if r["pst"] != "بالا":              # سیگنالِ دارای شواهد
            s -= 6.0
        if r["cst"] == "زیر":               # زیر حمایتِ امروز
            s -= 2.0
        ed = r["exit_days"]
        if ed is not None and ed > args.max_exit_days:
            s -= 4.0 * math.log1p(ed - args.max_exit_days)
        r["score"] = s

    # ── انتخاب و وزن‌دهی ──
    pool = [r for r in recs.values()
            if r["pst"] == "بالا" and r["score"] > 0 and r["n_up"] >= args.min_n]
    pool.sort(key=lambda r: -r["score"])
    thin = [r["sym"] for r in recs.values()
            if r["pst"] == "بالا" and r["score"] > 0 and r["n_up"] < args.min_n]
    if thin:
        print(f"کنار گذاشته شد — کمتر از {args.min_n} ماه سابقه: "
              + "، ".join(sorted(thin)[:10])
              + ("…" if len(thin) > 10 else ""))

    # ── سلّه‌بندی ──
    # امتیازِ خام تقریباً همیشه سهام‌محور را برنده می‌کند، چون در این یازده
    # ماه سهام بهتر بوده. ولی «بهتر بوده» با «سبد بهتری می‌سازد» یکی نیست:
    # وقتی همبستگی دو عامل منفی است، سلّهٔ ضعیف‌تر نوسان کل را کم می‌کند.
    # پس بودجه اول بین دو عامل تقسیم می‌شود و امتیاز فقط **داخل** هر عامل
    # انتخاب می‌کند.
    for r in recs.values():
        r["factor"] = factor_of(r["group"])

    budgets = ({"سهام‌محور": 100.0} if args.w_eq >= 99.99
               else {"سهام‌محور": args.w_eq, "فلزات": 100.0 - args.w_eq})
    per_group = max(1, math.ceil(args.n * args.max_group / 100))
    picks, gcount = [], defaultdict(int)
    for fac, bud in budgets.items():
        want = max(1, round(args.n * bud / 100))
        taken = 0
        for r in pool:
            if r["factor"] != fac or taken >= want:
                continue
            if gcount[r["group"]] >= per_group:
                continue
            risk = max(r["crisk"] if r["crisk"] is not None else 99,
                       args.risk_floor)
            r["size_risk"] = risk
            r["raw_w"] = r["score"] / risk
            picks.append(r)
            gcount[r["group"]] += 1
            taken += 1
        if taken < want:
            print(f"⚠️ سلّهٔ «{fac}»: فقط {taken} نماد از {want} واجد شرط بود "
                  f"(بالای باکس ماه قبل و امتیاز مثبت).")

    # وزن‌دهی: پرکردن تدریجی. هرچه به سقف خورد ثابت می‌شود و بقیه روی
    # باقی‌ماندهٔ بودجه دوباره نسبت‌گیری می‌شوند. اگر سقف‌ها اجازه ندهند به
    # ۱۰۰٪ برسیم، باقی‌مانده نقد می‌ماند — بهتر از شکستن سقف.
    capital0 = args.capital
    if capital0 is None:
        capital0 = sum(n * recs[sy]["close"]
                       for sy, n in holds.items() if sy in recs) or 1e9

    # ── سقف نقدشوندگی، روی **سایز هدف** ──
    # سؤال درست «از پوزیشن فعلی چند روز طول می‌کشد بیرون بیایم» نیست؛
    # «اگر این‌قدر بخرم، چند روز طول می‌کشد بیرون بیایم» است. اولی دربارهٔ
    # دیروز است، دومی دربارهٔ تصمیمی که الان گرفته می‌شود. این سقف به‌جای
    # بریدنِ بعدی، همان اول به _fill داده می‌شود تا بازپخشش سقف گروه را
    # نشکند.
    liq_cap = {}
    for r in picks:
        if not r["med_vol"]:
            continue
        max_units = r["med_vol"] * args.participation * args.max_exit_days
        liq_cap[r["sym"]] = (max_units * r["close"]
                             / (capital0 * args.core / 100) * 100)

    fixed = {}
    for fac, bud in budgets.items():
        members = [r for r in picks if r["factor"] == fac]
        if not members:
            continue
        fixed.update(_fill(members, bud, args.max_weight, args.max_group,
                           liq_cap))
    for r in picks:
        r["w"] = fixed.get(r["sym"], 0.0)

    capital = args.capital
    cur_val = sum(n * recs[s]["close"] for s, n in holds.items() if s in recs)
    if capital is None:
        capital = cur_val or 1e9

    core_cap0 = capital * args.core / 100
    for r in picks:
        if r["med_vol"]:
            units = core_cap0 * r["w"] / 100 / r["close"]
            r["tgt_exit_days"] = units / (r["med_vol"] * args.participation)
            r["liq_clipped"] = (r["sym"] in liq_cap
                                and r["w"] >= liq_cap[r["sym"]] - 1e-6)
    cash_w = max(0.0, 100.0 - sum(r["w"] for r in picks))

    # ── چاپ ──
    d = max(r["date"] for r in recs.values())
    print("=" * 74)
    print(f"پرتفوی هدف — کلوز {d:%Y-%m-%d}   ·   {len(recs)} نماد   ·   "
          f"تعریف باکس: {args.kind}")
    print(f"سرمایه: {capital/1e9:,.1f} میلیارد ریال"
          + ("  (ارزش پرتفوی فعلی)" if args.capital is None else ""))
    if args.core < 99.99:
        print(f"هستهٔ ماهانه: {args.core:.0f}٪ = "
              f"{capital*args.core/100/1e9:,.1f} میلیارد ریال"
              f"   (بند ۲ CLAUDE.md؛ هفتگی و دیلی جدا چیده می‌شوند)")
    print(f"نرخ پایه: {base:+.2f}٪ بازده ماهانهٔ هر نماد-ماه")
    print("=" * 74)

    if args.why:
        print("\nریسک در برابر بازده — روی همهٔ ماه‌های «بالای باکس»")
        print("  ریسک = فاصلهٔ کلوزِ ورود تا کف باکس، در لحظهٔ ورود.\n")
        buckets = [(0, 1), (1, 2), (2, 4), (4, 7), (7, 12), (12, 1e9)]
        rowsb = defaultdict(list)
        for r in recs.values():
            by_m = monthly_frames(uni[r["sym"]])
            ms = sorted(by_m)
            for i in range(len(ms) - 1):
                a, b = ms[i], ms[i + 1]
                nxt = (a[0] + 1, 1) if a[1] == 12 else (a[0], a[1] + 1)
                if b != nxt or len(by_m[a]) < 5 or len(by_m[b]) < 2:
                    continue
                bars = [x for _, x in by_m[a]]
                box = make_box(args.kind, bars, bars[-1].c,
                               args.min_rows, args.max_rows)
                if not box:
                    continue
                fwd = by_m[b]
                e, x = fwd[0][1].c, fwd[-1][1].c
                if state(e, box) != "بالا":
                    continue
                rk = (e - box[0]) / e * 100
                for lo, hi in buckets:
                    if lo <= rk < hi:
                        rowsb[(lo, hi)].append((x - e) / e * 100)
                        break
        print(f"  {'ریسک ورود':<12}{'n':>6}{'میانگین بازده':>15}"
              f"{'مثبت':>8}{'بازده به ازای ۱٪ ریسک':>24}")
        for lo, hi in buckets:
            v = rowsb.get((lo, hi))
            if not v or len(v) < 8:
                continue
            mid = (lo + hi) / 2 if hi < 1e9 else lo * 1.4
            lab = f"{lo:g}–{hi:g}٪" if hi < 1e9 else f"بالای {lo:g}٪"
            print(f"  {lab:<12}{len(v):>6}{statistics.mean(v):>+14.2f}٪"
                  f"{sum(1 for x in v if x>0)/len(v)*100:>7.0f}٪"
                  f"{statistics.mean(v)/mid:>24.2f}")
        print("\n  بازده با ریسک بالا می‌رود — ولی ستون آخر پایین می‌آید.")
        print("  یعنی ریسکِ بیشتر بازدهِ بیشتر می‌دهد، ولی نه به‌اندازهٔ")
        print("  ریسکی که برداشته‌اید. به همین دلیل سایز بر ریسک تقسیم می‌شود.")

    print(f"\n{'نماد':<12}{'گروه':<14}{'٪':>6}{'مبلغ (م ر)':>12}"
          f"{'امتیاز':>8}{'ریسک':>7}{'n':>4}{'برد':>7}{'خروج':>7}")
    print("─" * 74)
    core_cap = capital * args.core / 100
    for r in picks:
        amt = core_cap * r["w"] / 100 / 1e6
        te = r.get("tgt_exit_days")
        ed = "—" if te is None else (f"{te:.2f}" + ("*" if r.get("liq_clipped") else ""))
        wn = "—" if r["win"] is None else f"{r['win']:.0f}٪"
        print(f"{r['sym']:<12}{r['group']:<14}{r['w']:>6.1f}{amt:>12,.0f}"
              f"{r['score']:>8.1f}{r['size_risk']:>7.2f}{r['n_up']:>4}"
              f"{wn:>7}{ed:>7}")
    print("─" * 74)
    inv = sum(r["w"] for r in picks)
    print(f"{'جمع':<12}{'':<14}{inv:>6.1f}{core_cap*inv/100/1e6:>12,.0f}")
    if cash_w > 0.05:
        print(f"{'نقد':<12}{'':<14}{cash_w:>6.1f}"
              f"{core_cap*cash_w/100/1e6:>12,.0f}"
              f"   ← سقف‌ها اجازهٔ بیشتر ندادند")
    print("(ستون ٪ نسبت به هسته است، نه کل سرمایه)"
          if args.core < 99.99 else "")

    gw2 = defaultdict(float)
    for r in picks:
        gw2[r["group"]] += r["w"]
    print("\nوزن گروه: " + " · ".join(
        f"{g} {v:.0f}٪" for g, v in sorted(gw2.items(), key=lambda kv: -kv[1])))

    # ── فاصله تا پرتفوی فعلی ──
    if holds:
        print("\n" + "=" * 74)
        print("تغییر لازم نسبت به پرتفوی فعلی")
        print("=" * 74)
        # وزن هدف را به درصدِ **کل سرمایه** برگردان تا با پرتفوی فعلی
        # قابل مقایسه باشد
        tgt = {r["sym"]: r["w"] * args.core / 100 for r in picks}
        syms = sorted(set(tgt) | set(holds))
        print(f"{'نماد':<12}{'فعلی٪':>8}{'هدف٪':>8}{'Δ٪':>8}"
              f"{'Δ واحد':>14}{'Δ مبلغ (م ر)':>15}  کار")
        print("─" * 74)
        for s in sorted(syms, key=lambda s: -(tgt.get(s, 0))):
            if s not in recs:
                continue
            px = recs[s]["close"]
            cur_w = holds.get(s, 0) * px / capital * 100
            t_w = tgt.get(s, 0.0)
            dw = t_w - cur_w
            if abs(dw) < 0.4:
                continue
            du = dw / 100 * capital / px
            act = "خرید" if dw > 0 else "فروش"
            print(f"{s:<12}{cur_w:>8.1f}{t_w:>8.1f}{dw:>+8.1f}"
                  f"{du:>+14,.0f}{dw/100*capital/1e6:>+15,.0f}  {act}")
        print("\n⚠️ اصل کار پایان ماه است. این جدول فاصله را نشان می‌دهد تا")
        print("   بشود تدریجی نزدیک شد، نه اینکه امروز یک‌جا اجرا شود.")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps({
            "date": f"{d:%Y-%m-%d}", "kind": args.kind, "capital": capital,
            "base": base, "n_universe": len(recs),
            "picks": [{k: v for k, v in r.items()
                       if k not in ("hist", "date")} for r in picks],
            "cfg": {"n": args.n, "max_weight": args.max_weight,
                    "max_group": args.max_group,
                    "risk_floor": args.risk_floor},
        }, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(f"\nJSON: {Path(args.json_out).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
