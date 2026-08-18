#!/bin/bash
# 情绪温度计 cron 脚本
# 输出文本报告到 stdout → 由 cron no_agent 模式投递到飞书
# 同时记录到学习日志

SCRIPT_DIR="$HOME/.hermes/skills/stock/stock-expert/skills/feishu-bitable"
cd "$SCRIPT_DIR" || exit 1
python3 sentiment_thermo.py --learn 2>/dev/null