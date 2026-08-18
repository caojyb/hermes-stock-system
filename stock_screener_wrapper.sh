#!/bin/bash
# no_agent wrapper: 翻倍潜力股周选 (旧版报告 + V1扫描 + 候选统计)
cd /home/caojy/.hermes/skills/stock/stock-expert/skills/feishu-bitable || exit 2
source ~/.bashrc 2>/dev/null
echo "===== 翻倍潜力股周选报告 $(date '+%Y-%m-%d %H:%M') ====="
out1=$(python3 double_up_screener.py --min-score 50 --market-outlook --mode deep --industry-neutral --factor-process 2>&1); c1=$?
echo "$out1"
echo ""
echo "===== V1 翻倍扫描 (Top3参数, 写 double_up_scores) ====="
cd /home/caojy/.hermes/scripts/cron || exit 2
out2=$(python3 scan_doubling_potential.py 2>&1); c2=$?
echo "$out2" | tail -25
echo ""
echo "===== double_up_scores 最新候选统计 ====="
python3 -c "
import sqlite3
c=sqlite3.connect('/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db')
rows=list(c.execute('SELECT scan_date, COUNT(*) FROM double_up_scores GROUP BY scan_date ORDER BY scan_date DESC LIMIT 1'))
if rows: print('  最新一期', rows[0][0], '| 候选', rows[0][1], '只')
else: print('  无候选(跳过本周)')
"
if [ $c1 -ne 0 ] || [ $c2 -ne 0 ]; then
  echo ""
  echo "⚠️ 周选脚本执行失败:"
  [ $c1 -ne 0 ] && echo "  [double_up_screener exit $c1]"
  [ $c2 -ne 0 ] && echo "  [scan_doubling_potential exit $c2]"
  exit 1
fi
exit 0
