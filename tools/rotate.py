# -*- coding: utf-8 -*-
"""چهار راه با یک پول — کدام بیشتر می‌دهد؟

مصطفی: «اگر فقط تو یک بازار بمونم و هولد کنم چقدر سود می‌ده — طلا،
نقره، صندوق‌های سپردهٔ کالایی؟ و اگر هر بار سیگنال میاد خرید و فروش
کنم چقدر؟ … یا نه، بیشترِ سرمایه هم در هفته وقتی باکس منفی ساخته شد
خروج بزنیم و وارد نمادی بشیم که باکس مثبت ساخته. … یا مبلغی را از هر
نمادی هولد نگه داریم و روی بخشی از مبلغ استراتژی خرید و فروش کنیم.»

چهار راه، روی **یک سرمایه**، روی **یک جهانِ نماد**، در **یک دوره** —
تا قابلِ مقایسه باشند:

  ۱ هولد        سبدِ هم‌وزنِ کلِ جهان، دست‌نزده تا آخر
  ۲ نقدشو       بالای باکس بخر، زیرِ باکس **نقد** شو
  ۳ چرخش        همیشه در بازار؛ هر دوره پول را به نمادهایی که باکسشان
                مثبت است منتقل کن. نقد فقط وقتی **هیچ** نمادی مثبت نیست
  ۴ هسته+نوسان  `--core` درصد همیشه هولد، باقی با قاعدهٔ چرخش

راهِ ۳ همان چیزی است که آزمونِ قبلی نشان داد باید تست شود: مزیتی که
اندازه گرفتیم **انتخاب** است نه زمان‌بندی، و انتخاب با ماندن در بازار
و عوض کردنِ نماد برداشت می‌شود، نه با نقد شدن.

کارمزد روی **گردشِ واقعی** حساب می‌شود، نه به ازای هر تصمیم: اگر وزنِ
نمادی از ۲۰٪ به ۲۵٪ برود، فقط ۵٪ کارمزد می‌خورد.
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

# دسته‌ها، هم‌راستا با bourse.py
CATS = {
    "طلا": "ریتون زر زرفام زروان زرگر زریران زمرد طلا عیار قلک گلد قیراط "
           "لیان مثقال مهرگلد میراث ناب نفیس نگین‌فارس همیان کهربا گلدا "
           "گلدیس گنج گوهر",
    "نقره": "سیلور سیمین سیگلو نقرابی نقران نقرسا نقرفام نقرین پلاتا",
    "کالایی": "سافرون نهال سینرژی",
    "اهرمی": "اهرم بیدار توان جهش دوآیکس دوایکس شتاب موج نارنج پیشران",
    "سهامی": "آبنوس آتیمس آس آساس آمیتیس آوا آوان آوید آگاس ابتکار ارزش "
             "اطلس افق‌ملت الماس امتیاز انار اوج اکستریم اکسیژن بذر "
             "برلیان بزرگ تاراز ترمه تکپاد تیام ثروت‌ساز پادا پرتو پیروز",
}
SYM2CAT = {norm(s): c for c, ss in CATS.items() for s in ss.split()}


def periods(rows, mode, anchor):
    buck = defaultdict(list)
    for d, b in rows:
        if mode == "month":
            k = (d.year, d.month)
        else:
            k = (d - timedelta(days=(d.weekday() - anchor) % 7)).isoformat()
        buck[k].append((d, b))
    return buck


def build(files, mode, anchor, kind, cat, only=None):
    """{دوره: {نماد: (وضعیت، بازدهٔ دوره، نقدینگی)}} + فهرستِ دوره‌ها."""
    grid = defaultdict(dict)
    for f in files:
        sym = norm(f.stem.replace("_daily", ""))
        if is_fixed_income(sym):
            continue
        if only is not None and sym not in only:
            continue
        if cat and SYM2CAT.get(sym) != cat:
            continue
        rows = load_daily(f)
        if len(rows) < 80:
            continue
        buck = periods(rows, mode, anchor)
        ks = sorted(buck)
        for i in range(1, len(ks)):
            prev = [b for _d, b in buck[ks[i - 1]]]
            cur = buck[ks[i]]
            if len(prev) < 3 or not cur:
                continue
            box = make_box(kind, prev, ref_price=prev[-1].c)
            if box is None:
                continue
            ref = prev[-1].c
            st = state(ref, box)
            ret = cur[-1][1].c / ref          # ضریبِ رشدِ دوره
            liq = statistics.median([b.v * b.c for _d, b in cur]) or 0.0
            grid[ks[i]][sym] = (st, ret, liq)
    return grid, sorted(grid)


def run(grid, keys, mode, cost, core=0.0, topn=6, wcap=1.0):
    """چهار راه را با هم جلو می‌برد. خروجی: {نام: بازدهٔ درصدی}"""
    eq = {"هولد": 1.0, "نقدشو": 1.0, "چرخش": 1.0, "هسته+نوسان": 1.0}
    hold_state = set()               # نمادهایی که راهِ «نقدشو» نگه داشته
    w = {"نقدشو": {}, "چرخش": {}, "هسته+نوسان": {}}
    inmkt = {"نقدشو": 0, "چرخش": 0, "هسته+نوسان": 0}

    for k in keys:
        day = grid[k]
        if not day:
            continue
        syms = sorted(day)

        # ۱ هولد — هم‌وزنِ همه، بدون گردش
        eq["هولد"] *= statistics.mean([day[s][1] for s in syms])

        # کاندیدها: باکس مثبت، مرتب بر اساسِ نقدینگی
        up = [s for s in syms if day[s][0] == "بالا"]
        up.sort(key=lambda s: -day[s][2])
        pick = up[:topn]

        def step(name, target):
            """وزنِ هدف را اعمال کن، کارمزدِ گردش بگیر، دوره را سوار شو."""
            old = w[name]
            turn = sum(abs(target.get(s, 0) - old.get(s, 0))
                       for s in set(old) | set(target))
            eq[name] *= (1 - cost / 100.0 * turn / 2)
            g = sum(target.get(s, 0) * day[s][1] for s in syms)
            g += 1 - sum(target.values())      # بخشِ نقد، رشدِ صفر
            eq[name] *= g
            w[name] = target
            inmkt[name] += sum(target.values())

        # ۲ نقدشو — سهمِ هر نماد **جای خودش** را دارد. وقتی آن نماد
        #   بالای باکس رفت پر می‌شود، وقتی زیرِ باکس رفت نقد می‌شود و
        #   نقد می‌ماند تا **همان نماد** دوباره سیگنال بدهد. این دقیقاً
        #   همان «هر بار سیگنال آمد بخر، سیگنالِ عکس آمد بفروش» است.
        #   (اولین نسخه این را عیناً مثلِ چرخش نوشته بود و هر دو عددِ
        #   یکسان می‌دادند — در همان اولین اجرا لو رفت.)
        held = set(hold_state)
        for s in list(held):
            if s not in day or day[s][0] == "زیر":
                held.discard(s)
        for s in syms:
            if day[s][0] == "بالا":
                held.add(s)
        hold_state.clear()
        hold_state.update(held)
        slot = 1.0 / max(1, len(syms))
        step("نقدشو", {s: slot for s in held})

        # ۳ چرخش — همیشه در بازار تا وقتی حتی یک نماد مثبت است.
        #   پول از نمادِ منفی **بیرون** می‌آید و می‌رود روی مثبت‌ها،
        #   نه اینکه نقد بنشیند.
        # سقفِ وزنِ هر نماد. اگر کمتر از ۱/cap نماد واجد شرط باشد،
        # بقیه **نقد** می‌ماند — یعنی سقفِ تمرکز خودش نقد می‌سازد.
        if pick:
            wt = min(1.0 / len(pick), wcap)
            step("چرخش", {s: wt for s in pick})
        else:
            step("چرخش", {})

        # ۴ هسته + نوسان
        tgt = {s: core / len(syms) for s in syms}
        if pick:
            for s in pick:
                tgt[s] = tgt.get(s, 0) + (1 - core) / len(pick)
        step("هسته+نوسان", tgt)

    n = len(keys)
    return ({k: (v - 1) * 100 for k, v in eq.items()},
            {k: v / n * 100 for k, v in inmkt.items()}, n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_auto")
    ap.add_argument("--kind", default="poc_band")
    ap.add_argument("--cost", type=float, default=0.55)
    ap.add_argument("--core", type=float, default=0.5,
                    help="سهمِ همیشه-هولد در راهِ چهارم")
    ap.add_argument("--topn", type=int, default=6)
    ap.add_argument("--week-anchor", type=int, default=6)
    ap.add_argument("--syms", default=None,
                    help="فهرستِ نمادها با کاما — جهانِ محدود")
    ap.add_argument("--wcap", type=float, default=1.0,
                    help="سقفِ وزنِ هر نماد، مثلاً 0.2")
    ap.add_argument("--sweep-core", action="store_true",
                    help="نسبتِ هسته را از ۰ تا ۱۰۰ جارو کن")
    args = ap.parse_args()
    only = ({norm(x) for x in args.syms.split(",") if x.strip()}
            if args.syms else None)

    files = sorted(Path(args.data).glob("*.csv"))
    if not files:
        print(f"هیچ فایلی در {args.data} نبود.")
        return 1

    print(f"\n  باکس {args.kind} · کارمزد {args.cost:.2f}٪ روی گردش · "
          f"حداکثر {args.topn} نماد · هسته {args.core:.0%}")
    if only:
        print(f"  جهانِ محدود: {len(only)} نماد")

    # ── جاروی نسبتِ هسته ──────────────────────────────────────────
    # مصطفی: «چه نسبتی؟ پنجاه‌پنجاه؟ هفتاد سی؟»
    # ⚠️ این جارو روی **همان** ۴۶ هفته است که بقیهٔ اعداد از آن آمده.
    # بهترین خانه‌اش لزوماً بهترینِ آینده نیست — شکلِ منحنی را بخوان،
    # نه قلهٔ دقیقش.
    if args.sweep_core:
        grid, keys = build(files, "week", args.week_anchor,
                           args.kind, None, only)
        if len(keys) >= 4:
            print(f"\n  ══ نسبتِ هسته (هفتگی، {len(keys)} هفته) ══")
            print(f"  {'هسته':>6}{'نوسان':>8}{'بازده':>10}"
                  f"{'در بازار':>10}")
            print("  " + "─" * 36)
            for c in (0.0, 0.25, 0.4, 0.5, 0.6, 0.75, 1.0):
                res, inm, _n = run(grid, keys, "week", args.cost,
                                   c, args.topn, args.wcap)
                print(f"  {c:>5.0%}{1 - c:>8.0%}"
                      f"{res['هسته+نوسان']:>9.0f}٪"
                      f"{inm['هسته+نوسان']:>9.0f}٪")
        return 0

    for cat in [None] + sorted(CATS):
        name = cat or "همهٔ نمادها"
        line = []
        for mode, fa in (("week", "هفتگی"), ("month", "ماهانه")):
            grid, keys = build(files, mode, args.week_anchor,
                               args.kind, cat, only)
            if len(keys) < 4:
                continue
            res, inm, n = run(grid, keys, mode, args.cost,
                              args.core, args.topn, args.wcap)
            line.append((fa, res, inm, n))
        if not line:
            continue
        print(f"\n  ══ {name} ══")
        print(f"  {'دوره':<8}{'هولد':>10}{'نقدشو':>10}{'چرخش':>10}"
              f"{'هسته+نوسان':>14}{'n':>6}")
        print("  " + "─" * 60)
        for fa, res, inm, n in line:
            print(f"  {fa:<8}{res['هولد']:>9.0f}٪{res['نقدشو']:>9.0f}٪"
                  f"{res['چرخش']:>9.0f}٪{res['هسته+نوسان']:>13.0f}٪"
                  f"{n:>6}")
        best = max(line[0][1], key=line[0][1].get)
        print(f"  سهمِ سرمایه در بازار — نقدشو "
              f"{line[0][2]['نقدشو']:.0f}٪ · چرخش "
              f"{line[0][2]['چرخش']:.0f}٪ · هولد ۱۰۰٪")
        print(f"  بهترین ({line[0][0]}): **{best}**")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
