"""
Combination: vertical volume-gap candle (Pine v3 trigger) as the zone + the fixed-range
volume-profile valley INSIDE that gap candle as the entry.  Control: a random row of the
same profile.  Limit at the valley's near edge, SL beyond the gap candle's far edge.
"""
import sys
import numpy as np, pandas as pd
from run_study import IS_END, metrics
from vgap_engine import (CascadeConfig, atr_sma, generate_signals, load_bars, r_multiples, simulate,
                         spread_model, value_at_base)
from vp_valley import profile_valley, sub_index

base = load_bars(sys.argv[1])
base = base[(base.time >= "2011-06-01") & (base.time < "2025-03-21")].reset_index(drop=True)
rows = []
for top in ("H1", "H4", "D1"):
    sig, aux = generate_signals(base, CascadeConfig(top=top, base_tf="M5"))
    keep = (sig.df.sig_time >= pd.Timestamp("2012-01-01")).values
    df = sig.df[keep].reset_index(drop=True)
    gt, gb = sig.zones_top[keep, 0], sig.zones_bot[keep, 0]
    bt, h, l, v = aux["base_t"], aux["h"], aux["l"], aux["v"]
    st_i, en_i = sub_index(bt, top)
    rng = np.random.default_rng(1)
    atr_b = value_at_base(aux["rungs"]["H1"], atr_sma(aux["rungs"]["H1"], 14), len(bt))
    hold = {"H1": 24, "H4": 96, "D1": 240}[top] * 60
    for control in (False, True):
        vt = np.full(len(df), np.nan); vb = vt.copy()
        for i, k in enumerate(df.gap_bar.values):
            t_, b_, nr = profile_valley(h, l, v, st_i[k], en_i[k], 3, 30, rng.random() if control else -1.0)
            if nr > 0:
                vt[i], vb[i] = t_, b_
        d = df.dir.values.astype(np.int64); si = df.sig_idx.values.astype(np.int64)
        end = np.r_[si[1:], len(bt)].astype(np.int64)
        atr = atr_b[si]
        for entry in ("gapbox", "valley"):
            E = np.where(d == 1, gt, gb) if entry == "gapbox" else np.where(d == 1, vt, vb)
            if control and entry == "gapbox":
                continue
            for buf in (0.1, 0.25):
                S = np.where(d == 1, gb - buf * atr, gt + buf * atr)
                ok = ~np.isnan(E) & ~np.isnan(atr) & np.where(d == 1, S < E, S > E)
                idx = np.flatnonzero(ok)
                for cost in ("net", "gross"):
                    spr = spread_model(aux["c"], *((0.20, 1.0) if cost == "net" else (0.0, 0.0)))
                    cm = 0.07 if cost == "net" else 0.0
                    sim = simulate(aux, d[idx], si[idx], end[idx], E[idx], S[idx], np.full(len(idx), hold, dtype=np.int64), spr, cm, True)
                    ism = df.sig_time.values[idx] < np.datetime64(IS_END)
                    for rr in (1.5, 2.0, 3.0):
                        r, _ = r_multiples(sim, d[idx], E[idx], S[idx], rr, cm)
                        mi, mo = metrics(r[ism]), metrics(r[~ism])
                        rows.append(dict(top=top, entry=entry + ("_random" if control else ""), buf=buf, cost=cost, rr=rr,
                                         is_n=mi["n"], is_avgR=mi["avgR"], is_t=mi["t"], oos_n=mo["n"], oos_avgR=mo["avgR"], oos_t=mo["t"]))
res = pd.DataFrame(rows)
res.round(3).to_csv("results/combo_gap_valley.csv", index=False)
pd.set_option("display.width", 200)
print(res[(res.buf == 0.1) & (res.rr == 2.0)].round(3).to_string(index=False))
