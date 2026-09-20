# -*- coding: utf-8 -*-
"""
داشبورد تصمیم و پرتفو — از خروجی `export_monthly_risk.py`.

ورودی همان متنی است که اسکریپت شما چاپ می‌کند:

    کهربا | کلوز 227899.0 | جاری 223360.0-226440.0 ریسک 0.64% سبز | قبل ریسک 10.96% سبز

خروجی یک فایل HTML خودکفاست با:
  ۱. تصمیم امروز
  ۲. پرتفوی پیشنهادی — سایز هر پوزیشن از روی ریسک تا کف باکس
  ۳. جدول کامل نمادها با نوار باکس
  ۴. گذار ماه قبل → این ماه
  ۵. توزیع ریسک
  ۶. هشدارهای دیتا (نماد تکراری، برخورد نام، درآمد ثابت)

این داشبورد **بک‌تست ندارد** — بک‌تست به سری زمانی نیاز دارد، نه به یک
عکس لحظه‌ای. برای آن `build_dashboard.py` را روی `data_auto` اجرا کنید.

اجرا:
    python3 tools/snapshot_dashboard.py --in data/risk_export.txt \
        --out decision.html --capital 1000000000
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monthly_backtest import is_fixed_income, norm  # noqa: E402

ROW = re.compile(
    r"^(?P<sym>.+?)\s*\|\s*کلوز\s*(?P<close>[\d.]+)\s*\|\s*"
    r"جاری\s*(?P<lo>[\d.]+)-(?P<hi>[\d.]+)\s*ریسک\s*(?P<risk>-?[\d.]+)%\s*"
    r"(?P<st>\S+)\s*\|\s*قبل\s*ریسک\s*(?P<prisk>-?[\d.]+|NA)%?\s*(?P<pst>\S+)?\s*$"
)
STATE = {"سبز": "بالا", "قرمز": "زیر", "داخل": "داخل"}


def parse(text):
    rows, bad = [], []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("="):
            continue
        m = ROW.match(line)
        if not m:
            bad.append(line)
            continue
        g = m.groupdict()
        prisk = None if g["prisk"] == "NA" else float(g["prisk"])
        pst = STATE.get(g["pst"] or "", None)
        rows.append({
            "sym": g["sym"].strip(),
            "close": float(g["close"]),
            "lo": float(g["lo"]),
            "hi": float(g["hi"]),
            "risk": float(g["risk"]),
            "st": STATE.get(g["st"], g["st"]),
            "prisk": prisk,
            "pst": pst,
            "fixed": is_fixed_income(g["sym"].strip()),
        })
    return rows, bad


def dedupe(rows):
    """نماد تکراری و برخورد نام را جدا می‌کند."""
    keep, dropped, by_name, by_series = [], [], {}, {}
    for r in rows:
        key = norm(r["sym"])
        sig = (round(r["close"], 4), round(r["lo"], 4), round(r["hi"], 4))
        if key in by_name:
            dropped.append([r["sym"], by_name[key], "نام یکسان پس از نرمال‌سازی"])
            continue
        if sig in by_series:
            dropped.append([r["sym"], by_series[sig], "کلوز و باکس یکسان — برخورد نماد"])
            continue
        by_name[key] = r["sym"]
        by_series[sig] = r["sym"]
        keep.append(r)
    return keep, dropped


def build_portfolio(rows, capital, sleeve, max_risk, total_risk, top_n, max_weight):
    """سایز پوزیشن از روی فاصله تا استاپ.

    استاپ کف باکس است. بودجهٔ ریسک کل سبد `total_risk`٪ سرمایه است و بین
    `top_n` پوزیشن پخش می‌شود، پس هر پوزیشن `total_risk/top_n`٪ سرمایه ریسک
    می‌کند و مبلغش = سرمایه × (سهم ریسک) ÷ ریسک٪. نمادی با استاپ نزدیک مبلغ
    بیشتری می‌گیرد، چون ضرر همان مبلغ تا استاپ کمتر است.

    اگر جمع مبالغ از سهم هستهٔ ماهانه بیشتر شود، همه به نسبت کوچک می‌شوند و
    این در خروجی گزارش می‌شود — یعنی سقف سرمایه بسته، نه بودجهٔ ریسک.
    """
    elig = [r for r in rows
            if r["st"] == "بالا" and not r["fixed"] and 0 < r["risk"] <= max_risk]
    elig.sort(key=lambda r: r["risk"])
    picked = elig[:top_n]
    if not picked:
        return [], {"eligible": len(elig), "held": 0, "spent": 0.0,
                    "risked": 0.0, "risk_pct": 0.0, "scaled": 1.0}

    per = total_risk / len(picked)          # ٪ سرمایه که هر پوزیشن ریسک می‌کند
    pool = capital * sleeve
    amounts = [min(capital * per / r["risk"], capital * max_weight / 100)
               for r in picked]
    scale = min(1.0, pool / sum(amounts)) if sum(amounts) > 0 else 1.0

    out = []
    for r, amt in zip(picked, amounts):
        amt *= scale
        units = int(amt // r["close"])
        spend = units * r["close"]
        if units <= 0:
            continue
        out.append({**r, "weight": spend / capital * 100, "amount": spend,
                    "units": units, "risk_rial": spend * r["risk"] / 100})
    spent = sum(o["amount"] for o in out)
    risked = sum(o["risk_rial"] for o in out)
    return out, {"eligible": len(elig), "held": len(out), "spent": spent,
                 "cash": capital - spent, "risked": risked,
                 "risk_pct": risked / capital * 100 if capital else 0.0,
                 "scaled": scale}


TEMPLATE = r"""<title>تصمیم و پرتفوی ماهانه</title>
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
h1,h2{text-wrap:balance;margin:0}
.num{font-family:var(--mono);font-variant-numeric:tabular-nums;direction:ltr;
  display:inline-block;unicode-bidi:isolate}
header.top{position:sticky;top:env(safe-area-inset-top,0px);z-index:20;
  background:color-mix(in srgb,var(--bg) 88%,transparent);
  backdrop-filter:blur(12px);border-bottom:1px solid var(--line)}
.top-in{max-width:1100px;margin:0 auto;padding:14px 16px;display:flex;
  flex-wrap:wrap;gap:10px 18px;align-items:baseline}
h1{font-size:19px;font-weight:800;letter-spacing:-.01em}
.sub{color:var(--ink-3);font-size:12px}
.spacer{flex:1 1 auto;min-width:0}
section{margin-top:34px}
.eyebrow{font-size:11px;font-weight:600;letter-spacing:.09em;color:var(--ink-3);
  margin-bottom:5px}
h2{font-size:16.5px;font-weight:800;letter-spacing:-.01em}
.lede{color:var(--ink-2);font-size:13px;margin:7px 0 16px;max-width:64ch}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(148px,1fr));gap:10px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:10px;
  padding:14px 16px}
.tile .k{font-size:11.5px;color:var(--ink-3);font-weight:600}
.tile .v{font-size:26px;font-weight:800;margin-top:3px;letter-spacing:-.02em}
.tile .n{font-size:11.5px;color:var(--ink-3);margin-top:1px}
.tile.up .v{color:var(--up)} .tile.mid .v{color:var(--mid)} .tile.dn .v{color:var(--dn)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;
  overflow:hidden}
.scroll{overflow:auto;max-height:62vh;overscroll-behavior:contain}
.scroll.short{max-height:none}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:9px 12px;text-align:right;white-space:nowrap;
  border-bottom:1px solid var(--line-2)}
th{font-size:11.5px;font-weight:600;color:var(--ink-3);background:var(--bg);
  position:sticky;top:0;z-index:1}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover{background:var(--line-2)}
td.num,th.num{font-family:var(--mono);font-variant-numeric:tabular-nums;
  direction:ltr;text-align:right}
tfoot td{font-weight:700;background:var(--bg);border-top:1px solid var(--line)}
.pill{display:inline-block;font-size:11.5px;font-weight:600;padding:2px 9px;
  border-radius:999px;line-height:1.5}
.pill.up{background:var(--up-bg);color:var(--up)}
.pill.mid{background:var(--mid-bg);color:var(--mid)}
.pill.dn{background:var(--dn-bg);color:var(--dn)}
.gauge{width:104px;height:18px;display:block}
.verdict{border-radius:10px;padding:13px 16px;font-size:13px;
  border:1px solid var(--line);background:var(--panel);margin:14px 0}
.verdict b{font-weight:800}
.verdict.warn{border-color:color-mix(in srgb,var(--mid) 45%,var(--line));
  background:var(--mid-bg);color:var(--mid)}
.ctrl{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end;margin:0 0 16px}
.ctrl label{display:flex;flex-direction:column;gap:5px;font-size:11.5px;
  color:var(--ink-3);font-weight:600}
.ctrl input{font-family:var(--mono);font-size:14px;direction:ltr;text-align:right;
  padding:8px 11px;border:1px solid var(--line);border-radius:8px;
  background:var(--panel);color:var(--ink);width:160px}
.ctrl input:focus-visible{outline:2px solid var(--s1);outline-offset:1px}
figure{margin:0;padding:14px 12px 8px}
figcaption{font-size:11.5px;color:var(--ink-3);padding:0 4px 8px}
svg{display:block;max-width:100%;height:auto}
svg text{direction:ltr;unicode-bidi:isolate}
.foot{margin-top:44px;padding-top:18px;border-top:1px solid var(--line);
  color:var(--ink-3);font-size:12px}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style>

<header class="top"><div class="top-in">
  <h1>تصمیم و پرتفوی ماهانه</h1>
  <span class="sub" id="meta"></span>
  <span class="spacer"></span>
  <span class="sub num" id="stamp"></span>
</div></header>

<div class="wrap"><div id="app"></div>
  <p class="foot">ساخته‌شده از خروجی <span class="num">export_monthly_risk.py</span>.
    این خوانش قاعده‌های خودتان روی دادهٔ خودتان است، نه توصیهٔ مالی.</p>
</div>

<script>
const D = __DATA__;
const money = v => v==null?'—':Math.round(v).toLocaleString('en-US');
const p2 = v => v==null?'—':v.toFixed(2)+'٪';
const cls = st => st==='بالا'?'up':(st==='زیر'?'dn':'mid');
const esc = s => String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

function gauge(lo,hi,close){
  const span=Math.max(hi-lo,1e-9), pad=span*1.6, a=lo-pad, b=hi+pad, W=104,H=18;
  const x=v=>((v-a)/(b-a))*W;
  const bx=x(lo), bw=Math.max(x(hi)-x(lo),2), cx=Math.max(2,Math.min(W-2,x(close)));
  const col=close>hi?'var(--up)':(close<lo?'var(--dn)':'var(--mid)');
  return `<svg class="gauge" viewBox="0 0 ${W} ${H}" role="img" aria-label="کلوز نسبت به باکس">
    <line x1="0" y1="9" x2="${W}" y2="9" stroke="var(--line)" stroke-width="1"/>
    <rect x="${bx.toFixed(1)}" y="4" width="${bw.toFixed(1)}" height="10" rx="2"
      fill="var(--s2)" opacity="0.28"/>
    <rect x="${bx.toFixed(1)}" y="4" width="${bw.toFixed(1)}" height="10" rx="2"
      fill="none" stroke="var(--s2)" stroke-width="1"/>
    <circle cx="${cx.toFixed(1)}" cy="9" r="3.4" fill="${col}"
      stroke="var(--panel)" stroke-width="1.6"/></svg>`;
}

/* هیستوگرام ریسک — یک سری، بدون legend */
function riskHist(rows){
  const bands=[[0,1],[1,2],[2,3],[3,4],[4,5],[5,7],[7,100]];
  const lab=bands.map(([a,b])=>b===100?'7+':`${a}–${b}`);
  const cnt=bands.map(([a,b])=>rows.filter(r=>r.risk>=a&&r.risk<b).length);
  const W=560,H=170,L=34,R=12,T=14,B=34, iw=W-L-R, ih=H-T-B;
  const m=Math.max(1,...cnt);
  const bw=iw/bands.length*0.66;
  let bars='',lbls='';
  cnt.forEach((c,i)=>{
    const cx=L+iw*((i+0.5)/bands.length), h=c/m*ih, y=T+ih-h;
    bars+=`<rect x="${(cx-bw/2).toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}"
      height="${Math.max(h,1).toFixed(1)}" rx="3" fill="var(--s1)"/>`;
    if(c) bars+=`<text x="${cx.toFixed(1)}" y="${(y-5).toFixed(1)}" text-anchor="middle"
      font-size="10.5" font-family="var(--mono)" fill="var(--ink-2)">${c}</text>`;
    lbls+=`<text x="${cx.toFixed(1)}" y="${H-B+16}" text-anchor="middle" font-size="10"
      font-family="var(--mono)" fill="var(--ink-3)">${lab[i]}</text>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">
    <line x1="${L}" y1="${T+ih}" x2="${W-R}" y2="${T+ih}" stroke="var(--line)"/>
    ${bars}${lbls}
    <text x="${W-R}" y="${T+8}" text-anchor="end" font-size="10"
      fill="var(--ink-3)">٪ ریسک تا کف باکس</text></svg>`;
}

function renderPortfolio(){
  const cap=Math.max(0,Number(document.getElementById('cap').value)||0);
  const totalRisk=Math.max(0.1,Number(document.getElementById('bud').value)||3);
  const maxRisk=Math.max(0.1,Number(document.getElementById('mr').value)||7);
  const topN=Math.max(1,Number(document.getElementById('top').value)||12);
  const sleeve=D.cfg.sleeve, maxW=D.cfg.max_weight;

  const elig=D.rows.filter(r=>r.st==='بالا'&&!r.fixed&&r.risk>0&&r.risk<=maxRisk)
                   .sort((a,b)=>a.risk-b.risk);
  const picked=elig.slice(0,topN);
  const per = picked.length ? totalRisk/picked.length : 0;
  const pool = cap*sleeve;
  let amts = picked.map(r=>Math.min(cap*per/r.risk, cap*maxW/100));
  const sum0 = amts.reduce((a,b)=>a+b,0);
  const scale = sum0>0 ? Math.min(1, pool/sum0) : 1;

  let rowsOut=picked.map((r,i)=>{
    const amt=amts[i]*scale, units=Math.floor(amt/r.close), spend=units*r.close;
    return {...r, w:spend/cap*100, amount:spend, units, risk_rial:spend*r.risk/100};
  }).filter(o=>o.units>0);

  const spent=rowsOut.reduce((a,o)=>a+o.amount,0);
  const risked=rowsOut.reduce((a,o)=>a+o.risk_rial,0);

  document.getElementById('pf-tiles').innerHTML=`
    <div class="tile"><div class="k">پوزیشن</div>
      <div class="v"><span class="num">${rowsOut.length}</span></div>
      <div class="n">از ${elig.length} واجد شرایط</div></div>
    <div class="tile"><div class="k">تخصیص‌یافته</div>
      <div class="v"><span class="num">${money(spent)}</span></div>
      <div class="n">${p2(cap?spent/cap*100:0)} از سرمایه · سقف سهم ${(sleeve*100).toFixed(0)}٪</div></div>
    <div class="tile"><div class="k">نقد باقی‌مانده</div>
      <div class="v"><span class="num">${money(cap-spent)}</span></div>
      <div class="n">سبد دیلی و هفتگی از این</div></div>
    <div class="tile mid"><div class="k">ریسک تا استاپ</div>
      <div class="v"><span class="num">${p2(cap?risked/cap*100:0)}</span></div>
      <div class="n">${money(risked)} ریال اگر همه استاپ بخورند</div></div>`;

  // تشخیص: باکس باریک، استاپ را غیرعملی و سایز لازم را نجومی می‌کند
  const med = picked.length
    ? [...picked].map(r=>r.risk).sort((a,b)=>a-b)[Math.floor(picked.length/2)] : 0;
  const needW = med>0 ? per/med*100 : 0;   // ٪ سرمایه لازم برای بودجهٔ ریسک
  let note='';
  if(picked.length && needW>maxW){
    note+=`<div class="verdict warn"><b>استاپ برای این بودجهٔ ریسک خیلی نزدیک است.</b>
      میانهٔ فاصله تا کف باکس <span class="num">${med.toFixed(2)}٪</span> است.
      برای اینکه هر پوزیشن <span class="num">${per.toFixed(2)}٪</span> سرمایه
      ریسک کند، سایزش باید <span class="num">${needW.toFixed(0)}٪</span> سرمایه
      شود — که غیرعملی است، پس سقف وزن
      <span class="num">${maxW}٪</span> بسته و ریسک واقعی به
      <span class="num">${p2(cap?risked/cap*100:0)}</span> رسید.
      <br><br>این پیامد مستقیم <b>باریک‌بودن باکس</b> است: با تعریف
      «سه بین پرحجم» عرض باکس حدود ۱٪ درمی‌آید و استاپی به این نزدیکی را
      نوسان عادی روز می‌زند. سایز از ریسک تعیین نمی‌شود، از سقف سرمایه
      تعیین می‌شود — یعنی مدل ریسک عملاً کار نمی‌کند.</div>`;
  }
  if(scale<0.999){
    note+=`<div class="verdict warn">سهم هستهٔ ماهانه
      (<span class="num">${(sleeve*100).toFixed(0)}٪</span>) بسته است — مبالغ
      <span class="num">${((1-scale)*100).toFixed(0)}٪</span> کوچک شدند.
      برای رسیدن به بودجهٔ ریسک یا تعداد پوزیشن را کم کنید یا سهم هسته را
      بالا ببرید.</div>`;
  }
  document.getElementById('pf-note').innerHTML = note;

  document.getElementById('pf-rows').innerHTML = rowsOut.length ? rowsOut.map(o=>`
    <tr><td>${esc(o.sym)}</td>
      <td class="num">${money(o.close)}</td>
      <td class="num">${o.risk.toFixed(2)}٪</td>
      <td class="num">${o.w.toFixed(2)}٪</td>
      <td class="num">${money(o.units)}</td>
      <td class="num">${money(o.amount)}</td>
      <td class="num">${money(o.risk_rial)}</td>
      <td class="num">${money(o.lo)}</td></tr>`).join('')
    : `<tr><td colspan="8" style="text-align:center;color:var(--ink-3);padding:24px">
       با این آستانه نمادی واجد شرایط نشد.</td></tr>`;

  document.getElementById('pf-foot').innerHTML = rowsOut.length ? `
    <tr><td>جمع</td><td class="num">—</td><td class="num">—</td>
      <td class="num">${rowsOut.reduce((a,o)=>a+o.w,0).toFixed(2)}٪</td>
      <td class="num">—</td><td class="num">${money(spent)}</td>
      <td class="num">${money(risked)}</td><td class="num">—</td></tr>` : '';
}

(function init(){
  const S=D.stats, cfg=D.cfg;
  document.getElementById('meta').textContent =
    `${D.rows.length} نماد · ${S.fixed} درآمد ثابت`;
  document.getElementById('stamp').textContent = D.generated;

  let h='';

  /* ۱ — تصمیم امروز */
  h+=`<section><div class="eyebrow">تصمیم</div><h2>امروز</h2>
    <p class="lede">باکس از ماه کامل‌شدهٔ قبل. «بالای باکس با فاصلهٔ کم» یعنی
      نزدیک حمایت — همان‌جایی که قاعدهٔ شما می‌گوید فروشنده نیست.</p>
    <div class="tiles">
      <div class="tile up"><div class="k">بالای باکس</div>
        <div class="v"><span class="num">${S.above}</span></div>
        <div class="n">${p2(S.above/S.live*100)} از ${S.live} نماد غیرثابت</div></div>
      <div class="tile mid"><div class="k">داخل باکس</div>
        <div class="v"><span class="num">${S.inside}</span></div>
        <div class="n">ریسک صفر، بدون جهت</div></div>
      <div class="tile dn"><div class="k">زیر باکس</div>
        <div class="v"><span class="num">${S.below}</span></div>
        <div class="n">قاعده می‌گوید نخر</div></div>
      <div class="tile"><div class="k">ریسک ≤ ۲٪ و بالا</div>
        <div class="v"><span class="num">${S.tight}</span></div>
        <div class="n">نزدیک‌ترین به حمایت</div></div>
    </div></section>`;

  /* ۲ — پرتفو */
  h+=`<section><div class="eyebrow">تخصیص</div><h2>پرتفوی پیشنهادی</h2>
    <p class="lede">استاپ کف باکس است، پس سایز هر پوزیشن از روی فاصلهٔ تا کف
      حساب می‌شود — نه وزن برابر. وزن برابر یعنی نمادی با استاپ دور، ریسک کل
      سبد را می‌بلعد. سهم هستهٔ ماهانه ${(cfg.sleeve*100).toFixed(0)}٪ سرمایه است،
      طبق بند ۲ فایل قوانین.</p>
    <div class="ctrl">
      <label>سرمایهٔ کل (ریال)
        <input id="cap" type="number" min="0" step="1000000" value="${cfg.capital}"></label>
      <label>تعداد پوزیشن
        <input id="top" type="number" min="1" max="40" step="1" value="${cfg.top_n}"></label>
      <label>ریسک کل سبد (٪ سرمایه)
        <input id="bud" type="number" min="0.1" step="0.25" value="${cfg.total_risk}"></label>
      <label>حداکثر ریسک پذیرفته (٪)
        <input id="mr" type="number" min="0.1" step="0.5" value="${cfg.max_risk}"></label>
    </div>
    <div class="tiles" id="pf-tiles"></div>
    <div id="pf-note"></div>
    <div style="height:14px"></div>
    <div class="panel scroll"><table>
      <thead><tr><th>نماد</th><th class="num">کلوز</th><th class="num">ریسک</th>
        <th class="num">وزن</th><th class="num">تعداد واحد</th>
        <th class="num">مبلغ</th><th class="num">ریسک ریالی</th>
        <th class="num">استاپ</th></tr></thead>
      <tbody id="pf-rows"></tbody><tfoot id="pf-foot"></tfoot></table></div></section>`;

  /* ۳ — گذار ماه */
  const t=S.transition;
  h+=`<section><div class="eyebrow">گذار</div><h2>ماه قبل تا امروز</h2>
    <p class="lede">هر دو ستون فقط نمادهای غیرثابت‌اند. ماه قبل
      ${t.prev_above} از ${t.prev_total} بالای باکس بودند
      (${p2(t.prev_above/t.prev_total*100)}) و امروز ${S.above} از ${S.live}
      (${p2(S.above/S.live*100)}). سیگنالی که ماه قبل روی تقریباً کل جهان نماد
      روشن بود، جهت بازار را می‌گفت نه انتخاب نماد — امروز واقعاً تفکیک
      می‌کند.</p>
    <div class="tiles">
      <div class="tile"><div class="k">ماندند بالا</div>
        <div class="v"><span class="num">${t.stay}</span></div>
        <div class="n">سبز بود، سبز ماند</div></div>
      <div class="tile mid"><div class="k">افتادند داخل</div>
        <div class="v"><span class="num">${t.to_inside}</span></div></div>
      <div class="tile dn"><div class="k">افتادند زیر</div>
        <div class="v"><span class="num">${t.to_below}</span></div>
        <div class="n">خروج طبق قاعده</div></div>
      <div class="tile"><div class="k">میانهٔ ریسک ماه قبل</div>
        <div class="v"><span class="num">${t.prev_median.toFixed(2)}٪</span></div>
        <div class="n">امروز ${S.median_risk.toFixed(2)}٪</div></div>
    </div></section>`;

  /* ۴ — توزیع ریسک */
  h+=`<section><div class="eyebrow">توزیع</div><h2>ریسک تا کف باکس</h2>
    <p class="lede">فقط نمادهای بالای باکس و غیرثابت. آستانهٔ
      <span class="num">RISK_RELAXED = 7</span> قاعدهٔ شماست — و امروز فقط
      <b>${S.over_thresh} نماد از ${S.above}</b> را کنار می‌گذارد. یعنی این
      فیلتر عملاً هیچ کاری نمی‌کند؛ باکس‌ها آن‌قدر باریک‌اند که تقریباً همه
      زیر آستانه‌اند.</p>
    <div class="panel"><figure>${riskHist(D.rows.filter(r=>r.st==='بالا'&&!r.fixed))}
      <figcaption>تعداد نماد در هر بازهٔ ریسک</figcaption></figure></div></section>`;

  /* ۵ — جدول کامل */
  h+=`<section><div class="eyebrow">همهٔ نمادها</div><h2>وضعیت کامل</h2>
    <p class="lede">مرتب‌شده: اول بالای باکس با کمترین ریسک.</p>
    <div class="panel scroll"><table><thead><tr>
      <th>نماد</th><th class="num">کلوز</th><th class="num">باکس</th>
      <th class="num">ریسک</th><th>وضعیت</th><th class="num">ماه قبل</th>
      <th>جای کلوز</th></tr></thead><tbody>`;
  const ordered=[...D.rows].sort((a,b)=>
    (a.st!=='بالا')-(b.st!=='بالا') || a.fixed-b.fixed || a.risk-b.risk);
  ordered.forEach(r=>{
    h+=`<tr><td>${esc(r.sym)}${r.fixed?' <span class="pill mid">ثابت</span>':''}</td>
      <td class="num">${money(r.close)}</td>
      <td class="num">${money(r.lo)} – ${money(r.hi)}</td>
      <td class="num">${r.risk.toFixed(2)}٪</td>
      <td><span class="pill ${cls(r.st)}">${r.st}</span></td>
      <td class="num">${r.prisk==null?'—':r.prisk.toFixed(2)+'٪'}</td>
      <td>${gauge(r.lo,r.hi,r.close)}</td></tr>`;
  });
  h+=`</tbody></table></div></section>`;

  /* ۶ — هشدارها */
  h+=`<section><div class="eyebrow">سلامت داده</div><h2>هشدارها</h2>`;
  if(D.dropped.length){
    h+=`<div class="verdict warn"><b>${D.dropped.length} ردیف حذف شد</b> —
      نماد تکراری یا برخورد نام. این‌ها در میانگین‌های بک‌تست دو بار وزن
      می‌گرفتند.</div><div class="panel scroll short"><table>
      <thead><tr><th>حذف‌شده</th><th>هم‌ارز با</th><th>دلیل</th></tr></thead><tbody>`;
    D.dropped.forEach(d=>{ h+=`<tr><td>${esc(d[0])}</td><td>${esc(d[1])}</td>
      <td style="color:var(--ink-2)">${esc(d[2])}</td></tr>`; });
    h+=`</tbody></table></div>`;
  } else h+=`<div class="verdict">نماد تکراری پیدا نشد.</div>`;
  h+=`<div class="verdict"><b>${S.fixed} صندوق درآمد ثابت</b> شناسایی و از
    پرتفو و شمارش‌ها کنار گذاشته شد. قیمتشان تقریباً یکنواخت بالا می‌رود، پس
    در هر تست «یک ماه نگه دار» نزدیک ۱۰۰٪ برد می‌دهند و میانگین را باد می‌کنند.</div>`;
  h+=`<div class="verdict warn"><b>این صفحه بک‌تست ندارد.</b> ورودی‌اش یک عکس
    لحظه‌ای از دو ماه است، نه سری زمانی. برای نرخ پایه، تست جایگشت و مزیت
    ماه‌به‌ماه، <span class="num">build_dashboard.py</span> را روی پوشهٔ
    <span class="num">data_auto</span> اجرا کنید.</div></section>`;

  document.getElementById('app').innerHTML=h;
  ['cap','bud','mr','top'].forEach(id=>
    document.getElementById(id).addEventListener('input',renderPortfolio));
  renderPortfolio();
})();
</script>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", default="decision.html")
    ap.add_argument("--capital", type=float, default=1_000_000_000)
    ap.add_argument("--sleeve", type=float, default=0.60,
                    help="سهم هستهٔ ماهانه از سرمایه (CLAUDE.md بند ۲)")
    ap.add_argument("--total-risk", type=float, default=3.0,
                    help="٪ سرمایه که کل سبد تا استاپ ریسک می‌کند")
    ap.add_argument("--top", type=int, default=12, help="تعداد پوزیشن")
    ap.add_argument("--max-risk", type=float, default=7.0)
    ap.add_argument("--max-weight", type=float, default=12.0)
    ap.add_argument("--artifact", action="store_true")
    args = ap.parse_args()

    text = Path(args.inp).read_text(encoding="utf-8")
    rows, bad = parse(text)
    if not rows:
        print("هیچ ردیفی شناسایی نشد — قالب ورودی را چک کنید.")
        return 1
    rows, dropped = dedupe(rows)

    live = [r for r in rows if not r["fixed"]]
    above = [r for r in live if r["st"] == "بالا"]
    prev = [r for r in live if r["pst"]]
    prev_above = [r for r in prev if r["pst"] == "بالا"]
    pm = sorted(r["prisk"] for r in prev_above if r["prisk"] is not None)
    cm = sorted(r["risk"] for r in above)

    stats = {
        "live": len(live), "fixed": len(rows) - len(live),
        "above": len(above),
        "inside": sum(1 for r in live if r["st"] == "داخل"),
        "below": sum(1 for r in live if r["st"] == "زیر"),
        "tight": sum(1 for r in above if r["risk"] <= 2),
        "over_thresh": sum(1 for r in above if r["risk"] > 7),
        "median_risk": cm[len(cm) // 2] if cm else 0.0,
        "transition": {
            "prev_total": len(prev), "prev_above": len(prev_above),
            "prev_median": pm[len(pm) // 2] if pm else 0.0,
            "stay": sum(1 for r in prev_above if r["st"] == "بالا"),
            "to_inside": sum(1 for r in prev_above if r["st"] == "داخل"),
            "to_below": sum(1 for r in prev_above if r["st"] == "زیر"),
        },
    }

    payload = {
        "rows": rows, "dropped": dropped, "stats": stats,
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "cfg": {"capital": args.capital, "sleeve": args.sleeve,
                "total_risk": args.total_risk, "max_risk": args.max_risk,
                "top_n": args.top, "max_weight": args.max_weight},
    }
    html = TEMPLATE.replace("__DATA__", json.dumps(payload, ensure_ascii=False))
    if not args.artifact:
        html = ('<!doctype html>\n<html lang="fa" dir="rtl">\n<head>\n'
                '<meta charset="utf-8">\n<meta name="viewport" '
                'content="width=device-width,initial-scale=1,viewport-fit=cover">\n'
                + html + '\n</head>\n<body>\n</body>\n</html>\n')
    Path(args.out).write_text(html, encoding="utf-8")

    pf, summ = build_portfolio(rows, args.capital, args.sleeve, args.max_risk,
                               args.total_risk, args.top, args.max_weight)
    print(f"ردیف: {len(rows)}  حذف‌شده: {len(dropped)}  ناخوانا: {len(bad)}")
    print(f"بالا: {stats['above']}  داخل: {stats['inside']}  زیر: {stats['below']}"
          f"  درآمد ثابت: {stats['fixed']}")
    print(f"پرتفو: {summ.get('held', 0)} پوزیشن از {summ['eligible']} واجد شرایط")
    if pf:
        print(f"  تخصیص {summ['spent']:,.0f} ریال · ریسک تا استاپ "
              f"{summ['risked']:,.0f} ({summ['risk_pct']:.2f}٪)")
    for a, b, why in dropped:
        print(f"  حذف: {a} ≡ {b}  ({why})")
    print(f"\nداشبورد: {Path(args.out).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
