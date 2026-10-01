"""
Can money management, an anti-martingale and an hour filter turn the tested strategies
profitable?

For each strategy's trade list (net R per trade, entry time):
  * hour filter chosen ONLY on 2012-2019 (drop entry hours whose average R was negative),
    then applied unchanged to 2020-2025  -> honest
  * the same filter chosen on the whole period                  -> look-ahead (for contrast)
  * sizing: fixed 0.5% risk, or anti-martingale (x1.5 after each win, max 2%, back to 0.5%
    after a loss)
  * daily stop: no new trades once the day's closed loss reaches 2% of the day's start equity
Trades are settled in entry order (an approximation: exits of overlapping trades are not
re-ordered).
"""
import numpy as np
import pandas as pd

from run_study import IS_END, build_candidates
from vgap_engine import (CascadeConfig, atr_sma, generate_signals, load_bars, r_multiples, simulate,
                         spread_model, value_at_base)
import vp_valley
import lvn_clarity


def vgap_trades(base, top, rr):
    sig, aux = generate_signals(base, CascadeConfig(top=top, base_tf="M5"))
    atr_b = value_at_base(aux["rungs"]["H1"], atr_sma(aux["rungs"]["H1"], 14), len(aux["base_t"]))
    hold = {"H1": 24, "H4": 96}[top]
    ok, d, st, end, E, S, hl = build_candidates(sig, aux, 0, 0.0, "own", 0.1, atr_b, None, True, hold)
    i = np.flatnonzero(ok)
    sim = simulate(aux, d[i], st[i], end[i], E[i], S[i], hl[i], spread_model(aux["c"]), 0.07, True)
    r, _ = r_multiples(sim, d[i], E[i], S[i], rr, 0.07)
    f = sim["fill"]
    return pd.DataFrame({"time": pd.to_datetime(aux["base_t"][sim["fidx"][f]] * 60, unit="s"), "R": r[f]})


def valley_trades(base, top, rr):
    df, aux, atr_b = vp_valley.build(base, top)
    bt = aux["base_t"]
    si = df.sig_idx.values
    end = np.minimum(np.searchsorted(bt, bt[si] + 24 * 4 * 60), len(bt)).astype(np.int64)
    E, S, st, ok = vp_valley.model_orders(df, aux, atr_b, "Z", "top", 0.25, end)
    i = np.flatnonzero(ok)
    d = df.dir.values[i].astype(np.int64)
    sim = simulate(aux, d, st[i], end[i], E[i], S[i], np.full(len(i), 96 * 60, dtype=np.int64),
                   spread_model(aux["c"]), 0.07, True)
    r, _ = r_multiples(sim, d, E[i], S[i], rr, 0.07)
    f = sim["fill"]
    return pd.DataFrame({"time": pd.to_datetime(bt[sim["fidx"][f]] * 60, unit="s"), "R": r[f]})


def lvn_trades(base, top, rr):
    df, aux, atr_b = lvn_clarity.build_setups(base, top, 0)
    bt = aux["base_t"]
    si = df.sig_idx.values.astype(np.int64)
    end = np.r_[si[1:], len(bt)].astype(np.int64)
    tb, d = lvn_clarity.find_touch(aux["h"], aux["l"], aux["c"], si, end, df.zt.values, df.zb.values)
    i = np.flatnonzero(tb >= 0)
    dd = d[i]
    zt, zb = df.zt.values[i], df.zb.values[i]
    atr = atr_b[tb[i]]
    E = np.where(dd == 1, zt, zb)
    S = np.where(dd == 1, zb - 0.25 * atr, zt + 0.25 * atr)
    sim = simulate(aux, dd, tb[i], end[i], E, S, np.full(len(i), 96 * 60, dtype=np.int64),
                   spread_model(aux["c"]), 0.07, True)
    r, _ = r_multiples(sim, dd, E, S, rr, 0.07)
    f = sim["fill"]
    return pd.DataFrame({"time": pd.to_datetime(bt[sim["fidx"][f]] * 60, unit="s"), "R": r[f]})


def equity(tr, anti=False, base_risk=0.5, max_risk=2.0, mult=1.5, daily_cap=2.0):
    eq = 100.0
    peak, mdd = eq, 0.0
    risk = base_risk
    day, day_start, skipped = None, eq, 0
    for t, r in zip(tr.time.values, tr.R.values):
        dd_ = pd.Timestamp(t).date()
        if dd_ != day:
            day, day_start = dd_, eq
        if eq <= day_start * (1 - daily_cap / 100):
            skipped += 1
            continue
        eq *= 1 + risk / 100 * r
        if anti:
            risk = min(max_risk, risk * mult) if r > 0 else base_risk
        peak = max(peak, eq)
        mdd = max(mdd, 1 - eq / peak)
    return eq, mdd * 100, skipped


def main(path):
    base = load_bars(path)
    base = base[(base.time >= "2011-06-01") & (base.time < "2025-03-21")].reset_index(drop=True)
    strategies = {
        "Vertical gap H1 (Pine)": vgap_trades(base, "H1", 1.5),
        "Vertical gap H4": vgap_trades(base, "H4", 2.0),
        "Volume valley H4": valley_trades(base, "H4", 2.0),
        "LVN clarity H4": lvn_trades(base, "H4", 2.0),
    }
    rows = []
    for name, tr in strategies.items():
        tr = tr[tr.time >= "2012-01-01"].sort_values("time").reset_index(drop=True)
        tr["hour"] = tr.time.dt.hour
        is_ = tr[tr.time < IS_END]
        oos = tr[tr.time >= IS_END]
        good_is = is_.groupby("hour").R.mean().pipe(lambda s: s[s > 0].index)
        good_all = tr.groupby("hour").R.mean().pipe(lambda s: s[s > 0].index)
        variants = {
            "no filter": oos,
            "hours picked on 2012-19": oos[oos.hour.isin(good_is)],
            "hours picked on all data (look-ahead)": oos[oos.hour.isin(good_all)],
        }
        for vname, sub in variants.items():
            for anti in (False, True):
                eq, mdd, skipped = equity(sub, anti=anti)
                rows.append(dict(strategy=name, hours=vname, sizing="anti-martingale" if anti else "fixed 0.5%",
                                 trades=len(sub), avgR=round(sub.R.mean(), 3) if len(sub) else np.nan,
                                 final_equity_pct=round(eq - 100, 1), maxDD_pct=round(mdd, 1),
                                 skipped_by_daily_cap=skipped,
                                 kept_hours=len(good_is) if "2012" in vname else (len(good_all) if "look" in vname else 24)))
    res = pd.DataFrame(rows)
    res.to_csv("results/money_management_oos_2020_2025.csv", index=False)
    pd.set_option("display.width", 250)
    print(res.to_string(index=False))


if __name__ == "__main__":
    import sys
    main(sys.argv[1])
