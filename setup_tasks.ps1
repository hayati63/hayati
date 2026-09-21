# ═══════════════════════════════════════════════════════════════════
#  نصب دو زمان‌بندی روزانه — مسیر را خودش پیدا می‌کند
#
#  اجرا: راست‌کلیک روی این فایل → Run with PowerShell
#  یا در PowerShell:   .\setup_tasks.ps1
#
#  چرا اسکریپت و نه دستور دستی: مسیر پوشه فاصله دارد، و schtasks
#  برای مسیرِ فاصله‌دار نقل‌قولِ تودرتو می‌خواهد. یک کاراکتر اشتباه
#  یعنی تسک هر روز بی‌صدا شکست می‌خورد.
# ═══════════════════════════════════════════════════════════════════

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$bat  = Join-Path $here 'refresh.bat'

Write-Host ''
Write-Host '── بررسی ──' -ForegroundColor Cyan
if (-not (Test-Path $bat)) {
    Write-Host "✗ refresh.bat کنار این اسکریپت نیست." -ForegroundColor Red
    Write-Host "  این فایل باید داخل پوشهٔ مخزن باشد. الان اینجاست:"
    Write-Host "  $here"
    exit 1
}
Write-Host "✓ refresh.bat پیدا شد" -ForegroundColor Green
Write-Host "  $bat"

# پایتون هست؟ بدون آن تسک‌ها بی‌فایده‌اند.
try   { $pv = (& python --version 2>&1) }
catch { $pv = $null }
if (-not $pv) {
    Write-Host "✗ python در PATH نیست. تسک‌ها ساخته می‌شوند ولی کار نمی‌کنند." -ForegroundColor Red
    Write-Host "  اول پایتون را نصب کن و گزینهٔ «Add to PATH» را بزن."
    exit 1
}
Write-Host "✓ $pv" -ForegroundColor Green

function New-DailyTask {
    param([string]$Name, [string]$Mode, [string]$Time)
    # نقل‌قولِ تودرتو: schtasks خودش رشته را دوباره پارس می‌کند
    $action = '"{0}" {1}' -f $bat, $Mode
    $null = schtasks /create /tn $Name /tr $action /sc daily /st $Time /f 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "✗ ساخت $Name شکست خورد" -ForegroundColor Red
        return $false
    }
    Write-Host "✓ $Name  ساعت $Time" -ForegroundColor Green
    return $true
}

Write-Host ''
Write-Host '── ساخت زمان‌بندی ──' -ForegroundColor Cyan
$ok1 = New-DailyTask -Name 'hayati-bourse' -Mode 'bourse' -Time '12:45'
$ok2 = New-DailyTask -Name 'hayati-tala'   -Mode 'tala'   -Time '18:15'

Write-Host ''
Write-Host '── تأیید: مسیرِ ثبت‌شده ──' -ForegroundColor Cyan
foreach ($n in 'hayati-bourse','hayati-tala') {
    $info = schtasks /query /tn $n /fo list /v 2>&1 | Select-String 'Task to Run|اجرای'
    if ($info) {
        $p = ($info -split ':', 2)[1].Trim()
        Write-Host "  $n"
        if ($p -like '*...*') {
            Write-Host "    ✗ هنوز مسیرِ جای‌نگهدار دارد!" -ForegroundColor Red
        } else {
            Write-Host "    $p" -ForegroundColor Gray
        }
    }
}

Write-Host ''
Write-Host '── تست واقعی ──' -ForegroundColor Cyan
Write-Host 'یک‌بار همین حالا اجرا می‌شود تا مطمئن شویم کار می‌کند...'
Write-Host ''
& $bat bourse
if ($LASTEXITCODE -eq 0) {
    Write-Host ''
    Write-Host '✓ اجرا موفق بود. زمان‌بندی از فردا خودکار است.' -ForegroundColor Green
    $dash = Join-Path $here 'portfolio.html'
    if (Test-Path $dash) {
        Write-Host ''
        Write-Host "داشبورد اینجاست:" -ForegroundColor Cyan
        Write-Host "  $dash"
        Write-Host 'باز می‌شود...'
        Start-Process $dash
    } else {
        Write-Host ''
        Write-Host '⚠️ portfolio.html ساخته نشد.' -ForegroundColor Yellow
        Write-Host '  یعنی dashboard_monthly.py کنار refresh.bat نیست.'
        Write-Host '  آن فایل مال خودت است — کپی‌اش کن همین‌جا.'
    }
} else {
    Write-Host ''
    Write-Host '✗ اجرا شکست خورد. خروجی بالا را بفرست.' -ForegroundColor Red
}
Write-Host ''
Write-Host 'حذف زمان‌بندی‌ها، اگر خواستی:'
Write-Host '  schtasks /delete /tn "hayati-bourse" /f'
Write-Host '  schtasks /delete /tn "hayati-tala" /f'
