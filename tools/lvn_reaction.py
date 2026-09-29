"""Does price react when it returns to the volume void of a closed candle?

The hypothesis under test, in the author's words: take the volume profile of
each closed Weekly / Daily / 4-hour candle with a fixed row count (31), find
its low-volume area, and when price later comes back to that price the market
reacts.

Two things make or break a test like this, and both are handled here.

1. WHICH ROW. The single thinnest row of any candle is almost always the tip
   of a wick - price touched it once and left. That is the candle's high or
   low, not a volume void. What is meant is a VALLEY: heavy volume on one
   side, thin in the middle, heavy on the other. So a row only qualifies when
   the heaviest row somewhere below it AND the heaviest row somewhere above it
   are both real volume areas (a share of the POC), and the row itself sits
   well under the lower of the two. A tapering tail can never qualify, because
   in a tail there is no heavier row on the outer side.

2. COMPARED TO WHAT. "Price reacted at the level" means nothing on its own:
   price reverses at every level some of the time, and the exact bounce rate
   depends on how a touch and a reaction are measured. So every number here is
   compared against levels that were NOT chosen by volume, measured in exactly
   the same way, on exactly the same candles:

     shuffled  - each candle gets another candle's void position (same place
                 inside the range, e.g. 30% up from the low, but not chosen by
                 this candle's own volume). The strictest control: it keeps
                 wherever voids typically sit and removes only the volume.
     interior  - a random interior row of the same candle.

   The void has to beat both.

Measuring a reaction: after the candle closes, find the first bar that trades
through the level with the previous close on one side of it. Then, starting on
the NEXT bar - the touching bar's own high and low partly happened before the
touch, and scoring them would pay out for moves that preceded it - see which
comes first: price moving X back the way it came (a reaction) or X through the
level (a break). X is a fraction of the candle's own range, so the test means
the same thing on a quiet week and a wild one.

    python3 tools/lvn_reaction.py --eurusd-sample
    python3 tools/lvn_reaction.py --csv m1_export.csv.gz
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

import numpy as np
import pandas as pd

PERIOD = {"H4": 4 * 3600, "D1": 86400, "W1": 7 * 86400}
# the forex week opens on Sunday evening, so a week bucket starts Sunday 00:00;
# the Unix epoch was a Thursday, and 1970-01-04 00:00 is 259200 s after it
WEEK_OFFSET = 259200


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------

@dataclass
class Bars:
    time: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    step: int                    # seconds between bars
    label: str

    def __len__(self):
        return len(self.time)


def _to_seconds(values) -> np.ndarray:
    # never assume pandas' datetime unit - convert through an explicit one
    return np.asarray(values).astype("datetime64[s]").astype("int64")


def from_frame(df: pd.DataFrame, label: str) -> Bars:
    cols = {c.lower(): c for c in df.columns}
    t = _to_seconds(df.index.values if "time" not in cols else pd.to_datetime(df[cols["time"]]).values)
    vol_col = cols.get("tick_volume") or cols.get("volume")
    order = np.argsort(t, kind="stable")
    t = t[order]
    diffs = np.diff(t)
    step = int(np.median(diffs[diffs > 0])) if len(diffs) else 60
    return Bars(time=t,
                high=df[cols["high"]].to_numpy(float)[order],
                low=df[cols["low"]].to_numpy(float)[order],
                close=df[cols["close"]].to_numpy(float)[order],
                volume=df[vol_col].to_numpy(float)[order],
                step=step, label=label)


def load_csv(path: str) -> Bars:
    df = pd.read_csv(path)
    df.columns = [c.strip() for c in df.columns]
    df.index = pd.to_datetime(df[[c for c in df.columns if c.lower() == "time"][0]],
                              format="mixed")
    return from_frame(df.drop(columns=[c for c in df.columns if c.lower() == "time"]),
                      label=path)


def load_eurusd_sample() -> Bars:
    """Real EURUSD H1 with tick volume, bundled with the backtesting package.
    Apr 2017 - Feb 2018, 5000 bars. Small, and hourly - enough for a first
    look at Weekly and Daily voids, too coarse for 4-hour ones."""
    from backtesting.test import EURUSD
    return from_frame(EURUSD, label="EURUSD H1 (backtesting.py sample, 2017-04..2018-02)")


# --------------------------------------------------------------------------
# candles and their profiles
# --------------------------------------------------------------------------

def parent_candles(b: Bars, tf: str, min_intrabars: int):
    """(start, end) intrabar index ranges for each complete parent candle."""
    offset = WEEK_OFFSET if tf == "W1" else 0
    key = (b.time - offset) // PERIOD[tf]
    edges = np.flatnonzero(np.diff(key)) + 1
    starts = np.concatenate(([0], edges))
    ends = np.concatenate((edges, [len(b)]))
    keep = (ends - starts) >= min_intrabars
    # the last group may still be forming; it has no future to test anyway
    return list(zip(starts[keep][:-1], ends[keep][:-1]))


def profile(h: np.ndarray, l: np.ndarray, v: np.ndarray, rows: int):
    """Volume per row, each bar's volume spread over the rows its range covers
    (the way TradingView's volume profile distributes it)."""
    top, bot = float(h.max()), float(l.min())
    if top <= bot:
        return None, None
    step = (top - bot) / rows
    edges = bot + step * np.arange(rows + 1)

    lo = np.maximum(l[:, None], edges[None, :-1])
    hi = np.minimum(h[:, None], edges[None, 1:])
    overlap = np.clip(hi - lo, 0.0, None)
    span = h - l
    weights = overlap / np.where(span > 0, span, 1.0)[:, None]

    flat = span <= 0                      # a bar with no range sits in one row
    if flat.any():
        idx = np.clip(((l[flat] - bot) / step).astype(int), 0, rows - 1)
        weights[flat] = 0.0
        weights[np.flatnonzero(flat), idx] = 1.0

    return (weights * v[:, None]).sum(axis=0), edges


def volume_void(vol: np.ndarray, peak_frac: float, valley_frac: float):
    """The thinnest row that has real volume on BOTH sides of it.

    For row i, the heaviest row anywhere below it and the heaviest row
    anywhere above it must each carry at least `peak_frac` of the POC, and row
    i must hold at most `valley_frac` of the lighter of those two. A row in a
    tapering tail fails automatically - the outer side of a tail is lighter,
    never heavier.
    """
    n = len(vol)
    poc = float(vol.max())
    if poc <= 0:
        return None
    below = np.concatenate(([-np.inf], np.maximum.accumulate(vol)[:-1]))
    above = np.concatenate((np.maximum.accumulate(vol[::-1])[::-1][1:], [-np.inf]))
    flank = np.minimum(below, above)
    ok = (flank >= peak_frac * poc) & (vol <= valley_frac * flank) & (vol < flank)
    ok[0] = ok[-1] = False
    if not ok.any():
        return None
    idx = np.flatnonzero(ok)
    return int(idx[np.argmin(vol[idx])])        # thinnest; first on ties


# --------------------------------------------------------------------------
# touches and reactions
# --------------------------------------------------------------------------

def _first(mask: np.ndarray) -> int:
    return int(np.argmax(mask)) if mask.any() else -1


def reaction(b: Bars, level: float, search_from: int, search_to: int,
             x: float, resolve_bars: int):
    """1.0 reaction, 0.0 break, 0.5 same bar, None = untouched or unresolved."""
    if search_from < 1 or search_to <= search_from:
        return None
    hit = (b.low[search_from:search_to] <= level) & (b.high[search_from:search_to] >= level)
    j = _first(hit)
    if j < 0:
        return None
    j += search_from

    prev = b.close[j - 1]
    if prev > level:
        came_from = 1                   # from above: a reaction goes back up
    elif prev < level:
        came_from = -1
    else:
        return None

    a, z = j + 1, min(j + 1 + resolve_bars, len(b))
    if a >= z:
        return None
    up = _first(b.high[a:z] >= level + x)
    dn = _first(b.low[a:z] <= level - x)
    back, through = (up, dn) if came_from == 1 else (dn, up)

    if back < 0 and through < 0:
        return None
    if through < 0 or (back >= 0 and back < through):
        return 1.0
    if back < 0 or through < back:
        return 0.0
    return 0.5


# --------------------------------------------------------------------------
# the experiment
# --------------------------------------------------------------------------

@dataclass
class Result:
    tf: str
    candles: int
    with_void: int
    edge_min_share: float        # how often the raw thinnest row is a wick tip
    events: int                  # void touched and resolved
    void_rate: float
    shuffled_rate: float
    shuffled_p: float
    interior_rate: float
    interior_p: float


def run(b: Bars, tf: str, rows: int = 31, peak_frac: float = 0.5,
        valley_frac: float = 0.5, x_frac: float = 0.2, wait: int = 5,
        n_perm: int = 2000, seed: int = 7, min_intrabars: int = 20) -> Result | None:
    cands = parent_candles(b, tf, min_intrabars)
    if len(cands) < 10:
        return None

    per = PERIOD[tf] // b.step            # intrabars per parent candle
    resolve = max(1, per)

    table = []                            # outcome for every row of every candle
    void_rows = []
    edge_min = 0
    profiled = 0

    for k, (s, e) in enumerate(cands):
        vol, edges = profile(b.high[s:e], b.low[s:e], b.volume[s:e], rows)
        if vol is None:
            continue
        profiled += 1
        if int(np.argmin(vol)) in (0, 1, rows - 2, rows - 1):
            edge_min += 1

        vr = volume_void(vol, peak_frac, valley_frac)
        if vr is None:
            continue

        rng_k = edges[-1] - edges[0]
        x = x_frac * rng_k
        end_k = cands[min(k + wait, len(cands) - 1)][1]
        mids = (edges[:-1] + edges[1:]) * 0.5
        outcomes = [reaction(b, float(m), e, end_k, x, resolve) for m in mids]
        table.append(outcomes)
        void_rows.append(vr)

    if len(table) < 10:
        return None

    table = np.array([[np.nan if o is None else o for o in row] for row in table])
    void_rows = np.array(void_rows)
    K = len(void_rows)
    ix = np.arange(K)

    actual = table[ix, void_rows]
    events = int(np.sum(~np.isnan(actual)))
    if events < 8:
        return None
    rate = float(np.nanmean(actual))

    rng = np.random.default_rng(seed)
    interior = np.arange(3, rows - 3)
    shuf = np.empty(n_perm)
    inter = np.empty(n_perm)
    for p in range(n_perm):
        shuf[p] = np.nanmean(table[ix, void_rows[rng.permutation(K)]])
        inter[p] = np.nanmean(table[ix, rng.choice(interior, K)])

    return Result(
        tf=tf, candles=len(cands), with_void=K,
        edge_min_share=edge_min / max(1, profiled),
        events=events, void_rate=rate,
        shuffled_rate=float(shuf.mean()),
        shuffled_p=float((np.sum(shuf >= rate) + 1) / (n_perm + 1)),
        interior_rate=float(inter.mean()),
        interior_p=float((np.sum(inter >= rate) + 1) / (n_perm + 1)),
    )


def report(b: Bars, tfs, rows, peak_frac, valley_frac, x_fracs, wait, n_perm, seed):
    print(f"data: {b.label}")
    print(f"      {len(b):,} bars, {b.step // 60} min apart, "
          f"{(b.time[-1] - b.time[0]) / 86400:.0f} days")
    print(f"rows={rows}  void: both sides >= {peak_frac:g} x POC, "
          f"void <= {valley_frac:g} x lighter side  wait={wait} candles\n")

    header = (f"{'TF':<3} {'X':>5} {'candles':>7} {'voids':>5} {'tested':>6} "
              f"{'void':>6} {'shuffled':>9} {'p':>6} {'interior':>9} {'p':>6}")
    print(header)
    print("-" * len(header))
    rows_out = []
    for tf in tfs:
        for xf in x_fracs:
            r = run(b, tf, rows, peak_frac, valley_frac, xf, wait, n_perm, seed)
            if r is None:
                print(f"{tf:<3} {xf:>5.2f}   not enough data at this resolution")
                continue
            rows_out.append(r)
            print(f"{tf:<3} {xf:>5.2f} {r.candles:>7} {r.with_void:>5} {r.events:>6} "
                  f"{100 * r.void_rate:>5.1f}% {100 * r.shuffled_rate:>8.1f}% "
                  f"{r.shuffled_p:>6.3f} {100 * r.interior_rate:>8.1f}% {r.interior_p:>6.3f}")
    if rows_out:
        edge = np.mean([r.edge_min_share for r in rows_out])
        print(f"\nthe raw thinnest row was a wick tip (outer 2 rows) in "
              f"{100 * edge:.0f}% of candles")
    return rows_out


def main():
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", help="OHLCV CSV, e.g. the ExportM1.mq5 output")
    src.add_argument("--eurusd-sample", action="store_true",
                     help="real EURUSD H1 bundled with the backtesting package")
    ap.add_argument("--tf", default="W1,D1,H4")
    ap.add_argument("--rows", type=int, default=31)
    ap.add_argument("--peak-frac", type=float, default=0.5)
    ap.add_argument("--valley-frac", type=float, default=0.5)
    ap.add_argument("--x", default="0.1,0.2,0.3",
                    help="reaction distance as fractions of the candle's range")
    ap.add_argument("--wait", type=int, default=5,
                    help="candles to wait for price to come back")
    ap.add_argument("--perm", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()

    b = load_eurusd_sample() if a.eurusd_sample else load_csv(a.csv)
    report(b, a.tf.split(","), a.rows, a.peak_frac, a.valley_frac,
           [float(x) for x in a.x.split(",")], a.wait, a.perm, a.seed)


if __name__ == "__main__":
    main()
