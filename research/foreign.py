"""
Backtest of four well-known non-Iranian methods on XAUUSD, with the same data, costs, IS/OOS
split and random controls as the Poursamadi study.  Server clock = New York + 7 h.

ICT Silver Bullet (Michael Huddleston)
  * windows 03-04, 10-11 and 14-15 New York time (server 10-11, 17-18, 21-22), M5 chart
  * liquidity reference: the range of the server day so far ("day") or of the 3 hours before
    the window ("prev3h"); a sweep = a candle in the window trading beyond that range
  * after a sweep of the lows, a bullish fair value gap (low[k] > high[k-2], displacement
    candle in between) -> buy limit at the gap (top edge or 50% "CE"); SL below the sweep
    low; TP 2R / 3R or the opposite side of the reference range ("pool"); mirrored for sells
  * the newest valid gap replaces an older unfilled one; orders expire at the window end;
    open trades are closed at the end of the server day.  Optional daily bias (H1 EMA trend).
  * variants: no sweep required (any FVG in the window); control: the same rules in every
    other hour of the day
Al Brooks High 2 / Low 2
  * bull trend: 20-EMA rising (vs 5 candles ago) and the signal candle closing above it
  * pullback legs: a candle with a lower high starts/continues a pullback leg, the first candle
    whose high exceeds the previous high ends the leg (H1, H2...); a new trend high or a
    non-rising EMA resets the count
  * entry: buy stop one tick above the H2 signal candle; SL below the signal candle or below the
    pullback low; TP 1R / 2R; optional "pullback touched the EMA" and "bull signal candle"
  * control: the same stop entry on random candles in the same trend condition
Opening-range breakout (Crabel style)
  * New York open (09:30 NY = 16:30 server; range 15/30/60 min, orders until 12:00 NY),
    London open (03:00 NY = 10:00 server; 30/60 min, until 06:00 NY) and the Asian range
    (server 00:00-10:00, orders until 16:00 server)
  * stop orders above/below the range, first trigger only, SL at the other side (or the middle),
    TP 1R / 2R / end of day; control: ranges starting at random times
Turtle (Richard Dennis) - daily Donchian
  * System 1: 20-day breakout entry, 10-day exit; System 2: 55-day / 20-day; initial stop 2N
    (N = ATR 20); R = result / 2N; reported without and with a 4%/year financing (swap) charge
  * control: random entry days and directions with the same exits
"""
import argparse
import itertools
import os

import numpy as np
import pandas as pd
from numba import njit

from poursamadi import atr14, det_arrays, manage, resample, try_fill
from run_study import IS_END, metrics
from vgap_engine import load_bars, spread_model

NONE = np.full(1, -1, dtype=np.int64)


# ------------------------------------------------------------------------------------------
# ICT Silver Bullet
# ------------------------------------------------------------------------------------------
@njit(cache=True)
def silver_bullet(t, o, h, l, c, spr, ws, we, ref_hi, ref_lo, day_end, bias, need_sweep, entry_ce, tp_mode, rr,
                  comm, out_sig, out_fill, out_dir, out_r):
    """ws/we: first/last+1 bar index of each window; ref_hi/lo: liquidity range; bias per window
    (+1/-1, 0 = none).  tp_mode 0 = rr x risk, 1 = opposite side of the reference range."""
    cnt = 0
    for w in range(len(ws)):
        s0, s1 = ws[w], we[w]
        if s0 < 2 or s1 <= s0:
            continue
        swept_lo, swept_hi = False, False
        lo_ext, hi_ext = 1e18, -1e18
        pend_dir, pE, pS, pT, psig = 0, 0.0, 0.0, 0.0, -1
        done = False
        for k in range(s0, s1):
            # 1) a resting order may fill on this candle
            if pend_dir != 0:
                fp = try_fill(pend_dir, 0, pE, o[k], h[k], l[k], spr[k])
                if not np.isnan(fp):
                    hold = day_end[k] - t[k]
                    p, x, _ = manage(t, o, h, l, c, spr, pend_dir, k, fp, pS, pT, pT, 1.0, hold, np.nan)
                    out_sig[cnt] = psig
                    out_fill[cnt] = k
                    out_dir[cnt] = pend_dir
                    out_r[cnt] = (p - comm) / abs(pE - pS)
                    cnt += 1
                    done = True
                    break
                # invalid once price trades through the stop before filling
                if (pend_dir == 1 and l[k] <= pS) or (pend_dir == -1 and h[k] >= pS):
                    pend_dir = 0
            # 2) sweeps
            if l[k] < ref_lo[w]:
                swept_lo = True
            if h[k] > ref_hi[w]:
                swept_hi = True
            lo_ext = min(lo_ext, l[k])
            hi_ext = max(hi_ext, h[k])
            if k + 1 >= s1:
                break
            # 3) a new fair value gap closing on this candle (needs 3 candles inside the window)
            if k - 2 < s0:
                continue
            rng = h[k - 1] - l[k - 1]
            if rng <= 0:
                continue
            for d in (1, -1):
                if bias[w] != 0 and d != bias[w]:
                    continue
                if need_sweep and not (swept_lo if d == 1 else swept_hi):
                    continue
                if d == 1:
                    if not (l[k] > h[k - 2] and c[k - 1] > o[k - 1] and c[k - 1] - o[k - 1] >= 0.5 * rng):
                        continue
                    E = 0.5 * (l[k] + h[k - 2]) if entry_ce else l[k]
                    S = lo_ext if need_sweep else min(l[k - 2], l[k - 1])
                    T = ref_hi[w] if tp_mode == 1 else E + rr * (E - S)
                else:
                    if not (h[k] < l[k - 2] and c[k - 1] < o[k - 1] and o[k - 1] - c[k - 1] >= 0.5 * rng):
                        continue
                    E = 0.5 * (h[k] + l[k - 2]) if entry_ce else h[k]
                    S = hi_ext if need_sweep else max(h[k - 2], h[k - 1])
                    T = ref_lo[w] if tp_mode == 1 else E - rr * (S - E)
                if d * (E - S) <= 0 or d * (T - E) <= 0:
                    continue
                pend_dir, pE, pS, pT, psig = d, E, S, T, k
        if done:
            continue
    return cnt


def sb_windows(df, starts_server_h, ref_kind, bias_arr):
    """Windows (bar index ranges) for the given server start hours on M5 bars."""
    tm = df.time
    day = tm.dt.floor("D").values
    mins = (tm.dt.hour * 60 + tm.dt.minute).values
    first_of_day = np.flatnonzero(np.r_[True, day[1:] != day[:-1]])
    last_of_day = np.r_[first_of_day[1:], len(df)] - 1
    day_end_bar = np.repeat(last_of_day, np.diff(np.r_[first_of_day, len(df)]))
    t_min = tm.values.astype("datetime64[m]").astype(np.int64)
    day_end = t_min[day_end_bar] + 5
    H, L = df.high.values, df.low.values
    ws, we, rh, rl, bi = [], [], [], [], []
    for f, e in zip(first_of_day, last_of_day):
        m = mins[f:e + 1]
        for sh in starts_server_h:
            a = f + np.searchsorted(m, sh * 60)
            b = f + np.searchsorted(m, sh * 60 + 60)
            if a >= b:
                continue
            if ref_kind == "day":
                r0 = f
            else:
                r0 = f + np.searchsorted(m, sh * 60 - 180) if sh >= 3 else max(0, a - 36)
            if r0 >= a:
                continue
            ws.append(a)
            we.append(b)
            rh.append(H[r0:a].max())
            rl.append(L[r0:a].min())
            bi.append(bias_arr[a - 1])
    return (np.array(ws, dtype=np.int64), np.array(we, dtype=np.int64), np.array(rh), np.array(rl),
            np.array(bi, dtype=np.int64), day_end.astype(np.int64))


# ------------------------------------------------------------------------------------------
# Al Brooks High 2 / Low 2
# ------------------------------------------------------------------------------------------
@njit(cache=True)
def brooks_h2(t, o, h, l, c, spr, d, O, H, L, C, ema, need_count, ema_touch, good_bar, stop_pb, rr, hold,
              rand_mask, comm, out_sig, out_fill, out_r):
    n = len(t)
    cnt = 0
    busy = -1
    hh = -1e18
    in_pb = False
    count = 0
    pb_low = 1e18
    pb_touch = False
    for i in range(6, n - 1):
        # was an order resting for this candle?  (decided on candle i-1 = signal candle)
        s = i - 1
        trend = ema[s] > ema[s - 5] and C[s] > ema[s]
        if rand_mask[0] >= 0:
            setup = trend and rand_mask[s] == 1
        else:
            setup = trend and in_pb and count == need_count - 1
            if setup and ema_touch and not pb_touch:
                setup = False
        if setup and good_bar:
            r = H[s] - L[s]
            setup = r > 0 and C[s] > O[s] and C[s] - L[s] >= 0.5 * r
        if setup and i > busy:
            Ed = H[s]
            Sd = pb_low if (stop_pb and rand_mask[0] < 0) else L[s]
            if Sd < Ed:
                fp = try_fill(d, 1, d * Ed, o[i], h[i], l[i], spr[i])
                if not np.isnan(fp):
                    risk = Ed - Sd
                    p, x, _ = manage(t, o, h, l, c, spr, d, i, fp, d * Sd, d * (Ed + rr * risk), d * (Ed + rr * risk),
                                     1.0, hold, np.nan)
                    out_sig[cnt] = s
                    out_fill[cnt] = i
                    out_r[cnt] = (p - comm) / risk
                    cnt += 1
                    busy = x
        # update the leg count with candle i (a flat / falling EMA ends the bull context)
        if not (ema[i] > ema[i - 5]) or H[i] > hh:
            hh = H[i]
            in_pb = False
            count = 0
            pb_low = 1e18
            pb_touch = False
        elif H[i] < H[i - 1]:
            in_pb = True
            pb_low = min(pb_low, L[i])
            if L[i] <= ema[i]:
                pb_touch = True
        elif in_pb and H[i] > H[i - 1]:
            count += 1
            in_pb = False
        if in_pb:
            pb_low = min(pb_low, L[i])
    return cnt


# ------------------------------------------------------------------------------------------
# Opening-range breakout
# ------------------------------------------------------------------------------------------
@njit(cache=True)
def orb(t, o, h, l, c, spr, rs, re_, cut, day_end, stop_mid, rr, comm, trend, use_trend,
        out_sig, out_fill, out_dir, out_r):
    """rs/re_: opening-range bars [rs, re_); orders active from re_ until cut (exclusive)."""
    cnt = 0
    for w in range(len(rs)):
        a, b, z = rs[w], re_[w], cut[w]
        if b <= a or z <= b:
            continue
        hi = h[a:b].max()
        lo = l[a:b].min()
        if hi <= lo:
            continue
        mid = 0.5 * (hi + lo)
        for k in range(b, z):
            up = h[k] >= hi
            dn = l[k] <= lo
            if up and dn:
                break                      # both sides on one candle: ambiguous, no trade
            if not (up or dn):
                continue
            d = 1 if up else -1
            if use_trend and trend[b - 1] != d:
                break
            E = hi if d == 1 else lo
            S = (mid if stop_mid else lo) if d == 1 else (mid if stop_mid else hi)
            fp = try_fill(d, 1, E, o[k], h[k], l[k], spr[k])
            if np.isnan(fp):
                break
            risk = abs(E - S)
            T = E + d * rr * risk
            p, x, _ = manage(t, o, h, l, c, spr, d, k, fp, S, T, T, 1.0, day_end[k] - t[k], np.nan)
            out_sig[cnt] = b - 1
            out_fill[cnt] = k
            out_dir[cnt] = d
            out_r[cnt] = (p - comm) / risk
            cnt += 1
            break
    return cnt


def orb_ranges(df, start_min, length, cut_min, rng=None):
    tm = df.time
    day = tm.dt.floor("D").values
    mins = (tm.dt.hour * 60 + tm.dt.minute).values
    first = np.flatnonzero(np.r_[True, day[1:] != day[:-1]])
    last = np.r_[first[1:], len(df)] - 1
    t_min = tm.values.astype("datetime64[m]").astype(np.int64)
    day_end = (t_min[np.repeat(last, np.diff(np.r_[first, len(df)]))] + 5).astype(np.int64)
    rs, re_, cut = [], [], []
    for f, e in zip(first, last):
        m = mins[f:e + 1]
        st = start_min if rng is None else int(rng.integers(0, 20 * 12)) * 5
        ct = cut_min if rng is None else st + length + (cut_min - start_min - length)
        a = f + np.searchsorted(m, st)
        b = f + np.searchsorted(m, st + length)
        z = f + np.searchsorted(m, min(ct, 23 * 60 + 55))
        rs.append(a)
        re_.append(b)
        cut.append(z)
    return np.array(rs, dtype=np.int64), np.array(re_, dtype=np.int64), np.array(cut, dtype=np.int64), day_end


# ------------------------------------------------------------------------------------------
# Turtle
# ------------------------------------------------------------------------------------------
@njit(cache=True)
def turtle(o, h, l, c, spr, d, N, n_in, n_out, rand_mask, comm, out_sig, out_fill, out_r, out_days):
    n = len(o)
    cnt = 0
    busy = -1
    for i in range(max(n_in, 21) + 1, n):
        if i <= busy or not (N[i - 1] > 0):
            continue
        if rand_mask[0] >= 0:
            if rand_mask[i] != d:
                continue
            E = o[i]
        else:
            if d == 1:
                E = h[i - n_in:i].max()
                if h[i] < E:
                    continue
            else:
                E = l[i - n_in:i].min()
                if l[i] > E:
                    continue
        if d == 1:
            fp = max(o[i], E) + spr[i]
        else:
            fp = min(o[i], E)
        risk = 2.0 * N[i - 1]
        S0 = fp - d * risk
        x, px = n - 1, c[n - 1]
        for j in range(i, n):
            if j > i:
                ex = l[j - n_out:j].min() if d == 1 else h[j - n_out:j].max()
                stop = max(S0, ex) if d == 1 else min(S0, ex)
            else:
                stop = S0
            if d == 1:
                if j > i and o[j] <= stop:
                    x, px = j, o[j]
                    break
                if l[j] <= stop:
                    x, px = j, stop
                    break
            else:
                if j > i and o[j] + spr[j] >= stop:
                    x, px = j, o[j] + spr[j]
                    break
                if h[j] + spr[j] >= stop:
                    x, px = j, stop
                    break
        out_sig[cnt] = i
        out_fill[cnt] = i
        out_r[cnt] = (d * (px - fp) - comm) / risk
        out_days[cnt] = x - i + 1
        cnt += 1
        busy = x
    return cnt


# ------------------------------------------------------------------------------------------
def emit(rows, base_info, t_fill, r, years):
    m_is = t_fill < np.datetime64(IS_END)
    ok = t_fill >= np.datetime64("2012-01-01")
    mi, mo = metrics(r[ok & m_is]), metrics(r[ok & ~m_is])
    rows.append(dict(**base_info, is_n=mi["n"], is_perY=round(mi["n"] / years[0], 1), is_win=mi["win"],
                     is_avgR=mi["avgR"], is_t=mi["t"], oos_n=mo["n"], oos_perY=round(mo["n"] / years[1], 1),
                     oos_win=mo["win"], oos_avgR=mo["avgR"], oos_t=mo["t"], oos_maxDD=mo["maxDD"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="results")
    ap.add_argument("--only", default="ICT,Brooks,ORB,Turtle")
    a = ap.parse_args()
    base = load_bars(a.data)
    base = base[(base.time >= "2011-06-01") & (base.time < "2025-03-21")].reset_index(drop=True)
    years = ((IS_END - pd.Timestamp("2012-01-01")).days / 365.25, (base.time.iloc[-1] - IS_END).days / 365.25)
    rows = []
    rng = np.random.default_rng(3)
    costs = lambda c: {"net": (spread_model(c), 0.07), "gross": (np.zeros(len(c)), 0.0)}  # noqa: E731
    only = a.only.split(",")

    # ---------------- ICT Silver Bullet (M5) ----------------
    if "ICT" in only:
        df = base[base.time >= "2011-09-01"].reset_index(drop=True)
        t = df.time.values.astype("datetime64[m]").astype(np.int64)
        o, h, l, c = (df[k].values.astype(np.float64) for k in ("open", "high", "low", "close"))
        ema = df.close.ewm(span=600, adjust=False).mean().values      # = H1 EMA 50
        trend_arr = np.sign(c - ema).astype(np.int64)
        n = len(df)
        hour_sets = {"SB windows": (10, 17, 21)}
        for hh in range(24):
            if hh not in (10, 17, 21):
                hour_sets[f"control hour {hh:02d}"] = (hh,)
        for (hname, hrs), ref, bias_kind in itertools.product(hour_sets.items(), ("day", "prev3h"), ("none", "ema")):
            if hname != "SB windows" and (ref == "day" or bias_kind == "ema"):
                continue                   # controls: one reference, no bias
            bias_arr = trend_arr if bias_kind == "ema" else np.zeros(n, dtype=np.int64)
            ws, we, rh, rl, bi, day_end = sb_windows(df, hrs, ref, bias_arr)
            for sweep, ce, (tpm, rr) in itertools.product((1, 0), (0, 1), ((0, 2.0), (0, 3.0), (1, 0.0))):
                if hname != "SB windows" and not (sweep == 1 and ce == 0):
                    continue
                for cost, (spr, cm) in costs(c).items():
                    s, f, dd, r = (np.zeros(n, dtype=np.int64), np.zeros(n, dtype=np.int64),
                                   np.zeros(n, dtype=np.int64), np.zeros(n))
                    k = silver_bullet(t, o, h, l, c, spr, ws, we, rh, rl, day_end, bi, sweep, ce, tpm, rr, cm, s, f, dd, r)
                    emit(rows, dict(strategy="ICT Silver Bullet", tf="M5", variant=hname,
                                    params=f"ref={ref} bias={bias_kind} sweep={sweep} entry={'CE' if ce else 'edge'} "
                                           f"tp={'pool' if tpm else rr}", control=hname != "SB windows", cost=cost),
                         df.time.values[f[:k]], r[:k], years)
        print("ICT done", flush=True)

    # ---------------- Al Brooks H2 / L2 ----------------
    if "Brooks" in only:
        for tf in ("M5", "M15", "H1"):
            df = resample(base, tf)
            df = df[df.time >= "2011-09-01"].reset_index(drop=True)
            t = df.time.values.astype("datetime64[m]").astype(np.int64)
            o, h, l, c = (df[k].values.astype(np.float64) for k in ("open", "high", "low", "close"))
            n = len(df)
            ema = df.close.ewm(span=20, adjust=False).mean().values
            for control in (False, True):
                for cnt_, touch, good, spb, rr in itertools.product((2, 1), (0, 1), (0, 1), (0, 1), (1.0, 2.0)):
                    if control and (cnt_ != 2 or touch or spb):
                        continue
                    for cost, (spr, cm) in costs(c).items():
                        sigs, fills, rs_ = [], [], []
                        for d in (1, -1):
                            O, H, L, C = det_arrays(df, d)
                            em = d * ema
                            mask = (rng.random(n) < 0.03).astype(np.int64) if control else NONE
                            s, f, r = np.zeros(n, dtype=np.int64), np.zeros(n, dtype=np.int64), np.zeros(n)
                            k = brooks_h2(t, o, h, l, c, spr, d, O, H, L, C, em, cnt_, touch, good, spb, rr, 1440,
                                          mask, cm, s, f, r)
                            sigs.append(s[:k])
                            fills.append(f[:k])
                            rs_.append(r[:k])
                        f = np.concatenate(fills)
                        emit(rows, dict(strategy="Al Brooks", tf=tf, variant=f"H{cnt_}/L{cnt_}" if not control else "random candle",
                                        params=f"ema_touch={touch} good_bar={good} stop={'pullback' if spb else 'signal bar'} rr={rr}",
                                        control=control, cost=cost), df.time.values[f], np.concatenate(rs_), years)
            print(f"Brooks {tf} done", flush=True)

    # ---------------- Opening-range breakout (M5) ----------------
    if "ORB" in only:
        df = base[base.time >= "2011-09-01"].reset_index(drop=True)
        t = df.time.values.astype("datetime64[m]").astype(np.int64)
        o, h, l, c = (df[k].values.astype(np.float64) for k in ("open", "high", "low", "close"))
        n = len(df)
        trend_arr = np.sign(c - df.close.ewm(span=600, adjust=False).mean().values).astype(np.int64)
        sessions = {"NY open": (16 * 60 + 30, (15, 30, 60), 19 * 60), "London open": (10 * 60, (30, 60), 13 * 60),
                    "Asian range": (0, (600,), 16 * 60)}
        for (sname, (st, lens, cutm)), control in itertools.product(sessions.items(), (False, True)):
            for ln in lens:
                rs, re_, cut, day_end = orb_ranges(df, st, ln, cutm, np.random.default_rng(11) if control else None)
                for smid, rr, ut in itertools.product((0, 1), (1.0, 2.0, 50.0), (0, 1)):
                    for cost, (spr, cm) in costs(c).items():
                        s, f, dd, r = (np.zeros(n, dtype=np.int64), np.zeros(n, dtype=np.int64),
                                       np.zeros(n, dtype=np.int64), np.zeros(n))
                        k = orb(t, o, h, l, c, spr, rs, re_, cut, day_end, smid, rr, cm, trend_arr, ut, s, f, dd, r)
                        emit(rows, dict(strategy="Opening range breakout", tf="M5",
                                        variant=sname + (" (random start)" if control else ""),
                                        params=f"range={ln}m stop={'mid' if smid else 'other side'} "
                                               f"tp={'EOD' if rr > 10 else rr} trend={ut}", control=control, cost=cost),
                             df.time.values[f[:k]], r[:k], years)
        print("ORB done", flush=True)

    # ---------------- Turtle (D1) ----------------
    if "Turtle" in only:
        g = base.set_index("time").resample("1D")
        df = g.agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna().reset_index()
        df = df[df.time >= "2011-06-01"].reset_index(drop=True)
        o, h, l, c = (df[k].values.astype(np.float64) for k in ("open", "high", "low", "close"))
        n = len(df)
        pc = np.r_[c[0], c[:-1]]
        tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
        N = pd.Series(tr).rolling(20).mean().values
        for (nin, nout), control in itertools.product(((20, 10), (55, 20)), (False, True)):
            for cost, (spr, cm) in costs(c).items():
                for swap in (0.0, 4.0):
                    for side in ("long", "short", "both"):
                        fills, rs_ = [], []
                        for d in ((1,) if side == "long" else (-1,) if side == "short" else (1, -1)):
                            mask = (np.where(rng.random(n) < 0.05, rng.choice([1, -1], n), 0)).astype(np.int64) \
                                if control else NONE
                            if control:
                                mask[0] = 0            # index 0 = -1 would mean "no mask"
                            s, f, r, days = (np.zeros(n, dtype=np.int64), np.zeros(n, dtype=np.int64), np.zeros(n),
                                             np.zeros(n, dtype=np.int64))
                            k = turtle(o, h, l, c, spr, d, N, nin, nout, mask, cm, s, f, r, days)
                            f, r, days = f[:k], r[:k], days[:k]
                            if swap > 0:
                                r = r - c[f] * swap / 100 / 365 * days * 1.4 / (2 * N[f - 1])
                            fills.append(f)
                            rs_.append(r)
                        f = np.concatenate(fills)
                        emit(rows, dict(strategy="Turtle (Donchian)", tf="D1",
                                        variant=f"System {1 if nin == 20 else 2}" + (" (random entry)" if control else ""),
                                        params=f"{nin}/{nout} side={side} swap={swap}%", control=control, cost=cost),
                             df.time.values[f], np.concatenate(rs_), years)
        print("Turtle done", flush=True)

    res = pd.DataFrame(rows)
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, "foreign_grid.csv")
    if os.path.exists(path) and a.only != "ICT,Brooks,ORB,Turtle":
        old = pd.read_csv(path)
        old = old[~old.strategy.isin(res.strategy.unique())]
        res = pd.concat([old, res], ignore_index=True)
    res.round(4).to_csv(path, index=False)


if __name__ == "__main__":
    main()
