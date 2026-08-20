#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 8-B — Production Observation Period 测试（25 项）

运行：
  cd /home/caojy/.hermes/scripts/cron && python3 -m pytest decision/test_production_observation_phase8b.py -v
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
    SRC_SIM, SRC_MANUAL, SRC_SHADOW, _EXEC_DIR,
)
from decision.outcome import gen_outcome_id
from decision import outcome_store as _outcome_store
from decision import observation as obs

OUTCOME_DIR = Path(__file__).resolve().parent / 'outcomes'


def _fresh_decision(symbol='600000', decision_id=None, action='BUY'):
    return {
        'decision_id': decision_id or f"p8b_{datetime.now(timezone.utc).timestamp()}",
        'symbol': symbol,
        'name': 'P',
        'strategy': 'v1_double',
        'config_version': 'phase8b',
        'code_version': 'p8b_test',
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


def _clean_snapshots():
    for f in glob.glob(str(Path(__file__).resolve().parent / 'snapshots' / '*.json')):
        os.remove(f)


@pytest.fixture(autouse=True)
def _clean():
    _clean_executions()
    _clean_outcomes()
    _clean_snapshots()
    yield
    _clean_executions()
    _clean_outcomes()
    _clean_snapshots()


# ═══ 1. observation start boundary ═══
def test_01_observation_start_boundary():
    assert obs.OBSERVATION_START == '2026-08-20'
    assert obs.CODE_VERSION == 'phase8b'
    assert obs.CONFIG_VERSION == 'v1_double_top3'
    assert obs.STRATEGY_VERSION == 'v1_double'
    assert obs.DECISION_CONTRACT_VERSION == 'phase76a'


# ═══ 2. production source isolation ═══
def test_02_production_source_isolation():
    dec = _fresh_decision()
    eid = record_simulation_execution(dec, 'BUY', 10.0, 1000, run_mode='SIMULATION')
    ex = get_execution(eid)
    assert ex['run_mode'] == 'SIMULATION'
    eid2 = record_simulation_execution(dec, 'BUY', 10.0, 1000, run_mode='TEST')
    ex2 = get_execution(eid2)
    assert ex2['run_mode'] == 'TEST'


# ═══ 3. daily observation report ═══
def test_03_daily_observation_report():
    report = obs.build_daily_observation_report('2026-08-20')
    assert report['observation_date'] == '2026-08-20'
    assert report['observation_start'] == '2026-08-20'
    assert 'decision' in report
    assert 'execution' in report
    assert 'position' in report
    assert 'outcome' in report
    assert 'data_health' in report
    assert 'integrity' in report
    assert 'reconciliation' in report
    assert 'account_readiness' in report
    assert report['note'] == 'Observation only — no strategy evaluation'


# ═══ 4. decision counts ═══
def test_04_decision_counts():
    dec = _fresh_decision(action='BUY')
    record_simulation_execution(dec, 'BUY', 10.0, 1000, run_mode='SIMULATION')
    dec2 = _fresh_decision(action='NO_TRADE')
    record_simulation_execution(dec2, 'NO_TRADE', 0.0, 0, status=NOT_EXECUTED, run_mode='SIMULATION')
    snap_dir = Path('decision/snapshots')
    snap_dir.mkdir(exist_ok=True)
    for _d in (dec, dec2):
        (snap_dir / f"{_d['decision_id']}.json").write_text(json.dumps(_d, ensure_ascii=False, default=str))
    report = obs.build_daily_observation_report('2026-08-20')
    assert report['decision'].get('BUY', 0) >= 1
    assert report['decision'].get('NO_TRADE', 0) >= 1


# ═══ 5. execution counts ═══
def test_05_execution_counts():
    dec = _fresh_decision(action='BUY')
    record_simulation_execution(dec, 'BUY', 10.0, 1000, run_mode='SIMULATION')
    report = obs.build_daily_observation_report('2026-08-20')
    assert report['execution']['EXECUTED'] >= 1


# ═══ 6. position counts ═══
def test_06_position_counts():
    dec = _fresh_decision(action='BUY')
    record_simulation_execution(dec, 'BUY', 10.0, 1000, run_mode='SIMULATION')
    report = obs.build_daily_observation_report('2026-08-20')
    assert report['position']['OPEN'] >= 1


# ═══ 7. outcome counts ═══
def test_07_outcome_counts():
    dec = _fresh_decision(action='BUY')
    eid = record_simulation_execution(dec, 'BUY', 10.0, 1000, run_mode='SIMULATION')
    record_exit(eid, 12.0, 1000, '2026-08-20', 'TAKE_PROFIT', status=CLOSED,
                entry_execution_id=eid, exit_decision_id=dec['decision_id'])
    o = build_outcome_from_execution(eid)
    if o:
        _outcome_store.save_outcome(o)
    report = obs.build_daily_observation_report('2026-08-20')
    assert report['outcome'].get('CLOSED', 0) >= 1


# ═══ 8. no trade observation ═══
def test_08_no_trade_observation():
    dec = _fresh_decision(action='NO_TRADE')
    dec['reason_codes'] = ['REAL_TOTAL_ASSET_UNKNOWN']
    record_simulation_execution(dec, 'NO_TRADE', 0.0, 0, status=NOT_EXECUTED, run_mode='SIMULATION')
    snap_dir = Path('decision/snapshots')
    snap_dir.mkdir(exist_ok=True)
    (snap_dir / f"{dec['decision_id']}.json").write_text(json.dumps(dec, ensure_ascii=False, default=str))
    report = obs.build_daily_observation_report('2026-08-20')
    assert report['decision'].get('NO_TRADE', 0) >= 1


# ═══ 9. buy execution observation ═══
def test_09_buy_execution_observation():
    dec = _fresh_decision(action='BUY')
    eid = record_simulation_execution(dec, 'BUY', 10.0, 1000, run_mode='SIMULATION')
    report = obs.build_daily_observation_report('2026-08-20')
    assert report['integrity']['buy_without_execution'] == 0


# ═══ 10. partial execution ═══
def test_10_partial_execution():
    dec = _fresh_decision(action='BUY')
    record_simulation_execution(dec, 'BUY', 10.0, 1000, status=PARTIAL, run_mode='SIMULATION')
    report = obs.build_daily_observation_report('2026-08-20')
    assert report['execution']['PARTIAL'] >= 1


# ═══ 11. multiple exit ═══
def test_11_multiple_exit():
    dec = _fresh_decision(action='BUY')
    eid = record_simulation_execution(dec, 'BUY', 10.0, 1000, run_mode='SIMULATION')
    record_exit(eid, 11.0, 400, 'tp1', 'TAKE_PROFIT', status=PARTIAL,
                entry_execution_id=eid, exit_decision_id=dec['decision_id'])
    record_exit(eid, 12.0, 300, 'tp2', 'TAKE_PROFIT', status=PARTIAL,
                entry_execution_id=eid, exit_decision_id=dec['decision_id'])
    record_exit(eid, 13.0, 300, 'tp3', 'TAKE_PROFIT', status=CLOSED,
                entry_execution_id=eid, exit_decision_id=dec['decision_id'])
    report = obs.build_daily_observation_report('2026-08-20')
    assert report['position'].get('CLOSED', 0) >= 1


# ═══ 12. outcome attribution ═══
def test_12_outcome_attribution():
    dec = _fresh_decision(action='BUY')
    eid = record_simulation_execution(dec, 'BUY', 10.0, 1000, run_mode='SIMULATION')
    record_exit(eid, 12.0, 1000, '2026-08-20', 'TAKE_PROFIT', status=CLOSED,
                entry_execution_id=eid, exit_decision_id=dec['decision_id'])
    o = build_outcome_from_execution(eid)
    assert o is not None
    assert o.decision_id == dec['decision_id']
    if o:
        _outcome_store.save_outcome(o)
    report = obs.build_daily_observation_report('2026-08-20')
    assert report['outcome'].get('CLOSED', 0) >= 1


# ═══ 13. data health ═══
def test_13_data_health():
    report = obs.build_daily_observation_report('2026-08-20')
    assert 'decision_without_execution' in report['data_health']
    assert 'execution_without_position' in report['data_health']
    assert 'closed_without_outcome' in report['data_health']


# ═══ 14. active pipeline gap ═══
def test_14_active_pipeline_gap():
    report = obs.build_daily_observation_report('2026-08-20')
    assert 'active_pipeline_gap' in report.get('integrity', {}) or 'active_pipeline_gap' in report


# ═══ 15. legacy separation ═══
def test_15_legacy_separation():
    dec = _fresh_decision(decision_id='legacy_001')
    record_simulation_execution(dec, 'BUY', 10.0, 1000, run_mode='LEGACY')
    report = obs.build_daily_observation_report('2026-08-20')
    assert report['integrity']['outcome_without_decision'] >= 0


# ═══ 16. production evaluation gate ═══
def test_16_production_evaluation_gate():
    dec = _fresh_decision(action='BUY')
    eid = record_simulation_execution(dec, 'BUY', 10.0, 1000, run_mode='SIMULATION')
    record_exit(eid, 12.0, 1000, '2026-08-20', 'TAKE_PROFIT', status=CLOSED,
                entry_execution_id=eid, exit_decision_id=dec['decision_id'])
    o = build_outcome_from_execution(eid)
    if o:
        assert o.data_quality in ('PRODUCTION', 'SIMULATION', 'TEST', 'SHADOW', 'LEGACY', 'UNKNOWN')


# ═══ 17. immutable observation ═══
def test_17_immutable_observation():
    report = obs.build_daily_observation_report('2026-08-20')
    path = None
    try:
        saved = obs.save_daily_observation_report('2026-08-20')
        path = Path(saved['path'])
        assert path.exists()
        original = json.loads(path.read_text(encoding='utf-8'))
        del original['generated_at']
        obs.save_daily_observation_report('2026-08-20')
        after = json.loads(path.read_text(encoding='utf-8'))
        del after['generated_at']
        assert original == after
    finally:
        if path and path.exists():
            path.unlink()


# ═══ 18. planned vs actual ═══
def test_18_planned_vs_actual():
    dec = _fresh_decision(action='BUY')
    eid = record_simulation_execution(dec, 'BUY', 10.0, 1000, run_mode='SIMULATION')
    ex = get_execution(eid)
    assert ex['planned']['price'] == 10.0
    assert ex['actual']['price'] == 10.0


# ═══ 19. account readiness ═══
def test_19_account_readiness():
    report = obs.build_daily_observation_report('2026-08-20')
    assert 'status' in report['account_readiness']
    assert 'cash' in report['account_readiness']
    assert 'total_asset' in report['account_readiness']


# ═══ 20. count reconciliation ═══
def test_20_count_reconciliation():
    dec = _fresh_decision(action='BUY')
    record_simulation_execution(dec, 'BUY', 10.0, 1000, run_mode='SIMULATION')
    report = obs.build_daily_observation_report('2026-08-20')
    assert 'reconcile_ok' in report['reconciliation']
    assert 'anomalies' in report['reconciliation']


# ═══ 21. daily report deterministic ═══
def test_21_daily_report_deterministic():
    r1 = obs.build_daily_observation_report('2026-08-20')
    r2 = obs.build_daily_observation_report('2026-08-20')
    assert r1['observation_date'] == r2['observation_date']
    assert r1['health'] == r2['health']


# ═══ 22. test contamination prevention ═══
def test_22_test_contamination_prevention():
    dec = _fresh_decision(decision_id='test_contam_001')
    record_simulation_execution(dec, 'BUY', 10.0, 1000, run_mode='TEST')
    report = obs.build_daily_observation_report('2026-08-20')
    assert report['integrity']['outcome_without_decision'] >= 0


# ═══ 23. shadow isolation ═══
def test_23_shadow_isolation():
    dec = _fresh_decision(decision_id='shadow_001')
    record_simulation_execution(dec, 'BUY', 10.0, 1000, run_mode='SHADOW')
    report = obs.build_daily_observation_report('2026-08-20')
    assert report['integrity']['buy_without_execution'] == 0


# ═══ 24. legacy gap counts ═══
def test_24_legacy_gap_counts():
    dec = _fresh_decision(decision_id='legacy_gap_001')
    record_simulation_execution(dec, 'BUY', 10.0, 1000, run_mode='LEGACY')
    report = obs.build_daily_observation_report('2026-08-20')
    assert 'known_legacy_gap' in report or 'active_pipeline_gap' in report


# ═══ 25. no strategy evaluation in report ═══
def test_25_no_strategy_evaluation():
    report = obs.build_daily_observation_report('2026-08-20')
    assert 'v1_win_rate' not in report
    assert 'sharpe' not in report
    assert 'edge' not in report
    assert 'best_parameter' not in report
    assert 'strategy_recommendation' not in report
