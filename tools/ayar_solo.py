# -*- coding: utf-8 -*-
"""فقط عیار — هولد در برابر خرید و فروش، با قاعدهٔ ورودِ خودِ مصطفی.

مصطفی: «فقط عیار را ببین. هولدش کنی چقدر سود می‌دهد، یا بر اساس
استراتژی خرید و فروش کنی چقدر. … و نکته این است که ما باید روی باکسِ
حمایتی بخریم یا یک‌کم بالاترش. اگر فاصله از زیر ۳ درصد بود بخریم،
اگر بیشتر از ۳ درصد بود صبر کنیم پایین‌تر بیاید.»

## چرا عیار تنها، و چرا این تست تمیز است

عیار همبستگیِ شدید با طلای ۱۸ دارد (بازدهِ روزانه +۰٫۶۶، و از ۲۰۲۱
مجموعِ اختلاف +۱۲ واحد). پس «هولدِ عیار ≈ طلا». اگر معامله کردنِ عیار
از هولدِ عیار جلو بزند، یعنی **تعدادِ واحد** بیشتر شده — و این دقیقاً
همان چیزی است که او می‌خواهد.

## فرقِ این تست با `hold_vs_trade.py`

آنجا ورود روی **کلوزِ روزِ تصمیم** بود. اینجا ورود روی **پولبک به
نوارِ خرید** است — همان چیزی که او همیشه گفته و تا حالا در آزمونِ
هولد-در-برابر-معامله مدل نشده بود.

و مهم‌تر: **اگر پولبک نزند، وارد نمی‌شوی.** («حمایت خالی».) این را
هم می‌شمارد، چون جا ماندن هزینه دارد و نباید پنهان شود.

## قاعده

    کلوزِ هفتهٔ تصمیم بالای باکس  → سفارشِ خرید روی سقفِ باکس + offset
    در هفتهٔ بعد اگر کفِ روز به آن قیمت رسید → پر می‌شود
    اگر نرسید → آن هفته بیرون می‌مانی
    کلوزِ هفتهٔ تصمیم زیرِ باکس   → می‌فروشی (روی کلوز)

`--offset` درصدِ بالای سقفِ باکس است. ۰ یعنی دقیقاً روی سقف.
`--max-dist` قاعدهٔ «اگر بیشتر از X درصد دور بود صبر کن» را پیاده
می‌کند: اگر قیمتِ فعلی بیشتر از این از نوار فاصله دارد، آن هفته
سفارش نمی‌گذاریم.
"""
import argparse
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from monthly_backtest import load_daily  # noqa: E402
from vp_box import make_box, state  # noqa: E402


def weeks(rows, anchor=6, mode="week"):
    b = defaultdict(list)
    for d, bar in rows:
        k = ((d.year, d.month) if mode == "month"
             else d - timedelta(days=(d.weekday() - anchor) % 7))
        b[k].append((d, bar))
    return [(k, b[k]) for k in sorted(b)]


def run(rows, offset, max_dist, cost, mode="week"):
    ps = weeks(rows, mode=mode)
    eq = 1.0
    units = 1.0 / rows[0][1].c      # واحدهایی که با ۱ ریال می‌خری
    holding = False
    fills = misses = sells = 0
    for i in range(1, len(ps)):
        prev = [b for _d, b in ps[i - 1][1]]
        cur = ps[i][1]
        if len(prev) < 3 or not cur:
            continue
        box = make_box("poc_band", prev, ref_price=prev[-1].c)
        if box is None:
            continue
        ref = prev[-1].c
        st = state(ref, box)

        if holding and st == "زیر":
            eq *= (1 - cost / 100.0)
            holding = False
            sells += 1
        elif not holding and st == "بالا":
            # قیمتِ سفارش: سقفِ باکس + offset
            want = box[1] * (1 + offset / 100.0)
            # اگر قیمتِ فعلی خیلی بالاتر از نوار است، صبر کن
            if max_dist is not None and (ref / want - 1) * 100 > max_dist:
                misses += 1
            else:
                lo = min(b.l for _d, b in cur)
                if lo <= want:                    # پولبک زد → پر شد
                    eq *= (1 - cost / 100.0)
                    # از قیمتِ پرشدن تا پایانِ هفته
                    eq *= cur[-1][1].c / want
                    holding = True
                    fills += 1
                    continue
                misses += 1
        if holding:
            eq *= cur[-1][1].c / ref
    hold = rows[-1][1].c / rows[0][1].c
    return (eq - 1) * 100, (hold - 1) * 100, fills, misses, sells


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sym", default="عیار")
    ap.add_argument("--data", default="data_long")
    ap.add_argument("--cost", type=float, default=0.55)
    ap.add_argument("--from", dest="frm", default=None)
    args = ap.parse_args()

    rows = load_daily(Path(args.data) / f"{args.sym}_daily.csv")
    if args.frm:
        from datetime import date
        y, m, d = (int(x) for x in args.frm.split("-"))
        rows = [(dd, b) for dd, b in rows if dd >= date(y, m, d)]
    print(f"\n  {args.sym} · {rows[0][0]} تا {rows[-1][0]} "
          f"({len(rows)} روز) · کارمزد {args.cost}٪")

    for mode, fa in (("week", "هفتگی"), ("month", "ماهانه")):
        print(f"\n  ══ تصمیمِ {fa} ══")
        print(f"  {'ورود':<22}{'استراتژی':>11}{'هولد':>10}"
              f"{'اختلاف':>10}{'پر شد':>8}{'جا ماند':>9}")
        print("  " + "─" * 70)
        for off, md, lbl in ((0.0, None, "روی سقفِ باکس"),
                             (1.0, None, "‎+۱٪ بالای سقف"),
                             (2.0, None, "‎+۲٪ بالای سقف"),
                             (3.0, None, "‎+۳٪ بالای سقف"),
                             (0.0, 3.0, "روی سقف، فقط اگر <۳٪ دور"),
                             (2.0, 3.0, "‎+۲٪، فقط اگر <۳٪ دور")):
            s, h, f, m, sl = run(rows, off, md, args.cost, mode)
            mark = "✓" if s > h else ""
            print(f"  {lbl:<22}{s:>+10.0f}٪{h:>+9.0f}٪{s - h:>+9.0f}"
                  f"{f:>8}{m:>9} {mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
