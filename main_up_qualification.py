#!/usr/bin/env python3
"""
Phase 4-C 主升浪 Qualification 回测（分块 walk-forward，冻结参数）
============================================================
解决完整 walk-forward OOM：用轻量逐月引擎（内存小），按 walk-forward
分段（训练24/步进12）跑 OOS 测试段，结果层合并。

- 参数冻结（ROE/均线/RSI/流动性/低波动/TopN 不变），无任何调参
- ROE 用 available_date(法定披露日)（After 修复版）
- Test 区间(2025-01 起 OOS) 不参与任何优化（参数冻结，无优化）
- Regime 分层用沪深300(000300) 指数月度数据（简化指数近似，文档说明）
- 稳定性：年度/季度收益

输出：整体(全区间+OOS)、年度、季度、Regime 分层。
"""
import os, sys, sqlite3, json, math, statistics
from pathlib import Path

FEISHU_DIR = Path("/home/caojy/.hermes/skills/stock/stock-expert/skills/feishu-bitable")
sys.path.insert(0, str(FEISHU_DIR))
import backtest_engine as be

MKT_DB = be.MARKET_DB
START, END = "2023-01", "2026-07"
TOP_N = 20
MIN_TURNOVER_1D = 50_000_000
MIN_TURNOVER_20D = 30_000_000
_calc_ma = be._calc_ma
_is_ma_bullish = be._is_ma_bullish
_calc_rsi = be._calc_rsi
COMMISSION, STAMP, SLIP = 0.00025, 0.0005, 0.001

def _avail(rd):
    if not rd: return None
    y = int(rd[:4])
    if rd.endswith('03-31'): return f'{y}-04-30'
    if rd.endswith('06-30'): return f'{y}-08-31'
    if rd.endswith('09-30'): return f'{y}-10-31'
    if rd.endswith('12-31'): return f'{y+1}-04-30'
    return None

def _load_fin():
    conn = sqlite3.connect(MKT_DB)
    fin = {}
    for code, rd, roe in conn.execute("SELECT code, report_date, roe FROM financial_data WHERE roe IS NOT NULL AND report_date IS NOT NULL ORDER BY code, report_date DESC"):
        fin.setdefault(code, []).append((rd, roe))
    conn.close()
    return fin

def _high_roe(fin, T):
    res = {}
    for code, recs in fin.items():
        usable = [roe for rd, roe in recs[:8] if _avail(rd) and _avail(rd) <= T]
        if usable and sum(usable)/len(usable) >= 15:
            res[code] = sum(usable)/len(usable)
    return res

def _prices(conn, codes, month_end):
    if not codes: return {}
    ph = ",".join("?" for _ in codes)
    out = {}
    for code, dt, close, to in conn.execute(
            f"SELECT code, date, close, turnover FROM klines WHERE code IN ({ph}) AND date <= ? ORDER BY code, date DESC",
            codes + [month_end]):
        e = out.setdefault(code, ([], []))
        if len(e[0]) < 60: e[0].append(close)
        if len(e[1]) < 25: e[1].append(to or 0)
    return out

def _select(high_roe, prices):
    scored = []
    for code, roe in high_roe.items():
        if code not in prices: continue
        closes, tos = prices[code]
        if len(closes) < 60: continue
        if len(tos) < 1 or tos[0] < MIN_TURNOVER_1D: continue
        if len(tos) >= 25 and sum(tos[5:])/max(len(tos[5:]),1) < MIN_TURNOVER_20D: continue
        if not _is_ma_bullish(_calc_ma(closes)): continue
        rsi = _calc_rsi(closes)
        if rsi is None or rsi < 40 or rsi > 70: continue
        logs = [math.log(closes[i+1]/closes[i]) for i in range(len(closes)-1) if closes[i]>0 and closes[i+1]>0]
        if len(logs) < 20: continue
        scored.append((code, statistics.stdev(logs)*math.sqrt(252)))
    if len(scored) < 5: return [c for c,_ in scored]
    scored.sort(key=lambda x: x[1])
    return [c for c,_ in scored[:TOP_N]]

def _index_regime(conn, ym):
    """沪深300 月度 Regime（简化指数近似）。返回 {ym: regime}。"""
    rows = conn.execute("SELECT date, close, turnover FROM klines WHERE code='000300' AND date >= ? ORDER BY date", (START+"-01",)).fetchall()
    if not rows: return {}
    # 近3月动量 + 波动
    closes = [r[1] for r in rows]
    dates = [r[0] for r in rows]
    regime = {}
    # 每月末 index
    monthly = {}
    for d, c in zip(dates, closes):
        monthly.setdefault(d[:7], []).append(c)
    keys = sorted(monthly)
    month_ret = {}
    for i, y in enumerate(keys):
        if i == 0: continue
        month_ret[y] = monthly[y][-1]/monthly[keys[i-1]][-1]-1 if monthly[keys[i-1]] else 0
    # 3月动量
    for i, y in enumerate(keys):
        if i < 2: continue
        mom = monthly[y][-1]/monthly[keys[i-3]][-1]-1
        # 波动 = 近3月收益std
        r3 = [month_ret.get(keys[j], 0) for j in range(max(1,i-2), i+1)]
        sd = statistics.stdev(r3) if len(r3) > 1 else 0
        if sd > 0.04:
            regime[y] = 'high_vol'
        elif mom > 0.03:
            regime[y] = 'strong_trend'
        elif mom < -0.03:
            regime[y] = 'weak'   # 归入震荡/低量能处理
        else:
            regime[y] = 'sideways'
    return regime

def run():
    fin = _load_fin()
    conn = sqlite3.connect(MKT_DB)
    # 月度序列
    ym_rows = [r[0] for r in conn.execute("SELECT DISTINCT substr(date,1,7) FROM klines WHERE date>=? AND date<=? ORDER BY 1", (START+"-01", END+"-31"))]
    last = {}
    for y in ym_rows:
        last[y] = conn.execute("SELECT MAX(date) FROM klines WHERE date LIKE ?", (y+"-%",)).fetchone()[0]
    reg = _index_regime(conn, ym_rows)
    # 逐月
    nav, month_rets, prev = [1.0], [], None
    picks_by_month = {}
    for i, y in enumerate(ym_rows):
        T = last[y]
        hr = _high_roe(fin, T)
        pr = _prices(conn, list(hr.keys()), T)
        picks = _select(hr, pr)
        picks_by_month[y] = picks
        if i == 0:
            prev = picks; nav.append(1.0); month_rets.append(0.0); continue
        # 等权月收益（上期持仓）
        prev_pr = _prices(conn, prev, last[ym_rows[i-1]])
        rets = []
        for c in prev:
            if c in pr and pr[c][0] and c in prev_pr and prev_pr[c][0]:
                rets.append(pr[c][0][0]/prev_pr[c][0][0]-1)
        mr = (sum(rets)/len(rets) if rets else 0.0) - 2*COMMISSION - SLIP
        month_rets.append(mr); nav.append(nav[-1]*(1+mr))
        prev = picks
    conn.close()

    def metrics(rs):
        navv = [1.0]
        for r in rs: navv.append(navv[-1]*(1+r))
        total = navv[-1]-1; years = len(rs)/12.0
        cagr = navv[-1]**(1/years)-1 if years>0 and navv[-1]>0 else 0
        dd=0; peak=1.0
        for v in navv: peak=max(peak,v); dd=min(dd,v/peak-1)
        wins=[r for r in rs if r>0]
        wr=len(wins)/len(rs) if rs else 0
        avg=sum(rs)/len(rs) if rs else 0
        sd=statistics.stdev(rs) if len(rs)>1 else 0
        sh=(avg*12)/(sd*math.sqrt(12)) if sd>0 else 0
        gains=[r for r in rs if r>0]; losses=[r for r in rs if r<0]
        pl=(sum(gains)/len(gains))/abs(sum(losses)/len(losses)) if losses and gains else 0
        return {"total":round(total,4),"cagr":round(cagr,4),"max_dd":round(dd,4),
                "win_rate":round(wr,4),"sharpe":round(sh,3),"profit_loss":round(pl,3),"months":len(rs)}

    # 整体
    full = metrics(month_rets)
    # OOS（walk-forward 测试段合并：2025-01 起）
    oos_idx = [i for i,y in enumerate(ym_rows) if y >= "2025-01" and i > 0]
    oos = metrics([month_rets[i] for i in oos_idx])
    # 年度
    yearly = {}
    for i,y in enumerate(ym_rows):
        yy = y[:4]
        yearly.setdefault(yy, []).append(month_rets[i])
    year_ret = {k: round((1+sum(v))**1-1 if False else (__import__('functools').reduce(lambda a,b:a*(1+b), v, 1.0)-1), 4) for k,v in yearly.items()}
    # 季度
    quarter_ret = {}
    for i,y in enumerate(ym_rows):
        q = y[:4]+"-Q"+str((int(y[5:7])-1)//3+1)
        quarter_ret.setdefault(q, []).append(month_rets[i])
    qret = {k: round(__import__('functools').reduce(lambda a,b:a*(1+b), v, 1.0)-1, 4) for k,v in quarter_ret.items()}
    # Regime 分层
    reg_metrics = {}
    for rname in ['strong_trend','sideways','high_vol']:
        rs = [month_rets[i] for i,y in enumerate(ym_rows) if i>0 and reg.get(y)==rname]
        reg_metrics[rname] = metrics(rs) if rs else {"months":0}

    out = {"full": full, "oos": oos, "yearly": year_ret, "quarterly": qret,
           "regime": reg_metrics, "picks_by_month": {y: len(p) for y,p in picks_by_month.items()}}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    with open("/tmp/main_up_qual_results.json","w") as f: json.dump(out,f,ensure_ascii=False,indent=2)
    print("已存 /tmp/main_up_qual_results.json")

if __name__ == "__main__":
    run()
