#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Outcome Store（Phase 6）
========================
从现有数据（simulation trades legacy / 真实持仓 / 决策）构建 Outcome，
计算 MAE/MFE、NO_TRADE Counterfactual、replay、基础统计。

原则：Observe first, learn later。不自动调参、不伪造 legacy。
"""
import json, sqlite3, os, math, glob
from datetime import datetime, timezone
from pathlib import Path

from .outcome import (Outcome, Planned, Actual, Excursion, Counterfactual,
                      gen_outcome_id, map_exit_reason,
                      OPEN, CLOSED, DECIDED, UNKNOWN,
                      SOURCE_LEGACY, SOURCE_DECISION, SOURCE_SHADOW, CF_WINDOWS)

_OUTCOME_DIR = Path(__file__).resolve().parent / 'outcomes'
_DECISION_DIR = Path(__file__).resolve().parent / 'snapshots'

MARKET_DB = '/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db'


def _conn():
    return sqlite3.connect(MARKET_DB)


def compute_mae_mfe(code, entry_date, exit_date=None):
    """持仓期间 MAE/MFE（相对入场价）。数据不足 → UNKNOWN。"""
    conn = _conn()
    rows = conn.execute("SELECT low, high FROM klines WHERE code=? AND date >= ?",
                        (code, entry_date[:10])).fetchall()
    if exit_date:
        rows = [r for r in rows]
        # 用截至 exit_date 的行
        rows = conn.execute("SELECT low, high FROM klines WHERE code=? AND date>=? AND date<=?",
                            (code, entry_date[:10], exit_date[:10])).fetchall()
    conn.close()
    if not rows:
        return Excursion(status=UNKNOWN)
    lows = [r[0] for r in rows if r[0]]
    highs = [r[1] for r in rows if r[1]]
    if not lows or not highs:
        return Excursion(status=UNKNOWN)
    # 入场价用第一条 K 线 close 近似（若无，则用 lows/highs 相对自身）
    entry = None
    conn2 = _conn()
    r0 = conn2.execute("SELECT close FROM klines WHERE code=? AND date>=? ORDER BY date LIMIT 1", (code, entry_date[:10])).fetchone()
    conn2.close()
    if r0 and r0[0]:
        entry = r0[0]
    if not entry:
        return Excursion(status=UNKNOWN)
    mae = min(lows) / entry - 1
    mfe = max(highs) / entry - 1
    return Excursion(mae=round(mae, 4), mfe=round(mfe, 4),
                     max_drawdown=round(mae, 4), max_profit=round(mfe, 4),
                     status='OK')


def build_from_trade(trade, regime=''):
    """从 simulation trades（legacy，无 decision_id）构建 CLOSED Outcome。"""
    status = (trade.get('status') or '').strip()
    is_closed = status in ('清仓止盈', '止损', '部分止盈')  # 部分止盈视为有部分退出
    o = Outcome(
        outcome_id=gen_outcome_id(),
        decision_id='',           # legacy，不伪造
        symbol=trade.get('code', ''), name=trade.get('name', ''),
        action='SELL' if is_closed else 'BUY',
        strategy=trade.get('strategy', 'v1_double') or 'v1_double',
        strategy_version='legacy',
        outcome_source=SOURCE_LEGACY,
        decision_time='', execution_time=trade.get('buy_date', '') or UNKNOWN,
        exit_time=trade.get('sell_date', '') or UNKNOWN,
        planned=Planned(),
        actual=Actual(entry_price=trade.get('buy_price') or 0,
                      exit_price=trade.get('sell_price') or 0,
                      realized_pnl=trade.get('profit_amount') or 0,
                      return_pct=trade.get('profit_pct') or 0),
        lifecycle_status=CLOSED if is_closed else OPEN,
        exit_reason=map_exit_reason([trade.get('status', '')]),
        exit_triggers=[trade.get('status', '')] if trade.get('status') else [],
        entry_regime=regime,
        decision_quality=UNKNOWN, execution_quality=UNKNOWN,
    )
    # MAE/MFE
    if trade.get('buy_date'):
        o.excursion = compute_mae_mfe(trade.get('code', ''), trade['buy_date'],
                                      trade.get('sell_date'))
    return o


def build_open_from_real(pos, snapshot, regime=''):
    """从真实持仓（Bitable）构建 OPEN Outcome。"""
    entry = pos.get('avg_cost') or 0
    o = Outcome(
        outcome_id=gen_outcome_id(),
        decision_id='', symbol=pos.get('code', ''), name=pos.get('name', ''),
        action='HOLD', strategy='v1_double', strategy_version='real_holdings',
        outcome_source=SOURCE_LEGACY,
        execution_time=pos.get('buy_date', '') or UNKNOWN,
        planned=Planned(entry_price=entry),
        actual=Actual(entry_price=entry, position_size=pos.get('quantity') or 0,
                      exit_price=pos.get('current_price') or 0),
        lifecycle_status=OPEN,
        portfolio_snapshot_id=snapshot.get('snapshot_id', '') if snapshot else '',
        entry_regime=regime,
        decision_quality=UNKNOWN, execution_quality=UNKNOWN,
    )
    if pos.get('buy_date'):
        o.excursion = compute_mae_mfe(pos.get('code', ''), pos['buy_date'])
    return o


def build_from_decision(decision, symbol='', action='', regime=''):
    """从统一 Decision（有 decision_id）构建 Outcome。
    BUY/ADD/SELL → DECIDED；NO_TRADE → 附 counterfactual（由调用方补）。"""
    a = action or decision.get('action', '')
    o = Outcome(
        outcome_id=gen_outcome_id(),
        decision_id=decision.get('decision_id', ''),
        symbol=symbol or decision.get('symbol', ''), name=decision.get('name', ''),
        action=a, strategy=decision.get('strategy', 'v1_double'),
        strategy_version=decision.get('config_version', ''),
        outcome_source=SOURCE_DECISION,
        decision_time=decision.get('timestamp', ''),
        as_of_time=decision.get('as_of_time', ''),
        planned=Planned(entry_price=decision.get('reference_price', 0),
                        target_position=decision.get('target_position', 0)),
        lifecycle_status=DECIDED,
        entry_regime=regime or decision.get('regime_label', ''),
        decision_snapshot_id=decision.get('data_snapshot_id', ''),
        portfolio_snapshot_id=decision.get('portfolio_snapshot_id', ''),
        config_version=decision.get('config_version', ''),
        code_version=decision.get('code_version', ''),
        decision_quality=UNKNOWN, execution_quality=UNKNOWN,
    )
    return o


def compute_counterfactual(code, decision_date, entry_price, windows=CF_WINDOWS):
    """NO_TRADE Counterfactual：如果当时交易，后 N 日窗口 hypothetical 结果。
    仅研究数据，非真实交易。"""
    conn = _conn()
    rows = conn.execute("SELECT date, close FROM klines WHERE code=? AND date>=? ORDER BY date",
                        (code, decision_date[:10])).fetchall()
    conn.close()
    results = []
    if not rows or entry_price <= 0:
        for w in windows:
            results.append(Counterfactual(eligible=False, horizon=w, status='NOT_ELIGIBLE'))
        return results
    closes = [r[1] for r in rows if r[1]]
    for w in windows:
        seg = closes[1:w+1]  # 决策后第1~w日
        if len(seg) < w:
            results.append(Counterfactual(eligible=False, horizon=w, status='NOT_ELIGIBLE'))
            continue
        ret = seg[-1] / entry_price - 1
        mae = min(seg) / entry_price - 1
        mfe = max(seg) / entry_price - 1
        results.append(Counterfactual(eligible=True, horizon=w,
                                      hypothetical_entry_price=entry_price,
                                      hypothetical_position=0.0,
                                      hypothetical_return=round(ret, 4),
                                      hypothetical_mae=round(mae, 4),
                                      hypothetical_mfe=round(mfe, 4),
                                      status='COMPUTED'))
    return results


def save_outcome(outcome):
    """存不可变 Outcome snapshot（JSON 文件）。"""
    _OUTCOME_DIR.mkdir(parents=True, exist_ok=True)
    path = _OUTCOME_DIR / f"{outcome.outcome_id}.json"
    with open(path, 'w') as f:
        json.dump(outcome.freeze(), f, ensure_ascii=False, indent=2, default=str)
    return str(path)


def replay(outcome_id):
    """给定 outcome_id，恢复 Outcome + 关联 Decision Snapshot。"""
    path = _OUTCOME_DIR / f"{outcome_id}.json"
    if not path.exists():
        return {'ok': False, 'error': f'outcome 不存在: {outcome_id}'}
    o = json.load(open(path))
    decision = None
    if o.get('decision_id'):
        dp = _DECISION_DIR / f"{o['decision_id']}.json"
        if dp.exists():
            decision = json.load(open(dp))
    return {'ok': True, 'outcome': o, 'decision': decision,
            'decision_snapshot_id': o.get('decision_snapshot_id', ''),
            'portfolio_snapshot_id': o.get('portfolio_snapshot_id', '')}


def load_all():
    """加载全部 Outcome 记录。"""
    outs = []
    for f in glob.glob(str(_OUTCOME_DIR / '*.json')):
        try:
            outs.append(json.load(open(f)))
        except Exception:
            pass
    return outs


def stats(outcomes=None):
    """基础统计（不 ML）：count/winrate/avg/median/profit factor/By Exit/By Strategy/By Regime。"""
    outcomes = outcomes if outcomes is not None else load_all()
    closed = [o for o in outcomes if o.get('lifecycle_status') == CLOSED]
    stats_out = {'total': len(outcomes), 'closed': len(closed)}
    rets = [o['actual'].get('return_pct', 0) for o in closed]
    if rets:
        wins = [r for r in rets if r > 0]
        losses = [r for r in rets if r < 0]
        wins_pct = [r for r in rets if r > 0]
        stats_out['win_rate'] = round(len(wins) / len(rets), 4)
        stats_out['avg_return'] = round(sum(rets) / len(rets), 4)
        stats_out['median_return'] = round(sorted(rets)[len(rets)//2], 4)
        gp = sum(wins) if wins else 0
        gl = abs(sum(losses)) if losses else 0
        stats_out['profit_factor'] = round(gp / gl, 4) if gl else None
        stats_out['max_return'] = round(max(rets), 4)
        stats_out['min_return'] = round(min(rets), 4)
    # By Exit Reason
    by_exit = {}
    for o in closed:
        r = o.get('exit_reason', UNKNOWN)
        by_exit.setdefault(r, []).append(o['actual'].get('return_pct', 0))
    stats_out['by_exit_reason'] = {k: {'count': len(v), 'avg_return': round(sum(v)/len(v), 4)}
                                   for k, v in by_exit.items()}
    # By Strategy
    by_strategy = {}
    for o in outcomes:
        s = o.get('strategy', UNKNOWN)
        by_strategy.setdefault(s, []).append(o['actual'].get('return_pct', 0) if o.get('lifecycle_status') == CLOSED else None)
    stats_out['by_strategy'] = {k: {'closed_count': sum(1 for x in v if x is not None)}
                                for k, v in by_strategy.items()}
    # By Regime
    by_regime = {}
    for o in closed:
        r = o.get('entry_regime', UNKNOWN) or UNKNOWN
        by_regime.setdefault(r, []).append(o['actual'].get('return_pct', 0))
    stats_out['by_regime'] = {k: {'count': len(v), 'avg_return': round(sum(v)/len(v), 4)}
                              for k, v in by_regime.items()}
    return stats_out
