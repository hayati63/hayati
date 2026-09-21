#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
#  به‌روزرسانی — دو بار در روز. معادل refresh.bat برای لینوکس و مک.
#
#  crontab -e:
#    45 12 * * 6,0,1,2,3  cd /path/to/hayati && ./refresh.sh bourse >> refresh.log 2>&1
#    15 18 * * *          cd /path/to/hayati && ./refresh.sh tala   >> refresh.log 2>&1
#
#  شنبه تا چهارشنبه = 6,0,1,2,3 در cron (یکشنبه=0).
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail
cd "$(dirname "$0")"
MODE="${1:-full}"

echo "═══ $(date '+%F %T')  ·  حالت: $MODE ═══"

if [ "$MODE" != "tala" ]; then
    echo "[۱/۴] دانلود صندوق‌ها از TSETMC"
    python3 tools/fetch_tsetmc.py
fi

if compgen -G "data/chartix_in/*.csv" > /dev/null 2>&1 \
   || compgen -G "data/chartix_in/**/*.csv" > /dev/null 2>&1; then
    echo "[۲/۴] تبدیل اکسپورت چارتیکس"
    python3 tools/chartix_import.py --in data/chartix_in --tf 1D \
        --out data/drivers_daily
else
    echo "[۲/۴] data/chartix_in خالی است — محرک‌ها به‌روز نشدند."
fi

echo "[۳/۴] نقدشوندگی و پرتفوی هدف"
python3 tools/liquidity.py --data data_auto --holdings data/holdings.txt \
    --out data/liquidity.json
python3 tools/target_portfolio.py --data data_auto \
    --holdings data/holdings.txt --liquidity data/liquidity.json \
    --json data/target_portfolio.json

if [ -f dashboard_monthly.py ]; then
    python3 dashboard_monthly.py
    [ -f dashboard_monthly.html ] && python3 tools/portfolio_dashboard.py \
        --in dashboard_monthly.html --out portfolio.html
fi

echo "[۴/۴] ثبت و ارسال"
git add data_auto data/drivers_daily data/liquidity.json data/target_portfolio.json
if git diff --cached --quiet; then
    echo "  هیچ داده‌ای عوض نشد."
else
    git commit -q -m "داده $MODE $(date '+%F_%H:%M')"
    git push -q origin HEAD || echo "  ⚠️ push نشد. داده ثبت شد."
fi
echo "تمام."
