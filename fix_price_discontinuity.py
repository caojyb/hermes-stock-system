#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fix klines price 前复权/不复权 断点 (2026-08-10)
================================================
Diagnosis: klines prices are 前复权 throughout, but on TWO different anchors:
  - pre  2023-12-05 : 前复权 anchored ~2026-07 (investment_data basis)
  - post 2023-12-05 : 前复权 anchored ~now    (腾讯 qfq basis)
This creates a fake price jump at 2023-12-05 (e.g. 000001 2.84 -> 7.56 same stock).

Fix (user-accepted fallback: 统一为前复权, consistent with current refresh):
  Unify to the post-boundary (current, 腾讯 qfq) 前复权 basis.
  For each stock compute k = first_post_boundary_close / last_pre_boundary_close,
  then scale ALL pre-boundary rows' OHLC by k.
  -> series becomes continuous across 2023-12-05; ALL pre-boundary returns preserved
     (constant scaling); recent 2023 window converts to ~real price.

Backup: backups/market_cache_pre_pricefix_20260810.db
"""
import sqlite3, time, sys
DB='/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db'
SW='2023-12-05'
con=sqlite3.connect(DB,timeout=120); cur=con.cursor()
cur.execute("SELECT code FROM stocks")
codes=[r[0] for r in cur.fetchall()]
print(f"codes to process: {len(codes)}", file=sys.stderr)
scaled=0; skipped=0; no_post=0; done=0
t0=time.time()
con.execute("BEGIN")
for code in codes:
    cur.execute("SELECT close FROM klines WHERE code=? AND date<? ORDER BY date DESC LIMIT 1",(code,SW))
    pre=cur.fetchone()
    cur.execute("SELECT close FROM klines WHERE code=? AND date>=? ORDER BY date LIMIT 1",(code,SW))
    post=cur.fetchone()
    if not post:
        no_post+=1; continue
    if not pre or not pre[0] or pre[0]<=0 or not post[0] or post[0]<=0:
        skipped+=1; continue
    k=post[0]/pre[0]
    if k<=0:
        skipped+=1; continue
    cur.execute("""UPDATE klines SET open=open*?, high=high*?, low=low*?, close=close*?
                   WHERE code=? AND date<?""",(k,k,k,k,code,SW))
    scaled+=cur.rowcount; done+=1
    if done%1000==0:
        print(f"  ...{done} codes, {scaled} rows", file=sys.stderr)
con.commit()
print(f"scaled {scaled} rows across {len(codes)} codes in {time.time()-t0:.0f}s", file=sys.stderr)
print(f"no_post={no_post} skipped={skipped}", file=sys.stderr)
# verify continuity
print("\n=== Post-fix boundary continuity (should be ~continuous) ===")
for code in ['600519','000001','601318','600036','000858','600000']:
    cur.execute("SELECT date,close FROM klines WHERE code=? AND date IN ('2023-12-04','2023-12-05') ORDER BY date",(code,))
    r=cur.fetchall()
    if len(r)==2:
        print(f"  {code}: 12-04={r[0][1]:.2f} 12-05={r[1][1]:.2f} jump={r[1][1]/r[0][1]-1:+.2%}")
con.close()
print("\nFIX-COMPLETE", file=sys.stderr)
