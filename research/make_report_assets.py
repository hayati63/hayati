"""
Builds the tables and charts used in docs/REPORT_fa.md from the research engine.

    python make_report_assets.py --data <XAUUSD M5 parquet/csv> --grid <dir with grid_*.csv> --out results
"""
from __future__ import annotations

import argparse
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import reaction_entries as rx  # noqa: E402
from run_study import IS_END, build_candidates, metrics  # noqa: E402
from vgap_engine import (infer_base_tf, TF_MIN, CascadeConfig, _scan_reaction, atr_sma, build_rung, generate_signals, load_bars,  # noqa: E402
                         r_multiples, simulate, spread_model, value_at_base)
from walk_forward import walk_forward  # noqa: E402

INK, INK2, MUTED, GRID, BASE, SURF = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]


def limit_trades(base, top, lvl, rr, sl_buf=0.1, study_start="2012-01-01"):
    sig, aux = generate_signals(base, CascadeConfig(top=top, base_tf=infer_base_tf(base)))
    keep = (sig.df["sig_time"] >= pd.Timestamp(study_start)).values
    sig.df = sig.df[keep].reset_index(drop=True)
    sig.zones_top, sig.zones_bot = sig.zones_top[keep], sig.zones_bot[keep]
    bt, o, h, l, c, v = aux["base_t"], aux["o"], aux["h"], aux["l"], aux["c"], aux["v"]
    h1 = aux["rungs"].get("H1") or build_rung(bt, o, h, l, c, v, "H1", TF_MIN[infer_base_tf(base)])
    atr_b = value_at_base(h1, atr_sma(h1, 14), len(bt))
    hold_h = {"H1": 24, "H4": 96, "D1": 240}[top]
    ok, dirs, st, end, E, S, hold = build_candidates(sig, aux, lvl, 0.0, "own", sl_buf, atr_b, None, True, hold_h)
    idx = np.flatnonzero(ok)
    spr = spread_model(c, 0.20, 1.0)
    sim = simulate(aux, dirs[idx], st[idx], end[idx], E[idx], S[idx], hold[idx], spr, 0.07, True)
    r, _ = r_multiples(sim, dirs[idx], E[idx], S[idx], rr, 0.07)
    f = sim["fill"]
    t = pd.to_datetime(bt[sim["fidx"][f]] * 60, unit="s")
    return pd.DataFrame({"time": t, "R": r[f]}).sort_values("time")


def pin_trades(base, top, rr, sl_buf=0.1, study_start="2012-01-01"):
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
    zt, zb = sig.zones_top[:, 0], sig.zones_bot[:, 0]
    end = np.minimum(np.full(len(si), nb, dtype=np.int64), np.r_[si[1:], nb])
    ridx = np.full(len(si), -1, dtype=np.int64)
    _scan_reaction(o, h, l, c, d, si, end, zt, zb, 1, 0.30, ridx)
    idx = np.flatnonzero((ridx >= 0) & (ridx + 1 < nb))
    q = ridx[idx]
    stt = q + 1
    spr = spread_model(c, 0.20, 1.0)
    atr = atr_b[si[idx]]
    E = np.where(d[idx] == 1, o[stt] + spr[stt], o[stt])
    S = np.where(d[idx] == 1, zb[idx] - sl_buf * atr, zt[idx] + sl_buf * atr + spr[q])
    ok = np.where(d[idx] == 1, S < E, S > E) & ~np.isnan(atr)
    idx, stt, E, S = idx[ok], stt[ok], E[ok], S[ok]
    hold = np.full(len(idx), {"H1": 24, "H4": 96, "D1": 240}[top] * 60, dtype=np.int64)
    sim = simulate(aux, d[idx], stt, stt + 1, E, S, hold, spr, 0.07, True, np.ones(len(idx), bool))
    r, _ = r_multiples(sim, d[idx], E, S, rr, 0.07)
    t = pd.to_datetime(bt[stt] * 60, unit="s")
    return pd.DataFrame({"time": t, "R": r}).dropna().sort_values("time")


def style_axes(ax):
    ax.set_facecolor(SURF)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(BASE)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8, linestyle="-")
    ax.set_axisbelow(True)


def equity_chart(curves: dict, path: str, title: str, colors=None):
    colors = colors or SERIES
    fig, ax = plt.subplots(figsize=(10, 5.2), dpi=150)
    fig.patch.set_facecolor(SURF)
    style_axes(ax)
    ax.axhline(0, color=BASE, linewidth=1)
    ax.axvline(IS_END, color=MUTED, linewidth=1)
    ax.text(IS_END, 0.985, "  out-of-sample →", transform=ax.get_xaxis_transform(), color=INK2, fontsize=9, va="top")
    ax.text(IS_END, 0.985, "← in-sample  ", transform=ax.get_xaxis_transform(), color=INK2, fontsize=9, va="top", ha="right")
    ends = []
    for (name, df), col in zip(curves.items(), colors):
        if df.empty:
            continue
        eq = df["R"].cumsum().values
        ax.plot(df["time"].values, eq, color=col, linewidth=2, solid_capstyle="round", solid_joinstyle="round", label=name)
        ax.plot(df["time"].values[-1], eq[-1], "o", color=col, markersize=6, markeredgecolor=SURF, markeredgewidth=2)
        ends.append((eq[-1], name, df["time"].values[-1]))
    for y, name, t in ends:
        ax.annotate(f"{y:+.0f}R", xy=(t, y), xytext=(6, 0), textcoords="offset points", color=INK, fontsize=9, va="center")
    ax.set_ylabel("cumulative net R", color=INK2, fontsize=10)
    ax.set_title(title, color=INK, fontsize=12, loc="left", pad=10)
    leg = ax.legend(loc="lower left", frameon=False, fontsize=9)
    for txt in leg.get_texts():
        txt.set_color(INK)
    ax.margins(x=0.06)
    fig.tight_layout()
    fig.savefig(path, facecolor=SURF)
    plt.close(fig)


def level_chart(tbl: pd.DataFrame, path: str):
    labels = [f"{a} top · {b} zone" for a, b in zip(tbl["top"], tbl["level"])]
    y = np.arange(len(tbl))
    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=150)
    fig.patch.set_facecolor(SURF)
    style_axes(ax)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    hgt = 0.34
    ax.barh(y - hgt / 2 - 0.02, tbl["is_avgR"], height=hgt, color=SERIES[0], label="in-sample 2012–2019")
    ax.barh(y + hgt / 2 + 0.02, tbl["oos_avgR"], height=hgt, color=SERIES[1], label="out-of-sample 2020–2025")
    ax.axvline(0, color=INK2, linewidth=1)
    ax.set_yticks(y, labels, color=INK, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("average net R per trade (limit at zone edge, SL beyond zone + 0.1 ATR, TP 1.5R)", color=INK2, fontsize=9)
    ax.set_title("Limit entries lose after costs at every level; deeper (smaller) zones lose more", color=INK, fontsize=12, loc="left")
    leg = ax.legend(loc="lower left", frameon=False, fontsize=9)
    for txt in leg.get_texts():
        txt.set_color(INK)
    fig.tight_layout()
    fig.savefig(path, facecolor=SURF)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--grid", required=True)
    ap.add_argument("--out", default="results")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    base = load_bars(args.data)

    # ---- grid summaries -------------------------------------------------------------
    net = pd.read_csv(os.path.join(args.grid, "grid_pess.csv"))
    gro = pd.read_csv(os.path.join(args.grid, "grid_pess_nocost.csv"))
    for d in (net, gro):
        d["max_age_h"] = d["max_age_h"].fillna(-1)
    key = ["top", "level", "depth", "sl_ref", "sl_buf", "max_age_h", "replace", "hold_h", "rr"]
    m = net.merge(gro[key + ["is_avgR", "oos_avgR"]], on=key, suffixes=("", "_gross"))
    m = m[~((~m["replace"]) & (m["max_age_h"] == -1))]
    basic = m[(m.depth == 0) & (m.sl_ref == "own") & (m.sl_buf == 0.1) & (m["replace"]) & (m.max_age_h == -1) & (m.rr == 1.5)]
    basic = basic[["top", "level", "fill_rate", "risk_atr_med", "is_n", "is_win", "is_avgR_gross", "is_avgR", "is_pf",
                   "oos_n", "oos_win", "oos_avgR_gross", "oos_avgR", "oos_pf"]].copy()
    order = {"D1": 0, "H4": 1, "H1": 2, "M15": 3, "M5": 4}
    basic["o1"] = basic["top"].map({"H1": 0, "H4": 1, "D1": 2})
    basic["o2"] = basic["level"].map(order)
    basic = basic.sort_values(["o1", "o2"]).drop(columns=["o1", "o2"])
    basic.round(3).to_csv(os.path.join(args.out, "levels_basic_rr1.5.csv"), index=False)
    level_chart(basic.reset_index(drop=True), os.path.join(args.out, "avgR_by_level.png"))

    allcfg = m.groupby(["top", "level"]).agg(configs=("is_avgR", "size"), is_best=("is_avgR", "max"),
                                             is_median=("is_avgR", "median"), oos_best=("oos_avgR", "max"),
                                             oos_median=("oos_avgR", "median"),
                                             gross_is_median=("is_avgR_gross", "median"),
                                             gross_oos_median=("oos_avgR_gross", "median")).reset_index()
    both = m[(m.is_avgR > 0) & (m.oos_avgR > 0)].groupby(["top", "level"]).size().rename("positive_IS_and_OOS")
    allcfg = allcfg.merge(both, on=["top", "level"], how="left").fillna({"positive_IS_and_OOS": 0})
    allcfg.round(3).to_csv(os.path.join(args.out, "grid_overview.csv"), index=False)

    novol_path = os.path.join(args.grid, "grid_pess_novol.csv")
    if os.path.exists(novol_path):
        nv = pd.read_csv(novol_path)
        nv["max_age_h"] = nv["max_age_h"].fillna(-1)
        nv = nv[~((~nv["replace"]) & (nv["max_age_h"] == -1))]
        cmp_ = gro[~((~gro["replace"]) & (gro["max_age_h"] == -1))].merge(nv[key + ["is_avgR", "oos_avgR"]], on=key,
                                                                          suffixes=("_volgap", "_anycandle"))
        cmp_.groupby(["top", "level"])[["is_avgR_volgap", "is_avgR_anycandle", "oos_avgR_volgap", "oos_avgR_anycandle"]] \
            .median().round(3).reset_index().to_csv(os.path.join(args.out, "control_volume_vs_anycandle_gross.csv"), index=False)

    # ---- walk-forward -----------------------------------------------------------------
    yg_path = os.path.join(args.grid, "yearly_grid.parquet")
    if os.path.exists(yg_path):
        yg = pd.read_parquet(yg_path)
        rows = []
        for top in ("H1", "H4", "D1"):
            w = walk_forward(yg[yg.top == top], train_years=4, first_test=2016, last_test=2025,
                             min_trades_per_year={"H1": 20, "H4": 8, "D1": 4}[top], top_k=1)
            w.insert(0, "top", top)
            rows.append(w)
        wf = pd.concat(rows, ignore_index=True)
        wf.round(3).to_csv(os.path.join(args.out, "walk_forward.csv"), index=False)

    # ---- equity curves ---------------------------------------------------------------
    curves = {
        "H1 box, limit at edge, TP 1.5R (Pine default)": limit_trades(base, "H1", 0, 1.5),
        "H1 top → M5 zone, limit, TP 1.5R": limit_trades(base, "H1", 2, 1.5),
        "H4 box, limit at edge, TP 2R": limit_trades(base, "H4", 0, 2.0),
        "H4 box, pin bar near box, TP 2.5R (EA default)": pin_trades(base, "H4", 2.5),
    }
    summ = []
    for name, df in curves.items():
        ism = df["time"] < IS_END
        yrs_is = (IS_END - pd.Timestamp("2012-01-01")).days / 365.25
        yrs_oos = (df["time"].max() - IS_END).days / 365.25
        mi, mo = metrics(df["R"].values[ism.values], years=yrs_is), metrics(df["R"].values[~ism.values], years=yrs_oos)
        summ.append(dict(config=name, **{f"is_{k}": v for k, v in mi.items()}, **{f"oos_{k}": v for k, v in mo.items()}))
    pd.DataFrame(summ).round(3).to_csv(os.path.join(args.out, "equity_configs_summary.csv"), index=False)
    equity_chart(curves, os.path.join(args.out, "equity_curves.png"),
                 "Cumulative net R per configuration (XAUUSD 2012–2025, costs included)")
    h4 = {k: v for k, v in curves.items() if k.startswith("H4")}
    equity_chart(h4, os.path.join(args.out, "equity_curves_h4.png"),
                 "Zoom: the two H4 configurations (near break-even, not a proven edge)", colors=SERIES[2:4])
    print(pd.DataFrame(summ).round(3).to_string(index=False))


if __name__ == "__main__":
    main()
