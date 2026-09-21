@echo off
chcp 65001 >nul
REM ── به‌روزرسانی روزانه ─────────────────────────────────────────────
REM این را روی ماشین خودت اجرا کن، نه در کانتینر ابری. شبکهٔ کانتینر به
REM cdn.tsetmc.com جواب ۴۰۳ می‌دهد؛ از ویندوز تو کار می‌کند.
REM
REM یک‌بار، برای ساختن فهرست کامل نماد→insCode:
REM     python tools\fetch_tsetmc.py --discover
REM
REM زمان‌بندی خودکار (هر روز ساعت ۱۸:۳۰، بعد از کلوز طلا و نقره):
REM     schtasks /create /tn "hayati-daily" /tr "%~f0" /sc daily /st 18:30
REM حذفش:
REM     schtasks /delete /tn "hayati-daily" /f

cd /d "%~dp0"
echo.
echo === ۱. دانلود از TSETMC ===
python tools\fetch_tsetmc.py
if errorlevel 1 goto :fail

echo.
echo === ۲. نقدشوندگی ===
python tools\liquidity.py --data data_auto --holdings data\holdings.txt --out data\liquidity.json
if errorlevel 1 goto :fail

echo.
echo === ۳. پرتفوی هدف ===
python tools\target_portfolio.py --data data_auto --holdings data\holdings.txt --liquidity data\liquidity.json --json data\target_portfolio.json
if errorlevel 1 goto :fail

echo.
echo === ۴. داشبورد پرتفو ===
REM dashboard_monthly.py مال خودت است و اینجا نیست؛ اگر کنار این فایل
REM باشد اجرا می‌شود، وگرنه این مرحله رد می‌شود.
if exist dashboard_monthly.py (
  python dashboard_monthly.py
  if exist dashboard_monthly.html (
    python tools\portfolio_dashboard.py --in dashboard_monthly.html --out portfolio.html
  )
) else (
  echo   dashboard_monthly.py نبود — رد شد.
)

echo.
echo === ۵. ثبت و ارسال ===
git add data_auto data\liquidity.json data\target_portfolio.json
git diff --cached --quiet && (echo هیچ داده‌ای عوض نشد. & goto :done)
for /f "tokens=*" %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set TODAY=%%d
git commit -q -m "داده‌های روزانه %TODAY%"
git push -q origin HEAD
if errorlevel 1 (echo ⚠️ push نشد — شبکه یا دسترسی. داده ثبت شد، بعداً push کن.)

:done
echo.
echo تمام. بک‌تست کامل را با این بگیر:
echo     python tools\monthly_backtest.py --data data_auto --iters 20000 --json data\evidence_month.json
exit /b 0

:fail
echo.
echo ✗ یکی از مرحله‌ها شکست خورد. خروجی بالا را نگاه کن.
exit /b 1
