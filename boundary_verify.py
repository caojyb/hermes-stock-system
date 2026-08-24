#!/usr/bin/env python3
"""边界条件验证：检查候选池参数是否在合理范围内。"""
import sqlite3
from pathlib import Path

def main():
    print("🧪 边界条件验证")
    db = Path('/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db')
    if not db.exists():
        print("❌ market_cache.db 不存在")
        return 1
    conn = sqlite3.connect(str(db), timeout=10)
    cur = conn.cursor()
    checks = []
    # 1. turnover_rate 无空字符串
    cur.execute("SELECT COUNT(*) FROM indicators WHERE turnover_rate = ''")
    r = cur.fetchone()[0]
    checks.append(('turnover_rate 空字符串', r == 0, f'{r} 条'))
    # 2. param_optimization_log 有 annual_return 列
    cur.execute("PRAGMA table_info(param_optimization_log)")
    cols = [row[1] for row in cur.fetchall()]
    checks.append(('annual_return 列存在', 'annual_return' in cols, str(cols)))
    # 3. double_up_scores 主键完整
    cur.execute("PRAGMA table_info(double_up_scores)")
    dcols = [row[1] for row in cur.fetchall()]
    checks.append(('double_up_scores schema', 'scan_date' in dcols and 'code' in dcols, str(dcols)))
    # 4. real_portfolio_history 表存在
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='real_portfolio_history'")
    checks.append(('real_portfolio_history 表', cur.fetchone() is not None, ''))
    conn.close()
    all_ok = True
    for name, passed, detail in checks:
        icon = '✅' if passed else '❌'
        print(f"  {icon} {name}: {detail}")
        if not passed:
            all_ok = False
    if all_ok:
        print("✅ 边界验证通过")
        return 0
    else:
        print("❌ 边界验证失败")
        return 1

if __name__ == '__main__':
    import sys
    sys.exit(main())
