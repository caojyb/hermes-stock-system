#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 8-J0D 测试：Validation Baseline Reset 语义验证。
全部只读；断言历史数据未被删除/修改、边界定义确定性、初始状态与 DB 真实值一致。
"""
import os
import sys
import sqlite3
import unittest
from pathlib import Path

SCRIPT_DIR = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, SCRIPT_DIR)

SIM_DB = os.path.join(SCRIPT_DIR, 'simulation.db')
BACKUP_823 = '/mnt/hgfs/clawshare/hermesdata/db/daily/simulation_20260823.db'


def ro_conn(path=SIM_DB):
    return sqlite3.connect(f'file:{path}?mode=ro', uri=True)


class TestBaselineDefinition(unittest.TestCase):

    def test_new_start_is_20260827(self):
        from decision.validation_baseline import VALIDATION_START_DATE
        self.assertEqual(VALIDATION_START_DATE, '2026-08-27')

    def test_old_period_preserved_in_metadata(self):
        from decision.validation_baseline import PRE_FIX_VALIDATION_START, PRE_FIX_VALIDATION_END
        self.assertEqual((PRE_FIX_VALIDATION_START, PRE_FIX_VALIDATION_END),
                         ('2026-08-09', '2026-08-26'))

    def test_initial_state_matches_source_of_truth(self):
        """初始状态必须来自 8/26 收盘真实值，不允许第二套手工数据"""
        from decision.validation_baseline import (INITIAL_CASH, INITIAL_HOLDINGS_VALUE,
                                                 INITIAL_TOTAL_ASSET)
        conn = ro_conn()
        cash, hv, tv = conn.execute(
            "SELECT cash, holdings_value, total_value FROM portfolio_snapshots "
            "WHERE date='2026-08-26'").fetchone()
        open_pos = conn.execute(
            "SELECT COUNT(*) FROM trades WHERE status IN ('持有','部分止盈')").fetchone()[0]
        conn.close()
        self.assertEqual(open_pos, 0)
        self.assertAlmostEqual(INITIAL_CASH, cash, places=2)
        self.assertAlmostEqual(INITIAL_HOLDINGS_VALUE, hv, places=2)
        self.assertAlmostEqual(INITIAL_TOTAL_ASSET, tv, places=2)


class TestHistoricalDataIntact(unittest.TestCase):

    def test_legacy_trades_still_exist(self):
        conn = ro_conn()
        n = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        pre = conn.execute("SELECT COUNT(*) FROM trades WHERE buy_date < '2026-08-09'").fetchone()[0]
        conn.close()
        self.assertEqual(n, 32)
        self.assertGreaterEqual(pre, 10, 'PRE_FIX_LEGACY trades 必须保留')

    def test_legacy_nav_rows_still_exist(self):
        conn = ro_conn()
        n = conn.execute("SELECT COUNT(*) FROM portfolio_snapshots WHERE date < '2026-08-27'").fetchone()[0]
        contaminated = conn.execute(
            "SELECT COUNT(*) FROM portfolio_snapshots WHERE date >= '2026-08-09' AND date <= '2026-08-26'"
        ).fetchone()[0]
        conn.close()
        self.assertGreaterEqual(n, 13)
        self.assertEqual(contaminated, 12, '12 条旧期间 NAV 记录（8/11–8/26）保留为 legacy，不删除')

    def test_backup_cross_check(self):
        """主库历史行与 8/23 周备份一致 → reset 未触碰历史"""
        if not os.path.exists(BACKUP_823):
            self.skipTest('周备份不可达')
        main = ro_conn()
        bak = ro_conn(BACKUP_823)
        m = main.execute("SELECT date, cash, total_value FROM portfolio_snapshots "
                         "WHERE date <= '2026-08-21' ORDER BY date").fetchall()
        b = bak.execute("SELECT date, cash, total_value FROM portfolio_snapshots "
                        "WHERE date <= '2026-08-21' ORDER BY date").fetchall()
        main.close(); bak.close()
        self.assertEqual(m, b)


class TestPeriodFilter(unittest.TestCase):

    def test_is_validation_trade_boundary(self):
        from decision.validation_baseline import is_validation_trade
        self.assertFalse(is_validation_trade('2026-08-26'))
        self.assertTrue(is_validation_trade('2026-08-27'))
        self.assertTrue(is_validation_trade('2026-09-05'))

    def test_gate_insufficient_before_thresholds(self):
        from decision.validation_baseline import validation_gate_status
        self.assertEqual(validation_gate_status(19, 10), 'DATA_INSUFFICIENT')
        self.assertEqual(validation_gate_status(20, 9), 'DATA_INSUFFICIENT')
        self.assertEqual(validation_gate_status(20, 10), 'EVALUABLE')

    def test_gate_values_not_relaxed(self):
        from decision.validation_baseline import MIN_TRADING_DAYS, MIN_VALIDATION_TRADES
        self.assertEqual((MIN_TRADING_DAYS, MIN_VALIDATION_TRADES), (20, 10))


class TestUnchangedItems(unittest.TestCase):

    def test_v1_params_untouched_in_config(self):
        p = Path('/home/caojy/.hermes/skills/stock/stock-expert/stock_strategy_config.py')
        src = p.read_text(encoding='utf-8')
        self.assertIn('"vol_ratio_min": 2.7', src)

    def test_auto_trading_off_no_executed(self):
        conn = ro_conn()
        n = conn.execute("SELECT COUNT(*) FROM trades WHERE decision_id IS NOT NULL AND status='EXECUTED'").fetchone()[0]
        conn.close()
        self.assertEqual(n, 0)

    def test_reset_doc_exists_with_statement(self):
        doc = Path(SCRIPT_DIR, 'docs/audit/VALIDATION_BASELINE_RESET_20260827.md').read_text(encoding='utf-8')
        self.assertIn('Historical data was NOT deleted or modified', doc)
        self.assertIn('781,471.12', doc.replace('781471.12', '781,471.12'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
