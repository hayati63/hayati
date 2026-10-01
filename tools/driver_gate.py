# -*- coding: utf-8 -*-
"""آیا وضعیتِ باکسِ محرک، بازدهِ **صندوق‌ها** را پیش‌بینی می‌کند؟

دو سؤال مصطفی، هر دو اینجا:

۱. «من روی چارت، دیروز که دوشنبه است باکس قفل می‌شود و کلوزِ امروز که
   سه‌شنبه است تصمیم می‌گیریم... حالا این را ببر تو بک‌تست ببین کدام
   حالت بازدهِ بهتری می‌آورد **برای صندوق‌هایی که با دلار حرکت می‌کنند**.»

۲. «اولویت را تتر قرار بدهیم یا دلار؟»

نکتهٔ مهمِ روشی: محرک **معامله نمی‌شود**، دروازه است. پس سنجیدنش روی
بازدهِ خودش جوابِ سؤال نیست. اینجا بازدهِ **صندوق** سنجیده می‌شود، با
کنترلِ هفته — یعنی در هر هفته، صندوق‌هایی که محرکشان بالا بود در برابر
میانگینِ همهٔ صندوق‌های همان هفته.

    python3 tools/driver_gate.py
"""
import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

from monthly_backtest import load_daily, is_fixed_income, norm
from vp_box import make_box, state
from calendar_wk import week_key_for
from weekly_backtest import week_key as fund_week

# صندوق‌هایی که با دلار/تتر حرکت می‌کنند — از tools/attribute.py
DOLLAR_LINKED = ("طلا نقره کالا_کشاورزی",)
ANCHORS = {"دوشنبه": 0, "سه‌شنبه": 1}


def driver_states(path, anchor, kind):
    """dict[روزِ تصمیم] = وضعیتِ محرک در آن روز."""
    rows = load_daily(path)
    wk = week_key_for(anchor)
    by = defaultdict(list)
    for d, b in rows:
        by[wk(d)].append((d, b))
    ks = sorted(by)
    out = {}
    for i in range(len(ks) - 1):
        wa, wb = ks[i], ks[i + 1]
        if (wb - wa).days != 7:
            continue
        prev, fwd = by[wa], by[wb]
        if len(prev) < 3 or not fwd:
            continue
        box = make_box(kind, [x for _, x in prev], prev[-1][1].c)
        if box is None:
            continue
        # روزِ تصمیم = اولین روزِ هفتهٔ جدید
        dd, bar = fwd[0]
        out[dd] = state(bar.c, box)
    return out


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
    linked = set(DOLLAR_LINKED[0].split())

    # ── بازدهِ هفتگیِ صندوق‌های دلاری ──
    obs, seen, fps = [], set(), {}
    for p in sorted(Path(args.data).glob("*.csv")):
        sym = p.stem.replace("_daily", "").replace("_", " ")
        c = cat.get(norm(sym), "؟")
        if c not in linked or is_fixed_income(sym):
            continue
        rows = load_daily(p)
        if len(rows) < 40:
            continue
        fp = tuple((d.isoformat(), round(b.c, 6)) for d, b in rows)
        if fp in fps or norm(sym) in seen:
            continue
        fps[fp] = 1
        seen.add(norm(sym))
        by = defaultdict(list)
        for d, b in rows:
            by[fund_week(d)].append((d, b))
        ks = sorted(by)
        for i in range(len(ks) - 1):
            wa, wb = ks[i], ks[i + 1]
            if (wb - wa).days != 7:
                continue
            fwd = by[wb]
            if len(fwd) < 2:
                continue
            e, x = fwd[0][1].c, fwd[-1][1].c
            if e > 0:
                obs.append({"w": wb, "sym": sym, "d0": fwd[0][0],
                            "ret": (x - e) / e * 100})
    if not obs:
        print("مشاهده‌ای ساخته نشد.")
        return 1

    by_w = defaultdict(list)
    for o in obs:
        by_w[o["w"]].append(o)
    base = statistics.mean([o["ret"] for o in obs])

    print("=" * 78)
    print(f"دروازهٔ محرک روی صندوق‌های دلاری — {len(obs):,} مشاهده"
          f" · {len(by_w)} هفته · {len(seen)} نماد")
    print(f"نرخ پایه: {base:+.2f}٪ بازده هفتگی")
    print("=" * 78)

    out = {}
    for dname, dfile in (("دلار", "دلار"), ("تتر", "تتر")):
        dp = Path(args.drivers) / f"{dfile}_daily.csv"
        if not dp.exists():
            continue
        print(f"\n{'─'*78}\n{dname}\n{'─'*78}")
        print(f"  {'قرارداد':<26}{'n بالا':>8}{'میانگین':>10}"
              f"{'n زیر':>8}{'میانگین':>10}{'اختلاف':>9}{'t':>7}")
        for aname, anchor in ANCHORS.items():
            st = driver_states(dp, anchor, args.kind)
            # هر مشاهدهٔ صندوق به نزدیک‌ترین روزِ تصمیمِ **قبل یا برابر** وصل
            days = sorted(st)
            hi, lo, pair = [], [], []
            for w, xs in by_w.items():
                d0 = xs[0]["d0"]
                cand = [d for d in days if d <= d0]
                if not cand:
                    continue
                s = st[cand[-1]]
                rs = [o["ret"] for o in xs]
                if len(rs) < 3:
                    continue
                m = statistics.mean(rs)
                (hi if s == "بالا" else lo if s == "زیر" else []).append(m)
            if len(hi) < 4 or len(lo) < 4:
                print(f"  {aname:<26}  — هفتهٔ کافی نیست "
                      f"(بالا {len(hi)} · زیر {len(lo)})")
                continue
            mh, ml = statistics.mean(hi), statistics.mean(lo)
            sh = statistics.stdev(hi) / len(hi) ** 0.5 if len(hi) > 1 else 0
            sl = statistics.stdev(lo) / len(lo) ** 0.5 if len(lo) > 1 else 0
            se = (sh ** 2 + sl ** 2) ** 0.5
            t = (mh - ml) / se if se else 0.0
            star = " ★" if abs(t) > 2 else ""
            lbl = (f"باکس {aname[:-1]}→…، تصمیم {aname}")
            print(f"  {lbl:<26}{len(hi):>8}{mh:>+9.2f}٪{len(lo):>8}"
                  f"{ml:>+9.2f}٪{mh-ml:>+9.2f}{t:>7.2f}{star}")
            out[f"{dname}|{aname}"] = {"n_hi": len(hi), "avg_hi": mh,
                                       "n_lo": len(lo), "avg_lo": ml,
                                       "diff": mh - ml, "t": t}

    print("\n" + "=" * 78)
    print("حکم")
    print("=" * 78)
    if out:
        best = max(out, key=lambda k: out[k]["diff"])
        b = out[best]
        print(f"  بیشترین جدایی: **{best.replace('|', ' · ')}**")
        print(f"    محرک بالا {b['avg_hi']:+.2f}٪ در برابر "
              f"زیر {b['avg_lo']:+.2f}٪ — اختلاف {b['diff']:+.2f} واحد، "
              f"t={b['t']:+.2f}")
        for dn in ("دلار", "تتر"):
            ks = [k for k in out if k.startswith(dn)]
            if len(ks) == 2:
                a, bb = (out[k]["diff"] for k in ks)
                print(f"\n  {dn}: دو قرارداد {a:+.2f} و {bb:+.2f} واحد — "
                      f"اختلافشان {abs(a-bb):.2f}")
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nJSON: {Path(args.json_out).resolve()}")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
