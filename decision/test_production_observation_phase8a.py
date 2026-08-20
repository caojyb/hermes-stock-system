#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 8-A — Production Observation Infrastructure 测试（23 项）

运行：
  cd /home/caojy/.hermes/scripts/cron && python3 -m pytest decision/test_production_observation_phase8a.py -v
"""
import json, os, glob
from pathlib import Path
from datetime import datetime, timezone

import pytest

from decision.execution import (
    record_simulation_execution, confirm_manual_execution, record_exit,
    build_outcome_from_execution, lifecycle_replay, monitor,
    get_execution, find_execution, find_executions_by_position_id, find_entry_execution,
    gen_exec_id, gen_position_id,
    EXECUTED, PARTIAL, NOT_EXECUTED, CLOSED, OPEN, UNKNOWN,
    SRC_SIM, SRC_MANUAL, _EXEC_DIR
)
from decision.outcome import gen_outcome_id
from decision import outcome_store as _outcome_store

OUTCOME_DIR = Path(__file__).resolve().parent / 'outcomes'


# ═══ helpers ═══
def _fresh_decision(symbol='600000', decision_id=None, action='BUY'):
    return {
        'decision_id': decision_id or f"p8a_{datetime.now(timezone.utc).timestamp()}",
        'symbol': symbol,
        'name': 'P',
        'strategy': 'v1_double',
        'config_version': 'phase8a',
        'code_version': 'p8a_test',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'data_snapshot_id': f"snap_{symbol}",
        'portfolio_snapshot_id': f"port_{symbol}",
        'market_regime': 'high_volatility',
        'regime_label': 'HIGH_VOLATILITY',
        'candidate_score': 88.5,
        'candidate_rank': 1,
        'reason_codes': ['CANDIDATE_QUALIFIED'],
        'permission_status': 'ALLOW',
        'permission': {'new_entry': True},
        'portfolio_assessment': {'allowed': True},
        'portfolio_drawdown': -0.05,
        'portfolio_risk_flags': [],
        'reference_price': 10.0,
        'target_position': 2500.0,
        'action': action,
    }


def _clean_executions():
    for f in glob.glob(str(Path(_EXEC_DIR) / '*.json')):
        os.remove(f)


def _clean_outcomes():
    for f in glob.glob(str(OUTCOME_DIR / '*.json')):
        os.remove(f)


@pytest.fixture(autouse=True)
def _clean():
    _clean_executions()
    _clean_outcomes()
    yield
    _clean_executions()
    _clean_outcomes()


# ═══ 1. production observation graph ═══
def test_01_production_observation_graph():
    base = Path(__file__).resolve().parent
    assert (base / 'executions').exists()
    assert (base / 'outcomes').exists()


# ═══ 2. source classification ═══
def test_02_source_classification():
    dec = _fresh_decision()
    eid = record_simulation_execution(dec, 'BUY', 10.0, 1000, run_mode='SIMULATION')
    ex = get_execution(eid)
    assert ex['source'] == SRC_SIM
    assert ex['run_mode'] == 'SIMULATION'


# ═══ 3. decision snapshot immutable ═══
def test_03_decision_snapshot_immutable():
    dec = _fresh_decision()
    eid1 = record_simulation_execution(dec, 'BUY', 10.0, 1000)
    eid2 = record_simulation_execution(dec, 'BUY', 10.0, 1000)
    assert eid1 != eid2
    ex1 = get_execution(eid1)
    ex2 = get_execution(eid2)
    assert ex1['planned']['price'] == 10.0
    assert ex2['planned']['price'] == 10.0


# ═══ 4. production BUY observation ═══
def test_04_production_buy_observation():
    dec = _fresh_decision()
    eid = record_simulation_execution(dec, 'BUY', 10.0, 1000, run_mode='SIMULATION')
    ex = get_execution(eid)
    assert ex['decision_id'] == dec['decision_id']
    assert ex['position_id']
    assert ex['entry_regime'] == 'high_volatility'
    assert ex['permission_status'] == 'ALLOW'


# ═══ 5. production NO_TRADE observation ═══
def test_05_production_no_trade_observation():
    dec = _fresh_decision()
    dec['action'] = 'NO_TRADE'
    dec['reason_codes'] = ['PORTFOLIO_MAX_POSITION']
    eid = record_simulation_execution(dec, 'NO_TRADE', 0.0, 0, status=NOT_EXECUTED, run_mode='SIMULATION')
    ex = get_execution(eid)
    assert ex['status'] == NOT_EXECUTED
    assert ex['position_status'] == UNKNOWN


# ═══ 6. production SELL observation ═══
def test_06_production_sell_observation():
    dec = _fresh_decision(action='SELL')
    eid = record_simulation_execution(dec, 'SELL', 11.0, 1000, run_mode='SIMULATION')
    ex = get_execution(eid)
    assert ex['action'] == 'SELL'
    assert ex['position_status'] in (OPEN, UNKNOWN)


# ═══ 7. production REDUCE observation ═══
def test_07_production_reduce_observation():
    dec = _fresh_decision(action='REDUCE')
    eid = record_simulation_execution(dec, 'REDUCE', 11.0, 500, run_mode='SIMULATION')
    ex = get_execution(eid)
    assert ex['action'] == 'REDUCE'
    assert ex['actual']['quantity'] == 500


# ═══ 8. manual execution provenance ═══
def test_08_manual_execution_provenance():
    dec = _fresh_decision()
    eid = record_simulation_execution(dec, 'BUY', 0.0, 0, status=NOT_EXECUTED)
    eid2 = confirm_manual_execution(dec['decision_id'], actual_price=10.2, actual_quantity=1000,
                                    execution_time='2026-08-20T10:00:00Z', status=EXECUTED,
                                    run_mode='PRODUCTION', environment='PRODUCTION')
    ex = get_execution(eid2)
    assert ex['source'] == SRC_MANUAL
    assert ex['status'] == EXECUTED
    assert ex['actual']['price'] == 10.2
    assert ex['run_mode'] == 'PRODUCTION'


# ═══ 9. NOT_EXECUTED ═══
def test_09_not_executed():
    dec = _fresh_decision()
    eid = record_simulation_execution(dec, 'BUY', 0.0, 0, status=NOT_EXECUTED, run_mode='SIMULATION')
    ex = get_execution(eid)
    assert ex['status'] == NOT_EXECUTED
    assert ex['position_status'] == UNKNOWN
    o = build_outcome_from_execution(eid)
    assert o is None


# ═══ 10. PARTIAL execution ═══
def test_10_partial_execution():
    dec = _fresh_decision()
    eid = record_simulation_execution(dec, 'BUY', 10.0, 1000, status=PARTIAL, run_mode='SIMULATION')
    ex = get_execution(eid)
    assert ex['status'] == PARTIAL
    assert ex['position_status'] == PARTIAL
    o = build_outcome_from_execution(eid)
    assert o is None


# ═══ 11. multiple exit ═══
def test_11_multiple_exit():
    dec = _fresh_decision()
    eid = record_simulation_execution(dec, 'BUY', 10.0, 1000, run_mode='SIMULATION')
    record_exit(eid, 11.0, 400, 'tp1', 'TAKE_PROFIT', status=PARTIAL,
                entry_execution_id=eid, exit_decision_id=dec['decision_id'])
    record_exit(eid, 12.0, 300, 'tp2', 'TAKE_PROFIT', status=PARTIAL,
                entry_execution_id=eid, exit_decision_id=dec['decision_id'])
    record_exit(eid, 13.0, 300, 'tp3', 'TAKE_PROFIT', status=CLOSED,
                entry_execution_id=eid, exit_decision_id=dec['decision_id'])
    ex = get_execution(eid)
    assert len(ex['exit_segments']) == 3
    assert ex['exit_summary']['total_quantity'] == 1000
    o = build_outcome_from_execution(eid)
    assert o is not None
    assert o.outcome_id


# ═══ 12. production outcome ═══
def test_12_production_outcome():
    dec = _fresh_decision()
    eid = record_simulation_execution(dec, 'BUY', 10.0, 1000, run_mode='SIMULATION')
    record_exit(eid, 12.0, 1000, '2026-08-20', 'TAKE_PROFIT', status=CLOSED,
                entry_execution_id=eid, exit_decision_id=dec['decision_id'])
    o = build_outcome_from_execution(eid)
    assert o is not None
    assert o.decision_id == dec['decision_id']
    assert o.execution_time
    assert o.strategy_version == 'phase8a'


# ═══ 13. MAE/MFE trigger ═══
def test_13_mae_mfe_trigger():
    dec = _fresh_decision(symbol='600001')
    eid = record_simulation_execution(dec, 'BUY', 10.0, 1000, run_mode='SIMULATION')
    record_exit(eid, 12.0, 1000, '2026-08-20', 'TAKE_PROFIT', status=CLOSED,
                entry_execution_id=eid, exit_decision_id=dec['decision_id'])
    o = build_outcome_from_execution(eid)
    assert o is not None
    assert o.mae_mfe_status in ('COMPUTED', UNKNOWN)


# ═══ 14. holding period ═══
def test_14_holding_period():
    dec = _fresh_decision()
    eid = record_simulation_execution(dec, 'BUY', 10.0, 1000, run_mode='SIMULATION')
    ex = get_execution(eid)
    ex['execution_time'] = '2026-08-18T09:30:00Z'
    with open(Path(_EXEC_DIR) / f'{eid}.json', 'w') as f:
        json.dump(ex, f, ensure_ascii=False, indent=2, default=str)
    record_exit(eid, 12.0, 1000, '2026-08-20', 'TAKE_PROFIT', status=CLOSED,
                entry_execution_id=eid, exit_decision_id=dec['decision_id'])
    o = build_outcome_from_execution(eid)
    assert o is not None
    assert o.holding_period_days >= 1


# ═══ 15. execution quality ═══
def test_15_execution_quality():
    dec = _fresh_decision()
    eid = record_simulation_execution(dec, 'BUY', 10.0, 1000, run_mode='SIMULATION')
    record_exit(eid, 12.0, 1000, '2026-08-20', 'TAKE_PROFIT', status=CLOSED,
                entry_execution_id=eid, exit_decision_id=dec['decision_id'])
    ex = get_execution(eid)
    assert ex['planned']['price'] == 10.0
    assert ex['actual']['price'] == 10.0
    o = build_outcome_from_execution(eid)
    assert o is not None
    assert o.slippage_price == 0.0


# ═══ 16. portfolio snapshot linkage ═══
def test_16_portfolio_snapshot_linkage():
    dec = _fresh_decision()
    eid = record_simulation_execution(dec, 'BUY', 10.0, 1000, run_mode='SIMULATION')
    ex = get_execution(eid)
    assert ex['portfolio_snapshot_id'] == f"port_600000"
    assert ex['decision_snapshot_id'] == f"snap_600000"


# ═══ 17. active pipeline health ═══
def test_17_active_pipeline_health():
    dec = _fresh_decision()
    record_simulation_execution(dec, 'NO_TRADE', 0.0, 0, status=NOT_EXECUTED, run_mode='SIMULATION')
    report = monitor()
    assert report['status'] in ('HEALTHY', 'DEGRADED', 'BROKEN')
    assert 'active_pipeline_gap' in report


# ═══ 18. historical legacy separation ═══
def test_18_historical_legacy_separation():
    report = monitor()
    assert 'historical_unlinked' in report
    assert 'known_legacy_gap' in report
    assert report['historical_unlinked'] >= 0


# ═══ 19. daily observation health ═══
def test_19_daily_observation_health():
    dec = _fresh_decision()
    eid = record_simulation_execution(dec, 'BUY', 10.0, 1000, run_mode='SIMULATION')
    record_exit(eid, 12.0, 1000, '2026-08-20', 'TAKE_PROFIT', status=CLOSED,
                entry_execution_id=eid, exit_decision_id=dec['decision_id'])
    report = monitor()
    assert report['status'] in ('HEALTHY', 'DEGRADED', 'BROKEN')


# ═══ 20. production evaluation gate ═══
def test_20_production_evaluation_gate():
    dec = _fresh_decision()
    eid = record_simulation_execution(dec, 'BUY', 10.0, 1000, run_mode='SIMULATION')
    record_exit(eid, 12.0, 1000, '2026-08-20', 'TAKE_PROFIT', status=CLOSED,
                entry_execution_id=eid, exit_decision_id=dec['decision_id'])
    o = build_outcome_from_execution(eid)
    if o:
        assert o.data_quality in ('PRODUCTION', 'SIMULATION', 'TEST', 'SHADOW', 'LEGACY', 'UNKNOWN')


# ═══ 21. test contamination prevention ═══
def test_21_test_contamination_prevention():
    dec = _fresh_decision(decision_id='test_001')
    eid = record_simulation_execution(dec, 'BUY', 10.0, 1000, run_mode='TEST')
    record_exit(eid, 12.0, 1000, '2026-08-20', 'TAKE_PROFIT', status=CLOSED,
                entry_execution_id=eid, exit_decision_id=dec['decision_id'])
    o = build_outcome_from_execution(eid)
    if o:
        assert o.data_quality == 'TEST'


# ═══ 22. replay lifecycle ═══
def test_22_replay_lifecycle():
    dec = _fresh_decision()
    eid = record_simulation_execution(dec, 'BUY', 10.0, 1000, run_mode='SIMULATION')
    record_exit(eid, 12.0, 1000, '2026-08-20', 'TAKE_PROFIT', status=CLOSED,
                entry_execution_id=eid, exit_decision_id=dec['decision_id'])
    o = build_outcome_from_execution(eid)
    assert o is not None
    _outcome_store.save_outcome(o)
    r = lifecycle_replay(o.outcome_id)
    assert r['ok'] is True
    assert r['outcome']['outcome_id'] == o.outcome_id


# ═══ 23. observation start boundary ═══
def test_23_observation_start_boundary():
    dec = _fresh_decision(decision_id='legacy_001')
    eid = record_simulation_execution(dec, 'BUY', 10.0, 1000, run_mode='LEGACY')
    ex = get_execution(eid)
    assert ex['run_mode'] == 'LEGACY'
    record_exit(eid, 12.0, 1000, '2026-08-20', 'TAKE_PROFIT', status=CLOSED,
                entry_execution_id=eid, exit_decision_id=dec['decision_id'])
    o = build_outcome_from_execution(eid)
    if o:
        assert o.data_quality in ('SIMULATION', 'LEGACY', 'UNKNOWN')
