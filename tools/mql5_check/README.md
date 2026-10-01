# MQL5 checks without MetaTrader

MetaEditor is not available in the research container, so the EA is verified in two ways:

1. **Syntax / type check** — `mql2cpp.py` rewrites the MQL5-only syntax (dynamic arrays,
   `input`, `#property`) into C++ and compiles it against `mql5_stub.h` (declarations of every
   MQL5 function the EA uses):

   ```bash
   python tools/mql5_check/mql2cpp.py mql5/Experts/VolumeGapCascadeEA.mq5 /tmp/ea.cpp
   g++ -std=c++17 -fsyntax-only -Wall -Wextra -I tools/mql5_check /tmp/ea.cpp
   ```

2. **Behavioural check** — `mql5_emu.h` is a tiny MQL5 runtime (bar data, `iTime`,
   `CopyRates`, `iBarShift`, ATR, logged trade calls). `run_emu_compare.py` runs the real EA
   code tick-by-tick and compares every setup, zone boundary and pin-bar entry with the
   Python research engine:

   ```bash
   python tools/mql5_check/run_emu_compare.py --data <XAUUSD_M5.parquet> --top H4
   ```

   Result on 2019–2021 XAUUSD M5: H1 3035/3035, H4 882/882, D1 170/170 setups identical,
   286/286 H4 pin-bar entries identical.

The emulator follows MT5's documented data semantics; the final word is still a compile and a
Strategy Tester run in MetaTrader 5.
