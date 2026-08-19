"""
Phase 7.3-I：Historical Replay Blocker Impact & Sensitivity Audit 测试
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

DB = Path('/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db')


def load_universe() -> pd.DataFrame:
    """加载当前股票池。"""
    con = sqlite3.connect(str(DB))
    return pd.read_sql('SELECT code, name, is_st, total_mcap FROM stocks', con)


# ---------------------------------------------------------------------------
# V1 Filter Dependency
# ---------------------------------------------------------------------------
class TestV1FilterDependency:
    def test_universe_is_partial(self):
        """Universe 为 PARTIAL（无法识别停牌）。"""
        from audit_replay_blocker_impact import V1_DEPENDENCIES
        dep = next(d for d in V1_DEPENDENCIES if d.name == 'Universe')
        assert 'PARTIAL' in dep.pit_status

    def test_st_is_blocked(self):
        """ST 为 BLOCKED。"""
        from audit_replay_blocker_impact import V1_DEPENDENCIES
        dep = next(d for d in V1_DEPENDENCIES if d.name == 'ST')
        assert 'BLOCKED' in dep.pit_status

    def test_market_cap_is_partial(self):
        """Market Cap 为 PARTIAL。"""
        from audit_replay_blocker_impact import V1_DEPENDENCIES
        dep = next(d for d in V1_DEPENDENCIES if d.name == 'Market Cap 5-90B')
        assert 'PARTIAL' in dep.pit_status

    def test_volume_ratio_is_reconstructable(self):
        """Volume Ratio 为 RECONSTRUCTABLE。"""
        from audit_replay_blocker_impact import V1_DEPENDENCIES
        dep = next(d for d in V1_DEPENDENCIES if d.name == 'Volume Ratio')
        assert 'RECONSTRUCTABLE' in dep.pit_status


# ---------------------------------------------------------------------------
# Market Cap Bounds
# ---------------------------------------------------------------------------
class TestMarketCapBounds:
    def test_in_range_92pct(self):
        """约 92.5% 股票市值在 5-90B 范围内。"""
        from audit_replay_blocker_impact import compute_market_cap_bounds
        universe = load_universe()
        bounds = compute_market_cap_bounds(universe)
        assert bounds['in_range_pct'] > 90
        assert bounds['in_range_pct'] < 95

    def test_borderline_10pct_lt_100(self):
        """10% 边界内的股票应少于 100 只。"""
        from audit_replay_blocker_impact import compute_market_cap_bounds
        universe = load_universe()
        bounds = compute_market_cap_bounds(universe)
        assert bounds['borderline_10pct'] < 100

    def test_no_market_cap_less_than_161(self):
        """无市值数据的股票 ≤ 161 只。"""
        from audit_replay_blocker_impact import compute_market_cap_bounds
        universe = load_universe()
        bounds = compute_market_cap_bounds(universe)
        assert bounds['without_mcap'] <= 161


# ---------------------------------------------------------------------------
# ST Sensitivity
# ---------------------------------------------------------------------------
class TestSTSensitivity:
    def test_current_st_count(self):
        """当前 ST = 0。"""
        df = load_universe()
        st_count = int((df['is_st'] == 1).sum())
        assert st_count == 0

    def test_current_unknown_count(self):
        """当前 UNKNOWN = 0。"""
        df = load_universe()
        unknown_count = int(df['is_st'].isna().sum())
        assert unknown_count == 0

    def test_scenario_a_equals_total(self):
        """Scenario A (ALL NORMAL) = total。"""
        from audit_replay_blocker_impact import compute_st_sensitivity
        universe = load_universe()
        bounds = compute_st_sensitivity(universe)
        assert bounds['scenario_a_normal'] == bounds['total']

    def test_scenario_b_equals_normal(self):
        """Scenario B (ALL ST) = normal_count。"""
        from audit_replay_blocker_impact import compute_st_sensitivity
        universe = load_universe()
        bounds = compute_st_sensitivity(universe)
        assert bounds['scenario_b_st'] == bounds['normal_count']


# ---------------------------------------------------------------------------
# Combined Scenarios
# ---------------------------------------------------------------------------
class TestCombinedScenarios:
    def test_strict_coverage_above_90(self):
        """STRICT coverage > 90%。"""
        from audit_replay_blocker_impact import compute_combined_scenarios
        universe = load_universe()
        combined = compute_combined_scenarios(universe)
        assert combined['strict_coverage_pct'] > 90

    def test_research_coverage_above_90(self):
        """RESEARCH coverage > 90%。"""
        from audit_replay_blocker_impact import compute_combined_scenarios
        universe = load_universe()
        combined = compute_combined_scenarios(universe)
        assert combined['research_coverage_pct'] > 90

    def test_best_case_gte_worst_case(self):
        """Best Case >= Worst Case。"""
        from audit_replay_blocker_impact import compute_combined_scenarios
        universe = load_universe()
        combined = compute_combined_scenarios(universe)
        assert combined['scenario_3_best'] >= combined['scenario_4_worst']


# ---------------------------------------------------------------------------
# Replay Scope Matrix
# ---------------------------------------------------------------------------
class TestReplayScopeMatrix:
    def test_full_lifecycle_blocked(self):
        """Full Lifecycle = BLOCKED。"""
        from audit_replay_blocker_impact import compute_replay_scope_matrix
        matrix = compute_replay_scope_matrix()
        row = matrix[matrix['Replay Scope'] == 'Full Lifecycle'].iloc[0]
        assert row['Status'] == 'BLOCKED'

    def test_decision_replay_partial(self):
        """Decision Replay = PARTIAL。"""
        from audit_replay_blocker_impact import compute_replay_scope_matrix
        matrix = compute_replay_scope_matrix()
        row = matrix[matrix['Replay Scope'] == 'Decision Replay'].iloc[0]
        assert row['Status'] == 'PARTIAL'

    def test_signal_only_reconstructable(self):
        """Signal-only = RECONSTRUCTABLE。"""
        from audit_replay_blocker_impact import compute_replay_scope_matrix
        matrix = compute_replay_scope_matrix()
        row = matrix[matrix['Replay Scope'] == 'Signal-only'].iloc[0]
        assert row['Status'] == 'RECONSTRUCTABLE'


# ---------------------------------------------------------------------------
# Deterministic Results
# ---------------------------------------------------------------------------
class TestDeterministicResults:
    def test_strict_candidates_equals_in_range(self):
        """STRICT candidates = in_range (当前无 ST UNKNOWN)。"""
        from audit_replay_blocker_impact import compute_combined_scenarios, compute_market_cap_bounds
        universe = load_universe()
        combined = compute_combined_scenarios(universe)
        mcap = compute_market_cap_bounds(universe)
        assert combined['scenario_1_strict'] == mcap['in_range']

    def test_research_candidates_equals_in_range(self):
        """RESEARCH candidates = in_range (当前无 ST UNKNOWN)。"""
        from audit_replay_blocker_impact import compute_combined_scenarios, compute_market_cap_bounds
        universe = load_universe()
        combined = compute_combined_scenarios(universe)
        mcap = compute_market_cap_bounds(universe)
        assert combined['scenario_2_research'] == mcap['in_range']


# ---------------------------------------------------------------------------
# Production Contamination Guard
# ---------------------------------------------------------------------------
class TestProductionContaminationGuard:
    def test_no_production_modifications(self):
        """未修改生产数据。"""
        con = sqlite3.connect(str(DB))
        cur = con.cursor()
        # indicators 表应为当前快照
        cur.execute('SELECT COUNT(*) FROM indicators')
        ind_count = cur.fetchone()[0]
        assert ind_count == 5187, 'indicators 应为当前快照 5187 行'
        # stocks 表应为当前快照
        cur.execute('SELECT COUNT(*) FROM stocks')
        stk_count = cur.fetchone()[0]
        assert stk_count == 5187, 'stocks 应为当前快照 5187 行'
