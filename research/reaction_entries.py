"""
Reaction-based entries (market orders after a reaction at the zone):
  rejection = first bar that touches the zone and closes back outside on the bias side
  pinbar    = bullish/bearish pin bar near the zone's near edge without touching it
              (the intended v3 "Pin Bar" feature; evaluated on the base bars, M5 here)
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from run_study import IS_END, metrics
from vgap_engine import (infer_base_tf, TF_MIN, CascadeConfig, _scan_reaction, atr_sma, build_rung, generate_signals, load_bars,
                         r_multiples, simulate, spread_model, value_at_base)


def run(base, top, lvl, mode, sl_mode, sl_buf, rrs, replace=True, age_h=None, comm=0.07, sp=(0.20, 1.0),
        study_start="2012-01-01"):
    sig, aux = generate_signals(base, CascadeConfig(top=top, base_tf=infer_base_tf(base)))
    keep = (sig.df["sig_time"] >= pd.Timestamp(study_start)).values
    sig.df = sig.df[keep].reset_index(drop=True)
    sig.zones_top, sig.zones_bot = sig.zones_top[keep], sig.zones_bot[keep]
    bt, o, h, l, c, v = aux["base_t"], aux["o"], aux["h"], aux["l"], aux["c"], aux["v"]
    nb = len(bt)
    h1 = aux["rungs"].get("H1") or build_rung(bt, o, h, l, c, v, "H1", TF_MIN[infer_base_tf(base)])
    atr_b = value_at_base(h1, atr_sma(h1, 14), nb)
    si = sig.df["sig_idx"].values.astype(np.int64)
    d = sig.df["dir"].values.astype(np.int64)
    zt, zb = sig.zones_top[:, lvl], sig.zones_bot[:, lvl]
    ok = ~np.isnan(zt)
    end = np.full(len(si), nb, dtype=np.int64)
    if replace:
        end = np.minimum(end, np.r_[si[1:], nb])
    if age_h:
        end = np.minimum(end, np.searchsorted(bt, bt[si] + int(age_h * 60)))
    ridx = np.full(len(si), -1, dtype=np.int64)
    _scan_reaction(o, h, l, c, d, si, end, np.nan_to_num(zt), np.nan_to_num(zb), 0 if mode == "rejection" else 1,
                   0.30, ridx)
    ok &= (ridx >= 0) & (ridx + 1 < nb)
    idx = np.flatnonzero(ok)
    q = ridx[idx]
    st = q + 1
    spread = spread_model(c, *sp)
    atr = atr_b[si[idx]]
    E = np.where(d[idx] == 1, o[st] + spread[st], o[st])
    if sl_mode == "zone":
        far = np.where(d[idx] == 1, zb[idx], zt[idx])
    else:  # reaction bar extreme
        far = np.where(d[idx] == 1, l[q], h[q])
    S = np.where(d[idx] == 1, far - sl_buf * atr, far + sl_buf * atr + spread[q])
    valid = np.where(d[idx] == 1, S < E, S > E) & ~np.isnan(atr)
    idx, st, E, S = idx[valid], st[valid], E[valid], S[valid]
    hold = np.full(len(idx), {"H1": 24, "H4": 96, "D1": 240}[top] * 60, dtype=np.int64)
    sim = simulate(aux, d[idx], st, st + 1, E, S, hold, spread, comm, True, np.ones(len(idx), bool))
    ism = (sig.df["sig_time"].values[idx] < np.datetime64(IS_END))
    out = []
    for rr in rrs:
        r, _ = r_multiples(sim, d[idx], E, S, rr, comm)
        out.append(dict(top=top, level=sig.levels[lvl], mode=mode, sl=sl_mode, buf=sl_buf, rr=rr,
                        **{f"is_{k}": vv for k, vv in metrics(r[ism]).items()},
                        **{f"oos_{k}": vv for k, vv in metrics(r[~ism]).items()}))
    return pd.DataFrame(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="results/reaction_entries.csv")
    args = ap.parse_args()
    base = load_bars(args.data)
    frames = []
    for top, lvls in (("H1", [0, 1]), ("H4", [0, 1]), ("D1", [0, 1, 2])):
        for lvl in lvls:
            for mode in ("rejection", "pinbar"):
                for sl_mode, buf in (("zone", 0.1), ("bar", 0.1), ("bar", 0.25)):
                    for cost in ("net", "gross"):
                        kw = dict(comm=0.07, sp=(0.20, 1.0)) if cost == "net" else dict(comm=0.0, sp=(0.0, 0.0))
                        df = run(base, top, lvl, mode, sl_mode, buf, [1.0, 1.5, 2.0, 3.0], **kw)
                        df["cost"] = cost
                        frames.append(df)
    res = pd.concat(frames, ignore_index=True)
    res.to_csv(args.out, index=False)
    pd.set_option("display.width", 250)
    cols = ["top", "level", "mode", "sl", "buf", "rr", "cost", "is_n", "is_win", "is_avgR", "oos_n", "oos_win", "oos_avgR"]
    print(res[cols].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
