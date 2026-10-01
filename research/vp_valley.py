"""
Volume-Valley (fixed-range volume profile) strategy research.

Zone: for every top-TF candle (D1 / H4 / H1) build a fixed-range volume profile from its
sub-bars (volume spread proportionally over the rows each bar covers); rows start at 3 and
grow until the first interior local-minimum row appears (max 30).  Bias: that candle's own
close above the zone -> BUY on the pullback, below -> SELL.

Entry models (all resting limit orders, the user's three models + the plain zone):
  Z   the top zone itself (near edge)
  M1  valley of the LAST lower-TF candle inside the top candle (last H1 of an H4)
  M2  cascade: lower-TF candle of the bias colour that best covers the parent box
      (breakout tie-break), its valley, down one more TF (Pine "Production" logic);
      a stage that fails the direction/overlap checks kills the trade
  M3  body of the first doji / pin bar of one TF lower that touches the zone and closes back
      outside on the bias side
Filter "aligned": the last lower-TF candle closed on the same side of its own valley.
Control: a random interior row of the same profile instead of the valley.
Profiles are built from M5 bars (M1 was not available in this study).
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

CHAIN = {"D1": ["D1", "H4", "H1"], "H4": ["H4", "H1", "M15"], "H1": ["H1", "M15", "M5"]}


@njit(cache=True)
def profile_valley(h, l, v, s, e, min_r, max_r, rand_u):
    n = e - s + 1
    if n < 3:
        return np.nan, np.nan, -1
    hi = -1e18
    lo = 1e18
    for i in range(s, e + 1):
        hi = max(hi, h[i])
        lo = min(lo, l[i])
    pr = hi - lo
    if pr <= 0:
        return np.nan, np.nan, -1
    for rows in range(min_r, max_r + 1):
        step = pr / rows
        bins = np.zeros(rows)
        for i in range(s, e + 1):
            bh, bl, bv = h[i], l[i], v[i]
            br = bh - bl
            if br <= 0:
                idx = int(min(rows - 1, max(0.0, np.floor((bh - lo) / step))))
                bins[idx] += bv
            else:
                ilo = int(max(0.0, np.floor((bl - lo) / step)))
                ihi = int(min(rows - 1.0, np.floor((bh - lo) / step)))
                for b in range(ilo, ihi + 1):
                    blo = lo + b * step
                    ov = min(bh, blo + step) - max(bl, blo)
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


def sub_index(bt, tf):
    m = TF_MIN[tf]
    b = (bt // m) * m
    st = np.flatnonzero(np.r_[True, b[1:] != b[:-1]])
    return st, np.r_[st[1:], len(bt)] - 1


def pick_candle(r, j0, j1, d, top, bot, margin=0.10):
    """Pine f_pickCandle: bias colour, overlaps the box, highest coverage (volume tie-break),
    a candle that broke through wins if its coverage is within `margin`."""
    hgt = top - bot
    best, bcov, bvol, bb, bbcov, nq = -1, -1.0, -1.0, -1, -1.0, 0
    for j in range(j0, j1):
        if not ((r.c[j] < r.o[j]) if d == -1 else (r.c[j] > r.o[j])):
            continue
        ov = min(r.h[j], top) - max(r.l[j], bot)
        if ov <= 0 or hgt <= 0:
            continue
        nq += 1
        cov = ov / hgt
        brk = r.l[j] < bot if d == -1 else r.h[j] > top
        if cov > bcov or (cov == bcov and r.v[j] > bvol):
            best, bcov, bvol = j, cov, r.v[j]
        if brk and cov > bbcov:
            bb, bbcov = j, cov
    if bb >= 0 and bb != best and bcov - bbcov <= margin:
        best = bb
    return best, bcov, nq


def build(base, top, control=False, seed=0):
    bt = to_minutes(base["time"])
    o, h, l, c, v = [base[k].values.astype(np.float64) for k in ("open", "high", "low", "close", "volume")]
    bm = TF_MIN[infer_base_tf(base)]
    rng = np.random.default_rng(seed)
    t0, t1, t2 = CHAIN[top]
    R = {tf: build_rung(bt, o, h, l, c, v, tf, bm) for tf in set(CHAIN[top] + ["H1"])}
    S = {tf: sub_index(bt, tf) for tf in CHAIN[top]}
    rows = []
    for k in range(len(R[t0].t)):
        s, e = S[t0][0][k], S[t0][1][k]
        zt, zb, nr = profile_valley(h, l, v, s, e, 3, 30, rng.random() if control else -1.0)
        if nr < 0:
            continue
        cc = R[t0].c[k]
        d = 1 if cc > zt else (-1 if cc < zb else 0)
        if d == 0 or R[t0].avail[k] >= len(bt):
            continue
        rec = dict(k=k, sig_idx=int(R[t0].avail[k]), dir=d, zt=zt, zb=zb, rows=nr, tc=R[t0].tc[k])
        # ---- M1: last lower-TF candle inside the top candle
        r1 = R[t1]
        j0 = int(np.searchsorted(r1.t, R[t0].t[k]))
        j1 = int(np.searchsorted(r1.t, R[t0].tc[k]))
        rec.update(m1t=np.nan, m1b=np.nan, aligned=False)
        if j1 - 1 >= j0:
            j = j1 - 1
            at, ab, anr = profile_valley(h, l, v, S[t1][0][j], S[t1][1][j], 3, 30, -1.0)
            if anr > 0:
                rec.update(m1t=at, m1b=ab)
                ad = 1 if r1.c[j] > at else (-1 if r1.c[j] < ab else 0)
                rec["aligned"] = ad == d
        # ---- M2: cascade (Pine production logic) down two TFs
        rec.update(m2t=np.nan, m2b=np.nan)
        top_, bot_, w0, w1, ok = zt, zb, j0, j1, True
        for tf in (t1, t2):
            r = R[tf]
            if tf != t1:
                w0 = int(np.searchsorted(r.t, r_prev.t[jp]))
                w1 = int(np.searchsorted(r.t, r_prev.tc[jp]))
            jp, cov, nq = pick_candle(r, w0, w1, d, top_, bot_)
            if jp < 0:
                ok = False
                break
            vt, vb, vnr = profile_valley(h, l, v, S[tf][0][jp], S[tf][1][jp], 3, 30, -1.0)
            if vnr < 0:
                ok = False
                break
            clean = (1 if cc > vt else (-1 if cc < vb else 0)) == d
            overl = vb <= top_ and bot_ <= vt
            if not clean or not (overl or (nq == 1 and cov >= 0.95)):
                ok = False
                break
            top_, bot_, r_prev = vt, vb, r
        if ok:
            rec.update(m2t=top_, m2b=bot_)
        rows.append(rec)
    df = pd.DataFrame(rows)
    df["sig_time"] = pd.to_datetime(bt[df.sig_idx.values] * 60, unit="s")
    h1 = R["H1"]
    atr_b = value_at_base(h1, atr_sma(h1, 14), len(bt))
    aux = dict(base_t=bt, o=o, h=h, l=l, c=c, v=v, rungs=R)
    return df, aux, atr_b


def find_doji(df, aux, trig_tf, end, band=0.3):
    """M3: first doji (body <= 15% of range) or pin bar of trig_tf opening after the top
    candle, touching the zone (or within band*height of its near edge) and closing back
    outside on the bias side; stops when a bar closes beyond the far edge."""
    r = aux["rungs"][trig_tf]
    bt = aux["base_t"]
    out = np.full(len(df), -1, dtype=np.int64)
    for i, row in enumerate(df.itertuples()):
        hgt = row.zt - row.zb
        j = int(np.searchsorted(r.t, row.tc))
        while j < len(r.t) and r.avail[j] < end[i]:
            o, hh, ll, cc = r.o[j], r.h[j], r.l[j], r.c[j]
            body, rg = abs(cc - o), hh - ll
            up, lo = hh - max(o, cc), min(o, cc) - ll
            if rg > 0:
                if row.dir == 1:
                    if (body <= 0.15 * rg or (lo >= 2 * body and lo > up)) and ll <= row.zt + band * hgt and cc > row.zt:
                        out[i] = j
                        break
                    if cc < row.zb:
                        break
                else:
                    if (body <= 0.15 * rg or (up >= 2 * body and up > lo)) and hh >= row.zb - band * hgt and cc < row.zb:
                        out[i] = j
                        break
                    if cc > row.zt:
                        break
            j += 1
    return out


def model_orders(df, aux, atr_b, model, sl_ref, buf, end, doji_idx=None, trig_tf=None):
    """Limit entry E, stop S and start index for each signal (nan when the model has no zone)."""
    d = df.dir.values
    si = df.sig_idx.values.astype(np.int64)
    atr = atr_b[si]
    st = si.copy()
    if model == "Z":
        t, b = df.zt.values, df.zb.values
    elif model == "M1":
        t, b = df.m1t.values, df.m1b.values
    elif model == "M2":
        t, b = df.m2t.values, df.m2b.values
    else:  # M3: doji body
        r = aux["rungs"][trig_tf]
        ok = doji_idx >= 0
        j = np.where(ok, doji_idx, 0)
        t = np.where(ok, np.maximum(r.o[j], r.c[j]), np.nan)
        b = np.where(ok, np.minimum(r.o[j], r.c[j]), np.nan)
        st = np.where(ok, np.minimum(r.avail[j], len(aux["base_t"]) - 1), si).astype(np.int64)
        wick_lo, wick_hi = r.l[j], r.h[j]
    E = np.where(d == 1, t, b)
    if sl_ref == "own":
        if model == "M3":
            far = np.where(d == 1, wick_lo, wick_hi)
        else:
            far = np.where(d == 1, b, t)
    else:  # beyond the top zone
        far = np.where(d == 1, df.zb.values, df.zt.values)
    Sx = np.where(d == 1, far - buf * atr, far + buf * atr)
    ok = ~np.isnan(E) & ~np.isnan(atr) & np.where(d == 1, Sx < E, Sx > E) & (st < end)
    return E, Sx, st, ok


RRS = (1.0, 1.5, 2.0, 3.0)


def run(args):
    base = load_bars(args.data)
    base = base[(base.time >= "2011-06-01") & (base.time < "2025-03-21")].reset_index(drop=True)
    rows = []
    for top in args.tops.split(","):
        unit = {"H1": 1, "H4": 4, "D1": 24}[top]
        hold_h = {"H1": 24, "H4": 96, "D1": 240}[top]
        for control in (False, True):
            df, aux, atr_b = build(base, top, control=control)
            df = df[df.sig_time >= "2012-01-01"].reset_index(drop=True)
            bt = aux["base_t"]
            n = len(bt)
            si = df.sig_idx.values
            print(f"{top} {'control' if control else 'valley'}: signals={len(df)} aligned={df.aligned.mean():.2f} "
                  f"M1 zone={df.m1t.notna().mean():.2f} M2 zone={df.m2t.notna().mean():.2f}", flush=True)
            for age in (6 * unit, 24 * unit):
                end = np.minimum(np.searchsorted(bt, bt[si] + age * 60), n).astype(np.int64)
                dojis = {tf: find_doji(df, aux, tf, end) for tf in CHAIN[top][1:2]}
                models = [("Z", None), ("M1", None), ("M2", None)] + [("M3", tf) for tf in dojis]
                for (model, ttf), sl_ref, buf in itertools.product(models, ("own", "top"), (0.1, 0.25)):
                    if control and model != "Z":
                        continue
                    E, Sx, st, ok = model_orders(df, aux, atr_b, model, sl_ref, buf, end,
                                                 dojis.get(ttf), ttf)
                    for cost in ("net", "gross"):
                        spread = spread_model(aux["c"], *((0.20, 1.0) if cost == "net" else (0.0, 0.0)))
                        comm = 0.07 if cost == "net" else 0.0
                        idx = np.flatnonzero(ok)
                        d = df.dir.values[idx].astype(np.int64)
                        sim = simulate(aux, d, st[idx], end[idx], E[idx], Sx[idx],
                                       np.full(len(idx), hold_h * 60, dtype=np.int64), spread, comm, True)
                        ism = df.sig_time.values[idx] < np.datetime64(IS_END)
                        al = df.aligned.values[idx]
                        for rr in RRS:
                            rv, _ = r_multiples(sim, d, E[idx], Sx[idx], rr, comm)
                            for filt in ("all", "aligned"):
                                if control and filt == "aligned":
                                    continue
                                f = al if filt == "aligned" else np.ones(len(idx), bool)
                                mi, mo = metrics(rv[f & ism]), metrics(rv[f & ~ism])
                                rows.append(dict(top=top, control=control, cost=cost, model=model, trig_tf=ttf,
                                                 sl=sl_ref, buf=buf, age_h=age, filt=filt, rr=rr,
                                                 setups=int(f.sum()), fill=float(np.mean(sim["fill"][f])) if f.any() else np.nan,
                                                 is_n=mi["n"], is_win=mi["win"], is_avgR=mi["avgR"], is_t=mi["t"],
                                                 oos_n=mo["n"], oos_win=mo["win"], oos_avgR=mo["avgR"], oos_t=mo["t"],
                                                 is_maxDD=mi["maxDD"], oos_maxDD=mo["maxDD"]))
    res = pd.DataFrame(rows)
    os.makedirs(args.out, exist_ok=True)
    res.to_csv(os.path.join(args.out, "vp_grid.csv"), index=False)
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="results")
    ap.add_argument("--tops", default="H4,D1,H1")
    run(ap.parse_args())
