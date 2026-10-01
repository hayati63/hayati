"""
Backtest the real PoursamadiEA.mq5 code without MetaTrader: the EA is converted to C++, compiled
against mql5_emu_trade.h (a small trade server: limit/market orders, SL/TP, deal history,
balance) and driven over every M5 bar (open -> low/high -> high/low -> close, OnTick at each).
The EA's trades are then matched one-by-one with the Python research engine
(research/poursamadi.py) and summarised for 2012-2019 and 2020-2025.

    python tools/mql5_check/run_poursamadi_emu.py --data <XAUUSD M5 parquet>
"""
import argparse
import os
import re
import subprocess
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "research"))
from poursamadi import trade_list  # noqa: E402
from vgap_engine import build_rung, load_bars, to_minutes  # noqa: E402

MAGIC = 26100


def positions(deals):
    ins = deals[deals.entry == 0].set_index("pos")
    outs = deals[deals.entry == 1].groupby("pos").agg(out_time=("time", "max"), out_price=("price", "last"),
                                                      profit=("profit", "sum"), comm=("commission", "sum"))
    p = ins[["magic", "dir", "time", "price", "vol", "sl"]].join(outs, how="inner")
    p["net"] = p.profit + p.comm
    p["time"] = pd.to_datetime(p.time, unit="s")
    p["out_time"] = pd.to_datetime(p.out_time, unit="s")
    return p.reset_index()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--start", default="2011-06-01")
    ap.add_argument("--end", default="2025-03-21")
    ap.add_argument("--work", default=os.path.join(HERE, "_work"))
    ap.add_argument("--set", action="append", default=[], help="override an input, e.g. InpAntiMartingale=false")
    a = ap.parse_args()
    os.makedirs(a.work, exist_ok=True)
    base = load_bars(a.data)
    base = base[(base.time >= a.start) & (base.time < a.end)].reset_index(drop=True)
    bt = to_minutes(base["time"])
    o, h, l, c, v = [base[k].values.astype(float) for k in ("open", "high", "low", "close", "volume")]
    ddir = os.path.join(a.work, "pdata")
    os.makedirs(ddir, exist_ok=True)
    for tf in ("M5", "M15", "H1"):
        r = build_rung(bt, o, h, l, c, v, tf, 5)
        pd.DataFrame({"t": r.t * 60, "o": r.o, "h": r.h, "l": r.l, "c": r.c, "v": r.v.astype(int)}).to_csv(
            os.path.join(ddir, f"{tf}.csv"), header=False, index=False, float_format="%.2f")

    cpp = os.path.join(a.work, "pea.cpp")
    subprocess.run([sys.executable, os.path.join(HERE, "mql2cpp.py"),
                    os.path.join(ROOT, "mql5", "Experts", "PoursamadiEA.mq5"), cpp], check=True)
    src = open(cpp).read().replace('#include "mql5_stub.h"', '#include "%s"' % os.path.join(HERE, "mql5_emu_trade.h"))
    src = src.split("\nstring _Symbol; double _Point; int _Digits;")[0]
    for kv in ["InpVerbose=false"] + a.set:
        k, val = kv.split("=")
        src, n = re.subn(r"(const\s+\w+\s+%s\s*=\s*)[^;]+;" % k, r"\g<1>%s;" % val, src)
        assert n == 1, k
    src += "\n" + open(os.path.join(HERE, "emu_trade_main.inc")).read()
    emu = os.path.join(a.work, "pea_emu.cpp")
    open(emu, "w").write(src)
    exe = os.path.join(a.work, "pea_emu")
    subprocess.run(["g++", "-std=c++17", "-O2", "-Wall", "-Wno-unused", "-o", exe, emu], check=True)
    deals_csv = os.path.join(a.work, "pea_deals.csv")
    subprocess.run([exe, ddir, deals_csv], check=True)
    p = positions(pd.read_csv(deals_csv))

    # ---- EA trades in R ----
    main_ = p[p.magic == MAGIC].copy()
    add = p[p.magic == MAGIC + 1]
    add_net = []
    for _, r in main_.iterrows():
        m = add[(add.dir == r.dir) & (add.time >= r.time) & (add.time <= r.out_time)]
        add_net.append(m.net.sum())
    main_["R"] = (main_.net + np.array(add_net)) / (1.5 * (main_.price - main_.sl).abs() * 100 * main_.vol)
    main_["setup"] = "SP2L"
    btb = p[p.magic == MAGIC + 2].copy()
    btb["R"] = btb.net / ((btb.price - btb.sl).abs() * 100 * btb.vol)
    btb["setup"] = "BTB"
    ea = pd.concat([main_, btb])
    ea = ea[ea.time >= "2012-01-01"]

    # ---- Python reference ----
    py = {"SP2L": trade_list(base, "H1", "SP2L", ns=3, m=1.0, entry="main+50%", mgmt="RR3"),
          "BTB": trade_list(base, "M15", "BTB", lvl="prevday", strong=1, mode=3, mgmt="RR3", min_lv=2)}
    py["SP2L"] = py["SP2L"][py["SP2L"].trend_ok]
    py["BTB"] = py["BTB"][py["BTB"].window]
    rows = []
    for name, tf in (("SP2L", "h"), ("BTB", "15min")):
        e = ea[ea.setup == name].copy()
        e["key"] = list(zip(e.time.dt.floor(tf), e.dir))
        q = py[name].copy()
        q["key"] = list(zip(pd.to_datetime(q.time), q.dir))
        both = e.merge(q[["key", "R"]], on="key", suffixes=("_ea", "_py"))
        rows.append(dict(setup=name, ea_trades=len(e), python_trades=len(q), matched=len(both),
                         same_result_sign=float((np.sign(both.R_ea) == np.sign(both.R_py)).mean()),
                         corr=float(np.corrcoef(both.R_ea, both.R_py)[0, 1]),
                         ea_avgR=e.R.mean(), py_avgR=q.R.mean()))
        for per, msk in (("2012-2019", e.time < "2020-01-01"), ("2020-2025", e.time >= "2020-01-01")):
            rows[-1][f"ea_avgR_{per}"] = e[msk].R.mean()
    cmp_ = pd.DataFrame(rows).round(3)
    pd.set_option("display.width", 220)
    print(cmp_.to_string(index=False))

    # ---- balance curve of the EA (its own money management) ----
    ea = ea.sort_values("out_time")
    allp = p[p.time >= "2012-01-01"].sort_values("out_time")
    bal = 10000 + allp.net.cumsum()
    peak = bal.cummax()
    dd = (1 - bal / peak).max() * 100
    print(f"EA balance 2012-2025: 10000 -> {bal.iloc[-1]:.0f}  max drawdown {dd:.1f}%")
    for per, msk in (("2012-2019", allp.time < "2020-01-01"), ("2020-2025", allp.time >= "2020-01-01")):
        x = allp[msk]
        b0 = 10000 + allp[allp.out_time < x.time.min()].net.sum()
        b = b0 + x.net.cumsum()
        print(f"  {per}: {100 * (b.iloc[-1] / b0 - 1):+.1f}%  maxDD {(1 - b / np.maximum(b.cummax(), b0)).max() * 100:.1f}%")
    out = os.path.join(ROOT, "research", "results", "poursamadi_ea_emulator_trades.csv")
    ea[["setup", "time", "out_time", "dir", "price", "sl", "vol", "net", "R"]].to_csv(out, index=False)
    cmp_.to_csv(os.path.join(ROOT, "research", "results", "poursamadi_ea_vs_python.csv"), index=False)


if __name__ == "__main__":
    main()
