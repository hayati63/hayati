# -*- coding: utf-8 -*-
"""
تعریف‌های «باکس» که در پروژه هم‌زمان در جریان‌اند.

پروفایل یک‌بار ساخته می‌شود؛ تفاوت تعریف‌ها فقط در این است که **کدام** دره
برداشته شود. این عمدی است: اگر شمارش ردیف هم بین تعریف‌ها فرق کند، مقایسه‌شان
ناعادلانه می‌شود.

  valley_first    اولین درهٔ میانی از پایین — وفادار به Pine
  valley_nearest  درهٔ نزدیک‌ترین به قیمت مرجع — چیزی که چارتیکس نشان می‌دهد
  valley_deepest  کم‌حجم‌ترین دره
  value_area      سه بین پرحجم‌ترین روی close — پورت `box()` از dash.html

سه‌تای اول ناحیهٔ کم‌حجم‌اند (LVN)، چهارمی ناحیهٔ پرحجم. مفهوماً مخالف‌اند.
"""

from typing import List, Optional, Sequence, Tuple

Box = Tuple[float, float]  # (lo, hi)

BOX_KINDS = ("valley_first", "valley_nearest", "valley_deepest", "value_area")


class Bar:
    __slots__ = ("h", "l", "c", "v")

    def __init__(self, h: float, l: float, c: float, v: float):
        self.h, self.l, self.c, self.v = h, l, c, v


class Profile:
    """پروفایل یک پنجره، به‌همراه ایندکس همهٔ دره‌های میانی."""

    __slots__ = ("rows", "step", "lo", "bins", "valleys")

    def __init__(self, rows: int, step: float, lo: float,
                 bins: List[float], valleys: List[int]):
        self.rows, self.step, self.lo = rows, step, lo
        self.bins, self.valleys = bins, valleys

    def band(self, idx: int) -> Box:
        bot = self.lo + idx * self.step
        return (bot, bot + self.step)


def build_profile(
    bars: Sequence[Bar], min_rows: int = 3, max_rows: int = 20
) -> Optional[Profile]:
    """اولین تعداد ردیفی که حداقل یک درهٔ میانی بدهد.

    وفادار به `f_valleyIncremental` در Pine:
      - دامنه از High/Low کل پنجره، نه از close
      - حجم هر کندل به نسبت هم‌پوشانی بین ردیف‌ها پخش می‌شود
      - کندل با دامنهٔ صفر کل حجمش در یک ردیف می‌نشیند
      - دره فقط روی ردیف‌های میانی (۱ تا rows-2)
      - ردیف‌ها صعودی امتحان می‌شوند، اولین جواب برنده

    تفاوت با Pine: آنجا فقط **اولین** دره برمی‌گردد. اینجا همهٔ دره‌های همان
    شمارش ردیف نگه داشته می‌شوند تا تعریف‌های دیگر هم بتوانند انتخاب کنند.
    """
    n = len(bars)
    if n <= 2:
        return None

    r_hi = max(b.h for b in bars)
    r_lo = min(b.l for b in bars)
    price_range = r_hi - r_lo
    if price_range <= 0:
        return None

    # Pine در `for i = 1 to rows - 2` وقتی rows<3 باشد رو به پایین می‌شمارد و
    # به ایندکس ‎-1‎ می‌رسد. اینجا صریحاً جلویش را می‌گیریم.
    lo_rows = max(3, min_rows)

    for rows in range(lo_rows, max_rows + 1):
        step = price_range / rows
        bins = [0.0] * rows

        for b in bars:
            b_range = b.h - b.l
            if b_range <= 0:
                idx = max(0, min(rows - 1, int((b.h - r_lo) / step)))
                bins[idx] += b.v
                continue
            idx_lo = max(0, int((b.l - r_lo) / step))
            idx_hi = min(rows - 1, int((b.h - r_lo) / step))
            for bi in range(idx_lo, idx_hi + 1):
                bin_lo = r_lo + bi * step
                bin_hi = bin_lo + step
                overlap = min(b.h, bin_hi) - max(b.l, bin_lo)
                if overlap > 0:
                    bins[bi] += b.v * (overlap / b_range)

        valleys = [
            i for i in range(1, rows - 1)
            if bins[i] < bins[i - 1] and bins[i] < bins[i + 1]
        ]
        if valleys:
            return Profile(rows, step, r_lo, bins, valleys)

    return None


def valley_box(
    bars: Sequence[Bar], min_rows: int = 3, max_rows: int = 20
) -> Optional[Tuple[float, float, int]]:
    """اولین درهٔ میانی از پایین. خروجی (lo, hi, تعداد ردیف). وفادار به Pine."""
    p = build_profile(bars, min_rows, max_rows)
    if p is None:
        return None
    lo, hi = p.band(p.valleys[0])
    return (lo, hi, p.rows)


def value_area_box(bars: Sequence[Bar]) -> Optional[Box]:
    """سه بین پرحجم‌ترین، بین‌بندی روی close. پورت `box()` از dash.html."""
    if len(bars) < 3:
        return None
    if sum(b.v for b in bars) <= 0:
        return None

    lo = min(b.c for b in bars)
    hi = max(b.c for b in bars)
    if hi <= lo:
        return (lo, hi)

    nb = min(20, max(5, len(bars) // 2))
    w = (hi - lo) / nb
    vol = [0.0] * nb
    for b in bars:
        k = max(0, min(nb - 1, int((b.c - lo) / w)))
        vol[k] += b.v

    order = sorted(range(nb), key=lambda j: (-vol[j], j))[: min(3, nb)]
    return (lo + min(order) * w, lo + (max(order) + 1) * w)


def make_box(
    kind: str,
    bars: Sequence[Bar],
    ref_price: Optional[float] = None,
    min_rows: int = 3,
    max_rows: int = 20,
) -> Optional[Box]:
    """یک تعریف را روی یک پنجره اجرا می‌کند.

    `ref_price` فقط برای `valley_nearest` لازم است و باید قیمتی باشد که در
    لحظهٔ ساخت باکس **در دسترس بوده** — کلوز آخرین روز همان ماه، نه کلوز ماه
    بعد. وگرنه لوک‌اهد وارد می‌شود.
    """
    if kind == "value_area":
        return value_area_box(bars)

    p = build_profile(bars, min_rows, max_rows)
    if p is None:
        return None

    if kind == "valley_first":
        idx = p.valleys[0]
    elif kind == "valley_deepest":
        idx = min(p.valleys, key=lambda i: (p.bins[i], i))
    elif kind == "valley_nearest":
        if ref_price is None:
            raise ValueError("valley_nearest به ref_price نیاز دارد")
        idx = min(
            p.valleys,
            key=lambda i: (abs((p.lo + (i + 0.5) * p.step) - ref_price), i),
        )
    else:
        raise ValueError(f"تعریف ناشناخته: {kind}")

    return p.band(idx)


def state(close: float, box: Optional[Box]) -> str:
    """بالا / داخل / زیر — همان سه حالت CLAUDE.md."""
    if box is None:
        return "—"
    lo, hi = box
    if close > hi:
        return "بالا"
    if close < lo:
        return "زیر"
    return "داخل"
