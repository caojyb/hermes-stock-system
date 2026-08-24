#!/bin/bash
# 系统健康检查 - 正常无声，异常才推送
# 不产生任何输出文件

HERMES_OK=$(ps aux | grep -v grep | grep "hermes_cli.main gateway run" | wc -l)
# Hindsight 以 postgres 形式运行（hindsight-embed-hermes 实例）
HINDSIGHT_OK=$(ps aux | grep -v grep | grep "hindsight-embed-hermes" | wc -l)

if [ "$HERMES_OK" -eq 0 ] || [ "$HINDSIGHT_OK" -eq 0 ]; then
    echo "[ALERT] Hermes 健康异常 - Gateway:$HERMES_OK Hindsight:$HINDSIGHT_OK"
    exit 1
fi
exit 0
