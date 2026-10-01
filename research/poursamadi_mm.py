"""
Improvements for the two Poursamadi setups that held up out of sample
(SP2L H1 and Pro BTB M15), all chosen on 2012-2019 only and then checked on 2020-2025:

1. trade management: TP / half-close variants x break-even move (stop to entry after +1R..2R)
2. money management on the combined portfolio (both setups on one account):
   fixed risk, anti-martingale (risk x mult after each closed win, back to base after a
   loss, capped), drawdown throttle (half risk while equity is > X% below its peak) and a
   2% daily loss cap.  Trades are processed in time order; the risk of a new trade only uses
   trades already closed at its entry, and P&L is booked at the exit time.

    python poursamadi_mm.py <XAUUSD M5 parquet>
"""
import itertools
import sys

import numpy as np
import pandas as pd

from poursamadi import trade_list
from run_study import IS_END
from vgap_engine import load_bars

SETUPS = {
    "SP2L": dict(tf="H1", strategy="SP2L", ns=3, m=1.0, entry="main+50%", filt="trend"),
    # one trade per breakout candle, only when it closes through >= 2 unbroken previous-day highs/lows
    "BTB": dict(tf="M15", strategy="BTB", lvl="prevday", strong=1, mode=3, min_lv=2, filt="window"),
}


def trades(base, name, mgmt, be_r):
    c = dict(SETUPS[name])
    filt = c.pop("filt")
    tl = trade_list(base, mgmt=mgmt, be_r=be_r, **c)
    tl = tl[tl.window] if filt == "window" else tl[tl.trend_ok]
    tl = tl.assign(setup=name)
    return tl[["setup", "time", "exit_time", "dir", "R"]].reset_index(drop=True)


def stats(r):
    r = np.asarray(r)
    if len(r) < 2:
        return np.nan, np.nan
    return r.mean(), r.mean() / r.std(ddof=1) * np.sqrt(len(r))


def simulate_equity(tl, base=0.5, mult=1.0, cap=None, dd_throttle=None, daily_cap=None, per_setup=False):
    """Event-driven equity in % of the starting balance (compounded)."""
    cap = cap if cap is not None else base
    ev = []
    for i, r in tl.iterrows():
        ev.append((r.time, 1, i))       # open
        ev.append((r.exit_time, 0, i))  # close (closes sort before opens at the same time)
    ev.sort(key=lambda e: (e[0], e[1]))
    eq, peak, mdd = 100.0, 100.0, 0.0
    streak = {k: 0 for k in tl.setup.unique()} if per_setup else {"all": 0}
    risk_of = {}
    day, day_start = None, eq
    skipped = 0
    for t, kind, i in ev:
        key = tl.setup.iat[i] if per_setup else "all"
        if kind == 1:
            d = pd.Timestamp(t).date()
            if d != day:
                day, day_start = d, eq
            if daily_cap is not None and eq <= day_start * (1 - daily_cap / 100):
                skipped += 1
                continue
            risk = min(cap, base * mult ** streak[key])
            if dd_throttle is not None and eq < peak * (1 - dd_throttle / 100):
                risk *= 0.5
            risk_of[i] = risk * eq / 100.0        # money at risk
        elif i in risk_of:
            rr = tl.R.iat[i]
            eq += risk_of.pop(i) * rr
            streak[key] = streak[key] + 1 if rr > 0 else 0
            peak = max(peak, eq)
            mdd = max(mdd, 1 - eq / peak)
    return eq - 100.0, mdd * 100.0, skipped


def main(path):
    base = load_bars(path)
    base = base[(base.time >= "2011-06-01") & (base.time < "2025-03-21")].reset_index(drop=True)
    pd.set_option("display.width", 220)

    # ---- 1) trade management ----
    rows, cache = [], {}
    for name in SETUPS:
        for mgmt, be in itertools.product(("RR2", "RR3", "HC2-4", "HC3-6"), (0.0, 1.0, 1.5, 2.0)):
            tl = trades(base, name, mgmt, be)
            cache[(name, mgmt, be)] = tl
            isr, oos = tl[tl.time < IS_END].R, tl[tl.time >= IS_END].R
            (mi, ti), (mo, to) = stats(isr), stats(oos)
            rows.append(dict(setup=name, mgmt=mgmt, be_at_R=be, is_n=len(isr), is_avgR=mi, is_t=ti,
                             oos_n=len(oos), oos_avgR=mo, oos_t=to))
    mg = pd.DataFrame(rows).round(3)
    mg.to_csv("results/poursamadi_management.csv", index=False)
    print(mg.to_string(index=False))
    # the IS t-stats of the management variants are within noise of each other, so the portfolio
    # uses one fixed, simple choice for both setups: TP 3R, no break-even
    best = {}
    for name in SETUPS:
        sub = mg[mg.setup == name].sort_values("is_t", ascending=False)
        print(f"\nbest on 2012-2019 for {name}: {sub.iloc[0].mgmt} BE={sub.iloc[0].be_at_R} "
              f"-> OOS {sub.iloc[0].oos_avgR:+.3f}R (t={sub.iloc[0].oos_t})")
        best[name] = mg[(mg.setup == name) & (mg.mgmt == "RR3") & (mg.be_at_R == 0.0)].iloc[0]

    # ---- serial dependence (does a win make the next win more likely?) ----
    for name in SETUPS:
        b = best[name]
        r = cache[(name, b.mgmt, b.be_at_R)].R.values
        w = r > 0
        print(f"{name}: P(win)={w.mean():.3f}  P(win | previous win)={w[1:][w[:-1]].mean():.3f}  "
              f"P(win | previous loss)={w[1:][~w[:-1]].mean():.3f}")

    # ---- 2) money management on the combined portfolio ----
    port = pd.concat([cache[(n, best[n].mgmt, best[n].be_at_R)] for n in SETUPS], ignore_index=True)
    port = port.sort_values("time").reset_index(drop=True)
    variants = {"fixed 0.5%": dict(base=0.5), "fixed 0.75%": dict(base=0.75), "fixed 1%": dict(base=1.0)}
    for mult, cap in itertools.product((1.5, 2.0), (1.0, 1.5, 2.0)):
        variants[f"anti-martingale x{mult} cap {cap}%"] = dict(base=0.5, mult=mult, cap=cap)
        variants[f"anti-martingale per setup x{mult} cap {cap}%"] = dict(base=0.5, mult=mult, cap=cap, per_setup=True)
    for th in (3.0, 5.0):
        variants[f"fixed 0.75% + half risk in DD>{th}%"] = dict(base=0.75, dd_throttle=th)
        variants[f"anti-martingale x1.5 cap 1.5% + half risk in DD>{th}%"] = dict(base=0.5, mult=1.5, cap=1.5,
                                                                                  dd_throttle=th)
    variants["fixed 0.75% + 2% daily cap"] = dict(base=0.75, daily_cap=2.0)
    rows = []
    for vname, kw in variants.items():
        for period, sub in (("2012-2019", port[port.time < IS_END]), ("2020-2025", port[port.time >= IS_END])):
            ret, mdd, sk = simulate_equity(sub.reset_index(drop=True), **kw)
            yrs = (sub.time.max() - sub.time.min()).days / 365.25
            cagr = ((1 + ret / 100) ** (1 / yrs) - 1) * 100
            rows.append(dict(sizing=vname, period=period, trades=len(sub), return_pct=round(ret, 1),
                             CAGR_pct=round(cagr, 1), maxDD_pct=round(mdd, 1), CAGR_over_DD=round(cagr / mdd, 2),
                             skipped=sk))
    mm = pd.DataFrame(rows)
    mm.to_csv("results/poursamadi_money_management.csv", index=False)
    piv = mm.pivot(index="sizing", columns="period", values=["CAGR_pct", "maxDD_pct", "CAGR_over_DD"])
    print("\n", piv.sort_values(("CAGR_over_DD", "2012-2019"), ascending=False).to_string())


if __name__ == "__main__":
    main(sys.argv[1])
