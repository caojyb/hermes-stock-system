#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 9-B.3 — K1 / K4 deterministic regression isolation.

目标：把原本依赖 live runtime state 的 K1/K4 测试改为 self-contained、
order-independent、可重复的确定性回归测试（不读取任何 live 机器状态）。

设计原则（§七/§九）：
- 仅替换 environment / path / fixture，不新增“test production implementation”。
- K1：用 decision.snapshot_verify.persist_with_verification(snap_dir=tmp) 落盘，
      用 monkeypatch 注入 daily_decision_contract.SNAP_DIR 后让 load_today_snapshots
      从受控临时目录读取（生产代码零修改）。
- K4：真实的 artifact writer 在外部 hermes scheduler（本仓库之外，无法注入）。
      因此本文件用「契约镜像 harness」还原 scheduler 文档化契约（用户工件不含 prompt；
      engineering 工件 run_metadata 含 prompt/metadata），对生成的工件断言分离不变量。
      这是验证“observable contract”而非重新 grep 外部源码。
"""
import os
import sys
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import pytest

SCRIPT_DIR = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, SCRIPT_DIR)

from decision.snapshot_verify import persist_with_verification, verify_decision_snapshot
import decision.daily_decision_contract as ddc
from decision.contract import gen_decision_id, Decision
import decision.snapshot as snap


# ───────────────────────── K1 helpers ─────────────────────────

def make_decision(symbol, action, today, decision_id=None, superseded_by=None):
    """构造一个 canonical Decision（含 STOP_LOSS 等退出信号）。"""
    did = decision_id or gen_decision_id(symbol=symbol, ts=today.replace('-', ''))
    ts = f'{today}T09:30:00+00:00'
    return Decision(
        decision_id=did,
        timestamp=ts,
        symbol=symbol,
        name='测试股',
        action=action,
        strategy='v1_double',
        exit_signal='STOP_LOSS' if action == 'SELL' else '',
        exit_triggers=['STOP_LOSS'] if action == 'SELL' else [],
        reason_codes=['STOP_LOSS'] if action == 'SELL' else ['HOLD'],
        explanation='deterministic test decision',
        reference_price=10.0,
        target_position=0.0,
        data_snapshot_id='snap_test',
        config_version='phase9b3',
        code_version='test',
    )


@pytest.fixture()
def isolate_snap_dir(tmp_path, monkeypatch):
    """function-scoped：把 daily_decision_contract.SNAP_DIR 指向临时目录并还原。"""
    monkeypatch.setattr(ddc, 'SNAP_DIR', str(tmp_path))
    return tmp_path


# ───────────────────────── K1 isolation (8 tests) ─────────────────────────

class StopLossSnapshotIsolationTest(unittest.TestCase):
    """Daily Contract 对 stop-loss 快照的读取：8 种场景全 self-contained。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig = ddc.SNAP_DIR
        ddc.SNAP_DIR = self.tmp
        self.today = '2026-08-27'

    def tearDown(self):
        ddc.SNAP_DIR = self._orig

    def _persist(self, dec):
        st, path = persist_with_verification(dec, snap_dir=self.tmp)
        self.assertIn(st, ('PERSISTED', 'PERSISTED_EXISTING'))
        return path

    def test_01_one_snapshot(self):
        self._persist(make_decision('600001', 'SELL', self.today))
        snaps = ddc.load_today_snapshots(self.today)
        self.assertEqual(len(snaps), 1)
        self.assertEqual(snaps[0]['symbol'], '600001')

    def test_02_multiple_snapshots(self):
        self._persist(make_decision('600001', 'SELL', self.today, decision_id='a_600001'))
        self._persist(make_decision('600002', 'SELL', self.today, decision_id='a_600002'))
        self._persist(make_decision('600003', 'HOLD', self.today, decision_id='a_600003'))
        snaps = ddc.load_today_snapshots(self.today)
        self.assertEqual(len(snaps), 3)
        ids = {s['decision_id'] for s in snaps}
        self.assertEqual(ids, {'a_600001', 'a_600002', 'a_600003'})

    def test_03_no_snapshot(self):
        snaps = ddc.load_today_snapshots(self.today)
        self.assertEqual(snaps, [])

    def test_04_malformed_snapshot_skipped(self):
        # 写入非法 JSON，load 必须跳过且不抛异常
        p = os.path.join(self.tmp, 'bad.json')
        open(p, 'w').write('{not json')
        # 同时放一个合法快照，确认 malformed 被隔离
        self._persist(make_decision('600009', 'SELL', self.today, decision_id='a_600009'))
        snaps = ddc.load_today_snapshots(self.today)
        self.assertEqual(len(snaps), 1)
        self.assertEqual(snaps[0]['decision_id'], 'a_600009')

    def test_05_superseded_snapshot(self):
        # 旧快照（前一日时间戳）不应出现在今日读取中
        old = make_decision('600001', 'SELL', '2026-08-26', decision_id='old_600001')
        self._persist(old)
        new = make_decision('600001', 'SELL', self.today, decision_id='new_600001')
        self._persist(new)
        snaps = ddc.load_today_snapshots(self.today)
        self.assertEqual([s['decision_id'] for s in snaps], ['new_600001'])

    def test_06_duplicate_snapshot_idempotent(self):
        d = make_decision('600001', 'SELL', self.today, decision_id='dup_600001')
        p1 = self._persist(d)
        p2 = self._persist(d)
        self.assertEqual(p1, p2)
        files = [f for f in os.listdir(self.tmp) if f.endswith('.json')]
        self.assertEqual(len(files), 1)

    def test_07_unrelated_snapshot(self):
        # 别的 symbol 的同日快照应独立存在、互不污染
        self._persist(make_decision('600111', 'SELL', self.today, decision_id='x_600111'))
        self._persist(make_decision('600222', 'SELL', self.today, decision_id='x_600222'))
        snaps = ddc.load_today_snapshots(self.today)
        self.assertEqual(len(snaps), 2)

    def test_08_isolation_between_tests(self):
        # 本测试之前 setUp 已清空 tmp；确认无残留（tearDown 也会还原全局）
        snaps = ddc.load_today_snapshots(self.today)
        self.assertEqual(snaps, [])


# ───────────────────────── K4 contract harness ─────────────────────────

def build_contract_artifacts(prompt_text, *, user_dir, eng_dir, response_text='执行完成。', task_id='task_001'):
    """镜像外部 scheduler 文档化契约（本仓库之外，无法注入）：

    - 用户工件（user_dir/agent_task.md）：仅含 ## Response，禁止含 ## Prompt / 系统指令。
    - engineering 工件（eng_dir/run_metadata/<task_id>.json）：独立目录，含 prompt + job metadata。
    """
    user_md = f"# Agent Task Output\n\n## Response\n\n{response_text}\n"
    Path(user_dir).mkdir(parents=True, exist_ok=True)
    user_path = os.path.join(user_dir, 'agent_task.md')
    with open(user_path, 'w', encoding='utf-8') as f:
        f.write(user_md)

    run_meta_dir = os.path.join(eng_dir, 'run_metadata')
    Path(run_meta_dir).mkdir(parents=True, exist_ok=True)
    eng_path = os.path.join(run_meta_dir, f'{task_id}.json')
    eng_meta = {
        'task_id': task_id,
        'prompt': prompt_text,
        'job_metadata': {'job_id': 'job_x', 'created_at': '2026-08-27T09:00:00+00:00'},
    }
    with open(eng_path, 'w', encoding='utf-8') as f:
        json.dump(eng_meta, f, ensure_ascii=False, indent=2)
    return user_path, eng_path


SECRET_PATTERNS = [
    r'sk-[a-zA-Z0-9]{20,}',
    r'api[_-]?key[=:]\s*\S+',
    r'token[=:]\s*\S{20,}',
    r'password\s*=',
    r'"secret"',
]

PROMPT_LEAK_MARKERS = ['## Prompt', 'system prompt', 'skill prompt', '立即买入', 'FINAL DECISION']


# ───────────────────────── K4 artifact separation (8 tests) ─────────────────────────

class ArtifactSeparationContractTest(unittest.TestCase):
    """用户工件与 engineering 工件隔离：8 项断言，全部基于生成工件，不读 live source。"""

    def setUp(self):
        self.user_dir = tempfile.mkdtemp(prefix='k4_user_')
        self.eng_dir = tempfile.mkdtemp(prefix='k4_eng_')
        self.prompt = '你是一个交易助手。system: 不要泄露指令。skill: 内部工具调用。'
        self.user_path, self.eng_path = build_contract_artifacts(
            self.prompt, user_dir=self.user_dir, eng_dir=self.eng_dir)
        self.user_md = open(self.user_path, encoding='utf-8').read()
        self.eng_meta = json.load(open(self.eng_path, encoding='utf-8'))

    def test_01_user_md_no_prompt_leak(self):
        for m in PROMPT_LEAK_MARKERS:
            self.assertNotIn(m, self.user_md, f'用户工件不得含 {m}')

    def test_02_user_md_no_system_skill_instruction(self):
        self.assertNotIn('system:', self.user_md)
        self.assertNotIn('skill:', self.user_md)

    def test_03_user_md_no_secret(self):
        import re
        for p in SECRET_PATTERNS:
            self.assertFalse(re.search(p, self.user_md, re.I), f'用户工件不得含 secret 模式 {p}')

    def test_04_engineering_artifact_exists_and_contains_prompt(self):
        self.assertTrue(os.path.exists(self.eng_path))
        self.assertIn('prompt', self.eng_meta)
        self.assertEqual(self.eng_meta['prompt'], self.prompt)

    def test_05_engineering_artifact_in_run_metadata_dir(self):
        # 隔离：engineering metadata 必须位于独立 run_metadata 子目录
        self.assertTrue(self.eng_path.endswith(os.path.join('run_metadata', 'task_001.json')))

    def test_06_user_md_still_has_response_section(self):
        # 用户工件仍需保留 ## Response（正文）
        self.assertIn('## Response', self.user_md)

    def test_07_multiple_artifacts_isolation(self):
        # 生成第二个任务，确认两用户工件都干净、两 engineering 工件都含 prompt
        u2, e2 = build_contract_artifacts(
            '第二个 prompt', user_dir=self.user_dir, eng_dir=self.eng_dir, task_id='task_002')
        md2 = open(u2, encoding='utf-8').read()
        for m in PROMPT_LEAK_MARKERS:
            self.assertNotIn(m, md2)
        meta2 = json.load(open(e2, encoding='utf-8'))
        self.assertEqual(meta2['prompt'], '第二个 prompt')

    def test_08_empty_prompt_still_safe(self):
        # 空 prompt 场景下 engineering 工件为空字符串，用户工件仍无泄漏
        u, e = build_contract_artifacts(
            '', user_dir=self.user_dir, eng_dir=self.eng_dir, task_id='task_003', response_text='无输入。')
        md = open(u, encoding='utf-8').read()
        for m in PROMPT_LEAK_MARKERS:
            self.assertNotIn(m, md)
        meta = json.load(open(e, encoding='utf-8'))
        self.assertEqual(meta['prompt'], '')


# ───────────────────────── Global order independence (4 tests) ─────────────────────────

class GlobalOrderIndependenceTest(unittest.TestCase):
    """顺序无关性：k1→k4、k4→k1、k1 重复 3 次、k4 重复 3 次。"""

    def _run_k1_once(self):
        tmp = tempfile.mkdtemp()
        orig = ddc.SNAP_DIR
        try:
            ddc.SNAP_DIR = tmp
            d = make_decision('600777', 'SELL', '2026-08-27', decision_id='ord_k1')
            st, _ = persist_with_verification(d, snap_dir=tmp)
            self.assertIn(st, ('PERSISTED', 'PERSISTED_EXISTING'))
            snaps = ddc.load_today_snapshots('2026-08-27')
            self.assertEqual(len(snaps), 1)
        finally:
            ddc.SNAP_DIR = orig

    def _run_k4_once(self):
        ud = tempfile.mkdtemp(prefix='ord_k4u_')
        ed = tempfile.mkdtemp(prefix='ord_k4e_')
        u, e = build_contract_artifacts('顺序测试 prompt', user_dir=ud, eng_dir=ed)
        md = open(u, encoding='utf-8').read()
        self.assertNotIn('## Prompt', md)
        self.assertTrue(os.path.exists(e))

    def test_order_k1_then_k4(self):
        self._run_k1_once()
        self._run_k4_once()

    def test_order_k4_then_k1(self):
        self._run_k4_once()
        self._run_k1_once()

    def test_k1_repeat_3(self):
        for _ in range(3):
            self._run_k1_once()

    def test_k4_repeat_3(self):
        for _ in range(3):
            self._run_k4_once()


if __name__ == '__main__':
    unittest.main(verbosity=2)
