@echo off
chcp 65001 >nul
REM ═══════════════════════════════════════════════════════════════════
REM  نصب دو زمان‌بندی روزانه — نسخهٔ bat
REM
REM  چرا این کنار setup_tasks.ps1 هست: ویندوز اجرای اسکریپت PowerShell
REM  را به‌صورت پیش‌فرض می‌بندد (ExecutionPolicy) و خطای
REM  «running scripts is disabled on this system» می‌دهد. فایل bat
REM  اصلاً مشمول آن قانون نیست، پس همیشه اجرا می‌شود.
REM
REM  اجرا: دابل‌کلیک روی همین فایل. تمام.
REM ═══════════════════════════════════════════════════════════════════

cd /d "%~dp0"
set BAT=%~dp0refresh.bat

echo.
echo -- بررسی --

if not exist "%BAT%" (
  echo    x refresh.bat کنار این فایل نیست.
  echo      این فایل باید داخل پوشهٔ مخزن باشد. الان اینجاست:
  echo      %~dp0
  goto :hold
)
echo    + refresh.bat پیدا شد
echo      %BAT%

python --version >nul 2>&1
if errorlevel 1 (
  echo    x python در PATH نیست. تسک‌ها ساخته می‌شوند ولی کار نمی‌کنند.
  echo      اول پایتون را نصب کن و گزینهٔ «Add to PATH» را بزن.
  goto :hold
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo    + %%v

echo.
echo -- نصب --

REM نقل‌قولِ تودرتو: خودِ schtasks رشتهٔ /tr را دوباره پارس می‌کند، پس
REM مسیرِ فاصله‌دار باید با \" داخل نقل‌قول بیرونی بسته شود.
schtasks /create /f /tn "hayati-bourse" /tr "\"%BAT%\" bourse" /sc daily /st 12:45
if errorlevel 1 (echo    x ساخت hayati-bourse شکست خورد & goto :hold)
echo    + hayati-bourse   هر روز 12:45  (یک ربع بعد از بستن بورس)

schtasks /create /f /tn "hayati-tala" /tr "\"%BAT%\" tala" /sc daily /st 18:15
if errorlevel 1 (echo    x ساخت hayati-tala شکست خورد & goto :hold)
echo    + hayati-tala     هر روز 18:15  (یک ربع بعد از بستن طلا)

echo.
echo -- آزمایش --
echo    الان یک‌بار دستی اجرا می‌کنم تا مطمئن شویم کار می‌کند.
echo.
call "%BAT%" bourse
if errorlevel 1 (
  echo.
  echo    x اجرای آزمایشی شکست خورد. تسک‌ها ساخته شده‌اند ولی
  echo      تا این خطا حل نشود هر روز بی‌صدا شکست می‌خورند.
  goto :hold
)

echo.
echo -- تمام --
echo    داشبورد: %~dp0portfolio.html
echo.
echo    دیدنِ تسک‌ها:  schtasks /query /tn hayati-bourse
echo    اجرای دستی:    schtasks /run /tn hayati-bourse
echo    حذفشان:        schtasks /delete /tn hayati-bourse /f
echo                   schtasks /delete /tn hayati-tala /f

:hold
echo.
pause
