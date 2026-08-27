#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 8-K1 测试：Stop-Loss Snapshot Persistence Hardening。
覆盖：persist/verify/retry/idempotency/fail-safe/daily reconciliation。
"""
import os
import sys
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, SCRIPT_DIR)


def _make_decision(symbol='600001', action='SELL'):
    from decision.engine import DecisionEngine
    from decision.adapters import position_ctx
    eng = DecisionEngine(strategy='v1_double', config_version='k1test', code_version='k1')
    ctx = position_ctx(
        symbol=symbol, name='T', regime_label='震荡', regime_score=50,
        permission={'status': 'ALLOW', 'new_entry': True, 'add_position': True,
                    'reduce_position': True, 'exit_position': True},
        permission_status='ALLOW', data_health='VALID',
        exit_signal=action, exit_triggers=['STOP_LOSS'] if action == 'SELL' else [],
        drawdown=0, position_count=1, current_exposure=0.02,
        current_position=0.02, portfolio_risk='OK')
    return eng.decide(ctx)


class TestPersistenceVerify(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        import decision.snapshot_verify as sv
        self.sv = sv

    def test_persist_then_verified(self):
        dec = _make_decision()
        status, path = self.sv.persist_with_verification(dec, snap_dir=self.tmpdir)
        self.assertEqual(status, 'PERSISTED')
        self.assertTrue(os.path.exists(path))

    def test_snapshot_readable_and_identity_match(self):
        dec = _make_decision('600002')
        status, path = self.sv.persist_with_verification(dec, snap_dir=self.tmpdir)
        d = json.load(open(path))
        self.assertEqual(d['decision_id'], dec.decision_id)
        self.assertEqual(d['symbol'], '600002')
        self.assertEqual(d['action'], 'SELL')
        self.assertTrue(d.get('timestamp'))

    def test_missing_file_detected(self):
        status, err = self.sv.verify_decision_snapshot('nonexistent_id', self.tmpdir)
        self.assertEqual(status, 'FAILED')
        self.assertIn('missing', err)

    def test_malformed_snapshot_detected(self):
        p = os.path.join(self.tmpdir, 'bad_id.json')
        open(p, 'w').write('{not json')
        status, err = self.sv.verify_decision_snapshot('bad_id', self.tmpdir)
        self.assertEqual(status, 'FAILED')
        self.assertIn('malformed', err)

    def test_partial_write_detected_as_malformed(self):
        dec = _make_decision('600003')
        path = os.path.join(self.tmpdir, f'{dec.decision_id}.json')
        with open(path, 'w') as f:
            json.dump(dec.freeze(), f)
            f.flush(); os.fsync(f.fileno())
            f.truncate(len(json.dumps(dec.freeze())) // 2)  # 半截写入
        # 重写为半截 JSON
        raw = json.dumps(dec.freeze())
        with open(path, 'w') as f:
            f.write(raw[:len(raw)//2])
        status, err = self.sv.verify_decision_snapshot(dec.decision_id, self.tmpdir)
        self.assertEqual(status, 'FAILED')

    def test_decision_id_mismatch_detected(self):
        """文件名(A) 与内容 decision_id(B) 不一致 → 必须检测为 FAILED"""
        dec = _make_decision('600004')
        d = dec.freeze(); d['decision_id'] = 'content_other_id'
        path = os.path.join(self.tmpdir, 'filename_a.json')
        json.dump(d, open(path, 'w'))
        status, err = self.sv.verify_decision_snapshot('filename_a', self.tmpdir)
        self.assertEqual(status, 'FAILED')
        self.assertIn('mismatch', err)

    def test_retry_keeps_same_decision_id(self):
        """save 失败一次后重试成功，decision_id 不变、不重算"""
        dec = _make_decision('600005')
        orig_id = dec.decision_id
        calls = {'n': 0}
        real_save = self.sv._snap_module().save_snapshot
        def flaky(decision, snap_dir=None, overwrite=False):
            calls['n'] += 1
            if calls['n'] == 1:
                raise OSError('disk busy (simulated)')
            return real_save(decision, snap_dir=snap_dir, overwrite=overwrite)
        with mock.patch.object(self.sv._snap_module(), 'save_snapshot', side_effect=flaky):
            status, info = self.sv.persist_with_verification(dec, snap_dir=self.tmpdir)
        self.assertEqual(status, 'PERSISTED')
        self.assertEqual(calls['n'], 2, '应重试一次')
        self.assertEqual(dec.decision_id, orig_id, '重试不得改变 decision_id')

    def test_idempotent_existing(self):
        dec = _make_decision('600006')
        s1, p1 = self.sv.persist_with_verification(dec, snap_dir=self.tmpdir)
        s2, p2 = self.sv.persist_with_verification(dec, snap_dir=self.tmpdir)
        self.assertIn(s2, ('PERSISTED_EXISTING', 'PERSISTED'))
        self.assertEqual(p1, p2, '重复运行不得创建第二个文件')
        files = [f for f in os.listdir(self.tmpdir) if '600006' in f]
        self.assertEqual(len(files), 1, '不得产生重复 snapshot')

    def test_failure_message_contains_marker(self):
        msg = self.sv.format_persistence_failure('600007', 'SELL', 'did_123', 'boom')
        self.assertIn('FINAL DECISION PERSISTENCE FAILED', msg)
        self.assertIn('DECISION_PERSISTENCE_FAILED', msg)
        self.assertIn('600007', msg)
        self.assertIn('did_123', msg)

    def test_all_fail_reports_failed(self):
        dec = _make_decision('600008')
        with mock.patch.object(self.sv._snap_module(), 'save_snapshot',
                               side_effect=OSError('readonly fs')):
            status, err = self.sv.persist_with_verification(dec, max_retries=2,
                                                            snap_dir=self.tmpdir)
        self.assertEqual(status, 'FAILED')


class StopLossChainTest(unittest.TestCase):
    """端到端：stop-loss snapshot → Daily Contract 可读（确定性，无 live 依赖）"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        import decision.daily_decision_contract as ddc
        self.ddc = ddc
        self._orig = ddc.SNAP_DIR
        ddc.SNAP_DIR = self.tmp
        self.today = '2026-08-27'

    def tearDown(self):
        self.ddc.SNAP_DIR = self._orig

    def test_daily_reads_stoploss_snapshots(self):
        from decision.contract import gen_decision_id, Decision
        from decision.snapshot_verify import persist_with_verification
        # 构造并落盘一个 canonical STOP_LOSS 快照（受控临时目录，无 live Bitable）
        did = gen_decision_id(symbol='600001', ts=self.today.replace('-', ''))
        dec = Decision(
            decision_id=did, timestamp=f'{self.today}T09:30:00+00:00',
            symbol='600001', name='测试股', action='SELL',
            strategy='v1_double', exit_signal='STOP_LOSS',
            exit_triggers=['STOP_LOSS'], reason_codes=['STOP_LOSS'],
            explanation='deterministic stop-loss test', reference_price=10.0,
            data_snapshot_id='snap_test', config_version='phase9b3', code_version='test',
        )
        st, path = persist_with_verification(dec, snap_dir=self.tmp)
        self.assertIn(st, ('PERSISTED', 'PERSISTED_EXISTING'))
        snaps = self.ddc.load_today_snapshots(self.today)
        self.assertGreaterEqual(len(snaps), 1, 'stop-loss 快照必须能被 Daily Contract 读到')
        ids = {s['decision_id'] for s in snaps}
        self.assertIn(did, ids, '已落盘的 stop-loss 决策必须出现在 Daily 读取结果中')

    def test_no_executed_outcome_from_safe_run(self):
        conn = sqlite3.connect(f"file:{os.path.join(SCRIPT_DIR,'simulation.db')}?mode=ro", uri=True)
        n = conn.execute("SELECT COUNT(*) FROM trades WHERE decision_id IS NOT NULL AND status='EXECUTED'").fetchone()[0]
        conn.close()
        self.assertEqual(n, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
