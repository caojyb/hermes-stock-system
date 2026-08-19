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
    _classify_source,
    _to_float,
)


def _make_execution(decision_id='p7_d1', symbol='600030', action='BUY', strategy='v1_double',
                    status='EXECUTED', source='SIMULATION', position_id='', position_status='CLOSED'):
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
    }


def _make_outcome(decision_id='p7_d1', symbol='600030', strategy='v1_double', source='DECISION',
                  return_pct=0.1, realized_pnl=1000.0, exit_reason='TAKE_PROFIT',
                  position_id='', entry_regime='strong_trend', exit_regime='strong_trend',
                  mae=-0.02, mfe=0.05, max_drawdown=-0.01, holding_period_days=5):
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
        'exit_regime': exit_regime,
        'position_id': position_id or f"P_{decision_id}",
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
            _make_execution('eval_p1', strategy='v1_double', source='SIMULATION'),
            _make_execution('eval_s1', strategy='main_up', source='SIMULATION'),
            _make_execution('', symbol='600099', action='BUY', strategy='v1_double', status='EXECUTED', source='SIMULATION'),
        ]
        outcomes = [
            _make_outcome('eval_p1', strategy='v1_double', source='DECISION'),
            _make_outcome('eval_s1', strategy='main_up', source='DECISION'),
            _make_outcome('', symbol='600099', source='LEGACY'),
        ]
        dataset = build_dataset()
        # Phase 7.1: classification based on source + decision_id pattern
        assert _classify_source(execs[0]) == 'SIMULATION'  # SIMULATION source, no test prefix
        assert _classify_source(execs[1]) == 'SHADOW'      # main_up strategy
        assert _classify_source(execs[2]) == 'LEGACY'      # no decision_id


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
            _make_execution('perm_a1', status='EXECUTED', position_id='pid_a', source='MANUAL_CONFIRMATION'),
            _make_execution('perm_a2', status='EXECUTED', position_id='pid_b', source='MANUAL_CONFIRMATION'),
            _make_execution('perm_b1', status='BLOCKED', position_id='pid_c', source='MANUAL_CONFIRMATION'),
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
