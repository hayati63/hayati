"""
Trade-level feature analysis: does any concept-consistent filter create an edge that
survives out-of-sample?  Writes bucket tables (gross and net avg R, IS vs OOS).
"""
from __future__ import annotations

import argparse
import os

import numpy as np
import pandas as pd

from run_study import IS_END, build_candidates
from vgap_engine import (infer_base_tf, CascadeConfig, TF_MIN, atr_sma, build_rung, generate_signals, load_bars,
                         r_multiples, simulate, spread_model, to_minutes, value_at_base)


def ema(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).ewm(span=n, adjust=False).mean().values


def trade_table(base, top, lvl, depth, sl_ref, sl_buf, rr, max_age_h=None, replace=True, hold_h=None,
                spread_floor=0.20, spread_bps=1.0, comm=0.07, pessimistic=True, study_start="2012-01-01"):
    sig, aux = generate_signals(base, CascadeConfig(top=top, base_tf=infer_base_tf(base)))
    keep = (sig.df["sig_time"] >= pd.Timestamp(study_start)).values
    sig.df = sig.df[keep].reset_index(drop=True)
    sig.zones_top, sig.zones_bot = sig.zones_top[keep], sig.zones_bot[keep]
    bt = aux["base_t"]
    nb = len(bt)
    o, h, l, c, v = aux["o"], aux["h"], aux["l"], aux["c"], aux["v"]
    h1 = aux["rungs"].get("H1") or build_rung(bt, o, h, l, c, v, "H1", TF_MIN[infer_base_tf(base)])
    atr_b = value_at_base(h1, atr_sma(h1, 14), nb)
    d1 = build_rung(bt, o, h, l, c, v, "D1", TF_MIN[infer_base_tf(base)])
    h4 = build_rung(bt, o, h, l, c, v, "H4", TF_MIN[infer_base_tf(base)])
    d1_trend = value_at_base(d1, np.sign(d1.c - ema(d1.c, 50)), nb)
    h4_trend = value_at_base(h4, np.sign(h4.c - ema(h4.c, 50)), nb)
    d1_ret5 = value_at_base(d1, np.r_[np.full(5, np.nan), d1.c[5:] - d1.c[:-5]], nb)
    hold_h = hold_h or {"H1": 24, "H4": 96, "D1": 240}[top]
    ok, dirs, st, end, E, S, hold = build_candidates(sig, aux, lvl, depth, sl_ref, sl_buf, atr_b,
                                                     max_age_h, replace, hold_h)
    idx = np.flatnonzero(ok)
    df = sig.df.iloc[idx].reset_index(drop=True)
    res = {}
    for tag, sf, sb, cm in (("net", spread_floor, spread_bps, comm), ("gross", 0.0, 0.0, 0.0)):
        spr = spread_model(c, sf, sb)
        sim = simulate(aux, dirs[idx], st[idx], end[idx], E[idx], S[idx], hold[idx], spr, cm, pessimistic)
        r, win = r_multiples(sim, dirs[idx], E[idx], S[idx], rr, cm)
        res[tag] = r
        res[tag + "_sim"] = sim
    sim = res["net_sim"]
    si = df["sig_idx"].values
    atr = atr_b[si]
    zt, zb = sig.zones_top[idx, 0], sig.zones_bot[idx, 0]
    d = df["dir"].values
    df["R_net"] = res["net"]
    df["R_gross"] = res["gross"]
    df["filled"] = sim["fill"]
    df["fill_delay_h"] = np.where(sim["fill"], (bt[np.maximum(sim["fidx"], 0)] - bt[si]) / 60.0, np.nan)
    df["zone_h_atr"] = (zt - zb) / atr
    df["brk_atr"] = np.where(d == 1, df["px_at_sig"] - zt, zb - df["px_at_sig"]) / atr
    df["risk_atr"] = np.abs(E[idx] - S[idx]) / atr
    df["d1_trend_ok"] = (d1_trend[si] * d) > 0
    df["h4_trend_ok"] = (h4_trend[si] * d) > 0
    df["d1_mom_ok"] = (np.sign(d1_ret5[si]) * d) > 0
    hr = (bt[si] % 1440) // 60
    df["session"] = pd.cut(hr, [-1, 8, 14, 20, 24], labels=["asia(01-08)", "london(09-14)", "ny(15-20)", "late(21-24)"])
    df["is"] = df["sig_time"] < IS_END
    df["year"] = pd.to_datetime(df["sig_time"]).dt.year
    return df


def bucket_report(df: pd.DataFrame, col: str, bins=None, q=None) -> pd.DataFrame:
    x = df[col]
    if bins is not None:
        b = pd.cut(x, bins)
    elif q is not None:
        b = pd.qcut(x, q, duplicates="drop")
    else:
        b = x
    g = df.assign(b=b).dropna(subset=["R_net"]).groupby(["b", "is"], observed=True).agg(
        n=("R_net", "size"), gross=("R_gross", "mean"), net=("R_net", "mean"))
    g = g.unstack("is")
    g.columns = [f"{a}_{'IS' if b else 'OOS'}" for a, b in g.columns]
    return g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="results")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    base = load_bars(args.data)
    configs = [
        ("H1", 0, 0.0, "own", 0.1, 1.5),
        ("H4", 0, 0.0, "own", 0.1, 1.5),
        ("D1", 2, 0.0, "own", 0.1, 1.5),
    ]
    lines = []
    for top, lvl, depth, ref, buf, rr in configs:
        df = trade_table(base, top, lvl, depth, ref, buf, rr)
        df.to_csv(os.path.join(args.out, f"trades_{top}_L{lvl}.csv"), index=False)
        lines.append(f"\n==== top={top} level={lvl} depth={depth} sl={ref}+{buf}ATR rr={rr} ====")
        f = df.dropna(subset=["R_net"])
        lines.append(f"all: IS n={f['is'].sum()} gross={f[f['is']].R_gross.mean():.3f} net={f[f['is']].R_net.mean():.3f} | "
                     f"OOS n={(~f['is']).sum()} gross={f[~f['is']].R_gross.mean():.3f} net={f[~f['is']].R_net.mean():.3f}")
        for col, kw in (("gap_ratio", dict(bins=[0, 0.6, 0.75, 0.9, 1.0])), ("zone_h_atr", dict(q=4)),
                        ("brk_atr", dict(q=4)), ("path", {}), ("session", {}), ("d1_trend_ok", {}),
                        ("h4_trend_ok", {}), ("d1_mom_ok", {}), ("dir", {}), ("fill_delay_h", dict(bins=[-0.1, 1, 3, 8, 24, 1e4]))):
            lines.append(f"-- {col}")
            lines.append(bucket_report(f, col, **kw).round(3).to_string())
    txt = "\n".join(lines)
    open(os.path.join(args.out, "feature_buckets.txt"), "w").write(txt)
    print(txt)


if __name__ == "__main__":
    main()
