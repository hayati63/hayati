# -*- coding: utf-8 -*-
"""
دو تعریف «باکس» که در پروژه به‌طور همزمان در جریان‌اند.

`valley_box` پورت وفادار `f_valleyIncremental` از اسکریپت Pine است — همان چیزی که
CLAUDE.md بند ۱ توصیف می‌کند: شمارش ردیف تطبیقی، اولین درهٔ حجمی.

`value_area_box` پورت وفادار `box(bars)` از `app/dash.html` است — تعداد بین ثابت،
بین‌بندی روی close، سه بینِ **پرحجم‌ترین**.

این دو یک چیز نیستند و معمولاً نتیجهٔ مخالف می‌دهند. هر دو اینجا هستند تا بشود
روی یک دادهٔ واحد کنار هم سنجیدشان.
"""

from typing import List, Optional, Sequence, Tuple

Box = Tuple[float, float]  # (lo, hi)


class Bar:
    __slots__ = ("h", "l", "c", "v")

    def __init__(self, h: float, l: float, c: float, v: float):
        self.h, self.l, self.c, self.v = h, l, c, v


def valley_box(
    bars: Sequence[Bar], min_rows: int = 3, max_rows: int = 20
) -> Optional[Tuple[float, float, int]]:
    """اولین درهٔ حجمی. برمی‌گرداند (lo, hi, تعداد ردیفی که جواب داد).

    وفادار به Pine:
      - دامنه از High/Low کل پنجره، نه از close
      - حجم هر کندل به نسبت هم‌پوشانی بین ردیف‌ها پخش می‌شود
      - کندل با دامنهٔ صفر کل حجمش در یک ردیف می‌نشیند
      - جست‌وجوی دره فقط روی ردیف‌های **میانی** (۱ تا rows-2)، از پایین به بالا
      - اولین تعداد ردیفی که دره بدهد برنده است؛ ردیف‌ها صعودی امتحان می‌شوند

    بازگشت None یعنی تا `max_rows` هیچ دره‌ای پیدا نشد — که در Pine یعنی
    «اینجا ناحیه‌ای نیست»، نه «ردیف را بیشتر کن».
    """
    n = len(bars)
    if n <= 2:
        return None

    r_hi = max(b.h for b in bars)
    r_lo = min(b.l for b in bars)
    price_range = r_hi - r_lo
    if price_range <= 0:
        return None

    # Pine در `for i = 1 to rows - 2` وقتی rows<3 باشد رو به پایین می‌شمارد و به
    # ایندکس ‎-1‎ می‌رسد. اینجا صریحاً جلویش را می‌گیریم.
    lo_rows = max(3, min_rows)

    for rows in range(lo_rows, max_rows + 1):
        step = price_range / rows
        bins = [0.0] * rows

        for b in bars:
            b_range = b.h - b.l
            if b_range <= 0:
                idx = int((b.h - r_lo) / step)
                idx = max(0, min(rows - 1, idx))
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

        for i in range(1, rows - 1):
            if bins[i] < bins[i - 1] and bins[i] < bins[i + 1]:
                bot = r_lo + i * step
                return (bot, bot + step, rows)

    return None


def value_area_box(bars: Sequence[Bar]) -> Optional[Box]:
    """سه بینِ پرحجم‌ترین، بین‌بندی روی close. پورت `box()` از dash.html."""
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
        k = int((b.c - lo) / w)
        k = max(0, min(nb - 1, k))
        vol[k] += b.v

    order = sorted(range(nb), key=lambda j: (-vol[j], j))[: min(3, nb)]
    return (lo + min(order) * w, lo + (max(order) + 1) * w)


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
