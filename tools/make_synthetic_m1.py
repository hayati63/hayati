"""Generate synthetic M1 bars in the ExportM1.mq5 CSV format.

This is NOT market data and no trading conclusion can be drawn from it. It
exists so the backtest and the optimiser can be exercised end to end before
real broker data arrives — and, more usefully, as a control: an optimiser that
finds a profitable edge in a random walk is broken, and this is how you catch
that.

    python3 tools/make_synthetic_m1.py --out /tmp/synthetic_m1.csv --years 2
"""

import argparse
import numpy as np
import pandas as pd


def generate(years: float, seed: int, start_price: float, tick: float,
             spread_points: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    days = int(260 * years)
    minutes_per_day = 1440
    n = days * minutes_per_day

    # timestamps: weekdays only, one continuous minute grid per day
    base = pd.Timestamp("2023-01-02 00:00:00")
    stamps = []
    d = base
    added = 0
    while added < days:
        if d.weekday() < 5:
            stamps.append(pd.date_range(d, periods=minutes_per_day, freq="1min"))
            added += 1
        d += pd.Timedelta(days=1)
    times = pd.DatetimeIndex(np.concatenate([s.values for s in stamps]))

    # intraday volatility and volume seasonality, so local minima in volume
    # exist for the cascade to find
    minute_of_day = times.hour * 60 + times.minute
    season = 0.4 + 1.6 * np.exp(-((minute_of_day - 810) ** 2) / (2 * 220 ** 2)) \
                 + 1.1 * np.exp(-((minute_of_day - 450) ** 2) / (2 * 150 ** 2))

    steps = rng.standard_normal(n) * tick * 9.0 * season
    close = start_price + np.cumsum(steps)
    open_ = np.concatenate(([start_price], close[:-1]))

    wick = np.abs(rng.standard_normal(n)) * tick * 6.0 * season
    high = np.maximum(open_, close) + wick
    low = np.minimum(open_, close) - np.abs(rng.standard_normal(n)) * tick * 6.0 * season

    vol = np.maximum(1, rng.poisson(np.maximum(1.0, 60 * season))).astype(int)

    dec = max(0, int(round(-np.log10(tick))))
    return pd.DataFrame({
        "time": times.strftime("%Y.%m.%d %H:%M:%S"),
        "open": np.round(open_, dec),
        "high": np.round(high, dec),
        "low": np.round(low, dec),
        "close": np.round(close, dec),
        "tick_volume": vol,
        "real_volume": 0,
        "spread": spread_points,
    })


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--years", type=float, default=2.0)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--price", type=float, default=2000.0)
    ap.add_argument("--tick", type=float, default=0.01)
    ap.add_argument("--spread", type=int, default=20)
    a = ap.parse_args()

    df = generate(a.years, a.seed, a.price, a.tick, a.spread)
    df.to_csv(a.out, index=False)
    print(f"wrote {len(df):,} synthetic M1 bars to {a.out}")
    print("reminder: random walk, no edge exists in it by construction")


if __name__ == "__main__":
    main()
