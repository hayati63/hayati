#!/usr/bin/env python3
"""Differential test of the Vertical Volume Gap primitives.

Same method as tools/verify_clarity.py: the Pine helpers and the MQL5 helpers
are transcribed independently and run against the same inputs. Only the pieces
the (truncated) paste fully specified are covered here.

    python3 tools/verify_volume_gap.py
"""

import datetime as dt
import random
import sys

# ---------------------------------------------------------------- Pine side

def pine_find_volume_gap(vol, sa, sb):
    n = len(vol)
    lo = max(sa, 1)
    hi = min(sb, n - 2)
    best_idx = -1
    best_vol = 1e18
    if hi >= lo:
        for i in range(lo, hi + 1):
            v0, vl, vr = vol[i], vol[i - 1], vol[i + 1]
            if v0 < vl and v0 < vr and v0 < best_vol:
                best_vol = v0
                best_idx = i
    return best_idx


def pine_is_pin_bar(o, h, l, c, dir_bias):
    body = abs(c - o)
    upper = h - max(o, c)
    lower = min(o, c) - l
    is_bull = body > 0 and lower >= 2 * body and lower > upper
    is_bear = body > 0 and upper >= 2 * body and upper > lower
    return is_bull if dir_bias == 1 else (is_bear if dir_bias == -1 else False)


def pine_near_zone_pin(z_top, z_bot, dir_bias, o, h, l, c):
    band = (z_top - z_bot) * 0.30
    pin = pine_is_pin_bar(o, h, l, c, dir_bias)
    if dir_bias == 1:
        near = (l >= z_bot - band and l < z_bot and c < z_bot)
    elif dir_bias == -1:
        near = (h <= z_top + band and h > z_top and c > z_top)
    else:
        near = False
    return pin and near


def pine_zones_overlap(top1, bot1, top2, bot2):
    return bot1 <= top2 and bot2 <= top1


def pine_index_range(t_arr, tc_arr, from_t, to_t):
    start_idx = -1
    end_idx = -1
    for i in range(len(t_arr)):
        if t_arr[i] >= from_t and tc_arr[i] <= to_t:
            if start_idx == -1:
                start_idx = i
            end_idx = i
    return start_idx, end_idx


# ---------------------------------------------------------------- MQL5 side

def mql_find_volume_gap(vol, sa, sb):
    n = len(vol)
    lo = max(sa, 1)
    hi = min(sb, n - 2)
    best_idx = -1
    best_vol = 1e18
    i = lo
    while i <= hi:
        v0, vl, vr = vol[i], vol[i - 1], vol[i + 1]
        if v0 < vl and v0 < vr and v0 < best_vol:
            best_vol = v0
            best_idx = i
        i += 1
    return best_idx


def mql_is_pin_bar(o, h, l, c, d):
    body = abs(c - o)
    upper = h - max(o, c)
    lower = min(o, c) - l
    is_bull = body > 0.0 and lower >= 2.0 * body and lower > upper
    is_bear = body > 0.0 and upper >= 2.0 * body and upper > lower
    if d == 1:
        return is_bull
    if d == -1:
        return is_bear
    return False


def mql_near_zone_pin(z_top, z_bot, d, o, h, l, c):
    band = (z_top - z_bot) * 0.30
    if not mql_is_pin_bar(o, h, l, c, d):
        return False
    if d == 1:
        return l >= z_bot - band and l < z_bot and c < z_bot
    if d == -1:
        return h <= z_top + band and h > z_top and c > z_top
    return False


def mql_zones_overlap(top1, bot1, top2, bot2):
    return bot1 <= top2 and bot2 <= top1


def mql_index_range(times, duration, from_t, to_t):
    start_idx = -1
    end_idx = -1
    for i, t in enumerate(times):
        tc = t + duration
        if t >= from_t and tc <= to_t:
            if start_idx == -1:
                start_idx = i
            end_idx = i
    return start_idx, end_idx


# ------------------------------------------------- Tehran offset (MQL5 side)

def mql_tehran_is_dst(d: dt.datetime):
    if d.year > 2022:
        return False
    if d.year == 2022 and d.month == 9 and d.day > 21:
        return False
    if 3 < d.month < 9:
        return True
    if d.month == 3:
        return d.day >= 22
    if d.month == 9:
        return d.day <= 21
    return False


def mql_is_excluded_hour(utc: dt.datetime):
    off = dt.timedelta(hours=4, minutes=30) if mql_tehran_is_dst(utc) else dt.timedelta(hours=3, minutes=30)
    teh = utc + off
    return teh.minute == 30 and teh.hour in (23, 0)


# ----------------------------------------------------------------- driver

def main():
    rng = random.Random(4242)
    mismatch = 0
    cases = 0

    for trial in range(6000):
        n = rng.choice([3, 4, 8, 30, 200])
        mode = trial % 5
        if mode == 0:
            vol = [float(rng.randint(0, 1000)) for _ in range(n)]
        elif mode == 1:                      # many ties
            vol = [float(rng.choice([10, 10, 10, 50])) for _ in range(n)]
        elif mode == 2:                      # flat
            vol = [100.0] * n
        elif mode == 3:                      # strictly increasing, no local min
            vol = [float(i) for i in range(n)]
        else:                                # one deep well
            vol = [100.0] * n
            if n > 4:
                vol[rng.randrange(1, n - 1)] = 1.0

        sa = rng.randrange(0, n)
        sb = rng.randrange(sa, n)
        cases += 1
        if pine_find_volume_gap(vol, sa, sb) != mql_find_volume_gap(vol, sa, sb):
            mismatch += 1
            print(f"MISMATCH gap trial={trial} n={n} sa={sa} sb={sb}")

        # pin bar / proximity
        o = rng.uniform(1900, 2000)
        c = o + rng.gauss(0, 3)
        h = max(o, c) + abs(rng.gauss(0, 5))
        l = min(o, c) - abs(rng.gauss(0, 5))
        z_bot = rng.uniform(1900, 2000)
        z_top = z_bot + abs(rng.gauss(0, 4)) + 0.01
        d = rng.choice([1, -1, 0])
        cases += 1
        if pine_near_zone_pin(z_top, z_bot, d, o, h, l, c) != mql_near_zone_pin(z_top, z_bot, d, o, h, l, c):
            mismatch += 1
            print(f"MISMATCH pin trial={trial}")

        # overlap
        a_bot, a_top = sorted((rng.uniform(0, 10), rng.uniform(0, 10)))
        b_bot, b_top = sorted((rng.uniform(0, 10), rng.uniform(0, 10)))
        cases += 1
        if pine_zones_overlap(a_top, a_bot, b_top, b_bot) != mql_zones_overlap(a_top, a_bot, b_top, b_bot):
            mismatch += 1
            print(f"MISMATCH overlap trial={trial}")

        # index range
        dur = 3600
        base = 1_700_000_000
        times = [base + i * dur for i in range(n)]
        tcs = [t + dur for t in times]
        f = base + rng.randrange(0, max(1, n)) * dur
        t_to = f + rng.randrange(0, max(1, n)) * dur
        cases += 1
        if pine_index_range(times, tcs, f, t_to) != mql_index_range(times, dur, f, t_to):
            mismatch += 1
            print(f"MISMATCH index_range trial={trial}")

    print(f"primitives: {cases} comparisons, {mismatch} mismatches")

    # ---- the excluded hours must land where Tehran time says they do ----
    # Post-2022: Tehran is a fixed UTC+3:30, so 23:30 and 00:30 Tehran are the
    # H1 candles opening at 20:00 and 21:00 UTC.
    assert mql_is_excluded_hour(dt.datetime(2024, 6, 10, 20, 0))
    assert mql_is_excluded_hour(dt.datetime(2024, 6, 10, 21, 0))
    assert not mql_is_excluded_hour(dt.datetime(2024, 6, 10, 19, 0))
    assert not mql_is_excluded_hour(dt.datetime(2024, 6, 10, 22, 0))

    # Under the pre-2022 summer DST (UTC+4:30) they shift an hour earlier.
    assert mql_is_excluded_hour(dt.datetime(2021, 6, 10, 19, 0))
    assert mql_is_excluded_hour(dt.datetime(2021, 6, 10, 20, 0))
    assert not mql_is_excluded_hour(dt.datetime(2021, 6, 10, 21, 0))

    # Winter of the same year has no DST, so it is back to 20:00 / 21:00 UTC.
    assert mql_is_excluded_hour(dt.datetime(2021, 1, 10, 20, 0))
    assert not mql_is_excluded_hour(dt.datetime(2021, 1, 10, 19, 0))

    print("tehran exclusion: 9 assertions passed")

    # ---- grading, per the v3 header description ----
    def grade(n):
        return "A" if n <= 0 else "B" if n == 1 else "C" if n == 2 else "D"
    assert [grade(i) for i in range(5)] == ["A", "B", "C", "D", "D"]
    print("grading table: ok")

    return 1 if mismatch else 0


if __name__ == "__main__":
    sys.exit(main())
