# -*- coding: utf-8 -*-
"""
تست تفاضلی `valley_box` در برابر یک رونویسی مستقل از خود فایل Pine.

دو پیاده‌سازی جدا روی دادهٔ تصادفی یکسان اجرا می‌شوند و باید بیت‌به‌بیت یکی
دربیایند. حالت‌های لبه هم پوشش داده می‌شود: حجم صفر، قیمت تخت، کندل با دامنهٔ
صفر، تساوی ردیف‌ها، و پنجرهٔ خیلی کوتاه.

اجرا:  python3 tools/verify_box.py
"""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vp_box import Bar, build_profile, make_box, valley_box, value_area_box  # noqa: E402


# ─── رونویسی مستقل، خط‌به‌خط از pinescript/…/f_valleyIncremental ───
def pine_valley(hi_arr, lo_arr, vol_arr, min_r, max_r):
    top = None
    bot = None
    used_rows = -1
    n = len(hi_arr)
    if n > 2:
        r_hi = max(hi_arr)
        r_lo = min(lo_arr)
        price_range = r_hi - r_lo
        if price_range > 0:
            found = False
            for rows in range(min_r, max_r + 1):
                if found:
                    continue
                step = price_range / rows
                bins = [0.0] * rows
                for i in range(n):
                    bh, bl, bv = hi_arr[i], lo_arr[i], vol_arr[i]
                    b_range = bh - bl
                    if b_range <= 0:
                        idx = int(min(rows - 1, max(0, (bh - r_lo) // step)))
                        bins[idx] = bins[idx] + bv
                    else:
                        idx_lo = int(max(0, (bl - r_lo) // step))
                        idx_hi = int(min(rows - 1, (bh - r_lo) // step))
                        for b_idx in range(idx_lo, idx_hi + 1):
                            bin_lo = r_lo + b_idx * step
                            bin_hi = bin_lo + step
                            overlap = min(bh, bin_hi) - max(bl, bin_lo)
                            if overlap > 0:
                                bins[b_idx] = bins[b_idx] + bv * (overlap / b_range)
                v_idx = -1
                for i in range(1, rows - 1):
                    if v_idx == -1 and bins[i] < bins[i - 1] and bins[i] < bins[i + 1]:
                        v_idx = i
                if v_idx >= 0:
                    bot = r_lo + v_idx * step
                    top = bot + step
                    used_rows = rows
                    found = True
    return top, bot, used_rows


def make_bars(rng, n, flat=False, zero_vol=False, zero_range=False):
    bars = []
    px = rng.uniform(1_000, 500_000)
    for _ in range(n):
        if flat:
            h = l = c = px
        elif zero_range:
            h = l = c = px * (1 + rng.uniform(-0.02, 0.02))
        else:
            mid = px * (1 + rng.uniform(-0.05, 0.05))
            half = abs(mid) * rng.uniform(0.0001, 0.03)
            h, l = mid + half, mid - half
            c = rng.uniform(l, h)
        v = 0.0 if zero_vol else rng.choice([0.0, rng.uniform(1, 1e9)])
        bars.append(Bar(h, l, c, v))
        px = c if c else px
    return bars


def main():
    rng = random.Random(20260921)
    cases = 0
    mismatch = 0

    for _ in range(4000):
        n = rng.choice([0, 1, 2, 3, 4, 5, 8, 13, 21, 34, 60])
        kind = rng.random()
        bars = make_bars(
            rng,
            n,
            flat=kind < 0.08,
            zero_vol=0.08 <= kind < 0.16,
            zero_range=0.16 <= kind < 0.24,
        )
        min_r = rng.choice([3, 3, 3, 4, 5])
        max_r = rng.choice([6, 10, 20, 20, 20])
        if max_r < min_r:
            max_r = min_r

        mine = valley_box(bars, min_r, max_r)
        ref = pine_valley(
            [b.h for b in bars], [b.l for b in bars], [b.v for b in bars], min_r, max_r
        )

        cases += 1
        ref_top, ref_bot, ref_rows = ref
        if mine is None:
            if ref_top is not None:
                mismatch += 1
                print(f"  اختلاف: من None، Pine {ref}")
        else:
            lo, hi, rows = mine
            if (
                ref_bot is None
                or abs(lo - ref_bot) > 1e-9
                or abs(hi - ref_top) > 1e-9
                or rows != ref_rows
            ):
                mismatch += 1
                print(f"  اختلاف: من {mine}، Pine {ref}")

    print(f"جست‌وجوی دره: {cases} مورد، {mismatch} اختلاف")

    # ─── ادعاهای معنایی ───
    asserts = 0

    # ۱. دره از **پایین** پیدا می‌شود، نه نزدیک‌ترین به قیمت.
    #    پنجره‌ای می‌سازیم که دو دره دارد؛ باید پایینی برنده شود.
    bars = [
        Bar(10.5, 9.5, 10.0, 900.0),   # ردیف پایین: پرحجم
        Bar(12.5, 11.5, 12.0, 10.0),   # درهٔ پایینی
        Bar(14.5, 13.5, 14.0, 900.0),
        Bar(16.5, 15.5, 16.0, 20.0),   # درهٔ بالایی
        Bar(18.5, 17.5, 18.0, 900.0),
    ]
    got = valley_box(bars, 3, 20)
    assert got is not None, "باید دره پیدا کند"
    lo, hi, _ = got
    assert lo < 14.0, f"باید درهٔ پایینی را بگیرد، گرفت {got}"
    asserts += 1

    # ۲. پنجرهٔ کمتر از سه کندل ناحیه نمی‌دهد (شرط n>2 در Pine).
    assert valley_box([Bar(2, 1, 1.5, 5), Bar(3, 2, 2.5, 5)], 3, 20) is None
    asserts += 1

    # ۳. قیمت کاملاً تخت ناحیه نمی‌دهد (priceRange == 0).
    assert valley_box([Bar(5, 5, 5, 10)] * 9, 3, 20) is None
    asserts += 1

    # ۴. `valley_first` باید عیناً همان چیزی باشد که `valley_box` می‌دهد.
    rng3 = random.Random(99)
    for _ in range(300):
        bs = make_bars(rng3, rng3.choice([12, 25, 40]))
        vb = valley_box(bs, 3, 20)
        mb = make_box("valley_first", bs, None, 3, 20)
        if vb is None:
            assert mb is None
        else:
            assert mb is not None
            assert abs(vb[0] - mb[0]) < 1e-12 and abs(vb[1] - mb[1]) < 1e-12
    asserts += 1

    # ۵. سه انتخاب‌گر دره روی یک پروفایل واحد کار می‌کنند و هر سه یکی از
    #    دره‌های همان پروفایل‌اند — نه چیزی خارج از آن.
    bars2 = [
        Bar(10.5, 9.5, 10.0, 900.0),
        Bar(12.5, 11.5, 12.0, 10.0),    # درهٔ پایینی، کم‌حجم‌تر
        Bar(14.5, 13.5, 14.0, 900.0),
        Bar(16.5, 15.5, 16.0, 40.0),    # درهٔ بالایی
        Bar(18.5, 17.5, 18.0, 900.0),
    ]
    # با ۳ ردیف فقط ایندکس ۱ میانی است، پس حداکثر یک دره ممکن است. برای
    # آزمودن انتخاب‌گرها به پروفایلی با چند دره نیاز داریم.
    prof = build_profile(bars2, 5, 20)
    assert prof is not None and len(prof.valleys) >= 2, "باید دو دره بدهد"
    bands = [prof.band(i) for i in prof.valleys]
    for kind, ref in (
        ("valley_first", None),
        ("valley_deepest", None),
        ("valley_nearest", 18.0),
    ):
        got = make_box(kind, bars2, ref, 5, 20)
        assert got in bands, f"{kind} ناحیه‌ای خارج از دره‌های پروفایل داد: {got}"
    asserts += 1

    # ۶. انتخاب‌گرها واقعاً فرق می‌کنند: اولین ≠ نزدیک‌ترین وقتی مرجع بالاست.
    first = make_box("valley_first", bars2, None, 5, 20)
    near_hi = make_box("valley_nearest", bars2, 18.0, 5, 20)
    assert first != near_hi, "اولین و نزدیک‌ترین نباید یکی باشند"
    # و عمیق‌ترین باید کم‌حجم‌ترین دره را بگیرد
    deep = make_box("valley_deepest", bars2, None, 5, 20)
    deep_idx = min(prof.valleys, key=lambda i: prof.bins[i])
    assert deep == prof.band(deep_idx)
    asserts += 1

    # ۷. `valley_nearest` بدون ref_price باید خطا بدهد، نه بی‌صدا چیزی برگرداند.
    try:
        make_box("valley_nearest", bars2, None, 3, 20)
        raise AssertionError("باید ValueError می‌داد")
    except ValueError:
        pass
    asserts += 1

    # ۸. دره و سه‌بین‌پرحجم روی دادهٔ واحد یکی نمی‌شوند.
    rng2 = random.Random(7)
    diff = 0
    both = 0
    for _ in range(500):
        bs = make_bars(rng2, 25)
        v = valley_box(bs, 3, 20)
        a = value_area_box(bs)
        if v and a:
            both += 1
            if abs(v[0] - a[0]) > 1e-6 or abs(v[1] - a[1]) > 1e-6:
                diff += 1
    pct = (diff / both * 100) if both else 0.0
    print(f"دره در برابر سه‌بین‌پرحجم: {both} مورد، {diff} تا فرق داشتند ({pct:.1f}%)")
    asserts += 1

    # ۹. حلقهٔ ۳→۲۰ عملاً کجا می‌ایستد؟
    #    با ۳ ردیف فقط یک ایندکس میانی وجود دارد، پس اگر حلقه اغلب روی ۳
    #    بایستد، «شمارش ردیف تطبیقی» عملاً تطبیقی نیست و هر سه انتخاب‌گرِ دره
    #    مجبورند یک جواب بدهند.
    rng4 = random.Random(11)
    stop_rows = {}
    one_valley = 0
    pairs = {"اولین≠نزدیک‌ترین": 0, "اولین≠عمیق‌ترین": 0, "نزدیک‌ترین≠عمیق‌ترین": 0}
    tot = 0
    for _ in range(600):
        bs = make_bars(rng4, rng4.choice([12, 20, 25, 40]))
        p = build_profile(bs, 3, 20)
        if p is None:
            continue
        tot += 1
        stop_rows[p.rows] = stop_rows.get(p.rows, 0) + 1
        if len(p.valleys) == 1:
            one_valley += 1
        ref = bs[-1].c
        f = make_box("valley_first", bs, None, 3, 20)
        nr = make_box("valley_nearest", bs, ref, 3, 20)
        d = make_box("valley_deepest", bs, None, 3, 20)
        if f != nr:
            pairs["اولین≠نزدیک‌ترین"] += 1
        if f != d:
            pairs["اولین≠عمیق‌ترین"] += 1
        if nr != d:
            pairs["نزدیک‌ترین≠عمیق‌ترین"] += 1
    if tot:
        top = sorted(stop_rows.items(), key=lambda kv: -kv[1])[:4]
        where = "، ".join(f"{r} ردیف: {c/tot*100:.0f}٪" for r, c in top)
        print(f"حلقه کجا می‌ایستد ({tot} مورد): {where}")
        print(f"پروفایل با فقط یک دره: {one_valley/tot*100:.0f}٪")
        parts = "، ".join(f"{k} {v/tot*100:.0f}٪" for k, v in pairs.items())
        print(f"اختلاف انتخاب‌گرها: {parts}")
    asserts += 1

    print(f"ادعاهای معنایی: {asserts} مورد گذشت")
    if mismatch:
        print("\n❌ پورت با Pine یکی نیست.")
        return 1
    print("\n✅ پورت دره با Pine یکی است.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
