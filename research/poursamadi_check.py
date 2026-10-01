"""Robustness checks for the best Poursamadi configurations: per-year R, cost stress,
parameter neighbours, and a simple equity curve at 0.5% risk."""
import sys

import numpy as np
import pandas as pd

from poursamadi import trade_list
from run_study import IS_END
from vgap_engine import load_bars


def summary(tl, label):
    r = tl.R.values
    t = r.mean() / r.std(ddof=1) * np.sqrt(len(r)) if len(r) > 1 else np.nan
    isr, oos = tl[tl.time < IS_END].R, tl[tl.time >= IS_END].R
    return dict(config=label, n=len(r), avgR=round(r.mean(), 3), t=round(t, 2), is_avgR=round(isr.mean(), 3),
                oos_avgR=round(oos.mean(), 3), win=round((r > 0).mean(), 3))


def main(path):
    base = load_bars(path)
    base = base[(base.time >= "2011-06-01") & (base.time < "2025-03-21")].reset_index(drop=True)
    cands = {
        "SP2L H1 ns3 m1 +50% RR2 trend": dict(tf="H1", strategy="SP2L", ns=3, m=1.0, entry="main+50%", mgmt="RR2", filt="trend"),
        "SP2L H1 ns3 m1 +50% HC3-6 trend": dict(tf="H1", strategy="SP2L", ns=3, m=1.0, entry="main+50%", mgmt="HC3-6", filt="trend"),
        "BTB M15 prevday strong E3 RR3 window": dict(tf="M15", strategy="BTB", lvl="prevday", strong=1, mode=3, mgmt="RR3", filt="window"),
        "BTB M15 prevday strong E2 RR2 window": dict(tf="M15", strategy="BTB", lvl="prevday", strong=1, mode=2, mgmt="RR2", filt="window"),
    }
    rows, years = [], {}
    for name, c in cands.items():
        filt = c.pop("filt")
        for label, kw in (("net", {}), ("gross", {"gross": True}), ("net x1.5 cost", {"cost_mult": 1.5}),
                          ("net x2 cost", {"cost_mult": 2.0})):
            tl = trade_list(base, **c, **kw)
            if "window" in filt:
                tl = tl[tl.window]
            if "trend" in filt:
                tl = tl[tl.trend_ok]
            rows.append(summary(tl, f"{name} | {label}"))
            if label == "net":
                years[name] = tl.groupby(tl.time.dt.year).R.agg(["count", "mean", "sum"]).round(2)
                tl[["time", "dir", "R"]].to_csv(f"results/poursamadi_trades_{name.replace(' ', '_')}.csv", index=False)
        c["filt"] = filt
    # neighbours
    for tf in ("M5", "M15", "H1"):
        for ns, m in ((2, 1.0), (2, 2.0), (3, 1.0), (3, 2.0)):
            tl = trade_list(base, tf, "SP2L", ns=ns, m=m, entry="main+50%", mgmt="RR2")
            rows.append(summary(tl[tl.trend_ok], f"SP2L {tf} ns{ns} m{m} +50% RR2 trend | net"))
        for strong in (0, 1):
            for mode in (2, 3):
                tl = trade_list(base, tf, "BTB", lvl="prevday", strong=strong, mode=mode, mgmt="RR3")
                rows.append(summary(tl[tl.window], f"BTB {tf} prevday strong{strong} E{mode} RR3 window | net"))
    res = pd.DataFrame(rows)
    res.to_csv("results/poursamadi_checks.csv", index=False)
    pd.set_option("display.width", 200)
    print(res.to_string(index=False))
    for k, v in years.items():
        print("\n", k)
        print(v.T.to_string())


if __name__ == "__main__":
    main(sys.argv[1])
