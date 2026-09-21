# -*- coding: utf-8 -*-
"""دو چکی که در پرتفوی دیروز نبود.

۱. **پهنای گروه.** صندوق‌های یک گروه همگرایی بالایی دارند (همبستگی داخل
   مجموعهٔ سهام بالای ۰٫۹ است، بخش ۴ بازبینی). پس اگر از ده صندوق طلا هشت
   تا زیر باکس هفتگی باشند، آن دو تای دیگر سیگنال نیستند — عقب‌افتاده‌اند.
   نمادی که گروهش اکثراً منفی است علامت می‌خورد.

۲. **انطباق با محرک.** طلا را اونس و دلار می‌سازند، سینرژی را نفت و دلار،
   اهرمی‌ها را شاخص کل. اگر محرکِ یک گروه زیر باکس خودش باشد، سیگنالِ آن
   گروه روی پایهٔ سست نشسته.

⚠️ محرک‌های ۷روزه (دلار، تتر، اونس، نفت) مرزِ هفته‌شان قراردادِ چارتیکس است
و فایل 1W آن‌ها نرسیده. اینجا همان لنگر شنبه استفاده می‌شود تا با صندوق‌ها
قابل مقایسه بماند؛ این یک **فرض** است، نه اندازه‌گیری.
"""
import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

from monthly_backtest import load_daily, is_fixed_income, norm
from vp_box import make_box, state
from weekly_backtest import week_key
from drivers import group_of, EXPOSURE

DRIVER_FILE = {
    "dollar": "دلار", "usdt": "تتر", "xag": "اونس_نقره",
    "oil": "نفت_برنت", "copper": "مس", "gold18": "طلای_۱۸_عیار",
    "tedpix": "شاخص_کل", "eqwt": "شاخص_هم‌وزن",
    "cert_gold": "گواهی_شمش_طلا", "cert_silver": "گواهی_شمش_نقره",
}
NAME = {"dollar": "دلار", "usdt": "تتر", "xag": "اونس نقره",
        "oil": "نفت برنت", "copper": "مس", "gold18": "طلای ۱۸",
        "tedpix": "شاخص کل", "eqwt": "شاخص هم‌وزن", "xau": "اونس طلا",
        "cert_gold": "گواهی شمش طلا", "cert_silver": "گواهی شمش نقره"}


def box_states(rows, kind):
    """(حالت ماهانه، حالت هفتگی، ریسک ماهانه، ریسک هفتگی) یا None."""
    # پنجشنبه و جمعه **حذف نمی‌شوند**. برای صندوق‌های ایرانی این حذف
    # بی‌اثر بود (آن روزها اصلاً کندل ندارند)، ولی اونس نقره و نفت برنت
    # دوشنبه تا جمعه معامله می‌شوند — حذفشان هفته را به ۳ روز می‌رساند و
    # پروفایلِ ۳کندلی اغلب هیچ دره‌ای ندارد، پس محرک بی‌صدا «داده ندارد»
    # می‌شد. هر روزی که کندل دارد، داخل هفته‌اش می‌ماند.
    by_m, by_w = defaultdict(list), defaultdict(list)
    for d, b in rows:
        by_m[(d.year, d.month)].append((d, b))
        by_w[week_key(d)].append((d, b))
    ms, ws = sorted(by_m), sorted(by_w)
    if len(ms) < 3 or len(ws) < 3:
        return None
    close = rows[-1][1].c
    if len(by_m[ms[-2]]) < 5:
        return None
    mb = make_box(kind, [x for _, x in by_m[ms[-2]]], by_m[ms[-2]][-1][1].c)
    wp = by_w[ws[-2]]
    wb = make_box(kind, [x for _, x in wp], wp[-1][1].c) if len(wp) >= 3 else None
    if not mb or not wb:
        return None
    return {"close": close, "date": rows[-1][0],
            "mst": state(close, mb), "wst": state(close, wb),
            "mrisk": (close - mb[0]) / close * 100,
            "wrisk": (close - wb[0]) / close * 100,
            # چند کندل پشتِ باکس هفتگی است. بند ۱ می‌گوید پروفایلِ هفتگی
            # باید روی H1 ساخته شود — یعنی ~۱۲۰ کندل. با کندل روزانه یک
            # هفته فقط ۵ تا ۷ کندل دارد و هیستوگرامِ ۳ردیفه دره‌اش را
            # جایی می‌گذارد که معنا ندارد. مصطفی این را روی دلار گرفت:
            # باکسِ ۷کندلیِ ما ۲٬۳۲۵٬۴۲۹–۲٬۳۴۲٬۲۸۶ درآمد (پهنای ۰٫۷٪ در
            # هفته‌ای با رنج ۵٫۲٪) و «زیر» گفت، در حالی که چارت H1 او
            # «بالا» نشان می‌داد. پس زیر این آستانه، حکم نمی‌دهیم.
            "wbars": len(wp), "wok": len(wp) >= 20}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_auto")
    ap.add_argument("--drivers", default="data/drivers_daily")
    ap.add_argument("--kind", default="valley_first")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    cat = {}
    tp = root / "data/extracted/TODAY.json"
    if tp.exists():
        for r in json.loads(tp.read_text(encoding="utf-8")):
            cat[norm(r["نماد"])] = r["دسته"]

    # ── محرک‌ها ──
    drv = {}
    for did, fname in DRIVER_FILE.items():
        p = Path(args.drivers) / f"{fname}_daily.csv"
        if not p.exists():
            continue
        st = box_states(load_daily(p), args.kind)
        if st:
            drv[did] = st

    print("=" * 74)
    print("۱. محرک‌ها — باکس ماهانه و هفتگی خودشان")
    print("=" * 74)
    print(f"{'محرک':<16}{'کلوز':>14}{'ماهانه':>10}{'هفتگی':>10}"
          f"{'ریسک م':>9}{'ریسک ه':>9}")
    print("─" * 74)
    for did in ("dollar", "usdt", "gold18", "xag", "oil", "copper",
                "tedpix", "eqwt", "cert_gold", "cert_silver"):
        if did not in drv:
            print(f"{NAME.get(did, did):<16}{'— داده ندارد':>14}")
            continue
        s = drv[did]
        print(f"{NAME.get(did, did):<16}{s['close']:>14,.2f}"
              f"{s['mst']:>10}{s['wst']:>10}"
              f"{s['mrisk']:>9.1f}{s['wrisk']:>9.1f}")
    if "xau" not in drv:
        print("\n⚠️ اونس طلا (XAUUSD) هنوز نرسیده — چراغ طلا ناقص است.")

    # ── پهنای هر گروه ──
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
        st = box_states(rows, args.kind)
        if st:
            st["group"] = group_of(name, cat.get(norm(name), "سهامی"))
            recs[name] = st

    grp = defaultdict(list)
    for n, r in recs.items():
        grp[r["group"]].append(r)

    print("\n" + "=" * 74)
    print("۲. پهنای گروه — چند درصد اعضا بالای باکس هفتگی‌اند")
    print("=" * 74)
    print(f"{'گروه':<20}{'عضو':>6}{'هفتگی بالا':>12}{'پهنا':>8}"
          f"{'ماهانه بالا':>13}  محرک‌ها")
    print("─" * 74)
    breadth = {}
    for g, rows_ in sorted(grp.items(), key=lambda kv: -len(kv[1])):
        wup = sum(1 for r in rows_ if r["wst"] == "بالا")
        mup = sum(1 for r in rows_ if r["mst"] == "بالا")
        b = wup / len(rows_) * 100
        breadth[g] = {"n": len(rows_), "w_up": wup, "breadth": b,
                      "m_up": mup}
        ds = []
        for did in sorted(EXPOSURE.get(g, {}), key=lambda k: -EXPOSURE[g][k]):
            if did in drv:
                mark = {"بالا": "✓", "داخل": "~", "زیر": "✗"}[drv[did]["wst"]]
                ds.append(f"{NAME.get(did, did)}{mark}")
            else:
                ds.append(f"{NAME.get(did, did)}?")
        flag = "  ⚠️" if b < 50 else ""
        print(f"{g:<20}{len(rows_):>6}{wup:>12}{b:>7.0f}٪{mup:>13}"
              f"  {'، '.join(ds[:3])}{flag}")
    print("\n  ✓ محرک بالای باکس هفتگی · ~ داخل · ✗ زیر · ? داده ندارد")
    print("  ⚠️ = کمتر از نصف اعضای گروه بالای باکس هفتگی‌اند")

    # ── چک کردن انتخاب‌های دیروز ──
    tj = root / "data/tomorrow.json"
    if tj.exists():
        picks = json.loads(tj.read_text(encoding="utf-8")).get("picks", [])
        if picks:
            print("\n" + "=" * 74)
            print("۳. انتخاب‌های پرتفو — با این دو چک")
            print("=" * 74)
            print(f"{'نماد':<11}{'گروه':<18}{'٪':>6}{'پهنای گروه':>12}"
                  f"{'محرک':>22}")
            print("─" * 74)
            for r in sorted(picks, key=lambda x: -x.get("w", 0)):
                if r.get("w", 0) <= 0:
                    continue
                g = r["group"]
                b = breadth.get(g, {}).get("breadth")
                ds = []
                bad = 0
                for did in sorted(EXPOSURE.get(g, {}),
                                  key=lambda k: -EXPOSURE[g][k])[:2]:
                    if did in drv:
                        w = drv[did]["wst"]
                        ds.append(f"{NAME.get(did, did)}"
                                  f"{ {'بالا':'✓','داخل':'~','زیر':'✗'}[w] }")
                        if w == "زیر":
                            bad += 1
                    else:
                        ds.append(f"{NAME.get(did, did)}?")
                        bad += 1
                warn = ""
                if b is not None and b < 50:
                    warn += " ⚠️گروه"
                if bad:
                    warn += " ⚠️محرک"
                print(f"{r['sym']:<11}{g:<18}{r['w']:>6.1f}"
                      f"{(f'{b:.0f}٪' if b is not None else '—'):>12}"
                      f"{'، '.join(ds):>22}{warn}")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps({
            "drivers": {k: {kk: (f"{vv:%Y-%m-%d}" if kk == "date" else vv)
                            for kk, vv in v.items()} for k, v in drv.items()},
            "breadth": breadth,
        }, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("\n" + "=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
