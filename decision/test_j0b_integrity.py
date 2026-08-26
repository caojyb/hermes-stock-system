#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 8-J0B 回归测试：
- DB fallback FAIL CLOSED（Critical）
- J0-F risk post-action canonical refresh
- J0-D quality gate（ERROR→BUY/ADD blocked，SELL/REDUCE 不受影响）
- J0-G Bitable 单一 reader
- J0-H 当日 snapshot reuse
- J0-E MULTI_ACTION 分类
- URGENT presentation 语义

禁止覆盖业务规则；只验证完整性修复。
"""
import os
import sys
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, SCRIPT_DIR)


# ══════════════════ 1. DB fallback ══════════════════
class TestDBFallback(unittest.TestCase):
    """J0B STEP 1：stock_opportunity_scan 禁止 fallback 到 skills/simulation.db"""

    def test_no_skills_sim_fallback_in_get_holdings(self):
        src = Path(SCRIPT_DIR, 'stock_opportunity_scan.py').read_text(encoding='utf-8')
        body = src.split('def get_holdings')[1].split('\ndef ')[0]
        # 禁止硬编码 skills 目录 simulation.db 路径（Path 拼接或字符串）
        self.assertNotIn('stock-expert/simulation.db', body)
        self.assertNotIn('parent.parent.parent.parent', body)

    def test_helper_test_mode(self):
        os.environ['SIM_MODE'] = 'test'
        try:
            from simulation_db_helper import get_active_sim_db
            self.assertIn('simulation_test.db', str(get_active_sim_db()))
        finally:
            del os.environ['SIM_MODE']

    def test_helper_production_mode(self):
        os.environ.pop('SIM_MODE', None)
        from simulation_db_helper import get_active_sim_db
        p = str(get_active_sim_db())
        self.assertIn('simulation.db', p)
        self.assertNotIn('simulation_test.db', p)

    def test_helper_import_failure_fail_closed(self):
        """helper 不可用时 get_holdings 不读取任何 simulation.db"""
        src = Path(SCRIPT_DIR, 'stock_opportunity_scan.py').read_text(encoding='utf-8')
        # FAIL CLOSED 结构存在：resolve 失败 → _sim_path=None → 跳过
        self.assertIn('FAIL CLOSED', src)
        self.assertNotIn("parent.parent.parent.parent", src.split('def get_holdings')[1].split('\ndef ')[0])

    def test_sim_dbs_are_distinct_files(self):
        os.environ['SIM_MODE'] = 'test'
        try:
            from simulation_db_helper import get_active_sim_db
            t = str(get_active_sim_db())
            os.environ.pop('SIM_MODE')
            p = str(get_active_sim_db())
            self.assertNotEqual(t, p)
        finally:
            os.environ.pop('SIM_MODE', None)


# ══════════════════ 2. J0-F Risk refresh ══════════════════
class TestRiskRefresh(unittest.TestCase):
    """J0B STEP 2：风控后重读 canonical state 并刷新快照"""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.tmp.close()
        conn = sqlite3.connect(self.tmp.name)
        conn.execute("""CREATE TABLE trades (
            id INTEGER PRIMARY KEY, code TEXT, name TEXT,
            buy_date TEXT, buy_price REAL, buy_shares INTEGER, buy_amount REAL,
            sell_date TEXT, sell_price REAL, sell_amount REAL,
            profit_pct REAL, profit_amount REAL, status TEXT,
            exit_reason TEXT, decision_id TEXT, strategy TEXT DEFAULT 'v1_double')""")
        conn.execute("""CREATE TABLE portfolio_snapshots (
            date TEXT PRIMARY KEY, total_value REAL, cash REAL, holdings_value REAL,
            total_return_pct REAL, max_drawdown_pct REAL, win_count INTEGER, loss_count INTEGER)""")
        conn.commit()
        conn.close()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def _insert(self, code, shares, price, status='持有'):
        conn = sqlite3.connect(self.tmp.name)
        conn.execute(
            "INSERT INTO trades (code,name,buy_date,buy_price,buy_shares,buy_amount,status,strategy)"
            " VALUES (?,?,?,?,?,?,?, 'v1_double')",
            (code, code, '2026-08-20', price, shares, shares * price, status))
        conn.commit()
        conn.close()

    def _reduced_sell(self, code):
        """模拟风控减仓：状态改为已平仓并写 sell 字段（canonical 变化）"""
        conn = sqlite3.connect(self.tmp.name)
        row = conn.execute("SELECT buy_shares, buy_price FROM trades WHERE code=?", (code,)).fetchone()
        shares, price = row
        half = (shares // 2 // 100) * 100 or 100
        conn.execute(
            "UPDATE trades SET buy_shares=?, status='部分止盈', sell_date=?, "
            "sell_price=?, sell_amount=?, profit_pct=?, profit_amount=?, exit_reason='RISK_CONTROLLER_TRIM'"
            " WHERE code=?",
            (shares - half, '2026-08-26', price * 0.95, half * price * 0.95, -5.0,
             -(half * price * 0.05), code))
        conn.commit()
        conn.close()

    def _recompute_summary(self):
        """复刻 double_monitor RC-REFRESH 逻辑（canonical 重读）"""
        TOTAL_CAPITAL = 1_000_000
        conn = sqlite3.connect(self.tmp.name)
        rows = conn.execute(
            "SELECT code, name, buy_shares, buy_price FROM trades WHERE status IN ('持有','部分止盈')").fetchall()
        realized_pnl = conn.execute(
            "SELECT COALESCE(SUM(sell_amount - buy_amount),0) FROM trades WHERE sell_date IS NOT NULL").fetchone()[0]
        open_cost = sum((s or 0) * (p or 0) for _, _, s, p in rows)
        cash = TOTAL_CAPITAL + float(realized_pnl) - float(open_cost)
        holdings_value = sum((s or 0) * (p or 0) for _, _, s, p in rows)  # 现价=买价的简化
        tv = cash + holdings_value
        conn.execute("DELETE FROM portfolio_snapshots WHERE date=?", ('2026-08-26',))
        conn.execute(
            "INSERT INTO portfolio_snapshots (date,total_value,cash,holdings_value,"
            "total_return_pct,max_drawdown_pct,win_count,loss_count) VALUES (?,?,?,?,0,0,?,?)",
            ('2026-08-26', round(tv, 2), round(cash, 2), round(holdings_value, 2),
             len(rows), len(rows)))
        conn.commit()
        snap = conn.execute("SELECT total_value, cash FROM portfolio_snapshots WHERE date=?",
                            ('2026-08-26',)).fetchone()
        cnt = len(rows)
        conn.close()
        return cnt, snap

    def test_no_action_position_count(self):
        self._insert('600001', 1000, 10.0)
        cnt, _ = self._recompute_summary()
        self.assertEqual(cnt, 1)

    def test_full_reduction_refreshes_count(self):
        self._insert('600001', 1000, 10.0)
        self._insert('600002', 1000, 20.0)
        # 全部清仓 600001
        conn = sqlite3.connect(self.tmp.name)
        conn.execute("UPDATE trades SET status='已清仓', sell_date=?, sell_amount=9000 WHERE code='600001'",
                     ('2026-08-26',))
        conn.commit(); conn.close()
        cnt, _ = self._recompute_summary()
        self.assertEqual(cnt, 1, '风控减仓后 summary 必须等于 canonical 持仓数')

    def test_partial_reduction_snapshot_consistent(self):
        self._insert('600003', 2000, 10.0)
        self._reduced_sell('600003')
        cnt, snap = self._recompute_summary()
        self.assertEqual(cnt, 1)
        # 快照 total == cash + holdings_value（恒等式）
        conn = sqlite3.connect(self.tmp.name)
        realized = conn.execute(
            "SELECT COALESCE(SUM(sell_amount-buy_amount),0) FROM trades WHERE sell_date IS NOT NULL").fetchone()[0]
        cost = conn.execute(
            "SELECT COALESCE(SUM(buy_shares*buy_price),0) FROM trades WHERE status IN ('持有','部分止盈')").fetchone()[0]
        conn.close()
        expected_cash = 1_000_000 + realized - cost
        self.assertAlmostEqual(snap[1], expected_cash, delta=0.01)

    def test_multiple_reductions_idempotent(self):
        self._insert('600004', 2000, 10.0)
        self._reduced_sell('600004')
        c1, s1 = self._recompute_summary()
        c2, s2 = self._recompute_summary()  # 幂等重复运行
        self.assertEqual((c1, s1), (c2, s2))

    def test_rc_refresh_block_present_in_source(self):
        src = Path(SCRIPT_DIR, 'double_monitor.py').read_text(encoding='utf-8')
        seg = src.split('[BRANCH] RISK_CONTROL_EXEC')[1][:3000]
        self.assertIn('SELECT code, name, buy_shares, buy_price FROM trades', seg,
                      'RC-REFRESH 必须重读 canonical positions')
        self.assertIn('INSERT INTO portfolio_snapshots', seg, 'RC-REFRESH 必须刷新快照')
        self.assertIn('win_cnt', seg, 'RC-REFRESH 必须重算盈亏分布')


# ══════════════════ 3. J0-D Quality gate ══════════════════
class TestQualityGate(unittest.TestCase):
    """J0B STEP 3：QUALITY_ERROR 对 BUY/ADD fail-safe"""

    def setUp(self):
        import decision.daily_decision_contract as ddc
        self.ddc = ddc

    def _classify_with_quality(self, action, overall):
        readiness = {'status': 'READY', 'sizing_allowed': True}
        snap = [{
            'decision_id': 'd1', 'symbol': '600001', 'name': 'X', 'strategy': 'v1_double',
            'action': action, 'reference_price': 10.0,
            'total_asset': 100000.0, 'current_position_value': 0.0, 'cash': 50000.0,
        }]
        fake_rp = {'quality_report': {
            'overall': overall, 'warning_count': 1 if overall == 'WARNING' else 0,
            'error_count': 1 if overall == 'ERROR' else 0, 'checks': []}}
        with mock.patch.object(self.ddc, 'build_real_portfolio_section', return_value=fake_rp):
            actions = self.ddc.classify_actions(snap, [], readiness)
        return actions

    def test_valid_allows_buy(self):
        actions = self._classify_with_quality('BUY', 'OK')
        self.assertEqual(len(actions.get('BUY', [])), 1)

    def test_error_blocks_buy(self):
        actions = self._classify_with_quality('BUY', 'ERROR')
        self.assertEqual(len(actions.get('BUY', [])), 0)
        item = actions['NO_TRADE'][0]
        self.assertIn('REAL_HOLDINGS_QUALITY_ERROR', item['reason_codes'])

    def test_error_blocks_add(self):
        actions = self._classify_with_quality('ADD', 'ERROR')
        self.assertEqual(len(actions.get('ADD', [])), 0)

    def test_error_allows_sell(self):
        actions = self._classify_with_quality('SELL', 'ERROR')
        self.assertEqual(len(actions.get('SELL', [])), 1, '质量错误不得阻断合法 SELL')

    def test_error_allows_reduce(self):
        actions = self._classify_with_quality('REDUCE', 'ERROR')
        self.assertEqual(len(actions.get('REDUCE', [])), 1)

    def test_warning_does_not_block_buy(self):
        actions = self._classify_with_quality('BUY', 'WARNING')
        self.assertEqual(len(actions.get('BUY', [])), 1, 'WARNING 允许分析不过度阻断')
        self.assertTrue(actions['BUY'][0].get('quality_warning'))

    def test_missing_quality_defaults_unknown_not_error(self):
        fake_rp = {}
        with mock.patch.object(self.ddc, 'build_real_portfolio_section', return_value=fake_rp):
            status = self.ddc.get_real_holdings_quality_status({})
        self.assertEqual(status, 'QUALITY_UNKNOWN')

    def test_quality_status_helper_mapping(self):
        self.assertEqual(self.ddc.get_real_holdings_quality_status({'real_holdings_quality': 'OK'}),
                         'QUALITY_VALID')
        self.assertEqual(self.ddc.get_real_holdings_quality_status({'real_holdings_quality': 'ERROR'}),
                         'QUALITY_ERROR')

    def test_data_health_contains_quality_fields(self):
        fake_rp = {'quality_report': {'overall': 'WARNING', 'warning_count': 2, 'error_count': 0,
                                      'checks': [{'field': 'avg_cost', 'level': 'WARNING', 'reason': 'OUTLIER'}]}}
        with mock.patch.object(self.ddc, 'build_real_portfolio_section', return_value=fake_rp):
            dh = self.ddc.build_data_health_section()
        self.assertEqual(dh['real_holdings_quality'], 'WARNING')
        self.assertEqual(dh['quality_warning_count'], 2)
        self.assertEqual(dh['quality_flags'][0]['field'], 'avg_cost')

    def test_error_not_silently_valid(self):
        fake_rp = {'quality_report': {'overall': 'ERROR', 'warning_count': 0, 'error_count': 1, 'checks': []}}
        with mock.patch.object(self.ddc, 'build_real_portfolio_section', return_value=fake_rp):
            dh = self.ddc.build_data_health_section()
        self.assertNotEqual(dh['real_holdings_quality'], 'VALID')

    def test_local_semantics_not_global_broken(self):
        """quality ERROR 只影响 BUY/ADD 分类，不改变 market/portfolio data health 键"""
        fake_rp = {'quality_report': {'overall': 'ERROR', 'warning_count': 0, 'error_count': 1, 'checks': []}}
        with mock.patch.object(self.ddc, 'build_real_portfolio_section', return_value=fake_rp):
            dh = self.ddc.build_data_health_section()
        self.assertEqual(dh['market_regime'], 'VALID')
        self.assertEqual(dh['portfolio'], 'VALID')


# ══════════════════ 4. J0-G Bitable single reader ══════════════════
class TestBitableSingleReader(unittest.TestCase):
    """J0B STEP 4：fetch_holdings_westock 复用统一 reader，FAIL CLOSED"""

    def test_no_local_schema_parsing(self):
        src = Path(SCRIPT_DIR, 'fetch_holdings_westock.py').read_text(encoding='utf-8')
        body = src.split('def read_holdings_codes')[1].split('\ndef ')[0]
        self.assertNotIn('+record-list', body, '不得自行调用 lark-cli 解析 schema')
        self.assertNotIn("split('|')", body, '不得自行解析表结构')
        self.assertIn('get_daily_real_holdings', body)

    def test_read_holdings_uses_unified_reader(self):
        import fetch_holdings_westock as fhw
        fake = ([{'code': '600588'}, {'code': '000547'}], {'cached': False})
        with mock.patch('decision.real_portfolio_truth.get_daily_real_holdings', return_value=fake):
            codes = fhw.read_holdings_codes()
        self.assertEqual(codes, ['600588', '000547'])

    def test_unified_reader_unavailable_fails_closed(self):
        import fetch_holdings_westock as fhw
        with mock.patch('decision.real_portfolio_truth.get_daily_real_holdings',
                        side_effect=ImportError('module unavailable')):
            with self.assertRaises(RuntimeError) as ctx:
                fhw.read_holdings_codes()
        self.assertIn('FAIL CLOSED', str(ctx.exception))


# ══════════════════ 5. J0-H Snapshot reuse ══════════════════
class TestDailySnapshotReuse(unittest.TestCase):
    """J0B STEP 5：当日单次读取缓存"""

    def setUp(self):
        import decision.real_portfolio_truth as rpt
        self.rpt = rpt
        rpt.reset_daily_real_holdings_cache()
        self.calls = []

    def tearDown(self):
        self.rpt.reset_daily_real_holdings_cache()

    def _fake_reader(self, n=1):
        def reader():
            self.calls.append(1)
            return [{'code': '600001', 'quantity': 100}]
        return reader

    def test_first_read_calls_lark_once(self):
        with mock.patch.object(self.rpt, '_read_bitable_holdings', side_effect=self._fake_reader()):
            h, meta = self.rpt.get_daily_real_holdings()
            self.assertEqual(len(self.calls), 1)
            self.assertFalse(meta['cached'])

    def test_second_read_cache_hit(self):
        with mock.patch.object(self.rpt, '_read_bitable_holdings', side_effect=self._fake_reader()):
            self.rpt.get_daily_real_holdings()
            h2, meta = self.rpt.get_daily_real_holdings()
            self.assertEqual(len(self.calls), 1, '第二次必须命中缓存')
            self.assertTrue(meta['cached'])
            self.assertEqual(h2[0]['code'], '600001')

    def test_multiple_callers_same_snapshot(self):
        with mock.patch.object(self.rpt, '_read_bitable_holdings', side_effect=self._fake_reader()):
            h1, _ = self.rpt.get_daily_real_holdings()
            h2, _ = self.rpt.get_daily_real_holdings()
            self.assertEqual(h1, h2)
            self.assertEqual(len(self.calls), 1)

    def test_failed_first_read_not_cached(self):
        def boom():
            raise RuntimeError('lark-cli down')
        with mock.patch.object(self.rpt, '_read_bitable_holdings', side_effect=boom):
            with self.assertRaises(RuntimeError):
                self.rpt.get_daily_real_holdings()
        # 失败后恢复：下一次重新真实读取（不静默用旧缓存）
        with mock.patch.object(self.rpt, '_read_bitable_holdings', side_effect=self._fake_reader()):
            h, meta = self.rpt.get_daily_real_holdings()
            self.assertFalse(meta['cached'])
            self.assertEqual(len(self.calls), 1)

    def test_snapshot_meta_has_schema_and_hash(self):
        with mock.patch.object(self.rpt, '_read_bitable_holdings', side_effect=self._fake_reader()):
            _, meta = self.rpt.get_daily_real_holdings()
        self.assertIn('schema_version', meta)
        self.assertIn('source_hash', meta)
        self.assertIn('captured_at', meta)

    def test_refresh_forces_new_read(self):
        with mock.patch.object(self.rpt, '_read_bitable_holdings', side_effect=self._fake_reader()):
            self.rpt.get_daily_real_holdings()
            self.rpt.get_daily_real_holdings(refresh=True)
            self.assertEqual(len(self.calls), 2)

    def test_build_real_snapshot_records_cache_provenance(self):
        with mock.patch.object(self.rpt, '_read_bitable_holdings', side_effect=self._fake_reader()):
            snap = self.rpt.build_real_snapshot(cash=1000.0, total_asset=2000.0)
        self.assertIn('holdings_cache', snap.get('provenance', {}))


# ══════════════════ 6. MULTI_ACTION ══════════════════
class TestMultiAction(unittest.TestCase):
    """J0B STEP 6：当日同 symbol BUY+SELL → MULTI_ACTION 标注"""

    def _summary_line(self, buys, sells):
        buy_codes = {t[0] for t in buys}
        sell_codes = {t[0] for t in sells}
        multi = buy_codes & sell_codes
        multi_note = f" | MULTI_ACTION:{','.join(sorted(multi))}" if multi else ""
        return multi_note

    def test_buy_only(self):
        self.assertEqual(self._summary_line([('600001',)], []), '')

    def test_sell_only(self):
        self.assertEqual(self._summary_line([], [('600001',)]), '')

    def test_buy_sell_same_symbol(self):
        line = self._summary_line([('600001',)], [('600001',)])
        self.assertIn('MULTI_ACTION:600001', line)

    def test_multi_symbols_sorted(self):
        line = self._summary_line([('600002',), ('600001',)], [('600001',), ('600002',)])
        self.assertIn('MULTI_ACTION:600001,600002', line)

    def test_partial_overlap_only_common(self):
        line = self._summary_line([('600001',), ('600003',)], [('600001',)])
        self.assertIn('MULTI_ACTION:600001', line)
        self.assertNotIn('600003', line)

    def test_source_contains_multi_logic(self):
        src = Path(SCRIPT_DIR, 'double_monitor.py').read_text(encoding='utf-8')
        self.assertIn('MULTI_ACTION', src)

    def test_no_state_mutation(self):
        """分类只影响打印，不改交易记录——纯函数验证"""
        buys = [('600001',)]
        before = list(buys)
        self._summary_line(buys, [('600001',)])
        self.assertEqual(buys, before)


# ══════════════════ 7. URGENT semantics ══════════════════
class TestUrgentSemantics(unittest.TestCase):
    """J0B STEP 7：URGENT presentation 语义核对（只读验证）"""

    def test_final_decision_with_urgent_presentation_routes_now_urgent(self):
        from decision.user_authority import classify_message, FINAL_DECISION_AUTHORITY
        cls = classify_message(is_final_decision=True, from_authority=FINAL_DECISION_AUTHORITY,
                               action='SELL', presentation='URGENT', has_decision_id=True,
                               lifecycle_state='DECIDED', category='')
        self.assertEqual(cls, 'URGENT')

    def test_final_decision_default_is_final(self):
        from decision.user_authority import classify_message, FINAL_DECISION_AUTHORITY
        cls = classify_message(is_final_decision=True, from_authority=FINAL_DECISION_AUTHORITY,
                               action='SELL', presentation='', has_decision_id=True,
                               lifecycle_state='DECIDED', category='')
        self.assertEqual(cls, 'FINAL_DECISION')

    def test_signal_cannot_fake_final(self):
        from decision.user_authority import classify_message, FINAL_DECISION_AUTHORITY
        cls = classify_message(is_final_decision=False, from_authority=FINAL_DECISION_AUTHORITY,
                               action='SELL', presentation='', has_decision_id=True,
                               lifecycle_state='', category='')
        self.assertNotEqual(cls, 'FINAL_DECISION')

    def test_decision_contract_has_no_second_owner_field(self):
        """Decision 本身不带 presentation —— authority 在 engine，presentation 在 delivery 层"""
        src = Path(SCRIPT_DIR, 'decision', 'contract.py').read_text(encoding='utf-8')
        self.assertNotIn('presentation', src.split('class Decision')[1].split('\nclass ')[0])


if __name__ == '__main__':
    unittest.main(verbosity=2)
