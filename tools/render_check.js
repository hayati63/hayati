/*
 * اجرای واقعی اسکریپتِ یک صفحهٔ تولیدشده، با یک DOM حداقلی.
 *
 * این صفحه‌ها یک رشتهٔ چندهزارخطی جاوااسکریپت‌اند که از پایتون بیرون می‌آیند؛
 * یک بک‌تیکِ نبسته یا یک فیلدِ نبودهٔ JSON صفحه را سفید می‌کند بدون اینکه هیچ
 * ابزار پایتونی خبردار شود. این فایل واقعاً اسکریپت را اجرا می‌کند و سه چیز را
 * می‌سنجد: خطای زمان اجرا، پنل‌هایی که ساخته نشدند، و undefined/NaN در خروجی.
 *
 *   node tools/render_check.js صفحه.html [--want «متن» ...]
 *
 * ‎--want متنی است که باید در خروجی باشد؛ برای وقتی که می‌خواهید مطمئن شوید
 * یک پنل با دادهٔ واقعی پر شده، نه با پیام «فایل نیست».
 */
const fs = require('fs');

const args = process.argv.slice(2);
const file = args.find(a => !a.startsWith('--'));
const want = [];
for (let i = 0; i < args.length; i++) if (args[i] === '--want') want.push(args[++i]);
if (!file) { console.error('کاربرد: node tools/render_check.js صفحه.html [--want «متن»]'); process.exit(2); }

const html = fs.readFileSync(file, 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
if (!scripts.length) { console.error('✗ هیچ بلوک <script> پیدا نشد'); process.exit(1); }

function mkEl(tag) {
  const el = {
    tagName: (tag || 'div').toUpperCase(), children: [], dataset: {}, style: {},
    classList: { _s: new Set(), add(...c){c.forEach(x=>this._s.add(x))},
      remove(...c){c.forEach(x=>this._s.delete(x))}, contains(c){return this._s.has(c)},
      toggle(c){this._s.has(c)?this._s.delete(c):this._s.add(c)} },
    set className(v){ this._cn = v; }, get className(){ return this._cn || ''; },
    set innerHTML(v){ this._html = v; }, get innerHTML(){ return this._html || ''; },
    textContent: '', value: '', type: '', checked: false,
    appendChild(c){ this.children.push(c); return c; },
    addEventListener(){}, removeEventListener(){},
    setAttribute(){}, getAttribute(){ return null; },
    querySelector(){ return null; }, querySelectorAll(){ return []; },
    closest(){ return null; },
    getBoundingClientRect(){ return { top:0, left:0, width:100, height:20 }; },
    focus(){}, click(){}, remove(){},
  };
  return el;
}
const byId = {};
global.document = {
  createElement: mkEl,
  getElementById(id){ return byId[id] || (byId[id] = mkEl('div')); },
  querySelector(){ return null; }, querySelectorAll(){ return []; },
  addEventListener(){}, body: mkEl('body'), documentElement: mkEl('html'),
};
global.window = { addEventListener(){}, matchMedia: () => ({ matches:false, addEventListener(){} }) };
global.localStorage = { getItem(){ return null; }, setItem(){}, removeItem(){} };
global.requestAnimationFrame = f => f();
global.navigator = { language: 'fa-IR' };

let ok = true;
for (const [i, src] of scripts.entries()) {
  try { new Function(src)(); }
  catch (e) {
    ok = false;
    console.error(`✗ اسکریپت ${i + 1} خطای زمان اجرا داد: ${e.message}`);
    console.error(e.stack.split('\n').slice(1, 4).join('\n'));
  }
}
if (!ok) process.exit(1);

// هر ظرفی که چیزی داخلش ساخته شده — نام id در صفحه‌های مختلف فرق می‌کند
const built = Object.entries(byId).filter(([, el]) => el.children.length || el.innerHTML);
if (!built.length) { console.error('✗ اسکریپت اجرا شد ولی هیچ چیزی در DOM ننوشت'); process.exit(1); }

let panes = 0, chars = 0;
const dump = [];
for (const [id, el] of built) {
  const kids = el.children.length
    ? el.children
    : [{ id, innerHTML: el.innerHTML }];
  for (const c of kids) {
    // متن دکمه‌ها با textContent ست می‌شود نه innerHTML — اگر فقط
    // innerHTML خوانده شود، دکمه‌های ساخته‌شده با createElement نامرئی‌اند.
    const h = c.innerHTML || c.textContent || '';
    if (!h) continue;
    panes++; chars += h.length;
    dump.push(h);
    if (/\bundefined\b|\bNaN\b/.test(h)) {
      ok = false;
      const m = h.match(/.{0,60}(undefined|NaN).{0,60}/);
      console.error(`✗ ${c.id || id}: undefined/NaN در خروجی`);
      if (m) console.error('   …' + m[0].replace(/\s+/g, ' ') + '…');
    }
  }
}
const all = dump.join('');
console.log(`بخش رندرشده: ${panes}  ·  ${chars.toLocaleString('en')} کاراکتر`);
const ids = built.flatMap(([id, el]) => el.children.map(c => c.id).filter(Boolean));
if (ids.length) console.log('  ' + ids.join(' '));

for (const w of want) {
  const hit = all.includes(w);
  console.log(`  ${hit ? '✓' : '✗'} «${w}»`);
  if (!hit) ok = false;
}

console.log(ok ? '\n✓ صفحه بدون خطا رندر شد' : '\n✗ مشکل هست');
process.exit(ok ? 0 : 1);
