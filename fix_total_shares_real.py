#!/usr/bin/env python3
"""
补全 stocks.total_shares_real 数据
================================
方法：用 total_mcap / 最新收盘价 推算总股本
因为 total_mcap = total_shares × close_price，所以：
total_shares_real = total_mcap / close_price
"""
import sqlite3
from datetime import datetime

MKT_DB = '/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db'
TODAY = datetime.now().strftime('%Y-%m-%d')


def main():
    conn = sqlite3.connect(MKT_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 统计补全前
    cur.execute("SELECT COUNT(*) FROM stocks WHERE total_shares_real IS NOT NULL AND total_shares_real > 0")
    before = cur.fetchone()[0]

    # 获取所有有 total_mcap 但无 total_shares_real 的股票
    cur.execute("""
        SELECT code, total_mcap FROM stocks
        WHERE total_mcap IS NOT NULL AND total_mcap > 0
          AND (total_shares_real IS NULL OR total_shares_real <= 0)
    """)
    to_fix = {r["code"]: r["total_mcap"] for r in cur.fetchall()}
    print(f"  需要补全: {len(to_fix)} 只")

    # 获取每只股票的最新收盘价
    updated = 0
    no_price = 0
    for code, total_mcap in to_fix.items():
        cur.execute("""
            SELECT close FROM klines
            WHERE code=? AND date<=? AND close IS NOT NULL AND close > 0
            ORDER BY date DESC LIMIT 1
        """, (code, TODAY))
        row = cur.fetchone()
        if row and row["close"]:
            total_shares = total_mcap / row["close"]
            if total_shares > 1000 and total_shares < 1e12:  # 合理范围检查
                cur.execute("UPDATE stocks SET total_shares_real=? WHERE code=?", (total_shares, code))
                updated += 1
            else:
                no_price += 1
        else:
            no_price += 1

        if updated % 500 == 0 and updated > 0:
            conn.commit()

    conn.commit()

    # 统计补全后
    cur.execute("SELECT COUNT(*) FROM stocks WHERE total_shares_real IS NOT NULL AND total_shares_real > 0")
    after = cur.fetchone()[0]

    print(f"\n  补全前: {before} 只")
    print(f"  补全后: {after} 只")
    print(f"  已更新: {updated} 只")
    print(f"  无价格数据跳过: {no_price} 只")

    # 验证样本
    cur.execute("""
        SELECT code, name, total_shares_real, total_mcap FROM stocks
        WHERE total_shares_real IS NOT NULL AND total_shares_real > 0
        LIMIT 5
    """)
    print(f"\n  验证样本:")
    for r in cur.fetchall():
        print(f"    {r['code']} {r['name']:10s} total_shares={r['total_shares_real']:.0f} total_mcap={r['total_mcap']:.0f}")

    conn.close()
    print(f"\n  ✅ 完成")


if __name__ == "__main__":
    main()
