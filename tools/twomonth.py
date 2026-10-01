# -*- coding: utf-8 -*-
"""باکس دو ماهه — آیا پنجرهٔ بلندتر بهتر جدا می‌کند؟

مصطفی: «با حمایت ماه جاری و ماه قبل، ما یک حمایتِ دو ماه هم می‌توانیم
داشته باشیم — یک ولوم پروفایل برای دو ماه … که فاصله‌اش در ریسک
می‌تواند برای تصمیم‌گیری مفید باشد.»

## چطور تستش می‌کنیم، و چرا نه دقیقاً همان‌طور که گفت

شکلی که او گفت (ماه قبلِ کامل + ماه جاریِ ناتمام) یک اشکال دارد که
خودِ راهنما بند ۱ نوشته: **حجم تا پایانِ دوره کامل نمی‌شود**، پس
پروفایلِ وسطِ ماه معتبر نیست. و قبلاً اندازه گرفتیم: باکسِ ماهِ جاری
مزیتش +۰٫۰۱ واحد با t=+۰٫۰۶ بود — یعنی از تصادف جدا نشد.

پس سؤالِ اصلی را جدا می‌کنیم: **آیا پنجرهٔ دوماهه اصلاً چیزی به
یک‌ماهه اضافه می‌کند؟** این را می‌شود بدونِ لوک‌اهد پرسید — باکس از دو
ماهِ **کاملِ** قبل (M−2 و M−1) ساخته می‌شود و بازده روی ماه M سنجیده.
دقیقاً هم‌ارزِ آزمونِ یک‌ماهه، فقط پنجره دو برابر.

اگر دوماهه جلو بزند، آن‌وقت ارزشش را دارد که شکلِ موردنظرِ او هم
ساخته شود. اگر نزند، پنجرهٔ بلندتر فقط باکس را پهن‌تر و استاپ را دورتر
می‌کند بی‌آنکه چیزی بدهد.

معیار: **مزیت نسبت به نرخ پایهٔ همان ماه**، با آزمون جایگشتِ درون‌ماه —
همان کنترلی که بند ۰ قانون ۲ می‌خواهد.
"""
import argparse
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from monthly_backtest import load_daily, is_fixed_income, norm  # noqa: E402
from vp_box import Bar, make_box, state  # noqa: E402


def by_month(rows):
    out = defaultdict(list)
    for d, b in rows:
        out[(d.year, d.month)].append((d, b))
    return out


def collect(files, kind, nmonths):
    """(ماه، نماد، وضعیت، بازدهٔ ماه) برای هر نماد و ماه."""
    obs = []
    for f in files:
        sym = norm(f.stem.replace("_daily", ""))
        if is_fixed_income(sym):
            continue
        rows = load_daily(f)
        if len(rows) < 40:
            continue
        bm = by_month(rows)
        ms = sorted(bm)
        for i in range(nmonths, len(ms)):
            # ماه‌های پنجره و ماهِ بازده باید **پشتِ‌سرِ هم** باشند،
            # وگرنه شکافِ داده یک پنجرهٔ ساختگی می‌سازد.
            seq = ms[i - nmonths:i + 1]
            ok = True
            for a, b in zip(seq, seq[1:]):
                nxt = (a[0] + 1, 1) if a[1] == 12 else (a[0], a[1] + 1)
                if b != nxt:
                    ok = False
                    break
            if not ok:
                continue

            win = []
            for k in range(i - nmonths, i):
                win += [b for _, b in bm[ms[k]]]
            if len(win) < 5:
                continue
            cur = bm[ms[i]]
            if len(cur) < 2:
                continue

            # قرارداد ورود **عیناً** مثلِ monthly_backtest.py: مرجعِ
            # وضعیت کلوزِ آخرین روزِ پنجره است (در دسترس بوده، پس
            # لوک‌اهد نیست)، ولی بازده از کلوزِ **اولین روزِ ماهِ بعد**
            # شمرده می‌شود. اولین نسخهٔ این فایل بازده را از خودِ مرجع
            # می‌گرفت، یعنی گپِ سرِ ماه را هم می‌شمرد، و برای
            # valley_first عددِ منفی می‌داد در حالی که ابزارِ معتبر
            # ‎+۰٫۷۶‎ می‌دهد. همان اختلاف لوش داد.
            ref = win[-1].c
            entry = cur[0][1].c
            box = make_box(kind, win, ref_price=ref)
            if box is None:
                continue
            st = state(ref, box)
            ret = (cur[-1][1].c - entry) / entry * 100
            obs.append((ms[i], sym, st, ret))
    return obs


def edge(obs, want="بالا"):
    """مزیت = بازدهٔ گروه منهای بازدهٔ همهٔ نمادهای همان ماه."""
    by_m = defaultdict(list)
    for m, _s, st, r in obs:
        by_m[m].append((st, r))
    es, n = [], 0
    for m, xs in by_m.items():
        sel = [r for st, r in xs if st == want]
        if not sel:
            continue
        base = statistics.mean([r for _st, r in xs])
        es.append(statistics.mean(sel) - base)
        n += len(sel)
    return (statistics.mean(es) if es else 0.0), n, len(es)


def permute(obs, want, iters, rnd):
    """برچسبِ وضعیت را **داخلِ هر ماه** بُر بزن."""
    real, _, _ = edge(obs, want)
    by_m = defaultdict(list)
    for m, s, st, r in obs:
        by_m[m].append((st, r))
    hits = 0
    for _ in range(iters):
        shuffled = []
        for m, xs in by_m.items():
            sts = [st for st, _ in xs]
            rnd.shuffle(sts)
            shuffled += [(m, "x", st, r)
                         for st, (_o, r) in zip(sts, xs)]
        e, _, _ = edge(shuffled, want)
        if e >= real:
            hits += 1
    return (hits + 1) / (iters + 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_auto")
    ap.add_argument("--glob", default="*.csv")
    ap.add_argument("--kinds", default="valley_first,poc_band,value_area")
    ap.add_argument("--iters", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rnd = random.Random(args.seed)
    files = sorted(Path(args.data).glob(args.glob))
    if not files:
        print(f"هیچ فایلی در {args.data} نبود.")
        return 1

    print(f"\n  {len(files)} فایل · مزیتِ «بالای باکس» نسبت به نرخ پایهٔ"
          f" همان ماه\n")
    print(f"  {'تعریف':<14}{'پنجره':>8}{'سیگنال':>9}{'ماه':>6}"
          f"{'مزیت (واحد٪)':>15}{'p':>9}")
    print("  " + "─" * 62)
    for kind in args.kinds.split(","):
        for nm in (1, 2):
            obs = collect(files, kind, nm)
            if not obs:
                print(f"  {kind:<14}{nm:>7}ماه   —")
                continue
            e, n, nmo = edge(obs)
            p = permute(obs, "بالا", args.iters, rnd)
            print(f"  {kind:<14}{nm:>6} ماه{n:>9}{nmo:>6}"
                  f"{e:>+14.3f}{p:>9.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
