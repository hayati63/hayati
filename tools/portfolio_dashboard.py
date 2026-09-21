# -*- coding: utf-8 -*-
"""
داشبورد پرتفوی چنددارایی — روی دادهٔ واقعی `dashboard_monthly.html`.

ورودی همان فایلی است که `dashboard_monthly.py` می‌سازد؛ این اسکریپت چهار
آرایهٔ جاسازی‌شده‌اش را بیرون می‌کشد (TODAY، TRADES، SUMMARY، SIGNALS) و
داشبورد را با تم خود همان فایل بازمی‌سازد، به‌علاوهٔ:

  · پرتفوی چنددارایی با تفکیک عاملی — سهام‌محور در برابر فلزات
  · ماتریس همبستگی دسته‌ها از بازده ماهانهٔ خودِ بک‌تست
  · وزن کمینه‌واریانس دو عاملی، محاسبه‌شده از همان بازده‌ها
  · تفکیک معاملهٔ بسته‌شده از باز — که عدد سرصفحه را عوض می‌کند
  · ریسک تا باکس ماه جاری **و** ماه قبل، چون ماه هنوز بسته نشده

اجرا:
    python3 tools/portfolio_dashboard.py --in dashboard_monthly.html \
        --out portfolio.html --capital 1000000000
"""

import argparse
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from drivers import (  # noqa: E402
    CERTIFICATES, DRIVERS, EXPOSURE, SUBSECTOR, coverage, gate, group_of,
)

# دسته‌های خام → عامل. پایهٔ تفکیک، ماتریس همبستگی خودِ داده است.
FACTOR = {
    "سهامی": "سهام‌محور", "شاخصی": "سهام‌محور", "اهرمی": "سهام‌محور",
    "بخشی": "سهام‌محور", "مختلط": "سهام‌محور", "صندوق_در_صندوق": "سهام‌محور",
    "طلا": "فلزات", "نقره": "فلزات",
    "املاک": "املاک", "کالا_کشاورزی": "کالا",
}
FACTORS = ["سهام‌محور", "فلزات", "املاک", "کالا"]
OPEN_MONTH = "تا امروز"


def extract(html_path):
    s = Path(html_path).read_text(encoding="utf-8")
    out = {}
    for name in ("TODAY", "TRADES", "SUMMARY", "SIGNALS"):
        m = re.search(r"(?:var|const|let)\s+" + name + r"\s*=\s*", s)
        if not m:
            out[name] = []
            continue
        j = m.end()
        depth, k = 0, j
        while k < len(s):
            if s[k] in "[{":
                depth += 1
            elif s[k] in "]}":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        out[name] = json.loads(s[j:k + 1])
    return out


def mean(xs):
    return statistics.mean(xs) if xs else None


def pearson(a, b):
    p = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(p) < 3:
        return None
    xs = [x for x, _ in p]
    ys = [y for _, y in p]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in p)
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return num / den if den else None


def min_var_weight(ra, rb):
    """وزن کمینه‌واریانس عامل A در سبد دو عاملی.

    w = (σ²b − ρσaσb) / (σ²a + σ²b − 2ρσaσb)

    فقط ماه‌هایی که هر دو عامل داده دارند استفاده می‌شوند، وگرنه کوواریانس
    از دو بازهٔ زمانی متفاوت حساب می‌شود.
    """
    pair = [(x, y) for x, y in zip(ra, rb) if x is not None and y is not None]
    if len(pair) < 3:
        return None, None, len(pair)
    xs = [x for x, _ in pair]
    ys = [y for _, y in pair]
    sa, sb = statistics.pstdev(xs), statistics.pstdev(ys)
    rho = pearson(xs, ys)
    if rho is None or (sa == 0 and sb == 0):
        return None, rho, len(pair)
    den = sa * sa + sb * sb - 2 * rho * sa * sb
    if abs(den) < 1e-12:
        return None, rho, len(pair)
    w = (sb * sb - rho * sa * sb) / den
    return max(0.0, min(1.0, w)), rho, len(pair)


DRIVER_ROW = re.compile(
    r"^(?P<sym>.+?)\s*\|\s*کلوز\s*(?P<close>[\d.]+)\s*\|\s*"
    r"جاری\s*(?P<lo>[\d.]+)-(?P<hi>[\d.]+)\s*ریسک\s*(?P<risk>-?[\d.]+)%\s*"
    r"(?P<st>\S+)"
)
_ST = {"سبز": "بالا", "قرمز": "زیر", "داخل": "داخل"}
_ALIAS = {
    "دلار": "dollar", "دلارآزاد": "dollar", "usd": "dollar",
    "تتر": "usdt", "usdtirt": "usdt", "usdt": "usdt",
    "اونسطلا": "xau", "انسطلا": "xau", "xau": "xau", "طلایجهانی": "xau",
    "اونسنقره": "xag", "انسنقره": "xag", "xag": "xag", "نقرهجهانی": "xag",
    "نفت": "oil", "برنت": "oil", "oil": "oil", "brent": "oil",
    "مس": "copper", "copper": "copper",
    "شاخصکل": "tedpix", "شاخص": "tedpix", "tedpix": "tedpix",
    "شاخصهموزن": "eqwt", "هموزن": "eqwt", "شاخصکلهموزن": "eqwt",
}


def parse_drivers(path):
    """فایل محرک‌ها، با همان قالب خروجی `export_monthly_risk.py`."""
    out = {}
    if not path or not Path(path).exists():
        return out
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "=")):
            continue
        m = DRIVER_ROW.match(line)
        if not m:
            continue
        g = m.groupdict()
        key = re.sub(r"[\s_\-‌]+", "", g["sym"].strip()).lower()
        did = _ALIAS.get(key)
        if not did:
            continue
        out[did] = {"close": float(g["close"]), "lo": float(g["lo"]),
                    "hi": float(g["hi"]), "risk": float(g["risk"]),
                    "state": _ST.get(g["st"], g["st"]), "real": True}
    return out


def proxy_state(rows, group):
    """وضعیت پروکسی یک گروه: حالت اکثریت نمادهایش."""
    sel = [r for r in rows if r.get("group") == group or r.get("cat") == group]
    if not sel:
        return None
    c = defaultdict(int)
    for r in sel:
        c[{"سبز": "بالا", "قرمز": "زیر"}.get(r["st"], r["st"])] += 1
    top = max(c.items(), key=lambda kv: kv[1])
    risks = sorted(r["risk"] for r in sel)
    return {"state": top[0], "n": len(sel), "share": top[1] / len(sel) * 100,
            "risk": risks[len(risks) // 2], "real": False}


def analyse(data):
    today, trades, summary = data["TODAY"], data["TRADES"], data["SUMMARY"]

    closed = [t for t in trades if t["ماه_خروج"] != OPEN_MONTH]
    open_t = [t for t in trades if t["ماه_خروج"] == OPEN_MONTH]

    def stat(rows):
        v = [t["بازده٪"] for t in rows]
        if not v:
            return None
        return {"n": len(v), "win": sum(1 for x in v if x > 0) / len(v) * 100,
                "avg": mean(v), "med": statistics.median(v)}

    # ── ماه‌به‌ماه، فقط بسته‌شده ──
    bym = defaultdict(list)
    for t in closed:
        bym[t["ماه_خروج"]].append(t["بازده٪"])
    months = sorted(bym)
    monthly = [{"m": m, "n": len(bym[m]), "avg": mean(bym[m]),
                "win": sum(1 for x in bym[m] if x > 0) / len(bym[m]) * 100}
               for m in months]

    # ── بازده ماهانهٔ هر عامل ──
    fm = defaultdict(lambda: defaultdict(list))
    for t in closed:
        fm[FACTOR.get(t["دسته"], "سایر")][t["ماه_خروج"]].append(t["بازده٪"])

    # ── همان کار، ولی روی گروه (بخشی شکسته به زیربخش) ──
    gm = defaultdict(lambda: defaultdict(list))
    for t in closed:
        gm[group_of(t["نماد"], t["دسته"])][t["ماه_خروج"]].append(t["بازده٪"])
    fseries = {f: [mean(fm[f].get(m, [])) for m in months]
               for f in FACTORS if f in fm}

    # ── همبستگی بین عامل‌ها ──
    keys = [f for f in FACTORS if f in fseries]
    corr = {a: {b: pearson(fseries[a], fseries[b]) for b in keys} for a in keys}

    fstats = {}
    for f in keys:
        v = [x for x in fseries[f] if x is not None]
        fstats[f] = {"months": len(v), "avg": mean(v),
                     "vol": statistics.pstdev(v) if len(v) > 1 else None}

    mv_w, mv_rho, mv_n = (None, None, 0)
    if "سهام‌محور" in fseries and "فلزات" in fseries:
        mv_w, mv_rho, mv_n = min_var_weight(fseries["سهام‌محور"], fseries["فلزات"])

    # ── کارنامهٔ هر نماد با انقباض به میانگین دسته ──
    cat_avg = defaultdict(list)
    for s in summary:
        if s.get("میانگین_بازده٪") is not None:
            cat_avg[s["دسته"]].append(s["میانگین_بازده٪"])
    cat_mean = {c: mean(v) for c, v in cat_avg.items()}
    overall = mean([s["میانگین_بازده٪"] for s in summary
                    if s.get("میانگین_بازده٪") is not None]) or 0.0

    K = 3.0     # قدرت انقباض: با n=3 وزن نماد و دسته برابر می‌شود
    rec = {}
    for s in summary:
        n = s.get("تعداد") or 0
        raw = s.get("میانگین_بازده٪")
        if raw is None:
            continue
        prior = cat_mean.get(s["دسته"], overall)
        rec[s["نماد"]] = {
            "n": n, "raw": raw, "win": s.get("موفقیت٪"),
            "shrunk": (n * raw + K * prior) / (n + K),
            "cat": s["دسته"],
        }

    # ── امروز ──
    rows = []
    for r in today:
        name = r["نماد"]
        b = rec.get(name, {})
        rows.append({
            "sym": name, "cat": r["دسته"],
            "factor": FACTOR.get(r["دسته"], "سایر"),
            "close": r["کلوز"],
            "lo": r["لو_جاری"], "hi": r["های_جاری"],
            "risk": r["ریسک_جاری"], "st": r["وضعیت_جاری"],
            "plo": r.get("لو_قبل"), "phi": r.get("های_قبل"),
            "prisk": r.get("ریسک_قبل"), "pst": r.get("وضعیت_قبل"),
            "bt_n": b.get("n"), "bt_win": b.get("win"),
            "bt_avg": b.get("raw"), "score": b.get("shrunk"),
            "group": group_of(name, r["دسته"]),
        })

    # ── ریسک ورود در برابر بازده، روی معاملات بسته‌شده ──
    buckets = []
    for lo, hi in ((0, 1), (1, 2), (2, 4), (4, 7), (7, 1e9)):
        v = [t["بازده٪"] for t in closed if lo <= t["ریسک_ورود٪"] < hi]
        if len(v) >= 8:
            buckets.append({"label": f"{lo:g}–{hi:g}٪" if hi < 1e9 else f"بالای {lo:g}٪",
                            "n": len(v), "avg": mean(v),
                            "win": sum(1 for x in v if x > 0) / len(v) * 100})

    # ── بتای هر گروه نسبت به پروکسی شاخص، روی معاملات بسته‌شده ──
    gser = {g: [mean(gm[g].get(m, [])) for m in months] for g in gm}
    base = gser.get("شاخصی")
    gold = gser.get("طلا")

    def beta_of(y, x):
        pr = [(a, b) for a, b in zip(x or [], y) if a is not None and b is not None]
        if len(pr) < 3:
            return None, None, len(pr)
        xs = [a for a, _ in pr]
        ys = [b for _, b in pr]
        mx, my = statistics.mean(xs), statistics.mean(ys)
        cov = sum((a - mx) * (b - my) for a, b in pr) / len(pr)
        vx = sum((a - mx) ** 2 for a in xs) / len(pr)
        vy = sum((b - my) ** 2 for b in ys) / len(pr)
        r = cov / math.sqrt(vx * vy) if vx > 0 and vy > 0 else None
        return r, (cov / vx if vx > 0 else None), len(pr)

    groups = []
    for g, seq in sorted(gser.items(),
                         key=lambda kv: -sum(1 for v in kv[1] if v is not None)):
        v = [x for x in seq if x is not None]
        if not v:
            continue
        r_i, b_i, n_i = beta_of(seq, base)
        r_g, b_g, n_g = beta_of(seq, gold)
        groups.append({
            "g": g, "months": len(v), "avg": mean(v),
            "rho_idx": r_i, "beta_idx": b_i, "n_idx": n_i,
            "rho_gold": r_g, "beta_gold": b_g, "n_gold": n_g,
            "exposure": EXPOSURE.get(g, {}),
        })

    return {
        "rows": rows, "monthly": monthly, "months": months,
        "groups": groups, "gser": gser,
        "all": stat(trades), "closed": stat(closed), "open": stat(open_t),
        "factors": keys, "fseries": fseries, "fstats": fstats, "corr": corr,
        "mv": {"w": mv_w, "rho": mv_rho, "n": mv_n},
        "buckets": buckets,
        "cats": sorted({r["cat"] for r in rows}),
    }


TEMPLATE = r"""<title>پرتفوی چنددارایی ETF</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;600;800&display=swap">
<style>
:root{
  color-scheme: dark;
  --bg:#0f1419; --card:#1a2332; --card-2:#243044; --border:#2d3a4f;
  --text:#e7ecf3; --muted:#8b9cb3;
  --green:#3dd68c; --red:#f56565; --yellow:#ecc94b; --blue:#63b3ed;
  --c1:#4299e1; --c2:#dd6b20; --c3:#9f7aea; --c4:#0d9488;
  --ui:"Vazirmatn","Segoe UI",Tahoma,sans-serif;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:var(--ui);
  direction:rtl;font-size:14px;line-height:1.7;-webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding-inline:16px;padding-block:0 60px}
h1,h2,h3{margin:0;text-wrap:balance}
.num{font-family:var(--mono);font-variant-numeric:tabular-nums;direction:ltr;
  display:inline-block;unicode-bidi:isolate}

header{background:var(--card);border-bottom:1px solid var(--border);
  position:sticky;top:env(safe-area-inset-top,0px);z-index:30}
.hd{max-width:1180px;margin:0 auto;padding:14px 16px;display:flex;
  flex-wrap:wrap;gap:8px 18px;align-items:baseline}
h1{font-size:19px;font-weight:800}
.muted{color:var(--muted);font-size:12px}
.grow{flex:1 1 auto}

.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0 6px}
.tab{background:var(--card);border:1px solid var(--border);color:var(--text);
  padding:8px 16px;border-radius:20px;cursor:pointer;font-family:var(--ui);
  font-size:13px}
.tab:hover{border-color:var(--blue)}
.tab.active{background:var(--blue);border-color:var(--blue);color:#0f1419;
  font-weight:600}
.tab:focus-visible{outline:2px solid var(--blue);outline-offset:2px}
.panel{display:none;margin-top:16px}
.panel.active{display:block}

.lede{color:var(--muted);font-size:13px;margin:0 0 16px;max-width:70ch}
h2{font-size:17px;font-weight:800;margin:26px 0 4px}
h2:first-child{margin-top:0}
h3{font-size:14px;font-weight:600;color:var(--muted);margin:22px 0 8px}

.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(152px,1fr));gap:10px}
.kpi{background:var(--card);border:1px solid var(--border);border-radius:12px;
  padding:14px 16px}
.kpi .k{font-size:11.5px;color:var(--muted)}
.kpi .v{font-size:25px;font-weight:800;margin-top:2px}
.kpi .s{font-size:11.5px;color:var(--muted)}
.kpi.g .v{color:var(--green)} .kpi.r .v{color:var(--red)}
.kpi.y .v{color:var(--yellow)} .kpi.b .v{color:var(--blue)}

.box{background:var(--card);border:1px solid var(--border);border-radius:12px;
  overflow:hidden}
.scroll{overflow:auto;max-height:66vh}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:right;padding:10px 12px;background:var(--card-2);color:var(--muted);
  position:sticky;top:0;font-weight:600;font-size:11.5px;white-space:nowrap;z-index:1}
td{padding:9px 12px;border-top:1px solid var(--border);white-space:nowrap}
tbody tr:hover td{background:#1e2a3c}
td.n,th.n{font-family:var(--mono);font-variant-numeric:tabular-nums;
  direction:ltr;text-align:right}
tfoot td{background:var(--card-2);font-weight:700;border-top:2px solid var(--border)}

.badge{display:inline-block;padding:2px 9px;border-radius:12px;font-size:11.5px;
  font-weight:600;line-height:1.55}
.b-up{background:rgba(61,214,140,.15);color:var(--green)}
.b-mid{background:rgba(236,201,75,.15);color:var(--yellow)}
.b-dn{background:rgba(245,101,101,.15);color:var(--red)}
.b-f{background:rgba(99,179,237,.13);color:var(--blue)}
tbody tr.hl td{background:rgba(61,214,140,.07)}
tbody tr.hl td:first-child{box-shadow:inset 3px 0 0 var(--green)}

.chips{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 14px}
.chip{padding:4px 12px;border-radius:12px;font-size:12px;border:1px solid var(--border);
  cursor:pointer;background:var(--card);color:var(--text);font-family:var(--ui)}
.chip.on{border-color:var(--green);color:var(--green)}
.chip:focus-visible{outline:2px solid var(--blue);outline-offset:2px}

.ctrl{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end;margin:0 0 16px}
.ctrl label{display:flex;flex-direction:column;gap:5px;font-size:11.5px;color:var(--muted)}
.ctrl input{font-family:var(--mono);font-size:14px;direction:ltr;text-align:right;
  padding:8px 11px;border:1px solid var(--border);border-radius:8px;
  background:var(--card);color:var(--text);width:152px}
.ctrl input:focus-visible{outline:2px solid var(--blue);outline-offset:1px}

.note{border:1px solid var(--border);border-radius:12px;padding:13px 16px;
  font-size:13px;background:var(--card);margin:14px 0}
.note.warn{border-color:rgba(236,201,75,.45);background:rgba(236,201,75,.08)}
.note.bad{border-color:rgba(245,101,101,.45);background:rgba(245,101,101,.08)}
.note.ok{border-color:rgba(61,214,140,.45);background:rgba(61,214,140,.07)}
.note b{font-weight:800}

.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--muted);
  margin:0 0 10px}
.legend i{width:10px;height:10px;border-radius:2px;display:inline-block;
  margin-inline-end:6px;vertical-align:-1px}
figure{margin:0;padding:14px 12px 6px}
figcaption{font-size:11.5px;color:var(--muted);padding:0 4px 8px}
svg{display:block;max-width:100%;height:auto}
svg text{direction:ltr;unicode-bidi:isolate}
.gauge{width:110px;height:18px;display:block}
.bar{position:relative;height:16px;background:#222e42;border-radius:3px;
  overflow:hidden;direction:ltr}
.bar i{position:absolute;top:2px;bottom:2px;border-radius:3px}
.tip{position:fixed;pointer-events:none;background:#e7ecf3;color:#0f1419;
  font-size:11.5px;padding:6px 9px;border-radius:6px;opacity:0;z-index:60;
  white-space:pre;font-family:var(--mono);direction:ltr}
.foot{margin-top:40px;padding-top:16px;border-top:1px solid var(--border);
  color:var(--muted);font-size:12px}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style>

<header><div class="hd">
  <h1>پرتفوی چنددارایی ETF</h1>
  <span class="muted" id="meta"></span>
  <span class="grow"></span>
  <span class="muted num" id="stamp"></span>
</div></header>

<div class="wrap">
  <div class="tabs" id="tabs" role="tablist"></div>
  <div id="panels"></div>
  <p class="foot">ساخته‌شده از دادهٔ <span class="num">dashboard_monthly.html</span>
    خودتان. خوانش قاعده‌های شما روی دادهٔ شماست، نه توصیهٔ مالی.</p>
</div>
<div class="tip" id="tip"></div>

<script>
const D = __DATA__;
const tip = document.getElementById('tip');
const f2 = v => v==null?'—':(v>=0?'+':'')+v.toFixed(2);
const pc = v => v==null?'—':v.toFixed(1)+'٪';
const money = v => v==null?'—':Math.round(v).toLocaleString('en-US');
const esc = s => String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const stCls = s => s==='سبز'?'b-up':(s==='قرمز'?'b-dn':'b-mid');
const FC = {'سهام‌محور':'var(--c1)','فلزات':'var(--c2)','املاک':'var(--c3)','کالا':'var(--c4)'};

function showTip(e,t){ tip.textContent=t; tip.style.opacity='1';
  tip.style.left=Math.min(e.clientX+12,innerWidth-200)+'px';
  tip.style.top=(e.clientY+14)+'px'; }
function hideTip(){ tip.style.opacity='0'; }

function gauge(lo,hi,c){
  if(lo==null||hi==null) return '';
  const sp=Math.max(hi-lo,1e-9), pad=sp*1.7, a=lo-pad, b=hi+pad, W=110,H=18;
  const x=v=>((v-a)/(b-a))*W;
  const bx=x(lo), bw=Math.max(x(hi)-x(lo),2), cx=Math.max(2,Math.min(W-2,x(c)));
  const col=c>hi?'var(--green)':(c<lo?'var(--red)':'var(--yellow)');
  return `<svg class="gauge" viewBox="0 0 ${W} ${H}" role="img" aria-label="کلوز نسبت به باکس">
    <line x1="0" y1="9" x2="${W}" y2="9" stroke="var(--border)"/>
    <rect x="${bx.toFixed(1)}" y="4" width="${bw.toFixed(1)}" height="10" rx="2"
      fill="var(--blue)" opacity=".25"/>
    <rect x="${bx.toFixed(1)}" y="4" width="${bw.toFixed(1)}" height="10" rx="2"
      fill="none" stroke="var(--blue)"/>
    <circle cx="${cx.toFixed(1)}" cy="9" r="3.4" fill="${col}" stroke="var(--card)"
      stroke-width="1.6"/></svg>`;
}

/* میله‌های دوقطبی ماهانه */
function monthChart(rows){
  if(!rows.length) return '<p class="lede" style="padding:16px">ماهی نیست.</p>';
  const W=Math.max(340,rows.length*54+70),H=210,L=46,R=14,T=16,B=44;
  const iw=W-L-R, ih=H-T-B;
  const m=Math.max(1,...rows.map(r=>Math.abs(r.avg)))*1.15;
  const y=v=>T+ih/2-(v/m)*(ih/2);
  const bw=Math.min(30,iw/rows.length*.6);
  let g='',b='',x='';
  [-m,-m/2,0,m/2,m].forEach(v=>{
    g+=`<line x1="${L}" y1="${y(v).toFixed(1)}" x2="${W-R}" y2="${y(v).toFixed(1)}"
      stroke="${v===0?'var(--muted)':'var(--border)'}"/>
      <text x="${L-7}" y="${(y(v)+3.5).toFixed(1)}" text-anchor="end" font-size="9.5"
      font-family="var(--mono)" fill="var(--muted)">${v>0?'+':''}${v.toFixed(0)}</text>`;
  });
  rows.forEach((r,i)=>{
    const cx=L+iw*((i+.5)/rows.length), y0=y(0), y1=y(r.avg);
    b+=`<rect x="${(cx-bw/2).toFixed(1)}" y="${Math.min(y0,y1).toFixed(1)}"
      width="${bw.toFixed(1)}" height="${Math.max(Math.abs(y1-y0),1.5).toFixed(1)}"
      rx="3" fill="${r.avg>=0?'var(--green)':'var(--red)'}"
      data-t="${esc(r.m)}  ${f2(r.avg)}%\nwin ${r.win.toFixed(0)}%  n=${r.n}"/>`;
    x+=`<text x="${cx.toFixed(1)}" y="${H-B+16}" text-anchor="middle" font-size="9"
      font-family="var(--mono)" fill="var(--muted)">${esc(r.m.slice(2))}</text>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">${g}${b}${x}
    <text x="${W-R}" y="${T+9}" text-anchor="end" font-size="10"
      fill="var(--muted)">٪ میانگین بازده</text></svg>`;
}

/* خطوط بازده عامل‌ها روی ماه */
function factorChart(){
  const ms=D.months, ks=D.factors;
  if(!ms.length) return '';
  const W=Math.max(360,ms.length*56+80),H=230,L=46,R=96,T=16,B=44;
  const iw=W-L-R, ih=H-T-B;
  let all=[]; ks.forEach(k=>D.fseries[k].forEach(v=>{ if(v!=null) all.push(v); }));
  if(!all.length) return '';
  const lo=Math.min(...all), hi=Math.max(...all), pad=(hi-lo)*.12||1;
  const y=v=>T+ih-((v-(lo-pad))/((hi+pad)-(lo-pad)))*ih;
  const x=i=>L+iw*(ms.length===1?.5:i/(ms.length-1));
  let g='',lines='',lbl='',xs='';
  [lo-pad,(lo+hi)/2,hi+pad].forEach(v=>{
    g+=`<line x1="${L}" y1="${y(v).toFixed(1)}" x2="${W-R}" y2="${y(v).toFixed(1)}"
      stroke="var(--border)"/><text x="${L-7}" y="${(y(v)+3.5).toFixed(1)}"
      text-anchor="end" font-size="9.5" font-family="var(--mono)"
      fill="var(--muted)">${v>0?'+':''}${v.toFixed(0)}</text>`;
  });
  g+=`<line x1="${L}" y1="${y(0).toFixed(1)}" x2="${W-R}" y2="${y(0).toFixed(1)}"
    stroke="var(--muted)" stroke-dasharray="3 3"/>`;
  ms.forEach((m,i)=>{ xs+=`<text x="${x(i).toFixed(1)}" y="${H-B+16}"
    text-anchor="middle" font-size="9" font-family="var(--mono)"
    fill="var(--muted)">${esc(m.slice(2))}</text>`; });
  ks.forEach(k=>{
    const pts=D.fseries[k].map((v,i)=>v==null?null:[x(i),y(v)]).filter(Boolean);
    if(!pts.length) return;
    lines+=`<polyline fill="none" stroke="${FC[k]||'var(--c1)'}" stroke-width="2"
      stroke-linejoin="round" points="${pts.map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join(' ')}"/>`;
    pts.forEach((p,i)=>{ lines+=`<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}"
      r="3.2" fill="${FC[k]||'var(--c1)'}" stroke="var(--card)" stroke-width="1.4"/>`; });
    const last=pts[pts.length-1];
    lbl+=`<text x="${(W-R+8)}" y="${(last[1]+4).toFixed(1)}" font-size="11"
      fill="${FC[k]||'var(--c1)'}" font-weight="600" direction="rtl">${esc(k)}</text>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" height="auto"
    preserveAspectRatio="xMidYMid meet"
    style="max-height:260px">${g}${lines}${xs}${lbl}</svg>`;
}

function corrTable(){
  const ks=D.factors;
  let h=`<div class="box scroll" style="max-height:none"><table><thead><tr><th></th>`;
  ks.forEach(k=>h+=`<th class="n">${esc(k)}</th>`);
  h+=`</tr></thead><tbody>`;
  ks.forEach(a=>{
    h+=`<tr><td style="color:${FC[a]};font-weight:600">${esc(a)}</td>`;
    ks.forEach(b=>{
      const v=D.corr[a][b];
      let col='var(--muted)';
      if(v!=null && a!==b) col = v<=-0.3?'var(--green)':(v>=0.7?'var(--red)':'var(--yellow)');
      h+=`<td class="n" style="color:${col}">${v==null?'—':f2(v)}</td>`;
    });
    h+=`</tr>`;
  });
  return h+`</tbody></table></div>`;
}

/* ───────────── پرتفو ───────────── */
let TARGET=[], TARGET_CAP=0;

function renderPf(){
  const cap=Math.max(0,+document.getElementById('cap').value||0);
  const nEq=Math.max(0,+document.getElementById('nEq').value||0);
  const nMe=Math.max(0,+document.getElementById('nMe').value||0);
  const wEq=Math.max(0,Math.min(100,+document.getElementById('wEq').value||0));
  const maxRisk=Math.max(0.1,+document.getElementById('mr').value||7);
  const wMe=100-wEq;

  const rFloor=Math.max(0.1,+document.getElementById('rf').value||2);
  const maxW=Math.max(1,+document.getElementById('mw').value||15);
  const maxG=D.cfg.max_group;

  const useGate=document.getElementById('gate') &&
                document.getElementById('gate').checked;
  function pick(factor,k){
    return D.rows.filter(r=>{
      if(r.factor!==factor||r.st!=='سبز') return false;
      if(!(r.risk>0&&r.risk<=maxRisk)) return false;
      if(r.score==null||r.score<=0) return false;
      if(useGate){
        const gt=D.gates[r.group];
        if(gt && gt.light==='قرمز') return false;
      }
      return true;
    }).sort((a,b)=>b.score-a.score);
  }
  // سقف وزن هر گروه: از هر گروه حداکثر به تعداد لازم برداشته می‌شود تا
  // یک گروه، سبد را نبلعد — سه اهرمی در سبد، یک شرط‌بندی است نه سه تا.
  function capGroups(list,k,w){
    const perG=Math.max(1,Math.ceil(k*Math.min(1,maxG/Math.max(w,1e-9))));
    const cnt={}, out=[];
    for(const r of list){
      const g=r.group||'—';
      if((cnt[g]||0)>=perG) continue;
      cnt[g]=(cnt[g]||0)+1; out.push(r);
      if(out.length>=k) break;
    }
    return out;
  }
  const eq=capGroups(pick('سهام‌محور',nEq),nEq,wEq);
  const me=capGroups(pick('فلزات',nMe),nMe,wMe);
  const legs=[['سهام‌محور',eq,wEq],['فلزات',me,wMe]];

  let out=[];
  legs.forEach(([f,list,w])=>{
    if(!list.length||w<=0) return;
    const pool=cap*w/100;
    // بازده به ازای واحد ریسک. کف استاپ لازم است چون فاصلهٔ ۰٫۲٪ تا کف باکس
    // نشانهٔ کم‌نوسانی نیست — فقط می‌گوید کلوز اتفاقی نزدیک کف نشسته، و
    // سایزکردن وارونهٔ آن، وزن را به تصادف می‌دهد.
    let raw=list.map(r=>r.score/Math.max(r.risk,rFloor));
    // سقف وزن هر نماد، با پخش دوبارهٔ باقی‌مانده بین بقیه
    const capW=cap*maxW/100;
    let amt=[], left=pool, act=list.map((_,i)=>i);
    for(let pass=0; pass<6; pass++){
      const tot=act.reduce((a,i)=>a+raw[i],0);
      if(tot<=0) break;
      let over=false;
      act.forEach(i=>{ amt[i]=left*raw[i]/tot; });
      act.slice().forEach(i=>{
        if(amt[i]>capW){ amt[i]=capW; left-=capW; act=act.filter(x=>x!==i); over=true; }
      });
      if(!over) break;
    }
    list.forEach((r,i)=>{
      const units=Math.floor((amt[i]||0)/r.close), spend=units*r.close;
      if(units>0) out.push({...r,factor:f,amount:spend,units,
        w:spend/cap*100, risk_rial:spend*r.risk/100,
        rr:r.score/Math.max(r.risk,rFloor)});
    });
  });
  out.sort((a,b)=>a.factor===b.factor ? b.amount-a.amount : (a.factor==='سهام‌محور'?-1:1));

  TARGET=out; TARGET_CAP=cap;
  const spent=out.reduce((a,o)=>a+o.amount,0);
  const risked=out.reduce((a,o)=>a+o.risk_rial,0);
  const byF={};
  out.forEach(o=>{ byF[o.factor]=(byF[o.factor]||0)+o.amount; });

  // بازده انتظاری و نوسان سبد دو عاملی از بازده‌های تاریخی
  const fs=D.fstats, rho=D.mv.rho;
  let expR=null, vol=null;
  if(fs['سهام‌محور']&&fs['فلزات']&&rho!=null){
    const a=wEq/100,b=wMe/100;
    const ra=fs['سهام‌محور'].avg, rb=fs['فلزات'].avg;
    const sa=fs['سهام‌محور'].vol, sb=fs['فلزات'].vol;
    if(ra!=null&&rb!=null) expR=a*ra+b*rb;
    if(sa!=null&&sb!=null) vol=Math.sqrt(Math.max(0,a*a*sa*sa+b*b*sb*sb+2*a*b*rho*sa*sb));
  }

  document.getElementById('pf-kpi').innerHTML=`
    <div class="kpi"><div class="k">پوزیشن</div>
      <div class="v"><span class="num">${out.length}</span></div>
      <div class="s">${eq.length} سهام‌محور · ${me.length} فلزات</div></div>
    <div class="kpi b"><div class="k">تخصیص</div>
      <div class="v"><span class="num">${money(spent)}</span></div>
      <div class="s">${pc(cap?spent/cap*100:0)} از سرمایه</div></div>
    <div class="kpi y"><div class="k">ریسک تا استاپ</div>
      <div class="v"><span class="num">${pc(cap?risked/cap*100:0)}</span></div>
      <div class="s">${money(risked)} ریال</div></div>
    <div class="kpi g"><div class="k">بازده ماهانهٔ انتظاری</div>
      <div class="v"><span class="num">${expR==null?'—':f2(expR)+'٪'}</span></div>
      <div class="s">از میانگین تاریخی دو عامل</div></div>
    <div class="kpi"><div class="k">نوسان ماهانهٔ سبد</div>
      <div class="v"><span class="num">${vol==null?'—':vol.toFixed(1)+'٪'}</span></div>
      <div class="s">با ρ=${rho==null?'—':f2(rho)}</div></div>`;

  let split='';
  Object.keys(byF).forEach(f=>{
    const w=cap?byF[f]/cap*100:0;
    split+=`<div style="display:grid;grid-template-columns:96px 1fr 96px;gap:10px;
      align-items:center;margin-bottom:8px">
      <span style="color:${FC[f]};font-weight:600;font-size:12.5px">${esc(f)}</span>
      <span class="bar"><i style="left:0;width:${Math.min(100,w/60*100)}%;
        background:${FC[f]}"></i></span>
      <span class="num muted" style="font-size:12px">${pc(w)} · ${money(byF[f])}</span>
    </div>`;
  });
  document.getElementById('pf-split').innerHTML=split;

  document.getElementById('pf-rows').innerHTML = out.length ? out.map(o=>`
    <tr><td>${esc(o.sym)}</td>
      <td><span class="badge b-f" style="color:${FC[o.factor]}">${esc(o.cat)}</span></td>
      <td>${(()=>{const g=D.gates[o.group];return g?
        `<span class="badge ${g.light==='سبز'?'b-up':(g.light==='قرمز'?'b-dn':'b-mid')}">${esc(g.light)}</span>`:'—';})()}</td>
      <td class="n">${money(o.close)}</td>
      <td class="n">${o.risk.toFixed(2)}٪</td>
      <td class="n">${o.bt_n==null?'—':o.bt_n}</td>
      <td class="n">${o.bt_avg==null?'—':f2(o.bt_avg)}٪</td>
      <td class="n">${f2(o.score)}٪</td>
      <td class="n">${o.rr.toFixed(1)}</td>
      <td class="n">${o.w.toFixed(2)}٪</td>
      <td class="n">${money(o.units)}</td>
      <td class="n">${money(o.amount)}</td>
      <td class="n">${money(o.lo)}</td></tr>`).join('')
    : `<tr><td colspan="11" style="text-align:center;color:var(--muted);padding:26px">
       با این تنظیمات نمادی واجد شرایط نشد.</td></tr>`;
  document.getElementById('pf-foot').innerHTML = out.length ? `<tr>
    <td>جمع</td><td></td><td></td><td class="n">—</td><td class="n">—</td>
    <td class="n">—</td><td class="n">—</td><td class="n">—</td><td class="n">—</td>
    <td class="n">${out.reduce((a,o)=>a+o.w,0).toFixed(2)}٪</td><td class="n">—</td>
    <td class="n">${money(spent)}</td><td class="n">—</td></tr>` : '';
}

function renderReb(){
  if(!TARGET.length) renderPf();
  const ta=document.getElementById('cur');
  if(ta && !ta.value && Object.keys(D.holdings||{}).length){
    ta.value=Object.entries(D.holdings).map(([s,n])=>s+' '+n).join('\n');
  }
  const txt=(document.getElementById('cur')||{}).value||'';
  const cash=Math.max(0,+((document.getElementById('cash')||{}).value)||0);
  const price={}, grp={};
  D.rows.forEach(r=>{ price[r.sym]=r.close; grp[r.sym]=r.group; });

  const cur={}, unknown=[];
  txt.split(/\r?\n/).forEach(line=>{
    line=line.trim(); if(!line) return;
    const m=line.match(/^(.+?)[\s,،\t]+([\d.,]+)$/);
    if(!m) return;
    const sym=m[1].trim(), n=parseFloat(m[2].replace(/[,،]/g,''));
    if(!isFinite(n)) return;
    if(price[sym]==null){ unknown.push(sym); return; }
    cur[sym]=(cur[sym]||0)+n;
  });

  const tgt={}; TARGET.forEach(o=>{ tgt[o.sym]=o.units; });
  const syms=[...new Set([...Object.keys(cur),...Object.keys(tgt)])];
  const rows=syms.map(sym=>{
    const c=cur[sym]||0, t=tgt[sym]||0, d=t-c, px=price[sym]||0;
    return {sym, group:grp[sym]||'—', cur:c, tgt:t, diff:d,
            amount:Math.abs(d)*px,
            act: d>0?'خرید':(d<0?'فروش':'بدون تغییر')};
  }).filter(r=>r.diff!==0||r.cur>0)
    .sort((a,b)=>(a.act==='فروش'?-1:a.act==='خرید'?0:1)-(b.act==='فروش'?-1:b.act==='خرید'?0:1)
                 || b.amount-a.amount);

  const curVal=Object.entries(cur).reduce((a,[s,n])=>a+n*(price[s]||0),0);
  const buys=rows.filter(r=>r.act==='خرید').reduce((a,r)=>a+r.amount,0);
  const sells=rows.filter(r=>r.act==='فروش').reduce((a,r)=>a+r.amount,0);
  const need=buys-sells-cash;

  document.getElementById('reb-kpi').innerHTML=`
    <div class="kpi"><div class="k">ارزش پرتفوی فعلی</div>
      <div class="v"><span class="num">${money(curVal)}</span></div>
      <div class="s">${Object.keys(cur).length} نماد${unknown.length?` · ${unknown.length} ناشناس`:''}</div></div>
    <div class="kpi b"><div class="k">ارزش پرتفوی هدف</div>
      <div class="v"><span class="num">${money(TARGET.reduce((a,o)=>a+o.amount,0))}</span></div>
      <div class="s">${TARGET.length} پوزیشن</div></div>
    <div class="kpi g"><div class="k">باید بخرید</div>
      <div class="v"><span class="num">${money(buys)}</span></div></div>
    <div class="kpi r"><div class="k">باید بفروشید</div>
      <div class="v"><span class="num">${money(sells)}</span></div></div>
    <div class="kpi ${need>0?'y':''}"><div class="k">${need>0?'کسری نقد':'مازاد نقد'}</div>
      <div class="v"><span class="num">${money(Math.abs(need))}</span></div>
      <div class="s">اول بفروشید، بعد بخرید</div></div>`;

  document.getElementById('reb-rows').innerHTML = rows.length ? rows.map(r=>`
    <tr><td>${esc(r.sym)}</td>
      <td style="color:var(--muted);font-size:12px">${esc(r.group)}</td>
      <td><span class="badge ${r.act==='خرید'?'b-up':(r.act==='فروش'?'b-dn':'b-mid')}">${r.act}</span></td>
      <td class="n">${money(r.cur)}</td>
      <td class="n">${money(r.tgt)}</td>
      <td class="n">${r.diff>0?'+':''}${money(r.diff)}</td>
      <td class="n">${money(r.amount)}</td></tr>`).join('')
    + (unknown.length?`<tr><td colspan="7" style="color:var(--yellow);font-size:12px">
       نماد ناشناس (در جهان ۱۳۸تایی نیست): ${unknown.map(esc).join('، ')}</td></tr>`:'')
    : `<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:26px">
       پرتفوی فعلی را در کادر بالا بچسبانید.</td></tr>`;
}

/* ───────────── پنل‌ها ───────────── */
function panels(){
  const A=D.all,C=D.closed,O=D.open,mv=D.mv;
  const P={};

  /* تصمیم امروز */
  const green=D.rows.filter(r=>r.st==='سبز');
  const tight=green.filter(r=>r.risk<=2);
  P.today=`
    <div class="note warn"><b>ماه جاری هنوز بسته نشده.</b> تصمیم نهایی روی کلوز
      آخرین روز ماه میلادی گرفته می‌شود. تا آن موقع این صفحه دو چیز را نشان
      می‌دهد: فاصله تا کف باکس <b>ماه جاری</b> و فاصله تا کف باکس <b>ماه قبل</b>
      — هر دو ستون در جدول هست.</div>
    <div class="kpis">
      <div class="kpi g"><div class="k">بالای باکس</div>
        <div class="v"><span class="num">${green.length}</span></div>
        <div class="s">${pc(green.length/D.rows.length*100)} از ${D.rows.length}</div></div>
      <div class="kpi y"><div class="k">داخل باکس</div>
        <div class="v"><span class="num">${D.rows.filter(r=>r.st==='داخل').length}</span></div></div>
      <div class="kpi r"><div class="k">زیر باکس</div>
        <div class="v"><span class="num">${D.rows.filter(r=>r.st==='قرمز').length}</span></div></div>
      <div class="kpi b"><div class="k">ریسک ≤ ۲٪</div>
        <div class="v"><span class="num">${tight.length}</span></div>
        <div class="s">نزدیک‌ترین به حمایت</div></div>
    </div>
    <h2>نمادهای بالای باکس</h2>
    <p class="lede">مرتب بر اساس امتیاز — میانگین بازده بک‌تست، منقبض‌شده به
      میانگین دستهٔ خودش تا نمادی با ۲ معامله مثل نمادی با ۸ معامله وزن نگیرد.</p>
    <div class="box scroll"><table><thead><tr>
      <th>نماد</th><th>دسته</th><th class="n">کلوز</th>
      <th class="n">ریسک جاری</th><th class="n">ریسک ماه قبل</th>
      <th class="n">بک‌تست n</th><th class="n">میانگین</th><th class="n">امتیاز</th>
      <th>جای کلوز</th></tr></thead><tbody>${
      green.slice().sort((a,b)=>(b.score??-1e9)-(a.score??-1e9)).map(r=>`
      <tr><td>${esc(r.sym)}</td>
        <td><span class="badge b-f" style="color:${FC[r.factor]||'var(--blue)'}">${esc(r.cat)}</span></td>
        <td class="n">${money(r.close)}</td>
        <td class="n">${r.risk.toFixed(2)}٪</td>
        <td class="n">${r.prisk==null?'—':r.prisk.toFixed(2)+'٪'}</td>
        <td class="n">${r.bt_n??'—'}</td>
        <td class="n">${r.bt_avg==null?'—':f2(r.bt_avg)+'٪'}</td>
        <td class="n">${r.score==null?'—':f2(r.score)+'٪'}</td>
        <td>${gauge(r.lo,r.hi,r.close)}</td></tr>`).join('')}
    </tbody></table></div>`;

  /* پرتفو */
  const mvTxt = mv.w==null ? 'قابل محاسبه نیست' :
    `${(mv.w*100).toFixed(0)}٪ سهام‌محور / ${(100-mv.w*100).toFixed(0)}٪ فلزات`;
  P.pf=`
    <h2>ترکیب دو عاملی</h2>
    <p class="lede">دادهٔ خودتان می‌گوید سهام‌محور و فلزات با هم حرکت نمی‌کنند.
      همین واگرایی ابزار کاهش نوسان است: وقتی یکی افت می‌کند، دیگری معمولاً
      نمی‌کند، پس برایند روزانه صاف‌تر می‌شود. وزن کمینه‌واریانس از روی همین
      بازده‌ها <b>${mvTxt}</b> درمی‌آید${mv.n?` (روی ${mv.n} ماه مشترک)`:''}.</p>
    <div class="ctrl">
      <label>سرمایه (ریال)<input id="cap" type="number" min="0" step="10000000" value="${D.cfg.capital}"></label>
      <label>وزن سهام‌محور (٪)<input id="wEq" type="number" min="0" max="100" step="5" value="${D.cfg.w_eq}"></label>
      <label>تعداد سهام‌محور<input id="nEq" type="number" min="0" max="20" step="1" value="${D.cfg.n_eq}"></label>
      <label>تعداد فلزات<input id="nMe" type="number" min="0" max="20" step="1" value="${D.cfg.n_me}"></label>
      <label>حداکثر ریسک (٪)<input id="mr" type="number" min="0.1" step="0.5" value="${D.cfg.max_risk}"></label>
      <label>کف استاپ (٪)<input id="rf" type="number" min="0.1" step="0.25" value="${D.cfg.risk_floor}"></label>
      <label>سقف وزن هر نماد (٪)<input id="mw" type="number" min="1" max="100" step="1" value="${D.cfg.max_weight}"></label>
      <label style="justify-content:flex-end">چراغ محرک
        <span style="display:flex;gap:6px;align-items:center;height:37px">
          <input id="gate" type="checkbox" checked
            style="width:auto;accent-color:var(--blue)">
          <span style="font-size:12.5px;color:var(--text)">گروه قرمز حذف شود</span>
        </span></label>
    </div>
    <div class="kpis" id="pf-kpi"></div>
    <h3>تقسیم بین عامل‌ها</h3>
    <div class="box" style="padding:14px 16px"><div id="pf-split"></div></div>
    <h3>پوزیشن‌ها</h3>
    <div class="box scroll"><table><thead><tr>
      <th>نماد</th><th>دسته</th><th>چراغ</th><th class="n">کلوز</th>
      <th class="n">ریسک</th><th class="n">بک‌تست n</th><th class="n">میانگین</th>
      <th class="n">امتیاز</th><th class="n">بازده/ریسک</th><th class="n">وزن</th>
      <th class="n">واحد</th><th class="n">مبلغ</th><th class="n">استاپ</th>
      </tr></thead>
      <tbody id="pf-rows"></tbody><tfoot id="pf-foot"></tfoot></table></div>
    <div class="note"><b>چطور سایز می‌شود.</b> اول سرمایه بین دو عامل تقسیم
      می‌شود؛ بعد داخل هر عامل وزن متناسب با <b>امتیاز ÷ ریسک</b>
      پخش می‌شود — یعنی بازده به ازای
      واحد ریسک — و هیچ نمادی از سقف وزن بالاتر نمی‌رود.
      <br><br><b>چرا کف استاپ لازم است.</b> فاصلهٔ ۰٫۲٪ تا کف باکس نشانهٔ
      کم‌نوسانی نیست؛ فقط می‌گوید کلوز اتفاقی نزدیک کف نشسته. سایزکردن وارونهٔ
      آن، بزرگ‌ترین وزن سبد را به یک تصادف می‌دهد — و استاپی به آن نزدیکی را
      نوسان عادی روز می‌زند. پس در محاسبهٔ سایز، هر ریسکی زیر کف، برابر کف
      گرفته می‌شود.</div>
    <div class="note warn"><b>قید.</b> بازده انتظاری و نوسان از
      ${D.months.length} ماه بک‌تست حساب شده‌اند. با این تعداد ماه، ρ و σ هر دو
      نویزی‌اند و وزن کمینه‌واریانس را باید یک نقطهٔ شروع دانست، نه جواب
      بهینه. ضمناً بازده‌های بک‌تست خودشان به نرخ پایه سنجیده نشده‌اند — به
      تب «سلامت داده» نگاه کنید.</div>`;

  /* بک‌تست */
  P.bt=`
    <div class="note bad"><b>عدد سرصفحهٔ داشبورد قبلی
      (<span class="num">${A.win.toFixed(1)}٪ / ${f2(A.avg)}٪</span>) شامل
      معاملات باز است.</b> از ${A.n} معامله،
      <span class="num">${O.n}</span> تا (${pc(O.n/A.n*100)}) هنوز بسته نشده‌اند و
      با قیمت امروز ارزش‌گذاری شده‌اند. معاملهٔ باز در بازاری که تازه بالا رفته،
      نرخ برد را بالا می‌برد. فقط بسته‌شده‌ها:
      <span class="num">${C.win.toFixed(1)}٪ / ${f2(C.avg)}٪</span>.</div>
    <div class="kpis">
      <div class="kpi"><div class="k">همه (عدد قبلی)</div>
        <div class="v"><span class="num">${A.win.toFixed(1)}٪</span></div>
        <div class="s">n=${A.n} · میانگین ${f2(A.avg)}٪</div></div>
      <div class="kpi g"><div class="k">فقط بسته‌شده</div>
        <div class="v"><span class="num">${C.win.toFixed(1)}٪</span></div>
        <div class="s">n=${C.n} · میانگین ${f2(C.avg)}٪</div></div>
      <div class="kpi y"><div class="k">هنوز باز</div>
        <div class="v"><span class="num">${O.win.toFixed(1)}٪</span></div>
        <div class="s">n=${O.n} · میانگین ${f2(O.avg)}٪</div></div>
      <div class="kpi"><div class="k">ماه</div>
        <div class="v"><span class="num">${D.monthly.length}</span></div>
        <div class="s">n مؤثر، نه تعداد معامله</div></div>
    </div>
    <h2>ماه‌به‌ماه (فقط بسته‌شده)</h2>
    <p class="lede">اگر مزیت واقعی باشد باید اغلب ماه‌ها مثبت بماند. اینجا
      ${D.monthly.filter(m=>m.avg>0).length} از ${D.monthly.length} ماه مثبت است و
      دامنه از ${f2(Math.min(...D.monthly.map(m=>m.avg)))}٪ تا
      ${f2(Math.max(...D.monthly.map(m=>m.avg)))}٪ می‌رود — یعنی نتیجه عمدتاً
      تابع جهت بازار در آن ماه است.</p>
    <div class="box"><figure>${monthChart(D.monthly)}
      <figcaption>میانگین بازده معاملات بسته‌شده در هر ماه خروج</figcaption></figure></div>
    <h2>ریسک ورود در برابر بازده</h2>
    <p class="lede">قاعده می‌گوید «بالای باکس با فاصلهٔ کم» بهتر است. روی
      معاملات بسته‌شده، عکسش درمی‌آید.</p>
    <div class="box scroll" style="max-height:none"><table><thead><tr>
      <th>ریسک ورود</th><th class="n">n</th><th class="n">برد</th>
      <th class="n">میانگین بازده</th></tr></thead><tbody>${
      D.buckets.map(b=>`<tr><td>${esc(b.label)}</td><td class="n">${b.n}</td>
        <td class="n">${b.win.toFixed(1)}٪</td>
        <td class="n">${f2(b.avg)}٪</td></tr>`).join('')}
    </tbody></table></div>`;

  /* همبستگی */
  P.corr=`
    <h2>بازده ماهانهٔ هر عامل</h2>
    <p class="lede">این نمودار همان چیزی است که پرتفو رویش بنا شده: خط‌ها با هم
      بالا و پایین نمی‌روند.</p>
    <div class="legend">${D.factors.map(k=>
      `<span><i style="background:${FC[k]}"></i>${esc(k)}</span>`).join('')}</div>
    <div class="box"><figure>${factorChart()}
      <figcaption>میانگین بازده معاملات بسته‌شدهٔ هر عامل در هر ماه</figcaption></figure></div>
    <h2>ماتریس همبستگی</h2>
    <p class="lede">سبز یعنی واگرا (زیر ۰٫۳−) و برای تنوع مفید؛ قرمز یعنی
      هم‌جهت (بالای ۰٫۷+) و عملاً یک شرط‌بندی واحد.</p>
    ${corrTable()}
    <div class="note warn"><b>با ${D.months.length} ماه، این اعداد نویزی‌اند.</b>
      عامل فلزات فقط در چند ماه معامله دارد، پس همبستگی‌اش بر پایهٔ نمونهٔ
      کوچکی است. جهت رابطه احتمالاً درست است؛ به عدد دقیقش تکیه نکنید.</div>`;

  /* نمادها */
  P.all=`
    <div class="chips" id="chips"></div>
    <div class="box scroll"><table><thead><tr>
      <th>نماد</th><th>دسته</th><th class="n">کلوز</th>
      <th class="n">باکس جاری</th><th class="n">ریسک جاری</th><th>وضعیت</th>
      <th class="n">باکس ماه قبل</th><th class="n">ریسک قبل</th>
      <th class="n">بک‌تست</th><th>جای کلوز</th>
      </tr></thead><tbody id="all-rows"></tbody></table></div>`;

  /* محرک‌ها */
  const cov=D.coverage;
  const lightCls=l=>l==='سبز'?'b-up':(l==='قرمز'?'b-dn':'b-mid');
  const selfRef=D.groups.filter(g=>g.light==='خودارجاع').length;
  P.drv=`
    <h2>محرک‌های بازار</h2>
    <p class="lede">این هفت مرجع خودشان معامله نمی‌شوند، ولی جهت بقیه را
      می‌سازند. صندوقی به اسم «شاخص کل» وجود ندارد، ولی حمایت و مقاومتش
      تصمیم صندوق‌های اهرمی را تعیین می‌کند — همان‌طور که دلار و اونس طلا
      تصمیم صندوق‌های طلا را.</p>
    ${selfRef?`<div class="note bad"><b>${selfRef} گروه چراغ خودارجاع دارند (↺).</b>
      محرک اصلی‌شان فعلاً با پروکسی‌ای پر شده که <b>خودِ همان گروه</b> است —
      چراغ «طلا» از اونس طلا می‌آید و اونس طلا با دستهٔ «طلا» پروکسی شده. آن
      چراغ چیزی جز «طلا بالای باکس خودش است» نمی‌گوید و تا رسیدن دادهٔ واقعیِ
      اونس و دلار، اطلاعاتی اضافه نمی‌کند.</div>`:''}
    ${cov.have===0?`<div class="note warn"><b>هنوز دادهٔ هیچ محرکی نرسیده.</b>
      فعلاً به‌جای هرکدام، نزدیک‌ترین گروه قابل‌معامله نشسته — دستهٔ «شاخصی»
      به‌جای شاخص کل، «طلا» به‌جای اونس، «نقره» به‌جای اونس نقره. این‌ها با
      نشان «پروکسی» علامت خورده‌اند و جای دادهٔ واقعی را نمی‌گیرند.</div>`
     :`<div class="note"><b>${cov.have} از ${cov.total} محرک</b> دادهٔ واقعی
      دارند؛ بقیه پروکسی‌اند.</div>`}
    <div class="box scroll" style="max-height:none"><table><thead><tr>
      <th>محرک</th><th class="n">کلوز</th><th class="n">باکس</th>
      <th class="n">ریسک تا حمایت</th><th>وضعیت</th><th>منبع داده</th>
      </tr></thead><tbody>${D.drivers.map(d=>`
      <tr><td>${esc(d.name)}${d.proxy_of?` <span class="badge b-mid">پروکسی: ${esc(d.proxy_of)}</span>`:''}</td>
        <td class="n">${d.close!=null?money(d.close)
          :(d.n?`<span style="color:var(--muted)">${d.n} نماد</span>`:'—')}</td>
        <td class="n">${d.lo!=null?money(d.lo)+' – '+money(d.hi)
          :(d.share!=null?`<span style="color:var(--muted)">${d.share.toFixed(0)}٪ هم‌جهت</span>`:'—')}</td>
        <td class="n">${d.risk==null?'—':d.risk.toFixed(2)+'٪'}</td>
        <td>${d.state?`<span class="badge ${d.state==='بالا'?'b-up':(d.state==='زیر'?'b-dn':'b-mid')}">${esc(d.state)}</span>`
          :'<span class="badge b-mid">منتظر داده</span>'}</td>
        <td style="color:var(--muted);font-size:12px">${esc(d.source)}</td></tr>`).join('')}
    </tbody></table></div>

    <h2>گواهی سپردهٔ کالایی</h2>
    <p class="lede">این‌ها برخلاف بالایی‌ها <b>قابل معامله‌اند</b>، ولی نقششان
      در تصمیم همان است: قیمت پایهٔ فیزیکی که صندوق رویش بنا شده. اگر گواهی
      شمش نقره زیر حمایتش باشد، صندوق نقره هم معمولاً همان‌جاست.</p>
    <div class="box scroll" style="max-height:none"><table><thead><tr>
      <th>گواهی</th><th>چه چیزی را می‌راند</th><th class="n">کلوز</th>
      <th class="n">باکس</th><th>وضعیت</th><th>منبع داده</th>
      </tr></thead><tbody>${D.certs.map(c=>`
      <tr><td>${esc(c.name)}</td>
        <td style="color:var(--muted);font-size:12px">${c.drives.map(esc).join('، ')}</td>
        <td class="n">${c.close==null?'—':money(c.close)}</td>
        <td class="n">${c.lo==null?'—':money(c.lo)+' – '+money(c.hi)}</td>
        <td>${c.state?`<span class="badge ${c.state==='بالا'?'b-up':(c.state==='زیر'?'b-dn':'b-mid')}">${esc(c.state)}</span>`
          :'<span class="badge b-mid">منتظر داده</span>'}</td>
        <td style="color:var(--muted);font-size:12px">${esc(c.source)}</td></tr>`).join('')}
    </tbody></table></div>

    <h2>چراغ هر گروه</h2>
    <p class="lede">هر گروه از ترکیب وضعیت محرک‌هایش چراغ می‌گیرد. ستون
      «β شاخص» بتای اندازه‌گیری‌شدهٔ همان گروه روی معاملات بستهٔ بک‌تست است —
      کنترلی برای اینکه نقشه با رفتار واقعی داده بخواند.</p>
    <div class="box scroll" style="max-height:none"><table><thead><tr>
      <th>گروه</th><th>چراغ</th><th class="n">امتیاز</th><th>محرک‌ها</th>
      <th class="n">β شاخص</th><th class="n">ρ</th><th class="n">ماه</th>
      <th class="n">میانگین بازده</th></tr></thead><tbody>${
      D.groups.map(g=>`<tr>
        <td>${esc(g.g)}</td>
        <td><span class="badge ${lightCls(g.light)}">${esc(g.light)}</span></td>
        <td class="n">${g.gate_score==null?'—':f2(g.gate_score)}</td>
        <td style="font-size:12px;color:var(--muted)">${g.gate.map(x=>
          `${x.circular?'<span style="color:var(--yellow)">↺ </span>':''}${esc(x.name)} <span class="num">${(x.w*100).toFixed(0)}٪</span>`).join(' · ')}</td>
        <td class="n">${g.beta_idx==null?'—':g.beta_idx.toFixed(2)}</td>
        <td class="n">${g.rho_idx==null?'—':f2(g.rho_idx)}</td>
        <td class="n">${g.months}</td>
        <td class="n">${f2(g.avg)}٪</td></tr>`).join('')}
    </tbody></table></div>
    <div class="note warn"><b>چطور این نقشه ساخته شد.</b> وزن‌ها از ترکیب
      دارایی هر صندوق می‌آیند — صندوق طلا سکه و شمش دارد پس به اونس و دلار
      بند است؛ اهرمی سبد سهام بزرگ دارد پس به شاخص کل. بعد با بتای
      اندازه‌گیری‌شده کنترل شد: اهرمی <span class="num">۱٫۶۲</span>،
      فلزی <span class="num">۱٫۵۱</span>، بانکی <span class="num">۱٫۳۱</span>،
      املاک <span class="num">۰٫۲۲</span> — دقیقاً همان ترتیبی که ترکیب
      دارایی پیش‌بینی می‌کند. دستهٔ «بخشی» هم به زیربخش شکسته شد، چون
      بانکی و پالایشی و فلزی در یک سطل، محرک‌های متفاوتی دارند.</div>`;

  /* پرتفوی من */
  const HOLD=D.holdings||{};
  const hv=[], byG={}, byF={};
  let hTotal=0;
  Object.entries(HOLD).forEach(([sym,n])=>{
    const r=D.rows.find(x=>x.sym===sym);
    const px=r?r.close:0, val=n*px;
    hTotal+=val;
    hv.push({sym,n,val,row:r});
    const g=r?r.group:'ناشناس', f=r?r.factor:'ناشناس';
    byG[g]=(byG[g]||0)+val; byF[f]=(byF[f]||0)+val;
  });
  hv.sort((a,b)=>b.val-a.val);
  const topW=hTotal?hv[0].val/hTotal*100:0;
  const top2=hTotal?(hv[0].val+(hv[1]?hv[1].val:0))/hTotal*100:0;
  const nReal=hv.filter(h=>h.val>hTotal*0.001).length;
  const facRows=Object.entries(byF).sort((a,b)=>b[1]-a[1]);

  P.mine = !hv.length ? `<div class="note">فایل <span class="num">data/holdings.txt</span> خالی است.</div>` : `
    <h2>پرتفوی فعلی شما</h2>
    <p class="lede">جمع دو حساب، به قیمت پایانی. درصدها نسبت به ارزش سهام است،
      بدون نقد.</p>
    <div class="kpis">
      <div class="kpi b"><div class="k">ارزش سهام</div>
        <div class="v"><span class="num">${money(hTotal)}</span></div>
        <div class="s">${nReal} پوزیشن مؤثر</div></div>
      <div class="kpi ${topW>25?'r':''}"><div class="k">بزرگ‌ترین پوزیشن</div>
        <div class="v"><span class="num">${topW.toFixed(1)}٪</span></div>
        <div class="s">${esc(hv[0].sym)}</div></div>
      <div class="kpi ${top2>50?'r':''}"><div class="k">دو پوزیشن اول</div>
        <div class="v"><span class="num">${top2.toFixed(1)}٪</span></div></div>
      ${facRows.map(([f,v])=>`<div class="kpi"><div class="k">${esc(f)}</div>
        <div class="v" style="color:${FC[f]||'var(--text)'}"><span class="num">${(v/hTotal*100).toFixed(1)}٪</span></div>
        <div class="s">${money(v)}</div></div>`).join('')}
    </div>
    ${topW>25?`<div class="note bad"><b>تمرکز.</b> ${topW.toFixed(1)}٪ سبد در یک
      نماد (${esc(hv[0].sym)}) است و ${top2.toFixed(1)}٪ در دو نماد. هیچ
      چارچوب حرفه‌ای‌ای وزن تک‌پوزیشن را بالای حدود ۱۰–۱۵٪ نمی‌گذارد —
      نه چون آن نماد بد است، بلکه چون یک خطای واحد نباید سبد را ببرد.</div>`:''}
    <div class="box scroll"><table><thead><tr>
      <th>نماد</th><th>گروه</th><th>چراغ</th><th class="n">تعداد</th>
      <th class="n">کلوز</th><th class="n">ارزش</th><th class="n">٪ سبد</th>
      <th class="n">ریسک تا حمایت</th><th>وضعیت</th>
      <th class="n">٪ حجم روز</th><th class="n">روز خروج</th></tr></thead><tbody>${
      hv.map(h=>{const r=h.row, gt=r?D.gates[r.group]:null; return `
      <tr><td>${esc(h.sym)}</td>
        <td style="color:var(--muted);font-size:12px">${r?esc(r.group):'—'}</td>
        <td>${gt?`<span class="badge ${gt.light==='سبز'?'b-up':(gt.light==='قرمز'?'b-dn':'b-mid')}">${esc(gt.light)}</span>`:'—'}</td>
        <td class="n">${money(h.n)}</td>
        <td class="n">${r?money(r.close):'—'}</td>
        <td class="n">${money(h.val)}</td>
        <td class="n">${hTotal?(h.val/hTotal*100).toFixed(1):'0.0'}٪</td>
        <td class="n">${r?r.risk.toFixed(2)+'٪':'—'}</td>
        <td>${r?`<span class="badge ${stCls(r.st)}">${esc(r.st)}</span>`
          :'<span class="badge b-mid">خارج از جهان</span>'}</td>
        <td class="n">${r&&r.liq&&r.liq.pct_of_volume!=null
          ?r.liq.pct_of_volume.toFixed(2)+'٪':'—'}</td>
        <td class="n">${r&&r.liq&&r.liq.exit_days!=null
          ?`<b style="color:${r.liq.exit_days>2?'var(--red)':r.liq.exit_days>0.5?'var(--yellow)':'var(--green)'}">${r.liq.exit_days.toFixed(2)}</b>`
          :'—'}</td></tr>`;}).join('')}
    </tbody></table></div>
    ${D.liq_meta?(()=>{const worst=hv.map(h=>h.row&&h.row.liq&&h.row.liq.exit_days)
        .filter(x=>x!=null).sort((a,b)=>b-a)[0];
      return worst==null?'':`<div class="note ${worst>2?'bad':'ok'}">
      <b>نقدشوندگی ${worst>2?'قید هست':'قید نیست'}.</b> بدترین پوزیشن
      <span class="num">${worst.toFixed(2)}</span> روز طول می‌کشد تا با
      <span class="num">${(D.liq_meta.participation*100).toFixed(0)}٪</span>
      مشارکت در حجم روزانه بسته شود (میانهٔ
      <span class="num">${D.liq_meta.window}</span> روز اخیر).
      ${worst>2?'یعنی خروج چند روز طول می‌کشد و باید در سایزینگ لحاظ شود.'
        :'یعنی «امشب بفروشم یا فردا» سؤال اجرایی نیست — این حجم‌ها در یک نشست بازار جا می‌شوند. هر تصمیمی اینجا تصمیم قاعده است، نه تصمیم نقدشوندگی.'}
      </div>`;})():''}
    <div class="note warn"><b>سه اهرمی یک شرط‌بندی است، نه سه تا.</b>
      همبستگی داخل مجموعهٔ سهام بالای ۰٫۹ است، پس دوایکس و موج و بیدار در
      عمل یک پوزیشن‌اند. تنوع واقعی بین <b>عامل</b>ها به دست می‌آید، نه بین
      نمادهای یک عامل.</div>`;

  /* تراز پرتفو */
  P.reb=`
    <h2>فاصله تا پرتفوی هدف</h2>
    <p class="lead lede">پرتفوی فعلی‌تان را اینجا بچسبانید — هر خط یک نماد و
      تعداد واحد، با فاصله یا کاما. خروجی می‌گوید چه بخرید و چه بفروشید تا به
      هدف برسید.</p>
    <div class="note warn"><b>اصل کار پایان ماه است.</b> باکس ماه جاری تا
      بسته‌شدن ماه کامل نمی‌شود. این صفحه فاصله را نشان می‌دهد تا بتوانید
      تدریجی نزدیک شوید، ولی تراز نهایی روی کلوز آخرین روز ماه گرفته می‌شود.</div>
    <div class="ctrl" style="align-items:stretch">
      <label style="flex:1 1 320px">پرتفوی فعلی
        <textarea id="cur" rows="8" spellcheck="false"
          style="font-family:var(--mono);font-size:13px;direction:ltr;
            text-align:left;padding:10px;border:1px solid var(--border);
            border-radius:8px;background:var(--card);color:var(--text);width:100%"
          placeholder="کهربا 100000&#10;نقران 1000000&#10;دوایکس 50000"></textarea></label>
      <label>نقد فعلی (ریال)
        <input id="cash" type="number" min="0" step="1000000" value="0"></label>
    </div>
    <div class="kpis" id="reb-kpi"></div>
    <div style="height:14px"></div>
    <div class="box scroll"><table><thead><tr>
      <th>نماد</th><th>گروه</th><th>اقدام</th><th class="n">فعلی</th>
      <th class="n">هدف</th><th class="n">اختلاف واحد</th>
      <th class="n">مبلغ</th></tr></thead>
      <tbody id="reb-rows"></tbody></table></div>`;

  /* شواهد */
  const EV=D.ev, EVI=D.evi;
  const KN={valley_first:'اولین دره',valley_nearest:'نزدیک‌ترین دره',
            valley_deepest:'عمیق‌ترین دره',value_area:'سه‌بین پرحجم'};
  P.ev = !EV ? `<div class="note warn">فایل شواهد ساخته نشده. اجرا کنید:
      <span class="num">python3 tools/monthly_backtest.py --data data_auto
      --json data/evidence_month.json</span></div>` : `
    <div class="note"><b>این تب می‌گوید کدام تعریف باکس شواهد دارد و کدام ندارد
      — روی دادهٔ خودتان، نه روی حرف.</b> آزمون، جایگشتِ درون‌ماه است: برچسب
      سیگنال داخل هر ماه به‌هم می‌ریزد، پس حرکت کل بازار در آن ماه و تعداد
      سیگنال‌های آن ماه ثابت می‌مانند و تنها چیزی که تصادفی می‌شود این است که
      کدام نماد برچسب گرفت.</div>

    <h2>پنجرهٔ ۱ — باکس ماه قبل، بازده کل ماه بعد</h2>
    <p class="lede">تنها پنجره‌ای که بدون لوک‌اهد قابل معامله است: باکس وقتی
      ساخته می‌شود که ماه تمام شده، و ورود روی کلوز اولین روز ماه بعد است.
      <span class="num">${EV.symbols}</span> نماد،
      <span class="num">${EV.months}</span> ماه
      (<span class="num">${EV.span[0]}</span> تا
      <span class="num">${EV.span[1]}</span>).</p>
    <div class="box scroll"><table><thead><tr>
      <th>تعریف</th><th class="n">سیگنال</th><th class="n">نرخ پایه</th>
      <th class="n">برد</th><th class="n">میانگین</th><th class="n">عرض باکس</th>
      <th class="n">مزیت واحد٪</th><th class="n">p</th><th>حکم</th>
      </tr></thead><tbody>${
      Object.entries(EV.perm).sort((a,b)=>(a[1].p??1)-(b[1].p??1)).map(([k,v])=>`
      <tr${v.p!=null&&v.p<0.05?' class="hl"':''}>
        <td><b>${esc(KN[k]||k)}</b><div class="muted num">${esc(k)}</div></td>
        <td class="n">${v.n_signal}</td>
        <td class="n">${v.base_win==null?'—':v.base_win.toFixed(1)+'٪'}</td>
        <td class="n">${v.win==null?'—':v.win.toFixed(1)+'٪'}</td>
        <td class="n">${v.avg==null?'—':pc(v.avg)}</td>
        <td class="n">${v.width_med==null?'—':v.width_med.toFixed(2)+'٪'}</td>
        <td class="n">${v.edge>=0?'+':''}${v.edge.toFixed(2)}</td>
        <td class="n"><b>${v.p==null?'—':v.p.toFixed(4)}</b></td>
        <td>${v.p!=null&&v.p<0.05
            ? '<span class="badge b-up">قابل تفکیک از تصادف</span>'
            : '<span class="badge b-dn">قابل تفکیک نیست</span>'}</td>
      </tr>`).join('')}</tbody></table></div>
    <p class="lede">ستون «برد» را نخوانید، ستون «مزیت» را بخوانید. وقتی نرخ پایه
      <span class="num">${Object.values(EV.perm)[0].base_win.toFixed(1)}٪</span>
      است، «برد ۸۲٪» عمدتاً خودِ همان نرخ پایه است.</p>
    <div class="note ${Object.values(EV.perm).some(v=>v.p!=null&&v.p<0.05)?'ok':'warn'}">
      <b>کف p برابر <span class="num">${EV.p_floor.toFixed(5)}</span> است</b>
      (۱ تقسیم بر <span class="num">${EV.iters.toLocaleString('en')}</span> تکرار،
      به‌علاوهٔ یک) — نه <span class="num">${(1/(EV.months+1)).toFixed(2)}</span>.
      آن عدد دوم برای آزمونی است که علامتِ کل یک ماه را وارونه می‌کند؛ اینجا
      برچسب <b>داخل</b> هر ماه جابه‌جا می‌شود و هر ماه ده‌ها نماد دارد، پس فضای
      جایگشت نجومی است. آنچه
      <span class="num">${EV.months}</span> ماه محدود می‌کند <b>تعمیم‌پذیری</b>
      است، نه تفکیک‌پذیری: p کوچک می‌گوید باکس <b>در این دوره</b> بهتر از تصادف
      انتخاب کرده، نه اینکه همیشه می‌کند.</div>

    ${EV.geom?`<h2>هندسهٔ ۱:۱ — ورود روی پولبک</h2>
    <p class="lede">همان قاعدهٔ خودتان: ورود روی پولبک به سقف باکس، استاپ کف
      باکس، تارگت به اندازهٔ ارتفاع باکس. «خالی» یعنی پولبک نخورد و ورودی نبود.</p>
    <div class="box scroll"><table><thead><tr>
      <th>تعریف</th><th class="n">سیگنال</th><th class="n">حمایت خالی</th>
      <th class="n">تارگت</th><th class="n">استاپ</th><th class="n">میانگین R</th>
      </tr></thead><tbody>${
      Object.entries(EV.geom).map(([k,v])=>`
      <tr><td>${esc(KN[k]||k)}</td><td class="n">${v.n}</td>
        <td class="n">${v.empty.toFixed(0)}٪</td>
        <td class="n">${v.target}</td><td class="n">${v.stop}</td>
        <td class="n">${v.avg_r==null?'—':(v.avg_r>=0?'+':'')+v.avg_r.toFixed(3)}</td>
      </tr>`).join('')}</tbody></table></div>
    <div class="note warn"><b>R را با R مقایسه نکنید.</b> «سه‌بین پرحجم» میانگین
      R بالاتری می‌دهد چون باکسش
      ${EV.perm.value_area&&EV.perm.valley_first
        ? `<span class="num">${(EV.perm.value_area.width_med/EV.perm.valley_first.width_med).toFixed(1)}</span> برابر`
        : 'چند برابر'}
      پهن‌تر است — استاپ دورتر، تارگت دورتر. یک R آنجا حرکت قیمتی بسیار بزرگ‌تری
      است، و همان تعریف در آزمون جایگشت رد شد.</div>`:''}

    ${EVI?`<h2>پنجرهٔ ۲ — باکس همین ماه تا امروز، بازده تا پایان همین ماه</h2>
    <p class="lede">این پنجرهٔ چراغی است که داشبورد <b>در طول ماه</b> نشان
      می‌دهد. باکس روز d فقط کندل‌های تا روز d را می‌بیند، پس لوک‌اهد ندارد.
      <span class="num">${EVI.n_obs.toLocaleString('en')}</span> مشاهده
      (نماد×روز) روی <span class="num">${EVI.symbols}</span> نماد و
      <span class="num">${EVI.months}</span> ماه.</p>
    <div class="box scroll"><table><thead><tr>
      <th>حالت امروز</th><th class="n">n</th><th class="n">مثبت</th>
      <th class="n">میانگین تا پایان ماه</th><th class="n">مزیت واحد٪</th>
      <th class="n">p</th></tr></thead><tbody>${
      ['بالا','داخل','زیر'].filter(k=>EVI.states[k]).map(k=>{
        const v=EVI.states[k];
        return `<tr><td><span class="badge ${k==='بالا'?'b-up':k==='زیر'?'b-dn':'b-mid'}">${esc(k)} باکس</span></td>
        <td class="n">${v.n.toLocaleString('en')}</td>
        <td class="n">${v.win==null?'—':v.win.toFixed(1)+'٪'}</td>
        <td class="n">${v.avg==null?'—':pc(v.avg)}</td>
        <td class="n">${v.edge>=0?'+':''}${v.edge.toFixed(2)}</td>
        <td class="n">${v.p==null?'—':v.p.toFixed(4)}</td></tr>`}).join('')}
      </tbody></table></div>
    <p class="lede">نرخ پایهٔ این پنجره: میانگین
      <span class="num">${pc(EVI.base_avg)}</span> ·
      مثبت <span class="num">${EVI.base_win.toFixed(1)}٪</span>.
      p در این جدول یک‌طرفه و رو به بالاست، پس برای «زیر» عدد بزرگ یعنی بد بودن
      تأیید می‌شود؛ ستونی که باید خواند «مزیت» است.</p>

    ${EVI.cells&&Object.keys(EVI.cells).length?`
    <h2>همان جدول، این بار با کنترل افق</h2>
    <p class="lede">جدول بالا دو چیز را کنترل نکرده: کدام ماه، و کدام روزِ ماه
      — چون هرچه دیرتر در ماه، افق تا کلوز کوتاه‌تر است. اینجا مقایسه فقط
      <b>داخل هر سلولِ (ماه × روزِ ماه)</b> انجام می‌شود، یعنی فقط بین نمادهایی
      که در یک روزِ یکسان از یک ماهِ یکسان‌اند.</p>
    <div class="box scroll"><table><thead><tr>
      <th>حالت امروز</th><th class="n">میانگین روزِ ماه</th><th class="n">سلول</th>
      <th class="n">n</th><th class="n">مزیت واحد٪</th><th class="n">خطای معیار</th>
      <th class="n">t</th></tr></thead><tbody>${
      ['بالا','داخل','زیر'].filter(k=>EVI.cells[k]).map(k=>{const v=EVI.cells[k];
      return `<tr><td><span class="badge ${k==='بالا'?'b-up':k==='زیر'?'b-dn':'b-mid'}">${esc(k)} باکس</span></td>
        <td class="n">${v.mean_day.toFixed(1)}</td>
        <td class="n">${v.cells}</td>
        <td class="n">${v.n.toLocaleString('en')}</td>
        <td class="n"><b>${v.edge>=0?'+':''}${v.edge.toFixed(2)}</b></td>
        <td class="n">${v.se==null?'—':v.se.toFixed(2)}</td>
        <td class="n">${v.t==null?'—':(v.t>=0?'+':'')+v.t.toFixed(2)}</td>
      </tr>`}).join('')}</tbody></table></div>
    <h2>سه مشخصه، کنار هم</h2>
    <p class="lede">یک برآورد وقتی معنی دارد که با تغییر روشِ کنترل نلرزد.
      این جدول همان سه عدد را برای هر حالت کنار هم می‌گذارد.</p>
    <div class="box scroll"><table><thead><tr>
      <th>حالت امروز</th>
      <th class="n">خام<div class="muted">بدون کنترل</div></th>
      <th class="n">جایگشت<div class="muted">کنترل ماه</div></th>
      <th class="n">سلولی<div class="muted">کنترل ماه و افق</div></th>
      <th>پایداری</th></tr></thead><tbody>${
      ['بالا','داخل','زیر'].filter(k=>EVI.states[k]).map(k=>{
        const raw=EVI.states[k].avg-EVI.base_avg;
        const perm=EVI.states[k].edge;
        const cell=EVI.cells&&EVI.cells[k]?EVI.cells[k].edge:null;
        const vals=[raw,perm,cell].filter(x=>x!=null);
        const stable=vals.every(x=>x>=0)||vals.every(x=>x<=0);
        return `<tr><td><span class="badge ${k==='بالا'?'b-up':k==='زیر'?'b-dn':'b-mid'}">${esc(k)} باکس</span></td>
        <td class="n">${raw>=0?'+':''}${raw.toFixed(2)}</td>
        <td class="n">${perm>=0?'+':''}${perm.toFixed(2)}</td>
        <td class="n">${cell==null?'—':(cell>=0?'+':'')+cell.toFixed(2)}</td>
        <td>${stable?'<span class="badge b-mid">هم‌علامت</span>'
          :'<span class="badge b-dn">علامت عوض می‌شود</span>'}</td>
      </tr>`}).join('')}</tbody></table></div>
    ${(()=>{const up=EVI.cells?EVI.cells['بالا']:null;if(!up)return'';
      const days=['بالا','داخل','زیر'].filter(k=>EVI.cells[k])
        .map(k=>EVI.cells[k].mean_day);
      const spread=Math.max(...days)-Math.min(...days);
      const flip=['بالا','داخل','زیر'].filter(k=>{
        if(!EVI.states[k]||!EVI.cells||!EVI.cells[k])return false;
        const v=[EVI.states[k].avg-EVI.base_avg,EVI.states[k].edge,EVI.cells[k].edge];
        return !(v.every(x=>x>=0)||v.every(x=>x<=0));});
      return `<div class="note bad">
      <b>افق مقصر نیست</b> — میانگین روزِ ماه بین حالت‌ها فقط
      <span class="num">${spread.toFixed(1)}</span> روز فرق دارد. ولی با کنترل
      کامل، مزیتِ «بالای باکس»
      <span class="num">${up.edge>=0?'+':''}${up.edge.toFixed(2)}</span> واحد درصد
      است (t=<span class="num">${up.t==null?'—':(up.t>=0?'+':'')+up.t.toFixed(2)}</span>)
      — یعنی صفر. ${flip.length?`و برای <b>${flip.map(esc).join(' و ')}</b> علامتِ
      برآورد با انتخاب مشخصه عوض می‌شود؛ برآوردی که چنین می‌کند نویز را اندازه
      می‌گیرد، نه اثر را.`:''}
      <b>چراغ زندهٔ وسط ماه در این داده اطلاعاتی حمل نمی‌کند که از تصادف قابل
      تفکیک باشد.</b> این «اثباتِ نبودِ اثر» نیست، «نبودِ اثباتِ اثر» است.</div>`;})()}
    `:''}`:`
    <div class="note warn"><b>پنجرهٔ ۲ هنوز اجرا نشده.</b>
      <span class="num">python3 tools/intramonth_test.py --data data_auto
      --json data/evidence_intramonth.json</span></div>`}

    <div class="note"><b>دو چراغ، دو معنی.</b> ستون «وضعیت جاری» در بقیهٔ تب‌ها
      از باکس <b>همین ماه تا امروز</b> می‌آید (پنجرهٔ ۲) و ستون «وضعیت ماه قبل»
      از باکس <b>ماه قبل</b> (پنجرهٔ ۱). این دو می‌توانند هم‌زمان خلاف هم بگویند
      و این تناقض نیست — دو پنجره‌اند.</div>`;

  /* سلامت داده */
  P.health=`
    <div class="note bad"><b>${O.n} معاملهٔ باز</b> در بک‌تست با قیمت امروز
      ارزش‌گذاری شده‌اند (${pc(O.n/A.n*100)} کل). تا بسته نشوند، نرخ برد و
      میانگین بازده را خوش‌بینانه نشان می‌دهند.</div>
    ${EV?`<div class="note ok"><b>نرخ پایه دیگر غایب نیست.</b> این فایل فقط
      سیگنال‌های گرفته‌شده را دارد، ولی گروه کنترل حالا از CSVهای
      <span class="num">data_auto</span> ساخته شده:
      <span class="num">${EV.symbols}</span> نماد،
      <span class="num">${EV.months}</span> ماه. نرخ پایه
      <span class="num">${Object.values(EV.perm)[0].base_win.toFixed(1)}٪</span>
      است — یعنی ${C.win.toFixed(1)}٪ برد را باید منهای آن خواند. تب
      <b>شواهد</b> را ببینید.</div>`
      :`<div class="note warn"><b>نرخ پایه هنوز غایب است.</b> این فایل فقط
      سیگنال‌های گرفته‌شده را دارد، نه نماد-ماه‌هایی که سیگنال ندادند. بدون
      گروه کنترل نمی‌شود گفت ${C.win.toFixed(1)}٪ از «هر نماد تصادفی در همان
      ماه» بهتر است یا نه. اجرا کنید:
      <span class="num">python3 tools/monthly_backtest.py --data data_auto
      --json data/evidence_month.json</span></div>`}
    <div class="note"><b>ماه جاری باز است.</b> باکس ماه جاری تا پایان ماه کامل
      نمی‌شود، پس ستون «ریسک جاری» موقتی است. ستون «ریسک ماه قبل» روی دورهٔ
      کامل‌شده حساب شده و پایدارتر است.</div>
    <div class="note"><b>اندازهٔ نمونه.</b> ${D.monthly.length} ماه، و برخی
      نمادها فقط ۱ تا ۳ معامله دارند. امتیاز هر نماد برای همین به میانگین
      دسته‌اش منقبض شده — وگرنه رتبه‌بندی عمدتاً تصادف را نشان می‌دهد.</div>`;

  return P;
}

(function init(){
  document.getElementById('meta').textContent =
    `${D.rows.length} نماد · ${D.months.length} ماه بک‌تست`;
  document.getElementById('stamp').textContent = D.generated;

  const P=panels();
  const TABS=[['drv','محرک‌ها'],['mine','پرتفوی من'],['today','تصمیم امروز'],
              ['pf','پرتفوی هدف'],['reb','تراز پرتفو'],['ev','شواهد'],
              ['bt','بک‌تست'],['corr','همبستگی دسته‌ها'],['all','همهٔ نمادها'],
              ['health','سلامت داده']];
  const tabs=document.getElementById('tabs'), panelsEl=document.getElementById('panels');
  TABS.forEach(([id,label],i)=>{
    const b=document.createElement('button');
    b.className='tab'+(i===0?' active':''); b.textContent=label; b.dataset.p=id;
    b.type='button'; b.setAttribute('role','tab');
    tabs.appendChild(b);
    const d=document.createElement('div');
    d.className='panel'+(i===0?' active':''); d.id='p-'+id; d.innerHTML=P[id];
    panelsEl.appendChild(d);
  });
  tabs.addEventListener('click',e=>{
    const b=e.target.closest('.tab'); if(!b) return;
    tabs.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
    panelsEl.querySelectorAll('.panel').forEach(x=>x.classList.remove('active'));
    b.classList.add('active');
    document.getElementById('p-'+b.dataset.p).classList.add('active');
    try{localStorage.setItem('pf_tab',b.dataset.p)}catch(e){}
    if(b.dataset.p==='pf') renderPf();
    if(b.dataset.p==='reb') renderReb();
  });

  // فیلتر دسته در تب نمادها
  const chips=document.getElementById('chips');
  let filter=null;
  function drawAll(){
    document.getElementById('all-rows').innerHTML=D.rows
      .filter(r=>!filter||r.cat===filter)
      .slice().sort((a,b)=>(a.st!=='سبز')-(b.st!=='سبز')||a.risk-b.risk)
      .map(r=>`<tr><td>${esc(r.sym)}</td>
        <td><span class="badge b-f" style="color:${FC[r.factor]||'var(--blue)'}">${esc(r.cat)}</span></td>
        <td class="n">${money(r.close)}</td>
        <td class="n">${money(r.lo)} – ${money(r.hi)}</td>
        <td class="n">${r.risk.toFixed(2)}٪</td>
        <td><span class="badge ${stCls(r.st)}">${esc(r.st)}</span></td>
        <td class="n">${r.plo==null?'—':money(r.plo)+' – '+money(r.phi)}</td>
        <td class="n">${r.prisk==null?'—':r.prisk.toFixed(2)+'٪'}</td>
        <td class="n">${r.bt_n==null?'—':r.bt_n+' · '+f2(r.bt_avg)+'٪'}</td>
        <td>${gauge(r.lo,r.hi,r.close)}</td></tr>`).join('');
  }
  [['همه',null],...D.cats.map(c=>[c,c])].forEach(([lbl,val],i)=>{
    const c=document.createElement('button');
    c.className='chip'+(i===0?' on':''); c.textContent=lbl; c.type='button';
    c.addEventListener('click',()=>{
      chips.querySelectorAll('.chip').forEach(x=>x.classList.remove('on'));
      c.classList.add('on'); filter=val; drawAll();
    });
    chips.appendChild(c);
  });
  drawAll();
  renderPf();
  ['cap','wEq','nEq','nMe','mr','rf','mw','gate'].forEach(id=>{
    const el=document.getElementById(id);
    if(el) el.addEventListener(id==='gate'?'change':'input',renderPf);
  });
  ['cur','cash'].forEach(id=>{
    const el=document.getElementById(id);
    if(el) el.addEventListener('input',renderReb);
  });
  document.querySelectorAll('svg [data-t]').forEach(el=>{
    el.addEventListener('mousemove',e=>showTip(e,el.dataset.t));
    el.addEventListener('mouseleave',hideTip);
  });
  try{ const s=localStorage.getItem('pf_tab');
    if(s){ const b=tabs.querySelector(`.tab[data-p="${s}"]`); if(b) b.click(); } }catch(e){}
})();
</script>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True,
                    help="مسیر dashboard_monthly.html")
    ap.add_argument("--out", default="portfolio.html")
    ap.add_argument("--capital", type=float, default=1_000_000_000)
    ap.add_argument("--w-eq", type=float, default=None,
                    help="وزن سهام‌محور (٪). پیش‌فرض: کمینه‌واریانس از خود داده")
    ap.add_argument("--n-eq", type=int, default=6)
    ap.add_argument("--n-me", type=int, default=4)
    ap.add_argument("--max-risk", type=float, default=7.0)
    ap.add_argument("--risk-floor", type=float, default=2.0,
                    help="کف استاپ در محاسبهٔ سایز (٪)")
    ap.add_argument("--max-weight", type=float, default=15.0,
                    help="سقف وزن هر نماد (٪ سرمایه)")
    ap.add_argument("--drivers", default="data/drivers.txt",
                    help="فایل محرک‌ها؛ اگر نباشد پروکسی استفاده می‌شود")
    ap.add_argument("--holdings", default="data/holdings.txt",
                    help="پرتفوی فعلی: هر خط «نماد تعداد»")
    ap.add_argument("--liquidity", default="data/liquidity.json",
                    help="خروجی tools/liquidity.py — روزِ خروج از هر پوزیشن")
    ap.add_argument("--evidence", default="data/evidence_month.json",
                    help="خروجی tools/monthly_backtest.py --json")
    ap.add_argument("--evidence-intramonth",
                    dest="evidence_intra",
                    default="data/evidence_intramonth.json",
                    help="خروجی tools/intramonth_test.py --json")
    ap.add_argument("--max-group", type=float, default=35.0,
                    help="سقف وزن هر گروه (٪ سرمایه)")
    ap.add_argument("--artifact", action="store_true")
    args = ap.parse_args()

    data = extract(args.inp)
    if not data["TODAY"]:
        print("دادهٔ TODAY پیدا نشد — فایل ورودی درست است؟")
        return 1
    a = analyse(data)

    w_eq = args.w_eq
    if w_eq is None:
        w_eq = round(a["mv"]["w"] * 100) if a["mv"]["w"] is not None else 60.0
    # ── محرک‌ها: دادهٔ واقعی، وگرنه پروکسی ──
    real = parse_drivers(args.drivers)
    drv = []
    dstate = {}
    for d in DRIVERS:
        info = dict(d)
        got = real.get(d["id"])
        if got:
            info.update(got)
        elif d["proxy"]:
            px = proxy_state(a["rows"], d["proxy"])
            if px:
                info.update(px)
                info["proxy_of"] = d["proxy"]
        info.setdefault("state", None)
        info.setdefault("real", None)
        drv.append(info)
        if info.get("state"):
            dstate[d["id"]] = info["state"]
    a["drivers"] = drv
    proxy_map = {d["id"]: d.get("proxy_of") for d in drv if d.get("proxy_of")}
    a["coverage"] = dict(zip(("have", "total"), coverage(set(real))))

    for g in a["groups"]:
        light, score, detail = gate(g["g"], dstate, proxy_map)
        g["light"], g["gate_score"], g["gate"] = light, score, detail
    a["gates"] = {g["g"]: {"light": g["light"], "score": g["gate_score"],
                           "detail": g["gate"]} for g in a["groups"]}
    for g in set(EXPOSURE) - set(a["gates"]):
        light, score, detail = gate(g, dstate, proxy_map)
        a["gates"][g] = {"light": light, "score": score, "detail": detail}

    # ── پرتفوی فعلی ──
    holds = {}
    hp = Path(args.holdings)
    if hp.exists():
        for line in hp.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^(.+?)[\s,،\t]+([\d.,]+)$", line)
            if m:
                try:
                    holds[m.group(1).strip()] = float(
                        m.group(2).replace(",", "").replace("،", ""))
                except ValueError:
                    pass
    a["holdings"] = holds

    # ── نقدشوندگی ──
    # JSON خروجی tools/liquidity.py: واحدمحور، پس مقیاس‌آزاد. اگر نبود،
    # CSV قدیمیِ «ارزش معامله / ارزش بازار» هنوز خوانده می‌شود.
    liq, liq_meta = {}, None
    lp = Path(args.liquidity)
    if lp.exists():
        if lp.suffix == ".json":
            blob = json.loads(lp.read_text(encoding="utf-8"))
            liq = blob.get("rows", {})
            liq_meta = {"window": blob.get("window"),
                        "participation": blob.get("participation")}
        else:
            for line in lp.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = [x.strip() for x in re.split(r"[,\t]", line)]
                if len(parts) < 3:
                    continue
                try:
                    val, cap = float(parts[1]), float(parts[2])
                except ValueError:
                    continue
                if cap > 0:
                    liq[parts[0]] = {"med_value": val, "mcap": cap,
                                     "turnover": val / cap * 100}
    # `units`/`value`/`exit_days`/`pct_of_volume` از تعداد واحدهای پرتفو
    # می‌آیند. اگر پرتفو بارگذاری نشده، این‌ها نه معنایی دارند و نه جایی در
    # صفحه — و نباید از راه فایل نقدشوندگی به خروجی سر بخورند.
    POSITION_FIELDS = ("units", "value", "exit_days", "pct_of_volume")
    for r in a["rows"]:
        rec = liq.get(r["sym"])
        if rec and not a["holdings"]:
            rec = {k: v for k, v in rec.items() if k not in POSITION_FIELDS}
        r["liq"] = rec
    a["has_liquidity"] = bool(liq)
    a["liq_meta"] = liq_meta

    # ── شواهد: کدام تعریف باکس از آزمون جایگشت رد شد و کدام نشد ──
    a["ev"] = a["evi"] = None
    ep = Path(args.evidence)
    if ep.exists():
        a["ev"] = json.loads(ep.read_text(encoding="utf-8"))
    eip = Path(args.evidence_intra)
    if eip.exists():
        a["evi"] = json.loads(eip.read_text(encoding="utf-8"))

    a["certs"] = [dict(c) for c in CERTIFICATES]
    a["cfg"] = {"capital": args.capital, "w_eq": w_eq, "n_eq": args.n_eq,
                "n_me": args.n_me, "max_risk": args.max_risk,
                "risk_floor": args.risk_floor, "max_weight": args.max_weight,
                "max_group": args.max_group}
    a["generated"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    html = TEMPLATE.replace("__DATA__", json.dumps(a, ensure_ascii=False))
    if not args.artifact:
        html = ('<!doctype html>\n<html lang="fa" dir="rtl">\n<head>\n'
                '<meta charset="utf-8">\n<meta name="viewport" '
                'content="width=device-width,initial-scale=1,viewport-fit=cover">\n'
                + html + '\n</head>\n<body>\n</body>\n</html>\n')
    Path(args.out).write_text(html, encoding="utf-8")

    print(f"نماد: {len(a['rows'])}  ماه: {len(a['months'])}")
    print(f"همه: {a['all']['win']:.1f}٪ / {a['all']['avg']:+.2f}٪  (n={a['all']['n']})")
    print(f"بسته‌شده: {a['closed']['win']:.1f}٪ / {a['closed']['avg']:+.2f}٪"
          f"  (n={a['closed']['n']})")
    print(f"باز: {a['open']['win']:.1f}٪ / {a['open']['avg']:+.2f}٪  (n={a['open']['n']})")
    if a["mv"]["w"] is not None:
        print(f"وزن کمینه‌واریانس: {a['mv']['w']*100:.0f}٪ سهام‌محور"
              f"  (ρ={a['mv']['rho']:+.2f} روی {a['mv']['n']} ماه)")
    print(f"\nداشبورد: {Path(args.out).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
