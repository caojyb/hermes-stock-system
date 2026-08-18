#!/usr/bin/env python3
"""
因子IC分析模块 v3.1 — 使用存量K线数据计算真实IC
方法：利用K线表66天数据，前45天算指标，后21天算收益
输出：IC值、ICIR、胜率、有效/失效判断，自动推送到飞书
"""

import sqlite3
import os
import sys
import json
import math
import random
from datetime import datetime
from collections import defaultdict

HERMES_DIR = os.path.expanduser("~/.hermes")
MARKET_DB = os.path.join(HERMES_DIR, "skills/stock/stock-expert/market_cache.db")

# 飞书推送目标群
FEISHU_CHAT_ID = "oc_6825e1438c41d1b7251b1698ea3be4fe"


def calc_indicators(closes):
    """从收盘价序列计算技术指标"""
    if len(closes) < 45:
        return {}

    n = len(closes)

    # RSI(14)
    rsi = None
    if n >= 15:
        gains = losses = 0
        for i in range(1, 15):
            diff = closes[-i] - closes[-i-1]
            if diff >= 0:
                gains += diff
            else:
                losses -= diff
        avg_gain = gains / 14
        avg_loss = losses / 14
        rsi = 100 - 100 / (1 + avg_gain / avg_loss) if avg_loss > 0 else 100.0

    # 布林位置(20)
    boll = None
    if n >= 20:
        recent = closes[-20:]
        ma = sum(recent) / 20
        var = sum((p - ma) ** 2 for p in recent) / 20
        std = math.sqrt(var)
        upper = ma + 2 * std
        lower = ma - 2 * std
        boll = (closes[-1] - lower) / (upper - lower) * 100 if upper != lower else 50.0

    # MACD直方图
    macd_hist = None
    if n >= 35:
        def ema(data, period):
            k = 2.0 / (period + 1)
            result = [data[0]]
            for i in range(1, len(data)):
                result.append(data[i] * k + result[-1] * (1 - k))
            return result
        ema_fast = ema(closes, 12)
        ema_slow = ema(closes, 26)
        dif = [ema_fast[i] - ema_slow[i] for i in range(len(ema_fast))]
        dea = ema(dif, 9)
        macd_hist = dif[-1] - dea[-1]

    # 均线形态
    ma5 = sum(closes[-5:]) / 5
    ma20 = sum(closes[-20:]) / 20
    ma_bullish = 1 if ma5 > ma20 else -1

    # 波动率
    returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(-19, 0)]
    avg_r = sum(returns) / len(returns)
    var_r = sum((r - avg_r) ** 2 for r in returns) / len(returns)
    volatility = math.sqrt(var_r) * 100

    return {
        'rsi_14': rsi,
        'boll_position': boll,
        'macd_hist': macd_hist,
        'ma_bullish': ma_bullish,
        'volatility_20d': volatility,
    }


def _spearman_ic(values, returns, reverse=False):
    """计算Spearman Rank IC"""
    valid = [(v, r) for v, r in zip(values, returns) if v is not None and r is not None]
    if len(valid) < 30:
        return 0.0, 0

    n = len(valid)
    sorted_by_factor = sorted(valid, key=lambda x: x[0])

    # 收益排序
    ret_sorted = sorted([r for _, r in sorted_by_factor])

    sum_d2 = 0
    for i, (fv, ret) in enumerate(sorted_by_factor):
        f_rank = i
        r_rank = ret_sorted.index(ret)
        d = f_rank - r_rank
        sum_d2 += d * d

    ic = 1 - (6 * sum_d2) / (n * (n * n - 1))
    if reverse:
        ic = -ic
    return round(ic, 4), n


def _compute_win_rate(values, returns, reverse=False):
    """
    计算因子胜率：因子排序与收益排序同向的比例。
    对每只股票，因子值排名和收益排名同在 median 以上或以下记为"胜"。
    """
    valid = [(v, r) for v, r in zip(values, returns) if v is not None and r is not None]
    if len(valid) < 30:
        return 0.0, 0

    n = len(valid)
    # 计算因子值排名和收益排名
    sorted_by_factor = sorted(valid, key=lambda x: x[0])
    sorted_by_return = sorted(valid, key=lambda x: x[1])

    # 构建排名映射
    factor_rank = {id(v): i for i, (v, r) in enumerate(sorted_by_factor)}
    return_rank = {id(v): i for i, (v, r) in enumerate(sorted_by_return)}

    median = n / 2
    wins = 0
    for v, r in valid:
        fr = factor_rank[id(v)]
        rr = return_rank[id(v)]
        # 同向：都在上半区或都在下半区
        if (fr >= median and rr >= median) or (fr < median and rr < median):
            if not reverse:
                wins += 1
        else:
            if reverse:
                wins += 1

    win_rate = round(wins / n * 100, 1)
    return win_rate, n


def _compute_icir_bootstrap(values, returns, reverse=False, n_iter=100):
    """
    通过Bootstrap重采样计算ICIR（IC的均值/标准差）。
    对截面数据有放回重采样 n_iter 次，每次计算IC，得到IC分布。
    """
    valid = [(v, r) for v, r in zip(values, returns) if v is not None and r is not None]
    if len(valid) < 30:
        return 0.0, 0

    n = len(valid)
    bootstrap_ics = []

    for _ in range(n_iter):
        # 有放回采样
        sample = [random.choice(valid) for _ in range(n)]
        s_values = [v for v, _ in sample]
        s_returns = [r for _, r in sample]
        ic, _ = _spearman_ic(s_values, s_returns, reverse)
        bootstrap_ics.append(ic)

    mean_ic = sum(bootstrap_ics) / n_iter
    std_ic = math.sqrt(sum((ic - mean_ic) ** 2 for ic in bootstrap_ics) / n_iter)
    icir = round(mean_ic / std_ic, 2) if std_ic > 0 else 0.0

    return icir, n


def _compute_group_returns(values, returns, n_groups=5):
    """按因子值分组计算每组平均收益"""
    valid = [(v, r) for v, r in zip(values, returns) if v is not None and r is not None]
    if len(valid) < n_groups * 2:
        return [], 0, 0

    n = len(valid)
    sorted_by_factor = sorted(valid, key=lambda x: x[0])
    group_size = n // n_groups

    groups = []
    for g in range(n_groups):
        start = g * group_size
        end = start + group_size if g < n_groups - 1 else n
        group = sorted_by_factor[start:end]
        avg_ret = sum(p[1] for p in group) / len(group)
        groups.append(round(avg_ret, 4))

    long_short = groups[-1] - groups[0]
    monotonic = "是" if (groups[-1] > groups[0]) else "否"

    return groups, round(long_short, 4), monotonic


def _send_feishu(text):
    """通过 feishu_sender 模块发送消息到飞书"""
    sys.path.insert(0, os.path.join(HERMES_DIR,
        "skills/stock/stock-expert/skills/feishu-bitable"))
    try:
        from feishu_sender import send_text_message
        result = send_text_message(text, receive_id=FEISHU_CHAT_ID)
        if result.get("ok"):
            print(f"\n✅ 报告已推送到飞书群")
        else:
            print(f"\n⚠️ 飞书推送结果: {result.get('error', {}).get('message', 'unknown')}")
    except Exception as e:
        print(f"\n⚠️ 飞书推送失败: {e}")


def _format_feishu_report(factor_results, cutoff_date, sample_count):
    """
    将IC分析结果格式化为飞书可读报告。
    factor_results: [(label, ic, icir, win_rate, long_short, monotonic, n, is_effective), ...]
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"📊 因子IC月报",
        f"📅 {now}  |  截面: {cutoff_date} → 未来21天  |  样本: {sample_count}只",
        "",
    ]

    # 按有效性分组
    effective = [r for r in factor_results if r[7]]
    ineffective = [r for r in factor_results if not r[7]]

    if effective:
        lines.append("🔥 有效因子 (|IC| > 0.03)")
        lines.append("")
        for label, ic, icir, wr, ls, mono, n, _ in sorted(effective, key=lambda x: -abs(x[1])):
            direction = "📈 正向" if ic > 0 else "📉 反向"
            lines.append(
                f"  {direction} {label}"
            )
            lines.append(f"    IC={ic:+.4f}   ICIR={icir}   胜率={wr}%")
            lines.append(f"    多空收益={ls:+.2f}%   单调={mono}   样本={n}")
        lines.append("")

    if ineffective:
        lines.append("❌ 失效因子 (|IC| ≤ 0.03)")
        for label, ic, icir, wr, ls, mono, n, _ in sorted(ineffective, key=lambda x: -abs(x[1])):
            lines.append(f"  {label}  IC={ic:+.4f}   ICIR={icir}   胜率={wr}%")
        lines.append("")

    # 总结
    lines.append("━" * 30)
    lines.append(f"📋 总结：有效 {len(effective)} 个  |  失效 {len(ineffective)} 个")
    if effective:
        best = effective[0]
        worst = effective[-1]
        lines.append(f"🏆 最强因子：{best[0]}  IC={best[1]:+.4f}")
        if len(effective) > 1:
            lines.append(f"  🥉 最弱有效：{worst[0]}  IC={worst[1]:+.4f}")

    return "\n".join(lines)


def analyze_factor_ic(json_output=False):
    """使用K线数据计算前45天→后21天的因子IC"""
    _print = lambda *a, **kw: None if json_output else print(*a, **kw)

    conn = sqlite3.connect(MARKET_DB)
    cur = conn.cursor()

    # 获取所有股票代码
    cur.execute("SELECT DISTINCT code FROM klines")
    all_codes = [r[0] for r in cur.fetchall()]
    _print(f"\n[1/3] 加载数据... 共 {len(all_codes)} 只股票")

    # 获取K线数据
    _print("[2/3] 加载K线数据...")
    cur.execute("SELECT code, date, close FROM klines ORDER BY code, date")
    stock_data = defaultdict(list)
    for code, date, close in cur.fetchall():
        stock_data[code].append((date, close))

    conn.close()

    # 对每只股票：前45天算指标，后21天算收益
    _print("[3/3] 计算截面IC...")

    snapshot = []
    cutoff_date = None

    for code in all_codes:
        klines = stock_data.get(code, [])
        if len(klines) < 66:  # 需要至少66天数据
            continue

        # 取前45天收盘价计算指标
        indicator_closes = [c for _, c in klines[:45]]
        factors = calc_indicators(indicator_closes)
        if not factors:
            continue

        # 后21天收益
        start_price = klines[44][1]  # 第45天收盘价
        end_price = klines[-1][1]     # 最后一天收盘价
        if start_price <= 0:
            continue
        forward_ret = (end_price - start_price) / start_price * 100

        # 记录截面日期
        if cutoff_date is None:
            cutoff_date = klines[44][0]

        snapshot.append({
            'code': code,
            'factors': factors,
            'forward_ret': forward_ret,
        })

    _print(f"   截面日期: {cutoff_date} → 未来21天")
    _print(f"   有效样本: {len(snapshot)} 只股票\n")

    if len(snapshot) < 100:
        _print("   样本不足")
        return [], []

    # 计算每个因子的截面IC
    factor_names = ['rsi_14', 'boll_position', 'macd_hist', 'ma_bullish', 'volatility_20d']
    factor_labels = {
        'rsi_14': 'RSI(14)', 'boll_position': '布林位置',
        'macd_hist': 'MACD直方图', 'ma_bullish': '均线形态',
        'volatility_20d': '波动率(20日)',
    }

    # 也计算基本面因子IC
    fin_conn = sqlite3.connect(MARKET_DB)
    fcur = fin_conn.cursor()
    fcur.execute("""
        SELECT f.code, f.roe, f.profit_growth, f.revenue_growth,
               f.debt_ratio, f.gross_margin, f.net_margin
        FROM financial_data f
        INNER JOIN (
            SELECT code, MAX(report_date) as max_date
            FROM financial_data GROUP BY code
        ) l ON f.code = l.code AND f.report_date = l.max_date
    """)
    fin_data = {}
    for row in fcur.fetchall():
        fin_data[row[0]] = {
            'roe': row[1], 'profit_growth': row[2],
            'revenue_growth': row[3], 'debt_ratio': row[4],
            'gross_margin': row[5], 'net_margin': row[6],
        }

    fcur.execute("""
        SELECT code, pe_ttm, pb_mrq FROM pe_pb_data
        WHERE fetch_date = (SELECT MAX(fetch_date) FROM pe_pb_data)
    """)
    for row in fcur.fetchall():
        if row[0] in fin_data:
            fin_data[row[0]]['pe_ttm'] = row[1]
            fin_data[row[0]]['pb_mrq'] = row[2]
    fin_conn.close()

    # 合并基本面数据
    for s in snapshot:
        fd = fin_data.get(s['code'], {})
        for k, v in fd.items():
            s['factors'][k] = v

    all_factor_names = list(factor_names) + ['roe', 'profit_growth', 'revenue_growth',
                                              'debt_ratio', 'gross_margin', 'net_margin',
                                              'pe_ttm', 'pb_mrq']
    all_factor_labels = {**factor_labels,
        'roe': 'ROE', 'profit_growth': '利润增速', 'revenue_growth': '营收增速',
        'debt_ratio': '负债率', 'gross_margin': '毛利率', 'net_margin': '净利率',
        'pe_ttm': 'PE(TTM)', 'pb_mrq': 'PB(MRQ)',
    }

    # 是否反向因子（值越小越好）
    reverse_factors = {'debt_ratio': True, 'pe_ttm': True, 'pb_mrq': True,
                       'volatility_20d': True}

    _print(f"{'因子名称':<16} {'IC值':<10} {'ICIR':<8} {'胜率':<8} {'多空收益':<12} {'单调':<6} {'样本':<8}")
    _print("=" * 70)

    effective = []
    ineffective = []
    all_factor_results = []

    for fn in all_factor_names:
        label = all_factor_labels.get(fn, fn)
        valid = [(s['factors'].get(fn), s['forward_ret']) for s in snapshot if s['factors'].get(fn) is not None]

        if len(valid) < 50:
            _print(f"{label:<16} {'数据不足':<10}")
            continue

        values = [v for v, _ in valid]
        returns = [r for _, r in valid]
        rev = reverse_factors.get(fn, False)

        # IC值
        ic, n = _spearman_ic(values, returns, reverse=rev)

        # ICIR (Bootstrap)
        icir, _ = _compute_icir_bootstrap(values, returns, reverse=rev, n_iter=100)

        # 胜率
        win_rate, _ = _compute_win_rate(values, returns, reverse=rev)

        # 分组收益
        groups, ls, mono = _compute_group_returns(values, returns)

        _print(f"{label:<16} {ic:+.4f}    {icir:<8} {win_rate:<7}% {ls:+.2f}%     {mono:<6} {n}")

        is_effective = abs(ic) > 0.03
        result_item = (label, ic, icir, win_rate, ls, mono, n, is_effective)
        all_factor_results.append(result_item)

        if is_effective:
            effective.append((label, ic, ls))
        else:
            ineffective.append((label, ic))

    _print(f"\n{'=' * 70}")
    _print(f"🔥 有效因子 (|IC| > 0.03): {len(effective)} 个")
    for name, ic, ls in sorted(effective, key=lambda x: -abs(x[1])):
        _print(f"  {name:<16} IC={ic:+.4f} 多空收益={ls:+.2f}%")

    _print(f"\n❌ 失效因子 (|IC| <= 0.03): {len(ineffective)} 个")
    for name, ic in sorted(ineffective, key=lambda x: -abs(x[1])):
        _print(f"  {name:<16} IC={ic:+.4f}")

    # 生成飞书报告
    if not json_output and all_factor_results:
        report = _format_feishu_report(all_factor_results, cutoff_date, len(snapshot))
        print("\n" + "=" * 50)
        print(report)
        # 推送到飞书
        _send_feishu(report)

    return effective, ineffective


if __name__ == "__main__":
    json_flag = "--json" in sys.argv
    effective, ineffective = analyze_factor_ic(json_output=json_flag)
    if json_flag:
        result = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "factors": {},
            "effective": [{"name": n, "ic": ic, "long_short": ls} for n, ic, ls in effective],
            "ineffective": [{"name": n, "ic": ic} for n, ic in ineffective],
        }
        for name, ic, _ in effective:
            result["factors"][name] = ic
        for name, ic in ineffective:
            result["factors"][name] = ic
        print(json.dumps(result, ensure_ascii=False, indent=2))