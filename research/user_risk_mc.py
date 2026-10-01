"""Monte-Carlo of risk / anti-martingale settings on the user's LiteFinance v1.20 trades,
weighted exactly like the EA (SP2L main 2/3 + add-on 1/3 of the risk; per-setup win streak).
Calibration: the real-order replay of 3% x1.5 cap 8% gives x5.2, the MT5 test gave x5.1."""
import sys
import numpy as np
import pandas as pd
from numba import njit

g = pd.read_csv(sys.argv[1])
R = g.Reff.values
W = (g.R.values > 0).astype(np.int64)
S = (g.setup == "SP2L").values.astype(np.int64)
SF = g.stopfrac.values


@njit(cache=True)
def mc(R, W, S, SF, base, mult, cap, lev, n):
    np.random.seed(3)
    fin = np.empty(n)
    mdd = np.empty(n)
    for k in range(n):
        p = np.random.permutation(len(R))
        bal, peak, m = 1.0, 1.0, 0.0
        st = np.zeros(2, np.int64)
        for i in p:
            rp = min(base * mult ** st[S[i]], cap)
            lim = 0.3 * lev * SF[i] * 100.0          # margin of one trade <= 30% of equity
            if rp > lim:
                rp = lim
            bal *= 1 + rp / 100 * R[i]
            st[S[i]] = st[S[i]] + 1 if W[i] == 1 else 0
            if bal > peak:
                peak = bal
            if 1 - bal / peak > m:
                m = 1 - bal / peak
        fin[k] = bal
        mdd[k] = m
    return fin, mdd


rows = []
for lev in (100, 500):
    for cfg in ((2, 1.5, 5), (3, 1.5, 8), (4, 1.5, 8), (5, 1.5, 8), (5, 1.5, 10), (6, 1.5, 12), (8, 1, 8)):
        f, m = mc(R, W, S, SF, cfg[0], cfg[1], cfg[2], lev, 4000)
        rows.append(dict(lev=lev, cfg=str(cfg), median_x=np.median(f), p10_x=np.percentile(f, 10),
                         p90_x=np.percentile(f, 90), median_DD=np.median(m) * 100, p95_DD=np.percentile(m, 95) * 100,
                         P_DD70=(m > 0.7).mean() * 100, P_loss=(f < 1).mean() * 100))
res = pd.DataFrame(rows).round(1)
res.to_csv("research/results/user_risk_mc.csv", index=False)
print(res.to_string(index=False))
