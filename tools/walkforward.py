# -*- coding: utf-8 -*-
"""همین استراتژی را در گذشته اجرا کن — هفتگی در برابر ماهانه.

سؤال مصطفی: «یک پرتفوی هدف ماهانه داریم یک هفتگی داریم، بر اساس هفته
برویم جلو یا بر اساس ماه؟ کدام بهینه‌تر است؟»

این را نمی‌شود با استدلال جواب داد. اینجا استراتژی **قدم‌به‌قدم رو به جلو**
اجرا می‌شود: در هر تاریخ بازچینی، فقط با دادهٔ تا کلوزِ قبل، پرتفو چیده
می‌شود، تا بازچینی بعد نگه داشته می‌شود، و بازده واقعیِ همان دوره ثبت
می‌شود. هیچ لوک‌اهدی نیست.

چهار مقایسه:
  • بازچینی هفتگی      — هر شنبه
  • بازچینی ماهانه     — اول هر ماه میلادی
  • نگه‌داشتن کل جهان   — وزن مساوی، نرخ پایه
  • نقد                — صفر

کارمزد روی **گردش واقعی** حساب می‌شود، نه سرانگشتی: هر بازچینی وزن قبلی و
وزن جدید مقایسه می‌شود و جمعِ |اختلاف| ضربدر نرخ می‌شود. این همان چیزی
است که تفاوت هفتگی و ماهانه را می‌سازد — هفتگی چهار برابر بیشتر بازچینی
می‌کند، پس چهار برابر کارمزد می‌دهد.

    python3 tools/walkforward.py
    python3 tools/walkforward.py --fee 1.2 --n 7
"""
import argparse
import json
import math
import statistics
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from monthly_backtest import load_daily, is_fixed_income, norm
from vp_box import make_box, state
from calendar_wk import week_key_for
from drivers import group_of

SAT = week_key_for(5)          # صندوق‌های بورسی: هفته از شنبه


def load_universe(data_dir, glob, min_days):
    """dict[نماد] = [(تاریخ، Bar), ...] بدون تکرار."""
    uni, fps, seen = {}, {}, set()
    for p in sorted(Path(data_dir).glob(glob)):
        sym = p.stem.replace("_daily", "").replace("_", " ")
        rows = load_daily(p)
        if len(rows) < min_days or is_fixed_income(sym):
            continue
        fp = tuple((d.isoformat(), round(b.c, 6)) for d, b in rows)
        if fp in fps or norm(sym) in seen:
            continue
        fps[fp] = 1
        seen.add(norm(sym))
        uni[sym] = rows
    return uni


def month_key(d):
    return (d.year, d.month)


def prev_month(k):
    return (k[0] - 1, 12) if k[1] == 1 else (k[0], k[1] - 1)


def build_index(rows):
    """(by_month, by_week, close_on) برای یک نماد."""
    by_m, by_w, close_on = defaultdict(list), defaultdict(list), {}
    for d, b in rows:
        by_m[month_key(d)].append((d, b))
        by_w[SAT(d)].append((d, b))
        close_on[d] = b.c
    return by_m, by_w, close_on


def pick(uni, idx, asof, kind, n, max_group, min_n, hist, holding=None):
    """پرتفوی هدف در تاریخ `asof` — فقط با دادهٔ تا قبلِ آن.

    همان قاعدهٔ tomorrow.py، ساده‌شده: واجد شرط = بالای باکس ماهانهٔ قبل
    **و** بالای باکس هفتگیِ قبل؛ مرتب بر اساس ریسک (فاصله تا کف باکس)؛
    سقف تعداد در هر گروه؛ وزن مساوی بین انتخاب‌شده‌ها.

    وزنِ مساوی به‌جای امتیاز÷ریسک انتخاب شده تا آزمون دربارهٔ **تواتر
    بازچینی** باشد نه دربارهٔ فرمول وزن. هر دو حالت یک فرمول می‌گیرند،
    پس مقایسه منصفانه است.
    """
    cands = []
    for sym, rows in uni.items():
        by_m, by_w, _ = idx[sym]
        # آخرین کندلِ **قبل از** asof
        past = [d for d, _ in rows if d < asof]
        if len(past) < min_n:
            continue
        px = None
        for d, b in reversed(rows):
            if d < asof:
                px = b.c
                break
        if px is None:
            continue

        pm = prev_month(month_key(asof))
        if pm not in by_m or len(by_m[pm]) < 5:
            continue
        mb = make_box(kind, [x for _, x in by_m[pm]], by_m[pm][-1][1].c)
        if mb is None or state(px, mb) != "بالا":
            continue

        pw = SAT(asof) - timedelta(days=7)
        if pw not in by_w or len(by_w[pw]) < 3:
            continue
        wb = make_box(kind, [x for _, x in by_w[pw]], by_w[pw][-1][1].c)
        if wb is None or state(px, wb) != "بالا":
            continue

        risk = min((px - mb[0]) / px * 100, (px - wb[0]) / px * 100)
        cands.append((max(risk, 0.05), sym))

    cands.sort()
    out, gc = [], defaultdict(int)
    per_group = max(1, math.ceil(n * max_group / 100))
    # ── چسبندگی ──
    # کارمزد ۰٫۵۵٪ رفت‌وبرگشت با بازچینی هفتگی می‌شود ~۳۲٪ در سال، و
    # مزیتِ باکس ~۷٪ در سال است. پس هر تعویضی که «فقط رتبه بهتر شده»
    # ضرر است. نمادی که هنوز واجد شرط است سر جایش می‌ماند و فقط وقتی
    # بیرون می‌رود که از شرط بیفتد. مصطفی همین را روی کهربا گفت.
    if holding:
        keep = [(r, sm) for r, sm in cands if sm in holding]
        for risk, sym in keep[:n]:
            g = hist.get(sym, "؟")
            if gc[g] >= per_group:
                continue
            out.append(sym)
            gc[g] += 1
    for risk, sym in cands:
        if sym in out:
            continue
        g = hist.get(sym, "؟")
        if gc[g] >= per_group:
            continue
        out.append(sym)
        gc[g] += 1
        if len(out) >= n:
            break
    return {s: 100.0 / len(out) for s in out} if out else {}


def period_ret(rows_idx, sym, start, end):
    """بازده کلوز-به-کلوز بین دو تاریخ، با نزدیک‌ترین کندلِ موجود."""
    _, _, close_on = rows_idx
    ds = sorted(close_on)
    a = [d for d in ds if d >= start]
    b = [d for d in ds if d <= end]
    if not a or not b or a[0] >= b[-1]:
        return None
    p0, p1 = close_on[a[0]], close_on[b[-1]]
    return (p1 - p0) / p0 * 100 if p0 > 0 else None


def run(uni, idx, dates, kind, n, max_group, min_n, fee, hist,
        sticky=False):
    """یک سری بازچینی را اجرا کن. خروجی: (بازده‌ها، گردش‌ها، پرتفوها)."""
    prev_w, out, turns, books = {}, [], [], []
    for i in range(len(dates) - 1):
        a, b = dates[i], dates[i + 1]
        w = pick(uni, idx, a, kind, n, max_group, min_n, hist,
                 holding=set(prev_w) if sticky else None)
        if not w:
            # نقد می‌مانیم — گردشِ خروج از پرتفوی قبل
            turn = sum(prev_w.values())
            out.append(0.0 - turn / 100 * fee)
            turns.append(turn)
            books.append({})
            prev_w = {}
            continue
        turn = sum(abs(w.get(s, 0) - prev_w.get(s, 0))
                   for s in set(w) | set(prev_w))
        gross = 0.0
        held = 0.0
        for s, ww in w.items():
            r = period_ret(idx[s], s, a, b - timedelta(days=1))
            if r is None:
                continue
            gross += ww / 100 * r
            held += ww
        if held > 0:
            gross = gross / held * 100 * (held / 100)   # بخشِ پرشده
        out.append(gross - turn / 100 * fee)
        turns.append(turn)
        books.append(w)
        prev_w = w
    return out, turns, books


def stats(rs):
    if not rs:
        return None
    eq = 1.0
    peak, mdd = 1.0, 0.0
    for r in rs:
        eq *= 1 + r / 100
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak * 100)
    sd = statistics.stdev(rs) if len(rs) > 1 else 0.0
    return {"n": len(rs), "total": (eq - 1) * 100,
            "mean": statistics.mean(rs), "sd": sd,
            "win": sum(1 for r in rs if r > 0) / len(rs) * 100,
            "mdd": mdd, "sharpe": (statistics.mean(rs) / sd) if sd else 0.0,
            "worst": min(rs), "best": max(rs)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_auto")
    ap.add_argument("--glob", default="*.csv")
    ap.add_argument("--kind", default="valley_first")
    ap.add_argument("--n", type=int, default=7)
    ap.add_argument("--max-group", type=float, default=36.0)
    ap.add_argument("--min-n", type=int, default=40)
    ap.add_argument("--fee", type=float, default=0.55,
                    help="کارمزد رفت‌وبرگشت درصد؛ ۰٫۵۵ صندوق، ۱٫۲ سهام")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args()

    uni = load_universe(args.data, args.glob, args.min_n)
    if not uni:
        print("جهانی ساخته نشد.")
        return 1
    idx = {s: build_index(r) for s, r in uni.items()}

    root = Path(__file__).resolve().parent.parent
    cat, hist = {}, {}
    tp = root / "data/extracted/TODAY.json"
    if tp.exists():
        for r in json.loads(tp.read_text(encoding="utf-8")):
            cat[norm(r["نماد"])] = r["دسته"]
    for s in uni:
        hist[s] = group_of(s, cat.get(norm(s), "سهامی"))

    all_d = sorted({d for r in uni.values() for d, _ in r})
    first, last = all_d[0], all_d[-1]

    # ── تاریخ‌های بازچینی ──
    weeks = sorted({SAT(d) for d in all_d})
    weeks = [w for w in weeks if w > first + timedelta(days=40)]
    months = sorted({month_key(d) for d in all_d})
    m_dates = []
    for k in months:
        ds = [d for d in all_d if month_key(d) == k]
        if ds and ds[0] > first + timedelta(days=40):
            m_dates.append(ds[0])

    print("=" * 78)
    print(f"اجرای رو به جلو — {len(uni)} نماد · {first} تا {last}")
    print(f"کارمزد رفت‌وبرگشت {args.fee}٪ · حداکثر {args.n} نماد ·"
          f" سقف گروه {args.max_group:.0f}٪")
    print("=" * 78)

    wr, wt, wb = run(uni, idx, weeks, args.kind, args.n,
                     args.max_group, args.min_n, args.fee, hist)
    mr, mt, mb = run(uni, idx, m_dates, args.kind, args.n,
                     args.max_group, args.min_n, args.fee, hist)
    wsr, wst, _ = run(uni, idx, weeks, args.kind, args.n, args.max_group,
                      args.min_n, args.fee, hist, sticky=True)
    msr, mst, msb = run(uni, idx, m_dates, args.kind, args.n, args.max_group,
                        args.min_n, args.fee, hist, sticky=True)

    # ── گروه کنترل: کلِ جهان با وزن مساوی، بدون بازچینی ──
    base_w, base_m = [], []
    for i in range(len(weeks) - 1):
        a, b = weeks[i], weeks[i + 1]
        rs = [period_ret(idx[s], s, a, b - timedelta(days=1)) for s in uni]
        rs = [r for r in rs if r is not None]
        if rs:
            base_w.append(statistics.mean(rs))
    for i in range(len(m_dates) - 1):
        a, b = m_dates[i], m_dates[i + 1]
        rs = [period_ret(idx[s], s, a, b - timedelta(days=1)) for s in uni]
        rs = [r for r in rs if r is not None]
        if rs:
            base_m.append(statistics.mean(rs))

    rows = [("هفتگی", stats(wr), statistics.mean(wt) if wt else 0),
            ("هفتگی — چسبنده", stats(wsr),
             statistics.mean(wst) if wst else 0),
            ("پایه هفتگی (کل جهان)", stats(base_w), 0.0),
            ("ماهانه", stats(mr), statistics.mean(mt) if mt else 0),
            ("ماهانه — چسبنده", stats(msr),
             statistics.mean(mst) if mst else 0),
            ("پایه ماهانه (کل جهان)", stats(base_m), 0.0)]

    print(f"\n{'سبد':<24}{'دوره':>6}{'بازده کل':>10}{'هر دوره':>9}"
          f"{'نوسان':>8}{'برد':>7}{'بدترین':>9}{'افت':>7}{'گردش':>8}")
    print("─" * 78)
    for label, st, turn in rows:
        if not st:
            print(f"{label:<24}  —")
            continue
        print(f"{label:<24}{st['n']:>6}{st['total']:>+9.1f}٪"
              f"{st['mean']:>+8.2f}٪{st['sd']:>7.2f}٪{st['win']:>6.0f}٪"
              f"{st['worst']:>+8.1f}٪{st['mdd']:>6.1f}٪{turn:>7.0f}٪")

    # ── سالانه‌سازی، تا دو تواتر روی یک مقیاس بیایند ──
    print("\nروی یک مقیاس (سالانه‌شده)")
    print("─" * 78)
    for label, st, turn in rows:
        if not st or st["n"] < 2:
            continue
        per_yr = 52 if "هفتگی" in label else 12
        ann = ((1 + st["mean"] / 100) ** per_yr - 1) * 100
        ann_sd = st["sd"] * math.sqrt(per_yr)
        print(f"  {label:<24}{ann:>+9.1f}٪ سالانه"
              f"{ann_sd:>9.1f}٪ نوسان"
              f"{(ann/ann_sd if ann_sd else 0):>8.2f} بازده/نوسان"
              f"{turn*per_yr/100*args.fee:>8.1f}٪ کارمزد/سال")

    w_st, m_st = stats(wr), stats(mr)
    if w_st and m_st and w_st["n"] > 2 and m_st["n"] > 2:
        wa = ((1 + w_st["mean"] / 100) ** 52 - 1) * 100
        ma = ((1 + m_st["mean"] / 100) ** 12 - 1) * 100
        print("\n" + "=" * 78)
        print("حکم")
        print("=" * 78)
        better = "هفتگی" if wa > ma else "ماهانه"
        print(f"  سالانهٔ هفتگی {wa:+.1f}٪ · سالانهٔ ماهانه {ma:+.1f}٪"
              f"  →  {better} بهتر است")
        print(f"  ولی کارمزد: هفتگی "
              f"{statistics.mean(wt)*52/100*args.fee:.1f}٪ در سال،"
              f" ماهانه {statistics.mean(mt)*12/100*args.fee:.1f}٪")
        print(f"  و افت بیشینه: هفتگی {w_st['mdd']:.1f}٪ ·"
              f" ماهانه {m_st['mdd']:.1f}٪")
        print(f"\n  ⚠️ {w_st['n']} هفته و {m_st['n']} ماه. با این تعداد ماه،")
        print("  عددِ ماهانه خطای بزرگی دارد — به آن به‌عنوان تخمین نگاه کن.")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps({
            "fee": args.fee, "n": args.n, "span": [str(first), str(last)],
            "weekly": stats(wr), "monthly": stats(mr),
            "weekly_sticky": stats(wsr), "monthly_sticky": stats(msr),
            "turn_weekly_sticky": statistics.mean(wst) if wst else 0,
            "turn_monthly_sticky": statistics.mean(mst) if mst else 0,
            "monthly_sticky_rets": [round(r, 4) for r in msr],
            "weekly_sticky_rets": [round(r, 4) for r in wsr],
            "last_book_monthly_sticky": msb[-1] if msb else {},
            "base_weekly": stats(base_w), "base_monthly": stats(base_m),
            "turn_weekly": statistics.mean(wt) if wt else 0,
            "turn_monthly": statistics.mean(mt) if mt else 0,
            "weekly_rets": [round(r, 4) for r in wr],
            "monthly_rets": [round(r, 4) for r in mr],
            "base_weekly_rets": [round(r, 4) for r in base_w],
            "base_monthly_rets": [round(r, 4) for r in base_m],
            "last_book_weekly": wb[-1] if wb else {},
            "last_book_monthly": mb[-1] if mb else {},
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nJSON: {Path(args.json_out).resolve()}")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
