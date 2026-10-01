"""Risk / anti-martingale grid on the user's LiteFinance v1.20 trades (SP2L add-ons merged into
their main trade).  Monte-Carlo over trade order; margin limit: one trade's margin may use at
most `mfrac` of equity at the given leverage (risk is cut for tight stops)."""
import sys
import numpy as np
import pandas as pd
from numba import njit

T = pd.read_csv(sys.argv[1], parse_dates=["t", "out"])
R = T.R.values.astype(np.float64)
SF = T.stopfrac.values.astype(np.float64)


@njit(cache=True)
def run_all(R, SF, base, mult, cap, lev, mfrac, n, seed):
    np.random.seed(seed)
    fin = np.empty(n)
    mdd = np.empty(n)
    for k in range(n):
        p = np.random.permutation(len(R))
        bal, peak, m, s = 1.0, 1.0, 0.0, 0
        for i in p:
            rp = base * mult ** s
            if rp > cap:
                rp = cap
            lim = mfrac * lev * SF[i] * 100.0          # max risk % allowed by margin
            if rp > lim:
                rp = lim
            bal *= 1.0 + rp / 100.0 * R[i]
            s = s + 1 if R[i] > 0 else 0
            if bal > peak:
                peak = bal
            dd = 1.0 - bal / peak
            if dd > m:
                m = dd
        fin[k] = bal
        mdd[k] = m
    return fin, mdd


rows = []
for lev in (100, 500, 1000):
    for base in (2.0, 3.0, 4.0, 5.0, 6.0, 8.0):
        for mult in (1.0, 1.25, 1.5, 2.0):
            for cap in (base, 1.5 * base, 2 * base, 3 * base):
                if mult == 1.0 and cap != base:
                    continue
                if mult > 1.0 and cap == base:
                    continue
                fin, mdd = run_all(R, SF, base, mult, cap, lev, 0.3, 3000, 7)
                rows.append(dict(leverage=lev, base=base, mult=mult, cap=cap,
                                 median_x=np.median(fin), p10_x=np.percentile(fin, 10), p90_x=np.percentile(fin, 90),
                                 median_dd=np.median(mdd) * 100, p95_dd=np.percentile(mdd, 95) * 100,
                                 p_dd80=(mdd > 0.8).mean() * 100, p_loss=(fin < 1).mean() * 100))
res = pd.DataFrame(rows).round(2)
res.to_csv("research/results/user_risk_grid.csv", index=False)
pd.set_option("display.width", 220)
pd.set_option("display.max_rows", 300)
for lev in (100, 500, 1000):
    x = res[res.leverage == lev]
    safe = x[(x.p_dd80 < 1) & (x.p_loss < 1)].sort_values("median_x", ascending=False)
    print(f"\n=== leverage 1:{lev}: best 'safe' settings (P(drawdown>80%)<1%, P(end below start)<1%)")
    print(safe.head(8).to_string(index=False))
    print("aggressive (beyond safe):")
    print(x.sort_values("median_x", ascending=False).head(4).to_string(index=False))
