#!/bin/bash
# Cron健康检查 - 检查hermes cron调度器是否正常
# 正常无声，异常才告警

CRON_OK=$(ps aux | grep -v grep | grep "hermes.*scheduler\|cron" | grep -v "grep" | wc -l)

if [ "$CRON_OK" -eq 0 ]; then
    echo "[ALERT] Hermes Cron调度器未运行"
    exit 1
fi
exit 0
