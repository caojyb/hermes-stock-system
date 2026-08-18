#!/bin/bash
# no_agent wrapper: 财务数据增量补漏（7天内新鲜则跳过，秒级完成，规避3600s超时）
# 成功静默，失败告警+非零退出
cd /home/caojy/.hermes/skills/stock/stock-expert || exit 2
out=$(python3 fetch_financial_incremental.py 2>&1)
code=$?
if [ $code -ne 0 ]; then
  echo "🚨 fetch_financial_incremental 失败 (exit $code):"
  echo "$out" | tail -25
  exit $code
fi
exit 0
