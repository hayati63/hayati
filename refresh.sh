#!/usr/bin/env bash
# همان refresh.bat برای لینوکس و مک. روی ماشین خودت، نه کانتینر ابری.
#   crontab:  30 18 * * *  cd /path/to/hayati && ./refresh.sh >> refresh.log 2>&1
set -euo pipefail
cd "$(dirname "$0")"

echo "=== ۱. دانلود از TSETMC ==="
python3 tools/fetch_tsetmc.py

echo "=== ۲. نقدشوندگی ==="
python3 tools/liquidity.py --data data_auto --holdings data/holdings.txt \
    --out data/liquidity.json

echo "=== ۳. پرتفوی هدف ==="
python3 tools/target_portfolio.py --data data_auto --holdings data/holdings.txt \
    --liquidity data/liquidity.json --json data/target_portfolio.json

echo "=== ۴. داشبورد پرتفو ==="
if [ -f dashboard_monthly.py ]; then
    python3 dashboard_monthly.py
    [ -f dashboard_monthly.html ] && python3 tools/portfolio_dashboard.py \
        --in dashboard_monthly.html --out portfolio.html
else
    echo "  dashboard_monthly.py نبود — رد شد."
fi

echo "=== ۵. ثبت و ارسال ==="
git add data_auto data/liquidity.json data/target_portfolio.json
if git diff --cached --quiet; then
    echo "هیچ داده‌ای عوض نشد."
else
    git commit -q -m "داده‌های روزانه $(date +%F)"
    git push -q origin HEAD || echo "⚠️ push نشد. داده ثبت شد، بعداً push کن."
fi
