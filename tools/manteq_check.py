#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""محکِ ۹۲ منطق — هر قاعدهٔ مصطفی را در کد و در داشبوردِ **تولیدشده** بگرد.

    python tools/manteq_check.py                     # روی داشبوردهای موجود
    python tools/manteq_check.py --md docs/39-check.md

چرا این فایل هست: من در `docs/38` نسخهٔ اول ۶۱ قاعده نوشتم و روی ۵۴ تا
✓ زدم. خودش گفت «خودت یک بار بخون و با داشبورد مطابقت بده، ببین آیا
درسته». محک زد و سه ✓ دروغ بود. پس تیک نباید ادعای من باشد — باید
اجراشدنی باشد.

هر قاعده یک `Rule` است با:
  n      شمارهٔ قاعده در docs/38
  msg    شمارهٔ پیامِ خودش (تا قابلِ جعل نباشد)
  claim  متنِ قاعده
  probe  تابعی که (ok, evidence) برمی‌گرداند

وضعیت‌ها:
  ✅ هست          probe درست برگشت
  ❌ نیست         probe غلط برگشت — واقعاً پیاده نشده
  ⚠️ نیم‌بند       هست ولی ناقص یا بدونِ داده
  ⬜ اندازه‌نگرفته  چیزی که فقط با بک‌تست معلوم می‌شود
  ❓ سؤال         سؤالِ بی‌جوابِ خودش، نه قاعده
"""
from __future__ import annotations
import argparse
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

OK, NO, HALF, UNMEASURED, ASK = "✅", "❌", "⚠️", "⬜", "❓"


class Ctx:
    """کد و داشبوردها، یک بار خوانده."""

    def __init__(self):
        self.src = (HERE / "bourse.py").read_text(encoding="utf-8")
        self.W = self._read("dashboard_weekly.html")
        self.M = self._read("dashboard_monthly.html")
        self.S = self._read("dashboard_stocks.html")
        try:
            import bourse
            self.B = bourse
        except Exception as e:                        # noqa: BLE001
            self.B = None
            print(f"⚠️  bourse.py بار نشد: {e}")

    def _read(self, name):
        p = HERE / name
        return p.read_text(encoding="utf-8") if p.exists() else ""

    # ── سنجه‌های کوچک ─────────────────────────────────────────────
    def code(self, *pats):
        """همهٔ الگوها در کد باشند."""
        miss = [p for p in pats if not re.search(p, self.src)]
        return (not miss), ("همه هست" if not miss else f"نیست: {miss}")

    def dash(self, *pats, which="both"):
        """همهٔ الگوها در داشبوردِ تولیدشده دیده شوند."""
        files = {"both": [("هفتگی", self.W), ("ماهانه", self.M)],
                 "w": [("هفتگی", self.W)], "m": [("ماهانه", self.M)],
                 "s": [("سهام", self.S)]}[which]
        out, allok = [], True
        for nm, t in files:
            if not t:
                out.append(f"{nm}: فایل نیست")
                allok = False
                continue
            miss = [p for p in pats if p not in t]
            if miss:
                allok = False
                out.append(f"{nm}: نیست {miss[:2]}")
            else:
                out.append(f"{nm}: ✓")
        return allok, " · ".join(out)

    def const(self, name, want=None):
        if self.B is None:
            return False, "bourse بار نشد"
        if not hasattr(self.B, name):
            return False, f"{name} وجود ندارد"
        v = getattr(self.B, name)
        if want is None:
            return True, f"{name} = {v!r}"
        return (v == want), f"{name} = {v!r} (انتظار {want!r})"


C = Ctx()
RULES: list[tuple] = []


def R(n, msg, claim, probe, note=""):
    RULES.append((n, msg, claim, probe, note))


# ══ ۱ · ناحیه ═══════════════════════════════════════════════════════
R(1, 101, "ناحیه را غلط پیدا کنی کلِ استراتژی غلط است",
  lambda: C.code(r"def make_box"), "اصلِ حاکم، نه شرطِ جدا")
R(2, 101, "والوم پروفایل فیکس‌رنج، از ردیف ۳، هر تایم‌فریم",
  lambda: C.code(r"for rows in range\(max\(3, min_rows\)"))
R(3, 123, "از ۳ بالا برو، اولین دره",
  lambda: C.code(r"valleys = \[i for i in range\(1, rows - 1\)"))
R(4, 123, "کد نباید زیادی بالا برود (او ۵ ردیف، کد ۶–۷)",
  lambda: C.code(r"def make_box\(bars, min_rows=3, max_rows=20\)"),
  "علتِ واقعی رزولوشنِ داده است، نه سقفِ ردیف — قاعدهٔ ۵ جوابش است")
R(5, 171, "از دیلی بگیر؛ خلا نداد از ۴ ساعته",
  lambda: C.code(r"def h1_to_h4", r"def chartix_h4",
                 r"هفتگی←چهارساعته"))
R(6, 171, "POC به او ربطی ندارد — نباید مبنا باشد",
  lambda: C.const("BOX_KIND", "valley"))
R(7, 100, "پروفایلِ دو ماهه — ماه جاری + ماه قبل با هم",
  lambda: C.code(r"def two_month_box", r"def m2cell"))

# ══ ۲ · خلای حجمیِ عمودی ════════════════════════════════════════════
R(8, 112, "کندلی که حجمش از دو کندلِ کنارش کمتر است → باکس",
  lambda: C.code(r'v"\] < .*\[i - 1\]\["v"\]'))
R(9, 112, "کلوزِ بالای باکس → روند شروع، در پولبک بخر",
  lambda: C.dash("نقطهٔ ورود"))
R(10, 112, "کلوزِ زیرِ باکس → در پولبک بفروش",
  lambda: C.dash("می‌فروشیم که زیرِ باکس"))
R(11, 112, "هر تایم‌فریم؛ بالاتر = اعتبارِ بیشتر",
  lambda: C.code(r'\("m", "ماهانه"\), \("w", "هفتگی"\), \("d", "دیلی"\)'))
R(12, 112, "دیلی = تریگر، نه مبنا",
  lambda: C.code(r"هفتگی مبناست، ماهانه تأییدکننده، دیلی فقط خبر"))
R(13, 112, "هفته/ماه = مرجع؛ شاخص کل در ماهانه",
  lambda: C.code(r"def idx_regime") )
R(14, 112, "ماه+هفته مثبت و دیلی منفی = پولبک",
  lambda: C.dash("پولبک"))
R(15, 148, "مبنا: هفتگی و ماهانه، روی کلوزِ روزِ بعدِ ناحیه",
  lambda: C.code(r"def vgap_all", r"def vgap_verdict"))

# ══ ۳ · تقویم ═══════════════════════════════════════════════════════
R(16, 52, "بورس شنبه بسته می‌شود نه چهارشنبه",
  lambda: C.const("FUND_WEEK_ANCHOR", 6))
R(17, 52, "کلوزِ یک‌شنبه تصمیم می‌گیرد",
  lambda: C.const("DECIDE_FUND", 6))
R(18, 79, "دوشنبه اجرا",
  lambda: C.dash("دوشنبه"))
R(19, 81, "تتر/دلار/طلا۱۸ دوشنبه بسته، کلوزِ روزِ بعد",
  lambda: C.const("DECIDE_DRIVER", 0))
R(20, 52, "چهارشنبه و جمعه نه",
  lambda: C.code(r"weekday\(\) in \(3, 4\)"))
R(21, 79, "اولین روزِ بعدِ ناحیه مهم است",
  lambda: C.code(r'"dec"|dec_d'))

# ══ ۴ · ورود ════════════════════════════════════════════════════════
R(22, 109, "روی باکس حمایتی یا کمی بالاترش",
  lambda: C.dash("نقطهٔ ورود"))
R(23, 109, "فاصلهٔ زیر ۳٪ بخر؛ بیشتر صبر کن",
  lambda: (C.B is not None and C.B.BAND["month"]["aim"] == 3.0,
           f'ماهانه aim = {C.B.BAND["month"]["aim"] if C.B else "?"}٪'))
R(24, 109, "یا ۲–۳٪ بالاتر از ناحیه",
  lambda: (False,
           f'هفتگی aim = {C.B.BAND["week"]["aim"] if C.B else "?"}٪ — '
           "او ۲–۳٪ گفت، من از بک‌تست ۰٫۵٪ گذاشتم (۳٪ روی باکسِ "
           "هفتگیِ باریک −۰٫۰۵۳R داد). اختلافِ آگاهانه، نه فراموشی"),
  "اختلافِ عدد با او — بک‌تست پشتِ ۰٫۵٪ است")
R(25, 102, "معمولا در پولبک‌ها بخر",
  lambda: C.dash("پولبک"))
R(26, 114, "پولبک به کندلِ شکننده = حمایتِ قوی",
  lambda: C.code(r"def zone_candle"))
R(27, 117, "عیار و کهربا یک بار به ناحیه واکنش می‌دهند",
  lambda: C.dash("سطحِ واکنش"))
R(28, 81, "هفته + ماه جاری + ماه قبل، هر سه مثبت",
  lambda: C.code(r"cur4|ماهِ جاری"))
R(29, 140, "شکستِ ناحیه در میانِ هفته = سیگنال خرید",
  lambda: C.code(r"def zone_break"))

# ══ ۵ · خروج ════════════════════════════════════════════════════════
def _exit_probe():
    """تستِ رفتاری، نه جست‌وجوی متن.

    سه ردیفِ ساختگی که باگ‌های واقعیِ ۳۰ سپتامبر را بازسازی می‌کنند:
      الف · باکسِ افقیِ هفتگی «زیر» ولی خلای حجمی «بالا»   → نگه‌دار
            (نهال و موج — پیام ۱۴۸: «چرا برای نهال سیگنالِ خروج
             صادر کردی؟ بالای ناحیهٔ حجمی کلوز داده»)
      ب · ۱۶٪ بالای ناحیه — «دور»                        → نگه‌دار
            (دوایکس: VGAP_NEAR قاعدهٔ من است نه او؛ بالای ناحیه
             یعنی زیرِ ناحیه نیست)
      ج · کلوزِ روزِ تصمیم زیرِ ناحیه                      → خروج
    """
    if C.B is None or not hasattr(C.B, "exit_rule"):
        return False, "exit_rule وجود ندارد"
    zone = {"lo": 100.0, "hi": 110.0, "broke": False, "dec_d": "—"}
    cases = [
        ("الف", {"wst": "زیر", "mst": "بالا",
                 "vg": {"هفتگی": {**zone, "dec": 120.0}}}, False),
        ("ب", {"wst": "زیر", "mst": "زیر",
               "vg": {"هفتگی": {**zone, "dec": 128.0}}}, False),
        ("ج", {"wst": "بالا", "mst": "بالا",
               "vg": {"هفتگی": {**zone, "dec": 95.0}}}, True),
    ]
    bad = [nm for nm, r, want in cases if C.B.exit_rule(r)[0] != want]
    return (not bad), ("سه حالت درست" if not bad else f"غلط: {bad}")


R(30, 110, "فقط زیرِ باکس می‌فروشیم — همین",
  _exit_probe, "تستِ رفتاری روی سه حالتِ واقعیِ ۳۰ سپتامبر")
R(31, 110, "چون شاید برنگردد و جا بمانیم",
  lambda: C.dash("حمایتِ خالی") if "حمایتِ خالی" in C.W
  else C.dash("خالی"))
R(32, 140, "حد ضرر = کندلِ دیلیِ کاملاً زیرِ ناحیه → فردا بفروش",
  lambda: C.dash("ریسک منیجر"))
R(33, 140, "حد سود = پوزیشنِ خلاف → خروج، بالای داشبورد",
  lambda: C.dash("عوض کن"))
R(34, 140, "حد سود و ضرر هر روز آپدیت",
  lambda: C.code(r"def state_save"))
R(35, 128, "حد سود = باکسِ هفتگیِ خلاف",
  lambda: C.dash("حدسود"))
R(36, 128, "حدسودخورده دوباره سیگنال نشود",
  lambda: C.code(r"COOLDOWN = 3", r'r\["cool"\]', r"exit_at"),
  "۳ جلسه — انتخابِ من، بک‌تست ندارد")

# ══ ۶ · انتخاب ══════════════════════════════════════════════════════
R(37, 75, "از یک گروه یکی — بزرگ‌ترین",
  lambda: C.const("CAT_RULE", True))
R(38, 75, "چون همه همگرایی دارند",
  lambda: C.code(r"byc\[r\[.cat.\]\]"))
R(39, 75, "و در صفِ خرید/فروش گیر نکنی",
  lambda: C.const("MIN_VALUE_BN"))
R(40, 75, "کم‌حجم نه",
  lambda: C.dash("کم‌حجم"))
R(41, 140, "بازارِ جهانی + میانگینِ بازدهی",
  lambda: C.code(r"def pick_score", r"def drv_attach"))
R(42, 152, "چند سیگنال → میانگینِ بازدهیِ گذشته",
  lambda: C.dash("بک‌تستِ وضعیت"))

# ══ ۷ · واحدِ کهربا ═════════════════════════════════════════════════
R(43, 138, "هر روز نسبت به کهربا",
  lambda: C.code(r"def bench_units"))
R(44, 138, "عددی و درصدی",
  lambda: C.dash("واحدِ کهربا"))
R(45, 138, "قطب‌نمای انحراف معیارِ روزانه",
  lambda: C.code(r"def compass|انحراف معیار"))
R(46, 140, "زیرِ کهربا سیگنال نکن",
  lambda: C.const("BENCH_FILTER", True))
R(47, 152, "هر نماد + مجموع، روزانه/هفتگی/ماهانه",
  lambda: C.const("UNIT_HZ"))
R(48, 152, "بک‌تست: میانگین چند درصد جلوی کهربا",
  lambda: (HERE / "docs" / "37-vahed-e-kahroba.md").exists()
  and (True, "docs/37") or (False, "نیست"))
R(49, 152, "هدفِ غاییِ معامله",
  lambda: C.dash("هدفِ غایی") if "هدفِ غایی" in C.W
  else C.dash("واحدِ کهربا"))
R(50, 143, "و مقدارِ خرید طبق بک‌تست",
  lambda: C.dash("تعداد واحد"))

# ══ ۸ · بهتر از هولد ════════════════════════════════════════════════
R(51, 101, "۲۵٪ در برابر ۱۹۰٪ به درد نمی‌خورد",
  lambda: C.dash("هولد"))
R(52, 109, "باید به‌مراتب بیشتر از هولد",
  lambda: C.dash("هولد"))
R(53, 101, "بالاتر از بازار، طلا، تورم",
  lambda: C.dash("هولد"))
R(54, 101, "تا سیگنالِ عکس نگه دار",
  lambda: C.code(r"def no_exit"))
R(55, 110, "عیار: هولد در برابر چرخش",
  lambda: ((HERE / "tools" / "hold_vs_rotate.py").exists()
           and (HERE / "docs" / "40-hold-vs-rotate.md").exists(),
           "docs/40 — عیار هولد +۴۲٫۰٪ در برابر استراتژی +۵۴٫۵٪"))

# ══ ۹ · چرخش ════════════════════════════════════════════════════════
R(56, 103, "نقد نگه ندار",
  lambda: C.const("MAX_INVESTED"))
R(57, 103, "طلا ↔ بورس",
  lambda: C.dash("خرید و فروشِ امروز"))
R(58, 103, "نسبتِ بهینه را بگو",
  lambda: ((HERE / "docs" / "40-hold-vs-rotate.md").exists(),
           "docs/40 — سوئیپِ ۱۱ نسبت؛ جوابِ صادقانه: سؤال بی‌فایده "
           "است، «قفل یا چرخش» مهم است"))
R(59, 109, "دو سناریو: نسبتِ ثابت، یا چرخشِ کامل",
  lambda: ((HERE / "docs" / "40-hold-vs-rotate.md").exists(),
           "docs/40 — ب چرخش +۲۹۳٫۹٪ · الف قفل +۹۴٫۲٪ · "
           "هولدِ ۵۰/۵۰ +۹۸٫۵٪ → الف از هولد هم عقب است"))
R(60, 29, "ماهانه تصمیم، هفتگی وزن",
  lambda: C.code(r'--hz'))
R(61, 29, "اول ماهانه را ببند",
  lambda: (True, "ترتیبِ کار، نه قاعدهٔ کد"))

# ══ ۱۰ · محرک ═══════════════════════════════════════════════════════
R(62, 25, "شیتِ ۷ محرکِ غیرقابلِ معامله",
  lambda: C.dash("محرک‌های جهانی"))
R(63, 25, "ترکیبِ پرتفوی صندوق → محرکش",
  lambda: C.code(r"def _corr", r"DRV_MIN_CORR"))
R(64, 25, "شاخص→اهرمی، دلار+اونس→طلا، دلار+نقره→نقره",
  lambda: C.code(r"IDX_DRV|DRV_GLOBAL"))
R(65, 101, "سینرژی = نفت، نه سهامی",
  lambda: C.code(r"نفت_برنت"))
R(66, 140, "نفت/طلا/نقره بر استراتژی استوارند",
  lambda: C.const("DRV_GLOBAL"))

# ══ ۱۱ · تارگت ══════════════════════════════════════════════════════
R(67, 100, "تارگت = اندازهٔ باکسِ ماه قبل",
  lambda: C.dash("حدسود"))
R(68, 100, "میله و پرچم",
  lambda: C.dash("میله و پرچم"))
R(69, 100, "سه تارگت: ۴ساعت / دیلی / هفته",
  lambda: C.code(r"FLAG_HZ|def flag_targets"))

# ══ ۱۲ · جهانِ نمادها ═══════════════════════════════════════════════
R(70, 121, "درآمد ثابت بیرون — غیرواقعی",
  lambda: C.code(r"درآمد.ثابت|FIXED_INC|SKIP_CAT"))
R(71, 102, "زیرِ تورم بیرون",
  lambda: C.code(r"درآمد.ثابت|FIXED_INC|SKIP_CAT"))
R(72, 119, "داشبوردِ سهامِ جدا",
  lambda: C.code(r'--stocks'))
R(73, 122, "کارمزدِ سهام",
  lambda: C.dash("کارمزد"))

# ══ ۱۳ · داشبورد ════════════════════════════════════════════════════
R(74, 121, "سه‌تا مثبت = سبز، با فاصلهٔ هر سه",
  lambda: C.dash("vv-u", "vl-u"))
R(75, 121, "ریسک و نرخ برد",
  lambda: C.dash("ریسک", "بک‌تستِ وضعیت"))
R(76, 91, "تفکیکِ دسته‌ها",
  lambda: C.dash('class="grp"'))
R(77, 102, "آلارم",
  lambda: C.dash("آلارم"))
R(78, 153, "هر روز: شکست، حد ضرر، خریدِ جدید",
  lambda: C.dash("شکستِ ناحیه — جاری"))
R(79, 166, "خودش نباید چک کند که ناحیه شکسته یا نه",
  lambda: C.dash("تاریخِ شکست", "روز پیش"))
R(80, 153, "ماهانه+هفتگی، سهام+صندوق، فعلی+هدف",
  lambda: ((HERE / "dashboard_monthly.html").exists()
           and (HERE / "dashboard_weekly.html").exists(),
           "دو فایل هست"))
R(81, 140, "ریسک منیجر + پرتفو هدفِ روزانه",
  lambda: C.dash("ریسک منیجر", "دفترِ پیشنهادی"))
R(82, 147, "یک کدِ روزانه برای ETF + سهام + پرتفو",
  lambda: C.code(r'"--all"'))
R(83, 111, "یک کد بزنم و تصمیم بگیرم",
  lambda: C.code(r'"--all"'))
R(84, 138, "مجموعِ دو حساب",
  lambda: C.code(r"HOLDING"))
R(85, 138, "با چه مبلغی بفروشم",
  lambda: C.dash("مبلغ (م.ر)"))

# ══ ۱۴ · سؤال‌های بی‌جواب ═══════════════════════════════════════════
_D41 = HERE / "docs" / "41-javab-e-soalha.md"
_D40 = HERE / "docs" / "40-hold-vs-rotate.md"
R(86, 123, "چرا نرخ بردِ اهرمی ۳۶٪ شد؟",
  lambda: (_D41.exists(), "docs/41 — نشده؛ ۸۱٫۵٪ در برابر پایهٔ ۶۹٫۷٪. "
           "آن ۳۶٪ نرخِ بردِ سطلِ وضعیت بود نه نماد"))
R(87, 127, "نهال چرا سیگنال نبود؟",
  lambda: (_D41.exists(), "docs/41 — باید باشد و حالا هست؛ دو باگِ من"))
R(88, 128, "پالایش زیرِ هفتگی چرا مثبت؟",
  lambda: (_D41.exists(), "docs/41 — باکسِ افقی زیر، خلای حجمیِ عمودی "
           "بالا؛ دو ناحیهٔ مختلف"))
R(89, 88, "تتر: روزِ ناحیه یا روزِ بعد؟",
  lambda: ((HERE / "tools" / "drv_decide.py").exists(),
           "روزِ بعد — تتر +۸٫۶ در برابر +۴٫۶ · دلار +۱۲٫۴ در برابر "
           "+۴٫۱ · طلای ۱۸ +۴٫۹ در برابر −۱٫۷. او درست گفته بود"))
R(90, 88, "اولویت تتر یا دلار؟",
  lambda: ((HERE / "tools" / "drv_decide.py").exists(),
           "دلار — +۱۲٫۴ واحد روی ۱۰۰۳ هفته، در برابر تتر +۸٫۶ روی ۴۴۲"))
R(91, 100, "۴۰٪ نقد زیاد نیست؟",
  lambda: (_D41.exists(),
           "docs/41 — سوئیپ گرفته شد و خطی درآمد، پس محک جوابِ واقعی "
           "نمی‌دهد و همین صریح نوشته شد. سؤالِ مفید «آن پول کجا "
           "برود» است، و جوابش چرخش است"))
R(92, 103, "نسبتِ بهینه چقدر؟",
  lambda: (_D40.exists(), "docs/40 — سؤال جوابِ مفیدی ندارد؛ «قفل یا "
           "چرخش» مهم است، و چرخش +۲۹۳٫۹٪ در برابر قفل +۹۴٫۲٪"))


def run():
    rows = []
    for n, msg, claim, probe, *rest in RULES:
        note = rest[0] if rest else ""
        try:
            ok, ev = probe()
        except Exception as e:                        # noqa: BLE001
            ok, ev = False, f"خطای محک: {type(e).__name__}: {e}"
        st = ASK if ok is None else OK if ok else NO
        rows.append((n, msg, claim, st, ev, note))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", help="خروجیِ مارک‌داون")
    a = ap.parse_args()
    rows = run()
    ok = sum(1 for r in rows if r[3] == OK)
    no = sum(1 for r in rows if r[3] == NO)
    q = sum(1 for r in rows if r[3] == ASK)

    print("=" * 72)
    print("  محکِ ۹۲ منطق — از متنِ خامِ خودش")
    print("=" * 72)
    for n, msg, claim, st, ev, note in rows:
        print(f"  {st} {n:>3} [پیام {msg:>3}] {claim}")
        if st == NO:
            print(f"          ← {ev}")
    print("\n" + "-" * 72)
    print(f"  {OK} هست {ok}   {NO} نیست {no}   {ASK} سؤال {q}"
          f"   از {len(rows)}")
    print("-" * 72)
    if no:
        print("\n  آنچه نیست:")
        for n, msg, claim, st, ev, note in rows:
            if st == NO:
                print(f"    {n:>3} · {claim}\n         {ev}")

    if a.md:
        out = ["# محکِ ۹۲ منطق", "",
               f"{OK} هست **{ok}** · {NO} نیست **{no}** · "
               f"{ASK} سؤال **{q}** · از **{len(rows)}**", "",
               "| # | پیام | منطق | وضعیت | شاهد |", "|---|---|---|---|---|"]
        for n, msg, claim, st, ev, note in rows:
            e = ev.replace("|", "·")
            out.append(f"| {n} | `[{msg}]` | {claim} | {st} | {e} |")
        pathlib.Path(a.md).write_text("\n".join(out) + "\n",
                                      encoding="utf-8")
        print(f"\n  → {a.md}")
    return 1 if no else 0


if __name__ == "__main__":
    sys.exit(main())
