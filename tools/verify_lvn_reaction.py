"""Control for tools/lvn_reaction.py: on a random walk there is no level
effect, so the void must not beat random levels any more often than chance.

One seed is not enough to judge. The first control run for this test produced
a Weekly "discovery" at p=0.04 on pure noise - 48 events is simply not many -
and only running more seeds showed it was luck. Under a working null the
p-values are roughly uniform: across these seeds about one in twenty should
fall under 0.05, and a cluster of them means the measurement is biased.

    python3 tools/verify_lvn_reaction.py
"""

import sys
import tempfile
from pathlib import Path

import numpy as np

import lvn_reaction as L
from make_synthetic_m1 import generate

SEEDS = (11, 23, 37, 51, 68, 79)


def main():
    pvals = []
    with tempfile.TemporaryDirectory() as d:
        for seed in SEEDS:
            path = Path(d) / f"s{seed}.csv"
            generate(2.0, seed, 2000.0, 0.01, 20).to_csv(path, index=False)
            b = L.load_csv(str(path))
            for tf in ("W1", "D1"):
                r = L.run(b, tf, x_frac=0.2, n_perm=1000)
                if r is None:
                    continue
                pvals.append(r.shuffled_p)
                print(f"seed {seed:>3} {tf}: void {100 * r.void_rate:5.1f}%  "
                      f"shuffled {100 * r.shuffled_rate:5.1f}%  p={r.shuffled_p:.3f}  "
                      f"({r.events} events)")

    p = np.array(pvals)
    small = int((p < 0.05).sum())
    print(f"\n{len(p)} tests, {small} below 0.05 (about {0.05 * len(p):.1f} expected), "
          f"median p {np.median(p):.3f}")
    if small >= 3 or np.median(p) < 0.2:
        print("FAILED - the void beats random levels on random data: the measurement is biased")
        return 1
    print("ok: no level effect found where none exists")
    return 0


if __name__ == "__main__":
    sys.exit(main())
