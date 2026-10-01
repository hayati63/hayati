# -*- coding: utf-8 -*-
"""پرتفوی پیشنهادی فردا — ماهانه × هفتگی × ریسک × اندازه.

هر نماد چهار چیز را هم‌زمان باید داشته باشد:
  ۱. بالای باکس **ماه قبل**     — سیگنالی که p=۰٫۰۰۰۴ دارد
  ۲. بالای باکس **هفتهٔ قبل**   — سیگنالی که p=۰٫۰۰۰۳ دارد
  ۳. ریسک کم تا متوسط           — جدول بخش ۱۰: بهترین بازده در ۲–۴٪
  ۴. اندازه و حجم کافی          — خروج زیر ۲ روز در سایز هدف

⚠️ بخش ۱۸ نشان داد «هر دو بالا» مزیتِ **بیشتری** از «فقط هفتگی» ندارد.
پس این فیلتر برای **بازده بیشتر** نیست، برای **ریسک کمتر** است: نمادی که
هر دو افقش بالای حمایت است، حمایتِ نزدیک‌تری زیر پایش دارد.
"""
import argparse
import json
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path

from monthly_backtest import load_daily, is_fixed_income, norm
from vp_box import make_box, state
from weekly_backtest import week_key
from drivers import group_of, EXPOSURE, OVERRIDE
from target_portfolio import FACTOR, factor_of, _fill
from breadth import box_states, DRIVER_FILE


def read_holdings(path):
    out = {}
    p = Path(path)
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(.+?)[\s,،\t]+([\d.,]+)$", line)
        if m:
            k = m.group(1).strip()
            try:
                out[k] = out.get(k, 0) + float(
                    m.group(2).replace(",", "").replace("،", ""))
            except ValueError:
                pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_auto")
    ap.add_argument("--holdings", default="data/holdings.txt")
    ap.add_argument("--kind", default="valley_first")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--max-weight", type=float, default=12.0)
    ap.add_argument("--max-group", type=float, default=30.0)
    ap.add_argument("--w-eq", type=float, default=60.0)
    ap.add_argument("--max-exit-days", type=float, default=2.0)
    ap.add_argument("--participation", type=float, default=0.20)
    ap.add_argument("--min-n", type=int, default=3)
    ap.add_argument("--drivers", default="data/drivers_daily")
    ap.add_argument("--min-breadth", type=float, default=50.0,
                    help="کمینه درصد اعضای گروه که باید بالای باکس هفتگی "
                         "باشند. صندوق‌های یک گروه همگرایی بالایی دارند، پس "
                         "نمادِ مثبت در گروهی که اکثرش منفی است عقب‌افتاده "
                         "است، نه پیشرو. ۰ یعنی این قید خاموش")
    ap.add_argument("--require-driver", action="store_true",
                    help="محرکِ اصلیِ گروه هم باید بالای باکس هفتگی باشد")
    ap.add_argument("--require-cur-month", action="store_true", default=True,
                    help="باکسِ ماهِ **جاری** (اول ماه میلادی تا امروز) هم "
                         "باید بالا باشد. قاعدهٔ مصطفی روی نقران. "
                         "اندازه‌گیری (tools/curmonth_filter.py): مزیت از "
                         "+۰٫۳۹۹ به +۰٫۴۶۷ می‌رود ولی t از ۰٫۹۷ به ۰٫۸۴ "
                         "می‌افتد و ۲۱٪ سیگنال حذف می‌شود — شاهدِ محکمی "
                         "نیست، قاعدهٔ اوست. با --no-cur-month خاموش")
    ap.add_argument("--no-cur-month", dest="require_cur_month",
                    action="store_false")
    ap.add_argument("--one-per-group", action="store_true", default=True,
                    help="از هر گروه فقط **یک** نماد، و آن بزرگ‌ترین بر "
                         "اساس ارزشِ معاملاتِ روزانه. قاعدهٔ مصطفی: «اینا "
                         "همشون همگرایی دارن... بزرگ‌ترینش رو بگو که توی "
                         "صف خرید و فروش یا حجمش گیر نکنم.» داده تأییدش "
                         "کرد: چهار صندوق طلا با گواهی شمش ۰٫۸۹ تا ۰٫۹۲ "
                         "همبسته‌اند، پس دو تا برداشتن ریسک را پخش نمی‌کند "
                         "— فقط دو بار کارمزد می‌دهد و نقدشوندگی را بدتر "
                         "می‌کند. با --many خاموش")
    ap.add_argument("--many", dest="one_per_group", action="store_false")
    ap.add_argument("--min-value", type=float, default=500.0,
                    help="کمینه ارزشِ معاملاتِ روزانه، میلیارد ریال. "
                         "مصطفی پتروآبان (۱۱۸) و پتروما (۱۹) را رد کرد چون "
                         "در صف گیر می‌کند؛ مدلِ قبلیِ نقدشوندگی اجازه "
                         "می‌داد چون فقط «چند روز تا خروج» را می‌دید و "
                         "صف را نمی‌دید. ۰ یعنی خاموش")
    ap.add_argument("--sticky", action="store_true", default=True,
                    help="نمادی که همین حالا داریم و هنوز واجد شرط است "
                         "سر جایش می‌ماند، حتی اگر رتبه‌اش پایین باشد. "
                         "`tools/walkforward.py` نشان داد چسبندگی گردش را "
                         "از ۱۱۱٪ به ۷۸٪ می‌آورد و بازده سالانه را از "
                         "+۲۸٫۴٪ به +۳۸٫۵٪ می‌برد — چون کارمزد بزرگ‌ترین "
                         "هزینهٔ این سیستم است. با --no-sticky خاموش")
    ap.add_argument("--no-sticky", dest="sticky", action="store_false")
    ap.add_argument("--keep-bonus", type=float, default=1.6,
                    help="امتیازِ ماندنِ نمادی که همین حالا در پرتفو هست و "
                         "هنوز واجد شرط است، برحسب واحدِ ریسک (درصد فاصله "
                         "تا حمایت). چرا ۱٫۶: کارمزد رفت‌وبرگشت صندوق "
                         "۰٫۵۵٪ است و **قطعی**، ولی فاصلهٔ بیشترِ استاپ "
                         "فقط وقتی خرج می‌شود که استاپ بخورد — حدود ۳۵٪ "
                         "مواقع (۵۳ استاپ از ۱۵۱ معاملهٔ پرشده، "
                         "data/evidence_month.json). پس ۰٫۵۵ ÷ ۰٫۳۵ ≈ ۱٫۶ "
                         "واحد ریسک هم‌ارزِ کارمزدِ تعویض است. ۰ یعنی خاموش")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    cat = {}
    tp = root / "data/extracted/TODAY.json"
    if tp.exists():
        for r in json.loads(tp.read_text(encoding="utf-8")):
            cat[norm(r["نماد"])] = r["دسته"]

    recs, fps, norms = {}, {}, {}
    for p in sorted(Path(args.data).glob("*.csv")):
        name = p.stem.replace("_daily", "").replace("_", " ")
        rows = load_daily(p)
        if len(rows) < 40:
            continue
        fp = tuple((d.isoformat(), round(b.c, 6)) for d, b in rows)
        if fp in fps or norm(name) in norms:
            continue
        fps[fp] = norms[norm(name)] = name
        if is_fixed_income(name):
            continue

        by_m, by_w = defaultdict(list), defaultdict(list)
        for d, b in rows:
            by_m[(d.year, d.month)].append((d, b))
            if d.weekday() not in (3, 4):
                by_w[week_key(d)].append((d, b))
        ms, ws = sorted(by_m), sorted(by_w)
        if len(ms) < 3 or len(ws) < 3:
            continue

        close = rows[-1][1].c
        last = rows[-1][0]

        # باکس ماهِ کامل‌شدهٔ قبل و هفتهٔ کامل‌شدهٔ قبل
        mbox = (make_box(args.kind, [x for _, x in by_m[ms[-2]]],
                         by_m[ms[-2]][-1][1].c)
                if len(by_m[ms[-2]]) >= 5 else None)
        wprev = by_w[ws[-2]]
        wbox = (make_box(args.kind, [x for _, x in wprev], wprev[-1][1].c)
                if len(wprev) >= 3 else None)
        if not mbox or not wbox:
            continue

        # سابقه: ماه‌های «بالای باکس ماهانه»
        hist = []
        for i in range(len(ms) - 1):
            a, b = ms[i], ms[i + 1]
            nxt = (a[0] + 1, 1) if a[1] == 12 else (a[0], a[1] + 1)
            if b != nxt or len(by_m[a]) < 5 or len(by_m[b]) < 2:
                continue
            bx = make_box(args.kind, [x for _, x in by_m[a]],
                          by_m[a][-1][1].c)
            if not bx:
                continue
            e, x = by_m[b][0][1].c, by_m[b][-1][1].c
            if state(e, bx) == "بالا":
                hist.append((x - e) / e * 100)

        vols = [b.v for _, b in rows[-20:] if b.v]
        c = cat.get(norm(name), "سهامی")
        g = group_of(name, c)
        recs[name] = {
            "sym": name, "cat": c, "group": g, "factor": factor_of(g),
            "close": close, "date": last,
            "mst": state(close, mbox), "wst": state(close, wbox),
            "mrisk": (close - mbox[0]) / close * 100,
            "wrisk": (close - wbox[0]) / close * 100,
            "mbox": mbox, "wbox": wbox,
            # باکسِ ماهِ **جاری** — از اول ماه میلادی تا امروز. مصطفی
            # روی نقران گرفت که این می‌تواند مقاومتِ بالای سر بسازد در
            # حالی که ماهِ قبل و هفتگی هر دو مثبت‌اند.
            "cur_box": (make_box(args.kind, [x for _, x in by_m[ms[-1]]],
                                 by_m[ms[-1]][-1][1].c)
                        if len(by_m[ms[-1]]) >= 3 else None),
            "cur_days": len(by_m[ms[-1]]),
            "n": len(hist),
            "avg": statistics.mean(hist) if hist else None,
            "win": (sum(1 for x in hist if x > 0) / len(hist) * 100)
            if hist else None,
            "med_vol": statistics.median(vols) if vols else None,
            "value": (statistics.median([b.v * b.c for _, b in rows[-20:]
                                         if b.v]) if vols else None),
        }

    if not recs:
        print("دادهٔ کافی نبود.")
        return 1

    # ── انقباض امتیاز به میانگین گروه ──
    gsum = defaultdict(list)
    for r in recs.values():
        if r["avg"] is not None:
            gsum[r["group"]].append(r["avg"])
    gmean = {k: statistics.mean(v) for k, v in gsum.items() if v}
    allv = [x for v in gsum.values() for x in v]
    overall = statistics.mean(allv) if allv else 0.0
    K = 3.0
    for r in recs.values():
        prior = gmean.get(r["group"], overall)
        r["score"] = ((r["n"] * r["avg"] + K * prior) / (r["n"] + K)
                      if r["avg"] is not None else prior) - overall

    holds = read_holdings(args.holdings)
    capital = sum(n * recs[s]["close"] for s, n in holds.items()
                  if s in recs) or 1e9

    # ── پهنای گروه و وضعیت محرک‌ها ──
    grp_all = defaultdict(list)
    for r in recs.values():
        grp_all[r["group"]].append(r)
    breadth = {g: sum(1 for x in v if x["wst"] == "بالا") / len(v) * 100
               for g, v in grp_all.items()}

    drv = {}
    for did, fn in DRIVER_FILE.items():
        dp = Path(args.drivers) / f"{fn}_daily.csv"
        if dp.exists():
            st = box_states(load_daily(dp), args.kind)
            if st:
                drv[did] = st

    def driver_ok(g, sym=None):
        """محرکِ با بیشترین وزن در این گروه — بالای باکس هفتگی است؟

        اگر باکسِ هفتگیِ محرک از کمتر از ۲۰ کندل ساخته شده باشد **حکم
        نمی‌دهیم** و `None` برمی‌گردانیم. دلیلش در `breadth.py` نوشته
        شده: با کندل روزانه یک هفته ۵ تا ۷ کندل دارد و آن پروفایل
        قابل‌اتکا نیست. تا وقتی H1 نرسیده، این ستون فقط خبر است نه حکم.
        """
        exp = OVERRIDE.get(sym) or EXPOSURE.get(g, {})
        for did in sorted(exp, key=lambda k: -exp[k]):
            if did in drv:
                d = drv[did]
                if not d.get("wok"):
                    return None, did, None
                return d["wst"] == "بالا", did, d["wst"]
        return None, None, None

    # ── واجد شرط: هر دو بالا، سابقهٔ کافی، حجم کافی ──
    elig = []
    for r in recs.values():
        if r["mst"] != "بالا" or r["wst"] != "بالا":
            continue
        # شرطِ «امتیاز بالای میانگین» عمداً برداشته شد: با تعریف، نصف
        # جهان را حذف می‌کند و چیزی به سیگنال اضافه نمی‌کند. امتیاز برای
        # **مرتب‌کردن و وزن‌دهی** است، نه برای رد کردن.
        if r["n"] < args.min_n:
            continue
        if not r["med_vol"]:
            continue
        # ── شرطِ ماهِ جاری ──
        # باکسِ ماه میلادیِ جاری، فقط از کندل‌های تا امروز. اگر قیمت
        # زیرش باشد یعنی از اولِ ماه مقاومتی بالای سرش ساخته شده.
        # مصطفی روی نقران گرفت: ماه قبل بالا، هفتگی بالا، ولی ماه جاری
        # ۱۲٬۷۳۵–۱۲٬۸۹۹ و قیمت ۱۲٬۴۴۱ — زیرِ مقاومت.
        if args.require_cur_month:
            cb = r.get("cur_box")
            if cb is not None and state(r["close"], cb) != "بالا":
                continue
        r["breadth"] = breadth.get(r["group"], 0.0)
        ok, did, dst = driver_ok(r["group"], r["sym"])
        r["driver"], r["driver_st"], r["driver_ok"] = did, dst, ok
        # قید پهنای گروه فقط وقتی معنا دارد که نماد واقعاً با گروهش
        # حرکت کند. سینرژی برچسب «سهامی» دارد ولی همبستگی‌اش با شاخص کل
        # **−۰٫۱۷** است — یعنی ضدِ گروهش حرکت می‌کند. پهنای «سهامی» را
        # به آن تحمیل کردن همان اشتباهی است که مصطفی روی محرکش گرفت، یک
        # پله جلوتر. نمادی که در OVERRIDE هست، از این قید معاف است.
        r["breadth_exempt"] = r["sym"] in OVERRIDE
        if (args.min_breadth > 0 and r["breadth"] < args.min_breadth
                and not r["breadth_exempt"]):
            continue
        if args.require_driver and ok is not True:
            continue
        r["risk"] = min(r["mrisk"], r["wrisk"])   # نزدیک‌ترین حمایت
        # وزن باید مثبت بماند حتی برای نمادی که امتیازش زیر میانگین است،
        # وگرنه _fill وزن منفی پخش می‌کند.
        r["raw_w"] = max(0.15, r["score"] + 8.0) / max(r["risk"], 1.5)
        elig.append(r)
    elig.sort(key=lambda r: r["risk"])

    d = max(r["date"] for r in recs.values())
    print("=" * 78)
    print(f"پرتفوی پیشنهادی — کلوز {d:%Y-%m-%d}")
    print(f"جهان: {len(recs)} نماد · واجد شرط (ماهانه بالا **و** هفتگی بالا): "
          f"{len(elig)}")
    print("=" * 78)

    if args.min_breadth > 0:
        print(f"قید پهنای گروه: حداقل {args.min_breadth:.0f}٪ اعضا بالای "
              f"باکس هفتگی")
    print(f"\n{'نماد':<11}{'گروه':<13}{'کلوز':>11}{'ریسک':>7}"
          f"{'ماهانه':>8}{'هفتگی':>8}{'پهنا':>7}{'محرک':>16}{'n':>4}{'برد':>7}")
    print("─" * 78)
    for r in elig:
        wn = "—" if r["win"] is None else f"{r['win']:.0f}٪"
        ds = ("—" if not r["driver"] else
              f"{r['driver']}:{ {'بالا':'✓','داخل':'~','زیر':'✗'}.get(r['driver_st'],'؟') }")
        print(f"{r['sym']:<11}{r['group']:<13}{r['close']:>11,.0f}"
              f"{r['risk']:>7.2f}{r['mrisk']:>8.1f}{r['wrisk']:>8.1f}"
              f"{r['breadth']:>6.0f}٪{ds:>16}{r['n']:>4}{wn:>7}")

    # ── وزن‌دهی با سلّه و سقف‌ها و نقدشوندگی ──
    budgets = ({"سهام‌محور": 100.0} if args.w_eq >= 99.99
               else {"سهام‌محور": args.w_eq, "فلزات": 100.0 - args.w_eq})
    per_group = max(1, math.ceil(args.n * args.max_group / 100))
    picks, gc = [], defaultdict(int)
    # ترتیبِ انتخاب ≠ ترتیبِ نمایش: نمادی که همین حالا داریم به اندازهٔ
    # کارمزدِ تعویض جلو می‌افتد، وگرنه سیستم هر هفته یک صندوق طلا را با
    # صندوق طلای دیگری عوض می‌کند و کارمزد، مزیتِ نازک را می‌خورد
    # (بند ۹ CLAUDE.md).
    order = sorted(elig, key=lambda r: r["risk"]
                   - (args.keep_bonus if r["sym"] in holds else 0.0))
    if args.min_value > 0:
        thin = [r for r in elig
                if r["med_vol"] * r["close"] / 1e9 < args.min_value]
        if thin:
            print(f"\n⚠️ {len(thin)} نماد زیر آستانهٔ نقدشوندگی "
                  f"({args.min_value:.0f} میلیارد ریال در روز) حذف شد:")
            for r in sorted(thin, key=lambda x: -x["med_vol"] * x["close"]):
                print(f"   {r['sym']:<10} "
                      f"{r['med_vol']*r['close']/1e9:>8,.0f} میلیارد/روز")
            elig = [r for r in elig if r not in thin]
            order = [r for r in order if r not in thin]
    if args.one_per_group:
        # از هر گروه فقط پرگردش‌ترین
        best = {}
        for r in elig:
            g = r["group"]
            v = r["med_vol"] * r["close"]
            if g not in best or v > best[g][0]:
                best[g] = (v, r)
        keep = {id(r) for _, r in best.values()}
        order = [r for r in order if id(r) in keep]
    if args.sticky:
        # نمادهایی که داریم و هنوز واجد شرط‌اند اول صف. تعویضِ یک صندوق
        # طلا با صندوق طلای دیگر ۰٫۵۵٪ خرج دارد و صفر چیز عوض می‌کند —
        # همبستگی روزانه‌شان با گواهی شمش طلا ۰٫۸۹ تا ۰٫۹۲ است.
        order = ([r for r in order if r["sym"] in holds]
                 + [r for r in order if r["sym"] not in holds])
    for fac, bud in budgets.items():
        want = max(1, round(args.n * bud / 100))
        taken = 0
        for r in order:
            if r["factor"] != fac or taken >= want:
                continue
            if gc[r["group"]] >= per_group:
                continue
            picks.append(r)
            gc[r["group"]] += 1
            taken += 1
        if taken < want:
            print(f"\n⚠️ سلّهٔ «{fac}»: فقط {taken} نماد از {want} واجد شرط بود.")

    liq_cap = {r["sym"]: (r["med_vol"] * args.participation
                          * args.max_exit_days * r["close"] / capital * 100)
               for r in picks if r["med_vol"]}
    fixed = {}
    for fac, bud in budgets.items():
        mem = [r for r in picks if r["factor"] == fac]
        if mem:
            fixed.update(_fill(mem, bud, args.max_weight, args.max_group,
                               liq_cap))
    for r in picks:
        r["w"] = fixed.get(r["sym"], 0.0)
    cash = max(0.0, 100 - sum(r["w"] for r in picks))

    print("\n" + "=" * 78)
    print(f"وزن پیشنهادی — سرمایه {capital/1e9:,.1f} میلیارد ریال")
    print("=" * 78)
    print(f"{'نماد':<11}{'گروه':<13}{'٪':>6}{'مبلغ(م ر)':>12}"
          f"{'تعداد واحد':>14}{'ریسک':>7}{'روز خروج':>10}")
    print("─" * 78)
    for r in sorted(picks, key=lambda r: -r["w"]):
        if r["w"] <= 0:
            continue
        amt = capital * r["w"] / 100
        units = amt / r["close"]
        ed = units / (r["med_vol"] * args.participation) if r["med_vol"] else None
        print(f"{r['sym']:<11}{r['group']:<13}{r['w']:>6.1f}{amt/1e6:>12,.0f}"
              f"{units:>14,.0f}{r['risk']:>7.2f}"
              f"{(f'{ed:.2f}' if ed is not None else '—'):>10}")
    print("─" * 78)
    inv = sum(r["w"] for r in picks)
    print(f"{'جمع':<11}{'':<13}{inv:>6.1f}{capital*inv/100/1e6:>12,.0f}")
    if cash > 0.05:
        print(f"{'نقد':<11}{'':<13}{cash:>6.1f}{capital*cash/100/1e6:>12,.0f}")
    gw = defaultdict(float)
    for r in picks:
        gw[r["group"]] += r["w"]
    print("\nگروه: " + " · ".join(f"{k} {v:.0f}٪" for k, v in
                                  sorted(gw.items(), key=lambda kv: -kv[1])))

    # ── تبدیل از پرتفوی فعلی ──
    if holds:
        print("\n" + "=" * 78)
        print("چه چیزی را به چه چیزی تبدیل کن")
        print("=" * 78)
        tgt = {r["sym"]: r["w"] for r in picks}
        rowsx = []
        for s in set(tgt) | set(holds):
            if s not in recs:
                continue
            px = recs[s]["close"]
            cw = holds.get(s, 0) * px / capital * 100
            tw = tgt.get(s, 0.0)
            if abs(tw - cw) < 0.4:
                continue
            rowsx.append((s, cw, tw, tw - cw, px))
        rowsx.sort(key=lambda x: x[3])
        print(f"{'نماد':<11}{'الان٪':>8}{'هدف٪':>8}{'Δ٪':>8}"
              f"{'تعداد':>14}{'مبلغ(م ر)':>13}  کار")
        print("─" * 78)
        for s, cw, tw, dw, px in rowsx:
            print(f"{s:<11}{cw:>8.1f}{tw:>8.1f}{dw:>+8.1f}"
                  f"{dw/100*capital/px:>+14,.0f}"
                  f"{dw/100*capital/1e6:>+13,.0f}  "
                  f"{'خرید' if dw > 0 else 'فروش'}")
        print("\n⚠️ اول فروش، بعد خرید — بند ۲ CLAUDE.md.")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps({
            "date": f"{d:%Y-%m-%d}", "capital": capital,
            "universe": len(recs), "eligible": len(elig),
            "picks": [{k: (f"{v:%Y-%m-%d}" if k == "date" else v)
                       for k, v in r.items() if k not in ("mbox", "wbox")}
                      for r in picks],
            "eligible_all": [r["sym"] for r in elig],
        }, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("\n" + "=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
