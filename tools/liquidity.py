# -*- coding: utf-8 -*-
"""نقدشوندگی واقعی: چند روز طول می‌کشد تا از یک پوزیشن بیرون بیایی.

«ارزش معامله به ارزش بازار» نسبتی است که هر دو سرش را باید از بیرون گرفت و
مقیاسش هم قابل اعتماد نیست. این فایل به‌جایش چیزی می‌سنجد که مستقیم از خود
دادهٔ روزانه درمی‌آید و مقیاس‌آزاد است:

    روزِ خروج = تعداد واحدِ پوزیشن ÷ (میانهٔ حجم روزانه × سهم مشارکت)

«سهم مشارکت» یعنی حاضری چند درصد از حجم یک روز، خودت باشی. ۲۰٪ عدد محافظه‌کارانهٔ
مرسوم است؛ بالاتر از آن خودِ سفارش قیمت را جابه‌جا می‌کند.

خروجی JSON است، نه CSV، چون هم واحد و هم ریال را نگه می‌دارد.
"""
import argparse
import json
import re
import statistics
from pathlib import Path

from monthly_backtest import load_daily, norm


def read_holdings(path):
    """هر خط «نماد تعداد». خط با # نظر است."""
    out = {}
    p = Path(path)
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(.+?)[\s,،\t]+([\d.,]+)$", line)
        if not m:
            continue
        try:
            n = float(m.group(2).replace(",", "").replace("،", ""))
        except ValueError:
            continue
        out[m.group(1).strip()] = out.get(m.group(1).strip(), 0.0) + n
    return out


def build(data_dir, glob, window, participation, holdings):
    rows = {}
    for p in sorted(Path(data_dir).glob(glob)):
        name = p.name
        for suf in ("_daily.csv", ".csv"):
            if name.endswith(suf):
                name = name[: -len(suf)]
                break
        daily = load_daily(p)
        if len(daily) < 5:
            continue
        tail = daily[-window:]
        vols = [b.v for _, b in tail if b.v]
        if not vols:
            continue
        closes = [b.c for _, b in tail]
        med_v = statistics.median(vols)
        med_val = statistics.median(
            [b.v * b.c for _, b in tail if b.v])
        rec = {"sym": name, "days": len(tail), "med_vol": med_v,
               "med_value": med_val, "close": closes[-1],
               "zero_days": sum(1 for _, b in tail if not b.v)}
        units = holdings.get(name)
        if units:
            rec["units"] = units
            rec["value"] = units * closes[-1]
            cap = med_v * participation
            rec["exit_days"] = units / cap if cap > 0 else None
            rec["pct_of_volume"] = units / med_v * 100 if med_v else None
        rows[name] = rec
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_auto")
    ap.add_argument("--glob", default="*.csv")
    ap.add_argument("--holdings", default="data/holdings.txt")
    ap.add_argument("--out", default="data/liquidity.json")
    ap.add_argument("--window", type=int, default=20,
                    help="چند روز اخیر برای میانهٔ حجم")
    ap.add_argument("--participation", type=float, default=0.20,
                    help="چند درصد از حجم یک روز را خودت می‌توانی باشی")
    args = ap.parse_args()

    holdings = read_holdings(args.holdings)
    rows = build(args.data, args.glob, args.window, args.participation,
                 holdings)
    if not rows:
        print("هیچ دادهٔ حجمی پیدا نشد.")
        return 1

    Path(args.out).write_text(
        json.dumps({"window": args.window,
                    "participation": args.participation,
                    "rows": rows}, ensure_ascii=False, indent=1),
        encoding="utf-8")

    held = [r for r in rows.values() if r.get("exit_days") is not None]
    held.sort(key=lambda r: -r["exit_days"])
    print(f"نماد: {len(rows)}  |  در پرتفو: {len(held)}"
          f"  |  پنجره: {args.window} روز  |  مشارکت: "
          f"{args.participation*100:.0f}٪\n")
    if held:
        print(f"{'نماد':<10}{'واحد':>14}{'ارزش (م ریال)':>16}"
              f"{'٪ حجم روز':>11}{'روز خروج':>10}")
        for r in held:
            print(f"{r['sym']:<10}{r['units']:>14,.0f}"
                  f"{r['value']/1e6:>16,.0f}{r['pct_of_volume']:>11.2f}"
                  f"{r['exit_days']:>10.2f}")
        worst = held[0]
        print(f"\nبدترین: {worst['sym']} با {worst['exit_days']:.2f} روز.")
        if worst["exit_days"] < 1:
            print("هیچ‌کدام حتی یک روز معامله هم نمی‌برد — نقدشوندگی قید")
            print("این پرتفو نیست.")

    thin = [r for r in rows.values()
            if r["zero_days"] >= max(3, args.window // 4)]
    if thin:
        print(f"\n⚠️ {len(thin)} نماد در پنجره روزِ بی‌حجم دارند "
              "(احتمال بسته‌بودن یا صف):")
        for r in sorted(thin, key=lambda r: -r["zero_days"])[:10]:
            print(f"    {r['sym']:<12}{r['zero_days']:>3} روز از {r['days']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
