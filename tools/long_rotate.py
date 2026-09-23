# -*- coding: utf-8 -*-
"""چرخش روی پنجرهٔ بلند — آیا اندازهٔ جهان نتیجه را عوض می‌کند؟

`docs/17` روی ۴۶ هفته و ۱۳۳ نماد گفت چرخش +۳۳٫۸ واحد بالای طلا می‌دهد.
`docs/19` روی ۲۳۶ هفته ولی فقط **۲ نماد** گفت چرخش بدترین است (−۸۱).

دو توضیحِ ممکن برای این تناقض:
  الف) پنجرهٔ کوتاه خوش‌شانس بوده و چرخش واقعاً کار نمی‌کند
  ب) جهانِ دونمادی برای چرخش بی‌معناست — چرخش وقتی ارزش دارد که
     گزینه‌های زیادی باشد

این ابزار الف و ب را از هم جدا می‌کند: همان آزمون را روی جهان‌های
تودرتو اجرا می‌کند (۲ نماد، ۳، ۴، ۵، ۶) و هر بار پنجره را به
هم‌پوشانیِ همان مجموعه محدود می‌کند.

اگر با بزرگ شدنِ جهان نتیجه بهتر شود، (ب) درست است. اگر نه، (الف).

همه‌چیز **بر حسبِ طلا** سنجیده می‌شود، چون مصطفی همان را می‌خواهد.
"""
import argparse
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from monthly_backtest import load_daily  # noqa: E402
from vp_box import make_box, state  # noqa: E402
from vs_gold import load_gold, gold_at  # noqa: E402


def simulate(data, syms, ks, wk, mode, cost, wcap):
    eq = 1.0
    w = {}
    inmkt = 0.0
    n = 0
    for i in range(1, len(ks)):
        pd, cd = wk[ks[i - 1]], wk[ks[i]]
        if len(pd) < 3 or not cd:
            continue
        # ── بازدهِ هفته را **همیشه** حساب کن ───────────────────────
        # باگی که اینجا بود: اگر باکسِ یک نماد ساخته نمی‌شد، کلِ هفته
        # `continue` می‌شد و بازدهش از زنجیره می‌افتاد. ۶۰ هفته از ۲۶۵
        # (۲۳٪) این‌طور حذف می‌شدند و چون بازار در آن هفته‌ها بالا رفته
        # بود، **همهٔ** راه‌ها سیستماتیک کم برآورد می‌شدند: هولدِ
        # عیار+کهربا ‎+۶۰۸٪‎ درمی‌آمد در حالی که واقعی ‎+۲۱۴۱٪‎ است.
        #
        # درست: نداشتنِ باکس یعنی **تصمیمی گرفته نمی‌شود**، نه اینکه
        # پرتفو آن هفته وجود نداشته باشد. وزنِ قبلی نگه داشته می‌شود و
        # بازدهِ هفته روی آن می‌نشیند.
        ret, st = {}, {}
        for s in syms:
            if cd[-1] not in data[s]:
                continue
            prev = [data[s][d] for d in pd if d in data[s]]
            if not prev:
                continue
            ref = prev[-1].c
            ret[s] = data[s][cd[-1]].c / ref
            if len(prev) >= 3:
                box = make_box("poc_band", prev, ref_price=ref)
                if box is not None:
                    st[s] = state(ref, box)
        if len(ret) < len(syms):
            continue                      # قیمتِ هفته را نداریم
        n += 1
        if len(st) < len(syms):
            # تصمیم ممکن نیست — وزنِ قبلی بماند، بازده اعمال شود
            eq *= sum(w.get(s, 0) * ret[s] for s in syms) + 1 - sum(w.values())
            inmkt += sum(w.values())
            continue
        up = [s for s in syms if st[s] == "بالا"]
        if mode == "هولد":
            tgt = {s: 1.0 / len(syms) for s in syms}
        elif mode == "نقدشو":
            keep = [s for s in syms if st[s] != "زیر"]
            tgt = {s: 1.0 / len(syms) for s in keep}
        else:
            tgt = ({s: min(1.0 / len(up), wcap) for s in up}
                   if up else {})
        turn = sum(abs(tgt.get(s, 0) - w.get(s, 0)) for s in syms)
        eq *= (1 - cost / 100.0 * turn / 2)
        eq *= sum(tgt.get(s, 0) * ret[s] for s in syms) + 1 - sum(tgt.values())
        w = tgt
        inmkt += sum(tgt.values())
    return eq, (inmkt / n * 100 if n else 0), n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_long")
    ap.add_argument("--cost", type=float, default=0.55)
    ap.add_argument("--wcap", type=float, default=0.34)
    ap.add_argument("--anchor", type=int, default=6)
    args = ap.parse_args()

    gold = load_gold()
    files = sorted(Path(args.data).glob("*_daily.csv"))
    data, first = {}, {}
    for f in files:
        sym = f.stem.replace("_daily", "")
        rows = load_daily(f)
        if len(rows) < 120:
            continue
        data[sym] = {d: b for d, b in rows}
        first[sym] = rows[0][0]

    # از بلندترین تاریخچه به کوتاه‌ترین — جهان‌های تودرتو
    order = sorted(data, key=lambda s: first[s])
    print(f"\n  تاریخچهٔ هر نماد:")
    for s in order:
        print(f"    {s:<10} از {first[s]}  ({len(data[s])} کندل)")

    print(f"\n  کارمزد {args.cost}٪ روی گردش · سقفِ وزن {args.wcap:.0%}")
    print(f"\n  {'جهان':<6}{'از':<12}{'هفته':>6}{'هولد':>9}"
          f"{'نقدشو':>9}{'چرخش':>9}{'طلا':>9}   بهترین")
    print("  " + "─" * 74)

    for k in range(2, len(order) + 1):
        syms = order[:k]
        start = max(first[s] for s in syms)
        days = sorted(set.intersection(
            *[set(d for d in data[s] if d >= start) for s in syms]))
        if len(days) < 150:
            continue
        wk = defaultdict(list)
        for d in days:
            wk[d - timedelta(days=(d.weekday() - args.anchor) % 7)].append(d)
        ks = sorted(wk)

        g0, g1 = gold_at(gold, days[0]), gold_at(gold, days[-1])
        if not g0 or not g1:
            continue
        g = g1 / g0
        res = {}
        for m in ("هولد", "نقدشو", "چرخش"):
            e, _sh, n = simulate(data, syms, ks, wk, m, args.cost, args.wcap)
            res[m] = (e / g - 1) * 100
        best = max(res, key=res.get)
        if max(res.values()) < 0:
            best = "طلا"
        print(f"  {k:<6}{str(days[0]):<12}{len(ks):>6}"
              f"{res['هولد']:>+8.0f}٪{res['نقدشو']:>+8.0f}٪"
              f"{res['چرخش']:>+8.0f}٪{0:>+8.0f}٪   {best}")
        print(f"        ({'، '.join(syms)})")
    print("\n  همهٔ اعداد **بالای طلا**اند. صفر یعنی هم‌پای طلا.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
