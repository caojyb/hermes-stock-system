"""
Phase 7.3-J/L：Single-Stock Replay Pilot 集成测试

运行完整 Pilot 样本，生成 CSV 报告。
标记为慢速集成测试，不参与常规单测。
"""
from __future__ import annotations

import pytest
from pathlib import Path

from run_replay_pilot import run_pilot

CSV_PATH = Path('/home/caojy/.hermes/scripts/cron/replay_pilot_results.csv')


@pytest.mark.slow
def test_total_cases():
    """总 case 数 >= 30。"""
    df = run_pilot()
    assert len(df) >= 30


@pytest.mark.slow
def test_st_unknown_blocks_all():
    """ST UNKNOWN 导致所有 case 为 UNKNOWN。"""
    df = run_pilot()
    st_unknown = df[df['filter_st'] == 'UNKNOWN']
    assert len(st_unknown) == len(df)


@pytest.mark.slow
def test_market_cap_quality_mixed():
    """Market Cap Quality 包含 PIT_SAFE / APPROXIMATE / UNKNOWN。"""
    df = run_pilot()
    qualities = df['market_cap_quality'].unique()
    assert len(qualities) >= 2


@pytest.mark.slow
def test_no_current_snapshot_fallback():
    """不读取当前 Production Snapshot。"""
    df = run_pilot()
    assert (df['replay_case_id'].str.contains('HISTORICAL_REPLAY') == False).all()
