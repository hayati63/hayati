#!/usr/bin/env python3
"""Differential test of the clarity/LVN algorithm.

There is no MQL5 compiler on Linux, so the MQL5 port cannot be run directly.
What can be checked is that the *algorithm* was transcribed faithfully. Both
sides below are written independently:

  pine_valley_clarity()  follows pinescript/lvn_clarity_cascade.pine line by line,
                         including Pine's own semantics (array.indexof returns the
                         first match, the `if not found` guard, na handling).
  mql_zone_from_m1()     follows MQL5/Include/Hayati/ClarityLVN.mqh line by line,
                         including ArrayMinimum returning the first minimum and
                         the `rows <= max_rows && !found` loop condition.

They are then run against the same random candle sets and compared. Any
divergence is a transcription bug in the port.

    python3 tools/verify_clarity.py
"""

import math
import random
import sys

# --------------------------------------------------------------------------
# Pine side — transcribed from f_valleyClarity() in the .pine file
# --------------------------------------------------------------------------

def pine_valley_clarity(hi_arr, lo_arr, vol_arr, min_b, max_b, gap_thresh):
    n = len(hi_arr)
    bar_high = max(hi_arr) if n > 0 else None
    bar_low = min(lo_arr) if n > 0 else None

    best_clarity = -1.0
    best_buckets = None
    best_min_idx = None
    best_step = None
    found = False

    if n > 0 and bar_high is not None and bar_high > bar_low:
        for b_count in range(min_b, max_b + 1):
            if not found:
                step = (bar_high - bar_low) / b_count
                if step > 0:
                    bins = [0.0] * b_count
                    for i in range(n):
                        h, l, v = hi_arr[i], lo_arr[i], vol_arr[i]
                        mid = (h + l) / 2.0
                        idx = int(min(b_count - 1,
                                      max(0, math.floor((mid - bar_low) / step))))
                        bins[idx] += v
                    min_vol = min(bins)
                    min_idx = bins.index(min_vol)          # array.indexof -> first
                    total_vol = sum(bins)
                    avg_other = ((total_vol - min_vol) / (b_count - 1)
                                 if b_count > 1 else min_vol)
                    clarity = (1.0 - min_vol / avg_other) * 100.0 if avg_other > 0 else 0.0
                    if clarity > best_clarity:
                        best_clarity = clarity
                        best_buckets = b_count
                        best_min_idx = min_idx
                        best_step = step
                    if clarity >= gap_thresh:
                        found = True

    if best_buckets is None:
        return None
    lvn_low = bar_low + best_min_idx * best_step
    lvn_high = lvn_low + best_step
    return dict(bottom=lvn_low, top=lvn_high, rows=best_buckets,
                clarity=best_clarity, clear=found)


# --------------------------------------------------------------------------
# MQL5 side — transcribed from CL_ZoneFromM1() in ClarityLVN.mqh
# --------------------------------------------------------------------------

def array_minimum(arr, start, count):
    """MQL5 ArrayMinimum: index of the FIRST minimum in the range."""
    best = start
    for i in range(start, start + count):
        if arr[i] < arr[best]:
            best = i
    return best


def mql_zone_from_m1(m1, min_rows, max_rows, gap_threshold):
    n = len(m1)
    if n < 2:
        return None

    bar_high = m1[0]["high"]
    bar_low = m1[0]["low"]
    for i in range(1, n):
        if m1[i]["high"] > bar_high:
            bar_high = m1[i]["high"]
        if m1[i]["low"] < bar_low:
            bar_low = m1[i]["low"]
    if bar_high <= bar_low:
        return None

    best_clarity = -1.0
    best_rows = 0
    best_idx = -1
    best_step = 0.0
    found = False

    rows = min_rows
    while rows <= max_rows and not found:
        step = (bar_high - bar_low) / rows
        if step <= 0.0:
            rows += 1
            continue
        bins = [0.0] * rows
        for i in range(n):
            mid = (m1[i]["high"] + m1[i]["low"]) * 0.5
            idx = int(math.floor((mid - bar_low) / step))
            if idx < 0:
                idx = 0
            if idx > rows - 1:
                idx = rows - 1
            bins[idx] += m1[i]["vol"]

        min_idx = array_minimum(bins, 0, rows)
        min_vol = bins[min_idx]
        total = 0.0
        for i in range(rows):
            total += bins[i]
        avg_other = (total - min_vol) / (rows - 1) if rows > 1 else min_vol
        clarity = (1.0 - min_vol / avg_other) * 100.0 if avg_other > 0.0 else 0.0

        if clarity > best_clarity:
            best_clarity = clarity
            best_rows = rows
            best_idx = min_idx
            best_step = step
        if clarity >= gap_threshold:
            found = True
        rows += 1

    if best_idx < 0:
        return None
    bottom = bar_low + best_idx * best_step
    return dict(bottom=bottom, top=bottom + best_step, rows=best_rows,
                clarity=best_clarity, clear=found)


# --------------------------------------------------------------------------
# Containment rule — CL_FindFirstContaining / f_findFirstContaining
# --------------------------------------------------------------------------

def find_first_containing(bars, win_from, win_to, z_top, z_bottom, body_only, dur):
    for b in bars:
        if b["time"] < win_from:
            continue
        if b["time"] + dur > win_to:
            continue
        cover_high = max(b["open"], b["close"]) if body_only else b["high"]
        cover_low = min(b["open"], b["close"]) if body_only else b["low"]
        if cover_high >= z_top and cover_low <= z_bottom:
            return b["time"]
    return None


# --------------------------------------------------------------------------

def random_m1(rng, count, base=1.1000, tick=0.00001):
    bars = []
    price = base
    for _ in range(count):
        price += rng.gauss(0, 30 * tick)
        spread = abs(rng.gauss(0, 10 * tick)) + tick
        hi = price + spread
        lo = price - spread
        bars.append(dict(high=hi, low=lo, vol=float(rng.randint(0, 400))))
    return bars


def main():
    rng = random.Random(20260916)
    cases = 0
    mismatches = 0

    # Sweep parameter combinations, including degenerate ones.
    for trial in range(4000):
        n = rng.choice([2, 3, 5, 17, 60, 240, 1440])
        bars = random_m1(rng, n)

        # occasionally force pathological shapes
        mode = trial % 7
        if mode == 1:                       # all volumes zero
            for b in bars:
                b["vol"] = 0.0
        elif mode == 2:                     # ties: several empty buckets
            for b in bars:
                b["vol"] = 100.0 if rng.random() < 0.5 else 0.0
        elif mode == 3:                     # completely flat price
            for b in bars:
                b["high"] = b["low"] = 1.1
        elif mode == 4:                     # one dominant bucket
            for i, b in enumerate(bars):
                b["vol"] = 10000.0 if i % 3 == 0 else 1.0

        min_rows = rng.choice([2, 3, 4])
        max_rows = min_rows + rng.choice([0, 1, 4, 8, 12])
        gap = rng.choice([10.0, 40.0, 75.0, 95.0])

        hi = [b["high"] for b in bars]
        lo = [b["low"] for b in bars]
        vo = [b["vol"] for b in bars]

        want = pine_valley_clarity(hi, lo, vo, min_rows, max_rows, gap)
        got = mql_zone_from_m1(bars, min_rows, max_rows, gap)

        # The MQL5 side refuses windows with fewer than 2 candles; the Pine
        # script applies that same guard at the call site (sb > sa), so treat
        # a 1-candle window as "no zone" on both sides.
        if len(bars) < 2:
            want = None

        cases += 1
        if (want is None) != (got is None):
            mismatches += 1
            print(f"MISMATCH (presence) trial={trial} n={n} rows={min_rows}..{max_rows} "
                  f"gap={gap}: pine={want} mql={got}")
            continue
        if want is None:
            continue
        for key in ("rows", "clear"):
            if want[key] != got[key]:
                mismatches += 1
                print(f"MISMATCH ({key}) trial={trial}: pine={want} mql={got}")
                break
        else:
            for key in ("bottom", "top", "clarity"):
                if abs(want[key] - got[key]) > 1e-12:
                    mismatches += 1
                    print(f"MISMATCH ({key}) trial={trial}: pine={want} mql={got}")
                    break

    print(f"clarity search: {cases} cases, {mismatches} mismatches")

    # ---- containment rule: first match wins, not the best fit ----
    bars = [
        dict(time=0,   open=10, close=11, high=20, low=1),   # contains, first
        dict(time=100, open=10, close=11, high=15, low=4),   # tighter fit, later
    ]
    z_top, z_bot = 14.0, 6.0
    first = find_first_containing(bars, 0, 200, z_top, z_bot, False, 100)
    assert first == 0, f"containment must take the first match, got {first}"

    # body mode must reject a candle that only covers the zone with its wicks
    body = find_first_containing(bars, 0, 200, z_top, z_bot, True, 100)
    assert body is None, f"body mode should find nothing here, got {body}"

    # a candle whose close time falls outside the parent window is skipped
    late = [dict(time=150, open=10, close=11, high=20, low=1)]
    assert find_first_containing(late, 0, 200, z_top, z_bot, False, 100) is None

    print("containment rule: 3 assertions passed")
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
