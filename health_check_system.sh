#!/bin/bash
# 系统健康检查 - 正常无声，异常才推送
# 不产生任何输出文件

HERMES_OK=$(ps aux | grep -v grep | grep "hermes_cli.main gateway run" | wc -l)

# Hindsight HTTP 健康检查（进程在跑不代表服务可用，以 /health 为准）
HINDSIGHT_HTTP=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 http://127.0.0.1:9177/health 2>/dev/null || echo "000")
HINDSIGHT_BODY=$(curl -s --max-time 10 http://127.0.0.1:9177/health 2>/dev/null || echo "{}")
HINDSIGHT_STATUS=$(echo "$HINDSIGHT_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")

if [ "$HERMES_OK" -eq 0 ] || [ "$HINDSIGHT_HTTP" != "200" ] || [ "$HINDSIGHT_STATUS" != "healthy" ]; then
    echo "[ALERT] Hermes 健康异常 - Gateway:$HERMES_OK Hindsight_HTTP:$HINDSIGHT_HTTP status:$HINDSIGHT_STATUS"
    exit 1
fi
exit 0
