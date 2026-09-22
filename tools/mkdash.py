# -*- coding: utf-8 -*-
"""همهٔ چیزی که داشبورد لازم دارد، در یک JSON."""
import sys, json
from pathlib import Path
from collections import defaultdict
sys.path.insert(0, "tools")
from monthly_backtest import load_daily, norm
from vp_box import make_box, state
from weekly_backtest import week_key
from tomorrow import read_holdings
from breadth import DRIVER_FILE, NAME, box_states

out = {}
out["month"]  = json.loads(Path("data/evidence_month.json").read_text(encoding="utf-8"))
out["week"]   = json.loads(Path("data/evidence_week.json").read_text(encoding="utf-8"))
out["combo"]  = json.loads(Path("data/evidence_combo.json").read_text(encoding="utf-8"))
out["tom"]    = json.loads(Path("data/tomorrow.json").read_text(encoding="utf-8"))
wf = Path("data/walkforward.json")
if wf.exists():
    w = json.loads(wf.read_text(encoding="utf-8"))
    out["wf"] = {k: w.get(k) for k in
                 ("fee", "n", "span", "weekly", "monthly", "weekly_sticky",
                  "monthly_sticky", "base_weekly", "base_monthly",
                  "turn_weekly", "turn_monthly", "turn_weekly_sticky",
                  "turn_monthly_sticky")}
at = Path("data/attribution.json")
if at.exists():
    out["attr"] = json.loads(at.read_text(encoding="utf-8"))

# وضعیت باکس نمادهای پرتفوی فعلی
holds = read_holdings("data/holdings.txt")
want = {norm(k): k for k in holds}
cur = []
for p in sorted(Path("data_auto").glob("*.csv")):
    name = p.stem.replace("_daily","").replace("_"," ")
    if norm(name) not in want: continue
    rows = load_daily(p)
    if len(rows) < 40: continue
    st = box_states(rows, "valley_first")
    if not st: continue
    cur.append({"sym": name, "units": holds[want[norm(name)]],
                "close": st["close"], "mst": st["mst"], "wst": st["wst"],
                "mrisk": round(st["mrisk"],1), "wrisk": round(st["wrisk"],1)})
cur.sort(key=lambda r: -r["units"]*r["close"])
tot = sum(r["units"]*r["close"] for r in cur)
for r in cur: r["pct"] = round(r["units"]*r["close"]/tot*100, 1)
out["current"] = cur

# محرک‌ها — با تعداد کندلِ پشتِ باکس هفتگی
drv = []
for did, fn in list(DRIVER_FILE.items()) + [("xau", "اونس_طلا")]:
    p = Path("data/drivers_daily") / f"{fn}_daily.csv"
    if not p.exists():
        drv.append({"id": did, "name": NAME.get(did, did), "missing": True}); continue
    st = box_states(load_daily(p), "valley_first")
    if not st: continue
    drv.append({"id": did, "name": NAME.get(did, did), "close": st["close"],
                "mst": st["mst"], "wst": st["wst"], "wbars": st["wbars"],
                "wok": st["wok"], "mrisk": round(st["mrisk"],1),
                "wrisk": round(st["wrisk"],1), "anchor": st.get("anchor")})
out["drivers"] = drv

Path("data/dash.json").write_text(json.dumps(out, ensure_ascii=False,
    default=str, separators=(",",":")), encoding="utf-8")
print("نوشته شد:", Path("data/dash.json").stat().st_size, "بایت")
print("پرتفوی فعلی:", len(cur), "· محرک:", len(drv), "· واجد شرط:", out["tom"]["eligible"])
