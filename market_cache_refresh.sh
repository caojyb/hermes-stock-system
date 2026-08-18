#!/bin/bash
# 全市场K线缓存刷新 - 每日收盘后16:30执行
# no_agent 模式：成功→简洁汇总；失败→醒目告警 + 错误详情
set -eu

SCRIPT_DIR="/home/caojy/.hermes/skills/stock/stock-expert/skills/feishu-bitable"
LOG_FILE="/home/caojy/.hermes/logs/market_cache_refresh.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
}

log "=== 开始全市场K线缓存刷新 ==="

cd "$SCRIPT_DIR"
# 脚本内部已清除代理环境变量，无需额外处理
# 安静模式：no_agent 推送到飞书时只输出最终汇总，避免逐批进度刷屏
export MARKET_CACHE_QUIET=1

# 捕获 python 的 stdout+stderr，失败时把错误详情推送到飞书
OUT=$(mktemp)
if python3 market_cache.py incremental >"$OUT" 2>&1; then
    cat "$OUT"
    log "✅ 增量更新成功"
    echo "✅ market_cache incremental 完成"
    # 记录管道状态
    python3 -c "
import sys; sys.path.insert(0, '/home/caojy/.hermes/scripts/cron')
from pipeline_status import record_status
from datetime import date
record_status('stock-market-cache-refresh', 'ok', date.today().isoformat(), message='增量K线刷新成功')
" 2>/dev/null || true
    rm -f "$OUT"
    exit 0
else
    exit_code=$?
    log "❌ 增量更新失败 (exit=$exit_code)"
    echo "❌❌ market_cache incremental 刷新失败 (exit=$exit_code)"
    echo "--- 错误详情（末尾 40 行）---"
    tail -40 "$OUT"
    echo "--- 错误详情完 ---"
    python3 -c "
import sys; sys.path.insert(0, '/home/caojy/.hermes/scripts/cron')
from pipeline_status import record_status
from datetime import date
record_status('stock-market-cache-refresh', 'error', date.today().isoformat(), message=f'刷新失败 exit=$exit_code')
" 2>/dev/null || true
    rm -f "$OUT"
    exit $exit_code
fi
