"""
Backtest of M. A. Poursamadi's published price-action setups (poursamadi.com) on XAUUSD.

SP2L (Spike-2Leg)
  * spike: `ns` consecutive strong trend candles (body >= 50% of range, close in the outer
    third), total move >= `m` x ATR(14) and a price gap ("P-Gap": low of the last spike candle
    above the high of the candle two bars earlier, mirrored for sells)
  * 2nd leg: the first later candle that takes out the previous candle's low (buy) -> buy limit
    at that previous low (the limit trails the last candle's low until it is hit)
  * SL behind the candle the spike started from, TP = RR x risk (default 1:1)
  * optional add-on: a second limit at 50% between entry and SL, same SL/TP
PRO BTB (Back To Breakeven)
  * level = swing high/low (fractal of `p` bars each side) or previous day's high/low
  * breakout = first candle closing beyond the level; BE = that candle's close
  * entries: (1) limit on BE, (4) limit on the broken level, (3) market after the first candle
    that touched BE and closed back on the breakout side, (2) stop above/below that candle,
    (5) stop on the breakout candle's extreme after the return to BE
  * SL behind the breakout candle, TP = RR x risk (>= 2 recommended); orders valid until hit
    (capped at `exp` candles)
MicroMAP
  * spike of `ns` strong candles (move >= m x ATR) then a counter-trend micro-channel of
    >= `mc` candles with lower highs (buy) that are smaller than the spike candles
  * entry 1: buy stop at the high of the last micro-channel candle, SL its low
  * after a stop: entry 2 = break of the high of a new candle, SL the lowest new low;
    entry 3 = same, SL that candle's low; three stops -> setup void
Management
  * fixed TP, or the Time-Analysis "half-close": half at 2R (rest to 4R) or half at 3R (rest
    to 6R), SL unchanged.  Max hold 1 day.
Filters (applied to the entry candle): Poursamadi's best gold windows 10:00-13:00 and
15:30-18:00 broker time (GMT+3 broker == this NY+7 server clock), and higher-timeframe trend
(close vs EMA 50 of the next timeframe up).
Controls: the same rules on random candles (SP2L / MicroMAP) or random horizontal lines (BTB).
"""
import argparse
import itertools
import os

import numpy as np
import pandas as pd
from numba import njit

from run_study import IS_END, metrics
from vgap_engine import load_bars, spread_model

TFS = {"M5": 5, "M15": 15, "H1": 60}
HOLD_MIN = 1440
MGMT = {"RR1": (1.0, 1.0, 1.0), "RR1.5": (1.5, 1.5, 1.0), "RR2": (2.0, 2.0, 1.0), "RR3": (3.0, 3.0, 1.0),
        "HC2-4": (2.0, 4.0, 0.5), "HC3-6": (3.0, 6.0, 0.5)}


# ------------------------------------------------------------------------------------------
# order fills and position management (real prices; bid data, ask = bid + spread)
# ------------------------------------------------------------------------------------------
@njit(cache=True)
def try_fill(d, et, E, o, h, l, s):
    """et 0 = limit, 1 = stop, 2 = market at the open.  Returns fill price or nan."""
    if et == 2:
        return o + s if d == 1 else o
    if d == 1:
        if et == 0:
            if o + s <= E:
                return o + s
            if l + s <= E:
                return E
        else:
            if o >= E:
                return o + s
            if h >= E:
                return E + s
    else:
        if et == 0:
            if o >= E:
                return o
            if h >= E:
                return E
        else:
            if o <= E:
                return o
            if l <= E:
                return E
    return np.nan


@njit(cache=True)
def manage(t, o, h, l, c, spr, d, f, fp, S, T1, T2, frac, hold, be_px):
    """Returns (pnl per unit, exit bar, outcome) - outcome 1 = full stop, 2 = targets, 3 = time.
    be_px: once a later candle trades there, the stop moves to the entry price (nan = off)."""
    n = len(t)
    deadline = t[f] + hold
    rem1, rem2 = frac, 1.0 - frac
    pnl = 0.0
    # fill bar: pessimistic - the stop counts if the bar reached it; targets only on the close
    if d == 1:
        if l[f] <= S:
            return S - fp, f, 1
        if c[f] >= T1:
            pnl += rem1 * (T1 - fp)
            rem1 = 0.0
        if rem2 > 0 and c[f] >= T2:
            pnl += rem2 * (T2 - fp)
            rem2 = 0.0
    else:
        if h[f] + spr[f] >= S:
            return fp - S, f, 1
        if c[f] + spr[f] <= T1:
            pnl += rem1 * (fp - T1)
            rem1 = 0.0
        if rem2 > 0 and c[f] + spr[f] <= T2:
            pnl += rem2 * (fp - T2)
            rem2 = 0.0
    j = f
    while rem1 + rem2 > 1e-12:
        j += 1
        if j >= n:
            px = c[n - 1] if d == 1 else c[n - 1] + spr[n - 1]
            pnl += (rem1 + rem2) * d * (px - fp)
            return pnl, n - 1, 3
        if t[j] >= deadline:
            px = o[j] if d == 1 else o[j] + spr[j]
            pnl += (rem1 + rem2) * d * (px - fp)
            return pnl, j, 3
        if d == 1:
            lo, hi, op = l[j], h[j], o[j]
        else:
            lo, hi, op = h[j] + spr[j], l[j] + spr[j], o[j] + spr[j]   # adverse / favourable / open
        full = rem1 + rem2 >= 1.0 - 1e-12
        # gap through the stop or a target at the open
        if d * (op - S) <= 0:
            pnl += (rem1 + rem2) * d * (op - fp)
            return pnl, j, 1 if full else 2
        if rem1 > 0 and d * (op - T1) >= 0:
            pnl += rem1 * d * (op - fp)
            rem1 = 0.0
        if rem2 > 0 and d * (op - T2) >= 0:
            pnl += rem2 * d * (op - fp)
            rem2 = 0.0
        if rem1 + rem2 <= 1e-12:
            return pnl, j, 2
        if d * (lo - S) <= 0:                                 # stop first (pessimistic)
            pnl += (rem1 + rem2) * d * (S - fp)
            return pnl, j, 1 if rem1 + rem2 >= 1.0 - 1e-12 else 2
        if rem1 > 0 and d * (hi - T1) >= 0:
            pnl += rem1 * d * (T1 - fp)
            rem1 = 0.0
        if rem2 > 0 and d * (hi - T2) >= 0:
            pnl += rem2 * d * (T2 - fp)
            rem2 = 0.0
        if not np.isnan(be_px) and d * (hi - be_px) >= 0 and d * (S - fp) < 0:
            S = fp
    return pnl, j, 2


# ------------------------------------------------------------------------------------------
# setup detection helpers (long logic on "det" arrays = prices, or negated prices for sells)
# ------------------------------------------------------------------------------------------
@njit(cache=True)
def strong_bull(O, H, L, C, i):
    r = H[i] - L[i]
    return r > 0 and C[i] > O[i] and (C[i] - O[i]) >= 0.5 * r and (C[i] - L[i]) >= 0.667 * r


@njit(cache=True)
def spike_end(O, H, L, C, atr, k, ns, m, need_gap):
    if k < ns + 2:
        return False
    for i in range(k - ns + 1, k + 1):
        if not strong_bull(O, H, L, C, i):
            return False
    s0 = k - ns + 1
    a = atr[s0 - 1]
    if not (a > 0) or C[k] - O[s0] < m * a:
        return False
    if need_gap and not (L[k] > H[k - 2]):
        return False
    return True


@njit(cache=True)
def count_spikes(O, H, L, C, atr, ns, m, gap):
    k = 0
    for i in range(len(O)):
        if spike_end(O, H, L, C, atr, i, ns, m, gap):
            k += 1
    return k


# ------------------------------------------------------------------------------------------
# SP2L
# ------------------------------------------------------------------------------------------
@njit(cache=True)
def sp2l(t, o, h, l, c, spr, d, O, H, L, C, atr, ns, m, wait, rr1, rr2, frac, hold, rand_mask, comm,
         out_sig, out_fill, out_r1, out_rc, be_r=0.0, out_x=np.zeros(1, dtype=np.int64)):
    """out_r1 = R of the main entry; out_rc = R of main + 50% add-on (risk = both legs)."""
    n = len(t)
    cnt = 0
    busy = -1
    for k in range(n - 1):
        if k <= busy:
            continue
        if rand_mask[0] >= 0:
            if not rand_mask[k] or k < ns + 2:
                continue
        elif not spike_end(O, H, L, C, atr, k, ns, m, True):
            continue
        Sd = L[k - ns + 1]
        for j in range(k + 1, min(n, k + 1 + wait)):
            Ed = L[j - 1]
            if Ed <= Sd:
                break
            E, S = d * Ed, d * Sd
            fp = try_fill(d, 0, E, o[j], h[j], l[j], spr[j])
            if np.isnan(fp):
                if L[j] <= Sd:
                    break
                continue
            risk = Ed - Sd
            T1, T2 = d * (Ed + rr1 * risk), d * (Ed + rr2 * risk)
            bep = d * (Ed + be_r * risk) if be_r > 0 else np.nan
            p1, x, _ = manage(t, o, h, l, c, spr, d, j, fp, S, T1, T2, frac, hold, bep)
            # add-on at the midpoint, valid while the trade is open
            Md = 0.5 * (Ed + Sd)
            p2, r2 = 0.0, 0.5 * risk
            for jj in range(j, x + 1):
                fp2 = try_fill(d, 0, d * Md, o[jj], h[jj], l[jj], spr[jj])
                if not np.isnan(fp2):
                    q, _, _ = manage(t, o, h, l, c, spr, d, jj, fp2, S, T1, T2, frac, hold, bep)
                    p2 = q - comm
                    break
            out_sig[cnt] = k
            out_fill[cnt] = j
            out_r1[cnt] = (p1 - comm) / risk
            out_rc[cnt] = (p1 - comm + p2) / (risk + r2)
            if len(out_x) > 1:
                out_x[cnt] = x
            cnt += 1
            busy = x
            break
    return cnt


# ------------------------------------------------------------------------------------------
# PRO BTB
# ------------------------------------------------------------------------------------------
@njit(cache=True)
def btb(t, o, h, l, c, spr, d, O, H, L, C, lev_at, lev_val, mode, strong, exp, rr1, rr2, frac, hold, comm,
        out_sig, out_fill, out_r, be_r=0.0, out_x=np.zeros(1, dtype=np.int64), min_lv=0):
    """lev_val[k]: a new level (det space) becomes known at bar k (nan = none).
    min_lv = 0: one trade per broken level (a candle breaking 3 levels opens 3 identical trades);
    min_lv >= 1: one trade per breakout candle, only if it broke at least min_lv levels at once."""
    n = len(t)
    act = np.empty(4096)
    age = np.empty(4096, dtype=np.int64)
    crossed = np.empty(4096)
    na = 0
    cnt = 0
    for k in range(1, n - 1):
        if not np.isnan(lev_val[k]):
            if na < 4096:
                act[na] = lev_val[k]
                age[na] = k
                na += 1
        if na == 0:
            continue
        # levels broken (closed through) by this candle; expired levels are dropped
        nc = 0
        i = 0
        while i < na:
            lv = act[i]
            if k - age[i] > 2000 or (C[k] > lv and C[k - 1] <= lv):
                if k - age[i] <= 2000:
                    crossed[nc] = lv
                    nc += 1
                act[i] = act[na - 1]
                age[i] = age[na - 1]
                na -= 1
            else:
                i += 1
        if nc == 0:
            continue
        if min_lv > 0:
            if nc < min_lv:
                continue
            top = crossed[0]
            for q in range(1, nc):
                if crossed[q] > top:
                    top = crossed[q]
            crossed[0] = top
            nc = 1
        for q in range(nc):
            lv = crossed[q]
            rng = H[k] - L[k]
            if strong and not (rng > 0 and C[k] > O[k] and (C[k] - L[k]) >= 0.667 * rng and (C[k] - O[k]) >= 0.5 * rng):
                continue
            BE, Sd, Hk = C[k], L[k], H[k]
            if BE <= Sd:
                continue
            f, fp, Ed = -1, np.nan, 0.0
            if mode == 1 or mode == 4:
                Ed = BE if mode == 1 else lv
                if Ed <= Sd:
                    continue
                for j in range(k + 1, min(n, k + 1 + exp)):
                    fp = try_fill(d, 0, d * Ed, o[j], h[j], l[j], spr[j])
                    if not np.isnan(fp):
                        f = j
                        break
            else:
                r = -1
                for j in range(k + 1, min(n, k + 1 + exp)):
                    if C[j] <= Sd:
                        break
                    if L[j] <= BE:
                        if mode == 5 or C[j] > BE:
                            r = j
                            break
                if r < 0 or r + 1 >= n:
                    continue
                if mode == 3:
                    f = r + 1
                    fp = try_fill(d, 2, 0.0, o[f], h[f], l[f], spr[f])
                    Ed = d * fp  # chart entry = the fill
                else:
                    Ed = H[r] if mode == 2 else Hk
                    if Ed <= Sd:
                        continue
                    for j in range(r + 1, min(n, r + 1 + exp)):
                        fp = try_fill(d, 1, d * Ed, o[j], h[j], l[j], spr[j])
                        if not np.isnan(fp):
                            f = j
                            break
                        if L[j] <= Sd:
                            break
            if f < 0 or np.isnan(fp):
                continue
            risk = Ed - Sd
            if risk <= 0:
                continue
            S = d * Sd
            if d * (fp - S) <= 0:
                continue
            bep = d * (Ed + be_r * risk) if be_r > 0 else np.nan
            p, x, _ = manage(t, o, h, l, c, spr, d, f, fp, S, d * (Ed + rr1 * risk), d * (Ed + rr2 * risk),
                             frac, hold, bep)
            out_sig[cnt] = k
            out_fill[cnt] = f
            out_r[cnt] = (p - comm) / risk
            if len(out_x) > 1:
                out_x[cnt] = x
            cnt += 1
    return cnt


# ------------------------------------------------------------------------------------------
# MicroMAP
# ------------------------------------------------------------------------------------------
@njit(cache=True)
def stop_break(t, o, h, l, c, spr, d, H, L, s0, wait, Sfloor):
    """First candle from s0 that breaks the previous candle's high (det space) -> (bar, Ed, fill).
    Cancelled if price trades through Sfloor first."""
    n = len(t)
    for i in range(s0, min(n, s0 + wait)):
        Ed = H[i - 1]
        fp = try_fill(d, 1, d * Ed, o[i], h[i], l[i], spr[i])
        if not np.isnan(fp):
            return i, Ed, fp
        if L[i] <= Sfloor:
            return -1, 0.0, np.nan
    return -1, 0.0, np.nan


@njit(cache=True)
def micromap(t, o, h, l, c, spr, d, O, H, L, C, atr, ns, m, mc_min, rr1, rr2, frac, hold, rand_mask, comm,
             out_sig, out_fill, out_att, out_r):
    n = len(t)
    cnt = 0
    busy = -1
    for k in range(n - 2):
        if k <= busy:
            continue
        if rand_mask[0] >= 0:
            if not rand_mask[k] or k < ns + 2:
                continue
        elif not spike_end(O, H, L, C, atr, k, ns, m, False):
            continue
        s0 = k - ns + 1
        spike_low = L[s0]
        avg_rng = 0.0
        for i in range(s0, k + 1):
            avg_rng += H[i] - L[i]
        avg_rng /= ns
        # micro-channel: lower highs, small candles
        mc = 0
        j = k + 1
        trig = -1
        while j < n and mc <= 10:
            if H[j] >= H[j - 1]:
                trig = j
                break
            if L[j] <= spike_low or H[j] - L[j] >= avg_rng:
                break
            mc += 1
            j += 1
        if trig < 0 or mc < mc_min:
            continue
        # entry 1 at the break of the last micro-channel candle
        Ed, Sd = H[trig - 1], L[trig - 1]
        fp = try_fill(d, 1, d * Ed, o[trig], h[trig], l[trig], spr[trig])
        f = trig
        att = 1
        last_x = k
        while att <= 3:
            risk = Ed - Sd
            if np.isnan(fp) or risk <= 0 or d * (fp - d * Sd) <= 0:
                break
            p, x, oc = manage(t, o, h, l, c, spr, d, f, fp, d * Sd, d * (Ed + rr1 * risk), d * (Ed + rr2 * risk),
                              frac, hold, np.nan)
            out_sig[cnt] = k
            out_fill[cnt] = f
            out_att[cnt] = att
            out_r[cnt] = (p - comm) / risk
            cnt += 1
            last_x = x
            if oc != 1 or att == 3:
                break
            # wait one new candle, then trade the break of the latest candle's high
            att += 1
            f, Ed, fp = stop_break(t, o, h, l, c, spr, d, H, L, x + 2, 10, -1e18)
            if f < 0:
                break
            if att == 2:
                Sd = L[x]
                for i in range(x, f):
                    if L[i] < Sd:
                        Sd = L[i]
            else:
                Sd = L[f - 1]
        busy = last_x
    return cnt


# ------------------------------------------------------------------------------------------
def resample(base, tf):
    if tf == "M5":
        return base.copy()
    g = base.set_index("time").resample(f"{TFS[tf]}min", label="left", closed="left")
    df = g.agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    return df.reset_index()


def atr14(df):
    pc = df.close.shift(1).fillna(df.close)
    tr = np.maximum(df.high - df.low, np.maximum((df.high - pc).abs(), (df.low - pc).abs()))
    return tr.rolling(14).mean().values


def det_arrays(df, d):
    o, h, l, c = (df[k].values.astype(np.float64) for k in ("open", "high", "low", "close"))
    return (o, h, l, c) if d == 1 else (-o, -l, -h, -c)


def levels(df, d, kind, p=5, control=False, rng=None):
    """New levels (det space) known at each bar: fractal swing highs (lows for sells),
    previous-day high (low), or random horizontal lines (control)."""
    O, H, L, C = det_arrays(df, d)
    n = len(df)
    lv = np.full(n, np.nan)
    if control:
        idx = np.flatnonzero(rng.random(n) < kind)          # kind = density
        for k in idx:
            if k > 50:
                lv[k] = C[k - rng.integers(1, 50)]
        return lv
    if kind == "fractal":
        hs = pd.Series(H)
        is_f = (hs == hs.rolling(2 * p + 1, center=True).max()).values
        for i in np.flatnonzero(is_f):
            if i + p < n:
                lv[i + p] = H[i]
    else:  # previous day's high (low)
        day = df.time.dt.floor("D").values
        hi = pd.Series(H).groupby(day).max()
        first = np.flatnonzero(np.r_[True, day[1:] != day[:-1]])
        prev = hi.shift(1).reindex(day[first]).values
        lv[first] = prev
    return lv


def ctx_filters(df):
    hr = df.time.dt.hour.values + df.time.dt.minute.values / 60.0
    window = ((hr >= 10) & (hr < 13)) | ((hr >= 15.5) & (hr < 18))
    return window, hr


def trend(df, tf):
    k = {"M5": 12, "M15": 4, "H1": 4}[tf]
    ema = df.close.ewm(span=50 * k, adjust=False).mean().values
    return np.sign(df.close.values - ema)


def run_tf(base, tf, out_rows, rng):
    df = resample(base, tf)
    df = df[df.time >= "2011-09-01"].reset_index(drop=True)
    t = (df.time.values.astype("datetime64[m]").astype(np.int64))
    o, h, l, c = (df[k].values.astype(np.float64) for k in ("open", "high", "low", "close"))
    atr = atr14(df)
    window, _ = ctx_filters(df)
    tr = trend(df, tf)
    ism_bar = df.time.values < np.datetime64(IS_END)
    yrs_is = (IS_END - pd.Timestamp("2012-01-01")).days / 365.25
    yrs_oos = (df.time.iloc[-1] - IS_END).days / 365.25
    start_ok = df.time.values >= np.datetime64("2012-01-01")
    nmax = len(df)
    costs = {"net": (spread_model(c), 0.07), "gross": (np.zeros(len(c)), 0.0)}

    def collect(parts):
        # parts: list of (d, sig, fill, {name: r})
        sig = np.concatenate([p[1] for p in parts])
        fill = np.concatenate([p[2] for p in parts])
        dd = np.concatenate([np.full(len(p[1]), p[0]) for p in parts])
        names = parts[0][3].keys()
        rs = {k: np.concatenate([p[3][k] for p in parts]) for k in names}
        return sig, fill, dd, rs

    def emit_dirs(strategy, params, parts, control, cost, mg):
        sig, fill, dd, rs = collect(parts)
        # emit once with per-trade direction for the trend filter
        keep = start_ok[sig]
        for filt in ("none", "window", "trend", "window+trend"):
            m = keep.copy()
            if "window" in filt:
                m &= window[fill]
            if "trend" in filt:
                m &= tr[sig] == dd
            for rname, r in rs.items():
                mi = metrics(r[m & ism_bar[sig]])
                mo = metrics(r[m & ~ism_bar[sig]])
                out_rows.append(dict(strategy=strategy, tf=tf, **params, entry=rname, mgmt=mg, filter=filt,
                                     control=control, cost=cost,
                                     is_n=mi["n"], is_perY=round(mi["n"] / yrs_is, 1), is_win=mi["win"],
                                     is_avgR=mi["avgR"], is_t=mi["t"],
                                     oos_n=mo["n"], oos_perY=round(mo["n"] / yrs_oos, 1), oos_win=mo["win"],
                                     oos_avgR=mo["avgR"], oos_t=mo["t"], oos_maxDD=mo["maxDD"]))

    buf = lambda dt=np.int64: np.zeros(nmax, dtype=dt)  # noqa: E731

    # ---------------- SP2L ----------------
    for ns, m in itertools.product((2, 3), (1.0, 2.0)):
        for control in (False, True):
            for cost, (spr, cm) in costs.items():
                for mg, (rr1, rr2, frac) in MGMT.items():
                    parts = []
                    for d in (1, -1):
                        O, H, L, C = det_arrays(df, d)
                        if control:
                            mask = rng_masks[(tf, "sp2l", ns, m, d)]
                        else:
                            mask = np.full(1, -1, dtype=np.int64)
                        s, f, r1, rc = buf(), buf(), buf(np.float64), buf(np.float64)
                        k = sp2l(t, o, h, l, c, spr, d, O, H, L, C, atr, ns, m, 12, rr1, rr2, frac, HOLD_MIN,
                                 mask, cm, s, f, r1, rc)
                        parts.append((d, s[:k], f[:k], {"main": r1[:k], "main+50%": rc[:k]}))
                    emit_dirs("SP2L", dict(ns=ns, m=m, p="", lvl=""), parts, control, cost, mg)
        print(f"{tf} SP2L ns={ns} m={m} done", flush=True)

    # ---------------- MicroMAP ----------------
    for ns, m, mc in itertools.product((2, 3), (1.0, 2.0), (2, 3)):
        for control in (False, True):
            for cost, (spr, cm) in costs.items():
                for mg, (rr1, rr2, frac) in MGMT.items():
                    parts = []
                    for d in (1, -1):
                        O, H, L, C = det_arrays(df, d)
                        mask = rng_masks[(tf, "mm", ns, m, d)] if control else np.full(1, -1, dtype=np.int64)
                        s, f, a, r = buf(), buf(), buf(), buf(np.float64)
                        k = micromap(t, o, h, l, c, spr, d, O, H, L, C, atr, ns, m, mc, rr1, rr2, frac, HOLD_MIN,
                                     mask, cm, s, f, a, r)
                        a, r = a[:k], r[:k]
                        parts.append((d, s[:k], f[:k], {"entries 1-3": r,
                                                        "entry 1 only": np.where(a == 1, r, np.nan)}))
                    emit_dirs("MicroMAP", dict(ns=ns, m=m, p=mc, lvl=""), parts, control, cost, mg)
        print(f"{tf} MicroMAP ns={ns} m={m} mc={mc} done", flush=True)

    # ---------------- PRO BTB ----------------
    for lvl, strong in itertools.product(("fractal", "prevday"), (0, 1)):
        for control in (False, True):
            lv = {}
            for d in (1, -1):
                real = levels(df, d, lvl)
                if control:
                    dens_ = np.isfinite(real).mean()
                    lv[d] = levels(df, d, dens_, control=True, rng=np.random.default_rng(7 + d))
                else:
                    lv[d] = real
            for cost, (spr, cm) in costs.items():
                for mg, (rr1, rr2, frac) in MGMT.items():
                    for mode in (1, 2, 3, 4, 5):
                        parts = []
                        for d in (1, -1):
                            O, H, L, C = det_arrays(df, d)
                            s, f, r = buf(), buf(), buf(np.float64)
                            k = btb(t, o, h, l, c, spr, d, O, H, L, C, np.zeros(1, dtype=np.int64), lv[d], mode,
                                    strong, 100, rr1, rr2, frac, HOLD_MIN, cm, s, f, r)
                            parts.append((d, s[:k], f[:k], {f"E{mode}": r[:k]}))
                        emit_dirs("ProBTB", dict(ns=strong, m="", p=5, lvl=lvl), parts, control, cost, mg)
        print(f"{tf} BTB {lvl} strong={strong} done", flush=True)
    return df



def trade_list(base, tf, strategy, ns=3, m=1.0, mc=2, lvl="prevday", strong=1, mode=3, entry="main",
               mgmt="RR2", cost_mult=1.0, gross=False, be_r=0.0, min_lv=0):
    """Trade-level results (time, dir, R) for one configuration (used by poursamadi_check.py)."""
    df = resample(base, tf)
    df = df[df.time >= "2011-09-01"].reset_index(drop=True)
    t = df.time.values.astype("datetime64[m]").astype(np.int64)
    o, h, l, c = (df[k].values.astype(np.float64) for k in ("open", "high", "low", "close"))
    atr = atr14(df)
    spr = np.zeros(len(c)) if gross else spread_model(c) * cost_mult
    cm = 0.0 if gross else 0.07 * cost_mult
    rr1, rr2, frac = MGMT[mgmt]
    window, _ = ctx_filters(df)
    tr = trend(df, tf)
    n = len(df)
    out = []
    for d in (1, -1):
        O, H, L, C = det_arrays(df, d)
        s, f = np.zeros(n, dtype=np.int64), np.zeros(n, dtype=np.int64)
        r, r2, xo = np.zeros(n), np.zeros(n), np.zeros(n, dtype=np.int64)
        none = np.full(1, -1, dtype=np.int64)
        if strategy == "SP2L":
            k = sp2l(t, o, h, l, c, spr, d, O, H, L, C, atr, ns, m, 12, rr1, rr2, frac, HOLD_MIN, none, cm, s, f, r, r2,
                     be_r, xo)
            rr = r2[:k] if entry == "main+50%" else r[:k]
        elif strategy == "MicroMAP":
            a = np.zeros(n, dtype=np.int64)
            k = micromap(t, o, h, l, c, spr, d, O, H, L, C, atr, ns, m, mc, rr1, rr2, frac, HOLD_MIN, none, cm, s, f, a, r)
            rr = r[:k]
        else:
            k = btb(t, o, h, l, c, spr, d, O, H, L, C, np.zeros(1, dtype=np.int64), levels(df, d, lvl), mode, strong,
                    100, rr1, rr2, frac, HOLD_MIN, cm, s, f, r, be_r, xo, min_lv)
            rr = r[:k]
        out.append(pd.DataFrame({"sig": s[:k], "fill": f[:k], "exit": xo[:k], "dir": d, "R": rr}))
    tl = pd.concat(out, ignore_index=True)
    tl["time"] = df.time.values[tl.fill.values]
    tl["exit_time"] = df.time.values[tl.exit.values] + np.timedelta64(TFS[tf], "m")
    tl["window"] = window[tl.fill.values]
    tl["trend_ok"] = tr[tl.sig.values] == tl.dir.values
    return tl[tl.time >= "2012-01-01"].sort_values("time").reset_index(drop=True)

rng_masks = {}


def build_masks(base, rng):
    """Random-candle control: same number of setups as the real spike rule, random bars."""
    for tf in TFS:
        df = resample(base, tf)
        df = df[df.time >= "2011-09-01"].reset_index(drop=True)
        atr = atr14(df)
        for d in (1, -1):
            O, H, L, C = det_arrays(df, d)
            for ns, m in itertools.product((2, 3), (1.0, 2.0)):
                for kind, gap in (("sp2l", True), ("mm", False)):
                    cntr = count_spikes(O, H, L, C, atr, ns, m, gap)
                    mask = (rng.random(len(df)) < cntr / len(df)).astype(np.int64)
                    rng_masks[(tf, kind, ns, m, d)] = mask


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="results")
    ap.add_argument("--tfs", default="M5,M15,H1")
    a = ap.parse_args()
    base = load_bars(a.data)
    base = base[(base.time >= "2011-06-01") & (base.time < "2025-03-21")].reset_index(drop=True)
    rng = np.random.default_rng(1)
    build_masks(base, rng)
    rows = []
    for tf in a.tfs.split(","):
        run_tf(base, tf, rows, rng)
        res = pd.DataFrame(rows)
        os.makedirs(a.out, exist_ok=True)
        res.round(4).to_csv(os.path.join(a.out, "poursamadi_grid.csv"), index=False)


if __name__ == "__main__":
    main()
