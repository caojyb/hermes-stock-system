#!/bin/bash
# no_agent wrapper: 全流程引擎 + 知识库推送 + 学习记录
cd /home/caojy/.hermes/skills/stock/stock-expert/skills/feishu-bitable || exit 2
source ~/.hermes/venv/bin/activate 2>/dev/null
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
out=$(python3 stock_pipeline.py --quick 2>&1); c1=$?
kb=$(python3 kb_sync.py push --pipeline 2>&1); c2=$?
lg=$(python3 learn_log.py record-from-pipeline 2>&1); c3=$?
echo "$out"
echo ""
echo "===== 知识库同步 ====="
echo "$kb" | tail -15
echo ""
echo "===== 学习记录 ====="
echo "$lg" | tail -10
if [ $c1 -ne 0 ] || [ $c2 -ne 0 ] || [ $c3 -ne 0 ]; then
  echo ""
  echo "⚠️ 部分步骤失败:"
  [ $c1 -ne 0 ] && echo "  [stock_pipeline exit $c1]"
  [ $c2 -ne 0 ] && echo "  [kb_sync exit $c2]"
  [ $c3 -ne 0 ] && echo "  [learn_log exit $c3]"
  exit 1
fi
exit 0
