"""Download Dukascopy tick history and turn it into M1 bars.

Writes the same CSV layout as MQL5/Scripts/Hayati/ExportM1.mq5, so every
other tool here reads it unchanged. Needs datafeed.dukascopy.com reachable
from the environment.

    python3 tools/fetch_dukascopy.py --symbol XAUUSD --from 2021-01-01 \
        --to 2025-01-01 --out xauusd_m1.csv.gz

Bars are built from the BID, as MetaTrader charts are. tick_volume is the
number of ticks in the minute, real_volume is Dukascopy's own traded volume,
spread is the median ask-bid in points.

Day boundaries: forex daily candles close at 17:00 New York, which is what a
GMT+2/+3 MetaTrader broker and TradingView both show. Dukascopy stamps ticks
in UTC, so by default times are shifted to that broker clock (UTC+2 in winter,
UTC+3 while US daylight saving is on) - otherwise every Daily and Weekly
profile would be cut at the wrong hour. --utc keeps plain UTC.
"""

from __future__ import annotations

import argparse
import datetime as dt
import lzma
import struct
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

URL = "https://datafeed.dukascopy.com/datafeed/{sym}/{y:04d}/{m0:02d}/{d:02d}/{h:02d}h_ticks.bi5"
RECORD = struct.Struct(">3I2f")          # ms offset, ask, bid, ask volume, bid volume

# Dukascopy stores prices as integers; this is the divisor per instrument
SCALE = {"XAUUSD": 1e3, "XAGUSD": 1e3, "USDJPY": 1e3, "EURJPY": 1e3, "GBPJPY": 1e3}
DEFAULT_SCALE = 1e5


def decode_hour(raw: bytes, hour_start: dt.datetime, scale: float) -> np.ndarray:
    """Decompress one .bi5 file into rows of (epoch_ms, bid, ask, volume)."""
    if not raw:
        return np.empty((0, 4))
    data = lzma.decompress(raw)
    n = len(data) // RECORD.size
    if n == 0:
        return np.empty((0, 4))
    arr = np.frombuffer(data[:n * RECORD.size],
                        dtype=np.dtype([("ms", ">u4"), ("ask", ">u4"), ("bid", ">u4"),
                                        ("av", ">f4"), ("bv", ">f4")]))
    base = int(hour_start.replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    out = np.empty((n, 4))
    out[:, 0] = base + arr["ms"].astype(np.int64)
    out[:, 1] = arr["bid"] / scale
    out[:, 2] = arr["ask"] / scale
    out[:, 3] = arr["av"].astype(float) + arr["bv"].astype(float)
    return out


def fetch_hour(sym: str, t: dt.datetime, scale: float, retries: int = 4) -> np.ndarray:
    url = URL.format(sym=sym, y=t.year, m0=t.month - 1, d=t.day, h=t.hour)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return decode_hour(r.read(), t, scale)
        except urllib.error.HTTPError as e:
            if e.code == 404:                        # market closed that hour
                return np.empty((0, 4))
            err = e
        except (urllib.error.URLError, TimeoutError, lzma.LZMAError) as e:
            err = e
        time.sleep(2 ** attempt)
    raise RuntimeError(f"{url}: {err}")


def ny_close_shift(utc_ms: np.ndarray) -> np.ndarray:
    """Seconds to add so midnight lands on 17:00 New York (GMT+2/+3 broker)."""
    t = pd.DatetimeIndex(pd.to_datetime(utc_ms, unit="ms", utc=True))
    ny_offset = (t.tz_convert("America/New_York").tz_localize(None)
                 - t.tz_localize(None)).total_seconds().to_numpy()
    return np.where(ny_offset == -4 * 3600, 3 * 3600, 2 * 3600)   # EDT -> +3, EST -> +2


def ticks_to_m1(ticks: np.ndarray, point: float, utc: bool) -> pd.DataFrame:
    if len(ticks) == 0:
        return pd.DataFrame()
    ms = ticks[:, 0].astype(np.int64)
    shift = 0 if utc else ny_close_shift(ms)
    sec = ms // 1000 + shift
    minute = sec // 60 * 60

    df = pd.DataFrame({"m": minute, "bid": ticks[:, 1], "ask": ticks[:, 2],
                       "vol": ticks[:, 3]})
    df["spr"] = (df["ask"] - df["bid"]) / point
    g = df.groupby("m", sort=True)
    out = pd.DataFrame({
        "open": g["bid"].first(), "high": g["bid"].max(),
        "low": g["bid"].min(), "close": g["bid"].last(),
        "tick_volume": g["bid"].size(),
        "real_volume": g["vol"].sum().round(2),
        "spread": g["spr"].median().round().astype(int),
    })
    out.index = pd.to_datetime(out.index, unit="s").strftime("%Y.%m.%d %H:%M:%S")
    out.index.name = "time"
    return out.reset_index()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--from", dest="start", required=True)
    ap.add_argument("--to", dest="end", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--utc", action="store_true", help="keep UTC instead of broker time")
    a = ap.parse_args()

    sym = a.symbol.upper()
    scale = SCALE.get(sym, DEFAULT_SCALE)
    point = 1.0 / scale
    t0 = dt.datetime.fromisoformat(a.start)
    t1 = dt.datetime.fromisoformat(a.end)
    hours = []
    t = t0
    while t < t1:
        if t.weekday() != 5:                         # Saturday is always empty
            hours.append(t)
        t += dt.timedelta(hours=1)

    print(f"{sym}: {len(hours):,} hourly files, {a.workers} workers", file=sys.stderr)
    frames = []
    done = 0
    with ThreadPoolExecutor(a.workers) as pool:
        for chunk in (hours[i:i + 24 * 30] for i in range(0, len(hours), 24 * 30)):
            parts = list(pool.map(lambda h: fetch_hour(sym, h, scale), chunk))
            ticks = np.concatenate([p for p in parts if len(p)]) if any(len(p) for p in parts) \
                else np.empty((0, 4))
            frames.append(ticks_to_m1(ticks, point, a.utc))
            done += len(chunk)
            print(f"  {chunk[-1]:%Y-%m-%d}  {done:,}/{len(hours):,}", file=sys.stderr)

    m1 = pd.concat([f for f in frames if len(f)], ignore_index=True)
    m1 = m1.drop_duplicates("time").sort_values("time")
    m1.to_csv(a.out, index=False)
    print(f"wrote {len(m1):,} M1 bars to {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
