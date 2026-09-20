"""LVN Clarity Cascade — offline engine for backtesting and optimisation.

Mirrors MQL5/Include/Hayati/ClarityLVN.mqh and the event loop of
MQL5/Experts/Hayati/LVNCascade_EA.mq5. The clarity search is the same
transcription that tools/verify_clarity.py pins against the Pine source.

The split that makes optimisation cheap: the cascade, and therefore every
entry signal, does not depend on the stop or target at all. Signals are built
once; each stop/target combination then only replays the exits.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

MINUTE = 60
TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}
CHAIN = ["D1", "H4", "H1", "M15", "M5"]


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------

@dataclass
class M1Data:
    time: np.ndarray        # int64 seconds, broker server time
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray      # tick volume unless the broker supplies real volume
    spread: np.ndarray      # points, per bar, straight from the terminal
    point: float
    symbol: str = ""

    def __len__(self):
        return len(self.time)


def load_m1_csv(path: str, symbol: str = "", point: float | None = None,
                use_real_volume: bool = False) -> M1Data:
    """Read the CSV written by MQL5/Scripts/Hayati/ExportM1.mq5."""
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]

    t = pd.to_datetime(df["time"], format="mixed", dayfirst=False)
    # pandas picks the datetime64 unit from the data, so never assume it is
    # nanoseconds - convert through an explicit unit instead. Getting this
    # wrong rescales every timestamp and silently ruins the whole backtest.
    secs = t.to_numpy().astype("datetime64[s]").astype("int64")

    vol_col = "real_volume" if (use_real_volume and "real_volume" in df) else "tick_volume"
    vol = df[vol_col].to_numpy(dtype=float)
    if vol.sum() <= 0 and vol_col == "real_volume":
        vol = df["tick_volume"].to_numpy(dtype=float)

    close = df["close"].to_numpy(dtype=float)
    if point is None:
        # infer from the quote precision actually present in the file
        decimals = max(len(str(v).split(".")[-1]) if "." in str(v) else 0
                       for v in df["close"].head(200).astype(str))
        point = 10.0 ** (-decimals)

    spread = (df["spread"].to_numpy(dtype=float) if "spread" in df
              else np.zeros(len(df), dtype=float))

    order = np.argsort(secs, kind="stable")
    secs = secs[order]

    if len(secs) > 1:
        step = np.diff(secs)
        step = step[step > 0]
        median_step = int(np.median(step)) if len(step) else 0
        if median_step != 60:
            raise ValueError(
                f"{path}: bars are {median_step}s apart, expected 60s. "
                "This loader wants M1 data - re-export with PERIOD_M1.")
        if np.any(np.diff(secs) == 0):
            dupes = int((np.diff(secs) == 0).sum())
            raise ValueError(f"{path}: {dupes} duplicate timestamps, refusing to guess")

    return M1Data(
        time=secs,
        open=df["open"].to_numpy(dtype=float)[order],
        high=df["high"].to_numpy(dtype=float)[order],
        low=df["low"].to_numpy(dtype=float)[order],
        close=close[order],
        volume=vol[order],
        spread=spread[order],
        point=point,
        symbol=symbol,
    )


@dataclass
class TFBars:
    """Higher-timeframe bars aggregated from M1, the way MetaTrader does it."""
    start: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    seconds: int


def aggregate(m1: M1Data, tf: str) -> TFBars:
    sec = TF_SECONDS[tf]
    bucket = m1.time // sec
    # bucket is non-decreasing, so boundaries are where it changes
    edges = np.flatnonzero(np.diff(bucket)) + 1
    starts = np.concatenate(([0], edges))
    ends = np.concatenate((edges, [len(m1)]))

    hi = np.maximum.reduceat(m1.high, starts)
    lo = np.minimum.reduceat(m1.low, starts)
    return TFBars(
        start=bucket[starts] * sec,
        open=m1.open[starts],
        high=hi,
        low=lo,
        close=m1.close[ends - 1],
        seconds=sec,
    )


# --------------------------------------------------------------------------
# the clarity search — CL_ZoneFromM1
# --------------------------------------------------------------------------

@dataclass
class Zone:
    top: float
    bottom: float
    rows: int
    clarity: float
    clear: bool


def zone_from_m1(m1: M1Data, lo_idx: int, hi_idx: int,
                 min_rows: int, max_rows: int, gap_threshold: float) -> Zone | None:
    """[lo_idx, hi_idx) over the M1 arrays. Mirrors CL_ZoneFromM1 exactly."""
    n = hi_idx - lo_idx
    if n < 2:
        return None

    highs = m1.high[lo_idx:hi_idx]
    lows = m1.low[lo_idx:hi_idx]
    vols = m1.volume[lo_idx:hi_idx]

    bar_high = float(highs.max())
    bar_low = float(lows.min())
    if bar_high <= bar_low:
        return None

    mids = (highs + lows) * 0.5

    best_clarity = -1.0
    best_rows = 0
    best_idx = -1
    best_step = 0.0
    found = False

    rows = min_rows
    while rows <= max_rows and not found:
        step = (bar_high - bar_low) / rows
        if step <= 0.0:
            rows += 1
            continue

        idx = np.floor((mids - bar_low) / step).astype(np.int64)
        np.clip(idx, 0, rows - 1, out=idx)
        bins = np.bincount(idx, weights=vols, minlength=rows)[:rows]

        min_idx = int(np.argmin(bins))          # first minimum, as ArrayMinimum does
        min_vol = float(bins[min_idx])
        total = float(bins.sum())
        avg_other = (total - min_vol) / (rows - 1) if rows > 1 else min_vol
        clarity = (1.0 - min_vol / avg_other) * 100.0 if avg_other > 0.0 else 0.0

        if clarity > best_clarity:
            best_clarity = clarity
            best_rows = rows
            best_idx = min_idx
            best_step = step
        if clarity >= gap_threshold:
            found = True
        rows += 1

    if best_idx < 0:
        return None
    bottom = bar_low + best_idx * best_step
    return Zone(top=bottom + best_step, bottom=bottom, rows=best_rows,
                clarity=best_clarity, clear=found)


# --------------------------------------------------------------------------
# the cascade — CL_RunCascade
# --------------------------------------------------------------------------

@dataclass
class CascadeParams:
    top_stage: str = "D1"
    min_rows: int = 3
    max_rows: int = 8
    gap_threshold: float = 40.0
    body_only: bool = False


class CascadeEngine:
    def __init__(self, m1: M1Data, params: CascadeParams):
        self.m1 = m1
        self.p = params
        start = CHAIN.index(params.top_stage)
        self.chain = CHAIN[start:]
        self.bars = {tf: aggregate(m1, tf) for tf in self.chain}

    def _m1_slice(self, t_from: int, t_to: int) -> tuple[int, int]:
        lo = int(np.searchsorted(self.m1.time, t_from, side="left"))
        hi = int(np.searchsorted(self.m1.time, t_to, side="left"))
        return lo, hi

    def _first_containing(self, tf: str, win_from: int, win_to: int,
                          z_top: float, z_bottom: float) -> int | None:
        b = self.bars[tf]
        i = int(np.searchsorted(b.start, win_from, side="left"))
        while i < len(b.start):
            s = int(b.start[i])
            if s >= win_to:
                break
            if s + b.seconds > win_to:       # must close inside the parent window
                i += 1
                continue
            if self.p.body_only:
                cover_high = max(b.open[i], b.close[i])
                cover_low = min(b.open[i], b.close[i])
            else:
                cover_high = b.high[i]
                cover_low = b.low[i]
            if cover_high >= z_top and cover_low <= z_bottom:
                return s
            i += 1
        return None

    def run(self, top_from: int, top_to: int) -> tuple[int, Zone | None]:
        """Returns (stages completed, final zone). Complete only when
        stages == len(chain)."""
        lo, hi = self._m1_slice(top_from, top_to)
        zone = zone_from_m1(self.m1, lo, hi, self.p.min_rows,
                            self.p.max_rows, self.p.gap_threshold)
        if zone is None:
            return 0, None

        win_from, win_to = top_from, top_to
        for si in range(1, len(self.chain)):
            tf = self.chain[si]
            found = self._first_containing(tf, win_from, win_to, zone.top, zone.bottom)
            if found is None:
                return si, zone
            child_to = found + TF_SECONDS[tf]
            lo, hi = self._m1_slice(found, child_to)
            child = zone_from_m1(self.m1, lo, hi, self.p.min_rows,
                                 self.p.max_rows, self.p.gap_threshold)
            if child is None:
                return si, zone
            zone = child
            win_from, win_to = found, child_to

        return len(self.chain), zone


# --------------------------------------------------------------------------
# signals
# --------------------------------------------------------------------------

@dataclass
class Signal:
    idx: int            # M1 bar the zone was touched on
    time: int
    is_long: bool
    touch: float        # fill price on the BID, before any spread
    zone_top: float
    zone_bottom: float
    spread_price: float

    def entry_for(self, is_long: bool) -> float:
        """Buys lift the ask, sells hit the bid. Keeping the touch price and
        applying the side here is what lets the permutation test flip a
        direction without handing the flipped trade a free spread."""
        return self.touch + self.spread_price if is_long else self.touch


@dataclass
class SignalSet:
    signals: list[Signal] = field(default_factory=list)
    cascades_run: int = 0
    cascades_complete: int = 0
    zones_untouched: int = 0
    stage_histogram: dict = field(default_factory=dict)
    live_zones: list = field(default_factory=list)   # (time it went live, Zone)


def build_signals(m1: M1Data, params: CascadeParams) -> SignalSet:
    """Replays the expert's event loop and returns every entry it would take.

    The live-zone rule is the Pine one: a completed cascade replaces the
    watched zone, a failed one leaves the previous zone in place.
    """
    eng = CascadeEngine(m1, params)
    top = eng.bars[params.top_stage]
    out = SignalSet()

    # zones become live when their top-stage candle closes, i.e. at the next
    # candle's start, and stay live until the next COMPLETED cascade
    live: list[tuple[int, Zone]] = []
    for k in range(len(top.start) - 1):
        t_from = int(top.start[k])
        t_to = int(top.start[k + 1])
        stages, zone = eng.run(t_from, t_to)
        out.cascades_run += 1
        out.stage_histogram[stages] = out.stage_histogram.get(stages, 0) + 1
        if stages == len(eng.chain) and zone is not None:
            out.cascades_complete += 1
            live.append((t_to, zone))

    out.live_zones = live
    out.signals, out.zones_untouched = signals_from_zones(m1, live)
    return out


def signals_from_zones(m1: M1Data, live: list, rng=None,
                       shift_zone_heights: float = 5.0) -> tuple[list[Signal], int]:
    """Turn live zones into entries.

    With `rng` supplied each zone is displaced by a random offset of up to
    `shift_zone_heights` of its own height. That is the null the cascade has
    to beat: identical timing, identical zone size, identical fade-on-touch
    mechanics, only the price level is no longer the one the clarity search
    chose. Anything the strategy earns over this null came from the algorithm
    rather than from the act of fading a touch.
    """
    signals: list[Signal] = []
    untouched = 0
    for n, (t_live, zone) in enumerate(live):
        t_end = live[n + 1][0] if n + 1 < len(live) else int(m1.time[-1]) + 1
        z = zone
        if rng is not None:
            h = zone.top - zone.bottom
            off = (rng.random() * 2.0 - 1.0) * shift_zone_heights * h
            z = Zone(top=zone.top + off, bottom=zone.bottom + off,
                     rows=zone.rows, clarity=zone.clarity, clear=zone.clear)
        sig = _first_touch(m1, z, t_live, t_end)
        if sig is None:
            untouched += 1
        else:
            signals.append(sig)
    return signals, untouched


def _first_touch(m1: M1Data, zone: Zone, t_from: int, t_to: int) -> Signal | None:
    lo = int(np.searchsorted(m1.time, t_from, side="left"))
    hi = int(np.searchsorted(m1.time, t_to, side="left"))
    if lo < 1:
        lo = 1
    if hi <= lo:
        return None

    high = m1.high[lo:hi]
    low = m1.low[lo:hi]
    prev_close = m1.close[lo - 1:hi - 1]

    touch = (high >= zone.bottom) & (low <= zone.top)
    from_above = touch & (prev_close > zone.top)
    from_below = touch & (prev_close < zone.bottom)
    ok = from_above | from_below
    if not ok.any():
        return None

    j = int(np.argmax(ok))
    i = lo + j
    is_long = bool(from_above[j])
    spread_price = float(m1.spread[i]) * m1.point

    # Bars are Bid. Falling into the zone from above first touches its top;
    # rising into it from below first touches its bottom. A bar that opens
    # already past that edge fills at the open instead.
    # Falling into the zone from above first touches its top, rising into it
    # from below first touches its bottom. A bar that opens already past that
    # edge fills at its open instead.
    if is_long:
        touch = min(float(m1.open[i]), zone.top)
    else:
        touch = max(float(m1.open[i]), zone.bottom)

    return Signal(idx=i, time=int(m1.time[i]), is_long=is_long, touch=touch,
                  zone_top=zone.top, zone_bottom=zone.bottom,
                  spread_price=spread_price)


# --------------------------------------------------------------------------
# exits
# --------------------------------------------------------------------------

@dataclass
class ExitParams:
    sl_mode: str = "zone"       # "zone" | "atr" | "points"
    sl_zone_buffer: float = 0.25
    sl_atr: float = 1.5
    sl_points: float = 300.0
    tp_rr: float = 2.0
    max_hold_minutes: int = 0   # 0 = hold until stop or target
    one_at_a_time: bool = True
    entry_bar_stop: bool = False  # let the stop trigger on the entry bar too


@dataclass
class Trade:
    entry_time: int
    exit_time: int
    is_long: bool
    entry: float
    sl: float
    tp: float
    r_multiple: float
    reason: str
    bars_held: int


def _atr_m1(m1: M1Data, period_minutes: int = 14 * 60) -> np.ndarray:
    tr = np.maximum(m1.high - m1.low,
                    np.maximum(np.abs(m1.high - np.roll(m1.close, 1)),
                               np.abs(m1.low - np.roll(m1.close, 1))))
    tr[0] = m1.high[0] - m1.low[0]
    kernel = np.ones(period_minutes) / period_minutes
    atr = np.convolve(tr, kernel, mode="full")[:len(tr)]
    return atr


def _first_hit(mask: np.ndarray) -> int:
    """Index of the first True, or -1."""
    if not mask.any():
        return -1
    return int(np.argmax(mask))


def simulate(m1: M1Data, sigs: list[Signal], ex: ExitParams,
             atr: np.ndarray | None = None,
             flip: np.ndarray | None = None) -> list[Trade]:
    """Replay exits.

    Deliberately pessimistic where an M1 bar is ambiguous: if the bar could
    have hit both the stop and the target, the stop is taken. The stop is also
    live on the entry bar itself, because price that ran straight through the
    zone really would have taken it out.

    `flip` is an optional boolean array used by the permutation test: where it
    is True the trade's direction is inverted, keeping entry and geometry, so
    the real direction rule can be scored against a coin flip.

    The forward scan runs in chunks so a trade that resolves in minutes costs
    minutes of work, not a pass over the whole file.
    """
    if ex.sl_mode == "atr" and atr is None:
        atr = _atr_m1(m1)

    n_bars = len(m1)
    chunk = 4096
    trades: list[Trade] = []
    busy_until = -1

    for k, s in enumerate(sigs):
        if ex.one_at_a_time and s.idx <= busy_until:
            continue

        is_long = s.is_long if flip is None else (s.is_long != bool(flip[k]))
        entry = s.entry_for(is_long)

        # The stop DISTANCE always comes from the signal's own geometry, then
        # gets mirrored onto whichever side is being traded. Without this a
        # flipped trade would enter at the far edge of the zone and still put
        # its stop just past the near one, giving it a fraction of the real
        # trade's risk - which is a different trade, not the same trade in
        # reverse, and it silently rigged the permutation test.
        nat_entry = s.entry_for(s.is_long)
        zone_h = s.zone_top - s.zone_bottom
        if ex.sl_mode == "zone":
            nat_sl = (s.zone_bottom - zone_h * ex.sl_zone_buffer if s.is_long
                      else s.zone_top + zone_h * ex.sl_zone_buffer)
        elif ex.sl_mode == "atr":
            a = float(atr[s.idx])
            nat_sl = nat_entry - a * ex.sl_atr if s.is_long else nat_entry + a * ex.sl_atr
        else:
            d = ex.sl_points * m1.point
            nat_sl = nat_entry - d if s.is_long else nat_entry + d

        risk = abs(nat_entry - nat_sl)
        if risk <= 0:
            continue                                    # degenerate stop, skip

        sl = entry - risk if is_long else entry + risk
        tp = (entry + risk * ex.tp_rr if is_long else entry - risk * ex.tp_rr)

        limit = n_bars - 1
        if ex.max_hold_minutes > 0:
            limit = min(limit, s.idx + ex.max_hold_minutes)

        r = None
        reason = ""
        exit_i = limit

        # Exits start on the bar AFTER entry. The entry bar's high and low
        # mostly happened before the fill - a zone touched from above is
        # reached near that bar's low, so its high is already spent - and
        # scoring a target against them pays out for a move the trade was
        # never in. That leak is invisible in a single backtest and shows up
        # as the direction rule beating a coin flip on data that has no
        # direction in it at all.
        if ex.entry_bar_stop and s.idx <= limit:
            sp0 = float(m1.spread[s.idx]) * m1.point
            hit = (m1.low[s.idx] <= sl) if is_long else ((m1.high[s.idx] + sp0) >= sl)
            if hit:
                r, reason, exit_i = -1.0, "sl", s.idx

        pos = s.idx + 1
        while r is None and pos <= limit:
            end = min(pos + chunk, limit + 1)
            lo = m1.low[pos:end]
            hi = m1.high[pos:end]
            if is_long:
                sl_mask = lo <= sl                      # bars are bid
                tp_mask = hi >= tp
            else:
                sp = m1.spread[pos:end] * m1.point      # exits run on the ask
                sl_mask = (hi + sp) >= sl
                tp_mask = (lo + sp) <= tp

            i_sl = _first_hit(sl_mask)
            i_tp = _first_hit(tp_mask)
            if i_sl >= 0 or i_tp >= 0:
                if i_sl >= 0 and (i_tp < 0 or i_sl <= i_tp):
                    r, reason, exit_i = -1.0, "sl", pos + i_sl
                else:
                    r, reason, exit_i = ex.tp_rr, "tp", pos + i_tp
                break
            pos = end

        if r is None:                                   # ran out of bars or time
            last = float(m1.close[exit_i])
            move = (last - entry) if is_long else (entry - last)
            r = move / risk
            reason = "timeout" if ex.max_hold_minutes > 0 else "eod"

        trades.append(Trade(entry_time=s.time, exit_time=int(m1.time[exit_i]),
                            is_long=is_long, entry=entry, sl=sl, tp=tp,
                            r_multiple=float(r), reason=reason,
                            bars_held=exit_i - s.idx))
        busy_until = exit_i

    return trades


def metrics(trades: list[Trade]) -> dict:
    if not trades:
        return dict(trades=0, net_r=0.0, expectancy=0.0, win_rate=0.0,
                    profit_factor=0.0, max_dd_r=0.0, sharpe=0.0)

    r = np.array([t.r_multiple for t in trades], dtype=float)
    wins = r[r > 0]
    losses = r[r <= 0]
    equity = np.cumsum(r)
    peak = np.maximum.accumulate(equity)
    dd = peak - equity

    gross_win = float(wins.sum())
    gross_loss = float(-losses.sum())

    return dict(
        trades=len(trades),
        net_r=float(r.sum()),
        expectancy=float(r.mean()),
        win_rate=float(len(wins) / len(r)),
        profit_factor=(gross_win / gross_loss) if gross_loss > 0 else float("inf"),
        max_dd_r=float(dd.max()),
        sharpe=float(r.mean() / r.std(ddof=1)) if len(r) > 1 and r.std(ddof=1) > 0 else 0.0,
    )
