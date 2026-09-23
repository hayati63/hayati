# -*- coding: utf-8 -*-
"""میله و پرچم — آیا اندازهٔ میله واقعاً تارگت می‌دهد؟

مصطفی: «از علامت میله و پرچم … یک میله داره و یک پرچم داره که هرگاه اون
پرچم به بالا شکسته بشه یه میله رشد می‌کنه … سه تا تارگت … کوتاه‌مدت،
میان‌مدت، بلندمدت.»

قاعده‌ای که تستش می‌کنیم — و هیچ‌جای این مخزن تا امروز تست نشده بود:

    میله  : حرکتِ تندِ رو به بالا در `pole_max` کندل، دستِ‌کم `pole_min_pct`
    پرچم  : اصلاحِ کم‌عمق و کم‌دامنهٔ بعدش، دستِ‌کم ۲ و حداکثر `flag_max` کندل،
            که بیشتر از `retrace_max` از میله را پس ندهد
    تریگر : کلوز بالای سقفِ پرچم
    تارگت : نقطهٔ شکست + طولِ میله  (پروجکشنِ ۱:۱)
    استاپ : کفِ پرچم

## چرا نمی‌شود فقط «نرخ رسیدن به تارگت» را گزارش کرد

بند ۰ قانون ۲: هر عدد باید با نرخ پایه سنجیده شود. تارگتی که ۸٪ بالاتر
است، در بازاری که ماهی ۱۲٪ بالا می‌رود، خودبه‌خود می‌خورد. پس **گروه
کنترلِ هم‌هندسه** ساخته می‌شود: از همان نماد، همان روز، همان فاصلهٔ
درصدیِ تارگت و استاپ — ولی بدون شرطِ میله و پرچم. اگر الگو چیزی بلد
باشد، باید از آن کنترل جلو بزند.

معیار **R** است نه نرخ برد: تارگت و استاپ فاصله‌های متفاوتی دارند، پس
نرخ برد به‌تنهایی گمراه‌کننده است (استاپِ دور، نرخ برد را مکانیکی بالا
می‌برد — همان درسی که در سوییپِ نقطهٔ ورود گرفتیم).
"""
import argparse
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from monthly_backtest import load_daily, is_fixed_income, norm  # noqa: E402


def find_setups(bars, pole_max, pole_min_pct, flag_max, retrace_max):
    """هر جایی که میله+پرچم کامل شده، با نقطهٔ شکستش."""
    out = []
    n = len(bars)
    for i in range(1, n):
        # ── میله: از i شروع کن، تا pole_max کندل جلو برو ──
        for plen in range(1, pole_max + 1):
            j = i + plen - 1
            if j >= n:
                break
            p_lo = bars[i - 1].c
            p_hi = max(b.h for b in bars[i:j + 1])
            if p_lo <= 0:
                break
            rise = (p_hi - p_lo) / p_lo * 100
            if rise < pole_min_pct:
                continue
            pole = p_hi - p_lo

            # ── پرچم: اصلاحِ کم‌عمق بعد از میله ──
            for flen in range(2, flag_max + 1):
                k = j + flen
                if k >= n:
                    break
                fl = bars[j + 1:k + 1]
                f_lo = min(b.l for b in fl)
                f_hi = max(b.h for b in fl)
                if p_hi - f_lo > pole * retrace_max:
                    break                      # عمیق‌تر از حد → پرچم نیست
                if f_hi > p_hi:
                    break                      # سقف را زده، دیگر پرچم نیست
                # تریگر: کلوزِ بالای سقفِ پرچم، در همان کندلِ بعدی.
                # اگر نزد، پرچم یک کندل بلندتر می‌شود و دوباره امتحان —
                # برای همین `flen` باید واقعاً جلو برود. (اولین نسخه اینجا
                # بی‌قید `break` داشت، پس پرچم همیشه ۲ کندل می‌ماند و
                # `--flag-max` هیچ اثری نداشت. در سوییپِ آستانه‌ها لو رفت:
                # ۴ و ۶ و ۱۰ عددِ کاملاً یکسان می‌دادند.)
                t = k + 1
                if t < n and bars[t].c > f_hi:
                    out.append({
                        "i": t, "entry": bars[t].c,
                        "pole": pole, "stop": f_lo,
                        "rise": rise, "plen": plen, "flen": flen,
                    })
                    break                      # یک پرچم به ازای هر میله
            break                              # یک میله به ازای هر شروع
    return out


def run_trade(bars, start, entry, target, stop, horizon):
    """۱ اگر تارگت اول خورد، −۱ اگر استاپ، وگرنه بازدهٔ نرمال‌شده."""
    risk = entry - stop
    if risk <= 0:
        return None
    for t in range(start + 1, min(start + 1 + horizon, len(bars))):
        hit_t = bars[t].h >= target
        hit_s = bars[t].l <= stop
        if hit_t and hit_s:
            return None                        # هر دو در یک کندل — مبهم
        if hit_t:
            return (target - entry) / risk
        if hit_s:
            return -1.0
    last = bars[min(start + horizon, len(bars) - 1)].c
    return (last - entry) / risk


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_auto")
    ap.add_argument("--glob", default="*.csv")
    ap.add_argument("--pole-max", type=int, default=5)
    ap.add_argument("--pole-min-pct", type=float, default=8.0)
    ap.add_argument("--flag-max", type=int, default=6)
    ap.add_argument("--retrace-max", type=float, default=0.5)
    ap.add_argument("--horizon", type=int, default=30)
    ap.add_argument("--iters", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rnd = random.Random(args.seed)
    root = Path(args.data)
    files = sorted(root.glob(args.glob))
    if not files:
        print(f"هیچ فایلی در {root} نبود.")
        return 1

    real, ctrl = [], []
    per_sym = defaultdict(list)
    nsym = 0
    for f in files:
        sym = norm(f.stem.replace("_daily", ""))
        if is_fixed_income(sym):
            continue
        rows = load_daily(f)
        if len(rows) < 60:
            continue
        bars = [b for _, b in rows]
        nsym += 1
        sets = find_setups(bars, args.pole_max, args.pole_min_pct,
                           args.flag_max, args.retrace_max)
        for s in sets:
            tgt = s["entry"] + s["pole"]
            r = run_trade(bars, s["i"], s["entry"], tgt, s["stop"],
                          args.horizon)
            if r is None:
                continue
            real.append(r)
            per_sym[sym].append(r)
            # ── کنترلِ هم‌هندسه: همان نماد، روزِ تصادفی، همان درصدها ──
            up = s["pole"] / s["entry"]
            dn = (s["entry"] - s["stop"]) / s["entry"]
            for _ in range(3):
                t0 = rnd.randrange(30, len(bars) - args.horizon - 1) \
                    if len(bars) > args.horizon + 32 else None
                if t0 is None:
                    break
                e = bars[t0].c
                rc = run_trade(bars, t0, e, e * (1 + up), e * (1 - dn),
                               args.horizon)
                if rc is not None:
                    ctrl.append(rc)

    if not real:
        print("هیچ ستاپی پیدا نشد. آستانه‌ها را شل‌تر کن.")
        return 1

    def desc(xs):
        m = statistics.mean(xs)
        sd = statistics.pstdev(xs) or 1e-9
        win = sum(1 for x in xs if x > 0) / len(xs) * 100
        return m, sd, win

    mr, sr, wr = desc(real)
    mc, sc, wc = desc(ctrl) if ctrl else (0.0, 1.0, 0.0)
    se = (sr ** 2 / len(real) + sc ** 2 / max(1, len(ctrl))) ** 0.5
    t = (mr - mc) / se if se else 0.0

    print(f"\n  میله ≥{args.pole_min_pct:.0f}٪ در ≤{args.pole_max} کندل · "
          f"پرچم ≤{args.flag_max} کندل · اصلاح ≤{args.retrace_max:.0%} · "
          f"افق {args.horizon} روز")
    print(f"  {nsym} نماد\n")
    print(f"  {'':<22}{'n':>7}{'میانگین R':>12}{'نرخ برد':>10}")
    print(f"  {'میله و پرچم':<22}{len(real):>7}{mr:>12.3f}{wr:>9.1f}٪")
    print(f"  {'کنترلِ هم‌هندسه':<22}{len(ctrl):>7}{mc:>12.3f}{wc:>9.1f}٪")
    print(f"\n  اختلاف {mr - mc:+.3f}R · t={t:+.2f}")

    # ── آزمون جایگشت: برچسبِ «ستاپ» را داخلِ همان نماد بُر بزن ──
    pool = real + ctrl
    obs = mr - mc
    hits = 0
    for _ in range(args.iters):
        rnd.shuffle(pool)
        a = pool[:len(real)]
        b = pool[len(real):]
        if not b:
            break
        if (statistics.mean(a) - statistics.mean(b)) >= obs:
            hits += 1
    p = (hits + 1) / (args.iters + 1)
    print(f"  p={p:.4f} (جایگشت، {args.iters:,} بار)")

    pos = sum(1 for v in per_sym.values()
              if len(v) >= 3 and statistics.mean(v) > 0)
    tot = sum(1 for v in per_sym.values() if len(v) >= 3)
    if tot:
        print(f"  {pos} از {tot} نماد (با ≥۳ ستاپ) میانگینِ مثبت دارند")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
