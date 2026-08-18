#!/bin/bash
# 市场环境分析周报 - 每周日17:00执行
# 调用 market_env_report.py 生成并推送飞书群
set -eu

SCRIPT_DIR="/home/caojy/.hermes/skills/stock/stock-expert/skills/feishu-bitable"
LOG_FILE="/home/caojy/.hermes/logs/market_env_report.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
}

log "=== 开始市场环境分析 ==="

cd "$SCRIPT_DIR"
OUT=$(mktemp)
if python3 market_env_report.py >"$OUT" 2>&1; then
    cat "$OUT"
    log "✅ 市场环境分析完成"
    rm -f "$OUT"
    exit 0
else
    exit_code=$?
    log "❌ 市场环境分析失败 (exit=$exit_code)"
    echo "❌❌ market_env_report 失败 (exit=$exit_code)"
    echo "--- 错误详情（末尾 30 行）---"
    tail -30 "$OUT"
    echo "--- 错误详情完 ---"
    rm -f "$OUT"
    exit $exit_code
fi
