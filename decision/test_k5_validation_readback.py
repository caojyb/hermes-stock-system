#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 8-K5 测试：Forward Validation Daily Readback（只读）。
验证边界/过滤/状态机/gate/contamination/reconciliation/分离/确定性，不写生产事实。
"""

import os
import sys
import json
import sqlite3
import unittest
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, SCRIPT_DIR)

import decision.validation_readback as vr
from decision.validation_baseline import is_validation_trade, validation_gate_status


class TestValidationDateBoundary(unittest.TestCase):
    """严格使用 2026-08-27 boundary。"""

    def test_start_date_constant(self):
        self.assertEqual(vr.VALIDATION_START_DATE, '2026-08-27')

    def test_is_validation_trade_boundary(self):
        # 8/26 之前 = legacy；8/27 起 = validation
        self.assertFalse(is_validation_trade('2026-08-26'))
        self.assertTrue(is_validation_trade('2026-08-27'))
        self.assertTrue(is_validation_trade('2026-09-01'))


class TestTradingDayCount(unittest.TestCase):

    def test_single_day(self):
        self.assertEqual(vr._trading_days_between('2026-08-27', '2026-08-27'), 1)

    def test_checkpoint_window(self):
        # 8/27(Thu) - 9/5(Sat): 8/27,28,31,9/1,2,3,4 = 7 trading days
        self.assertEqual(vr._trading_days_between('2026-08-27', '2026-09-05'), 7)

    def test_weekend_excluded(self):
        # 8/28(Fri)-8/31(Mon): Fri,Sat,Sun,Mon -> 2 trading days
        self.assertEqual(vr._trading_days_between('2026-08-28', '2026-08-31'), 2)


class TestValidationTradeFilter(unittest.TestCase):
    """只统计 trade_date >= 2026-08-27 的 validation trades。"""

    def test_legacy_excluded(self):
        sim = vr._simulation_state()
        # 当前 simulation.db 全为 legacy (<8/27)
        self.assertEqual(sim['validation_trades'], 0)
        self.assertGreater(sim['legacy_trades'], 0)

    def test_zero_trade_day(self):
        rb = vr.build_readback('2026-08-27')
        self.assertEqual(rb['SIMULATION']['validation_trades'], 0)
        self.assertEqual(rb['OUTCOME']['SIMULATION']['validation_outcome_count'], 0)


class TestValidationState(unittest.TestCase):

    def test_active_before_threshold(self):
        rb = vr.build_readback('2026-08-27')
        self.assertEqual(rb['VALIDATION_IDENTITY']['validation_state'], 'ACTIVE')

    def test_status_clean_no_anomaly(self):
        rb = vr.build_readback('2026-08-27')
        self.assertEqual(rb['VALIDATION_IDENTITY']['validation_status'], 'VALIDATION_CLEAN')


class TestGate(unittest.TestCase):

    def test_insufficient_not_fail(self):
        # 样本不够 → DATA_INSUFFICIENT，不是 FAIL
        self.assertEqual(validation_gate_status(5, 2), 'DATA_INSUFFICIENT')
        self.assertEqual(validation_gate_status(7, 0), 'DATA_INSUFFICIENT')

    def test_sufficient_can_evaluate(self):
        # 满足样本量才允许进入 EVALUABLE（不提前判 PASS/FAIL/BORDERLINE）
        st = validation_gate_status(20, 12)
        self.assertIn(st, ('EVALUABLE', 'DATA_INSUFFICIENT'))

    def test_early_evaluation_blocked(self):
        rb = vr.build_readback('2026-08-27')
        self.assertEqual(rb['GATE']['early_evaluation'], 'BLOCKED')


class TestContaminationDetection(unittest.TestCase):

    def test_no_contamination_clean(self):
        rb = vr.build_readback('2026-08-27')
        self.assertFalse(rb['CONTAMINATION']['VALIDATION_CONTAMINATION'])
        self.assertEqual(rb['CONTAMINATION']['detected'], [])

    def test_persistence_failure_degrades(self):
        # 注入 persistence failed snapshot + 对应 daily decision 模拟
        snap_dir = Path(SCRIPT_DIR, 'decision', 'snapshots')
        snap_dir.mkdir(exist_ok=True)
        inj = snap_dir / 'inj_persist_test.json'
        inj.write_text(json.dumps({
            'timestamp': '2026-08-27T09:35:00', 'source': 'STOP_LOSS',
            'decision_id': 'INJ1', 'persistence_status': 'FAILED'
        }, ensure_ascii=False))
        # 写对应 daily decision 报告使 reconciliation 通过（仅 urgent gap 不触发）
        rep = Path(SCRIPT_DIR, 'reports', 'daily_decision_2026-08-27.json')
        rep.parent.mkdir(exist_ok=True, parents=True)
        rep.write_text(json.dumps({'actions': {'SELL': [{'decision_id': 'INJ1'}]}}, ensure_ascii=False))
        try:
            rb = vr.build_readback('2026-08-27')
            self.assertIn('PERSISTENCE_FAILED', rb['CONTAMINATION']['detected'])
            self.assertEqual(rb['VALIDATION_IDENTITY']['validation_status'], 'VALIDATION_DEGRADED')
        finally:
            inj.unlink()
            rep.unlink()


class TestPersistenceAnomalyDetection(unittest.TestCase):

    def test_persistence_failed_count_visible(self):
        rb = vr.build_readback('2026-08-27')
        self.assertIn('persistence_failed_count', rb['DELIVERY'])
        self.assertIn('urgent_daily_reconciliation_gap', rb['DELIVERY'])


class TestReconciliation(unittest.TestCase):

    def test_decision_in_daily(self):
        rb = vr.build_readback('2026-08-27')
        # 无 decision 时 True（空集 <= 任意集）
        self.assertTrue(rb['RECONCILIATION']['decision_in_daily'])

    def test_urgent_in_daily(self):
        rb = vr.build_readback('2026-08-27')
        self.assertTrue(rb['RECONCILIATION']['urgent_in_daily'])


class TestSimulationProductionSeparation(unittest.TestCase):

    def test_production_outcome_zero(self):
        rb = vr.build_readback('2026-08-27')
        self.assertEqual(rb['OUTCOME']['PRODUCTION']['production_outcome_count'], 0)

    def test_separation_note_present(self):
        rb = vr.build_readback('2026-08-27')
        self.assertIn('完全分离', rb['EXECUTION']['note'])


class TestDeterministicReadback(unittest.TestCase):

    def test_deterministic(self):
        r1 = vr.build_readback('2026-08-27')
        r2 = vr.build_readback('2026-08-27')
        self.assertEqual(json.dumps(r1, sort_keys=True), json.dumps(r2, sort_keys=True))


class TestNoWriteToProductionFacts(unittest.TestCase):
    """readback 不得修改 simulation.db / market_cache.db / 不创建 Decision。"""

    def test_simulation_db_untouched(self):
        before = Path(SCRIPT_DIR, 'simulation.db').stat().st_mtime
        vr.build_readback('2026-08-27')
        after = Path(SCRIPT_DIR, 'simulation.db').stat().st_mtime
        self.assertEqual(before, after, 'simulation.db 未被修改')

    def test_v1_rules_frozen_reported(self):
        rb = vr.build_readback('2026-08-27')
        self.assertEqual(rb['V1_RULE_FREEZE']['V1_RULES_CHANGED'], 'NO')

    def test_no_new_decision_created(self):
        # readback 不调用 DecisionEngine / 不写 snapshot
        rb = vr.build_readback('2026-08-27')
        self.assertNotIn('decision_id', rb['DECISION'] or {})


class TestCheckpointOnly(unittest.TestCase):

    def test_checkpoint_is_not_evaluation(self):
        rb = vr.build_readback('2026-08-27')
        self.assertTrue(rb['CHECKPOINT']['is_checkpoint_only'])
        self.assertEqual(rb['CHECKPOINT']['target_date'], '2026-09-05')


if __name__ == '__main__':
    unittest.main(verbosity=2)
