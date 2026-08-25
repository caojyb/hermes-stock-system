#!/bin/bash
# 系统健康检查 - 正常无声，异常才推送
# 不产生任何输出文件

# 进程检查改用 pgrep，避免自匹配
HERMES_PID=$(pgrep -f "hermes_cli.main gateway run" | head -1)
HERMES_OK=0
if [ -n "$HERMES_PID" ]; then
  if kill -0 "$HERMES_PID" 2>/dev/null; then
    HERMES_OK=1
  fi
fi

# Hindsight HTTP 健康检查（进程在跑不代表服务可用，以 /health 为准）
HINDSIGHT_HTTP=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "http://127.0.0.1:9177/health" 2>/dev/null || echo "000")
HINDSIGHT_OK=0
if [ "$HINDSIGHT_HTTP" = "200" ]; then
  HINDSIGHT_BODY=$(curl -s --max-time 10 "http://127.0.0.1:9177/health" 2>/dev/null || echo "")
  if echo "$HINDSIGHT_BODY" | grep -q '"status":"healthy"'; then
    HINDSIGHT_OK=1
  fi
fi

# Hermes cron daemon 进程检查（不是 systemd user service）
CRON_PID=$(pgrep -f "cron_daemon.py daemon" | head -1)
CRON_OK=0
if [ -n "$CRON_PID" ]; then
  if kill -0 "$CRON_PID" 2>/dev/null; then
    CRON_OK=1
  fi
fi

# 构建告警（只有异常时才输出）
ALERTS=""
if [ "$HERMES_OK" -eq 0 ]; then
  ALERTS="${ALERTS}[ALERT] Hermes Gateway 进程异常\n"
fi
if [ "$HINDSIGHT_OK" -eq 0 ]; then
  ALERTS="${ALERTS}[ALERT] Hindsight daemon 异常 (HTTP=$HINDSIGHT_HTTP)\n"
fi
if [ "$CRON_OK" -eq 0 ]; then
  ALERTS="${ALERTS}[ALERT] Hermes cron daemon 进程异常\n"
fi

# 输出结果
if [ -n "$ALERTS" ]; then
  echo -e "$ALERTS"
  exit 1
else
  exit 0
fi
