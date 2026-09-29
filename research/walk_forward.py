"""
Walk-forward optimisation (WFO) of the Vertical Volume Gap Cascade.

For every test year Y the parameter set is chosen using ONLY the previous `train_years`
years, then traded blind in year Y.  Chaining the test years gives an honest estimate of
what "optimising SL/TP (and filters) on history" would really have delivered.

    python walk_forward.py --data ../data/XAUUSD_M5.parquet --out results
"""
from __future__ import annotations

import argparse
import itertools
import os
import time

import numpy as np
import pandas as pd

from analyze_features import ema
from run_study import build_candidates
from vgap_engine import (infer_base_tf, TF_MIN, CascadeConfig, atr_sma, build_rung, generate_signals, load_bars, r_multiples,
                         simulate, spread_model, value_at_base)

RRS = [0.75, 1.0, 1.5, 2.0, 3.0]


def yearly_grid(base, top, spread, comm, study_start="2012-01-01", pessimistic=True):
    sig, aux = generate_signals(base, CascadeConfig(top=top, base_tf=infer_base_tf(base)))
    keep = (sig.df["sig_time"] >= pd.Timestamp(study_start)).values
    sig.df = sig.df[keep].reset_index(drop=True)
    sig.zones_top, sig.zones_bot = sig.zones_top[keep], sig.zones_bot[keep]
    bt, o, h, l, c, v = aux["base_t"], aux["o"], aux["h"], aux["l"], aux["c"], aux["v"]
    nb = len(bt)
    h1 = aux["rungs"].get("H1") or build_rung(bt, o, h, l, c, v, "H1", TF_MIN[infer_base_tf(base)])
    atr_b = value_at_base(h1, atr_sma(h1, 14), nb)
    d1 = build_rung(bt, o, h, l, c, v, "D1", TF_MIN[infer_base_tf(base)])
    d1_trend = value_at_base(d1, np.sign(d1.c - ema(d1.c, 50)), nb)
    si_all = sig.df["sig_idx"].values
    d_all = sig.df["dir"].values
    trend_ok = (d1_trend[si_all] * d_all) > 0
    direct = sig.df["path"].values == 0
    years = pd.to_datetime(sig.df["sig_time"]).dt.year.values
    u = {"H1": 1, "H4": 4, "D1": 24}[top]
    hold_h = {"H1": 24, "H4": 96, "D1": 240}[top]
    grid = dict(
        lvl=list(range(len(sig.levels))),
        depth=[0.0, 0.5],
        sl_ref=["own", "top"],
        sl_buf=[0.0, 0.1, 0.25, 0.5],
        arm=[("replace", None), ("replace", 24 * u), ("age", 6 * u), ("age", 24 * u)],
        delay_h=[0, 2 * u],
    )
    rows = []
    keys = list(grid)
    for combo in itertools.product(*[grid[k] for k in keys]):
        p = dict(zip(keys, combo))
        if p["sl_ref"] == "top" and p["lvl"] == 0:
            continue
        replace = p["arm"][0] == "replace"
        ok, dirs, st, end, E, S, hold = build_candidates(sig, aux, p["lvl"], p["depth"], p["sl_ref"], p["sl_buf"],
                                                         atr_b, p["arm"][1], replace, hold_h)
        if p["delay_h"] > 0:
            st = np.maximum(st, np.searchsorted(bt, bt[st] + int(p["delay_h"] * 60), side="left"))
            ok &= st < end
        idx = np.flatnonzero(ok)
        sim = simulate(aux, dirs[idx], st[idx], end[idx], E[idx], S[idx], hold[idx], spread, comm, pessimistic)
        for rr in RRS:
            r, _ = r_multiples(sim, dirs[idx], E[idx], S[idx], rr, comm)
            for flt_name, fmask in (("all", np.ones(len(idx), bool)), ("direct", direct[idx]),
                                    ("trend", trend_ok[idx]), ("direct+trend", direct[idx] & trend_ok[idx])):
                rr_ok = fmask & ~np.isnan(r)
                if not rr_ok.any():
                    continue
                y = years[idx][rr_ok]
                rv = r[rr_ok]
                agg = pd.DataFrame({"y": y, "r": rv}).groupby("y")["r"].agg(["size", "sum"])
                for yy, (nn, ss) in agg.iterrows():
                    rows.append((top, p["lvl"], sig.levels[p["lvl"]], p["depth"], p["sl_ref"], p["sl_buf"],
                                 p["arm"][0], p["arm"][1] if p["arm"][1] else -1, p["delay_h"], flt_name, rr,
                                 int(yy), int(nn), float(ss)))
    cols = ["top", "lvl", "level", "depth", "sl_ref", "sl_buf", "arm", "age_h", "delay_h", "filter", "rr",
            "year", "n", "sumR"]
    return pd.DataFrame(rows, columns=cols)


def walk_forward(yg: pd.DataFrame, train_years=4, first_test=2016, last_test=2025, min_trades_per_year=8,
                 top_k=1, by_level=False):
    cfg_cols = ["top", "lvl", "level", "depth", "sl_ref", "sl_buf", "arm", "age_h", "delay_h", "filter", "rr"]
    out = []
    groups = [((None,), yg)] if not by_level else list(yg.groupby("level"))
    for gkey, g in groups:
        piv_n = g.pivot_table(index=cfg_cols, columns="year", values="n", aggfunc="sum", fill_value=0)
        piv_s = g.pivot_table(index=cfg_cols, columns="year", values="sumR", aggfunc="sum", fill_value=0.0)
        for ty in range(first_test, last_test + 1):
            tr = [y for y in range(ty - train_years, ty) if y in piv_n.columns]
            if ty not in piv_n.columns or len(tr) < train_years:
                continue
            n_tr = piv_n[tr].sum(1)
            s_tr = piv_s[tr].sum(1)
            elig = n_tr >= min_trades_per_year * train_years
            score = (s_tr / n_tr.replace(0, np.nan))[elig].sort_values(ascending=False)
            pick = score.index[:top_k]
            n_te = piv_n.loc[pick, ty].sum()
            s_te = piv_s.loc[pick, ty].sum()
            out.append(dict(group=gkey if by_level else "all", test_year=ty, train_avgR=float(score.iloc[:top_k].mean()),
                            test_n=int(n_te), test_sumR=float(s_te),
                            test_avgR=float(s_te / n_te) if n_te else np.nan,
                            pick=" | ".join(str(dict(zip(cfg_cols, p))) for p in pick[:1])))
    return pd.DataFrame(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="results")
    ap.add_argument("--tops", default="H1,H4,D1")
    ap.add_argument("--spread_floor", type=float, default=0.20)
    ap.add_argument("--spread_bps", type=float, default=1.0)
    ap.add_argument("--comm", type=float, default=0.07)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    base = load_bars(args.data)
    spread = spread_model(base["close"].values, args.spread_floor, args.spread_bps)
    frames = []
    for top in args.tops.split(","):
        t0 = time.time()
        yg = yearly_grid(base, top, spread, args.comm)
        print(f"{top}: {len(yg)} rows in {time.time() - t0:.0f}s", flush=True)
        frames.append(yg)
    yg = pd.concat(frames, ignore_index=True)
    yg.to_parquet(os.path.join(args.out, "yearly_grid.parquet"), index=False)


if __name__ == "__main__":
    main()
