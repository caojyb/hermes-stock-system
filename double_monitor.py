#!/usr/bin/env python3
"""
翻倍策略监控系统 — 收盘信号扫描 + 止盈止损 + 仓位管理 + 模拟交易 + 新股虹吸
=====================================================
每日15:00后执行一次，输出信号扫描结果和持仓提醒

用法:
  python3 double_monitor.py                    # 正常扫描
  python3 double_monitor.py --force-sell       # 强制输出所有持仓状态
"""
import os, sys, json, sqlite3, requests, time, socket
from datetime import date, datetime, timedelta
from collections import defaultdict
from pathlib import Path

socket.setdefaulttimeout(10)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / 'skills/stock/stock-expert'))
from stock_db_paths import get_db_path
MARKET_DB = str(get_db_path('market_cache'))
SIM_DB = str(get_db_path('simulation'))
SIM_TEST_DB = str(get_db_path('simulation_test'))
# P2-2: 模拟仓交易标记策略来源
from stock_strategy_config import DEFAULT_STRATEGY
# 2026-08-18: 市场环境 → 仓位缩放（高波动/低量能环境自动收紧单笔建仓）
from stock_strategy_config import get_market_env_scale
ENV_SCALE, ENV_LABEL, ENV_TOTAL = get_market_env_scale()
print(f"📊 市场环境: {ENV_LABEL or '未知'} | 总分: {ENV_TOTAL if ENV_TOTAL is not None else 'N/A'} | 建仓缩放: {ENV_SCALE:.2f}")

# ═══ Phase 2: Unified Decision（唯一拍板 + 冻结 + 回放）═══
# decision 是 scripts/cron/decision 包，double_monitor 与它同目录
from decision.engine import DecisionEngine
from decision.adapters import entry_ctx, position_ctx, norm_exit_signal
from decision.portfolio import assess_portfolio
from decision import snapshot as decision_snapshot
decision_engine = DecisionEngine(
    strategy=DEFAULT_STRATEGY, config_version='phase1',
    code_version='double_monitor_p2',
)

# ═══ 模拟交易运行模式 ═══
# 生产模式：只记录真实策略信号交易到 simulation.db
# 测试模式：仅写入 simulation_test.db，不污染生产库
SIM_MODE = os.getenv("SIM_MODE", "production").strip().lower()
if SIM_MODE not in ("production", "test"):
    SIM_MODE = "production"
ACTIVE_SIM_DB = SIM_TEST_DB if SIM_MODE == "test" else SIM_DB

# ═══ 模拟交易规则 ═══
TOTAL_CAPITAL = 1_000_000
FIRST_POSITION = 0.025
MAX_POSITION = 0.05
STOP_LOSS = 0.08
TP1, TP2, TP3 = 0.25, 0.50, 0.80
PEAK_RETRACE = 0.08
LARGE_IPO_THRESHOLD = 50_000_000_000  # 500亿
SUSPEND_DAYS = 3

# ═══ 规则 ═══
STOP_LOSS = 0.08
TP1, TP2, TP3 = 0.25, 0.50, 0.80
PEAK_RETRACE = 0.08
MAX_SINGLE_PCT = 0.05
FIRST_POSITION_PCT = 0.025
MAX_SECTOR_CNT = 3

SIGNAL_LABELS = {
    'A': '站上20日均线+均线拐头',
    'B': '倍量启动(3日/10日均量>1.8)',
    'C': '创20日新高',
    'D': 'MACD零轴上方金叉',
}

def load_watch_list() -> list[dict]:
    """从 double_up_scores 读取最新一期评分，按总分降序返回监控标的。"""
    con = sqlite3.connect(MARKET_DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("SELECT MAX(scan_date) FROM double_up_scores")
    row = cur.fetchone()
    if not row or row[0] is None:
        return []
    max_scan_date = row[0]
    cur.execute("""
        SELECT code, name, sector, total_score
        FROM double_up_scores
        WHERE scan_date = ?
        ORDER BY total_score DESC
    """, (max_scan_date,))
    watch_list = []
    for r in cur.fetchall():
        watch_list.append({
            'code': r['code'],
            'name': r['name'],
            'sector': r['sector'] or '',
            'entry_price': 0,
        })
    # 从 simulation.db 补录真实买入价，避免止盈止损死代码
    try:
        sim_db = str(get_db_path('simulation'))
        sim_con = sqlite3.connect(sim_db)
        sim_cur = sim_con.cursor()
        sim_cur.execute("""
            SELECT code, buy_price FROM trades
            WHERE status IN ('持有','部分止盈')
              AND buy_price IS NOT NULL AND buy_price > 0
        """)
        entry_map = {row[0]: row[1] for row in sim_cur.fetchall()}
        sim_con.close()
        for s in watch_list:
            if s['entry_price'] == 0 and s['code'] in entry_map:
                s['entry_price'] = entry_map[s['code']]
    except Exception:
        pass
    con.close()
    return watch_list

# 日期健康检查累计计数（用于连续 3 周期告警）—— 已改为落库持久化（alert_counters 表）
# 保留空 dict 作为兼容占位，实际计数读写 simulation.db 的 alert_counters 表
date_health_counter: dict[str, dict] = {}

# ── alert_counters 落库持久化（P1-1）：跨 run 保留连续异常计数 ──
def _alert_conn():
    return sqlite3.connect(ACTIVE_SIM_DB, timeout=60)

def _ensure_alert_counters_table():
    conn = _alert_conn()
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS alert_counters (
        counter_name TEXT PRIMARY KEY,
        current_count INTEGER DEFAULT 0,
        threshold INTEGER DEFAULT 3,
        first_seen TEXT,
        last_seen TEXT,
        reason TEXT,
        alerted INTEGER DEFAULT 0,
        last_updated TEXT
    )''')
    conn.commit()
    conn.close()

def get_alert_counter(counter_name):
    """读取某只股票的连续异常计数。返回 dict，不存在时返回默认值。"""
    _ensure_alert_counters_table()
    conn = _alert_conn()
    cur = conn.cursor()
    cur.execute('SELECT current_count, threshold, first_seen, last_seen, reason, alerted FROM alert_counters WHERE counter_name=?', (counter_name,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return {'counter_name': counter_name, 'current_count': 0, 'threshold': 3,
                'first_seen': None, 'last_seen': None, 'reason': None, 'alerted': 0}
    return {'counter_name': counter_name, 'current_count': row[0], 'threshold': row[1],
            'first_seen': row[2], 'last_seen': row[3], 'reason': row[4], 'alerted': row[5]}

def increment_alert_counter(counter_name, reason, threshold=3):
    """连续异常计数 +1，返回 (累计次数, 是否已告警)。跨 run 持久化。"""
    _ensure_alert_counters_table()
    conn = _alert_conn()
    cur = conn.cursor()
    now = datetime.now().isoformat()
    cur.execute('''INSERT INTO alert_counters (counter_name, current_count, threshold, first_seen, last_seen, reason, alerted, last_updated)
                   VALUES (?, 1, ?, ?, ?, ?, 0, ?)
                   ON CONFLICT(counter_name) DO UPDATE SET
                     current_count = current_count + 1,
                     last_seen = ?,
                     reason = ?,
                     last_updated = ?''',
                (counter_name, threshold, now, now, reason, now, now, reason, now))
    conn.commit()
    cur.execute('SELECT current_count, alerted FROM alert_counters WHERE counter_name=?', (counter_name,))
    count, alerted = cur.fetchone()
    conn.close()
    return count, alerted

def reset_alert_counter(counter_name):
    """股票恢复正常后清除计数。"""
    _ensure_alert_counters_table()
    conn = _alert_conn()
    cur = conn.cursor()
    cur.execute('DELETE FROM alert_counters WHERE counter_name=?', (counter_name,))
    conn.commit()
    conn.close()

def mark_alerted(counter_name):
    """标记该计数已告警（不重复告警直到重置）。"""
    _ensure_alert_counters_table()
    conn = _alert_conn()
    cur = conn.cursor()
    cur.execute('UPDATE alert_counters SET alerted=1, last_updated=? WHERE counter_name=?', (datetime.now().isoformat(), counter_name))
    conn.commit()
    conn.close()


def validate_klines_health(code: str, klines: list[dict]) -> tuple[bool, str]:
    """
    校验 K 线健康度：
    1. 数据新鲜度：最新日期落后系统当前日期超过 3 个交易日则视为停更
    2. 未来日期：存在 date > 系统当前日期 + 1 天则视为数据异常
    返回 (是否健康, 不健康原因)
    """
    if not klines:
        return False, "klines 为空"

    today = date.today()
    latest_date_str = klines[-1]['date']
    try:
        latest_date = datetime.strptime(latest_date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return False, f"latest_date 解析失败: {latest_date_str}"

    # 1. 数据新鲜度：超过 3 个交易日未更新
    data_lag = (today - latest_date).days
    if data_lag > 3:
        return False, f"K线数据停更，最新日期 {latest_date_str}，落后 {data_lag} 天"

    # 2. 未来日期校验
    future_threshold = today + timedelta(days=1)
    for k in klines:
        d_str = k['date']
        try:
            d = datetime.strptime(d_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            continue
        if d > future_threshold:
            return False, f"K线存在未来日期 {d_str}"

    return True, ""

WATCH_LIST = load_watch_list()

# ═══ 管道健康检查 ═══
try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
    from pipeline_status import check_upstream, record_status
    # 检查上游数据新鲜度
    check_upstream('daily-data-refresh', max_age_minutes=180)
    check_upstream('stock-market-cache-refresh', max_age_minutes=180)
    PIPELINE_AVAILABLE = True
except Exception as e:
    print(f'  [PIPELINE] pipeline_status 不可用: {e}')
    PIPELINE_AVAILABLE = False

conn = sqlite3.connect(str(MARKET_DB), timeout=60)  # 60s busy timeout，避免与 market-cache 并发写冲突
conn.row_factory = sqlite3.Row
cur = conn.cursor()

today = date.today()
lookback = (today - timedelta(days=400)).isoformat()
today_str = today.isoformat()

# ── 交易日/数据就绪语义分离（Phase 8-G0 / CALENDAR_INFRA_FIX）──
# 修复：不再用"有无当日K线"反推交易日（会把"行情未刷新"误判为"非交易日"）。
# 现在区分：TRADING_DAY（日历工作日）与 MARKET_DATA_READY（当日K线是否刷新）。
try:
    from trading_calendar import classify_trading_day, is_buy_eligible
    try:
        cur.execute("SELECT COUNT(*) FROM klines WHERE date=?", (today_str,))
        today_kline_count = cur.fetchone()[0]
        cur.execute("SELECT MAX(date) FROM klines")
        latest_kline_row = cur.fetchone()
        latest_kline_date = latest_kline_row[0] if latest_kline_row else None
    except Exception:
        today_kline_count = 0
        latest_kline_date = None
    _cal = classify_trading_day(today, today_kline_count, latest_kline_date)
    IS_TRADING_DAY = is_buy_eligible(today, today_kline_count)
    if not IS_TRADING_DAY:
        print(f"  ⚠️ {_cal['message']}")
except Exception as e:
    # 兜底：保持原行为（当天有K线才算交易日），不因日历模块故障改变买入行为
    try:
        cur.execute("SELECT COUNT(*) FROM klines WHERE date=?", (today_str,))
        today_kline_count = cur.fetchone()[0]
    except Exception:
        today_kline_count = 0
    IS_TRADING_DAY = today_kline_count > 0
    if not IS_TRADING_DAY:
        print(f"  ⚠️ 今日 {today_str} 非交易日（无当日 K 线），跳过买入信号扫描，仅监控持仓与出摘要")

# 价格异常连续计数（用于连续 3 周期告警）
price_anomaly_counter: dict[str, dict] = {}

print(f"📊 翻倍策略监控系统")
print(f"   扫描日期: {today_str}")
print(f"   监控标的: {len(WATCH_LIST)} 只")
print(f"   {'='*50}")

# ── 行业归属检查（任务三） ──
sector_counts = defaultdict(int)
for s in WATCH_LIST:
    sector_counts[s['sector']] += 1
print(f"\n📋 行业分布:")
for sector, cnt in sorted(sector_counts.items(), key=lambda x: -x[1]):
    stocks = [s['name'] for s in WATCH_LIST if s['sector'] == sector]
    warn = " ⚠️超限" if cnt > MAX_SECTOR_CNT else ""
    print(f"   {sector}: {cnt}只 {stocks}{warn}")

# ── 板块强度计算（任务三） ──
def calc_sector_strength(cur, sector_name):
    """计算某行业站上20日均线的个股占比"""
    cur.execute("SELECT code FROM stocks WHERE sector=? AND sector IS NOT NULL AND sector!=''", (sector_name,))
    codes = [r[0] for r in cur.fetchall()]
    if not codes:
        return 0.0
    above = 0
    total = 0
    for code in codes:
        cur.execute("SELECT close FROM klines WHERE code=? ORDER BY date DESC LIMIT 20", (code,))
        rows = [r[0] for r in cur.fetchall()]
        if len(rows) < 20:
            continue
        total += 1
        closes_rev = rows[::-1]  # 从旧到新
        ma20 = sum(closes_rev) / 20
        if rows[0] > ma20:  # 最新收盘价 > 20日均线
            above += 1
    return above / total if total > 0 else 0.0

# 预计算板块强度
print(f"\n📊 板块强度扫描...")
sector_strength_cache = {}
for stock in WATCH_LIST:
    # 从DB获取实际行业归属
    cur.execute("SELECT sector FROM stocks WHERE code=?", (stock['code'],))
    actual_sector_row = cur.fetchone()
    actual_sector = actual_sector_row[0] if actual_sector_row else stock['sector']
    stock['actual_sector'] = actual_sector
    if actual_sector not in sector_strength_cache:
        strength = calc_sector_strength(cur, actual_sector)
        sector_strength_cache[actual_sector] = strength
        print(f"   {actual_sector}: {strength*100:.0f}% 站上20日均线 {'✅强势' if strength > 0.60 else '❌弱势'}")

# ── 个股北向资金数据更新（提前到评级打印前，用于推荐降级真实生效） ──
print(f"\n{'='*55}")
print("📊 个股北向资金更新")
print(f"{'='*55}")
north_risk_map = {}
try:
    from northbound_stock import run as north_run
    _pool_codes = [s['code'] for s in WATCH_LIST]
    _analysis = north_run(pool_codes=_pool_codes)
    if _analysis:
        for _r in _analysis:
            if _r.get('risk'):
                north_risk_map[_r['code']] = _r['risk']
except Exception as e:
    print(f"   北向数据更新失败: {e}")

# ── 数据升级风险预取（主力净流出/事件/负向景气），并入评级降级 ──
upgrade_risk_map = {}
try:
    from data_upgrade import format_candidate_risk
    _dup_pool = [{'code': s['code'], 'name': s['name'], 'sector': s.get('sector', '')} for s in WATCH_LIST]
    _enriched = format_candidate_risk(_dup_pool)
    for _s in _enriched:
        _downgrade_flags = []
        for _f in _s.get('risk_flags', []):
            if _f.startswith('北向流出'):
                continue  # 北向已由 north_risk_map 单独处理
            if ('流出' in _f) or ('减持' in _f) or ('解禁' in _f) or ('质押' in _f):
                _downgrade_flags.append(_f)
            elif _f.startswith('景气') and ('👎' in _f or '❌' in _f):
                _downgrade_flags.append(_f)
        if _downgrade_flags:
            upgrade_risk_map[_s['code']] = ' | '.join(_downgrade_flags)
except Exception as e:
    print(f"   数据升级风险预取失败: {e}")

# ── 逐个扫描 ──
for i, stock in enumerate(WATCH_LIST):
    code = stock['code']
    name = stock['name']
    entry = stock['entry_price']
    
    # 获取K线
    cur.execute("SELECT date, close, volume, open, high, low FROM klines WHERE code=? AND date>=? ORDER BY date", (code, lookback))
    klines = [dict(r) for r in cur.fetchall()]
    if len(klines) < 60:
        continue
    
    # ── 日期健康校验（新鲜度 + 未来日期） ──
    date_ok, date_reason = validate_klines_health(code, klines)
    if not date_ok:
        print(f"[WARN] {code} {name} {date_reason}，跳过本轮监控")
        # 跨 run 持久化计数（alert_counters 表）
        cnt, already_alerted = increment_alert_counter(code, date_reason, threshold=3)
        if cnt >= 3 and not already_alerted:
            try:
                sys.path.insert(0, '/home/caojy/.hermes/skills/stock/stock-expert/skills/feishu-bitable')
                from feishu_sender import feishu_send_message
                counter = get_alert_counter(code)
                feishu_send_message(
                    f"⚠️ K线日期异常审核告警\n"
                    f"{code} {name} 连续 {cnt} 个监控周期日期异常\n"
                    f"原因: {date_reason}\n"
                    f"首次出现: {counter['first_seen']}\n"
                    f"请人工检查数据源"
                )
                mark_alerted(code)
            except Exception as e:
                print(f"   [ERROR] 发送飞书告警失败: {e}")
        continue
    else:
        reset_alert_counter(code)
    
    latest = klines[-1]
    price = latest['close']
    
    # ── 价格有效性熔断（防止 klines.close 异常导致止损误触发） ──
    skip_stop_loss = False
    if price is None or price <= 0:
        print(f"[WARN] {code} {name} 当前价格异常 (price={price})，停止损计算")
        skip_stop_loss = True
    
    closes = [k['close'] for k in klines]
    volumes = [k['volume'] for k in klines]
    highs = [k['high'] for k in klines]
    
    # 价格异常连续计数（跨周期持久化）
    if skip_stop_loss:
        price_anomaly_counter[code] = price_anomaly_counter.get(code, {"count": 0, "first_seen": today_str})
        price_anomaly_counter[code]["count"] += 1
        price_anomaly_counter[code]["last_seen"] = today_str
    else:
        if code in price_anomaly_counter:
            del price_anomaly_counter[code]
    
    # ── 信号检测（优先从 indicators 表读取预计算信号） ──
    signals = []
    cur.execute("SELECT signal_a, signal_b, signal_c, signal_d FROM indicators WHERE code=? ORDER BY date DESC LIMIT 1", (code,))
    sig_row = cur.fetchone()
    if sig_row and any(sig_row):
        if sig_row[0]: signals.append('A')
        if sig_row[1]: signals.append('B')
        if sig_row[2]: signals.append('C')
        if sig_row[3]: signals.append('D')
    else:
        # 兜底：indicators 表无信号时从 klines 实时计算
        # A: 站上20日均线+均线拐头
        if len(closes) >= 20:
            ma20 = sum(closes[-20:]) / 20
            ma20_prev = sum(closes[-21:-1]) / 20
            if price > ma20 and ma20 >= ma20_prev:
                signals.append('A')
        # B: 倍量启动
        if len(volumes) >= 13:
            v3 = sum(volumes[-3:])
            v10 = sum(volumes[-13:-3]) / 10
            if v10 > 0 and v3 > v10 * 1.8:
                signals.append('B')
        # C: 20日新高
        if len(highs) >= 20:
            if price >= max(highs[-20:]):
                signals.append('C')
        # D: MACD金叉
        if len(closes) >= 35:
            def ema(d, p):
                k = 2/(p+1); r = [d[0]]
                for x in d[1:]: r.append(x*k + r[-1]*(1-k))
                return r
            ef = ema(closes, 12); es = ema(closes, 26)
            dif = [ef[i]-es[i] for i in range(len(closes))]
            dea = ema(dif[-20:], 9) if len(dif)>=20 else [0]
            dc, dp = dif[-1], dif[-2] if len(dif)>=2 else 0
            dea_c, dea_p = dea[-1], dea[-2] if len(dea)>=2 else 0
            if dp < dea_p and dc > dea_c: signals.append('D')
            elif dc > 0 and dea_c > 0 and dc > dea_c: signals.append('D')

    stock['signals'] = signals
    # ── 集成分钟级盘中信号 ──
    intraday_signals = []
    intraday_db = os.path.join(os.path.dirname(__file__), 'intraday_cache.db')
    if os.path.exists(intraday_db):
        try:
            ic = sqlite3.connect(intraday_db)
            icc = ic.cursor()
            icc.execute("SELECT signal_type, triggered_at, details FROM signals WHERE code=? AND trade_date=? ORDER BY triggered_at DESC", (code, today_str))
            for row in icc.fetchall():
                intraday_signals.append({'type': row[0], 'ts': row[1], 'detail': row[2]})
            ic.close()
        except:
            pass

    # ── 输出 ──
    print(f"\n{'─'*55}")
    print(f"📌 {i+1}. {code} {name}  |  收盘价: {price:.2f}")
    sig_str = ' '.join(signals) if signals else '无'
    if intraday_signals:
        intra_sigs = sorted(set(s['type'] for s in intraday_signals))
        sig_str += f" [盘中:{'+'.join(intra_sigs)}]"
    print(f"   信号: {sig_str}")
    
    # ── 板块强度验证（任务三） ──
    actual_sector = stock.get('actual_sector', stock['sector'])
    sector_strength = sector_strength_cache.get(actual_sector, 0)
    is_strong = sector_strength > 0.60
    print(f"   板块: {actual_sector} | 强度: {sector_strength*100:.0f}%站上20日均线 {'✅强势' if is_strong else '❌弱势'}")
    
    # 推荐等级（考虑板块强度）
    if len(signals) >= 3:
        if is_strong:
            rating = '⭐⭐⭐ 强烈推荐'
        else:
            rating = '⭐⭐ 可关注'  # 板块非强势，降一档
        detail_mode = 'full'
    elif len(signals) == 2:
        if is_strong:
            rating = '⭐⭐ 可关注'
        else:
            rating = '⭐ 仅观察'  # 板块非强势，降一档
        detail_mode = 'full'
    else:
        # 1个或0个信号 → 仅显示评级，不展示详细信号描述
        rating = '⭐ 仅观察'
        detail_mode = 'minimal'

    # 北向大幅卖出 + 数据升级风险（主力净流出/事件/负向景气）→ 推荐等级降一级（真实生效，非仅日志）
    _north_risk = north_risk_map.get(code)
    _up_risk = upgrade_risk_map.get(code)
    _risks = [r for r in (_north_risk, _up_risk) if r]
    if _risks:
        if rating == '⭐⭐⭐ 强烈推荐':
            rating = '⭐⭐ 可关注'
        elif rating == '⭐⭐ 可关注':
            rating = '⭐ 仅观察'
        elif rating == '⭐ 仅观察':
            pass
        rating = f"{rating} ⛔{' | '.join(_risks)}"

    print(f"   {rating}")
    
    # 详细输出（仅2+信号展开）
    if detail_mode == 'full':
        sig_names = [SIGNAL_LABELS[s] for s in signals]
        print(f"   {'='*45}")
        print(f"   🚨【买入信号】{today_str} | {code} | {name} | {'+'.join(signals)} | {price:.2f}")
        print(f"   建议买入价=次日开盘价（参考收盘价{price:.2f}）")
        print(f"   触发条件: {', '.join(sig_names)}")
        print(f"   {'='*45}")
    else:
        # 1个信号也展示是什么信号，但不展开
        if signals:
            print(f"   信号: {', '.join(signals)}（仅1项，需2项触发）")
        else:
            print(f"   ❌ 未触发任何信号")
    
    # ── 止盈止损（仅对有买入价的） ──
    if entry > 0:
        if skip_stop_loss:
            print(f"   ⚠️ 价格异常，本期跳过止盈止损判断")
        else:
            ret = (price - entry) / entry
            max_p = max(k['high'] for k in klines)
            peak_ret = (max_p - entry) / entry
            retrace = (max_p - price) / max_p if max_p > 0 else 0
            
            print(f"   持仓: 买入价{entry:.2f} | 收益{ret*100:+.1f}% | 最高+{peak_ret*100:.1f}%")
            
            alerts = []
            if ret <= -STOP_LOSS:
                alerts.append(f"⚠️清仓止损 | {code} {name} | 买入{entry:.2f}→当前{price:.2f} | 亏损{ret*100:.1f}%")
            if ret >= TP3 or (peak_ret >= TP3 and retrace >= PEAK_RETRACE):
                alerts.append(f"🚨清仓剩余全部 | {code} {name} | 盈利{ret*100:.1f}% | 高点回落{retrace*100:.1f}%")
            elif ret >= TP2:
                alerts.append(f"⚠️再卖出1/3仓位 | {code} {name} | 盈利{ret*100:.1f}%")
            elif ret >= TP1:
                alerts.append(f"⚠️卖出1/3仓位 | {code} {name} | 盈利{ret*100:.1f}%")
            
            if alerts:
                for a in alerts:
                    print(f"   🚨 {a}")
            else:
                print(f"   ✅ 正常持有")
    
    # 连续 3 个监控周期价格异常 -> 人工审核告警
    if price_anomaly_counter.get(code, {}).get("count", 0) >= 3 and not price_anomaly_counter[code].get("alerted"):
        try:
            sys.path.insert(0, '/home/caojy/.hermes/skills/stock/stock-expert/skills/feishu-bitable')
            from feishu_sender import feishu_send_message
            feishu_send_message(
                f"⚠️ 价格异常审核告警\n"
                f"{code} {name} 连续 {price_anomaly_counter[code]['count']} 个监控周期价格异常\n"
                f"首次出现: {price_anomaly_counter[code]['first_seen']}\n"
                f"请人工检查数据源"
            )
            price_anomaly_counter[code]["alerted"] = True
        except Exception as e:
            print(f"   [ERROR] 发送飞书告警失败: {e}")
    
    # 仓位限制
    sector = stock['sector']
    same_sector = [s for s in WATCH_LIST if s['sector'] == sector and s['code'] != code]
    if same_sector:
        print(f"   同行业: {', '.join([s['name'] for s in same_sector])}")

# 模拟交易引擎
print(f"\n{'='*55}")
print("📋 模拟交易处理")
print(f"{'='*55}")

# 初始化模拟数据库
sim_conn = sqlite3.connect(ACTIVE_SIM_DB)
sim_cur = sim_conn.cursor()
print(f"🧪 模拟交易模式: {SIM_MODE}")
print(f"📂 模拟数据库: {ACTIVE_SIM_DB}")
sim_cur.execute("""
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT, name TEXT, sector TEXT,
        buy_date TEXT, buy_price REAL, buy_shares INTEGER,
        buy_amount REAL,
        sell_date TEXT, sell_price REAL, sell_amount REAL,
        profit_pct REAL, profit_amount REAL,
        status TEXT, signal_type TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        hold_mode TEXT DEFAULT 'normal'
    )
""")
sim_cur.execute("""
    CREATE TABLE IF NOT EXISTS portfolio_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT, total_value REAL, cash REAL,
        holdings_value REAL, total_return_pct REAL,
        max_drawdown_pct REAL, win_count INTEGER, loss_count INTEGER,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )
""")
sim_cur.execute("""
    CREATE TABLE IF NOT EXISTS ipo_blocks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ipo_code TEXT, ipo_name TEXT, ipo_date TEXT,
        ipo_market_cap REAL, sector TEXT,
        suspend_start TEXT, suspend_end TEXT,
        affected_stocks TEXT, active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )
""")
sim_conn.commit()

# 新股虹吸检查
print("🔍 新股虹吸扫描...")
try:
    url = "http://push2delay.eastmoney.com/api/qt/clist/get"
    params = {'pn': 1, 'pz': 50, 'po': 1, 'np': 1,
        'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
        'fltt': 2, 'invt': 2, 'fid': 'f12',
        'fs': 'm:0+t:8',
        'fields': 'f12,f14,f20,f84,f127'}
    r = requests.get(url, params=params, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
    items = r.json().get('data', {}).get('diff', [])
    for item in items:
        mcap = item.get('f20', 0) or 0
        if mcap and isinstance(mcap, (int,float)) and mcap > LARGE_IPO_THRESHOLD:
            ipo_code = item.get('f12','')
            ipo_name = item.get('f14','')
            sector = item.get('f127','')
            print(f"  🚨 大市值IPO: {ipo_name}({ipo_code}) 市值{mcap/1e8:.0f}亿 行业:{sector}")
            affected = [s for s in WATCH_LIST if s['sector'] == sector]
            if affected:
                suspend_end = date.today() + timedelta(days=SUSPEND_DAYS)
                affected_json = json.dumps([{'code':s['code'],'name':s['name']} for s in affected], ensure_ascii=False)
                sim_cur.execute("""INSERT INTO ipo_blocks (ipo_code,ipo_name,ipo_date,ipo_market_cap,sector,
                    suspend_start,suspend_end,affected_stocks) VALUES (?,?,?,?,?,?,?,?)""",
                    (ipo_code, ipo_name, today_str, mcap, sector, today_str, suspend_end.isoformat(), affected_json))
                sim_conn.commit()
                print(f"    暂缓{len(affected)}只: {', '.join([s['name'] for s in affected])}")
except Exception as e:
    print(f"  新股扫描: {e}")

# 清理过期暂缓
sim_cur.execute("UPDATE ipo_blocks SET active=0 WHERE suspend_end < ?", (today_str,))
sim_conn.commit()

# ── 模拟自动交易（基于当日信号 + 持仓检查） ──
print(f"\n{'='*55}")
print("🤖 模拟自动交易")
print(f"{'='*55}")

# ── Trading Permission Gate（Phase 1）──
# 统一大盘择时（唯一入口，消除重复调用）
# fail-safe: 择时失败 → 不再"默认允许买入"，改为安全暂停
try:
    from data_filters import check_market_timing
    market_safe, idx_close, idx_ma20, market_msg = check_market_timing()
    timing_ok = True
except Exception as e:
    print(f"  大盘择时检查失败: {e}")
    market_safe, idx_close, idx_ma20 = False, 0, 0
    market_msg = f"检查失败，为安全暂停买入（fail-safe）"
    timing_ok = False

print(f"  大盘择时: {market_msg}")

# 数据健康（关键：K线新鲜度 + timing 是否成功）
try:
    cur.execute("SELECT MAX(date) FROM klines")
    _mx = cur.fetchone()[0]
    kline_lag = (today - datetime.strptime(str(_mx)[:10], '%Y-%m-%d').date()).days if _mx else 999
except Exception:
    kline_lag = 999
from trading_permission import evaluate as tp_evaluate, classify_data_health
data_health = classify_data_health(timing_ok=timing_ok, kline_lag_days=kline_lag)
print(f"  数据健康: {data_health} (K线滞后 {kline_lag} 天)")

# 当前持仓
sim_cur.execute("SELECT code, name, buy_date, buy_price, buy_shares, status FROM trades WHERE status IN ('持有','部分止盈')")
open_rows = sim_cur.fetchall()
open_map = {r[0]: {'name': r[1], 'buy_date': r[2], 'buy_price': float(r[3]), 'shares': int(r[4]), 'status': r[5]} for r in open_rows}

# 1. 卖出检查
for code, h in list(open_map.items()):
    cur_mkt = conn.cursor()
    cur_mkt.execute("SELECT close, high FROM klines WHERE code=? ORDER BY date DESC LIMIT 1", (code,))
    row = cur_mkt.fetchone()
    if not row or row[0] is None:
        print(f"  ⚠️ {code} {h['name']} 无最新价格，跳过卖出检查")
        continue
    curr_price = float(row[0])
    recent_high = float(row[1]) if row[1] and row[1] > 0 else curr_price

    # 持仓期最高价
    cur_mkt.execute("SELECT MAX(high) FROM klines WHERE code=? AND date>=?", (code, h['buy_date']))
    max_row = cur_mkt.fetchone()
    if max_row and max_row[0] and float(max_row[0]) > recent_high:
        recent_high = float(max_row[0])

    ret = (curr_price - h['buy_price']) / h['buy_price']
    peak_ret = (recent_high - h['buy_price']) / h['buy_price'] if recent_high > h['buy_price'] else 0
    retrace = (recent_high - curr_price) / recent_high if recent_high > 0 else 0

    if ret <= -STOP_LOSS:
        # ── Phase 2: Decision Engine 归一 SELL + 冻结（Exit 不依赖 new_entry 权限）──
        try:
            _sig, _trig = norm_exit_signal(ret, peak_ret, retrace, stop_loss=STOP_LOSS,
                                           tp1=TP1, peak_retrace=PEAK_RETRACE)
            _pctx = position_ctx(symbol=code, name=h['name'], regime_label=ENV_LABEL, regime_score=ENV_TOTAL or 0,
                                 permission={}, permission_status='', data_health=data_health,
                                 exit_signal=_sig, exit_triggers=_trig, position_count=len(open_map),
                                 stop_loss=STOP_LOSS, take_profit=[TP1, TP2, TP3], trailing_stop=PEAK_RETRACE,
                                 as_of_time=today_str)
            _dec = decision_engine.decide(_pctx)
            decision_snapshot.save_snapshot(_dec)
        except Exception as _e:
            print(f"  ⚠️ Decision Engine 异常({_e})")
        sell_amount = curr_price * h['shares']
        profit = (curr_price - h['buy_price']) * h['shares']
        profit_pct = ret * 100
        sim_cur.execute("""
            UPDATE trades SET sell_date=?, sell_price=?, sell_amount=?, profit_pct=?, profit_amount=?, status=?, exit_reason=?
            WHERE code=? AND status IN ('持有','部分止盈')
        """, (today_str, curr_price, sell_amount, profit_pct, profit, '止损', 'STOP_LOSS', code))
        print(f"  🔴 止损 {code} {h['name']}: {h['buy_price']:.2f}->{curr_price:.2f} ({profit_pct:.1f}%) | {_dec.decision_id}")
        # Phase 6.6: Exit Execution + Outcome Closure（不改退出触发/参数，只归口 lifecycle）
        try:
            from decision.execution import record_sim_exit_and_outcome
            # 尽量用结构化关联；不额外改策略/参数
            eid, oid, _ = record_sim_exit_and_outcome(code, curr_price, h['shares'], 'STOP_LOSS', today_str,
                                                      decision_id=_dec.decision_id)
        except Exception as _e3:
            print(f"  ⚠️ Exit 归口失败: {_e3}")
        open_map.pop(code, None)
        continue

    if peak_ret >= TP1 and retrace >= PEAK_RETRACE:
        # ── Phase 2: Decision Engine 归一 SELL + 冻结 ──
        try:
            _sig, _trig = norm_exit_signal(ret, peak_ret, retrace, stop_loss=STOP_LOSS,
                                           tp1=TP1, peak_retrace=PEAK_RETRACE)
            _pctx = position_ctx(symbol=code, name=h['name'], regime_label=ENV_LABEL, regime_score=ENV_TOTAL or 0,
                                 permission={}, permission_status='', data_health=data_health,
                                 exit_signal=_sig, exit_triggers=_trig, position_count=len(open_map),
                                 stop_loss=STOP_LOSS, take_profit=[TP1, TP2, TP3], trailing_stop=PEAK_RETRACE,
                                 as_of_time=today_str)
            _dec = decision_engine.decide(_pctx)
            decision_snapshot.save_snapshot(_dec)
        except Exception as _e:
            print(f"  ⚠️ Decision Engine 异常({_e})")
        sell_amount = curr_price * h['shares']
        profit = (curr_price - h['buy_price']) * h['shares']
        profit_pct = ret * 100
        sim_cur.execute("""
            UPDATE trades SET sell_date=?, sell_price=?, sell_amount=?, profit_pct=?, profit_amount=?, status=?, exit_reason=?
            WHERE code=? AND status IN ('持有','部分止盈')
        """, (today_str, curr_price, sell_amount, profit_pct, profit, '清仓止盈', 'TAKE_PROFIT', code))
        print(f"  🟢 止盈 {code} {h['name']}: {h['buy_price']:.2f}->{curr_price:.2f} ({profit_pct:.1f}%) | {_dec.decision_id}")
        # Phase 6.6: Exit Execution + Outcome Closure（不改退出触发/参数，只归口 lifecycle）
        try:
            from decision.execution import record_sim_exit_and_outcome
            eid, oid, _ = record_sim_exit_and_outcome(code, curr_price, h['shares'], 'TAKE_PROFIT', today_str,
                                                      decision_id=_dec.decision_id)
        except Exception as _e3:
            print(f"  ⚠️ Exit 归口失败: {_e3}")
        open_map.pop(code, None)

sim_conn.commit()

# 2. 买入检查（非交易日跳过，避免虚假"今日买入"）
current_count = len(open_map)

# ── Trading Permission 计算（买入前，组合风险纳入 Gate，只读无副作用）──
try:
    sim_cur.execute("SELECT date, total_value FROM portfolio_snapshots WHERE date >= ? ORDER BY date DESC",
                    ((date.today() - timedelta(days=45)).isoformat(),))
    _snaps = sim_cur.fetchall()
    _real = [s for s in _snaps if not str(s[0]).startswith('cooling_') and s[1]]
    if _real:
        _high = max(s[1] for s in _real)
        _cur = _real[0][1]
        drawdown = (_high - _cur) / _high if _high else None
    else:
        drawdown = None
except Exception:
    drawdown = None
tp_result = tp_evaluate(
    regime_label=ENV_LABEL,
    timing_safe=market_safe,
    timing_ok=timing_ok,
    data_health=data_health,
    drawdown=drawdown, drawdown_limit=0.15,
    position_count=current_count, max_positions=20,
    has_positions=current_count > 0,
)
new_entry_ok = tp_result['permission']['new_entry'] == 'ALLOW'
print(f"  🚦 交易权限: {tp_result['status']} | 回撤={drawdown if drawdown is None else f'{drawdown:.1%}'} | "
      f"new={tp_result['permission']['new_entry']} add={tp_result['permission']['add_position']} "
      f"reduce={tp_result['permission']['reduce_position']} reasons={','.join(tp_result['reason_codes'])}")

# ── 过滤器预处理（Phase 1: 在买入决策前计算 filters，使过滤器真正进入买入链）──
try:
    from data_filters import check_gap_up, check_liquidity_accurate
    for stock in WATCH_LIST:
        code = stock['code']
        filters = []
        try:
            cur.execute("SELECT close, open FROM klines WHERE code=? ORDER BY date DESC LIMIT 2", (code,))
            ks = cur.fetchall()
            if len(ks) >= 2 and ks[1][0]:
                prev_close, today_open = float(ks[1][0]), float(ks[0][1] or 0)
                is_gap, gp, _ = check_gap_up(code, prev_close, today_open)
                if is_gap:
                    filters.append(f'跳空{gp}%')
            liq_pass, liq_amt, _ = check_liquidity_accurate(code)
            if not liq_pass:
                filters.append(f'流动性{liq_amt/1e4:.0f}万')
        except Exception:
            pass
        stock['filters'] = filters
except Exception as e:
    print(f"  过滤器预处理异常: {e}")

# ── Phase 3: 现有持仓行业分布（供 Portfolio Assessment 行业上限/单股上限）──
sector_counts = {}
try:
    for _r in sim_cur.execute("SELECT sector FROM trades WHERE status IN ('持有','部分止盈')"):
        _s = _r[0] or ''
        sector_counts[_s] = sector_counts.get(_s, 0) + 1
except Exception as _e:
    print(f"  组合行业统计异常: {_e}")

if new_entry_ok and current_count < 20 and IS_TRADING_DAY:
    buy_candidates = []
    for stock in WATCH_LIST:
        code = stock['code']
        if code in open_map:
            continue
        signals = stock.get('signals', [])
        if len(signals) < 2:
            continue
        if stock.get('filters'):
            continue
        buy_candidates.append(stock)

    buy_candidates.sort(key=lambda x: x.get('total_score', 0), reverse=True)
    max_new = min(20 - current_count, len(buy_candidates))

    sim_cur.execute("SELECT COALESCE(SUM(buy_amount),0) FROM trades WHERE status IN ('持有','部分止盈')")
    total_invested = sim_cur.fetchone()[0]
    available_cash = TOTAL_CAPITAL - total_invested

    for stock in buy_candidates[:max_new]:
        code = stock['code']
        name = stock['name']
        cur_mkt = conn.cursor()
        cur_mkt.execute("SELECT close FROM klines WHERE code=? ORDER BY date DESC LIMIT 1", (code,))
        row = cur_mkt.fetchone()
        if not row or not row[0] or float(row[0]) <= 0:
            continue
        entry_price = float(row[0])

        target_value = TOTAL_CAPITAL * FIRST_POSITION_PCT * ENV_SCALE
        shares = int(target_value / entry_price / 100) * 100
        if shares <= 0:
            continue
        buy_amount = entry_price * shares

        if buy_amount > available_cash:
            shares = int(available_cash / entry_price / 100) * 100
            if shares <= 0:
                continue
            buy_amount = entry_price * shares

        # ── Phase 3: Portfolio Assessment（组合前置否决：回撤/单股上限/行业上限/持仓上限）──
        try:
            _pa = assess_portfolio(
                candidate_sector=stock.get('sector', ''), target_position=buy_amount,
                total_capital=TOTAL_CAPITAL, position_count=current_count, max_positions=20,
                max_position_pct=MAX_POSITION, max_sector_cnt=MAX_SECTOR_CNT,
                sector_counts=sector_counts, drawdown=drawdown, drawdown_limit=0.15,
                liquidity_ok=True, cooldown_active=False,
            )
            _pa_risk = 'OK' if _pa['allowed'] else 'BLOCKED'
        except Exception as _e:
            _pa = {'action': 'OK', 'reason_codes': [], 'allowed': True}
            _pa_risk = 'OK'

        # ── Phase 2: 统一 Decision Engine 唯一拍板（BUY 才执行）──
        try:
            dctx = entry_ctx(
                symbol=code, name=name, regime_label=ENV_LABEL, regime_score=ENV_TOTAL or 0,
                permission=tp_result['permission'], permission_status=tp_result['status'],
                data_health=data_health,
                candidate_qualified=not stock.get('filters'), candidate_score=stock.get('total_score', 0),
                signals=stock.get('signals', []), entry_price=entry_price, target_position=buy_amount,
                drawdown=drawdown, position_count=current_count, portfolio_risk=_pa_risk,
                portfolio_assessment=_pa,
                stop_loss=STOP_LOSS, take_profit=[TP1, TP2, TP3], as_of_time=today_str,
            )
            dec = decision_engine.decide(dctx)
            decision_snapshot.save_snapshot(dec)
        except Exception as _e:
            print(f"  ⚠️ Decision Engine 异常({_e})，跳过买入 {code}")
            continue
        if dec.action != 'BUY':
            print(f"  ⛔ NO_TRADE {code} {name}: {','.join(dec.reason_codes)}")
            continue
        sim_cur.execute("""
            INSERT INTO trades (code, name, sector, buy_date, buy_price, buy_shares, buy_amount, status, signal_type, hold_mode, strategy, decision_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, '持有', ?, 'normal', ?, ?)
        """, (code, name, stock.get('sector',''), today_str, entry_price, shares, buy_amount, '+'.join(stock.get('signals',[])), DEFAULT_STRATEGY, dec.decision_id))
        available_cash -= buy_amount
        print(f"  🟢 买入 {code} {name}: {entry_price:.2f} x {shares}股 = {buy_amount:.0f}元 | {dec.decision_id}")
        # Phase 6.5: 模拟执行写入 Execution Record（关联 decision_id，不静默丢失）
        try:
            from decision.execution import record_simulation_execution
            record_simulation_execution(dec.freeze(), 'BUY', entry_price, shares, buy_amount)
        except Exception as _e2:
            print(f"  ⚠️ Execution 记录失败: {_e2}")

    sim_conn.commit()

# ── 健康检查 ──
from health_check import run_health_check
run_health_check()

# ── 数据升级 ──
print(f"\n{'='*55}")
print("📊 数据全面性升级")
print(f"{'='*55}")
from data_upgrade import run_all
run_all(candidate_pool=[{'code':s['code'],'name':s['name'],'sector':s.get('sector','')} for s in WATCH_LIST] if WATCH_LIST and hasattr(WATCH_LIST[0], 'get') else None)

# ── 四个过滤器 ──
print(f"\n{'='*55}")
print("🔍 过滤器检查")
print(f"{'='*55}")
from data_filters import run_all_filters, check_market_timing, check_gap_up, check_liquidity_accurate

# 大盘择时（复用 Trading Permission 阶段的唯一结果，不再重复调用 check_market_timing）
print(f"  📊 大盘择时: {market_msg}")

# 过滤器展示（filters 已在买入决策前由 Trading Permission 阶段计算，这里只打印结果，不重算）
for stock in WATCH_LIST:
    code = stock['code']
    filters = stock.get('filters') or []
    if filters:
        print(f"    ⏸️ {code} {stock['name']}: {'; '.join(filters)}")

# 业绩预告监控
print(f"  🔍 业绩预告扫描...")
perf_alerts = []
try:
    from data_filters import fetch_performance_warnings, save_performance_log
    ws = fetch_performance_warnings()
    if ws:
        for w in ws:
            print(f"    ⚠️ {w['name']}({w['code']}): {w['type']}")
            for s in WATCH_LIST:
                if s['code'] == w['code']:
                    perf_alerts.append(w)
                    print(f"      -> 候选池中 {s['name']}，警告: {w['type']}")
        if perf_alerts:
            save_performance_log(perf_alerts)
except Exception as e:
    print(f"    ⚠️ 业绩预告扫描异常: {e}")

if not market_safe:
    print(f"  ⚠️ 大盘弱势，今日所有买入推荐暂停")

# ═══ 双池资金流转管理 ═══
print(f"\n{'='*55}")
print(f"🔄 双池资金流转管理")
print(f"{'='*55}")
try:
    from track_flow_manager import run as track_flow_run
    track_flow_run()
except Exception as e:
    print(f"   双池管理异常: {e}")

# ═══ 模拟仓每日摘要 ═══
print(f"\n{'─'*50}")
print(f"📊 【模拟仓每日摘要】{today_str}")
print(f"{'─'*50}")
try:
    # ── 实时结算（不再读陈旧快照：portfolio_snapshots 无进程更新，改用现价实时计算）──
    # 现金 = 初始资金 + 已实现盈亏 - 当前持仓成本
    open_pos_for_cash = sim_cur.execute("SELECT buy_shares, buy_price FROM trades WHERE status IN ('持有','部分止盈')").fetchall()
    realized_pnl = sim_cur.execute("SELECT COALESCE(SUM(sell_amount - buy_amount),0) FROM trades WHERE sell_date IS NOT NULL").fetchone()[0]
    open_cost = sum((shares or 0) * (price or 0) for shares, price in open_pos_for_cash)
    cash = TOTAL_CAPITAL + float(realized_pnl) - float(open_cost)
    # 风控减仓后再刷新一次，避免刚减仓后现金仍被低估

    # 当前持仓市值 + 浮盈分布（现价 × 股数）
    mkt_cur = conn.cursor()
    sim_cur.execute("SELECT code, name, buy_shares, buy_price FROM trades WHERE status IN ('持有','部分止盈')")
    open_pos = sim_cur.fetchall()
    holdings_value = 0.0
    win_cnt = 0
    loss_cnt = 0
    for code, name, shares, buy_price in open_pos:
        mkt_cur.execute("SELECT close FROM klines WHERE code=? ORDER BY date DESC LIMIT 1", (code,))
        pr = mkt_cur.fetchone()
        if not pr or pr[0] is None:
            continue
        price = float(pr[0])
        market_val = price * shares
        holdings_value += market_val
        if market_val - buy_price * shares >= 0:
            win_cnt += 1
        else:
            loss_cnt += 1
    tv = cash + holdings_value
    trp = (tv - TOTAL_CAPITAL) / TOTAL_CAPITAL * 100
    print(f"  净值: {tv:>8,.0f} | 现金: {cash:>8,.0f} | 持仓市值: {holdings_value:>8,.0f}")
    print(f"  累计收益率: {trp:>+.2f}% | 持仓浮盈: {win_cnt}盈/{loss_cnt}亏")

    # ── 每日收盘写入真实快照（供回撤检查/图表等下游读取）──
    sim_cur.execute("DELETE FROM portfolio_snapshots WHERE date=?", (today_str,))
    # 真实回撤：相对历史峰值（含今日，快照里 total_value 一直真实）
    prev_peak = sim_cur.execute("SELECT MAX(total_value) FROM portfolio_snapshots").fetchone()[0]
    prev_peak = prev_peak if prev_peak else tv
    peak = max(prev_peak, tv)
    drawdown = (peak - tv) / peak * 100 if peak > 0 else 0.0
    sim_cur.execute(
        "INSERT INTO portfolio_snapshots (date, total_value, cash, holdings_value, "
        "total_return_pct, max_drawdown_pct, win_count, loss_count) VALUES (?,?,?,?,?,?,?,?)",
        (today_str, round(tv, 2), round(cash, 2), round(holdings_value, 2),
         round(trp, 2), round(drawdown, 2), win_cnt, loss_cnt))
    sim_conn.commit()

    # 本地输出落盘（no_agent 可观测性）
    try:
        import json as _json, os as _os
        _out_dir = _os.path.expanduser('~/.hermes/cron/output/db39df50d53e')
        _os.makedirs(_out_dir, exist_ok=True)
        _out = {
            'date': today_str,
            'total_value': round(tv, 2),
            'cash': round(cash, 2),
            'holdings_value': round(holdings_value, 2),
            'total_return_pct': round(trp, 2),
            'max_drawdown_pct': round(drawdown, 2),
            'win_count': win_cnt,
            'loss_count': loss_cnt,
        }
        with open(_os.path.join(_out_dir, f'{today_str}.json'), 'w', encoding='utf-8') as _f:
            _json.dump(_out, _f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    # 今日交易
    today_str = date.today().isoformat()
    sim_cur.execute("SELECT code, name, status, buy_price, profit_pct FROM trades WHERE buy_date=?", (today_str,))
    buys = sim_cur.fetchall()
    sim_cur.execute("SELECT code, name, status, buy_price, profit_pct FROM trades WHERE sell_date=?", (today_str,))
    sells = sim_cur.fetchall()
    if buys or sells:
        buy_names = [f"{t[1]}" for t in buys[:3]]
        sell_detail = []
        for t in sells[:3]:
            tp = t[4] or 0
            stype = "止损" if tp < 0 else "止盈"
            sell_detail.append(f"{t[1]}{stype}")
        print(f"  今日交易: {'买入 ' + str(len(buys)) + '笔(' + ','.join(buy_names) + ')' if buys else ''}"
              f"{' | ' if buys and sells else ''}"
              f"{'卖出 ' + str(len(sells)) + '笔(' + ','.join(sell_detail) + ')' if sells else ''}"
              f"{'无' if not buys and not sells else ''}")
    else:
        print(f"  今日交易: 无")

    # ── 组合回撤风控（自动执行：净值回撤超线则减仓至50%，按真实收盘价）──
    try:
        from risk_controller_v2 import check_portfolio_drawdown_v2
        rc_action, rc_msgs = check_portfolio_drawdown_v2(sim_conn)
        for rc_m in rc_msgs:
            print(f"   🚨 {rc_m}")
        if rc_action and rc_action != 'none':
            print(f"   组合回撤风控: 触发 action={rc_action}")
            # 风控减仓后重新计算现金
            open_pos_for_cash = sim_cur.execute("SELECT buy_shares, buy_price FROM trades WHERE status IN ('持有','部分止盈')").fetchall()
            realized_pnl = sim_cur.execute("SELECT COALESCE(SUM(sell_amount - buy_amount),0) FROM trades WHERE sell_date IS NOT NULL").fetchone()[0]
            open_cost = sum((shares or 0) * (price or 0) for shares, price in open_pos_for_cash)
            cash = TOTAL_CAPITAL + float(realized_pnl) - float(open_cost)
            print(f"   [RC-REFRESH] 风控后现金={cash:.0f}")
    except Exception as e:
        print(f"   [WARN] 组合回撤风控检查失败: {e}")

    # 当前持仓盈亏分布（已在上方实时结算中计算）
    print(f"  当前持仓: {len(open_pos)} 只 | 盈亏分布: 盈利 {win_cnt} 只/亏损 {loss_cnt} 只")

    # 候选池
    watch_count = len(WATCH_LIST)
    if watch_count >= 15:
        pool_status = "正常"
    elif watch_count >= 5:
        pool_status = "偏少"
    else:
        pool_status = "枯竭"
    # 获取最新 scan_date（double_up_scores 在 market_cache.db，用 conn 而非 sim_conn）
    sim_cur2 = conn.cursor()
    sim_cur2.execute("SELECT MAX(scan_date) FROM double_up_scores")
    sd = sim_cur2.fetchone()
    latest_scan = sd[0] if sd and sd[0] else "未知"
    print(f"  候选池: {watch_count} 只 ({latest_scan}扫描) | 状态: {pool_status}")
except Exception as e:
    print(f"  模拟仓摘要生成异常: {e}")
print(f"{'─'*50}")

print(f"\n✅ 完成 | {date.today()}")

# 记录管道状态
if PIPELINE_AVAILABLE:
    try:
        today_str_local = date.today().isoformat()
        record_status('double-monitor-daily', 'ok', today_str_local,
                      row_count=len(WATCH_LIST), message=f'扫描 {len(WATCH_LIST)} 只标的')
    except Exception as e:
        print(f'  [PIPELINE] 状态记录失败: {e}')

# Phase 8-E.1: 生成 Primary / Secondary 报告，不反向影响 Decision
try:
    from decision.daily_decision_contract import build_daily_report, save_daily_report
    try:
        primary_report = save_daily_report(build_daily_report())
        print(f"  [REPORT] Daily Decision Report: {primary_report.get('json_path')} / {primary_report.get('txt_path')}")
    except Exception as report_err:
        print(f"  [REPORT] Daily Decision Report 写入失败: {report_err}")
except Exception as e:
    print(f"  [REPORT] Daily Decision Report 初始化失败: {e}")

# Phase 8-G0.2: Primary Feishu Delivery（只发送已生成的 Decision，不重算）
try:
    from decision.feishu_delivery import deliver_primary_feishu_with_retry
    try:
        delivery_result = deliver_primary_feishu_with_retry(primary_report if 'primary_report' in dir() else build_daily_report(), max_retries=1)
        print(f"  [DELIVERY] Primary Feishu: status={delivery_result.get('delivery_status')} "
              f"id={delivery_result.get('delivery_id')} "
              f"retry={delivery_result.get('retry_count')} "
              f"error={delivery_result.get('error') or 'none'}")
    except Exception as delivery_err:
        print(f"  [DELIVERY] Primary Feishu 投递失败（不影响 Decision）: {delivery_err}")
except Exception as e:
    print(f"  [DELIVERY] Primary Feishu 初始化失败: {e}")

try:
    from decision.observation import save_daily_observation_report
    try:
        secondary_report = save_daily_observation_report()
        print(f"  [REPORT] Production Observation Report: {secondary_report.get('json_path')} / {secondary_report.get('txt_path')}")
    except Exception as report_err:
        print(f"  [REPORT] Production Observation Report 写入失败: {report_err}")
except Exception as e:
    print(f"  [REPORT] Production Observation Report 初始化失败: {e}")

conn.close()
print(f"\n{'='*55}")
print(f"✅ 扫描完成 | {today_str} | {len(WATCH_LIST)}只标的")
print(f"{'='*55}")