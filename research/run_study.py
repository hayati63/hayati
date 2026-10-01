"""
Backtest + robust optimisation study for the Vertical Volume Gap Cascade.

    python run_study.py --data ../data/XAUUSD_M5.parquet --base M5 --out results

Every configuration is evaluated in R-multiples (net of spread + commission) on an
in-sample period and, separately, on an out-of-sample period that is never used for
choosing parameters.  See docs/REPORT_fa.md for the interpretation.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import time

import numpy as np
import pandas as pd

from vgap_engine import (CascadeConfig, TF_MIN, atr_sma, generate_signals, r_multiples,
                         simulate, spread_model, value_at_base)

IS_END = pd.Timestamp("2020-01-01")


# --------------------------------------------------------------------------------------
def build_candidates(sig, aux, lvl: int, depth: float, sl_ref: str, sl_buf: float,
                     atr_base: np.ndarray, max_age_h: float | None, replace: bool,
                     hold_h: float, min_risk_atr: float = 0.0):
    df = sig.df
    zt = sig.zones_top[:, lvl]
    zb = sig.zones_bot[:, lvl]
    ok = ~np.isnan(zt)
    sig_idx = df["sig_idx"].values.astype(np.int64)
    dirs = df["dir"].values.astype(np.int64)
    bt = aux["base_t"]
    n = len(bt)
    # end of the "armed" period
    end = np.full(len(df), n, dtype=np.int64)
    if replace:
        nxt = np.r_[sig_idx[1:], n]
        end = np.minimum(end, nxt)
    if max_age_h is not None:
        lim = np.searchsorted(bt, bt[sig_idx] + int(max_age_h * 60), side="left")
        end = np.minimum(end, lim)
    height = zt - zb
    E = np.where(dirs == 1, zt - depth * height, zb + depth * height)
    if sl_ref == "own":
        far = np.where(dirs == 1, zb, zt)
    else:  # far edge of the top-level zone
        far = np.where(dirs == 1, sig.zones_bot[:, 0], sig.zones_top[:, 0])
    atr = atr_base[sig_idx]
    buf = sl_buf * atr
    S = np.where(dirs == 1, far - buf, far + buf)
    if min_risk_atr > 0:
        mr = min_risk_atr * atr
        S = np.where(dirs == 1, np.minimum(S, E - mr), np.maximum(S, E + mr))
    ok &= ~np.isnan(atr) & (np.abs(E - S) > 1e-9)
    hold = np.full(len(df), int(hold_h * 60), dtype=np.int64)
    return ok, dirs, sig_idx, end, E, S, hold


def metrics(r: np.ndarray, t_exit: np.ndarray | None = None, years: float = 1.0) -> dict:
    r = r[~np.isnan(r)]
    n = len(r)
    if n == 0:
        return dict(n=0, win=np.nan, avgR=np.nan, pf=np.nan, totR=0.0, perYear=0.0, t=np.nan, maxDD=0.0)
    wins = r[r > 0].sum()
    losses = -r[r < 0].sum()
    eq = np.cumsum(r)
    dd = np.max(np.maximum.accumulate(np.r_[0, eq])[1:] - eq) if n else 0.0
    sd = r.std(ddof=1) if n > 1 else np.nan
    return dict(n=n, win=float((r > 0).mean()), avgR=float(r.mean()),
                pf=float(wins / losses) if losses > 0 else np.inf, totR=float(r.sum()),
                perYear=float(n / years), t=float(r.mean() / sd * np.sqrt(n)) if sd and sd > 0 else np.nan,
                maxDD=float(dd))


def run_grid(sig, aux, spread, comm, grid: dict, rrs, pessimistic=True, label=""):
    rungs = aux["rungs"]
    h1 = rungs["H1"] if "H1" in rungs else None
    atr_base = value_at_base(h1, atr_sma(h1, 14), len(aux["base_t"]))
    sig_time = pd.to_datetime(sig.df["sig_time"]).values
    is_mask_all = sig_time < np.datetime64(IS_END)
    y_is = (IS_END - pd.Timestamp(sig.df["sig_time"].min())).days / 365.25
    y_oos = (pd.Timestamp(sig.df["sig_time"].max()) - IS_END).days / 365.25
    rows = []
    keys = list(grid.keys())
    for combo in itertools.product(*[grid[k] for k in keys]):
        p = dict(zip(keys, combo))
        if p["lvl"] >= len(sig.levels):
            continue
        if p["sl_ref"] == "top" and p["lvl"] == 0:
            continue  # identical to "own"
        ok, dirs, st, end, E, S, hold = build_candidates(
            sig, aux, p["lvl"], p["depth"], p["sl_ref"], p["sl_buf"], atr_base,
            p["max_age_h"], p["replace"], p["hold_h"], p.get("min_risk_atr", 0.0))
        idx = np.flatnonzero(ok)
        sim = simulate(aux, dirs[idx], st[idx], end[idx], E[idx], S[idx], hold[idx], spread, comm, pessimistic)
        fill_rate = sim["fill"].mean() if len(idx) else np.nan
        risk = np.abs(E[idx] - S[idx])
        atr_i = atr_base[st[idx]]
        for rr in rrs:
            r, win = r_multiples(sim, dirs[idx], E[idx], S[idx], rr, comm)
            ism = is_mask_all[idx]
            m_is = metrics(r[ism], years=y_is)
            m_oos = metrics(r[~ism], years=y_oos)
            row = dict(label=label, **p, rr=rr, fill_rate=fill_rate,
                       risk_atr_med=float(np.nanmedian((risk / atr_i)[sim["fill"]])) if sim["fill"].any() else np.nan)
            row.update({f"is_{k}": v for k, v in m_is.items()})
            row.update({f"oos_{k}": v for k, v in m_oos.items()})
            rows.append(row)
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--base", default="auto", help="M1, M5 or auto")
    ap.add_argument("--out", default="results")
    ap.add_argument("--tops", default="H1,H4,D1")
    ap.add_argument("--start", default="2011-06-01")
    ap.add_argument("--end", default="2025-03-21")
    ap.add_argument("--study_start", default="2012-01-01")
    ap.add_argument("--spread_floor", type=float, default=0.20)
    ap.add_argument("--spread_bps", type=float, default=1.0)
    ap.add_argument("--comm", type=float, default=0.07)
    ap.add_argument("--heuristic", action="store_true")
    ap.add_argument("--tag", default="")
    ap.add_argument("--no_volume_gap", action="store_true", help="control: drop the volume condition")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    from vgap_engine import load_bars
    base = load_bars(args.data)
    base = base[(base.time >= args.start) & (base.time < args.end)].reset_index(drop=True)
    if args.base == "auto":
        from vgap_engine import infer_base_tf
        args.base = infer_base_tf(base)
    spread = spread_model(base["close"].values, args.spread_floor, args.spread_bps)
    if "spread" in base.columns and base["spread"].gt(0).any():
        pass  # real spreads are in points; the model is kept for comparability
    rrs = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0]
    all_rows = []
    for top in args.tops.split(","):
        t0 = time.time()
        sig, aux = generate_signals(base, CascadeConfig(top=top, base_tf=args.base,
                                                        require_volume_gap=not args.no_volume_gap))
        keep = sig.df["sig_time"] >= pd.Timestamp(args.study_start)
        sig.df = sig.df[keep].reset_index(drop=True)
        sig.zones_top = sig.zones_top[keep.values]
        sig.zones_bot = sig.zones_bot[keep.values]
        age_unit = {"H1": 1, "H4": 4, "D1": 24}[top]
        grid = dict(
            lvl=list(range(len(sig.levels))),
            depth=[0.0, 0.5],
            sl_ref=["own", "top"],
            sl_buf=[0.0, 0.1, 0.25, 0.5],
            max_age_h=[None, 6 * age_unit, 24 * age_unit],
            replace=[True, False],
            hold_h=[24 * age_unit if top != "D1" else 24 * 10],
        )
        # replace=False with no max age is not a realistic setting
        df = run_grid(sig, aux, spread, args.comm, grid, rrs, pessimistic=not args.heuristic, label=top)
        df = df[~((~df["replace"]) & (df["max_age_h"].isna()))]
        df["top"] = top
        df["level"] = [sig.levels[i] for i in df["lvl"]]
        all_rows.append(df)
        print(f"{top}: {len(sig.df)} signals, {len(df)} rows, {time.time() - t0:.1f}s, stats={sig.stats}")
    res = pd.concat(all_rows, ignore_index=True)
    tag = ("heur" if args.heuristic else "pess") + (("_" + args.tag) if args.tag else "")
    res.to_csv(os.path.join(args.out, f"grid_{tag}.csv"), index=False)
    print("saved", len(res))


if __name__ == "__main__":
    main()
