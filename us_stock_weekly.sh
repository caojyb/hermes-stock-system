#!/bin/bash
# 美股持仓周报推送
cd ~/.hermes/skills/stock/stock-expert/skills/feishu-bitable
http_proxy= https_proxy= HTTP_PROXY= HTTPS_PROXY= python3 us_stock_monitor.py --config us_stock_positions.json 2>&1