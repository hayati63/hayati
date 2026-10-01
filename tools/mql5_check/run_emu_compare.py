"""
Behavioural check of the EA without MetaTrader: the real EA source is converted to C++,
compiled against a small MQL5 runtime emulator (mql5_emu.h) and run tick-by-tick (one tick
per M5 bar open).  Every setup the EA creates is compared with the Python research engine.

    python tools/mql5_check/run_emu_compare.py --data <XAUUSD M5 parquet/csv> --top H4
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
from vgap_engine import CascadeConfig, _scan_reaction, build_rung, generate_signals, load_bars, to_minutes  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="M5 bars (parquet or csv)")
    ap.add_argument("--top", default="H1", choices=["H1", "H4", "D1"])
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default="2022-01-01")
    ap.add_argument("--work", default=os.path.join(HERE, "_work"))
    a = ap.parse_args()
    os.makedirs(a.work, exist_ok=True)

    base = load_bars(a.data)
    base = base[(base.time >= a.start) & (base.time < a.end)].reset_index(drop=True)
    bt = to_minutes(base["time"])
    o, h, l, c, v = [base[k].values.astype(float) for k in ("open", "high", "low", "close", "volume")]
    ddir = os.path.join(a.work, "data")
    os.makedirs(ddir, exist_ok=True)
    for tf in ("M5", "M15", "H1", "H4", "D1"):
        r = build_rung(bt, o, h, l, c, v, tf, 5)
        pd.DataFrame({"t": r.t * 60, "o": r.o, "h": r.h, "l": r.l, "c": r.c, "v": r.v.astype(int)}).to_csv(
            os.path.join(ddir, f"{tf}.csv"), header=False, index=False, float_format="%.2f")

    ea_src = os.path.join(ROOT, "mql5", "Experts", "VolumeGapCascadeEA.mq5")
    cpp = os.path.join(a.work, "ea.cpp")
    subprocess.run([sys.executable, os.path.join(HERE, "mql2cpp.py"), ea_src, cpp], check=True)
    src = open(cpp).read().replace('#include "mql5_stub.h"', '#include "%s"' % os.path.join(HERE, "mql5_emu.h"))
    src = src.split("\nstring _Symbol; double _Point; int _Digits;")[0]
    over = {"InpTopTF": "VGC_TOP_" + a.top, "InpUseM1Stage": "false", "InpVerbose": "true", "InpDraw": "false",
            "InpTradeZ0": "true", "InpTradeZ1": "true", "InpTradeZ2": "true", "InpTradePin": "true"}
    for k, val in over.items():
        src, n = re.subn(r"(const\s+\w+\s+%s\s*=\s*)[^;]+;" % k, r"\g<1>%s;" % val, src)
        assert n == 1, k
    src += "\n" + open(os.path.join(HERE, "emu_main.inc")).read()
    emu_cpp = os.path.join(a.work, "ea_emu.cpp")
    open(emu_cpp, "w").write(src)
    exe = os.path.join(a.work, "ea_emu")
    subprocess.run(["g++", "-std=c++17", "-O2", "-w", "-o", exe, emu_cpp], check=True)
    out = subprocess.run([exe, ddir], capture_output=True, text=True, check=True).stdout

    pat = re.compile(r"^(\S+ \S+)\|VGC: setup #(\d+) (BUY|SELL) (direct|waited) entries=(on|off)(.*)$")
    zpat = re.compile(r"\[(\w+) (gap|none) ([\d.]+)-([\d.]+)\]")
    ea = []
    for line in out.splitlines():
        m = pat.match(line)
        if m:
            ea.append(dict(time=pd.Timestamp(m.group(1).replace(".", "-", 2)), dir=1 if m.group(3) == "BUY" else -1,
                           zones=[(g == "gap", float(b), float(t)) for _, g, b, t in zpat.findall(m.group(6))]))
    ea = pd.DataFrame(ea)
    sig, aux = generate_signals(base, CascadeConfig(top=a.top, base_tf="M5"))
    warm = pd.Timestamp(a.start) + pd.Timedelta(days=9)
    py = sig.df[sig.df.sig_time >= warm]
    ea = ea[ea.time >= warm]
    key = {(r.sig_time, r.dir): i for i, r in py.iterrows()}
    ok = bad = 0
    for _, r in ea.iterrows():
        i = key.get((r.time, r.dir))
        if i is None:
            continue
        same = True
        for li, (found, b, t) in enumerate(r.zones):
            pt, pb = sig.zones_top[i, li], sig.zones_bot[i, li]
            if (not np.isnan(pt)) != found or (found and (abs(pt - t) > 0.011 or abs(pb - b) > 0.011)):
                same = False
        ok += same
        bad += not same
    ea_keys, py_keys = set(zip(ea.time, ea.dir)), set(key)
    print(f"top={a.top}: python signals={len(py)} EA setups={len(ea)} identical={ok} zone-mismatch={bad} "
          f"EA-only={len(ea_keys - py_keys)} python-only={len(py_keys - ea_keys)}")

    bt_, o_, h_, l_, c_ = aux["base_t"], aux["o"], aux["h"], aux["l"], aux["c"]
    si = sig.df.sig_idx.values.astype(np.int64)
    d = sig.df.dir.values.astype(np.int64)
    nb = len(bt_)
    end = np.minimum(np.full(len(si), nb, dtype=np.int64), np.r_[si[1:], nb])
    ridx = np.full(len(si), -1, dtype=np.int64)
    _scan_reaction(o_, h_, l_, c_, d, si, end, sig.zones_top[:, 0], sig.zones_bot[:, 0], 1, 0.30, ridx)
    py_pin = {t for t in pd.to_datetime(bt_[ridx[ridx >= 0] + 1] * 60, unit="s") if t >= warm}
    ea_pin = {pd.Timestamp(ln.split("|")[0].replace(".", "-", 2)) for ln in out.splitlines()
              if "|TRADE BUY " in ln or "|TRADE SELL " in ln}
    ea_pin = {t for t in ea_pin if t >= warm}
    print(f"pin-bar entries: python={len(py_pin)} EA={len(ea_pin)} identical={len(py_pin & ea_pin)}")
    sys.exit(0 if (bad == 0 and ea_keys == py_keys and py_pin == ea_pin) else 1)


if __name__ == "__main__":
    main()
