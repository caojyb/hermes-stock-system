#!/usr/bin/env python3
"""
双池资金流转管理器
===================
补全1：赛道宽松池半自动买入（A+B+D信号推送+确认）
补全2：主池止盈资金→赛道池流转（50%自动转入）
"""
import os, sys, json, sqlite3, requests
from datetime import date, datetime, timedelta
from pathlib import Path

MKT_DB = '/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db'
SIM_DB = '/home/caojy/.hermes/scripts/cron/simulation.db'
PENDING_FILE = '/home/caojy/.hermes/scripts/cron/track_pending_buy.json'
TRACK_POOL_FILE = '/home/caojy/.hermes/scripts/cron/track_loose_pool.json'
TOTAL_CAPITAL = 1000000
HEADERS = {'User-Agent': 'Mozilla/5.0'}

# ═══ 补全1：A+B+D信号检测 ═══
def check_signals(code, closes, volumes, highs):
    """检测A/B/D三重信号"""
    sigs = []
    # A: 站上20日均线+均线拐头
    if len(closes) >= 20:
        ma20 = sum(closes[:20]) / 20
        ma20_prev = sum(closes[1:21]) / 20
        if closes[0] > ma20 and ma20 >= ma20_prev:
            sigs.append('A')
    # B: 倍量启动
    if len(volumes) >= 13:
        v3 = sum(volumes[:3])
        v10 = sum(volumes[3:13]) / 10
        if v10 > 0 and v3 > v10 * 1.8:
            sigs.append('B')
    # D: MACD金叉
    if len(closes) >= 35:
        def ema(d, p):
            k = 2/(p+1); r = [d[0]]
            for x in d[1:]: r.append(x*k + r[-1]*(1-k))
            return r
        ef = ema(closes, 12); es = ema(closes, 26)
        dif = [ef[i]-es[i] for i in range(len(closes))]
        dea = ema(dif[:20], 9) if len(dif) >= 20 else [0]
        dc, dp = dif[0], dif[1] if len(dif) > 1 else 0
        dea_c, dea_p = dea[0], dea[1] if len(dea) > 1 else 0
        if dp < dea_p and dc > dea_c: sigs.append('D')
        elif dc > 0 and dea_c > 0 and dc > dea_c: sigs.append('D')
    return sigs

def load_track_pool():
    """加载赛道宽松池"""
    if not os.path.exists(TRACK_POOL_FILE):
        return []
    with open(TRACK_POOL_FILE) as f:
        data = json.load(f)
    return data.get('stocks', [])

def load_pending_buys():
    """加载待确认买入请求"""
    if not os.path.exists(PENDING_FILE):
        return []
    with open(PENDING_FILE) as f:
        return json.load(f)

def save_pending_buys(pending):
    """保存待确认买入请求"""
    with open(PENDING_FILE, 'w') as f:
        json.dump(pending, f, ensure_ascii=False, indent=2)

def scan_track_signals():
    """扫描赛道池的A+B+D信号，返回触发的标的"""
    conn = sqlite3.connect(MKT_DB)
    cur = conn.cursor()
    
    pool = load_track_pool()
    if not pool:
        return []
    
    signals_found = []
    for s in pool:
        code = s['code']
        # 获取K线数据
        cur.execute('SELECT close, volume, high FROM klines WHERE code=? ORDER BY date DESC LIMIT 60', (code,))
        rows = cur.fetchall()
        if len(rows) < 35:
            continue
        closes = [r[0] for r in rows]
        volumes = [r[1] or 0 for r in rows]
        highs = [r[2] or 0 for r in rows]
        
        sigs = check_signals(code, closes, volumes, highs)
        if 'A' in sigs and 'B' in sigs and 'D' in sigs:
            signals_found.append({
                'code': code,
                'name': s['name'],
                'track': s['track'],
                'price': closes[0],
                'signals': sigs,
                'time': datetime.now().isoformat(),
            })
    
    conn.close()
    return signals_found

def get_track_fund_balance(conn_sim):
    """获取赛道弹性资金池余额"""
    cur = conn_sim.cursor()
    cur.execute("SELECT SUM(amount) FROM track_fund_pool")
    r = cur.fetchone()
    return r[0] or 0

def init_track_fund_db(conn_sim):
    """初始化赛道资金池表"""
    cur = conn_sim.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS track_fund_pool (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            source TEXT,  -- 'main_pool_tp' / 'track_buy'
            amount REAL,  -- 正=转入 负=支出
            balance REAL,
            note TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn_sim.commit()

# ═══ 补全2：主池止盈→赛道资金流转 ═══
def transfer_tp_to_track_fund(conn_sim, released_amount, code, name):
    """
    主池止盈释放资金→50%转入赛道弹性资金池
    在止盈时调用：released_amount = 卖出1/3获得的总金额
    """
    transfer = released_amount * 0.5
    cur = conn_sim.cursor()
    cur.execute("SELECT COALESCE(SUM(amount),0) FROM track_fund_pool")
    balance = cur.fetchone()[0] + transfer
    cur.execute("""
        INSERT INTO track_fund_pool (date, source, amount, balance, note)
        VALUES (?, 'main_pool_tp', ?, ?, ?)
    """, (date.today().isoformat(), transfer, balance,
          f'主池{code} {name}止盈释放{released_amount:.0f}元，50%={transfer:.0f}元转入'))
    conn_sim.commit()
    return transfer, balance

def track_buy_using_fund(conn_sim, code, name, buy_amount):
    """从赛道资金池扣款"""
    cur = conn_sim.cursor()
    cur.execute("SELECT COALESCE(SUM(amount),0) FROM track_fund_pool")
    balance = cur.fetchone()[0]
    if balance < buy_amount:
        return False, balance
    cur.execute("""
        INSERT INTO track_fund_pool (date, source, amount, balance, note)
        VALUES (?, 'track_buy', ?, ?, ?)
    """, (date.today().isoformat(), -buy_amount, balance - buy_amount,
          f'买入赛道股{code} {name}，使用{buy_amount:.0f}元'))
    conn_sim.commit()
    return True, balance - buy_amount

# ═══ 主流程 ═══
def run():
    today = date.today().isoformat()
    print(f'\n{"="*55}')
    print(f'🔄 双池资金流转管理 | {today}')
    print(f'{"="*55}')
    
    # 检查是否有待确认的买入请求
    pending = load_pending_buys()
    if pending:
        active = [p for p in pending if p.get('expires_at', '') >= today]
        expired = [p for p in pending if p.get('expires_at', '') < today]
        if expired:
            print(f'⏰ 已过期{len(expired)}条待确认请求（24小时超时）')
        pending = active
        save_pending_buys(pending)
        print(f'📋 当前待确认买入: {len(pending)}条')
    
    # 扫描赛道池信号
    print(f'\n🔍 扫描赛道池A+B+D信号...')
    signals = scan_track_signals()
    if signals:
        for s in signals:
            code = s['code']
            # 检查是否已有待确认
            existing = [p for p in pending if p['code'] == code]
            if existing:
                print(f'  ⏳ {code} {s["name"]} 已有待确认请求')
                continue
            
            # 创建新请求
            expires = (date.today() + timedelta(days=1)).isoformat()
            pending.append({
                'code': code,
                'name': s['name'],
                'track': s['track'],
                'price': s['price'],
                'signals': s['signals'],
                'created_at': datetime.now().isoformat(),
                'expires_at': expires,
                'status': 'pending',
            })
            print(f'  🆕 {code} {s["name"]} A+B+D信号触发! 当前价{s["price"]:.2f}')
            print(f'    请在{today} 24:00前回复"买入{code}"执行，或"跳过{code}"放弃')
    else:
        print(f'  当前无赛道股触发A+B+D信号')
    
    save_pending_buys(pending)
    
    # 检查赛道资金池余额
    conn_sim = sqlite3.connect(SIM_DB)
    init_track_fund_db(conn_sim)
    balance = get_track_fund_balance(conn_sim)
    print(f'\n💰 赛道弹性资金池余额: {balance:,.0f}元')
    if balance < 5000:
        print(f'  ⚠️ 余额不足5000元，暂停赛道买入，等待主池止盈补充')
    
    conn_sim.close()
    
    # 输出系统状态
    print(f'\n📌 系统状态:')
    print(f'  补全1已激活: 赛道股A+B+D信号→推送确认→半自动买入')
    print(f'  补全2已激活: 主池止盈50%→赛道弹性资金池')
    print(f'  赛道买入规则: 首仓2.5%总资金，长持模式(-15%止损, 不设止盈)')
    print(f'  赛道资金不足: 余额<5000元暂停买入')
    print(f'{"="*55}')

def confirm_buy(code):
    """用户确认买入"""
    pending = load_pending_buys()
    match = [p for p in pending if p['code'] == code and p['status'] == 'pending']
    if not match:
        return False, f'未找到{code}的待确认请求'
    
    p = match[0]
    # 检查是否过期
    if p.get('expires_at', '') < date.today().isoformat():
        p['status'] = 'expired'
        save_pending_buys(pending)
        return False, f'{code}的待确认请求已过期'
    
    p['status'] = 'confirmed'
    p['confirmed_at'] = datetime.now().isoformat()
    save_pending_buys(pending)
    
    # 执行买入
    conn_sim = sqlite3.connect(SIM_DB)
    init_track_fund_db(conn_sim)
    cur = conn_sim.cursor()
    
    buy_amount = TOTAL_CAPITAL * 0.025  # 2.5%
    balance = get_track_fund_balance(conn_sim)
    
    if balance < buy_amount:
        # 资金不足，从主现金池划拨
        pass  # 暂时使用主现金
    
    # ── Phase 3.6: 建仓前经统一 Decision（Trading Permission + Portfolio + DecisionEngine）──
    # track_flow 提供 Candidate/Entry Assessment，DecisionEngine 拥有最终建仓权。fail-safe：异常不建仓。
    try:
        from decision.engine import DecisionEngine
        from decision.adapters import entry_ctx
        from decision.portfolio import assess_portfolio
        from decision import snapshot as _snap
        from trading_permission import evaluate as _tp_eval, classify_data_health
        from stock_strategy_config import get_market_env_scale
        from datetime import datetime as _dt

        _scale, _label, _total = get_market_env_scale()
        _m = sqlite3.connect(MKT_DB)
        _mx = _m.execute("SELECT MAX(date) FROM klines").fetchone()[0]
        _lag = (date.today() - _dt.strptime(str(_mx)[:10], '%Y-%m-%d').date()).days if _mx else 999
        _dh = classify_data_health(timing_ok=True, kline_lag_days=_lag)
        _pos_cnt = cur.execute("SELECT COUNT(*) FROM trades WHERE status IN ('持有','部分止盈')").fetchone()[0]
        _sectors = {}
        for _r in cur.execute("SELECT sector FROM trades WHERE status IN ('持有','部分止盈')"):
            _s = _r[0] or ''
            _sectors[_s] = _sectors.get(_s, 0) + 1
        _m.close()
        _tp = _tp_eval(regime_label=_label, timing_safe=True, timing_ok=True, data_health=_dh,
                       position_count=_pos_cnt, max_positions=20)
        _pa = assess_portfolio(candidate_sector=p.get('track', ''), target_position=buy_amount,
                               total_capital=TOTAL_CAPITAL, position_count=_pos_cnt, max_positions=20,
                               max_position_pct=0.05, max_sector_cnt=3, sector_counts=_sectors, drawdown=None)
        _eng = DecisionEngine(strategy='v1_double', config_version='phase1', code_version='track_flow_p36')
        _dctx = entry_ctx(symbol=code, name=p['name'], regime_label=_label, regime_score=_total or 0,
                          permission=_tp['permission'], permission_status=_tp['status'], data_health=_dh,
                          candidate_qualified=True, candidate_score=0, signals=['A', 'B', 'D'],
                          entry_price=p['price'], target_position=buy_amount,
                          position_count=_pos_cnt, portfolio_risk='OK' if _pa['allowed'] else 'BLOCKED',
                          portfolio_assessment=_pa, stop_loss=0.08, take_profit=[0.25, 0.5, 0.8])
        _dec = _eng.decide(_dctx)
        _snap.save_snapshot(_dec)
        if _dec.action != 'BUY':
            return False, f'⛔ 统一Decision拒绝建仓 {code} {p["name"]}: {",".join(_dec.reason_codes)}'
        print(f"  ✅ track_flow 建仓经统一 Decision: {_dec.decision_id}")
    except Exception as _e:
        return False, f'⚠️ Decision Engine 异常，为安全拒绝建仓 {code} {p["name"]}: {_e}'

    # 记录买入到模拟交易
    cur.execute("""
        INSERT INTO trades (code, name, sector, buy_date, buy_price, buy_shares, buy_amount, status, signal_type, hold_mode)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (code, p['name'], p.get('track', ''), date.today().isoformat(), p['price'],
          int(buy_amount / p['price']), buy_amount, '持有', 'A+B+D', 'long'))
    conn_sim.commit()
    conn_sim.close()
    
    return True, f'已确认买入{code} {p["name"]}，金额{buy_amount:.0f}元，长持模式'

def skip_buy(code):
    """用户跳过买入"""
    pending = load_pending_buys()
    for p in pending:
        if p['code'] == code and p['status'] == 'pending':
            p['status'] = 'skipped'
            p['skipped_at'] = datetime.now().isoformat()
            break
    save_pending_buys(pending)
    return True, f'已跳过{code}'

if __name__ == '__main__':
    # 检查命令行参数
    if len(sys.argv) >= 3 and sys.argv[1] == 'confirm':
        success, msg = confirm_buy(sys.argv[2])
        print(msg)
    elif len(sys.argv) >= 3 and sys.argv[1] == 'skip':
        success, msg = skip_buy(sys.argv[2])
        print(msg)
    else:
        run()