"""
LVN Clarity Cascade (automated v1) — backtest.

Rules as in the Pine script:
  * LVN of a candle: its sub-candles (ONE timeframe finer) are binned by their midpoint
    (H+L)/2 over the candle's own high/low; rows from 3 to 8; the row count with the best
    "clarity" = (1 - minVol / avg(other rows)) * 100 wins, stopping early at >= 40%.
    The zone is the thinnest row.
  * Cascade (depth N): inside the current window, the FIRST lower-TF candle whose full range
    contains the zone; its own LVN becomes the zone.
  * No bias until the end: the first bar that touches the final zone decides it — previous
    close above the zone -> BUY (price came from above), below -> SELL.  A newer setup
    replaces an untouched one.
Trades: limit at the touched edge, SL beyond the far edge + buffer x ATR(H1), TP = RR x risk.
Control: a random row instead of the thinnest one.  Base data M5 (M1 unavailable), so the
finest usable profile is an M15 candle binned by M5 bars.
"""
import argparse
import itertools
import os

import numpy as np
import pandas as pd
from numba import njit

from run_study import IS_END, metrics
from vgap_engine import (TF_MIN, atr_sma, build_rung, load_bars, r_multiples, simulate, spread_model,
                         to_minutes, value_at_base)

FINER = {"D1": "H4", "H4": "H1", "H1": "M15", "M15": "M5"}


@njit(cache=True)
def lvn_clarity(sh, sl, sv, s, e, hi, lo, min_b, max_b, thr, rand_u):
    if e < s or hi <= lo:
        return np.nan, np.nan, -1.0
    best_c = -1.0
    best_b = -1
    best_i = -1
    for b in range(min_b, max_b + 1):
        step = (hi - lo) / b
        bins = np.zeros(b)
        for i in range(s, e + 1):
            mid = (sh[i] + sl[i]) / 2.0
            k = int(min(b - 1, max(0.0, np.floor((mid - lo) / step))))
            bins[k] += sv[i]
        mi = 0
        for k in range(1, b):
            if bins[k] < bins[mi]:
                mi = k
        tot = bins.sum()
        avg = (tot - bins[mi]) / (b - 1)
        cl = (1.0 - bins[mi] / avg) * 100.0 if avg > 0 else 0.0
        if cl > best_c:
            best_c, best_b, best_i = cl, b, mi
        if cl >= thr:
            break
    if rand_u >= 0:
        best_i = int(rand_u * best_b)
    step = (hi - lo) / best_b
    zb = lo + best_i * step
    return zb + step, zb, best_c


def build_setups(base, top, depth, control=False, thr=40.0, seed=0):
    bt = to_minutes(base["time"])
    o, h, l, c, v = [base[k].values.astype(np.float64) for k in ("open", "high", "low", "close", "volume")]
    chain = [top]
    while len(chain) <= depth + 1 and chain[-1] in FINER:
        chain.append(FINER[chain[-1]])
    R = {tf: build_rung(bt, o, h, l, c, v, tf, 5) for tf in set(chain + ["H1"])}
    rng = np.random.default_rng(seed)

    def lvn(tf, j):
        fr = R[FINER[tf]]
        s = int(np.searchsorted(fr.t, R[tf].t[j]))
        e = int(np.searchsorted(fr.t, R[tf].tc[j])) - 1
        return lvn_clarity(fr.h, fr.l, fr.v, s, e, R[tf].h[j], R[tf].l[j], 3, 8, thr,
                           rng.random() if control else -1.0)

    rows = []
    T = R[top]
    for k in range(len(T.t)):
        if top == "M15" or FINER[top] not in R:
            break
        zt, zb, cl = lvn(top, k)
        if np.isnan(zt):
            continue
        tf, j, ok = top, k, True
        for dstep in range(depth):
            lt = FINER[tf]
            if lt not in FINER or FINER[lt] not in R:      # no finer bins available (M5 needs M1)
                ok = False
                break
            r = R[lt]
            j0 = int(np.searchsorted(r.t, R[tf].t[j]))
            j1 = int(np.searchsorted(r.t, R[tf].tc[j]))
            f = -1
            for jj in range(j0, j1):
                if r.h[jj] >= zt and r.l[jj] <= zb:
                    f = jj
                    break
            if f < 0:
                ok = False
                break
            nt, nb, _ = lvn(lt, f)
            if np.isnan(nt):
                ok = False
                break
            zt, zb, tf, j = nt, nb, lt, f
        if not ok or T.avail[k] >= len(bt):
            continue
        rows.append((int(T.avail[k]), zt, zb, cl))
    df = pd.DataFrame(rows, columns=["sig_idx", "zt", "zb", "clarity"])
    h1 = R["H1"]
    atr_b = value_at_base(h1, atr_sma(h1, 14), len(bt))
    aux = dict(base_t=bt, o=o, h=h, l=l, c=c, v=v)
    return df, aux, atr_b


@njit(cache=True)
def find_touch(h, l, c, si, end, zt, zb):
    """First bar touching the zone whose previous close is outside it -> (bar, dir)."""
    n = len(si)
    tb = np.full(n, -1, dtype=np.int64)
    td = np.zeros(n, dtype=np.int64)
    for k in range(n):
        for i in range(max(si[k], 1), end[k]):
            if h[i] >= zb[k] and l[i] <= zt[k]:
                if c[i - 1] > zt[k]:
                    tb[k] = i
                    td[k] = 1
                    break
                if c[i - 1] < zb[k]:
                    tb[k] = i
                    td[k] = -1
                    break
    return tb, td


def run(args):
    base = load_bars(args.data)
    base = base[(base.time >= "2011-06-01") & (base.time < "2025-03-21")].reset_index(drop=True)
    rows = []
    for top, depth in (("D1", 0), ("D1", 1), ("D1", 2), ("H4", 0), ("H4", 1), ("H4", 2), ("H1", 0), ("H1", 1)):
        hold = {"H1": 24, "H4": 96, "D1": 240}[top] * 60
        for control in (False, True):
            df, aux, atr_b = build_setups(base, top, depth, control)
            bt = aux["base_t"]
            si = df.sig_idx.values.astype(np.int64)
            end = np.r_[si[1:], len(bt)].astype(np.int64)            # replaced by the next setup
            zt, zb = df.zt.values, df.zb.values
            tb, d = find_touch(aux["h"], aux["l"], aux["c"], si, end, zt, zb)
            ok = tb >= 0
            t_sig = pd.to_datetime(bt[si] * 60, unit="s")
            ok &= (t_sig >= pd.Timestamp("2012-01-01"))
            idx = np.flatnonzero(ok)
            dd = d[idx]
            E = np.where(dd == 1, zt[idx], zb[idx])
            atr = atr_b[tb[idx]]
            ism = t_sig[idx] < IS_END
            print(f"{top} depth={depth} {'control' if control else 'LVN'}: setups={len(df)} touched={len(idx)} "
                  f"zone/ATR={np.nanmedian((zt[idx] - zb[idx]) / atr):.2f}", flush=True)
            for buf, cost in itertools.product((0.1, 0.25, 0.5), ("net", "gross")):
                S = np.where(dd == 1, zb[idx] - buf * atr, zt[idx] + buf * atr)
                spr = spread_model(aux["c"], *((0.20, 1.0) if cost == "net" else (0.0, 0.0)))
                cm = 0.07 if cost == "net" else 0.0
                sim = simulate(aux, dd, tb[idx], end[idx], E, S, np.full(len(idx), hold, dtype=np.int64), spr, cm, True)
                for rr in (1.0, 1.5, 2.0, 3.0):
                    r, _ = r_multiples(sim, dd, E, S, rr, cm)
                    mi, mo = metrics(r[ism]), metrics(r[~ism])
                    rows.append(dict(top=top, depth=depth, control=control, buf=buf, cost=cost, rr=rr,
                                     is_n=mi["n"], is_win=mi["win"], is_avgR=mi["avgR"], is_t=mi["t"],
                                     oos_n=mo["n"], oos_win=mo["win"], oos_avgR=mo["avgR"], oos_t=mo["t"],
                                     oos_maxDD=mo["maxDD"]))
    res = pd.DataFrame(rows)
    os.makedirs(args.out, exist_ok=True)
    res.round(4).to_csv(os.path.join(args.out, "lvn_clarity_grid.csv"), index=False)
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="results")
    run(ap.parse_args())
