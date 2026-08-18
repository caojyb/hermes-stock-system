#!/bin/bash
# weekly_pool_report.sh - 推荐池每周跟踪报告
# 由 stock-recommendation-pool-weekly cron 调用
# 每次推送推荐后自动更新价格并生成报告，推送到飞书群

SKILL_DIR="$HOME/.hermes/skills/stock/stock-expert/skills/feishu-bitable"
cd "$SKILL_DIR" || exit 1

# 1. 更新推荐池价格和状态
echo "=== 更新推荐池价格 ==="
python3 recommendation_pool.py update 2>&1

# 2. 生成并推送跟踪报告
echo ""
echo "=== 生成推荐池跟踪报告 ==="
python3 weekly_pool_report.py 2>&1