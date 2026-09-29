"""
Volume-Valley (fixed-range volume profile) strategy research.

Rules tested (from the Pine "Volume-Valley" scripts + the manual variant):
  * For every top-TF candle (D1 / H4 / H1) build a fixed-range volume profile from its
    sub-bars (volume spread proportionally over the price rows each bar covers).
    Rows start at 3 and grow by one until the first interior local-minimum row appears
    (max 30).  That row is the zone (the "valley").
  * Bias: the candle's own close above the zone -> BUY on the pullback, below -> SELL.
  * Alignment filter (manual observation): the LAST lower-TF candle inside the top candle
    (last H1 of an H4, last H4 of a D1, last M15 of an H1) has its own valley and closed
    on the same side of it.
  * Entries: limit at the zone edge, or a pin-bar / doji trigger "connected" to the zone on
    the same TF or one/two TFs lower (market after it closes, or limit back at its body).
  * Control: a random interior row of the same profile instead of the valley.

The profile is built from M5 bars (M1 was not available); pass M1 data to use M1.
"""
from __future__ import annotations

import argparse
import itertools
import os

import numpy as np
import pandas as pd
from numba import njit

from run_study import IS_END, metrics
from vgap_engine import (TF_MIN, atr_sma, build_rung, infer_base_tf, load_bars, r_multiples, simulate,
                         spread_model, to_minutes, value_at_base)

LOWER = {"D1": ["D1", "H4", "H1"], "H4": ["H4", "H1", "M15"], "H1": ["H1", "M15", "M5"]}
ALIGN_TF = {"D1": "H4", "H4": "H1", "H1": "M15"}


@njit(cache=True)
def _profile_valley(h, l, v, s, e, min_r, max_r, rand_u):
    """Incremental-row volume profile of bars s..e.  Returns (top, bot, rows) of the first
    interior local-minimum row; with rand_u >= 0 returns a random interior row instead
    (control), using the same row count."""
    n = e - s + 1
    if n < 3:
        return np.nan, np.nan, -1
    hi = -1e18
    lo = 1e18
    for i in range(s, e + 1):
        if h[i] > hi:
            hi = h[i]
        if l[i] < lo:
            lo = l[i]
    pr = hi - lo
    if pr <= 0:
        return np.nan, np.nan, -1
    for rows in range(min_r, max_r + 1):
        step = pr / rows
        bins = np.zeros(rows)
        for i in range(s, e + 1):
            bh = h[i]
            bl = l[i]
            bv = v[i]
            br = bh - bl
            if br <= 0:
                idx = int(min(rows - 1, max(0.0, np.floor((bh - lo) / step))))
                bins[idx] += bv
            else:
                ilo = int(max(0.0, np.floor((bl - lo) / step)))
                ihi = int(min(rows - 1.0, np.floor((bh - lo) / step)))
                for b in range(ilo, ihi + 1):
                    blo = lo + b * step
                    bhi = blo + step
                    ov = min(bh, bhi) - max(bl, blo)
                    if ov > 0:
                        bins[b] += bv * (ov / br)
        vi = -1
        for i in range(1, rows - 1):
            if bins[i] < bins[i - 1] and bins[i] < bins[i + 1]:
                vi = i
                break
        if vi >= 0:
            if rand_u >= 0:
                vi = 1 + int(rand_u * (rows - 2))
            bot = lo + vi * step
            return bot + step, bot, rows
    return np.nan, np.nan, -1


def bars_of(bt, tf, base_min):
    m = TF_MIN[tf]
    bucket = (bt // m) * m
    starts = np.flatnonzero(np.r_[True, bucket[1:] != bucket[:-1]])
    ends = np.r_[starts[1:], len(bt)] - 1
    return starts, ends


def build(base, top, control=False, seed=0, min_r=3, max_r=30):
    bt = to_minutes(base["time"])
    o, h, l, c, v = [base[k].values.astype(np.float64) for k in ("open", "high", "low", "close", "volume")]
    base_min = TF_MIN[infer_base_tf(base)]
    rng = np.random.default_rng(seed)
    rungs = {tf: build_rung(bt, o, h, l, c, v, tf, base_min) for tf in set(LOWER[top] + [ALIGN_TF[top], "H1"])}
    st, en = bars_of(bt, top, base_min)
    R = rungs[top]
    ast, aen = bars_of(bt, ALIGN_TF[top], base_min)
    A = rungs[ALIGN_TF[top]]
    rows = []
    for k in range(len(st)):
        zt, zb, nr = _profile_valley(h, l, v, st[k], en[k], min_r, max_r, rng.random() if control else -1.0)
        if nr < 0:
            continue
        cc = R.c[k]
        d = 1 if cc > zt else (-1 if cc < zb else 0)
        if d == 0:
            continue
        sig_idx = int(R.avail[k])
        if sig_idx >= len(bt):
            continue
        # last lower-TF candle inside this top candle
        j = int(np.searchsorted(A.t, R.tc[k], side="left")) - 1
        al = 0
        if j >= 0 and A.t[j] >= R.t[k]:
            at, ab, anr = _profile_valley(h, l, v, ast[j], aen[j], min_r, max_r, -1.0)
            if anr > 0:
                al = 1 if A.c[j] > at else (-1 if A.c[j] < ab else 0)
        rows.append((k, sig_idx, d, zt, zb, nr, al == d, R.t[k], R.tc[k]))
    df = pd.DataFrame(rows, columns=["k", "sig_idx", "dir", "zt", "zb", "rows", "aligned", "t", "tc"])
    df["sig_time"] = pd.to_datetime(bt[df.sig_idx.values] * 60, unit="s")
    h1 = rungs["H1"]
    atr_b = value_at_base(h1, atr_sma(h1, 14), len(bt))
    aux = dict(base_t=bt, o=o, h=h, l=l, c=c, v=v, rungs=rungs)
    return df, aux, atr_b


def setup_end(df, bt, age_h):
    n = len(bt)
    si = df.sig_idx.values
    end = np.r_[si[1:], n].astype(np.int64)          # replaced by the next setup (Pine behaviour)
    if age_h:
        end = np.minimum(end, np.searchsorted(bt, bt[si] + int(age_h * 60)))
    return end


def find_triggers(df, aux, trig_tf, end, kind, band=0.3):
    """First pin bar / doji of trig_tf that opens after the setup, touches the zone (or is
    within band*height of its near edge) and closes back outside on the bias side.
    Scanning stops when a bar closes beyond the far edge.  Returns rung index or -1."""
    r = aux["rungs"][trig_tf]
    out = np.full(len(df), -1, dtype=np.int64)
    for i, row in enumerate(df.itertuples()):
        j0 = int(np.searchsorted(r.t, row.tc, side="left"))
        e_time = aux["base_t"][min(end[i], len(aux["base_t"]) - 1)]
        hgt = row.zt - row.zb
        j = j0
        while j < len(r.t) and r.avail[j] <= end[i] and r.tc[j] <= e_time + TF_MIN[trig_tf]:
            o, hh, ll, cc = r.o[j], r.h[j], r.l[j], r.c[j]
            body = abs(cc - o)
            rng_ = hh - ll
            up = hh - max(o, cc)
            lo = min(o, cc) - ll
            if rng_ > 0:
                if row.dir == 1:
                    shape = (lo >= 2 * body and lo > up) if kind == "pin" else (body <= 0.15 * rng_ or (lo >= 2 * body and lo > up))
                    if shape and ll <= row.zt + band * hgt and cc > row.zt:
                        out[i] = j
                        break
                    if cc < row.zb:
                        break
                else:
                    shape = (up >= 2 * body and up > lo) if kind == "pin" else (body <= 0.15 * rng_ or (up >= 2 * body and up > lo))
                    if shape and hh >= row.zb - band * hgt and cc < row.zb:
                        out[i] = j
                        break
                    if cc > row.zt:
                        break
            j += 1
    return out


def evaluate(df, aux, atr_b, spread, comm, mode, rr, sl_buf, age_h, trig_tf=None, kind="pinordoji",
             sl_ref="zone", hold_h=96, filt="all"):
    bt, o = aux["base_t"], aux["o"]
    n = len(bt)
    sel = np.ones(len(df), bool) if filt == "all" else df.aligned.values
    d = df.dir.values.astype(np.int64)
    zt, zb = df.zt.values, df.zb.values
    si = df.sig_idx.values.astype(np.int64)
    end = setup_end(df, bt, age_h)
    atr = atr_b[si]
    if mode == "zone":
        E = np.where(d == 1, zt, zb)
        S = np.where(d == 1, zb - sl_buf * atr, zt + sl_buf * atr)
        st = si.copy()
        mkt = np.zeros(len(df), bool)
    else:
        trig = find_triggers(df, aux, trig_tf, end, kind)
        r = aux["rungs"][trig_tf]
        ok = trig >= 0
        sel = sel & ok
        tj = np.where(ok, trig, 0)
        pl, ph, po, pc = r.l[tj], r.h[tj], r.o[tj], r.c[tj]
        st = np.minimum(r.avail[tj], n - 1).astype(np.int64)
        if sl_ref == "zone":
            S = np.where(d == 1, zb - sl_buf * atr, zt + sl_buf * atr)
        else:
            S = np.where(d == 1, pl - sl_buf * atr, ph + sl_buf * atr)
        if mode == "trig_mkt":
            E = np.where(d == 1, o[st] + spread[st], o[st])
            mkt = np.ones(len(df), bool)
        else:  # limit back at the trigger candle's body
            E = np.where(d == 1, np.maximum(po, pc), np.minimum(po, pc))
            mkt = np.zeros(len(df), bool)
    valid = sel & ~np.isnan(atr) & np.where(d == 1, S < E, S > E) & (st < end if mode == "trig_lim" else True)
    idx = np.flatnonzero(valid)
    if len(idx) == 0:
        return None
    endv = np.where(mkt[idx], st[idx] + 1, end[idx])
    hold = np.full(len(idx), int(hold_h * 60), dtype=np.int64)
    sim = simulate(aux, d[idx], st[idx], endv, E[idx], S[idx], hold, spread, comm, True, mkt[idx])
    rv, _ = r_multiples(sim, d[idx], E[idx], S[idx], rr, comm)
    return pd.DataFrame({"time": df.sig_time.values[idx], "R": rv}).dropna()


def run(args):
    base = load_bars(args.data)
    base = base[(base.time >= "2011-06-01") & (base.time < "2025-03-21")].reset_index(drop=True)
    rows = []
    for top in args.tops.split(","):
        hold_h = {"H1": 24, "H4": 96, "D1": 240}[top]
        unit = {"H1": 1, "H4": 4, "D1": 24}[top]
        for control in (False, True):
            df, aux, atr_b = build(base, top, control=control)
            df = df[df.sig_time >= "2012-01-01"].reset_index(drop=True)
            for cost in ("net", "gross"):
                spread = spread_model(aux["c"], 0.20, 1.0) if cost == "net" else spread_model(aux["c"], 0.0, 0.0)
                comm = 0.07 if cost == "net" else 0.0
                grid = [("zone", None, None, "zone")]
                for ttf in LOWER[top]:
                    for kind in ("pin", "pinordoji"):
                        grid += [("trig_mkt", ttf, kind, "zone"), ("trig_mkt", ttf, kind, "bar"),
                                 ("trig_lim", ttf, kind, "bar")]
                for (mode, ttf, kind, slr), filt, rr, buf, age in itertools.product(
                        grid, ("all", "aligned"), (1.0, 1.5, 2.0, 3.0), (0.1, 0.25), (None, 10 * unit)):
                    if control and filt == "aligned":
                        continue
                    tr = evaluate(df, aux, atr_b, spread, comm, mode, rr, buf, age, ttf, kind or "pin", slr, hold_h, filt)
                    if tr is None:
                        continue
                    ism = tr.time < IS_END
                    mi, mo = metrics(tr.R.values[ism.values]), metrics(tr.R.values[~ism.values])
                    rows.append(dict(top=top, control=control, cost=cost, mode=mode, trig_tf=ttf, kind=kind, sl=slr,
                                     filt=filt, rr=rr, buf=buf, age=age or -1,
                                     is_n=mi["n"], is_win=mi["win"], is_avgR=mi["avgR"], is_t=mi["t"], is_maxDD=mi["maxDD"],
                                     oos_n=mo["n"], oos_win=mo["win"], oos_avgR=mo["avgR"], oos_t=mo["t"], oos_maxDD=mo["maxDD"]))
            print(top, "control" if control else "valley", "signals:", len(df),
                  "aligned share: %.2f" % df.aligned.mean(), flush=True)
    res = pd.DataFrame(rows)
    os.makedirs(args.out, exist_ok=True)
    res.to_csv(os.path.join(args.out, "vp_grid.csv"), index=False)
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="results")
    ap.add_argument("--tops", default="H4,H1,D1")
    run(ap.parse_args())
