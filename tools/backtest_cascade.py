"""Backtest the LVN Clarity Cascade on M1 CSV exported from MetaTrader.

    python3 tools/backtest_cascade.py --csv m1_export.csv \
        --top-stage D1 --sl-mode zone --sl-zone-buffer 0.25 --tp-rr 2.0
"""

import argparse
import json

from cascade_core import (CascadeParams, ExitParams, build_signals, load_m1_csv,
                          metrics, simulate)


def add_common_args(ap):
    ap.add_argument("--csv", required=True, help="M1 export from ExportM1.mq5")
    ap.add_argument("--symbol", default="")
    ap.add_argument("--point", type=float, default=None,
                    help="price of one point; inferred from the file when omitted")
    ap.add_argument("--real-volume", action="store_true",
                    help="use real volume when the broker supplies it")
    ap.add_argument("--top-stage", default="D1", choices=["D1", "H4", "H1", "M15", "M5"])
    ap.add_argument("--min-rows", type=int, default=3)
    ap.add_argument("--max-rows", type=int, default=8)
    ap.add_argument("--gap-threshold", type=float, default=40.0)
    ap.add_argument("--body-only", action="store_true")


def main():
    ap = argparse.ArgumentParser()
    add_common_args(ap)
    ap.add_argument("--sl-mode", default="zone", choices=["zone", "atr", "points"])
    ap.add_argument("--sl-zone-buffer", type=float, default=0.25)
    ap.add_argument("--sl-atr", type=float, default=1.5)
    ap.add_argument("--sl-points", type=float, default=300.0)
    ap.add_argument("--tp-rr", type=float, default=2.0)
    ap.add_argument("--max-hold-minutes", type=int, default=0)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    m1 = load_m1_csv(a.csv, a.symbol, a.point, a.real_volume)
    cp = CascadeParams(a.top_stage, a.min_rows, a.max_rows, a.gap_threshold, a.body_only)

    sigs = build_signals(m1, cp)
    ex = ExitParams(a.sl_mode, a.sl_zone_buffer, a.sl_atr, a.sl_points,
                    a.tp_rr, a.max_hold_minutes)
    trades = simulate(m1, sigs.signals, ex)
    m = metrics(trades)

    if a.json:
        print(json.dumps(dict(cascade=vars(cp), exits=vars(ex), **m), indent=2))
        return

    span_days = (m1.time[-1] - m1.time[0]) / 86400
    print(f"data      : {len(m1):,} M1 bars, {span_days:.0f} days, point={m1.point}")
    print(f"cascades  : {sigs.cascades_run} run, {sigs.cascades_complete} completed "
          f"({100 * sigs.cascades_complete / max(1, sigs.cascades_run):.0f}%)")
    print(f"            stages reached: "
          f"{dict(sorted(sigs.stage_histogram.items()))}")
    print(f"zones     : {sigs.cascades_complete} watched, "
          f"{sigs.zones_untouched} never touched, {len(sigs.signals)} triggered")
    print()
    print(f"trades    : {m['trades']}")
    print(f"net R     : {m['net_r']:+.1f}")
    print(f"expectancy: {m['expectancy']:+.4f} R per trade")
    print(f"win rate  : {100 * m['win_rate']:.1f}%")
    print(f"profit fac: {m['profit_factor']:.2f}")
    print(f"max DD    : {m['max_dd_r']:.1f} R")
    print(f"sharpe    : {m['sharpe']:.3f} (per trade)")

    if m["trades"]:
        longs = sum(1 for t in trades if t.is_long)
        by_reason = {}
        for t in trades:
            by_reason[t.reason] = by_reason.get(t.reason, 0) + 1
        print(f"direction : {longs} long / {m['trades'] - longs} short")
        print(f"exits     : {by_reason}")


if __name__ == "__main__":
    main()
