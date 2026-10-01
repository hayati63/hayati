# -*- coding: utf-8 -*-
"""دو سناریوی مصطفی، با جهانِ معاملاتیِ خودش.

او **قبل از دیدنِ نتیجه** گفت چه چیزی معامله می‌کند — که مهم است، چون
انتخاب از روی گذشته نیست:

    اهرمی : دوایکس (شتابش خوب است)
    طلا   : عیار، کهربا
    انرژی : سینرژی

و دو سناریو:

**الف) سبدِ ثابت، نوسان‌گیریِ درون‌سبدی.** مثلاً ۵۰٪ طلا و ۵۰٪ سهام.
   روی سهمِ طلا نوسان می‌گیری (باکس منفی → نقد، باکس مثبت → ورود) تا
   **تعدادِ واحد** بیشتر شود. پول بینِ دو سبد **جابه‌جا نمی‌شود**.

**ب) چرخشِ کامل.** از یک بازار کاملاً خارج شو، وارد بازارِ دیگر شو.

معیار: بر حسبِ طلا، چون هدفِ او زدنِ طلاست.

⚠️ سناریوی الف داخلِ هر سبد **نقد** می‌شود. تجزیهٔ `docs/20` نشان داد
هفته‌های «زیرِ باکس» در پنجرهٔ بلند مثبت‌اند، پس انتظار می‌رود این
ضرر بدهد — ولی خودش خواست تستش کنم، و نتیجه باید اندازه‌گیری شود نه
حدس زده.
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

SLEEVE = {"طلا": ["عیار", "کهربا"], "سهام": ["دوایکس", "سینرژی"]}


def build(data, syms, anchor):
    days = sorted(set.intersection(*[set(data[s]) for s in syms]))
    wk = defaultdict(list)
    for d in days:
        wk[d - timedelta(days=(d.weekday() - anchor) % 7)].append(d)
    return days, wk, sorted(wk)


def states(data, syms, pd, cd):
    st, ret = {}, {}
    for s in syms:
        prev = [data[s][d] for d in pd if d in data[s]]
        if len(prev) < 3 or cd[-1] not in data[s]:
            return None, None
        ref = prev[-1].c
        ret[s] = data[s][cd[-1]].c / ref
        box = make_box("poc_band", prev, ref_price=ref)
        st[s] = state(ref, box) if box else "؟"
    return st, ret


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_long")
    ap.add_argument("--cost", type=float, default=0.55)
    ap.add_argument("--anchor", type=int, default=6)
    ap.add_argument("--syms", default="عیار,کهربا,دوایکس,سینرژی")
    args = ap.parse_args()

    gold = load_gold()
    syms = [x.strip() for x in args.syms.split(",")]
    data = {}
    for s in syms:
        p = Path(args.data) / f"{s}_daily.csv"
        if not p.exists():
            print(f"  {s}: فایل نیست")
            return 1
        data[s] = {d: b for d, b in load_daily(p)}
    days, wk, ks = build(data, syms, args.anchor)
    g = gold_at(gold, days[-1]) / gold_at(gold, days[0])
    print(f"\n  {'، '.join(syms)}")
    print(f"  {days[0]} تا {days[-1]} · {len(ks)} هفته · "
          f"طلا {(g - 1) * 100:+.0f}٪\n")

    sleeves = {k: [s for s in v if s in syms] for k, v in SLEEVE.items()}
    sleeves = {k: v for k, v in sleeves.items() if v}

    res = {}
    for mode in ("هولد", "الف: سبدِ ثابت", "ب: چرخشِ کامل",
                 "ب۲: چرخشِ پر"):
        eq = 1.0
        w = {}
        for i in range(1, len(ks)):
            pd, cd = wk[ks[i - 1]], wk[ks[i]]
            if len(pd) < 3 or not cd:
                continue
            st, ret = states(data, syms, pd, cd)
            if st is None:
                continue
            if mode == "هولد":
                tgt = {s: 1.0 / len(syms) for s in syms}
            elif mode.startswith("الف"):
                # هر سبد نصفِ پول، و **داخلِ سبد** نوسان‌گیری
                tgt = {}
                for _name, mem in sleeves.items():
                    share = 1.0 / len(sleeves)
                    ok = [s for s in mem if st[s] != "زیر"]
                    for s in ok:
                        tgt[s] = share / len(ok)
                    # اگر همهٔ اعضای سبد زیر بودند → آن سبد نقد
            elif mode.startswith("ب:"):
                up = [s for s in syms if st[s] == "بالا"]
                tgt = {s: 1.0 / len(up) for s in up} if up else {}
            else:
                up = [s for s in syms if st[s] == "بالا"]
                tgt = ({s: 1.0 / len(up) for s in up} if up
                       else {s: 1.0 / len(syms) for s in syms})
            turn = sum(abs(tgt.get(s, 0) - w.get(s, 0)) for s in syms)
            eq *= (1 - args.cost / 100.0 * turn / 2)
            eq *= sum(tgt.get(s, 0) * ret[s] for s in syms) \
                + 1 - sum(tgt.values())
            w = tgt
        res[mode] = ((eq - 1) * 100, (eq / g - 1) * 100)

    print(f"  {'راه':<18}{'ریالی':>10}{'نسبت به طلا':>14}")
    print("  " + "─" * 44)
    for k, (r, rel) in res.items():
        print(f"  {k:<18}{r:>+9.0f}٪{rel:>+13.0f}٪")
    print(f"  {'طلا':<18}{(g - 1) * 100:>+9.0f}٪{0:>+13.0f}٪")
    best = max(res, key=lambda k: res[k][1])
    print(f"\n  بهترین: **{best if res[best][1] > 0 else 'طلا'}**")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
