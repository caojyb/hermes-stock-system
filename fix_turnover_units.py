#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fix klines.turnover unit inconsistency (2026-08-10) — corrected, ratio-aware version
====================================================================================
The klines.turnover table mixes 3 conventions (distinguishable by r = turnover/(volume*close)):

  r ≈ 0.1   (0.005 <= r < 0.5) : 千元  — volume in 手, turnover in 千元  -> NEEDS ×1000
  r ≈ 1.0   (0.5  <= r < 5)    : 股-vol 元 — volume in 股, turnover in 元 -> leave alone
  r ≈ 100   (5    <= r < 500)  : 手-vol 元 — volume in 手, turnover in 元 -> leave alone

This migration converts ONLY the 千元 rows (any date, the unit is inconsistent with the
元 口径 everywhere) to 元 by ×1000. 元 rows (whether volume is 股 or 手) are untouched.

Verified on original data: bands are cleanly separated (only 11 rows in 0.3-0.7, 7335 in 2-20).
Backup kept: backups/market_cache_pre_turnover_fix_20260810.db
"""
import sqlite3, time, sys

DB = '/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db'

con = sqlite3.connect(DB, timeout=120)
cur = con.cursor()

# Pre-count
cur.execute("""SELECT COUNT(*) FROM klines
               WHERE turnover>0 AND volume>0 AND close>0
                 AND turnover/(volume*close) < 0.5""")
to_fix = cur.fetchone()[0]
cur.execute("""SELECT COUNT(*) FROM klines
               WHERE turnover>0 AND volume>0 AND close>0
                 AND turnover/(volume*close) >= 0.5""")
keep = cur.fetchone()[0]
print(f"rows to convert (千元->元): {to_fix}", file=sys.stderr)
print(f"rows to keep (already 元):  {keep}", file=sys.stderr)

t0 = time.time()
con.execute("BEGIN")
cur.execute("""UPDATE klines SET turnover = turnover * 1000
               WHERE turnover>0 AND volume>0 AND close>0
                 AND turnover/(volume*close) < 0.5""")
con.commit()
print(f"UPDATE done: {cur.rowcount} rows in {time.time()-t0:.0f}s", file=sys.stderr)

# Post-verify: no 千元 rows remain, bands now 元
cur.execute("""SELECT COUNT(*) FROM klines WHERE turnover>0 AND volume>0 AND close>0
               AND turnover/(volume*close) < 0.5""")
print(f"post-check remaining 千元 rows: {cur.fetchone()[0]}", file=sys.stderr)

print("\n=== Post-fix verification ===")
for code,dt in [('000001','2007-01-04'),('000001','2008-01-02'),('000001','2015-01-05'),
                ('000001','2018-01-02'),('600519','2023-12-04'),('000078','2026-01-05'),
                ('689009','2026-08-07'),('600000','2010-01-04')]:
    cur.execute("SELECT close,volume,turnover FROM klines WHERE code=? AND date=?",(code,dt))
    r=cur.fetchone()
    if not r: continue
    cl,vol,to=r
    print(f"  {code} {dt}: close={cl} vol={vol:.0f} turnover={to:,.0f} t/(v*c)={to/(vol*cl):.2f}")
con.close()
print("\nFIX-COMPLETE", file=sys.stderr)
