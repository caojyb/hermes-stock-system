#!/bin/bash
# no_agent wrapper: PE/PB/PS/PCF 全量更新，成功静默，失败告警
cd /home/caojy/.hermes/skills/stock/stock-expert/skills/feishu-bitable || exit 2
source ~/.hermes/venvs/astock/bin/activate 2>/dev/null
out1=$(python3 fetch_pe_pb.py 2>&1); c1=$?
out2=$(python3 /home/caojy/.hermes/scripts/cron/ps_pcf_update.py 2>&1); c2=$?
if [ $c1 -ne 0 ] || [ $c2 -ne 0 ]; then
  echo "🚨 PE/PB/PS/PCF 更新失败:"
  [ $c1 -ne 0 ] && { echo "[fetch_pe_pb exit $c1]"; echo "$out1" | tail -15; }
  [ $c2 -ne 0 ] && { echo "[ps_pcf exit $c2]"; echo "$out2" | tail -15; }
  exit 1
fi
exit 0
