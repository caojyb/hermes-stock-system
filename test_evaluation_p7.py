"""
Phase 7：Decision Evaluation & Evidence Audit 测试
覆盖：
1. dataset 分离
2. stats 计算
3. regime 分层
4. permission counterfactual
5. time stability
6. data quality
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from collections import defaultdict

import pytest

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))

from evaluation.run_evaluation import (
    build_dataset,
    compute_stats,
    layer_stats,
    group_by,
    evaluate_trading_permission,
    time_stability,
    is_production_qualified,
    check_evaluation_health,
    _classify_source,
    _to_float,
)


def _make_execution(decision_id='eval_d1', symbol='600030', action='BUY', strategy='v1_double',
                    status='EXECUTED', source='SIMULATION', position_id='', position_status='CLOSED',
                    run_mode='', environment=''):
    return {
        'execution_id': f"exec_{decision_id}",
        'decision_id': decision_id,
        'symbol': symbol,
        'name': 'T',
        'action': action,
        'strategy': strategy,
        'status': status,
        'source': source,
        'planned': {'price': 10.0, 'quantity': 0, 'position': 0},
        'actual': {'price': 10.0, 'quantity': 1000, 'position': 1000.0},
        'execution_time': '2026-08-19T00:00:00+00:00',
        'position_id': position_id or f"P_{decision_id}",
        'position_status': position_status,
        'exit_segments': [],
        'exit_summary': {},
        'linkage': '',
        'run_mode': run_mode,
        'environment': environment,
    }


def _make_outcome(decision_id='eval_d1', symbol='600030', strategy='v1_double', source='DECISION',
                  return_pct=0.1, realized_pnl=1000.0, exit_reason='TAKE_PROFIT',
                  position_id='', entry_regime='strong_trend', exit_regime='strong_trend',
                  mae=-0.02, mfe=0.05, max_drawdown=-0.01, holding_period_days=5,
                  permission_status='ALLOW', portfolio_assessment=None, exit_regime_actual=''):
    portfolio_assessment = portfolio_assessment or {}
    return {
        'outcome_id': f"out_{decision_id}",
        'decision_id': decision_id,
        'symbol': symbol,
        'action': 'BUY',
        'strategy': strategy,
        'outcome_source': source,
        'lifecycle_status': 'CLOSED',
        'exit_reason': exit_reason,
        'return_pct': return_pct,
        'realized_pnl': realized_pnl,
        'holding_period_days': holding_period_days,
        'mae': mae,
        'mfe': mfe,
        'max_drawdown': max_drawdown,
        'entry_regime': entry_regime,
        'exit_regime': exit_regime_actual or exit_regime,
        'permission_status': permission_status,
        'portfolio_assessment': portfolio_assessment,
        'position_id': position_id or f"P_{decision_id}",
        'execution_id': f"exec_{decision_id}",
        'actual': {
            'entry_price': 10.0,
            'exit_price': 11.0,
            'position_size': 1000.0,
            'return_pct': return_pct,
            'realized_pnl': realized_pnl,
            'initial_quantity': 1000.0,
            'added_quantity': 0.0,
            'total_entry_quantity': 1000.0,
            'average_entry_price': 10.0,
            'total_exit_quantity': 1000.0,
            'weighted_exit_price': 11.0,
            'final_quantity': 0.0,
        },
        'excursion': {
            'mae': mae,
            'mfe': mfe,
            'max_drawdown': max_drawdown,
            'max_profit': 0.0,
            'status': 'KNOWN',
        },
    }


class TestDatasetSeparation:
    def test_production_shadow_legacy_separated(self):
        execs = [
            _make_execution('eval_p1', strategy='v1_double', source='SIMULATION', run_mode='SIMULATION'),
            _make_execution('eval_s1', strategy='main_up', source='SIMULATION', run_mode='SIMULATION'),
            _make_execution('', symbol='600099', action='BUY', strategy='v1_double', status='EXECUTED', source='SIMULATION', run_mode='LEGACY'),
        ]
        outcomes = [
            _make_outcome('eval_p1', strategy='v1_double', source='DECISION'),
            _make_outcome('eval_s1', strategy='main_up', source='DECISION'),
            _make_outcome('', symbol='600099', source='LEGACY'),
        ]
        dataset = build_dataset()
        assert _classify_source(execs[0]) == 'SIMULATION'
        assert _classify_source(execs[1]) == 'SHADOW'
        assert _classify_source(execs[2]) == 'LEGACY'


class TestStats:
    def test_win_rate_and_profit_factor(self):
        recs = [
            _make_outcome('p7_a', return_pct=0.1, realized_pnl=1000.0),
            _make_outcome('p7_b', return_pct=-0.05, realized_pnl=-500.0),
            _make_outcome('p7_c', return_pct=0.2, realized_pnl=2000.0),
        ]
        st = compute_stats(recs)
        assert st['N'] == 3
        assert st['win_rate'] == pytest.approx(2/3)
        assert st['profit_factor'] == pytest.approx(3000.0 / 500.0)

    def test_median_and_distribution(self):
        recs = [_make_outcome(f'p7_m{i}', return_pct=v) for i, v in enumerate([0.1, -0.2, 0.3])]
        st = compute_stats(recs)
        assert st['median_return'] == pytest.approx(0.1)

    def test_data_insufficient(self):
        recs = [_make_outcome('p7_insuf')]
        st = compute_stats(recs)
        assert st.get('DATA_INSUFFICIENT') is True


class TestLayerStats:
    def test_regime_layers(self):
        recs = [
            _make_outcome('p7_r1', entry_regime='strong_trend', return_pct=0.1),
            _make_outcome('p7_r2', entry_regime='strong_trend', return_pct=0.2),
            _make_outcome('p7_r3', entry_regime='high_volatility', return_pct=-0.1),
        ]
        layered = layer_stats(recs, 'entry_regime')
        assert 'strong_trend' in layered
        assert 'high_volatility' in layered
        assert layered['strong_trend']['N'] == 2
        assert layered['high_volatility']['N'] == 1

    def test_insufficient_layer_marked(self):
        recs = [_make_outcome('p7_r1', entry_regime='rare_regime')]
        layered = layer_stats(recs, 'entry_regime')
        assert layered['rare_regime']['status'] == 'DATA_INSUFFICIENT'


class TestPermissionCounterfactual:
    def test_allowed_vs_blocked(self):
        execs = [
            _make_execution('perm_a1', status='EXECUTED', position_id='pid_a', source='MANUAL_CONFIRMATION', run_mode='PRODUCTION'),
            _make_execution('perm_a2', status='EXECUTED', position_id='pid_b', source='MANUAL_CONFIRMATION', run_mode='PRODUCTION'),
            _make_execution('perm_b1', status='BLOCKED', position_id='pid_c', source='MANUAL_CONFIRMATION', run_mode='PRODUCTION'),
        ]
        outcomes = [
            _make_outcome('perm_a1', position_id='pid_a', return_pct=0.1),
            _make_outcome('perm_a2', position_id='pid_b', return_pct=0.2),
            _make_outcome('perm_b1', position_id='pid_c', return_pct=-0.1),
        ]
        res = evaluate_trading_permission(execs, outcomes)
        assert res['allowed_N'] == 2
        assert res['blocked_N'] == 1
        assert res['allowed_stats']['win_rate'] == pytest.approx(1.0)
        assert res['blocked_stats']['win_rate'] == pytest.approx(0.0)


class TestTimeStability:
    def test_by_year_and_quarter(self):
        recs = [
            _make_outcome('p7_y1'),
            _make_outcome('p7_y2'),
        ]
        recs[0]['year'] = '2026'
        recs[0]['quarter'] = '2026-Q3'
        recs[1]['year'] = '2026'
        recs[1]['quarter'] = '2026-Q3'
        ts = time_stability(recs)
        assert '2026' in ts['yearly']
        assert '2026-Q3' in ts['quarterly']


class TestSourceClassification:
    def test_manual_confirmation_alone_not_production(self):
        e = _make_execution('src_m1', source='MANUAL_CONFIRMATION')
        assert _classify_source(e) != 'PRODUCTION'

    def test_production_needs_environment(self):
        e = _make_execution('src_p1', source='MANUAL_CONFIRMATION')
        e['environment'] = 'PRODUCTION'
        assert _classify_source(e) == 'PRODUCTION'

    def test_shadow_by_strategy(self):
        e = _make_execution('src_s1', strategy='main_up', source='SIMULATION')
        assert _classify_source(e) == 'SHADOW'

    def test_legacy_by_decision_id(self):
        e = _make_execution('lc_legacy', source='SIMULATION')
        assert _classify_source(e) == 'LEGACY'

    def test_test_by_decision_id_prefix(self):
        e = _make_execution('p67_d1', source='SIMULATION')
        assert _classify_source(e) == 'TEST'


class TestProductionQualification:
    def test_full_production_qualified(self):
        rec = _make_outcome('pq_full', entry_regime='strong_trend', permission_status='ALLOW',
                            exit_reason='TAKE_PROFIT', exit_regime='sideways')
        rec['source'] = 'PRODUCTION'
        rec['decision_id'] = 'prod_d1'
        rec['execution_id'] = 'exec_prod_d1'
        rec['position_id'] = 'P_prod_d1'
        rec['portfolio_assessment'] = {'drawdown': 0.1}
        q = is_production_qualified(rec)
        assert q['qualified'] is True
        assert q['status'] == 'QUALIFIED'

    def test_missing_regime_data_gap(self):
        rec = _make_outcome('pq_gap', permission_status='ALLOW', exit_reason='TAKE_PROFIT')
        rec['source'] = 'PRODUCTION'
        rec['decision_id'] = 'prod_d2'
        rec['execution_id'] = 'exec_prod_d2'
        rec['position_id'] = 'P_prod_d2'
        rec['portfolio_assessment'] = {}
        rec['entry_regime'] = ''
        q = is_production_qualified(rec)
        assert q['status'] == 'DATA_GAP'
        assert 'entry_regime' in q['missing']

    def test_missing_permission_data_gap(self):
        rec = _make_outcome('pq_gap2', entry_regime='strong_trend', exit_reason='TAKE_PROFIT')
        rec['source'] = 'PRODUCTION'
        rec['decision_id'] = 'prod_d3'
        rec['execution_id'] = 'exec_prod_d3'
        rec['position_id'] = 'P_prod_d3'
        rec['portfolio_assessment'] = {}
        rec['permission_status'] = ''
        q = is_production_qualified(rec)
        assert q['status'] == 'DATA_GAP'
        assert 'permission_status' in q['missing']

    def test_missing_exit_regime_partial(self):
        rec = _make_outcome('pq_partial', entry_regime='strong_trend', permission_status='ALLOW',
                            exit_reason='TAKE_PROFIT')
        rec['source'] = 'PRODUCTION'
        rec['decision_id'] = 'prod_d4'
        rec['execution_id'] = 'exec_prod_d4'
        rec['position_id'] = 'P_prod_d4'
        rec['portfolio_assessment'] = {'exposure': 0.5}
        rec['exit_regime'] = ''
        q = is_production_qualified(rec)
        assert q['status'] == 'PRODUCTION_PARTIAL'
        assert 'exit_regime' in q['missing']

    def test_non_production_never_qualified(self):
        rec = _make_outcome('pq_testsrc')
        rec['source'] = 'TEST'
        q = is_production_qualified(rec)
        assert q['qualified'] is False
        assert 'source!=PRODUCTION' in q['missing']


class TestEvaluationHealth:
    def test_not_ready_without_production(self):
        health = check_evaluation_health()
        assert health['evaluation_health']['status'] == 'NOT_READY'
        assert health['evaluation_health']['production']['total'] == 0

    def test_health_counts(self):
        health = check_evaluation_health()
        prod = health['evaluation_health']['production']
        assert 'valid' in prod
        assert 'partial' in prod
        assert 'data_gap' in prod
        assert 'missing_regime' in prod
        assert 'missing_score' in prod
        assert 'missing_permission' in prod
        assert 'missing_portfolio' in prod
        assert 'missing_mae' in prod
        assert 'missing_mfe' in prod


class TestExitRegimeProvenance:
    def test_exit_regime_propagates_to_outcome(self):
        from decision.execution import record_exit, build_outcome_from_execution, record_simulation_execution
        did = 'p72_exit_regime'
        eid = record_simulation_execution({'decision_id': did, 'symbol': '600011', 'name': 'T',
                                           'strategy': 'v1_double', 'reference_price': 10.0,
                                           'market_regime': 'sideways'}, 'BUY', 10.0, 1000)
        record_exit(eid, 12.0, 1000, '2026-08-19', 'TAKE_PROFIT', exit_regime='high_volatility')
        o = build_outcome_from_execution(eid)
        assert o is not None
        assert o.exit_regime == 'high_volatility'


class TestHoldingPeriod:
    def test_holding_period_uses_actual_execution_time(self):
        from decision.execution import record_exit, build_outcome_from_execution, record_simulation_execution
        did = 'p72_hold'
        eid = record_simulation_execution({'decision_id': did, 'symbol': '600012', 'name': 'T',
                                           'strategy': 'v1_double', 'reference_price': 10.0,
                                           'timestamp': '2026-08-18T10:00:00+00:00'}, 'BUY', 10.0, 1000)
        record_exit(eid, 11.0, 1000, '2026-08-19', 'TAKE_PROFIT')
        o = build_outcome_from_execution(eid)
        assert o is not None
        assert o.holding_period_days >= 0


class TestSlippageCapture:
    def test_slippage_from_planned_actual(self):
        from decision.execution import record_simulation_execution, record_exit, build_outcome_from_execution
        did = 'p72_slip'
        eid = record_simulation_execution({'decision_id': did, 'symbol': '600013', 'name': 'T',
                                           'strategy': 'v1_double', 'reference_price': 10.0}, 'BUY', 10.2, 1000)
        record_exit(eid, 11.0, 1000, '2026-08-19', 'TAKE_PROFIT', status='CLOSED')
        o = build_outcome_from_execution(eid)
        assert o is not None
        assert o.actual.entry_price == 10.2
        assert o.slippage_price == 0.2
