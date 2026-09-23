# -*- coding: utf-8 -*-
"""نگه‌داشتن تا سیگنالِ مخالف — در برابر خریدن و نگه داشتن.

مصطفی: «اگر طبق این استراتژی بری ۲۵٪، ولی اگر هولد کنی ۱۹۰٪ رشد
می‌کرد پارسال — خب به درد نمی‌خوره که… می‌خوام ببینیم هرگاه سیگنال
خرید دادیم، این معامله را **تا وقتی جهتِ عکس صادر نشده** نگه داریم،
چقدر بازدهی می‌دهد. و دوباره وقتی سیگنال داد دوباره ورود بزنیم.»

## این آزمون با بقیه فرق دارد، و فرقش مهم است

آزمون‌های قبلی این مخزن **هندسهٔ ۱:۱** را می‌سنجیدند: ورود روی پولبک،
تارگت به اندازهٔ ارتفاعِ باکس، استاپ زیر کف. آن آزمون جوابِ «این
معامله چقدر می‌دهد» را می‌دهد.

سؤالِ او فرق دارد: **آیا اصلاً ارزشش را دارد که از بازار بیرون
بیایم؟** معیارش هم تارگت نیست، خودِ **نگه‌داشتنِ همان نماد** است.
این تنها نرخ پایهٔ درستِ این سؤال است (بند ۰ قانون ۲).

## قاعده

روی هر نمادِ جداگانه، دو حالت: نقد یا سهم.

    نقد  + کلوزِ دورهٔ تصمیم **بالای** باکس  → بخر  (کلوزِ همان روز)
    سهم  + کلوزِ دورهٔ تصمیم **زیرِ** باکس   → بفروش
    «داخلِ باکس» یعنی دست نگه دار — نه بخر، نه بفروش

باکس از دورهٔ کامل‌شدهٔ قبل، پس لوک‌اهد نیست. کارمزد رفت‌وبرگشت از
`--cost` کم می‌شود (پیش‌فرض ۰٫۵۵٪، بند ۹ راهنما).

خروجی برای هر نماد: بازدهٔ استراتژی، بازدهٔ نگه‌داشتن، اختلاف، و
اینکه چند وقت در بازار بوده. جمع‌بندی هم می‌گوید در چند درصدِ نمادها
استراتژی از نگه‌داشتن جلو زده — که عددِ اصلیِ این آزمون است.
"""
import argparse
import statistics
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from monthly_backtest import load_daily, is_fixed_income, norm  # noqa: E402
from vp_box import make_box, state  # noqa: E402


def periods(rows, mode, anchor):
    """دوره‌ها را برمی‌گرداند: [(کلید، [(تاریخ، کندل)...]), ...]"""
    buck = defaultdict(list)
    for d, b in rows:
        if mode == "month":
            k = (d.year, d.month)
        else:
            # لنگرِ هفته: روزِ `anchor` شروعِ هفته است
            off = (d.weekday() - anchor) % 7
            s = d - timedelta(days=off)
            k = (s.year, s.month, s.day)
        buck[k].append((d, b))
    return [(k, buck[k]) for k in sorted(buck)]


def simulate(rows, kind, mode, anchor, cost):
    """ماشینِ حالت. خروجی: (بازدهٔ استراتژی، بازدهٔ هولد، سهمِ زمان، معامله)"""
    ps = periods(rows, mode, anchor)
    if len(ps) < 4:
        return None

    equity = 1.0
    long = False
    in_days = 0
    tot_days = 0
    trades = 0

    for i in range(1, len(ps)):
        prev = [b for _d, b in ps[i - 1][1]]
        cur = ps[i][1]
        if len(prev) < 3 or not cur:
            continue
        box = make_box(kind, prev, ref_price=prev[-1].c)
        if box is None:
            continue
        ref = prev[-1].c                    # کلوزِ دورهٔ تصمیم
        st = state(ref, box)
        end = cur[-1][1].c                  # کلوزِ پایانِ دورهٔ بعد
        tot_days += len(cur)

        # ── ۱) تصمیم روی کلوزِ ref، **قبل** از سوار شدنِ دورهٔ بعد ──
        # ترتیب مهم است: اگر سیگنالِ فروش آمده، همان‌جا می‌فروشیم و
        # دورهٔ بعد را سوار نمی‌شویم. اولین نسخهٔ این تابع اول سوار
        # می‌شد و بعد می‌فروخت، که یعنی هر خروج یک دوره دیر انجام
        # می‌شد و نتیجه به نفعِ استراتژی تقلب می‌کرد.
        if long and st == "زیر":
            long = False
            equity *= (1 - cost / 100.0)
        elif not long and st == "بالا":
            long = True
            trades += 1
            equity *= (1 - cost / 100.0)
        # «داخل» یعنی دست نگه دار — حالت عوض نمی‌شود

        # ── ۲) حالا دورهٔ بعد را سوار شو، اگر سهم داریم ──
        if long:
            equity *= end / ref
            in_days += len(cur)

    first = rows[0][1].c
    last = rows[-1][1].c
    hold = (last / first - 1) * 100
    strat = (equity - 1) * 100
    share = in_days / tot_days * 100 if tot_days else 0.0
    return strat, hold, share, trades


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_auto")
    ap.add_argument("--glob", default="*.csv")
    ap.add_argument("--kind", default="poc_band")
    ap.add_argument("--cost", type=float, default=0.55)
    ap.add_argument("--week-anchor", type=int, default=6,
                    help="۶ = یکشنبه، لنگرِ هفتهٔ صندوق‌های بورسی")
    ap.add_argument("--top", type=int, default=14)
    args = ap.parse_args()

    files = sorted(Path(args.data).glob(args.glob))
    if not files:
        print(f"هیچ فایلی در {args.data} نبود.")
        return 1

    res = {"week": [], "month": []}
    for f in files:
        sym = norm(f.stem.replace("_daily", ""))
        if is_fixed_income(sym):
            continue
        rows = load_daily(f)
        if len(rows) < 80:
            continue
        for mode in ("week", "month"):
            out = simulate(rows, args.kind, mode, args.week_anchor,
                           args.cost)
            if out:
                res[mode].append((sym,) + out)

    print(f"\n  تعریفِ باکس: {args.kind} · کارمزد رفت‌وبرگشت "
          f"{args.cost:.2f}٪ · {len(res['week'])} نماد")
    print("  «هولد» = همان نماد، از اولین تا آخرین روزِ داده.\n")

    for mode, fa in (("week", "تصمیمِ هفتگی"), ("month", "تصمیمِ ماهانه")):
        xs = res[mode]
        if not xs:
            continue
        beat = sum(1 for _s, st, ho, _sh, _t in xs if st > ho)
        ms = statistics.median([x[1] for x in xs])
        mh = statistics.median([x[2] for x in xs])
        msh = statistics.median([x[3] for x in xs])
        mt = statistics.median([x[4] for x in xs])
        print(f"  ══ {fa} ══")
        print(f"     میانهٔ بازدهِ استراتژی : {ms:>8.1f}٪")
        print(f"     میانهٔ بازدهِ هولد     : {mh:>8.1f}٪")
        print(f"     اختلاف                : {ms - mh:>+8.1f} واحد")
        print(f"     از هولد جلو زد        : {beat} از {len(xs)} نماد"
              f"  ({beat / len(xs) * 100:.0f}٪)")
        print(f"     میانهٔ سهمِ زمان در بازار: {msh:>6.0f}٪ · "
              f"میانهٔ معامله: {mt:.0f}\n")

    # ── نمادهایی که مصطفی دارد یا دنبال می‌کند ──
    watch = {norm(x) for x in
             ("عیار کهربا نهال نقران سینرژی اهرم موج دوایکس تمشک "
              "سمازن شاراک سقاین").split()}
    print("  ── نمادهای خودت ──")
    print(f"  {'نماد':<10}{'دوره':<9}{'استراتژی':>10}{'هولد':>9}"
          f"{'اختلاف':>10}{'در بازار':>10}")
    print("  " + "─" * 58)
    for mode, fa in (("week", "هفتگی"), ("month", "ماهانه")):
        for sym, st, ho, sh, _t in sorted(res[mode]):
            if sym in watch:
                mark = "✓" if st > ho else " "
                print(f"  {sym:<10}{fa:<9}{st:>9.1f}٪{ho:>8.1f}٪"
                      f"{st - ho:>+9.1f}{sh:>9.0f}٪ {mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
