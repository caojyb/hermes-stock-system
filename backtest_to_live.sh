#!/usr/bin/env bash
# backtest_to_live_cron.sh — 每月回测→实盘参数自动更新
# 调度时间：每月1日 10:00（在 factor-rotation 之后）
# 功能：运行回测引擎，评估策略绩效，更新实盘参数

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FEISHU_DIR="$HOME/.hermes/skills/stock/stock-expert/skills/feishu-bitable"
OUTPUT_DIR="$HOME/.hermes/cron/output"
LOG_FILE="$OUTPUT_DIR/backtest_to_live_cron_$(date +%Y%m%d).log"

mkdir -p "$OUTPUT_DIR"

echo "=========================================" > "$LOG_FILE"
echo "📊 回测→实盘参数自动更新" >> "$LOG_FILE"
echo "时间: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
echo "=========================================" >> "$LOG_FILE"

# 计算回测时间范围：过去3年至今
# 如果是1月，回测从3年前1月开始
START_YEAR=$(date +%Y)
START_MONTH=$(date +%m)
END_YEAR=$START_YEAR
END_MONTH=$START_MONTH

# 回测至少3年数据
START_YEAR=$((START_YEAR - 3))
START="${START_YEAR}-${START_MONTH}"

# 如果是月首，回测到上个月
if [ "$START_MONTH" = "01" ]; then
    PREV_YEAR=$((END_YEAR - 1))
    END="${PREV_YEAR}-12"
else
    PREV_MONTH=$((10#$START_MONTH - 1))
    PREV_MONTH=$(printf "%02d" $PREV_MONTH)
    END="${END_YEAR}-${PREV_MONTH}"
fi

echo "回测区间: ${START} ~ ${END}" >> "$LOG_FILE"

# 运行回测→实盘映射（带重试，最多3次）
for i in 1 2 3; do
    echo "尝试第${i}次..." >> "$LOG_FILE"
    
    cd "$FEISHU_DIR" && python3 backtest_to_live.py \
        --apply \
        --start "$START" \
        --end "$END" \
        --top-n 30 2>&1 >> "$LOG_FILE"
    
    exit_code=$?
    if [ $exit_code -eq 0 ]; then
        echo "=== 完成 ===" >> "$LOG_FILE"
        break
    fi
    
    echo "=== 第${i}次失败(exit $exit_code)，15秒后重试 ===" >> "$LOG_FILE"
    sleep 15
done

# 输出结果摘要
echo "" >> "$LOG_FILE"
echo "--- 结果摘要 ---" >> "$LOG_FILE"

if [ -f "$OUTPUT_DIR/backtest_live_applied.json" ]; then
    BEST_STRATEGY=$(python3 -c "
import json
d = json.load(open('$OUTPUT_DIR/backtest_live_applied.json'))
print(f\"最佳策略: {d.get('best_strategy', '?')}\")
k = d.get('kelly_params', {})
print(f\"凯利: 胜率={k.get('win_rate', '?')}, 盈亏比={k.get('reward_risk_ratio', '?')}\")
c = d.get('config_adjustments', {})
print(f\"配置: 止损={c.get('stop_loss_pct', '?')}, 仓位={c.get('max_position_pct', '?')}\")
print(f\"变更数: {d.get('change_count', 0)}\")
")
    echo "$BEST_STRATEGY" >> "$LOG_FILE"
    echo "" >> "$LOG_FILE"
    echo "✅ 回测→实盘参数更新完成" >> "$LOG_FILE"
else
    echo "⚠️ 未找到映射结果文件" >> "$LOG_FILE"
fi

echo "=========================================" >> "$LOG_FILE"

# 输出日志到 stdout（供 Hermes cron 捕获）
cat "$LOG_FILE"