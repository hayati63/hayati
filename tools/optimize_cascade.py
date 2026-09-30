"""Walk-forward optimisation of the LVN Clarity Cascade's stop and target.

The point of this file is to make it hard to fool yourself. Four guards:

  1. WALK-FORWARD. Parameters are chosen on data the result is never scored
     on. The headline number is out-of-sample only. An in-sample number is
     reported beside it purely so the gap between them is visible.

  2. PLATEAU, NOT PEAK. The in-sample winner is not the single best cell of
     the grid but the best local neighbourhood. A lone spike surrounded by
     losses is noise; a broad region that works is a parameter you can trade.

  3. A TRADE FLOOR. Any cell with too few trades is disqualified before it
     can win, however good its numbers look.

  4. A PERMUTATION TEST. The direction rule is scored against a coin flip on
     the very same entries. If flipping directions at random does about as
     well, the rule carries no information and nothing else matters.

    python3 tools/optimize_cascade.py --csv m1_export.csv --folds 4
"""

import argparse
import json

import numpy as np

from backtest_cascade import add_common_args
from cascade_core import (CascadeParams, ExitParams, build_signals, load_m1_csv,
                          metrics, signals_from_zones, simulate, _atr_m1)


def parse_grid(text: str) -> list[float]:
    return [float(x) for x in text.replace(",", " ").split()]


def score_grid(m1, sigs, sl_mode, sl_values, rr_values, min_trades, atr):
    """expectancy and trade count for every cell."""
    exp = np.full((len(sl_values), len(rr_values)), np.nan)
    net = np.full_like(exp, np.nan)
    cnt = np.zeros_like(exp, dtype=int)

    for i, slv in enumerate(sl_values):
        for j, rr in enumerate(rr_values):
            ex = _exits(sl_mode, slv, rr)
            tr = simulate(m1, sigs, ex, atr)
            m = metrics(tr)
            cnt[i, j] = m["trades"]
            if m["trades"] >= min_trades:
                exp[i, j] = m["expectancy"]
                net[i, j] = m["net_r"]
    return exp, net, cnt


def _exits(sl_mode, sl_value, rr, max_hold=0):
    if sl_mode == "zone":
        return ExitParams("zone", sl_zone_buffer=sl_value, tp_rr=rr, max_hold_minutes=max_hold)
    if sl_mode == "atr":
        return ExitParams("atr", sl_atr=sl_value, tp_rr=rr, max_hold_minutes=max_hold)
    return ExitParams("points", sl_points=sl_value, tp_rr=rr, max_hold_minutes=max_hold)


def plateau_smooth(grid: np.ndarray) -> np.ndarray:
    """Mean of each cell's 3x3 neighbourhood, ignoring disqualified cells.

    A cell whose neighbours are all bad cannot win no matter how good it is.
    """
    out = np.full_like(grid, np.nan)
    rows, cols = grid.shape
    for i in range(rows):
        for j in range(cols):
            if np.isnan(grid[i, j]):
                continue
            block = grid[max(0, i - 1):i + 2, max(0, j - 1):j + 2]
            vals = block[~np.isnan(block)]
            if len(vals) >= 3:                 # need a real neighbourhood
                out[i, j] = vals.mean()
    return out


def pick(grid_smoothed, sl_values, rr_values):
    if np.all(np.isnan(grid_smoothed)):
        return None
    k = int(np.nanargmax(grid_smoothed))
    i, j = np.unravel_index(k, grid_smoothed.shape)
    return int(i), int(j), sl_values[i], rr_values[j]


def render(grid, sl_values, rr_values, title, fmt="{:+.3f}"):
    print(f"\n{title}")
    print("      RR " + " ".join(f"{rr:>7.2f}" for rr in rr_values))
    for i, slv in enumerate(sl_values):
        cells = []
        for j in range(len(rr_values)):
            v = grid[i, j]
            cells.append("      ." if np.isnan(v) else fmt.format(v))
        print(f"SL {slv:>6.2f} " + " ".join(f"{c:>7}" for c in cells))


def permutation_test(m1, live_zones, ex, atr, real_exp, n_perm, seed,
                     shift_zone_heights=5.0):
    """Score the cascade's chosen levels against random levels.

    Same timing, same zone sizes, same fade-on-touch mechanics - only the
    price level is displaced. Whatever the strategy earns above this null came
    from the clarity search; whatever it earns below it came from the act of
    fading a touch, which needs no algorithm at all.

    Comparing on expectancy rather than net R keeps it fair when a displaced
    zone happens to be touched more or less often than the real one.
    """
    rng = np.random.default_rng(seed)
    null = np.empty(n_perm)
    counts = np.empty(n_perm, dtype=int)
    for p in range(n_perm):
        sig, _ = signals_from_zones(m1, live_zones, rng, shift_zone_heights)
        m = metrics(simulate(m1, sig, ex, atr))
        null[p] = m["expectancy"]
        counts[p] = m["trades"]
    better = int((null >= real_exp).sum())
    return dict(p_value=(better + 1) / (n_perm + 1),
                null_mean=float(null.mean()), null_std=float(null.std(ddof=1)),
                null_best=float(null.max()), real=float(real_exp),
                null_trades=float(counts.mean()))


def main():
    ap = argparse.ArgumentParser()
    add_common_args(ap)
    ap.add_argument("--sl-mode", default="zone", choices=["zone", "atr", "points"])
    ap.add_argument("--sl-grid", default="0 0.1 0.2 0.3 0.4 0.5 0.7 0.9 1.2 1.5")
    ap.add_argument("--rr-grid", default="0.5 1 1.5 2 2.5 3 4 5")
    ap.add_argument("--folds", type=int, default=4)
    ap.add_argument("--min-trades", type=int, default=25)
    ap.add_argument("--min-trades-oos", type=int, default=10)
    ap.add_argument("--permutations", type=int, default=300)
    ap.add_argument("--zone-shift", type=float, default=5.0,
                    help="null displaces each zone by up to N of its own heights")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--set-file", default=None, help="write the chosen params as an MT5 .set")
    a = ap.parse_args()

    sl_values = parse_grid(a.sl_grid)
    rr_values = parse_grid(a.rr_grid)

    m1 = load_m1_csv(a.csv, a.symbol, a.point, a.real_volume)
    cp = CascadeParams(a.top_stage, a.min_rows, a.max_rows, a.gap_threshold, a.body_only)
    sset = build_signals(m1, cp)
    sigs = sset.signals
    atr = _atr_m1(m1) if a.sl_mode == "atr" else None

    span_days = (m1.time[-1] - m1.time[0]) / 86400
    print(f"data     : {len(m1):,} M1 bars, {span_days:.0f} days")
    print(f"cascades : {sset.cascades_run} run, {sset.cascades_complete} complete, "
          f"{len(sigs)} entries")
    if len(sigs) < a.min_trades * 2:
        print(f"\nSTOP: {len(sigs)} entries is not enough to optimise honestly. "
              f"Use a longer history or a lower --top-stage.")
        return

    # ---------------- in-sample picture, for reference only ----------------
    exp, net, cnt = score_grid(m1, sigs, a.sl_mode, sl_values, rr_values,
                               a.min_trades, atr)
    render(cnt, sl_values, rr_values, "trade count per cell", "{:>7d}")
    render(exp, sl_values, rr_values, "IN-SAMPLE expectancy (R/trade) — do not trade this")
    sm = plateau_smooth(exp)
    render(sm, sl_values, rr_values, "plateau-smoothed in-sample expectancy")

    best_is = pick(sm, sl_values, rr_values)
    if best_is is None:
        print("\nSTOP: every cell failed the trade floor.")
        return
    print(f"\nin-sample plateau pick: SL={best_is[2]}  RR={best_is[3]}  "
          f"(expectancy {exp[best_is[0], best_is[1]]:+.4f} R, "
          f"{cnt[best_is[0], best_is[1]]} trades)")

    # ---------------- walk-forward ----------------
    print(f"\n{'=' * 64}\nWALK-FORWARD ({a.folds} folds, anchored)\n{'=' * 64}")
    bounds = np.linspace(0, len(sigs), a.folds + 2).astype(int)
    oos_trades = []
    chosen = []

    for f in range(1, a.folds + 1):
        tr_sigs = sigs[:bounds[f]]
        te_sigs = sigs[bounds[f]:bounds[f + 1]]
        if len(te_sigs) < a.min_trades_oos or len(tr_sigs) < a.min_trades:
            print(f"fold {f}: skipped (train {len(tr_sigs)}, test {len(te_sigs)})")
            continue

        e, _, c = score_grid(m1, tr_sigs, a.sl_mode, sl_values, rr_values,
                             a.min_trades, atr)
        best = pick(plateau_smooth(e), sl_values, rr_values)
        if best is None:
            print(f"fold {f}: no cell cleared the trade floor in training")
            continue

        ex = _exits(a.sl_mode, best[2], best[3])
        tt = simulate(m1, te_sigs, ex, atr)
        mm = metrics(tt)
        oos_trades.extend(tt)
        chosen.append((best[2], best[3]))
        print(f"fold {f}: train {len(tr_sigs):>4} -> SL={best[2]:<5} RR={best[3]:<5} "
              f"| test {mm['trades']:>3} trades  net {mm['net_r']:+7.1f}R  "
              f"exp {mm['expectancy']:+.3f}R  win {100*mm['win_rate']:.0f}%")

    if not oos_trades:
        print("\nSTOP: no out-of-sample trades were produced.")
        return

    om = metrics(oos_trades)
    print(f"\n{'-' * 64}")
    print(f"OUT-OF-SAMPLE, all folds pooled  ({om['trades']} trades)")
    print(f"  net R      : {om['net_r']:+.1f}")
    print(f"  expectancy : {om['expectancy']:+.4f} R per trade")
    print(f"  win rate   : {100 * om['win_rate']:.1f}%")
    print(f"  profit fac : {om['profit_factor']:.2f}")
    print(f"  max DD     : {om['max_dd_r']:.1f} R")
    print(f"  params kept: {sorted(set(chosen))}")

    # ---------------- do the cascade's levels beat random levels? ----------
    stable = max(set(chosen), key=chosen.count)
    ex = _exits(a.sl_mode, stable[0], stable[1])
    real_m = metrics(simulate(m1, sigs, ex, atr))
    pt = permutation_test(m1, sset.live_zones, ex, atr, real_m["expectancy"],
                          a.permutations, a.seed, a.zone_shift)

    print(f"\n{'-' * 64}")
    print(f"RANDOM-LEVEL TEST at SL={stable[0]} RR={stable[1]}")
    print(f"  {a.permutations} runs with each zone displaced by up to "
          f"{a.zone_shift:g} of its own height,")
    print(f"  everything else identical.")
    print(f"  cascade levels  : {pt['real']:+.4f} R/trade over {real_m['trades']} trades")
    print(f"  random levels   : {pt['null_mean']:+.4f} R/trade "
          f"(sd {pt['null_std']:.4f}, best {pt['null_best']:+.4f}, "
          f"~{pt['null_trades']:.0f} trades)")
    print(f"  p-value         : {pt['p_value']:.3f}")

    # secondary, deterministic: what if every direction were reversed?
    rev = metrics(simulate(m1, sigs, ex, atr, flip=np.ones(len(sigs), dtype=bool)))
    print(f"  reversed rule   : {rev['expectancy']:+.4f} R/trade "
          f"(the same entries taken the other way)")

    print(f"\n{'=' * 64}\nVERDICT\n{'=' * 64}")
    reasons = []
    if om["expectancy"] <= 0:
        reasons.append(f"out-of-sample expectancy is {om['expectancy']:+.4f} R, not positive")
    if pt["p_value"] > 0.05:
        reasons.append(f"the cascade's levels are no better than random levels "
                       f"(p={pt['p_value']:.3f})")
    if om["trades"] < 30:
        reasons.append(f"only {om['trades']} out-of-sample trades, too few to conclude")

    if reasons:
        print("Do NOT trade this as it stands:")
        for r in reasons:
            print(f"  - {r}")
    else:
        print(f"Out-of-sample expectancy {om['expectancy']:+.4f} R over {om['trades']} "
              f"trades, p={pt['p_value']:.3f}.")
        print(f"Parameters that held up: SL={stable[0]}  RR={stable[1]}")
        print("Forward-test on demo before risking money.")

    if a.set_file:
        write_set(a.set_file, cp, a.sl_mode, stable[0], stable[1])
        print(f"\nwrote {a.set_file}")


def write_set(path, cp, sl_mode, sl_value, rr):
    mode = {"zone": "0", "atr": "1", "points": "2"}[sl_mode]
    top = {"D1": "0", "H4": "1", "H1": "2", "M15": "3", "M5": "4"}[cp.top_stage]
    lines = [
        f"InpTopStage={top}",
        f"InpMinRows={cp.min_rows}",
        f"InpMaxRows={cp.max_rows}",
        f"InpGapThreshold={cp.gap_threshold}",
        f"InpCoverage={1 if cp.body_only else 0}",
        f"InpSLMode={mode}",
        f"InpSLZoneBuffer={sl_value if sl_mode == 'zone' else 0.25}",
        f"InpSLATR={sl_value if sl_mode == 'atr' else 1.5}",
        f"InpSLPoints={int(sl_value) if sl_mode == 'points' else 300}",
        "InpTPMode=0",
        f"InpTPRR={rr}",
    ]
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
