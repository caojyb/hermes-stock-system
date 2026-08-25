#!/bin/bash
# 系统健康检查 - 正常无声，异常才推送
# 不产生任何输出文件

# Gateway HTTP 健康检查（直接验证服务可用性，比进程检查更可靠）
GW_BODY=$(curl -s --max-time 5 http://127.0.0.1:18789/health 2>/dev/null)
GW_OK=0
if echo "$GW_BODY" | grep -q '"ok":true'; then
  GW_OK=1
fi

# Hindsight HTTP 健康检查（进程在跑不代表服务可用，以 /health 为准）
HINDSIGHT_BODY=$(curl -s --max-time 10 http://127.0.0.1:9177/health 2>/dev/null)
HINDSIGHT_OK=0
if echo "$HINDSIGHT_BODY" | grep -q '"status":"healthy"'; then
  HINDSIGHT_OK=1
fi

# 判断结果：任一 HTTP 检查失败即告警
if [ "$GW_OK" -eq 0 ] || [ "$HINDSIGHT_OK" -eq 0 ]; then
  echo "[ALERT] Hermes 健康异常 - Gateway:${GW_OK} Hindsight:${HINDSIGHT_OK}"
  echo "  Gateway body: ${GW_BODY:-timeout}"
  echo "  Hindsight body: ${HINDSIGHT_BODY:-timeout}"
  exit 1
fi

exit 0
