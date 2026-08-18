#!/bin/bash
# 因子轮动月度 cron 脚本
# 每月1日 09:30 运行（在 factor_ic.py 之后）
# 计算IC权重并应用到评分系统

SCRIPT_DIR="$HOME/.hermes/skills/stock/stock-expert/skills/feishu-bitable"
cd "$SCRIPT_DIR" || exit 1
python3 factor_rotation.py --apply 2>/dev/null