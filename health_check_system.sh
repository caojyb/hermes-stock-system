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
HINDSIGHT_HTTP=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 http://127.0.0.1:9177/health 2>/dev/null)
HINDSIGHT_OK=0
if [ "$HINDSIGHT_HTTP" = "200" ]; then
  HINDSIGHT_BODY=$(curl -s --max-time 10 http://127.0.0.1:9177/health 2>/dev/null)
  if echo "$HINDSIGHT_BODY" | grep -q '"status":"healthy"'; then
    HINDSIGHT_OK=1
  fi
fi

# cron 任务连续失败检查（检查最近一次是否同时触发 last_fire_error 和 last_delivery_error）
CRON_FAIL=0
CRON_STATUS=$(hermes cronjob list --json 2>/dev/null)
if [ -n "$CRON_STATUS" ]; then
  FAIL_COUNT=$(echo "$CRON_STATUS" | grep -c '"last_fire_error":.*"last_delivery_error":' 2>/dev/null || echo 0)
  if [ "$FAIL_COUNT" -gt 0 ]; then
    CRON_FAIL=1
  fi
fi

# 汇总
if [ "$HERMES_OK" -eq 1 ] && [ "$HINDSIGHT_OK" -eq 1 ] && [ "$CRON_FAIL" -eq 0 ]; then
  exit 0
else
  echo "[ALERT] Hermes 健康异常 - Gateway:${HERMES_OK} Hindsight:${HINDSIGHT_OK} CronFail:${CRON_FAIL} HTTP:${HINDSIGHT_HTTP}"
  exit 1
fi
