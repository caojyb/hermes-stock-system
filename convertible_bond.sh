#!/bin/bash
# 可转债每日扫描推送
cd ~/.hermes/skills/stock/stock-expert/skills/feishu-bitable
http_proxy= https_proxy= HTTP_PROXY= HTTPS_PROXY= python3 convertible_bond.py 2>&1