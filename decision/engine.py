#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Decision Engine — 唯一拍板（Phase 2）

职责：收集各模块的 Assessment（Candidate/MarketRegime/TradingPermission/
EntryAssessment/RiskAssessment/ExitAssessment），校验完整性，应用显式冲突
优先级，归一为唯一 BUY/HOLD/SELL/NO_TRADE，生成 Decision + reason_codes。

原则（Decision Engine 是裁判，不是选手）：
- 不重新发明选股/择时/仓位/卖出规则。
- 不偷偷新增技术指标 / 新选股条件 / 新 Regime 算法 / 新止盈策略。
- Position Sizing / Exit Assessment 由底层模块产生，本引擎只接收、校验、纳入。
"""
from __future__ import annotations

from .contract import (
    BUY, HOLD, SELL, NO_TRADE, REDUCE, ADD,
    REASON, ENTRY_CONFIRMED, ENTRY_INSUFFICIENT, ENTRY_NONE,
    EXIT_NONE, EXIT_NORMAL, EXIT_RISK, EXIT_FORCED,
    RISK_OK, RISK_BLOCKED, CANDIDATE_QUALIFIED, CANDIDATE_FAIL,
    Decision, gen_decision_id,
)

# 关键数据健康等级（与 trading_permission 对齐）
_DATA_CRITICAL = {'INVALID', 'MISSING'}
_DATA_STALE = {'STALE'}


class DecisionEngine:
    """统一决策入口。所有最终 BUY/HOLD/SELL/NO_TRADE 都经过这里。"""

    def __init__(self, *, config_version='', code_version='', strategy='v1_double', strategy_version=''):
        self.config_version = config_version
        self.code_version = code_version
        self.strategy = strategy
        self.strategy_version = strategy_version

    def decide(self, ctx: dict) -> Decision:
        """核心裁决。ctx 为各模块 Assessment 的统一输入。

        ctx 关键字段（调用方采集）:
          symbol, name, mode('entry'|'position'), has_position
          regime_label, regime_score, regime_version
          permission: dict, permission_status: str
          data_health: str
          candidate_qualified, candidate_score, candidate_rank
          entry_signal: str, entry_signals: list
          reference_price, target_position
          drawdown, position_count, current_exposure
          stop_loss, take_profit(list), trailing_stop, risk_flags
          exit_signal, exit_triggers, forced_exit: bool
          as_of_time
        """
        d = Decision(
            symbol=ctx.get('symbol', ''),
            name=ctx.get('name', ''),
            market_regime=_norm_regime(ctx.get('regime_label', '')),
            regime_label=ctx.get('regime_label', ''),
            regime_score=ctx.get('regime_score', 0.0) or 0.0,
            regime_version=ctx.get('regime_version', ''),
            permission_status=ctx.get('permission_status', ''),
            permission=dict(ctx.get('permission', {}) or {}),
            strategy=self.strategy,
            strategy_version=self.strategy_version,
            entry_signal=ctx.get('entry_signal', ENTRY_NONE),
            entry_signals=list(ctx.get('entry_signals', []) or []),
            reference_price=ctx.get('reference_price', 0.0) or 0.0,
            target_position=ctx.get('target_position', 0.0) or 0.0,
            portfolio_drawdown=ctx.get('drawdown', 0.0) or 0.0,
            position_count=ctx.get('position_count', 0) or 0,
            has_position=bool(ctx.get('has_position', False)),
            current_exposure=ctx.get('current_exposure', 0.0) or 0.0,
            stop_loss=ctx.get('stop_loss', 0.0) or 0.0,
            take_profit=list(ctx.get('take_profit', []) or []),
            trailing_stop=ctx.get('trailing_stop', 0.0) or 0.0,
            risk_flags=list(ctx.get('risk_flags', []) or []),
            exit_signal=ctx.get('exit_signal', EXIT_NONE),
            exit_triggers=list(ctx.get('exit_triggers', []) or []),
            config_version=self.config_version,
            code_version=self.code_version,
        )
        # 完整 Assessment（candidate/entry）
        d.candidate_qualified = bool(ctx.get('candidate_qualified', False))
        d.candidate_score = ctx.get('candidate_score', 0.0) or 0.0
        d.candidate_rank = ctx.get('candidate_rank', 0) or 0

        # Phase 5.5: Real Portfolio provenance（Decision → Portfolio Snapshot 反查）
        d.portfolio_snapshot_id = ctx.get('portfolio_snapshot_id', '')
        d.portfolio_source = ctx.get('portfolio_source', '')
        d.portfolio_as_of_time = ctx.get('portfolio_as_of_time', '')

        data_health = ctx.get('data_health', '')
        forced_exit = bool(ctx.get('forced_exit', False))
        mode = ctx.get('mode', 'position' if d.has_position else 'entry')
        d.as_of_time = ctx.get('as_of_time', '')
        d.timestamp = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()

        # ═══ 优先级 1/2：系统关键失败 / 强制退出 ═══
        if forced_exit:
            d.action = SELL
            d.reason_codes = [REASON['FORCED_EXIT']]
            d.exit_signal = EXIT_FORCED
            d.exit_triggers.append('FORCED_EXIT')
            d.explanation = '强制退出：系统/风险关键条件要求退出'
            return self._finalize(d)

        if data_health in _DATA_CRITICAL:
            # 关键数据失败：若已持仓且有退出需求 → SELL；否则禁新仓
            d.reason_codes.append(REASON['DATA_' + data_health])
            if d.has_position:
                if ctx.get('exit_signal') not in (EXIT_NONE, None):
                    d.action = SELL
                    d.exit_signal = ctx.get('exit_signal')
                    d.exit_triggers = list(ctx.get('exit_triggers', []) or [])
                    d.explanation = f'关键数据异常({data_health})但退出需求存在，执行退出'
                else:
                    d.action = HOLD
                    d.explanation = f'关键数据异常({data_health})，禁止新仓，持仓保持'
            else:
                d.action = NO_TRADE
                d.explanation = f'关键数据异常({data_health})，禁止开新仓'
            return self._finalize(d)

        # ═══ 已有持仓：Position Management（Phase 5）═══
        if d.has_position or mode == 'position':
            cur_pos = ctx.get('current_position', 0.0) or 0.0
            pa = ctx.get('portfolio_assessment') or {}
            # 1. Exit 优先（止损/移动止盈/强制退出）→ SELL（NO_NEW_ENTRY 不阻止 SELL）
            if ctx.get('exit_signal') not in (EXIT_NONE, None):
                d.action = SELL
                d.exit_signal = ctx.get('exit_signal')
                d.exit_triggers = list(ctx.get('exit_triggers', []) or [])
                d.reason_codes.extend(_exit_reason_codes(d.exit_signal, d.exit_triggers))
                d.current_position = cur_pos
                d.target_position = 0.0
                d.delta_position = -cur_pos
                d.explanation = f'持仓触发退出({d.exit_signal})'
            # 2. Portfolio Risk（组合回撤/暴露）→ REDUCE（目标仓位减半）
            #    仅"确认风险"才减仓；DRAWDOWN_UNKNOWN（历史峰值缺失）不强制减仓（持仓保持，除非 exit）
            elif (ctx.get('portfolio_risk') == RISK_BLOCKED or pa.get('action') == 'BLOCK') \
                 and 'DRAWDOWN_UNKNOWN' not in (pa.get('reason_codes') or []):
                target = cur_pos / 2.0
                d.action = REDUCE
                d.current_position = cur_pos
                d.target_position = target
                d.delta_position = -(cur_pos - target)
                d.reason_codes.append(REASON['PORTFOLIO_RISK_BLOCKED'])
                for rc in (pa.get('reason_codes') or []):
                    d.reason_codes.append(rc)
                d.explanation = '组合风险要求减仓'
            # 3. ADD（严格条件：add_position ALLOW + 组合OK + Entry VALID + 目标>当前）
            elif (d.permission.get('add_position') == 'ALLOW'
                  and ctx.get('entry_signal') == ENTRY_CONFIRMED
                  and (ctx.get('target_position', 0.0) or 0.0) > cur_pos):
                target = ctx.get('target_position', cur_pos)
                d.action = ADD
                d.current_position = cur_pos
                d.target_position = target
                d.delta_position = target - cur_pos
                d.reason_codes.append('ADD_ALLOWED')
                d.explanation = '加仓条件满足'
            # 4. 否则 HOLD（禁止新仓不机械清仓）
            else:
                d.action = HOLD
                d.current_position = cur_pos
                d.target_position = cur_pos
                d.delta_position = 0.0
                d.reason_codes.append('NO_EXIT_SIGNAL' if cur_pos else 'HOLD')
                d.explanation = '持仓无退出/减仓/加仓信号，继续持有'
            return self._finalize(d)

        # ═══ 新仓候选：必要条件逐条检查 ═══
        # 数据 STALE → 禁新仓
        if data_health in _DATA_STALE:
            d.action = NO_TRADE
            d.reason_codes.append(REASON['DATA_STALE'])
            d.explanation = '数据明显滞后，禁止开新仓'
            return self._finalize(d)

        # 1. Trading Permission.new_entry
        if (d.permission.get('new_entry') or 'DENY') != 'ALLOW':
            d.action = NO_TRADE
            d.reason_codes.append(REASON['PERMISSION_BLOCKED'])
            _merge_perm_reasons(d, d.permission_status)
            d.explanation = f'Trading Permission 禁止开新仓({d.permission_status})'
            return self._finalize(d)
        d.reason_codes.append(REASON['PERMISSION_ALLOWED'])

        # 2. Portfolio Risk（回撤/暴露/单股/行业/流动性/冷却）—— Phase 3 前置否决
        pa = ctx.get('portfolio_assessment') or {}
        if pa.get('action') == 'BLOCK' or (not pa and ctx.get('portfolio_risk') == RISK_BLOCKED):
            d.action = NO_TRADE
            d.reason_codes.append(REASON['PORTFOLIO_RISK_BLOCKED'])
            # 合并 Portfolio Assessment 的具体 reason codes（可解释为什么）
            for rc in (pa.get('reason_codes') or []):
                d.reason_codes.append(rc)
            if ctx.get('drawdown', 0) >= (ctx.get('drawdown_limit', 0.15) or 0.15):
                d.reason_codes.append(REASON['DRAWDOWN_BLOCKED'])
            d.explanation = f'组合风险不允许开新仓({pa.get("action","BLOCK")})'
            return self._finalize(d)
        d.reason_codes.append(REASON['PORTFOLIO_RISK_OK'])

        # 3. Candidate Qualification
        if not d.candidate_qualified:
            d.action = NO_TRADE
            d.reason_codes.append(REASON['CANDIDATE_FAIL'])
            d.explanation = '候选未通过筛选'
            return self._finalize(d)
        d.reason_codes.append(REASON['CANDIDATE_PASS'])

        # 4. Entry Signal
        if d.entry_signal != ENTRY_CONFIRMED:
            d.action = NO_TRADE
            d.reason_codes.append(REASON['ENTRY_INSUFFICIENT'])
            d.explanation = '入场信号未确认'
            return self._finalize(d)
        d.reason_codes.append(REASON['ENTRY_CONFIRMED'])

        # 5. Target Position > 0
        if d.target_position <= 0:
            d.action = NO_TRADE
            d.reason_codes.append(REASON.get('EXPOSURE_BLOCKED', 'EXPOSURE_BLOCKED'))
            d.explanation = '目标仓位为 0/负，无法买入'
            return self._finalize(d)

        # ═══ 全部通过 → BUY ═══
        d.action = BUY
        if d.market_regime in ('HIGH_VOLATILITY', 'LOW_VOLUME'):
            d.reason_codes.append(REASON['REGIME_ALLOWED'])
        d.explanation = f'满足买入必要条件（权限+组合+候选+信号+仓位）'
        return self._finalize(d)

    def _finalize(self, d: Decision) -> Decision:
        # 去重保序 reason_codes
        d.reason_codes = list(dict.fromkeys([c for c in d.reason_codes if c]))
        if not d.decision_id:
            d.decision_id = gen_decision_id(d.symbol, d.timestamp)
        return d


def _norm_regime(label):
    if not label:
        return 'UNKNOWN'
    for k in ('高波动', '低量能', '震荡市', '强趋势'):
        if k in label:
            return {'高波动': 'HIGH_VOLATILITY', '低量能': 'LOW_VOLUME',
                    '震荡市': 'SIDEWAYS', '强趋势': 'STRONG_TREND'}[k]
    return 'UNKNOWN'


def _exit_reason_codes(exit_signal, triggers):
    codes = []
    for t in triggers or []:
        t = str(t).upper()
        if 'STOP' in t and 'LOSS' in t:
            codes.append(REASON['STOP_LOSS'])
        elif 'TAKE' in t or 'TP' in t:
            codes.append(REASON['TAKE_PROFIT'])
        elif 'TRAIL' in t:
            codes.append(REASON['TRAILING_STOP'])
        elif 'MA20' in t:
            codes.append(REASON['MA20_EXIT'])
        elif 'FORCE' in t or 'RISK' in t:
            codes.append(REASON['FORCED_EXIT'])
    if not codes:
        codes.append(REASON['EXIT_SIGNAL'])
    return codes


def _merge_perm_reasons(d, status):
    if status == 'NO_NEW_ENTRY':
        d.reason_codes.append(REASON['PERMISSION_BLOCKED'])
    elif status == 'REDUCE':
        d.reason_codes.append(REASON.get('DRAWDOWN_BLOCKED', 'DRAWDOWN_BLOCKED'))
    if d.market_regime in ('HIGH_VOLATILITY', 'LOW_VOLUME'):
        d.reason_codes.append(REASON.get('HIGH_VOLATILITY' if d.market_regime == 'HIGH_VOLATILITY' else 'LOW_VOLUME',
                                         'HIGH_VOLATILITY'))
    if d.permission.get('new_entry') == 'DENY' and d.position_count >= (d.permission.get('_max', 20) or 20):
        d.reason_codes.append(REASON['MAX_POSITION_REACHED'])


if __name__ == '__main__':
    import json
    eng = DecisionEngine()
    # 快速自测
    cases = {
        '正常BUY': dict(symbol='000001', mode='entry', has_position=False, regime_label='强趋势',
                        regime_score=80, permission_status='ALLOW',
                        permission={'new_entry': 'ALLOW'}, data_health='VALID',
                        candidate_qualified=True, candidate_score=75, entry_signal='CONFIRMED',
                        entry_signals=['A', 'B', 'D'], reference_price=10.0, target_position=25000),
        '高波动NO_TRADE': dict(symbol='000002', mode='entry', has_position=False, regime_label='🔴 高波动',
                               regime_score=50, permission_status='NO_NEW_ENTRY',
                               permission={'new_entry': 'DENY'}, data_health='VALID',
                               candidate_qualified=True, entry_signal='CONFIRMED', target_position=25000),
        '持仓SELL': dict(symbol='000003', mode='position', has_position=True, regime_label='高波动',
                         permission_status='REDUCE', permission={'new_entry': 'DENY'},
                         data_health='VALID', exit_signal='RISK', exit_triggers=['STOP_LOSS']),
    }
    for name, c in cases.items():
        r = eng.decide(c)
        print(f"{name}: {r.action} reasons={r.reason_codes} perm_status={r.permission_status}")
