"""Regression test for the anti-overfit machinery itself.

An optimiser is only worth trusting if it says no when there is nothing there.
This builds a random walk — which by construction contains no edge, and after
spread must lose — runs the whole pipeline over it, and fails if the result
comes back looking tradeable.

The null the cascade is scored against is a displaced zone: same timing, same
zone size, same fade-on-touch mechanics, only the price level is not the one
the clarity search chose. Scoring against a flipped direction instead does not
work — entries always fill on the favourable edge of the touching bar, so the
real direction wins on random data for reasons that have nothing to do with
the algorithm. That mistake is what this file exists to keep out.

If this test ever passes a random walk, the optimiser is broken and every
conclusion it has produced is void.

    python3 tools/verify_optimizer.py
"""

import sys
import tempfile
from pathlib import Path

import numpy as np

from cascade_core import (CascadeParams, ExitParams, build_signals, load_m1_csv,
                          metrics, simulate)
from make_synthetic_m1 import generate
from optimize_cascade import (permutation_test, pick, plateau_smooth, score_grid,
                              _exits)

SL_GRID = [0.0, 0.2, 0.4, 0.7, 1.0, 1.5]
RR_GRID = [0.5, 1.0, 2.0, 3.0]


def run_once(seed: int, years: float = 2.0) -> dict:
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "synth.csv"
        generate(years, seed, 2000.0, 0.01, 20).to_csv(path, index=False)
        m1 = load_m1_csv(str(path))

    sset = build_signals(m1, CascadeParams())
    sigs = sset.signals
    if len(sigs) < 40:
        return dict(skipped=True, trades=len(sigs))

    half = len(sigs) // 2
    train, test = sigs[:half], sigs[half:]

    e, _, _ = score_grid(m1, train, "zone", SL_GRID, RR_GRID, 15, None)
    best = pick(plateau_smooth(e), SL_GRID, RR_GRID)
    if best is None:
        return dict(skipped=True, trades=len(sigs))

    ex = _exits("zone", best[2], best[3])
    oos = metrics(simulate(m1, test, ex))
    real_exp = metrics(simulate(m1, sigs, ex))["expectancy"]
    pt = permutation_test(m1, sset.live_zones, ex, None, real_exp, 120, seed)

    return dict(skipped=False, seed=seed, sl=best[2], rr=best[3],
                is_exp=float(np.nanmax(e)), oos_exp=oos["expectancy"],
                oos_trades=oos["trades"], p=pt["p_value"])


SEEDS = (3, 17, 101, 202, 313, 404)


def main():
    failures = []
    pvals = []

    for seed in SEEDS:
        r = run_once(seed)
        if r.get("skipped"):
            print(f"seed {seed}: skipped, only {r['trades']} signals")
            continue

        print(f"seed {seed:>3}: picked SL={r['sl']} RR={r['rr']} | "
              f"best in-sample {r['is_exp']:+.3f}R | "
              f"out-of-sample {r['oos_exp']:+.3f}R over {r['oos_trades']} trades | "
              f"p={r['p']:.3f}")
        pvals.append(r["p"])

        # A clearly profitable out-of-sample result on a random walk would
        # mean the walk-forward split is leaking.
        if r["oos_exp"] > 0.15:
            failures.append(f"seed {seed}: out-of-sample expectancy {r['oos_exp']:+.3f}R "
                            "on random data suggests a leak")

    if not pvals:
        print("\nFAILED — no seed produced enough signals to judge")
        return 1

    # Under the null a p-value is roughly uniform, so a single small one across
    # several seeds means nothing. A cluster of them does: with 6 seeds you
    # expect about 0.3 below 0.05, and seeing 3 would say the null is biased
    # rather than that a random walk turned out to be tradeable.
    small = sum(1 for p in pvals if p < 0.05)
    print(f"\np-values: {[f'{p:.3f}' for p in pvals]}")
    print(f"below 0.05: {small} of {len(pvals)} (expect about "
          f"{0.05 * len(pvals):.1f} by chance)")
    if small >= 3:
        failures.append(f"{small} of {len(pvals)} seeds beat random levels on random "
                        "data - the null is biased")

    if failures:
        print("\nFAILED — the optimiser found an edge that cannot exist:")
        for f in failures:
            print("  -", f)
        return 1

    print("\nok: the pipeline refuses to find a tradeable edge in a random walk")
    return 0


if __name__ == "__main__":
    sys.exit(main())
