@echo off
REM ---------------------------------------------------------------
REM  به‌روزرسانی داشبورد ماهانه — یک بار کلیک، دو مرحله
REM  این فایل را کنار dashboard_monthly.py بگذارید و اجرا کنید.
REM ---------------------------------------------------------------
chcp 65001 >nul
echo.
echo [1/2] گرفتن دیتای تازه و ساخت dashboard_monthly.html ...
python dashboard_monthly.py
if errorlevel 1 goto fail

echo.
echo [2/2] ساخت داشبورد پرتفوی ...
python tools\portfolio_dashboard.py --in dashboard_monthly.html --out portfolio.html --capital %1
if errorlevel 1 goto fail

echo.
echo تمام. portfolio.html ساخته شد.
start portfolio.html
goto end

:fail
echo.
echo خطا خورد. پیام بالا را بفرستید.
pause

:end
