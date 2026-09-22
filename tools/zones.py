# -*- coding: utf-8 -*-
"""محدودهٔ خرید، استاپ و تارگتِ هر نماد — و آلارمِ رسیدن قیمت.

**چرا محدوده روی سقفِ باکس نیست.** مصطفی گفت: «بازار بعضی مواقع به خود
ناحیه نمی‌رسد، به کندل‌هایی که به آن ناحیه مرتبط‌اند واکنش نشان می‌دهد...
تو بک‌تست‌ها هم نشون داده بود که فاصلهٔ ۳ درصدی ۴ درصدی ارجحیت بیشتری
دارند.» اندازه‌گیری شد (`tools/reaction.py` و سوییپِ R):

    پنجرهٔ ماهانه — میانگین R بر حسب سطحِ ورود
      سقف باکس       +۰٫۰۸۸ R   t=۱٫۳۵   ۳۵٫۵٪ پر شد
      سقف +۲٪        +۰٫۲۳۴ R   t=۴٫۵۴   ۵۳٫۴٪
      سقف +۳٪        +۰٫۲۴۷ R   t=۵٫۴۱   ۶۲٫۱٪   ← بهترین
      سقف +۴٪        +۰٫۲۴۱ R   t=۵٫۶۶   ۶۹٫۲٪

    پنجرهٔ هفتگی
      سقف باکس       +۰٫۱۲۱ R   t=۳٫۰۱   ۲۶٫۶٪
      سقف +۰٫۵٪      +۰٫۱۷۰ R   t=۴٫۷۱   ۳۴٫۸٪   ← بهترین
      سقف +۱٫۵٪      +۰٫۱۳۵ R   t=۴٫۵۰   ۵۰٫۱٪
      سقف +۴٪        −۰٫۰۵۳ R   t=−۲٫۵۴  (خراب می‌شود)

حق با او بود، و «حمایت خالی» هم نصف می‌شود: پرشدنِ ماهانه از ۳۵٪ به ۶۲٪.

پس محدودهٔ خرید یک **نوار** است، نه یک خط:
    ماهانه: از سقفِ باکس تا سقف +۴٪ (هدف: +۳٪)
    هفتگی: از سقفِ باکس تا سقف +۲٪ (هدف: +۰٫۵٪)
استاپ زیر کفِ باکس، تارگت به اندازهٔ فاصلهٔ ورود تا استاپ (۱:۱ واقعی).

    python3 tools/zones.py                 # جدول محدوده‌ها
    python3 tools/zones.py --alert         # فقط آنهایی که قیمت در محدوده است
    python3 tools/zones.py --telegram      # ارسال به تلگرام
"""
import argparse
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

from monthly_backtest import load_daily, is_fixed_income, norm
from breadth import box_states

# از سوییپِ R بالا. «hi» لبهٔ بالایی نوار است، «aim» نقطهٔ هدف.
BAND = {"month": {"aim": 3.0, "hi": 4.0}, "week": {"aim": 0.5, "hi": 2.0}}


def zone(box, px, band):
    """(کفِ نوار، هدف، سقفِ نوار، استاپ، تارگت، وضعیت)"""
    lo, hi = box
    z_lo, z_aim, z_hi = hi, hi * (1 + band["aim"] / 100), hi * (1 + band["hi"] / 100)
    stop = lo
    risk = z_aim - stop
    target = z_aim + risk
    if px < z_lo:
        st = "زیر نوار"
    elif px <= z_hi:
        st = "در نوار"
    else:
        st = "بالای نوار"
    return {"lo": z_lo, "aim": z_aim, "hi": z_hi, "stop": stop,
            "target": target, "risk_pct": (z_aim - stop) / z_aim * 100,
            "dist_pct": (px - z_hi) / px * 100, "state": st}


def telegram(text, token=None, chat=None):
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = chat or os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("\n⚠️ TELEGRAM_BOT_TOKEN و TELEGRAM_CHAT_ID در محیط نیست.")
        print("   ویندوز:  setx TELEGRAM_BOT_TOKEN \"...\"")
        print("   متن بالا ارسال نشد.")
        return False
    data = urllib.parse.urlencode({"chat_id": chat, "text": text,
                                   "parse_mode": "HTML"}).encode()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        with urllib.request.urlopen(url, data=data, timeout=30) as r:
            return r.status == 200
    except Exception as e:                       # noqa: BLE001
        print("خطای تلگرام:", e)
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_auto")
    ap.add_argument("--kind", default="valley_first")
    ap.add_argument("--tomorrow", default="data/tomorrow.json",
                    help="فقط نمادهای این فایل؛ خالی یعنی همه")
    ap.add_argument("--all", action="store_true", help="کلِ جهان")
    ap.add_argument("--alert", action="store_true",
                    help="فقط نمادهایی که قیمت در نوار خرید است")
    ap.add_argument("--telegram", action="store_true")
    ap.add_argument("--json", dest="json_out", default="data/zones.json")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    want = None
    if not args.all:
        tp = root / args.tomorrow
        if tp.exists():
            t = json.loads(tp.read_text(encoding="utf-8"))
            want = {norm(s) for s in t.get("eligible_all", [])}
            want |= {norm(p["sym"]) for p in t.get("picks", [])}

    out, seen = [], set()
    for p in sorted(Path(args.data).glob("*.csv")):
        sym = p.stem.replace("_daily", "").replace("_", " ")
        if want is not None and norm(sym) not in want:
            continue
        if norm(sym) in seen or is_fixed_income(sym):
            continue
        rows = load_daily(p)
        if len(rows) < 40:
            continue
        seen.add(norm(sym))
        st = box_states(rows, args.kind)
        if not st:
            continue
        px = st["close"]
        # باکس‌ها را دوباره لازم داریم تا نوار ساخته شود
        from collections import defaultdict
        from vp_box import make_box
        from calendar_wk import week_key_for, derive_anchor
        anchor, _, _ = derive_anchor([d for d, _ in rows])
        wk = week_key_for(anchor)
        by_m, by_w = defaultdict(list), defaultdict(list)
        for d, b in rows:
            by_m[(d.year, d.month)].append(b)
            by_w[wk(d)].append(b)
        ms, ws = sorted(by_m), sorted(by_w)
        if len(ms) < 2 or len(ws) < 2:
            continue
        mb = make_box(args.kind, by_m[ms[-2]], by_m[ms[-2]][-1].c)
        wb = make_box(args.kind, by_w[ws[-2]], by_w[ws[-2]][-1].c)
        if mb is None or wb is None:
            continue
        row = {"sym": sym, "close": px, "date": str(st["date"]),
               "mst": st["mst"], "wst": st["wst"],
               "month": zone(mb, px, BAND["month"]),
               "week": zone(wb, px, BAND["week"])}
        out.append(row)

    if not out:
        print("نمادی نبود.")
        return 1
    out.sort(key=lambda r: r["week"]["dist_pct"])

    hot = [r for r in out if r["week"]["state"] == "در نوار"
           or r["month"]["state"] == "در نوار"]
    rows = hot if args.alert else out

    print("=" * 96)
    print(f"محدودهٔ خرید — {len(out)} نماد · کلوز {out[0]['date']}")
    print("ماهانه: سقفِ باکس تا +۴٪ (هدف +۳٪) · هفتگی: تا +۲٪ (هدف +۰٫۵٪)")
    print("=" * 96)
    print(f"\n{'نماد':<11}{'کلوز':>11}"
          f"{'نوارِ هفتگی':>25}{'وضعیت':>11}"
          f"{'نوارِ ماهانه':>25}{'وضعیت':>11}")
    print("─" * 96)
    for r in rows:
        w, m = r["week"], r["month"]
        print(f"{r['sym']:<11}{r['close']:>11,.0f}"
              f"{f'{w[chr(108)+chr(111)]:,.0f}–{w[chr(104)+chr(105)]:,.0f}':>25}"
              f"{w['state']:>11}"
              f"{f'{m[chr(108)+chr(111)]:,.0f}–{m[chr(104)+chr(105)]:,.0f}':>25}"
              f"{m['state']:>11}")

    if hot:
        print(f"\n🔔 {len(hot)} نماد همین الان در نوار خرید است:")
        for r in hot:
            for k, nm in (("week", "هفتگی"), ("month", "ماهانه")):
                z = r[k]
                if z["state"] != "در نوار":
                    continue
                print(f"   {r['sym']:<10} {nm}  ورود {z['aim']:,.0f} · "
                      f"استاپ {z['stop']:,.0f} · تارگت {z['target']:,.0f} · "
                      f"ریسک {z['risk_pct']:.1f}٪")
    else:
        print("\n— هیچ نمادی الان در نوار خرید نیست.")

    if args.telegram:
        lines = [f"<b>نوار خرید</b> — کلوز {out[0]['date']}"]
        if hot:
            for r in hot:
                for k, nm in (("week", "هفتگی"), ("month", "ماهانه")):
                    z = r[k]
                    if z["state"] != "در نوار":
                        continue
                    lines.append(
                        f"• <b>{r['sym']}</b> {nm} | ورود {z['aim']:,.0f} "
                        f"| استاپ {z['stop']:,.0f} | ریسک {z['risk_pct']:.1f}%")
        else:
            lines.append("امروز هیچ نمادی در نوار خرید نیست.")
        lines.append("")
        lines.append("این خوانشِ قاعده‌های خودت روی داده است، نه توصیهٔ مالی.")
        print("\nتلگرام:", telegram("\n".join(lines)))

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nJSON: {Path(args.json_out).resolve()}")
    print("=" * 96)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
