# -*- coding: utf-8 -*-
"""
ساخت داشبورد کامل — یک فایل HTML خودکفا، بدون وابستگی.

از همان CSVهای روزانه‌ای می‌خواند که `monthly_backtest.py` می‌خواند و هر چهار
تعریف باکس را حساب می‌کند. داشبورد یک کلید انتخاب تعریف دارد؛ با عوض‌کردنش
**همهٔ** پنل‌ها دوباره رسم می‌شوند — چون سؤال اصلی همین است.

پنل‌ها:
  ۱. وضعیت امروز + جدول نمادها با نوار باکس
  ۲. نرخ پایه در برابر شرطی
  ۳. تست جایگشت
  ۴. مزیت ماه‌به‌ماه
  ۵. سطل ریسک — آیا آستانهٔ ۷٪ توجیه دارد؟
  ۶. افق نگهداری — ۱ روز / ۵ روز / پایان ماه
  ۷. هندسهٔ ۱:۱ و نرخ حمایت خالی
  ۸. عرض باکس
  ۹. کارنامهٔ هر نماد

اجرا:
    python3 tools/build_dashboard.py --data data_auto --out dashboard.html
"""

import argparse
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monthly_backtest import (  # noqa: E402
    geometry_trade, is_fixed_income, load_daily, month_edge, norm, permutation_p,
)
from vp_box import BOX_KINDS, make_box, state  # noqa: E402

KIND_FA = {
    "valley_first": "دره — اولین از پایین",
    "valley_nearest": "دره — نزدیک‌ترین به قیمت",
    "valley_deepest": "دره — عمیق‌ترین",
    "value_area": "سه بین پرحجم (داشبورد فعلی)",
}


def pct(xs):
    return statistics.mean(xs) if xs else None


def win_rate(xs):
    return sum(1 for x in xs if x > 0) / len(xs) * 100 if xs else None


def load_series(data_dir, pattern):
    files = sorted(Path(data_dir).glob(pattern))
    series, fps, collisions, thin = {}, {}, [], []
    for p in files:
        name = p.name
        for suf in ("_daily.csv", ".csv"):
            if name.endswith(suf):
                name = name[: -len(suf)]
                break
        rows = load_daily(p)
        if len(rows) < 20:
            thin.append(name)
            continue
        fp = hash(tuple((d.isoformat(), round(b.c, 6)) for d, b in rows))
        if fp in fps:
            collisions.append([name, fps[fp], "سری قیمت یکسان"])
            continue
        fps[fp] = name
        key = norm(name)
        if key in series:
            collisions.append([name, series[key][0], "نام یکسان"])
            continue
        series[key] = (name, rows)
    return files, series, collisions, thin


def analyse(series, kind, min_rows, max_rows, min_bars, iters):
    """همهٔ سنجه‌های یک تعریف باکس."""
    obs, widths, geom, today = [], [], [], []

    for _, (name, rows) in series.items():
        fixed = is_fixed_income(name)
        by_month = defaultdict(list)
        for d, b in rows:
            by_month[(d.year, d.month)].append((d, b))
        months = sorted(by_month)
        if len(months) < 2:
            continue

        for i in range(len(months) - 1):
            m_box, m_fwd = months[i], months[i + 1]
            y, mo = m_box
            if m_fwd != ((y + 1, 1) if mo == 12 else (y, mo + 1)):
                continue
            box_bars = [b for _, b in by_month[m_box]]
            if len(box_bars) < min_bars:
                continue
            fwd = by_month[m_fwd]
            if len(fwd) < 2:
                continue

            ref = box_bars[-1].c              # کلوز آخر ماهِ باکس — بدون لوک‌اهد
            box = make_box(kind, box_bars, ref, min_rows, max_rows)
            if box is None:
                continue

            entry = fwd[0][1].c
            st = state(entry, box)
            w = (box[1] - box[0]) / entry * 100.0
            risk = (entry - box[0]) / entry * 100.0

            def fwd_ret(k):
                if len(fwd) <= k:
                    return None
                return (fwd[k][1].c - entry) / entry * 100.0

            obs.append({
                "month": f"{m_fwd[0]}-{m_fwd[1]:02d}", "sym": name, "fixed": fixed,
                "st": st, "ret": (fwd[-1][1].c - entry) / entry * 100.0,
                "r1": fwd_ret(1), "r5": fwd_ret(5), "risk": risk, "w": w,
            })
            widths.append(w)
            if st == "بالا" and not fixed:
                outcome, r = geometry_trade(box, fwd)
                geom.append((outcome, r))

        # وضعیت امروز: باکس آخرین ماهِ کامل، سنجیده با آخرین کلوز موجود
        last_complete = months[-2]
        box_bars = [b for _, b in by_month[last_complete]]
        if len(box_bars) >= min_bars:
            box = make_box(kind, box_bars, box_bars[-1].c, min_rows, max_rows)
            if box is not None:
                close = rows[-1][1].c
                today.append({
                    "sym": name, "fixed": fixed, "close": close,
                    "lo": box[0], "hi": box[1], "st": state(close, box),
                    "risk": (close - box[0]) / close * 100.0,
                    "month": f"{last_complete[0]}-{last_complete[1]:02d}",
                })

    live = [o for o in obs if not o["fixed"]]

    # ── نرخ پایه در برابر شرطی ──
    cells = {}
    for label, want in (("بدون درآمد ثابت", False), ("فقط درآمد ثابت", True)):
        rows_ = [o for o in obs if o["fixed"] == want]
        if len(rows_) < 10:
            continue
        base = [o["ret"] for o in rows_]
        entry = {"n": len(rows_), "base_win": win_rate(base), "base_ret": pct(base),
                 "states": {}}
        for st in ("بالا", "داخل", "زیر"):
            sel = [o["ret"] for o in rows_ if o["st"] == st]
            if len(sel) < 5:
                continue
            entry["states"][st] = {"n": len(sel), "win": win_rate(sel),
                                   "ret": pct(sel),
                                   "edge_win": win_rate(sel) - entry["base_win"],
                                   "edge_ret": pct(sel) - entry["base_ret"]}
        cells[label] = entry

    # ── جایگشت ──
    by_m = defaultdict(list)
    for o in live:
        by_m[o["month"]].append(o)
    edge, p = permutation_p(by_m, "بالا", iters)
    perm = {"months": len(month_edge(by_m, "بالا")), "edge": edge, "p": p,
            "iters": iters}

    # ── ماه‌به‌ماه ──
    monthly = []
    for m in sorted(by_m):
        rows_ = by_m[m]
        sel = [o["ret"] for o in rows_ if o["st"] == "بالا"]
        if len(rows_) < 5 or len(sel) < 3:
            continue
        b = pct([o["ret"] for o in rows_])
        monthly.append({"m": m, "n": len(rows_), "n_up": len(sel),
                        "base": b, "above": pct(sel), "edge": pct(sel) - b})

    # ── سطل ریسک: آستانهٔ ۷٪ خودشان را می‌سنجد ──
    ups = [o for o in live if o["st"] == "بالا"]
    bands = [(0, 1), (1, 2), (2, 4), (4, 7), (7, 12), (12, 1e9)]
    risk_buckets = []
    for lo, hi in bands:
        sel = [o for o in ups if lo <= o["risk"] < hi]
        if len(sel) < 5:
            continue
        lbl = f"{lo:g}–{hi:g}٪" if hi < 1e9 else f"بالای {lo:g}٪"
        risk_buckets.append({"label": lbl, "n": len(sel),
                             "ret": pct([o["ret"] for o in sel]),
                             "win": win_rate([o["ret"] for o in sel])})

    # ── عرض باکس ──
    ws = sorted(o["w"] for o in live)
    width_buckets = []
    if len(ws) >= 20:
        q1, q3 = ws[len(ws) // 4], ws[3 * len(ws) // 4]
        for lbl, lo, hi in (("باریک", -1, q1), ("متوسط", q1, q3), ("پهن", q3, 1e9)):
            sel = [o for o in ups if lo <= o["w"] < hi]
            if len(sel) < 5:
                continue
            width_buckets.append({"label": lbl, "n": len(sel),
                                  "ret": pct([o["ret"] for o in sel]),
                                  "win": win_rate([o["ret"] for o in sel])})

    # ── افق نگهداری ──
    horizons = []
    for key, lbl in (("r1", "۱ روز"), ("r5", "۵ روز"), ("ret", "پایان ماه")):
        sel = [o[key] for o in ups if o.get(key) is not None]
        allr = [o[key] for o in live if o.get(key) is not None]
        if len(sel) < 5 or len(allr) < 5:
            continue
        horizons.append({"label": lbl, "n": len(sel), "above": pct(sel),
                         "base": pct(allr), "edge": pct(sel) - pct(allr)})

    # ── هندسهٔ ۱:۱ ──
    rs = [r for _, r in geom if r is not None]
    geom_out = None
    if geom:
        geom_out = {
            "n": len(geom),
            "empty": sum(1 for o, _ in geom if o == "خالی") / len(geom) * 100,
            "tp": sum(1 for o, _ in geom if o == "تارگت"),
            "sl": sum(1 for o, _ in geom if o == "استاپ"),
            "avg_r": pct(rs),
        }

    # ── کارنامهٔ هر نماد ──
    per_sym = defaultdict(list)
    for o in ups:
        per_sym[o["sym"]].append(o["ret"])
    per_symbol = sorted(
        ({"sym": s, "n": len(v), "win": win_rate(v), "ret": pct(v)}
         for s, v in per_sym.items() if len(v) >= 2),
        key=lambda d: -d["ret"],
    )

    today.sort(key=lambda d: (d["st"] != "بالا", d["risk"]))
    return {
        "today": today, "cells": cells, "perm": perm, "monthly": monthly,
        "risk_buckets": risk_buckets, "width_buckets": width_buckets,
        "horizons": horizons, "geom": geom_out, "per_symbol": per_symbol,
        "width_median": statistics.median(widths) if widths else None,
        "width_mean": pct(widths),
        "n_obs": len(obs),
    }


TEMPLATE = r"""<title>باکس حجمی ماهانه</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@300;400;600;800&family=IBM+Plex+Mono:wght@400;600&display=swap">
<style>
:root{
  color-scheme: light;
  --bg:#F7F8FA; --panel:#FFFFFF; --ink:#14161A; --ink-2:#565C66; --ink-3:#8A909B;
  --line:#E3E5EA; --line-2:#EEF0F4;
  --s1:#4263EB; --s2:#1098AD; --neg:#E8590C;
  --up:#2B8A3E; --up-bg:#E9F5EC; --mid:#B0740A; --mid-bg:#FBF3E2;
  --dn:#C92A2A; --dn-bg:#FBECEC;
  --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
  --ui:"Vazirmatn",system-ui,-apple-system,"Segoe UI",Tahoma,sans-serif;
}
@media (prefers-color-scheme:dark){ :root:not([data-theme="light"]){
  color-scheme: dark;
  --bg:#101217; --panel:#171A20; --ink:#E9EBEF; --ink-2:#A4AAB6; --ink-3:#727987;
  --line:#272B33; --line-2:#1F232A;
  --s1:#4C6EF5; --s2:#1098AD; --neg:#FF922B;
  --up:#51CF66; --up-bg:#16271B; --mid:#FCC419; --mid-bg:#2A2410;
  --dn:#FF6B6B; --dn-bg:#2B1618;
}}
:root[data-theme="dark"]{
  color-scheme: dark;
  --bg:#101217; --panel:#171A20; --ink:#E9EBEF; --ink-2:#A4AAB6; --ink-3:#727987;
  --line:#272B33; --line-2:#1F232A;
  --s1:#4C6EF5; --s2:#1098AD; --neg:#FF922B;
  --up:#51CF66; --up-bg:#16271B; --mid:#FCC419; --mid-bg:#2A2410;
  --dn:#FF6B6B; --dn-bg:#2B1618;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--ui);
  direction:rtl;font-size:14px;line-height:1.65;-webkit-font-smoothing:antialiased}
.wrap{max-width:1100px;margin:0 auto;padding-inline:16px;padding-block:0 64px}
h1,h2,h3{text-wrap:balance;margin:0}
a{color:var(--s1)}
.num{font-family:var(--mono);font-variant-numeric:tabular-nums;direction:ltr;
  display:inline-block;unicode-bidi:isolate}

header.top{position:sticky;top:env(safe-area-inset-top,0px);z-index:20;
  background:color-mix(in srgb,var(--bg) 88%,transparent);
  backdrop-filter:blur(12px);border-bottom:1px solid var(--line)}
.top-in{max-width:1100px;margin:0 auto;padding:14px 16px;display:flex;
  flex-wrap:wrap;gap:12px 20px;align-items:baseline}
h1{font-size:19px;font-weight:800;letter-spacing:-.01em}
.sub{color:var(--ink-3);font-size:12px;font-family:var(--mono);direction:ltr}
.spacer{flex:1 1 auto;min-width:0}

.picker{display:flex;flex-wrap:wrap;gap:6px;margin:20px 0 6px}
.picker button{font-family:var(--ui);font-size:12.5px;font-weight:600;
  padding:7px 13px;border-radius:999px;border:1px solid var(--line);
  background:var(--panel);color:var(--ink-2);cursor:pointer;
  transition:background .14s,color .14s,border-color .14s}
.picker button:hover{border-color:var(--s1);color:var(--ink)}
.picker button[aria-pressed="true"]{background:var(--s1);border-color:var(--s1);
  color:#fff}
.picker button:focus-visible{outline:2px solid var(--s1);outline-offset:2px}
.picker-note{color:var(--ink-3);font-size:12px;margin:0 0 26px}

section{margin-top:34px}
.eyebrow{font-size:11px;font-weight:600;letter-spacing:.09em;color:var(--ink-3);
  margin-bottom:5px}
h2{font-size:16.5px;font-weight:800;letter-spacing:-.01em}
.lede{color:var(--ink-2);font-size:13px;margin:7px 0 16px;max-width:64ch}

.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  gap:10px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:10px;
  padding:14px 16px}
.tile .k{font-size:11.5px;color:var(--ink-3);font-weight:600}
.tile .v{font-size:27px;font-weight:800;margin-top:3px;letter-spacing:-.02em}
.tile .n{font-size:11.5px;color:var(--ink-3);margin-top:1px}
.tile.up .v{color:var(--up)} .tile.mid .v{color:var(--mid)}
.tile.dn .v{color:var(--dn)}

.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;
  overflow:hidden}
.scroll{overflow:auto;max-height:60vh;overscroll-behavior:contain}
.scroll.short{max-height:none}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:9px 12px;text-align:right;white-space:nowrap;
  border-bottom:1px solid var(--line-2)}
th{font-size:11.5px;font-weight:600;color:var(--ink-3);background:var(--bg);
  position:sticky;top:0}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover{background:var(--line-2)}
td.num,th.num{font-family:var(--mono);font-variant-numeric:tabular-nums;
  direction:ltr;text-align:right}

.pill{display:inline-block;font-size:11.5px;font-weight:600;padding:2px 9px;
  border-radius:999px;line-height:1.5}
.pill.up{background:var(--up-bg);color:var(--up)}
.pill.mid{background:var(--mid-bg);color:var(--mid)}
.pill.dn{background:var(--dn-bg);color:var(--dn)}

/* نوار باکس: جای قیمت نسبت به باکس */
.gauge{width:104px;height:18px;display:block}

.verdict{border-radius:10px;padding:13px 16px;font-size:13px;
  border:1px solid var(--line);background:var(--panel);margin-bottom:14px}
.verdict b{font-weight:800}
.verdict.warn{border-color:color-mix(in srgb,var(--mid) 45%,var(--line));
  background:var(--mid-bg);color:var(--mid)}
.verdict.bad{border-color:color-mix(in srgb,var(--dn) 45%,var(--line));
  background:var(--dn-bg);color:var(--dn)}

.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--ink-2);
  margin:0 0 10px;padding:0 2px}
.legend i{width:10px;height:10px;border-radius:2px;display:inline-block;
  margin-inline-end:6px;vertical-align:-1px}
figure{margin:0;padding:14px 12px 8px}
figcaption{font-size:11.5px;color:var(--ink-3);padding:0 4px 8px}
svg{display:block;max-width:100%;height:auto}
svg text{direction:ltr;unicode-bidi:isolate}
.tip{position:fixed;pointer-events:none;background:var(--ink);color:var(--bg);
  font-size:11.5px;padding:6px 9px;border-radius:6px;opacity:0;
  transition:opacity .1s;z-index:60;white-space:pre;font-family:var(--mono);
  direction:ltr}
.empty{padding:26px 16px;color:var(--ink-3);font-size:13px;text-align:center}
.foot{margin-top:44px;padding-top:18px;border-top:1px solid var(--line);
  color:var(--ink-3);font-size:12px}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
@media (max-width:560px){ .top-in{padding:12px 16px} h1{font-size:17px} }
</style>

<header class="top"><div class="top-in">
  <h1>باکس حجمی ماهانه</h1>
  <span class="sub" id="meta" style="direction:rtl"></span>
  <span class="spacer"></span>
  <span class="sub" id="span"></span>
</div></header>

<div class="wrap">
  <div id="note"></div>
  <div class="picker" id="picker" role="group" aria-label="تعریف باکس"></div>
  <p class="picker-note">تعریف را عوض کنید — هر عددی در این صفحه دوباره حساب می‌شود.</p>
  <div id="app"></div>
  <p class="foot">ساخته‌شده با <span class="num">tools/build_dashboard.py</span>.
    هیچ عددی اینجا توصیهٔ مالی نیست — خوانش قاعده‌های خودتان روی دادهٔ خودتان است.</p>
</div>
<div class="tip" id="tip"></div>

<script>
const DATA = __DATA__;
const KINDS = __KINDS__;
const tip = document.getElementById('tip');

const f1 = v => v==null ? '—' : (v>=0?'+':'') + v.toFixed(1);
const f2 = v => v==null ? '—' : (v>=0?'+':'') + v.toFixed(2);
const p0 = v => v==null ? '—' : v.toFixed(0) + '٪';
const p1 = v => v==null ? '—' : v.toFixed(1) + '٪';
const money = v => v==null ? '—' : v.toLocaleString('en-US',{maximumFractionDigits:0});
const cls = st => st==='بالا'?'up':(st==='زیر'?'dn':'mid');
const esc = s => String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

function showTip(e,txt){ tip.textContent=txt; tip.style.opacity='1';
  tip.style.left=Math.min(e.clientX+12,innerWidth-190)+'px';
  tip.style.top=(e.clientY+14)+'px'; }
function hideTip(){ tip.style.opacity='0'; }

/* ── نوار باکس: کف/سقف باکس و جای کلوز ── */
function gauge(lo,hi,close){
  const span=Math.max(hi-lo,1e-9), pad=span*1.6;
  const a=lo-pad, b=hi+pad, W=104, H=18;
  const x=v=>((v-a)/(b-a))*W;
  const bx=x(lo), bw=Math.max(x(hi)-x(lo),2), cx=Math.max(2,Math.min(W-2,x(close)));
  const col=close>hi?'var(--up)':(close<lo?'var(--dn)':'var(--mid)');
  return `<svg class="gauge" viewBox="0 0 ${W} ${H}" role="img"
    aria-label="کلوز نسبت به باکس">
    <line x1="0" y1="9" x2="${W}" y2="9" stroke="var(--line)" stroke-width="1"/>
    <rect x="${bx.toFixed(1)}" y="4" width="${bw.toFixed(1)}" height="10" rx="2"
      fill="var(--s2)" opacity="0.28"/>
    <rect x="${bx.toFixed(1)}" y="4" width="${bw.toFixed(1)}" height="10" rx="2"
      fill="none" stroke="var(--s2)" stroke-width="1"/>
    <circle cx="${cx.toFixed(1)}" cy="9" r="3.4" fill="${col}"
      stroke="var(--panel)" stroke-width="1.6"/></svg>`;
}

/* ── نمودار میله‌ای دوقطبی: مزیت هر ماه ── */
function edgeChart(rows){
  if(!rows.length) return '<p class="empty">ماه کافی نیست.</p>';
  const W=Math.max(320,rows.length*46+64), H=210, L=44,R=14,T=16,B=46;
  const iw=W-L-R, ih=H-T-B;
  const vals=rows.map(r=>r.edge);
  const m=Math.max(0.5,...vals.map(Math.abs))*1.15;
  const y=v=>T+ih/2-(v/m)*(ih/2);
  const bw=Math.min(26,iw/rows.length*0.62);
  let bars='',ticks='';
  rows.forEach((r,i)=>{
    const cx=L+iw*((i+0.5)/rows.length);
    const y0=y(0), y1=y(r.edge);
    const top=Math.min(y0,y1), h=Math.max(Math.abs(y1-y0),1.5);
    bars+=`<rect x="${(cx-bw/2).toFixed(1)}" y="${top.toFixed(1)}"
      width="${bw.toFixed(1)}" height="${h.toFixed(1)}" rx="3"
      fill="${r.edge>=0?'var(--s1)':'var(--neg)'}"
      data-t="${esc(r.m)}  edge ${f2(r.edge)}pp\nbase ${f2(r.base)}%  above ${f2(r.above)}%\nn=${r.n} (up ${r.n_up})"/>`;
    if(rows.length<=14||i%2===0)
      ticks+=`<text x="${cx.toFixed(1)}" y="${H-B+16}" text-anchor="middle"
        font-size="9.5" font-family="var(--mono)" fill="var(--ink-3)">${esc(r.m)}</text>`;
  });
  let grid='';
  [-m,-m/2,0,m/2,m].forEach(v=>{
    grid+=`<line x1="${L}" y1="${y(v).toFixed(1)}" x2="${W-R}" y2="${y(v).toFixed(1)}"
      stroke="var(${v===0?'--ink-3':'--line-2'})" stroke-width="1"/>
      <text x="${L-7}" y="${(y(v)+3.5).toFixed(1)}" text-anchor="end" font-size="9.5"
      font-family="var(--mono)" fill="var(--ink-3)">${v>0?'+':''}${v.toFixed(1)}</text>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">
    ${grid}${bars}${ticks}
    <text x="${W-R}" y="${T+10}" text-anchor="end" font-size="10"
      fill="var(--ink-3)">واحد درصد</text></svg>`;
}

/* ── میله‌های افقی با برچسب مستقیم ── */
function hbars(rows,key,unit){
  if(!rows.length) return '<p class="empty">داده کافی نیست.</p>';
  const m=Math.max(0.5,...rows.map(r=>Math.abs(r[key])))*1.3;
  return `<div style="display:grid;gap:8px;padding:4px 2px">`+rows.map(r=>{
    const v=r[key], w=Math.abs(v)/m*50;
    const pos=v>=0;
    return `<div style="display:grid;grid-template-columns:96px 1fr 84px;
      gap:10px;align-items:center">
      <span style="font-size:12.5px;color:var(--ink-2)">${esc(r.label)}</span>
      <span style="position:relative;height:17px;background:var(--line-2);
        border-radius:3px;overflow:hidden;direction:ltr">
        <i style="position:absolute;top:0;bottom:0;left:50%;width:1px;
          background:var(--ink-3);opacity:.5"></i>
        <i style="position:absolute;top:2px;bottom:2px;border-radius:3px;
          ${pos?`left:50%;width:${w}%`:`right:50%;width:${w}%`};
          background:${pos?'var(--s1)':'var(--neg)'}"></i></span>
      <span class="num" style="font-size:12px;color:var(--ink-2)">${f2(v)}${unit} · n=${r.n}</span>
    </div>`;
  }).join('')+`</div>`;
}

function tbl(head,rows,extra){
  return `<div class="panel scroll ${extra||''}"><table><thead><tr>`+
    head.map(h=>`<th class="${h[1]||''}">${h[0]}</th>`).join('')+
    `</tr></thead><tbody>`+rows.join('')+`</tbody></table></div>`;
}

function render(kind){
  const d=DATA.defs[kind], M=DATA.meta;
  document.querySelectorAll('#picker button').forEach(b=>
    b.setAttribute('aria-pressed', String(b.dataset.k===kind)));

  const t=d.today, live=t.filter(r=>!r.fixed);
  const c={بالا:0,داخل:0,زیر:0}; live.forEach(r=>c[r.st]++);
  const tot=live.length||1;
  const cell=d.cells['بدون درآمد ثابت'];
  const perm=d.perm;

  let h='';

  /* ۱ — امروز */
  h+=`<section><div class="eyebrow">وضعیت</div>
    <h2>امروز</h2>
    <p class="lede">باکس از ماه کامل‌شدهٔ قبل ساخته شده و با آخرین کلوز موجود
      سنجیده می‌شود. صندوق درآمد ثابت از این شمارش بیرون است.</p>
    <div class="tiles">
      <div class="tile up"><div class="k">بالای باکس</div>
        <div class="v"><span class="num">${c['بالا']}</span></div>
        <div class="n">${p0(c['بالا']/tot*100)} از ${tot} نماد</div></div>
      <div class="tile mid"><div class="k">داخل باکس</div>
        <div class="v"><span class="num">${c['داخل']}</span></div>
        <div class="n">${p0(c['داخل']/tot*100)}</div></div>
      <div class="tile dn"><div class="k">زیر باکس</div>
        <div class="v"><span class="num">${c['زیر']}</span></div>
        <div class="n">${p0(c['زیر']/tot*100)}</div></div>
      <div class="tile"><div class="k">میانهٔ عرض باکس</div>
        <div class="v"><span class="num">${d.width_median==null?'—':d.width_median.toFixed(2)+'٪'}</span></div>
        <div class="n">انگشت‌نگاری تعریف</div></div>
    </div>`;

  if(c['بالا']/tot > 0.9)
    h+=`<div class="verdict warn" style="margin-top:14px">⚠️ <b>${p0(c['بالا']/tot*100)}
      نمادها بالای باکس‌اند.</b> شرطی که روی تقریباً کل جهان نماد روشن می‌شود
      فیلتر نیست — جهت بازار را می‌گوید، نه انتخاب نماد.</div>`;

  h+=`<div style="height:14px"></div>`+tbl(
    [['نماد'],['کلوز','num'],['باکس','num'],['ریسک تا کف','num'],['وضعیت'],['جای کلوز']],
    live.map(r=>`<tr><td>${esc(r.sym)}</td>
      <td class="num">${money(r.close)}</td>
      <td class="num">${money(r.lo)} – ${money(r.hi)}</td>
      <td class="num">${r.risk==null?'—':r.risk.toFixed(2)+'٪'}</td>
      <td><span class="pill ${cls(r.st)}">${r.st}</span></td>
      <td>${gauge(r.lo,r.hi,r.close)}</td></tr>`));
  h+=`</section>`;

  /* ۲ — نرخ پایه */
  h+=`<section><div class="eyebrow">اعتبارسنجی</div>
    <h2>نرخ پایه در برابر شرطی</h2>
    <p class="lede">نرخ برد به‌تنهایی عدد نیست. ستون «مزیت» فاصله تا گروه کنترل
      است — اگر نزدیک صفر بود، باکس چیزی اضافه نکرده.</p>`;
  const cellRows=[];
  for(const [label,cc] of Object.entries(d.cells)){
    cellRows.push(`<tr><td colspan="6" style="background:var(--bg);
      font-weight:600;font-size:12px;color:var(--ink-2)">${esc(label)} —
      پایه <span class="num">${p1(cc.base_win)}</span> مثبت،
      میانگین <span class="num">${f2(cc.base_ret)}٪</span> · n=<span class="num">${cc.n}</span></td></tr>`);
    for(const [st,s] of Object.entries(cc.states))
      cellRows.push(`<tr><td><span class="pill ${cls(st)}">${st}</span></td>
        <td class="num">${s.n}</td><td class="num">${p1(s.win)}</td>
        <td class="num">${f1(s.edge_win)}</td>
        <td class="num">${f2(s.ret)}٪</td>
        <td class="num">${f2(s.edge_ret)}</td></tr>`);
  }
  h+=tbl([['حالت'],['n','num'],['برد','num'],['مزیت برد','num'],
          ['میانگین','num'],['مزیت بازده','num']],cellRows,'short')+`</section>`;

  /* ۳ — جایگشت */
  const pv=perm.p, floor=1/((perm.iters||5000)+1);
  h+=`<section><div class="eyebrow">معناداری</div>
    <h2>تست جایگشت</h2>
    <p class="lede">برچسب «بالا» داخل هر ماه به‌هم ریخته می‌شود، پس حرکت کل بازار
      و تعداد سیگنال آن ماه ثابت می‌ماند. تنها سؤال: آیا باکس بهتر از تصادف
      انتخاب می‌کند؟</p>`;
  if(pv==null){
    h+=`<div class="verdict bad">ماه کافی برای تست نیست
      (<span class="num">${perm.months}</span> ماه قابل‌استفاده).</div>`;
  }else{
    h+=`<div class="tiles">
      <div class="tile"><div class="k">مزیت ماهانه</div>
        <div class="v"><span class="num">${f2(perm.edge)}</span></div>
        <div class="n">واحد درصد</div></div>
      <div class="tile ${pv<0.05?'up':'mid'}"><div class="k">p</div>
        <div class="v"><span class="num">${pv.toFixed(4)}</span></div>
        <div class="n">${pv<0.05?'از تصادف قابل تفکیک':'از تصادف قابل تفکیک نیست'}</div></div>
      <div class="tile"><div class="k">ماه قابل‌استفاده</div>
        <div class="v"><span class="num">${perm.months}</span></div>
        <div class="n">n مؤثر، نه تعداد معامله</div></div>
      <div class="tile"><div class="k">کف p</div>
        <div class="v"><span class="num">${floor.toFixed(5)}</span></div>
        <div class="n">۱/(تکرار+۱) — نه تابع تعداد ماه</div></div></div>`;
    h+=`<div class="verdict ${pv<0.05?'ok':'warn'}" style="margin-top:14px">
      کف p برابر <span class="num">${floor.toFixed(5)}</span> است، نه
      <span class="num">${(1/(M.months_n+1)).toFixed(2)}</span>: برچسب سیگنال
      <b>داخل</b> هر ماه جابه‌جا می‌شود و هر ماه ده‌ها نماد دارد، پس تعداد
      جایگشت ممکن نجومی است. آنچه <b>${M.months_n} ماه</b> محدود می‌کند
      تعمیم‌پذیری است، نه تفکیک‌پذیری — p کوچک می‌گوید باکس
      <b>در این دوره</b> بهتر از تصادف انتخاب کرده، نه اینکه همیشه می‌کند.</div>`;
  }
  h+=`</section>`;

  /* ۴ — ماه‌به‌ماه */
  h+=`<section><div class="eyebrow">پایداری</div>
    <h2>مزیت ماه‌به‌ماه</h2>
    <p class="lede">بازده «بالا» منهای بازده همهٔ نمادهای همان ماه. اگر مزیت
      واقعی باشد باید اغلب ماه‌ها مثبت بماند، نه اینکه چند ماه بزرگ بقیه را
      بپوشاند.</p>
    <div class="legend">
      <span><i style="background:var(--s1)"></i>ماه مثبت</span>
      <span><i style="background:var(--neg)"></i>ماه منفی</span></div>
    <div class="panel"><figure>${edgeChart(d.monthly)}
      <figcaption>${d.monthly.filter(r=>r.edge>0).length} از
        ${d.monthly.length} ماه مثبت</figcaption></figure></div></section>`;

  /* ۵ — سطل ریسک */
  h+=`<section><div class="eyebrow">آستانه</div>
    <h2>آیا ریسک کمتر بازده بیشتر می‌دهد؟</h2>
    <p class="lede">قاعدهٔ شما می‌گوید «بالای باکس با فاصلهٔ کم یعنی نزدیک
      حمایت». اگر درست باشد، سطل‌های کم‌ریسک باید بازده بهتری بدهند. آستانهٔ
      <span class="num">RISK_RELAXED = 7</span> اینجا سنجیده می‌شود.</p>
    <div class="panel"><figure>${hbars(d.risk_buckets,'ret','٪')}
      <figcaption>میانگین بازده ماه بعد، به تفکیک فاصله تا کف باکس</figcaption>
      </figure></div></section>`;

  /* ۶ — افق */
  h+=`<section><div class="eyebrow">افق</div>
    <h2>سیگنال چند وقت زنده می‌ماند؟</h2>
    <p class="lede">مزیت نسبت به نرخ پایه در سه افق. اگر فقط در یک افق مثبت
      باشد، احتمالاً نویز است.</p>
    <div class="panel"><figure>${hbars(d.horizons,'edge','')}
      <figcaption>مزیت بر حسب واحد درصد، نسبت به نرخ پایهٔ همان افق</figcaption>
      </figure></div></section>`;

  /* ۷ — هندسه */
  h+=`<section><div class="eyebrow">اجرا</div>
    <h2>هندسهٔ ۱:۱</h2>
    <p class="lede">ورود روی پولبک به سقف باکس، استاپ کف باکس، تارگت به اندازهٔ
      ارتفاع باکس. اگر پولبک نخورد «حمایت خالی» است و معامله‌ای نیست.</p>`;
  if(d.geom){
    h+=`<div class="tiles">
      <div class="tile"><div class="k">سیگنال</div>
        <div class="v"><span class="num">${d.geom.n}</span></div></div>
      <div class="tile mid"><div class="k">حمایت خالی</div>
        <div class="v"><span class="num">${d.geom.empty.toFixed(0)+'٪'}</span></div>
        <div class="n">پولبک نخورد</div></div>
      <div class="tile up"><div class="k">تارگت</div>
        <div class="v"><span class="num">${d.geom.tp}</span></div></div>
      <div class="tile dn"><div class="k">استاپ</div>
        <div class="v"><span class="num">${d.geom.sl}</span></div></div>
      <div class="tile"><div class="k">میانگین R</div>
        <div class="v"><span class="num">${f2(d.geom.avg_r)}</span></div></div></div>
    <div class="verdict" style="margin-top:14px">عدد خام R را مزیت نخوانید —
      ورود روی پولبک ذاتاً انتخابی است و روی دادهٔ بدون سیگنال هم R مثبت
      می‌دهد. این ستون برای <b>مقایسهٔ تعریف‌ها با هم</b> مفید است.</div>`;
  } else h+=`<p class="empty">سیگنالی برای سنجش نبود.</p>`;
  h+=`</section>`;

  /* ۸ — عرض باکس */
  if(d.width_buckets.length){
    h+=`<section><div class="eyebrow">شکل ناحیه</div>
      <h2>باکس باریک در برابر پهن</h2>
      <p class="lede">عرض باکس مستقیماً «ریسک» را تعیین می‌کند. اگر تعریف عوض
        شود عرض چند برابر می‌شود و آستانهٔ ۷٪ معنای دیگری پیدا می‌کند.</p>
      <div class="panel"><figure>${hbars(d.width_buckets,'ret','٪')}
        <figcaption>میانگین بازده، به تفکیک چارک عرض باکس</figcaption>
        </figure></div></section>`;
  }

  /* ۹ — نمادها */
  if(d.per_symbol.length){
    h+=`<section><div class="eyebrow">تفکیک</div>
      <h2>کارنامهٔ هر نماد</h2>
      <p class="lede">فقط نمادهایی با دست‌کم ۲ سیگنال. با این تعداد ماه، رتبهٔ
        بالا و پایین این جدول عمدتاً تصادف است — برای انتخاب نماد از رویش
        استفاده نکنید.</p>`;
    h+=tbl([['نماد'],['سیگنال','num'],['برد','num'],['میانگین','num']],
      d.per_symbol.map(r=>`<tr><td>${esc(r.sym)}</td>
        <td class="num">${r.n}</td><td class="num">${p0(r.win)}</td>
        <td class="num">${f2(r.ret)}٪</td></tr>`))+`</section>`;
  }

  document.getElementById('app').innerHTML=h;
  document.querySelectorAll('svg [data-t]').forEach(el=>{
    el.addEventListener('mousemove',e=>showTip(e,el.dataset.t));
    el.addEventListener('mouseleave',hideTip);
  });
}

(function init(){
  const M=DATA.meta;
  if(M.note) document.getElementById('note').innerHTML =
    `<div class="verdict warn" style="margin-top:20px">${esc(M.note)}</div>`;
  document.getElementById('meta').innerHTML =
    `<span class="num">${M.symbols}</span> نماد ·` +
    ` <span class="num">${M.months_n}</span> ماه`;
  document.getElementById('span').textContent =
    (M.span ? M.span + '  ·  ' : '') + M.generated;
  const pick=document.getElementById('picker');
  KINDS.forEach(k=>{
    const b=document.createElement('button');
    b.type='button'; b.dataset.k=k.id; b.textContent=k.fa;
    b.setAttribute('aria-pressed','false');
    b.addEventListener('click',()=>{ render(k.id);
      try{localStorage.setItem('vp_kind',k.id)}catch(e){} });
    pick.appendChild(b);
  });
  let start=KINDS[0].id;
  try{ const s=localStorage.getItem('vp_kind');
    if(s && DATA.defs[s]) start=s; }catch(e){}
  render(start);
})();
</script>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--glob", default="*_daily.csv")
    ap.add_argument("--out", default="dashboard.html")
    ap.add_argument("--min-rows", type=int, default=3)
    ap.add_argument("--max-rows", type=int, default=20)
    ap.add_argument("--min-bars", type=int, default=8)
    ap.add_argument("--iters", type=int, default=5000)
    ap.add_argument("--note", default="", help="بنر هشدار بالای صفحه")
    ap.add_argument("--artifact", action="store_true",
                    help="بدون اسکلت html/head/body — برای انتشار روی claude.ai")
    args = ap.parse_args()

    files, series, collisions, thin = load_series(args.data, args.glob)
    if not series:
        print(f"هیچ فایل قابل‌استفاده‌ای در {args.data} نبود.")
        return 1

    print(f"فایل: {len(files)} · نماد یکتا: {len(series)} · "
          f"کم‌داده: {len(thin)} · تکراری: {len(collisions)}")

    defs = {}
    for k in BOX_KINDS:
        print(f"  {KIND_FA[k]} ...", end=" ", flush=True)
        defs[k] = analyse(series, k, args.min_rows, args.max_rows,
                          args.min_bars, args.iters)
        pv = defs[k]["perm"]["p"]
        print(f"n={defs[k]['n_obs']}  p={'—' if pv is None else f'{pv:.4f}'}")

    months = sorted({m["m"] for d in defs.values() for m in d["monthly"]})
    meta = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "symbols": len(series),
        "months_n": len(months),
        "span": f"{months[0]} → {months[-1]}" if months else "",
        "files": len(files),
        "collisions": collisions,
        "thin": len(thin),
        "note": args.note,
    }

    html = (TEMPLATE
            .replace("__DATA__", json.dumps({"meta": meta, "defs": defs},
                                            ensure_ascii=False))
            .replace("__KINDS__", json.dumps(
                [{"id": k, "fa": KIND_FA[k]} for k in BOX_KINDS],
                ensure_ascii=False)))

    if not args.artifact:
        # فایل محلی اسکلت کامل می‌خواهد؛ نسخهٔ claude.ai خودش آن را می‌گذارد
        html = ('<!doctype html>\n<html lang="fa" dir="rtl">\n<head>\n'
                '<meta charset="utf-8">\n<meta name="viewport" '
                'content="width=device-width,initial-scale=1,viewport-fit=cover">\n'
                + html + '\n</head>\n<body>\n</body>\n</html>\n')

    out = Path(args.out)
    out.write_text(html, encoding="utf-8")
    print(f"\nداشبورد: {out.resolve()}  ({len(html)//1024} کیلوبایت)")
    if collisions:
        print("نمادهای حذف‌شده:")
        for a, b, why in collisions[:10]:
            print(f"    {a} ≡ {b}  ({why})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
