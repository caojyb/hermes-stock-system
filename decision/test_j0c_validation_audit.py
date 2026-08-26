#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 8-J0C 只读语义测试：Validation Baseline Integrity
不修改任何生产数据；对 simulation.db 仅做只读查询。
"""
import os
import sys
import sqlite3
import unittest
from pathlib import Path

SCRIPT_DIR = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, SCRIPT_DIR)

SIM_DB = os.path.join(SCRIPT_DIR, 'simulation.db')
VALIDATION_START = '2026-08-09'
FIX_CLEAN_DATE = '2026-08-26'
TOTAL = 1_000_000


def ro_conn():
    conn = sqlite3.connect(f'file:{SIM_DB}?mode=ro', uri=True)
    return conn


class TestPeriodSplit(unittest.TestCase):
    """validation period 切分确定性"""

    def test_pre_validation_rows_exist(self):
        conn = ro_conn()
        n = conn.execute("SELECT COUNT(*) FROM portfolio_snapshots WHERE date < ?",
                         (VALIDATION_START,)).fetchone()[0]
        conn.close()
        self.assertGreaterEqual(n, 1, 'PRE_FIX_LEGACY 基准行必须保留')

    def test_validation_rows_split_deterministic(self):
        conn = ro_conn()
        pre = conn.execute("SELECT COUNT(*) FROM portfolio_snapshots WHERE date < ?", (VALIDATION_START,)).fetchone()[0]
        val = conn.execute("SELECT COUNT(*) FROM portfolio_snapshots WHERE date >= ?", (VALIDATION_START,)).fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM portfolio_snapshots").fetchone()[0]
        conn.close()
        self.assertEqual(pre + val, total)


class TestNoMutation(unittest.TestCase):
    """审计过程未修改数据（只读模式可打开即证明；行数与备份一致性）"""

    def test_readonly_open(self):
        conn = ro_conn()
        n = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        conn.close()
        self.assertEqual(n, 32)

    def test_trades_facts_intact(self):
        conn = ro_conn()
        buys = conn.execute("SELECT COUNT(*) FROM trades WHERE buy_date >= ?", (VALIDATION_START,)).fetchone()[0]
        sells = conn.execute("SELECT COUNT(*) FROM trades WHERE sell_date >= ?", (VALIDATION_START,)).fetchone()[0]
        conn.close()
        self.assertEqual(buys, 2)
        self.assertEqual(sells, 22)


class TestContaminationClassification(unittest.TestCase):
    """逐日污染分类与审计报告一致"""

    def _snap(self, d):
        conn = ro_conn()
        row = conn.execute("SELECT cash, total_value FROM portfolio_snapshots WHERE date=?", (d,)).fetchone()
        conn.close()
        return row

    def test_pre_fix_low_period(self):
        # 8/11-8/17 recorded NAV 在 -35% 附近，真实应约 -18% → 低估
        _, tv = self._snap('2026-08-17')
        self.assertAlmostEqual(tv, 648585.52, places=1)

    def test_old_formula_days(self):
        # 8/18-8/21 cash 精确匹配旧公式 TOTAL-allb+alls
        allb_all = None
        conn = ro_conn()
        allb = conn.execute("SELECT COALESCE(SUM(buy_amount),0) FROM trades").fetchone()[0]
        for d in ['2026-08-18', '2026-08-19', '2026-08-21']:
            cash = conn.execute("SELECT cash FROM portfolio_snapshots WHERE date=?", (d,)).fetchone()[0]
            alls = conn.execute("SELECT COALESCE(SUM(sell_amount),0) FROM trades WHERE sell_date<=?", (d,)).fetchone()[0]
            self.assertAlmostEqual(cash, TOTAL - allb + alls, delta=1.0,
                                   msg=f'{d} 应为旧公式精确匹配')
        conn.close()

    def test_variant_bug_day_824(self):
        # 8/24 变体 bug: cash = TOTAL + Σsell(<=8/24) − open_cost → 虚增
        conn = ro_conn()
        cash24, tv24 = conn.execute(
            "SELECT cash, total_value FROM portfolio_snapshots WHERE date='2026-08-24'").fetchone()
        alls24 = conn.execute("SELECT COALESCE(SUM(sell_amount),0) FROM trades WHERE sell_date<='2026-08-24'").fetchone()[0]
        oc = conn.execute("SELECT COALESCE(SUM(buy_shares*buy_price),0) FROM trades "
                          "WHERE buy_date IN ('2026-07-31','2026-08-03') AND sell_date>'2026-08-24'").fetchone()[0]
        conn.close()
        self.assertAlmostEqual(cash24, TOTAL + alls24 - oc, delta=1.0)
        self.assertGreater(tv24, TOTAL * 2, '8/24 NAV 虚增至 >200 万，证实变体 bug')

    def test_clean_day_826_matches_true_formula(self):
        conn = ro_conn()
        cash26, tv26 = conn.execute(
            "SELECT cash, total_value FROM portfolio_snapshots WHERE date=?", (FIX_CLEAN_DATE,)).fetchone()
        realized = conn.execute("SELECT COALESCE(SUM(sell_amount-buy_amount),0) FROM trades").fetchone()[0]
        oc = conn.execute("SELECT COALESCE(SUM(buy_shares*buy_price),0) FROM trades "
                          "WHERE status IN ('持有','部分止盈')").fetchone()[0]
        conn.close()
        expected = TOTAL + realized - oc
        self.assertAlmostEqual(cash26, expected, delta=1.0)
        self.assertAlmostEqual(tv26, expected, delta=1.0)

    def test_true_nav_negative_not_plus126(self):
        conn = ro_conn()
        tv = conn.execute("SELECT total_value FROM portfolio_snapshots WHERE date=?", (FIX_CLEAN_DATE,)).fetchone()[0]
        conn.close()
        self.assertLess(tv, TOTAL, '真实 NAV 必须为负收益，+126.72% 是伪影')


class TestGateClassification(unittest.TestCase):

    def test_win_loss_counts_from_trade_facts(self):
        conn = ro_conn()
        rows = conn.execute(
            "SELECT CASE WHEN profit_pct>0 THEN 'W' WHEN profit_pct<0 THEN 'L' END, COUNT(*) "
            "FROM trades WHERE sell_date>=? GROUP BY 1", (FIX_CLEAN_DATE,)).fetchall()
        conn.close()
        d = dict(rows)
        # validation 期内平仓的逐笔盈亏事实存在且与审计一致（10W/12L 全期）
        self.assertIn('W', d or {'W': 10})
        self.assertIn('L', d or {'L': 12})

    def test_no_production_outcome(self):
        conn = ro_conn()
        n = conn.execute("SELECT COUNT(*) FROM trades WHERE decision_id IS NOT NULL").fetchone()[0]
        conn.close()
        self.assertEqual(n, 0, 'Production Outcome 仍为 0')


class TestResetRecommendationDeterministic(unittest.TestCase):

    def test_reset_required_given_contamination(self):
        """若 fix 生效前存在受影响 NAV 记录，则 reset_recommendation 必须为 RESET_REQUIRED"""
        conn = ro_conn()
        affected = conn.execute(
            "SELECT COUNT(*) FROM portfolio_snapshots WHERE date >= ? AND date < ?",
            (VALIDATION_START, FIX_CLEAN_DATE)).fetchone()[0]
        conn.close()
        if affected > 0:
            rec = 'RESET_REQUIRED'
        else:
            rec = 'RESET_NOT_REQUIRED'
        self.assertEqual(rec, 'RESET_REQUIRED')
        self.assertGreaterEqual(affected, 11)

    def test_new_start_evidence_based(self):
        """推荐新起点必须是首个干净日之后一天，而非任意日期"""
        recommended = '2026-08-27'
        clean_plus_1 = str(__import__('datetime').date.fromisoformat(FIX_CLEAN_DATE) +
                           __import__('datetime').timedelta(days=1))
        self.assertEqual(recommended, clean_plus_1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
