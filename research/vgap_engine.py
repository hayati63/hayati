"""
Vertical Volume Gap Cascade — research engine (Python port of the Pine v3 logic).

Faithful, causal re-implementation of "XAUUSD Vertical Volume Gap Cascade — v3":

  * top-stage trigger: on the close of top-TF bar c, bar c-1 is a "volume gap" when
    vol[c-1] < vol[c-2] and vol[c-1] < vol[c]; the zone is bar c-1's high/low.
  * bias: close[c] above the zone -> BUY, below -> SELL, inside -> wait for up to
    N closes of the next-lower TF (M15 for an H1 top); first close outside fixes the bias.
  * session-hour exclusion (H1 top only): gap candles that open 23:30 / 00:30 Tehran.
  * cascade: inside the gap bar's time window look one TF lower for bars that are local
    volume minima (v[i] < v[i-1] and v[i] < v[i+1]); the deepest (lowest volume) wins and
    becomes the new window/zone; if none, the level is "gray" and the window is kept.
  * every found level is an independent entry zone (box) that stays armed until touched.

The engine works with any base resolution (M1 or M5).  With M5 base data the final M1
stage cannot be computed and is skipped.

Trade simulation (numba) models MT5 execution on bid bars:
  BUY  limit at E (ask)  fills when bid_low  <= E - spread
  SELL limit at E (bid)  fills when bid_high >= E
  BUY  SL/TP trigger on bid, SELL SL/TP trigger on ask (= bid + spread)
Intrabar order is either pessimistic (SL first on any ambiguous bar) or the usual OHLC
path heuristic (bullish bar: O-L-H-C, bearish bar: O-H-L-C).
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from numba import njit

TF_MIN = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}
TF_ORDER = ["D1", "H4", "H1", "M15", "M5", "M1"]


# --------------------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------------------
def load_bars(path: str) -> pd.DataFrame:
    """Load OHLC + tick volume bars (server time).  Accepts parquet, the CSV written by
    ExportBarsCSV.mq5 (time,open,high,low,close,tick_volume,spread) or MT5's own
    History-Center export (<DATE> <TIME> <OPEN> ... <TICKVOL> <VOL> <SPREAD>)."""
    if path.endswith(".parquet"):
        df = pd.read_parquet(path)
    else:
        with open(path, "r", encoding="utf-8-sig", errors="ignore") as fh:
            head = fh.readline()
        if "<DATE>" in head:
            df = pd.read_csv(path, sep="\t")
            df.columns = [c.strip("<>").lower() for c in df.columns]
            df["time"] = pd.to_datetime(df["date"] + " " + df["time"], format="%Y.%m.%d %H:%M:%S")
            df = df.rename(columns={"tickvol": "volume"})
        else:
            df = pd.read_csv(path)
            df.columns = [c.strip().lower() for c in df.columns]
            if "tick_volume" in df.columns:
                df = df.rename(columns={"tick_volume": "volume"})
            df["time"] = pd.to_datetime(df["time"].astype(str).str.replace(".", "-", n=2, regex=False))
    df["time"] = pd.to_datetime(df["time"])
    cols = ["time", "open", "high", "low", "close", "volume"] + (["spread"] if "spread" in df.columns else [])
    df = df[cols].sort_values("time").drop_duplicates("time").reset_index(drop=True)
    return df


def infer_base_tf(df: pd.DataFrame) -> str:
    """Base resolution of the loaded bars ("M1" or "M5"), from the most common bar spacing."""
    step = int(pd.Series(df["time"].values[:5000]).diff().dt.total_seconds().div(60).mode().iloc[0])
    for name, m in TF_MIN.items():
        if m == step:
            return name
    raise ValueError(f"unsupported base bar spacing: {step} minutes (use M1 or M5 data)")


def to_minutes(ts: pd.Series) -> np.ndarray:
    return (ts.values.astype("datetime64[m]").astype(np.int64)).astype(np.int64)


# --------------------------------------------------------------------------------------
# Multi-timeframe "rungs"
# --------------------------------------------------------------------------------------
@dataclass
class Rung:
    tf: str
    t: np.ndarray      # open time (minutes since epoch, server time)
    tc: np.ndarray     # close time  = t + tf length
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray
    avail: np.ndarray  # first base-bar index at which this bar is complete/known


def build_rung(base_t: np.ndarray, o, h, l, c, v, tf: str, base_tf_min: int) -> Rung:
    m = TF_MIN[tf]
    if m == base_tf_min:
        t = base_t.copy()
        avail = np.arange(1, len(t) + 1, dtype=np.int64)
        return Rung(tf, t, t + m, o.copy(), h.copy(), l.copy(), c.copy(), v.copy(), avail)
    bucket = (base_t // m) * m
    # boundaries where bucket changes
    starts = np.flatnonzero(np.r_[True, bucket[1:] != bucket[:-1]])
    ends = np.r_[starts[1:], len(base_t)] - 1
    t = bucket[starts]
    ro = o[starts]
    rc = c[ends]
    rh = np.maximum.reduceat(h, starts)
    rl = np.minimum.reduceat(l, starts)
    rv = np.add.reduceat(v, starts)
    tc = t + m
    avail = np.searchsorted(base_t, tc, side="left").astype(np.int64)
    return Rung(tf, t, tc, ro, rh, rl, rc, rv, avail)


def atr_sma(r: Rung, n: int = 14) -> np.ndarray:
    """MT5 iATR = simple moving average of true range."""
    prev_c = np.r_[r.c[0], r.c[:-1]]
    tr = np.maximum(r.h - r.l, np.maximum(np.abs(r.h - prev_c), np.abs(r.l - prev_c)))
    s = pd.Series(tr).rolling(n, min_periods=n).mean().values
    return s


def value_at_base(r: Rung, values: np.ndarray, nbase: int) -> np.ndarray:
    """For every base index i, the value of the last rung bar completed at or before i."""
    out = np.full(nbase, np.nan)
    # rung bar k becomes known at base index avail[k]
    idx = np.searchsorted(r.avail, np.arange(nbase), side="right") - 1
    ok = idx >= 0
    out[ok] = values[idx[ok]]
    return out


# --------------------------------------------------------------------------------------
# Time zones (server time = New York + 7h, i.e. GMT+2 winter / GMT+3 US-summer)
# --------------------------------------------------------------------------------------
def _us_dst(d: _dt.date) -> bool:
    y = d.year
    march = _dt.date(y, 3, 1)
    second_sun_march = march + _dt.timedelta(days=(6 - march.weekday()) % 7 + 7)
    nov = _dt.date(y, 11, 1)
    first_sun_nov = nov + _dt.timedelta(days=(6 - nov.weekday()) % 7)
    return second_sun_march <= d < first_sun_nov


def server_to_utc_minutes(t_min: np.ndarray, winter_off: int = 2, summer_off: int = 3) -> np.ndarray:
    days = (t_min // 1440)
    uniq = np.unique(days)
    offs = {}
    for d in uniq:
        date = _dt.date(1970, 1, 1) + _dt.timedelta(days=int(d))
        offs[d] = summer_off if _us_dst(date) else winter_off
    off = np.array([offs[d] for d in days], dtype=np.int64)
    return t_min - off * 60


# --------------------------------------------------------------------------------------
# Signal generation (the cascade)
# --------------------------------------------------------------------------------------
@dataclass
class CascadeConfig:
    top: str = "H1"
    base_tf: str = "M5"
    wait_n: int = 4                  # closes of the next-lower TF to wait when confirm closes inside
    exclusion: str = "tehran"        # "tehran" | "none" | "server"
    tehran_hhmm: tuple = ((23, 30), (0, 30))
    tehran_offset_min: int = 210     # UTC+3:30
    server_hours: tuple = (22, 23, 0, 1)
    server_winter_off: int = 2
    server_summer_off: int = 3
    require_volume_gap: bool = True  # False = control experiment: any bar is a "zone"


@dataclass
class Signals:
    levels: list                      # e.g. ["H1","M15","M5"] (+"M1")
    df: pd.DataFrame                  # one row per signal
    zones_top: np.ndarray             # [nsig, nlev]  (nan when the level has no gap)
    zones_bot: np.ndarray
    stats: dict = field(default_factory=dict)


def _local_min_deepest(v: np.ndarray, lo: int, hi: int) -> int:
    best = -1
    bestv = 1e300
    for i in range(lo, hi + 1):
        v0 = v[i]
        if v0 < v[i - 1] and v0 < v[i + 1] and v0 < bestv:
            bestv = v0
            best = i
    return best


def generate_signals(base: pd.DataFrame, cfg: CascadeConfig) -> tuple[Signals, dict]:
    base_tf_min = TF_MIN[cfg.base_tf]
    bt = to_minutes(base["time"])
    o = base["open"].values.astype(np.float64)
    h = base["high"].values.astype(np.float64)
    l = base["low"].values.astype(np.float64)
    c = base["close"].values.astype(np.float64)
    v = base["volume"].values.astype(np.float64)

    top_i = TF_ORDER.index(cfg.top)
    chain = [tf for tf in TF_ORDER[top_i:] if TF_MIN[tf] >= base_tf_min]
    levels = list(chain)
    rungs = {tf: build_rung(bt, o, h, l, c, v, tf, base_tf_min) for tf in chain}
    top = rungs[cfg.top]
    wait_tf = chain[1] if len(chain) > 1 else chain[0]
    wr = rungs[wait_tf]

    # exclusion helper (applies to H1 top only, as in Pine)
    excl_mask = np.zeros(len(top.t), dtype=bool)
    if cfg.top == "H1" and cfg.exclusion != "none":
        if cfg.exclusion == "tehran":
            utc = server_to_utc_minutes(top.t, cfg.server_winter_off, cfg.server_summer_off)
            teh = (utc + cfg.tehran_offset_min) % 1440
            for hh, mm in cfg.tehran_hhmm:
                excl_mask |= teh == hh * 60 + mm
        elif cfg.exclusion == "server":
            hrs = (top.t % 1440) // 60
            excl_mask = np.isin(hrs, np.array(cfg.server_hours))

    rows = []
    n_top = len(top.t)
    stats = dict(gap=0, excluded=0, direct=0, waited_resolved=0, abandoned=0, superseded=0)
    cand = []  # (detect_idx, resolve_idx, k, dir, path)
    for cc in range(2, n_top):
        k = cc - 1
        vL, vC, vR = top.v[cc - 2], top.v[k], top.v[cc]
        if cfg.require_volume_gap and not (vC < vL and vC < vR):
            continue
        stats["gap"] += 1
        detect_idx = int(top.avail[cc])
        if detect_idx >= len(bt):
            continue
        if excl_mask[k]:
            stats["excluded"] += 1
            continue
        zt, zb = top.h[k], top.l[k]
        conf = top.c[cc]
        if conf > zt:
            cand.append((detect_idx, detect_idx, k, 1, 0))
        elif conf < zb:
            cand.append((detect_idx, detect_idx, k, -1, 0))
        else:
            # wait for up to N subsequent closes of the next-lower TF
            j0 = int(np.searchsorted(wr.t, top.tc[cc], side="left"))
            res = None
            for j in range(j0, min(j0 + cfg.wait_n, len(wr.t))):
                if wr.c[j] > zt:
                    res = (int(wr.avail[j]), 1)
                    break
                if wr.c[j] < zb:
                    res = (int(wr.avail[j]), -1)
                    break
            if res is None:
                stats["abandoned"] += 1
                continue
            cand.append((detect_idx, res[0], k, res[1], 1))

    # a newer (non-excluded) gap cancels an older, still-unresolved wait
    detects = np.array([x[0] for x in cand], dtype=np.int64)
    final = []
    for i, (d_idx, r_idx, k, dirn, path) in enumerate(cand):
        if path == 1:
            later = detects[i + 1:] if i + 1 < len(detects) else np.array([], dtype=np.int64)
            if len(later) and np.any((later > d_idx) & (later <= r_idx)):
                stats["superseded"] += 1
                continue
            stats["waited_resolved"] += 1
        else:
            stats["direct"] += 1
        if r_idx >= len(bt):
            continue
        final.append((r_idx, k, dirn, path, d_idx))
    final.sort(key=lambda x: (x[0], x[4]))

    nlev = len(levels)
    ztop = np.full((len(final), nlev), np.nan)
    zbot = np.full((len(final), nlev), np.nan)
    for si, (sig_idx, k, dirn, path, d_idx) in enumerate(final):
        winT, winTC = top.t[k], top.tc[k]
        ztop[si, 0], zbot[si, 0] = top.h[k], top.l[k]
        for li in range(1, nlev):
            r = rungs[levels[li]]
            n_av = int(np.searchsorted(r.avail, sig_idx, side="right"))
            sa = int(np.searchsorted(r.t, winT, side="left"))
            sb = int(np.searchsorted(r.tc, winTC, side="right")) - 1
            g = -1
            if sa <= sb:
                lo = max(sa, 1)
                hi = min(sb, n_av - 2)
                if hi >= lo:
                    g = _local_min_deepest(r.v, lo, hi)
            if g >= 0:
                winT, winTC = r.t[g], r.tc[g]
                ztop[si, li], zbot[si, li] = r.h[g], r.l[g]
        prev_close = c[sig_idx - 1]
        inside = 0
        for li in range(nlev):
            if not np.isnan(ztop[si, li]) and zbot[si, li] <= prev_close <= ztop[si, li]:
                inside += 1
        vmin_nb = min(top.v[k - 1], top.v[k + 1])
        rows.append(dict(sig_idx=sig_idx, detect_idx=d_idx, gap_bar=k, dir=dirn, path=path,
                         gap_time=pd.Timestamp(int(top.t[k]) * 60, unit="s"),
                         sig_time=pd.Timestamp(int(bt[sig_idx]) * 60, unit="s"),
                         inside=inside,
                         gap_ratio=top.v[k] / vmin_nb if vmin_nb > 0 else np.nan,
                         conf_close=top.c[k + 1], px_at_sig=prev_close))
    sdf = pd.DataFrame(rows)
    stats["signals"] = len(sdf)
    aux = dict(rungs=rungs, base_t=bt, o=o, h=h, l=l, c=c, v=v, levels=levels)
    return Signals(levels, sdf, ztop, zbot, stats), aux


# --------------------------------------------------------------------------------------
# Trade simulation
# --------------------------------------------------------------------------------------
@njit(cache=True)
def _sim_batch(t, o, h, l, c, spr, dirs, start, end, E, S, hold_min, comm, pessimistic, mkt,
               out_fill, out_fidx, out_fprice, out_mfe, out_xidx, out_xprice, out_outcome, out_ext):
    """For each candidate: find the limit fill, then walk forward until SL or time-out and
    record the best favourable price reached *before* the stop (for RR sweeps).
    outcome: 0 = not filled, 1 = stopped, 2 = time exit, 3 = data end."""
    n = len(t)
    for k in range(len(dirs)):
        d = dirs[k]
        e = E[k]
        s = S[k]
        out_fill[k] = False
        out_outcome[k] = 0
        f = -1
        fp = 0.0
        ext = e  # extreme between signal and fill (for structural targets)
        i0 = start[k]
        i1 = min(end[k], n)
        if mkt[k] and i0 < n:
            # market order at the open of bar i0 (BUY pays the ask, SELL gets the bid)
            f = i0
            fp = o[i0] + spr[i0] if d == 1 else o[i0]
            i1 = i0  # skip the limit search
        for i in range(i0, i1):
            if d == 1:
                ask_open = o[i] + spr[i]
                if i == i0 and ask_open <= e:
                    break  # buy limit cannot be placed below the market -> skip
                if l[i] <= e - spr[i]:
                    f = i
                    fp = ask_open if ask_open < e else e
                    break
                if h[i] > ext:
                    ext = h[i]
            else:
                if i == i0 and o[i] >= e:
                    break
                if h[i] >= e:
                    f = i
                    fp = o[i] if o[i] > e else e
                    break
                a_low = l[i] + spr[i]
                if a_low < ext:
                    ext = a_low
        out_ext[k] = ext
        if f < 0:
            continue
        out_fill[k] = True
        out_fidx[k] = f
        out_fprice[k] = fp
        mfe = fp
        deadline = t[f] + hold_min[k]
        outcome = 3
        xidx = n - 1
        xprice = c[n - 1] if d == 1 else c[n - 1] + spr[n - 1]
        # ---- fill bar ----
        if d == 1:
            if l[f] <= s:
                outcome = 1
                xidx = f
                xprice = o[f] if o[f] < s else s
            else:
                bull = c[f] >= o[f]
                if (not pessimistic) and bull:
                    if h[f] > mfe:
                        mfe = h[f]
                if c[f] > mfe:
                    mfe = c[f]
        else:
            if h[f] + spr[f] >= s:
                outcome = 1
                xidx = f
                xprice = o[f] + spr[f] if o[f] + spr[f] > s else s
            else:
                bear = c[f] < o[f]
                if (not pessimistic) and bear:
                    if l[f] + spr[f] < mfe:
                        mfe = l[f] + spr[f]
                if c[f] + spr[f] < mfe:
                    mfe = c[f] + spr[f]
        if outcome != 1:
            for j in range(f + 1, n):
                if t[j] >= deadline:
                    outcome = 2
                    xidx = j
                    xprice = o[j] if d == 1 else o[j] + spr[j]
                    break
                if d == 1:
                    if o[j] > mfe:
                        mfe = o[j]
                    if o[j] <= s:
                        outcome = 1
                        xidx = j
                        xprice = o[j]
                        break
                    hit = l[j] <= s
                    bull = c[j] >= o[j]
                    if hit:
                        if (not pessimistic) and (not bull):
                            if h[j] > mfe:
                                mfe = h[j]
                        outcome = 1
                        xidx = j
                        xprice = s
                        break
                    if h[j] > mfe:
                        mfe = h[j]
                else:
                    ao = o[j] + spr[j]
                    if ao < mfe:
                        mfe = ao
                    if ao >= s:
                        outcome = 1
                        xidx = j
                        xprice = ao
                        break
                    hit = h[j] + spr[j] >= s
                    bull = c[j] >= o[j]
                    if hit:
                        # bullish bar path O-L-H-C: the low (target side) comes first
                        if (not pessimistic) and bull:
                            if l[j] + spr[j] < mfe:
                                mfe = l[j] + spr[j]
                        outcome = 1
                        xidx = j
                        xprice = s
                        break
                    if l[j] + spr[j] < mfe:
                        mfe = l[j] + spr[j]
        out_mfe[k] = mfe
        out_xidx[k] = xidx
        out_xprice[k] = xprice
        out_outcome[k] = outcome


def simulate(aux: dict, dirs, start, end, E, S, hold_min, spread, comm=0.07, pessimistic=True, mkt=None):
    n = len(dirs)
    mkt = np.zeros(n, dtype=np.bool_) if mkt is None else np.asarray(mkt, dtype=np.bool_)
    out = dict(
        fill=np.zeros(n, dtype=np.bool_), fidx=np.full(n, -1, dtype=np.int64), fprice=np.zeros(n),
        mfe=np.zeros(n), xidx=np.full(n, -1, dtype=np.int64), xprice=np.zeros(n),
        outcome=np.zeros(n, dtype=np.int64), ext=np.zeros(n))
    _sim_batch(aux["base_t"], aux["o"], aux["h"], aux["l"], aux["c"], spread,
               np.asarray(dirs, dtype=np.int64), np.asarray(start, dtype=np.int64),
               np.asarray(end, dtype=np.int64), np.asarray(E, dtype=np.float64),
               np.asarray(S, dtype=np.float64), np.asarray(hold_min, dtype=np.int64),
               comm, pessimistic, mkt,
               out["fill"], out["fidx"], out["fprice"], out["mfe"], out["xidx"], out["xprice"],
               out["outcome"], out["ext"])
    return out


def r_multiples(sim: dict, dirs, E, S, rr: float, comm: float):
    """Net R of every filled trade for a fixed reward:risk target."""
    dirs = np.asarray(dirs)
    risk = np.where(dirs == 1, E - S, S - E)
    tp = np.where(dirs == 1, E + rr * risk, E - rr * risk)
    win = np.where(dirs == 1, sim["mfe"] >= tp, sim["mfe"] <= tp)
    exit_px = np.where(win, tp, sim["xprice"])
    pnl = np.where(dirs == 1, exit_px - sim["fprice"], sim["fprice"] - exit_px) - comm
    r = pnl / risk
    r[~sim["fill"]] = np.nan
    return r, win & sim["fill"]


def spread_model(close: np.ndarray, floor: float = 0.20, bps: float = 1.0) -> np.ndarray:
    """Spread in $ per oz: max(floor, bps * price / 1e4)."""
    return np.maximum(floor, close * bps / 1e4)


@njit(cache=True)
def _scan_reaction(o, h, l, c, dirs, start, end, zt, zb, mode, band_frac, out_idx):
    """First bar in [start, end) that is a reaction at the zone.
    mode 0 = rejection close: bar touches the zone and closes back outside on the bias side.
    mode 1 = pin bar near the near edge WITHOUT touching (intended v3 feature):
             BUY: bullish pin (lower wick >= 2*body, lower > upper), zt < low <= zt + band, close > zt.
    Scanning stops at the first bar that closes beyond the far edge (zone failed)."""
    for k in range(len(dirs)):
        out_idx[k] = -1
        d = dirs[k]
        band = band_frac * (zt[k] - zb[k])
        for i in range(start[k], min(end[k], len(o))):
            body = abs(c[i] - o[i])
            up = h[i] - max(o[i], c[i])
            lo = min(o[i], c[i]) - l[i]
            if d == 1:
                if mode == 0:
                    if l[i] <= zt[k] and c[i] > zt[k]:
                        out_idx[k] = i
                        break
                else:
                    pin = body > 0 and lo >= 2 * body and lo > up
                    if pin and l[i] > zt[k] and l[i] <= zt[k] + band and c[i] > zt[k]:
                        out_idx[k] = i
                        break
                    if l[i] <= zt[k]:
                        break  # zone touched: the limit entry takes over
                if c[i] < zb[k]:
                    break
            else:
                if mode == 0:
                    if h[i] >= zb[k] and c[i] < zb[k]:
                        out_idx[k] = i
                        break
                else:
                    pin = body > 0 and up >= 2 * body and up > lo
                    if pin and h[i] < zb[k] and h[i] >= zb[k] - band and c[i] < zb[k]:
                        out_idx[k] = i
                        break
                    if h[i] >= zb[k]:
                        break
                if c[i] > zt[k]:
                    break


@njit(cache=True)
def _sim_fixed(t, o, h, l, c, spr, dirs, start, end, E, S, T, be_r, hold_min, pessimistic, mkt, out_r, out_fill):
    """Explicit TP/SL simulation with an optional break-even stop (moved to the entry once the
    trade is +be_r R in profit; takes effect from the next bar).  Returns net R before commission."""
    n = len(t)
    for k in range(len(dirs)):
        d = dirs[k]
        e = E[k]
        s = S[k]
        tp = T[k]
        risk = abs(e - s)
        out_fill[k] = False
        out_r[k] = np.nan
        i0 = start[k]
        i1 = min(end[k], n)
        f = -1
        fp = 0.0
        if mkt[k] and i0 < n:
            f = i0
            fp = o[i0] + spr[i0] if d == 1 else o[i0]
        else:
            for i in range(i0, i1):
                if d == 1:
                    ao = o[i] + spr[i]
                    if i == i0 and ao <= e:
                        break
                    if l[i] <= e - spr[i]:
                        f = i
                        fp = ao if ao < e else e
                        break
                else:
                    if i == i0 and o[i] >= e:
                        break
                    if h[i] >= e:
                        f = i
                        fp = o[i] if o[i] > e else e
                        break
        if f < 0:
            continue
        out_fill[k] = True
        deadline = t[f] + hold_min[k]
        cur_s = s
        exit_px = np.nan
        for j in range(f, n):
            if j > f and t[j] >= deadline:
                exit_px = o[j] if d == 1 else o[j] + spr[j]
                break
            if d == 1:
                if j > f and o[j] <= cur_s:
                    exit_px = o[j]
                    break
                sl_hit = l[j] <= cur_s
                tp_hit = h[j] >= tp and j > f
                if j == f and (not pessimistic) and c[j] >= o[j] and h[j] >= tp:
                    tp_hit = True
                if sl_hit and tp_hit:
                    first_sl = pessimistic or (c[j] >= o[j])
                    exit_px = cur_s if first_sl else tp
                    break
                if sl_hit:
                    exit_px = cur_s
                    break
                if tp_hit:
                    exit_px = tp
                    break
                if be_r > 0 and h[j] - e >= be_r * risk and cur_s < e:
                    cur_s = e
            else:
                if j > f and o[j] + spr[j] >= cur_s:
                    exit_px = o[j] + spr[j]
                    break
                sl_hit = h[j] + spr[j] >= cur_s
                tp_hit = l[j] + spr[j] <= tp and j > f
                if j == f and (not pessimistic) and c[j] < o[j] and l[j] + spr[j] <= tp:
                    tp_hit = True
                if sl_hit and tp_hit:
                    first_sl = pessimistic or (c[j] < o[j])
                    exit_px = cur_s if first_sl else tp
                    break
                if sl_hit:
                    exit_px = cur_s
                    break
                if tp_hit:
                    exit_px = tp
                    break
                if be_r > 0 and e - (l[j] + spr[j]) >= be_r * risk and cur_s > e:
                    cur_s = e
        if np.isnan(exit_px):
            exit_px = c[n - 1] if d == 1 else c[n - 1] + spr[n - 1]
        pnl = (exit_px - fp) if d == 1 else (fp - exit_px)
        out_r[k] = pnl / risk
