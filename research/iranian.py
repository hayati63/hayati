"""
Backtest of the methods taught by well-known Iranian teachers whose rules are published in
writing (mechanical versions; same data, costs and IS/OOS split as the other studies).

RTM - Quasimodo (QM)  (RTM school, e.g. Parisa Nasr, Morteza Marvahzadeh)
  * alternating swing points (fractal, 3 candles each side, confirmed 3 candles later)
  * bullish QM: low L1, high H1, lower low L2 (liquidity grab), then a candle closes above H1
    (break of structure) -> buy limit at L1 (the "left shoulder"), SL below L2, TP 2R / 3R
CRT - Candle Range Theory (ICT-derived, taught e.g. by Parisa Nasr)
  * a higher-timeframe candle trades above the previous candle's high and closes back inside
    its range -> sell at the next open, SL above the sweep high, TP the previous candle's low
    (or 2R); mirrored for buys.  H4 "key" candles (01:00, 05:00, 09:00 New York) or all
    H4 candles, and daily candles.
1-2-3 pattern (Ali Taghikhan's main pattern)
  * after lower highs: point 1 = swing low, point 2 = the next swing high, point 3 = a higher
    swing low -> buy stop at point 2, SL below point 3, TP the 1->2 distance projected from
    point 2 (or 2R); mirrored for sells.  H1 / H4 / D1.
CTS - Comprehensive Trading Strategy (Hooman Meghrazi), mechanical approximation
  * PRZ = at least 2 of these within 0.25 ATR of the candle's low (support) / high
    (resistance): weekly pivot S2/S3 (R2/R3), daily SMA 50, Fibonacci 50% / 61.8% of the last
    swing, one of the last 3 swing lows (highs)
  * "energy": a bullish (bearish) engulfing candle on H4 at the PRZ, optional RSI(14)
    divergence, optional daily-trend agreement; entry at the next open, SL beyond the candle,
    TP 3R (CTS's 1:3 rule)
Fills and exits are simulated on M15 candles (pessimistic when a candle reaches both SL and
TP).  Control for every setup: the opposite trade (market at the next M15 open, same risk
distance, mirrored SL/TP) - with no directional edge both sides lose about the costs.
"""
import argparse
import itertools
import os

import numpy as np
import pandas as pd
from numba import njit

from poursamadi import atr14, manage, resample, try_fill
from run_study import IS_END, metrics
from vgap_engine import load_bars, spread_model

HOLD = {"M15": 1440, "H1": 1440, "H4": 3 * 1440, "D1": 10 * 1440}


@njit(cache=True)
def run_orders(t, o, h, l, c, spr, d, et, start, expire, E, S, T, hold, comm, flip,
               out_fill, out_r):
    """et 0 limit, 1 stop, 2 market at start.  Invalid once price trades through S unfilled.
    flip: also simulate the opposite trade at the next open (control) -> out_r[:, 1]."""
    n = len(t)
    for k in range(len(d)):
        out_fill[k] = -1
        out_r[k, 0] = np.nan
        out_r[k, 1] = np.nan
        dk = d[k]
        for j in range(start[k], min(n, expire[k])):
            fp = try_fill(dk, et[k], E[k], o[j], h[j], l[j], spr[j])
            if not np.isnan(fp):
                risk = abs(E[k] - S[k])
                if dk * (fp - S[k]) <= 0 or risk <= 0:
                    break
                p, x, _ = manage(t, o, h, l, c, spr, dk, j, fp, S[k], T[k], T[k], 1.0, hold, np.nan)
                out_fill[k] = j
                out_r[k, 0] = (p - comm) / risk
                if flip and j + 1 < n:
                    g = j + 1
                    dd = -dk
                    fq = o[g] + spr[g] if dd == 1 else o[g]
                    rr = abs(T[k] - E[k]) / risk
                    p2, _, _ = manage(t, o, h, l, c, spr, dd, g, fq, fq - dd * risk, fq + dd * rr * risk,
                                      fq + dd * rr * risk, 1.0, hold, np.nan)
                    out_r[k, 1] = (p2 - comm) / risk
                break
            if (dk == 1 and l[j] <= S[k]) or (dk == -1 and h[j] >= S[k]):
                break
    return 0


def swings(df, p=3):
    """Alternating swing points: list of (bar, price, +1 high / -1 low, confirm bar)."""
    H, L = df.high.values, df.low.values
    hs = pd.Series(H).rolling(2 * p + 1, center=True).max().values
    ls = pd.Series(L).rolling(2 * p + 1, center=True).min().values
    cand = []
    for i in range(p, len(df) - p):
        if H[i] == hs[i]:
            cand.append((i, H[i], 1))
        if L[i] == ls[i]:
            cand.append((i, L[i], -1))
    out = []
    for i, px, ty in cand:
        if out and out[-1][2] == ty:
            if (ty == 1 and px > out[-1][1]) or (ty == -1 and px < out[-1][1]):
                out[-1] = (i, px, ty, i + p)
            continue
        out.append((i, px, ty, i + p))
    return out


class Book:
    """Collects orders (on the M15 execution grid) for one strategy configuration."""

    def __init__(self):
        self.rows = []

    def add(self, d, et, start, expire, E, S, T, sig_time):
        if d * (E - S) <= 0 or d * (T - E) <= 0:
            return
        self.rows.append((d, et, start, expire, E, S, T, sig_time))

    def run(self, ex, hold, cost):
        if not self.rows:
            return None
        a = np.array([r[:7] for r in self.rows], dtype=np.float64)
        spr, cm = cost
        n = len(a)
        fill = np.zeros(n, dtype=np.int64)
        r = np.zeros((n, 2))
        run_orders(ex["t"], ex["o"], ex["h"], ex["l"], ex["c"], spr, a[:, 0].astype(np.int64), a[:, 1].astype(np.int64),
                   a[:, 2].astype(np.int64), a[:, 3].astype(np.int64), a[:, 4], a[:, 5], a[:, 6], hold, cm, True, fill, r)
        ok = fill >= 0
        return ex["time"][fill[ok]], r[ok, 0], r[ok, 1]


def to_exec(tf_df, ex_time, k):
    """M15 index of the first execution candle after tf candle k has closed."""
    close_t = tf_df.time.values[k] + np.timedelta64(int(tf_df.attrs["tfmin"]), "m")
    return int(np.searchsorted(ex_time, close_t))


def qm_setups(df, ex_time, atr, rr, exp_bars):
    sw = swings(df)
    C = df.close.values
    H, L = df.high.values, df.low.values
    bk = Book()
    tfm = int(df.attrs["tfmin"])
    for a in range(len(sw) - 2):
        s1, s2, s3 = sw[a], sw[a + 1], sw[a + 2]
        d = 1 if s1[2] == -1 else -1                     # bullish QM starts with a low
        # bullish: L1, H1, L2 < L1 ; bearish: H1, L1, H2 > H1
        if d * (s3[1] - s1[1]) >= 0:
            continue
        brk = s2[1]
        j0 = s3[3]
        nxt = sw[a + 3][3] if a + 3 < len(sw) else len(df)
        for j in range(j0, min(len(df), j0 + exp_bars, nxt + 1)):
            if d * (C[j] - brk) > 0:
                E, S = s1[1], s3[1]
                T = E + d * rr * abs(E - S)
                st = to_exec(df, ex_time, j)
                bk.add(d, 0, st, st + exp_bars * tfm // 15, E, S, T, df.time.values[j])
                break
            if (d == 1 and L[j] < s3[1]) or (d == -1 and H[j] > s3[1]):
                break
    return bk


def onetwothree_setups(df, ex_time, rr_mode, exp_bars):
    sw = swings(df)
    bk = Book()
    tfm = int(df.attrs["tfmin"])
    for a in range(len(sw) - 3):
        s0, p1, p2, p3 = sw[a], sw[a + 1], sw[a + 2], sw[a + 3]
        d = 1 if p1[2] == -1 else -1                     # bullish: p1 low, p2 high, p3 higher low
        if d * (p3[1] - p1[1]) <= 0:                     # point 3 must hold above point 1
            continue
        if d * (s0[1] - p2[1]) <= 0:                     # prior trend: lower high before point 1
            continue
        E, S = p2[1], p3[1]
        T = E + d * abs(p2[1] - p1[1]) if rr_mode == "measured" else E + d * 2.0 * abs(E - S)
        st = to_exec(df, ex_time, p3[3])
        bk.add(d, 1, st, st + exp_bars * tfm // 15, E, S, T, df.time.values[p3[3]])
    return bk


def crt_setups(df, ex_time, key_only, tp_mode):
    O, H, L, C = (df[k].values for k in ("open", "high", "low", "close"))
    hrs = df.time.dt.hour.values
    bk = Book()
    for k in range(1, len(df) - 1):
        if key_only and hrs[k] not in (8, 12, 16):
            continue
        for d in (1, -1):
            # sell CRT: sweep above the previous high, close back inside; buy: mirrored
            if d == -1 and not (H[k] > H[k - 1] and L[k - 1] < C[k] < H[k - 1]):
                continue
            if d == 1 and not (L[k] < L[k - 1] and L[k - 1] < C[k] < H[k - 1]):
                continue
            S = H[k] if d == -1 else L[k]
            st = to_exec(df, ex_time, k)
            E = C[k]
            T = (L[k - 1] if d == -1 else H[k - 1]) if tp_mode == "range" else E + d * 2.0 * abs(E - S)
            bk.add(d, 2, st, st + 1, E, S, T, df.time.values[k])
    return bk


def cts_setups(h4, d1, ex_time, need_div, need_trend):
    O, H, L, C = (h4[k].values for k in ("open", "high", "low", "close"))
    atr = atr14(h4)
    n = len(h4)
    # weekly pivots from the previous server week
    wk = d1.set_index("time").resample("W-FRI").agg({"high": "max", "low": "min", "close": "last"}).dropna()
    P = (wk.high + wk.low + wk.close) / 3
    piv = pd.DataFrame({"R2": P + (wk.high - wk.low), "S2": P - (wk.high - wk.low),
                        "R3": wk.high + 2 * (P - wk.low), "S3": wk.low - 2 * (wk.high - P)}).shift(1)
    piv.index = piv.index + pd.Timedelta(days=1)
    pv = piv.reindex(h4.time, method="ffill").values
    sma50 = d1.close.rolling(50).mean().shift(1)
    sma = pd.Series(sma50.values, index=d1.time).reindex(h4.time.dt.floor("D"), method="ffill").values
    d1c = pd.Series(d1.close.shift(1).values, index=d1.time).reindex(h4.time.dt.floor("D"), method="ffill").values
    delta = np.diff(C, prepend=C[0])
    up = pd.Series(np.maximum(delta, 0)).ewm(alpha=1 / 14, adjust=False).mean()
    dn = pd.Series(np.maximum(-delta, 0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = (100 - 100 / (1 + up / dn.replace(0, np.nan))).values
    sw = swings(h4)
    conf = np.array([s[3] for s in sw])
    bk = Book()
    for k in range(60, n - 1):
        a = atr[k]
        if not (a > 0):
            continue
        known = [s for s in sw[max(0, np.searchsorted(conf, k, side="right") - 8):np.searchsorted(conf, k, side="right")]]
        if len(known) < 4:
            continue
        lows = [s for s in known if s[2] == -1][-3:]
        highs = [s for s in known if s[2] == 1][-3:]
        last_two = known[-2:]
        lo_, hi_ = min(x[1] for x in last_two), max(x[1] for x in last_two)
        fibs = [lo_ + 0.5 * (hi_ - lo_), lo_ + 0.382 * (hi_ - lo_), lo_ + 0.618 * (hi_ - lo_)]
        for d in (1, -1):
            px = L[k] if d == 1 else H[k]
            cats = 0
            pv_lv = (pv[k, 1], pv[k, 3]) if d == 1 else (pv[k, 0], pv[k, 2])
            if any(abs(px - x) <= 0.25 * a for x in pv_lv if np.isfinite(x)):
                cats += 1
            if np.isfinite(sma[k]) and abs(px - sma[k]) <= 0.25 * a:
                cats += 1
            if any(abs(px - x) <= 0.25 * a for x in fibs):
                cats += 1
            sr = lows if d == 1 else highs
            if any(abs(px - s[1]) <= 0.25 * a for s in sr):
                cats += 1
            if cats < 2:
                continue
            # engulfing reversal candle
            if d == 1 and not (C[k] > O[k] and C[k - 1] < O[k - 1] and C[k] >= O[k - 1] and O[k] <= C[k - 1]):
                continue
            if d == -1 and not (C[k] < O[k] and C[k - 1] > O[k - 1] and C[k] <= O[k - 1] and O[k] >= C[k - 1]):
                continue
            if need_div:
                # regular divergence: price at / beyond the extreme of the last 30 candles, RSI not
                w0 = max(0, k - 30)
                j = w0 + (int(np.argmin(L[w0:k - 2])) if d == 1 else int(np.argmax(H[w0:k - 2])))
                if d == 1 and not (L[k] <= L[j] + 0.25 * a and rsi[k] > rsi[j]):
                    continue
                if d == -1 and not (H[k] >= H[j] - 0.25 * a and rsi[k] < rsi[j]):
                    continue
            if need_trend and not (np.isfinite(sma[k]) and d * (d1c[k] - sma[k]) > 0):
                continue
            S = L[k] - 0.1 * a if d == 1 else H[k] + 0.1 * a
            E = C[k]
            st = to_exec(h4, ex_time, k)
            bk.add(d, 2, st, st + 1, E, S, E + d * 3.0 * abs(E - S), h4.time.values[k])
    return bk


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="results")
    a = ap.parse_args()
    base = load_bars(a.data)
    base = base[(base.time >= "2011-06-01") & (base.time < "2025-03-21")].reset_index(drop=True)
    years = ((IS_END - pd.Timestamp("2012-01-01")).days / 365.25, (base.time.iloc[-1] - IS_END).days / 365.25)
    m15 = resample(base, "M15")
    ex = dict(time=m15.time.values, t=m15.time.values.astype("datetime64[m]").astype(np.int64),
              o=m15.open.values, h=m15.high.values, l=m15.low.values, c=m15.close.values)
    costs = {"net": (spread_model(ex["c"]), 0.07), "gross": (np.zeros(len(m15)), 0.0)}
    frames = {}
    for tf, mins in (("M15", 15), ("H1", 60), ("H4", 240)):
        frames[tf] = resample(base, tf) if tf != "H4" else \
            base.set_index("time").resample("240min").agg({"open": "first", "high": "max", "low": "min",
                                                           "close": "last", "volume": "sum"}).dropna().reset_index()
        frames[tf].attrs["tfmin"] = mins
    d1 = base.set_index("time").resample("1D").agg({"open": "first", "high": "max", "low": "min",
                                                    "close": "last", "volume": "sum"}).dropna().reset_index()
    d1.attrs["tfmin"] = 1440
    frames["D1"] = d1
    rows = []

    def record(strategy, tf, params, bk):
        for cost, cst in costs.items():
            res = bk.run(ex, HOLD[tf], cst)
            if res is None:
                continue
            tt, r, rf = res
            keep = tt >= np.datetime64("2012-01-01")
            m_is = tt < np.datetime64(IS_END)
            for ctl, rr_ in ((False, r), (True, rf)):
                mi, mo = metrics(rr_[keep & m_is]), metrics(rr_[keep & ~m_is])
                rows.append(dict(strategy=strategy, tf=tf, params=params, control=ctl, cost=cost,
                                 is_n=mi["n"], is_perY=round(mi["n"] / years[0], 1), is_win=mi["win"], is_avgR=mi["avgR"],
                                 is_t=mi["t"], oos_n=mo["n"], oos_perY=round(mo["n"] / years[1], 1), oos_win=mo["win"],
                                 oos_avgR=mo["avgR"], oos_t=mo["t"], oos_maxDD=mo["maxDD"]))

    for tf in ("M15", "H1", "H4"):
        df = frames[tf]
        atr = atr14(df)
        for rr in (2.0, 3.0):
            record("RTM Quasimodo", tf, f"rr={rr}", qm_setups(df, ex["time"], atr, rr, 50))
        print("QM", tf, flush=True)
    for tf in ("H1", "H4", "D1"):
        for mode in ("measured", "2R"):
            record("1-2-3 (Taghikhan)", tf, f"tp={mode}", onetwothree_setups(frames[tf], ex["time"], mode, 50))
        print("123", tf, flush=True)
    for tf, key in (("H4", True), ("H4", False), ("D1", False)):
        for tpm in ("range", "2R"):
            record("CRT", tf, f"key_candles={key} tp={tpm}", crt_setups(frames[tf], ex["time"], key, tpm))
        print("CRT", tf, key, flush=True)
    for div, tr in itertools.product((0, 1), (0, 1)):
        record("CTS (Meghrazi, approx.)", "H4", f"divergence={div} trend={tr}",
               cts_setups(frames["H4"], d1, ex["time"], div, tr))
    print("CTS done", flush=True)
    res = pd.DataFrame(rows)
    os.makedirs(a.out, exist_ok=True)
    res.round(4).to_csv(os.path.join(a.out, "iranian_grid.csv"), index=False)
    pd.set_option("display.width", 250)
    print(res[res.cost == "net"].drop(columns=["cost"]).round(3).to_string(index=False))


if __name__ == "__main__":
    main()
