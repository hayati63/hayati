@echo off
chcp 65001 >nul
REM ═══════════════════════════════════════════════════════════════════
REM  به‌روزرسانی — دو بار در روز
REM
REM  این را روی ماشین خودت اجرا کن، نه در کانتینر ابری. شبکهٔ کانتینر به
REM  cdn.tsetmc.com جواب ۴۰۳ می‌دهد؛ از ویندوز تو کار می‌کند.
REM
REM  ── نصب زمان‌بندی، یک‌بار ────────────────────────────────────────
REM    schtasks /create /tn "hayati-bourse" /tr "%~f0 bourse" /sc daily /st 12:45
REM    schtasks /create /tn "hayati-tala"   /tr "%~f0 tala"   /sc daily /st 18:15
REM
REM  ۱۲:۴۵ — یک ربع بعد از بستن بورس، تا قیمت پایانی جا افتاده باشد.
REM  ۱۸:۱۵ — یک ربع بعد از بستن طلا.
REM
REM  حذفشان:  schtasks /delete /tn "hayati-bourse" /f
REM           schtasks /delete /tn "hayati-tala" /f
REM ═══════════════════════════════════════════════════════════════════

cd /d "%~dp0"
set MODE=%1
if "%MODE%"=="" set MODE=full

echo.
echo ═══ %DATE% %TIME%  ·  حالت: %MODE% ═══

REM ── ۱. صندوق‌های بورسی — فقط در حالت bourse یا full ────────────────
if not "%MODE%"=="tala" (
  echo.
  echo [۱/۴] دانلود صندوق‌ها از TSETMC
  python tools\fetch_tsetmc.py
  if errorlevel 1 goto :fail
)

REM ── ۲. محرک‌ها — چارتیکس export نمی‌دهد، پس این مرحله دستی است ─────
REM  اگر اکسپورت تازهٔ چارتیکس را در data\chartix_in\ ریختی، تبدیل می‌شود.
if exist data\chartix_in\*.csv (
  echo.
  echo [۲/۴] تبدیل اکسپورت چارتیکس به کندل روزانه
  python tools\chartix_import.py --in data\chartix_in --tf 1D --out data\drivers_daily
) else (
  echo.
  echo [۲/۴] پوشهٔ data\chartix_in خالی است — محرک‌ها به‌روز نشدند.
)

REM ── ۳. محاسبه‌ها ──────────────────────────────────────────────────
echo.
echo [۳/۴] نقدشوندگی و پرتفوی هدف
python tools\liquidity.py --data data_auto --holdings data\holdings.txt --out data\liquidity.json
if errorlevel 1 goto :fail
python tools\target_portfolio.py --data data_auto --holdings data\holdings.txt --liquidity data\liquidity.json --json data\target_portfolio.json
if errorlevel 1 goto :fail

if exist dashboard_monthly.py (
  python dashboard_monthly.py
  if exist dashboard_monthly.html (
    python tools\portfolio_dashboard.py --in dashboard_monthly.html --out portfolio.html
  )
)

REM ── ۴. ثبت و ارسال ────────────────────────────────────────────────
echo.
echo [۴/۴] ثبت و ارسال
git add data_auto data\drivers_daily data\liquidity.json data\target_portfolio.json
git diff --cached --quiet && (echo   هیچ داده‌ای عوض نشد. & goto :done)
for /f "tokens=*" %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH:mm"') do set STAMP=%%d
git commit -q -m "داده %MODE% %STAMP%"
git push -q origin HEAD
if errorlevel 1 echo   ⚠️ push نشد. داده ثبت شد، بعداً push کن.

:done
echo.
echo تمام.
exit /b 0

:fail
echo.
echo ✗ شکست خورد. خروجی بالا را نگاه کن.
exit /b 1
