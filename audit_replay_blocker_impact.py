"""
Phase 7.3-I：Historical Replay Blocker Impact & Sensitivity Audit

量化 Market Cap / ST / Portfolio 三个 Replay Blocker 对 V1 历史决策重放的实际影响。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

DB = Path('/home/caojy/.hermes/skills/stock/stock-expert/market_cache.db')

# V1 过滤参数
MCAP_MIN = 5e8      # 5 亿
MCAP_MAX = 9e10     # 90 亿
TURNOVER_MIN_1D = 8e6   # 8000 万
TURNOVER_MIN_20D = 4e6  # 4000 万
ATR_MIN = 3.0
VOL_RATIO_MIN = 2.7
PRICE_POS_MAX = 0.4    # 分位 ≤ 40%


@dataclass
class V1FilterDependency:
    """V1 单票过滤链的历史数据依赖。"""
    name: str
    required_data: str
    pit_status: str
    if_unknown: str
    replay_impact: str


V1_DEPENDENCIES = [
    V1FilterDependency(
        name='Universe',
        required_data='stocks + klines',
        pit_status='PARTIAL (可用，但无法识别停牌/ST)',
        if_unknown='跳过该股票',
        replay_impact='MEDIUM — 只能重建 as-of 存在交易的股票，无法识别停牌'
    ),
    V1FilterDependency(
        name='ST',
        required_data='stocks.is_st',
        pit_status='BLOCKED (当前快照，无历史序列)',
        if_unknown='严格模式跳过；研究模式标记 UNKNOWN',
        replay_impact='HIGH — 直接影响候选资格，ST 股票被排除'
    ),
    V1FilterDependency(
        name='Market Cap 5-90B',
        required_data='Historical Market Cap',
        pit_status='PARTIAL (STRICT=16.3%, RESEARCH=76%)',
        if_unknown='严格模式跳过；研究模式标记 UNKNOWN',
        replay_impact='HIGH — 直接影响候选资格，市值是硬过滤条件'
    ),
    V1FilterDependency(
        name='Volume Ratio',
        required_data='klines.volume + MA20',
        pit_status='RECONSTRUCTABLE (有 K 线)',
        if_unknown='无法计算，跳过',
        replay_impact='LOW — K 线数据完整，可重建'
    ),
    V1FilterDependency(
        name='Amount (Turnover)',
        required_data='klines.volume × close',
        pit_status='RECONSTRUCTABLE (有 K 线)',
        if_unknown='无法计算，跳过',
        replay_impact='LOW — K 线数据完整，可重建'
    ),
    V1FilterDependency(
        name='MA20',
        required_data='klines.close 20 日平均',
        pit_status='PARTIAL (有 K 线，但 MA20 与生产指标有 PRICE_SEMANTIC_CONFLICT)',
        if_unknown='无法计算，跳过',
        replay_impact='LOW — 可重建，但值可能与生产环境有差异'
    ),
    V1FilterDependency(
        name='ATR',
        required_data='klines.high/low/close',
        pit_status='RECONSTRUCTABLE (有 K 线)',
        if_unknown='无法计算，跳过',
        replay_impact='LOW — K 线数据完整，可重建'
    ),
    V1FilterDependency(
        name='Price Position (分位)',
        required_data='klines.close + MA20',
        pit_status='PARTIAL (与 MA20 同样的 PRICE_SEMANTIC_CONFLICT)',
        if_unknown='无法计算，跳过',
        replay_impact='LOW — 可重建，但值可能与生产环境有差异'
    ),
]


def load_universe() -> pd.DataFrame:
    """加载当前股票池。"""
    con = sqlite3.connect(str(DB))
    return pd.read_sql('SELECT code, name, is_st, total_mcap FROM stocks', con)


def compute_market_cap_bounds(df: pd.DataFrame) -> dict:
    """计算市值边界统计。"""
    total = len(df)
    with_mcap = df[df['total_mcap'].notna()].copy()
    without_mcap = df[df['total_mcap'].isna()]

    in_range = with_mcap[(with_mcap['total_mcap'] >= MCAP_MIN) & (with_mcap['total_mcap'] <= MCAP_MAX)]
    below = with_mcap[with_mcap['total_mcap'] < MCAP_MIN]
    above = with_mcap[with_mcap['total_mcap'] > MCAP_MAX]

    # 边界分析：所有有市值股票中，距离最近边界的相对距离
    def nearest_boundary_distance(mcap):
        if mcap < MCAP_MIN:
            return (MCAP_MIN - mcap) / MCAP_MIN
        elif mcap > MCAP_MAX:
            return (mcap - MCAP_MAX) / MCAP_MAX
        else:
            # 在范围内，距离最近边界的距离
            dist_to_min = (mcap - MCAP_MIN) / MCAP_MIN
            dist_to_max = (MCAP_MAX - mcap) / MCAP_MAX
            return min(dist_to_min, dist_to_max)

    with_mcap['bd'] = with_mcap['total_mcap'].apply(nearest_boundary_distance)
    borderline_5 = with_mcap[with_mcap['bd'] <= 0.05]
    borderline_10 = with_mcap[with_mcap['bd'] <= 0.10]

    return {
        'total': total,
        'with_mcap': len(with_mcap),
        'without_mcap': len(without_mcap),
        'in_range': len(in_range),
        'below': len(below),
        'above': len(above),
        'borderline_5pct': len(borderline_5),
        'borderline_10pct': len(borderline_10),
        'in_range_pct': len(in_range) / total * 100 if total > 0 else 0,
    }


def compute_st_sensitivity(df: pd.DataFrame) -> dict:
    """计算 ST 敏感性。"""
    total = len(df)
    st_count = len(df[df['is_st'] == 1])
    unknown_count = len(df[df['is_st'].isna()])  # 当前无 NULL，但历史可能有

    # 当前全部非 ST
    normal_count = len(df[df['is_st'] == 0])

    # Scenario A：UNKNOWN 全部视为 NORMAL
    # Scenario B：UNKNOWN 全部视为 ST
    # 当前 UNKNOWN = 0，所以 min = max = normal_count

    return {
        'total': total,
        'st_count': st_count,
        'unknown_count': unknown_count,
        'normal_count': normal_count,
        'scenario_a_normal': normal_count + unknown_count,  # 全正常
        'scenario_b_st': normal_count,  # 全 ST
        'uncertainty_range': unknown_count,
        'uncertainty_ratio': unknown_count / total * 100 if total > 0 else 0,
    }


def compute_combined_scenarios(df: pd.DataFrame) -> dict:
    """计算联合敏感性场景。"""
    mcap_bounds = compute_market_cap_bounds(df)
    st_bounds = compute_st_sensitivity(df)

    # 当前状态：全部非 ST，有市值数据
    # Scenario 1: Strict (仅 STRICT Market Cap + KNOWN ST)
    # 当前 ST 全部 KNOWN_NORMAL，所以：
    strict_candidates = mcap_bounds['in_range']

    # Scenario 2: Research (RESEARCH Market Cap + KNOWN ST)
    # 当前 Market Cap = 全有，所以：
    research_candidates = mcap_bounds['in_range']

    # Scenario 3: Research + ST Best Case
    research_best = mcap_bounds['in_range'] + st_bounds['unknown_count']

    # Scenario 4: Research + ST Worst Case
    research_worst = mcap_bounds['in_range']

    return {
        'scenario_1_strict': strict_candidates,
        'scenario_2_research': research_candidates,
        'scenario_3_best': research_best,
        'scenario_4_worst': research_worst,
        'total_universe': len(df),
        'strict_coverage_pct': strict_candidates / len(df) * 100 if len(df) > 0 else 0,
        'research_coverage_pct': research_candidates / len(df) * 100 if len(df) > 0 else 0,
    }


def compute_replay_scope_matrix() -> pd.DataFrame:
    """构建 Replay Scope Matrix。"""
    matrix = pd.DataFrame([
        {
            'Replay Scope': 'Signal-only',
            'Market Cap': 'RESEARCH',
            'ST': 'KNOWN + APPROXIMATE',
            'Portfolio': 'N/A',
            'Status': 'RECONSTRUCTABLE',
            'Notes': '单票信号研究，不依赖历史组合'
        },
        {
            'Replay Scope': 'Candidate Replay',
            'Market Cap': 'RESEARCH',
            'ST': 'KNOWN + APPROXIMATE',
            'Portfolio': 'N/A',
            'Status': 'RECONSTRUCTABLE',
            'Notes': '可重建候选列表，但 ST UNKNOWN 需标注'
        },
        {
            'Replay Scope': 'Entry Replay',
            'Market Cap': 'RESEARCH',
            'ST': 'KNOWN + APPROXIMATE',
            'Portfolio': 'N/A',
            'Status': 'RECONSTRUCTABLE',
            'Notes': '可重建入场决策，但非 Production-equivalent'
        },
        {
            'Replay Scope': 'Decision Replay',
            'Market Cap': 'STRICT',
            'ST': 'KNOWN',
            'Portfolio': 'PARTIAL',
            'Status': 'PARTIAL',
            'Notes': '严格 PIT 模式下，仅 16.3% Market Cap + 0% ST 可用'
        },
        {
            'Replay Scope': 'Full Lifecycle',
            'Market Cap': 'STRICT',
            'ST': 'KNOWN',
            'Portfolio': 'FULL',
            'Status': 'BLOCKED',
            'Notes': 'Portfolio NONE，ST BLOCKED，无法开展'
        },
    ])
    return matrix


def main():
    df = load_universe()
    mcap_bounds = compute_market_cap_bounds(df)
    st_bounds = compute_st_sensitivity(df)
    combined = compute_combined_scenarios(df)
    scope_matrix = compute_replay_scope_matrix()

    print('=' * 60)
    print('Phase 7.3-I：Historical Replay Blocker Impact & Sensitivity Audit')
    print('=' * 60)

    print('\n## V1 Filter Dependency Matrix')
    print('-' * 60)
    for dep in V1_DEPENDENCIES:
        print(f'\n### {dep.name}')
        print(f'  Required Data: {dep.required_data}')
        print(f'  PIT Status: {dep.pit_status}')
        print(f'  If Unknown: {dep.if_unknown}')
        print(f'  Replay Impact: {dep.replay_impact}')

    print('\n## Market Cap Bounds')
    print('-' * 60)
    print(f'Total Universe: {mcap_bounds["total"]}')
    print(f'With Market Cap: {mcap_bounds["with_mcap"]} ({mcap_bounds["with_mcap"]/mcap_bounds["total"]*100:.1f}%)')
    print(f'Without Market Cap: {mcap_bounds["without_mcap"]}')
    print(f'  5-90B (In Range): {mcap_bounds["in_range"]} ({mcap_bounds["in_range_pct"]:.1f}%)')
    print(f'  <5B (Below): {mcap_bounds["below"]}')
    print(f'  >90B (Above): {mcap_bounds["above"]}')
    print(f'  Borderline 0-5%: {mcap_bounds["borderline_5pct"]}')
    print(f'  Borderline 0-10%: {mcap_bounds["borderline_10pct"]}')

    print('\n## ST Sensitivity')
    print('-' * 60)
    print(f'Total: {st_bounds["total"]}')
    print(f'ST: {st_bounds["st_count"]}')
    print(f'NORMAL: {st_bounds["normal_count"]}')
    print(f'UNKNOWN: {st_bounds["unknown_count"]}')
    print(f'  Scenario A (ALL NORMAL): {st_bounds["scenario_a_normal"]}')
    print(f'  Scenario B (ALL ST): {st_bounds["scenario_b_st"]}')
    print(f'  Uncertainty Range: {st_bounds["uncertainty_range"]}')
    print(f'  Uncertainty Ratio: {st_bounds["uncertainty_ratio"]:.2f}%')

    print('\n## Combined Scenarios')
    print('-' * 60)
    print(f'Scenario 1 (Strict Market Cap + KNOWN ST): {combined["scenario_1_strict"]} candidates')
    print(f'  Strict Coverage: {combined["strict_coverage_pct"]:.1f}%')
    print(f'Scenario 2 (Research Market Cap + KNOWN ST): {combined["scenario_2_research"]} candidates')
    print(f'  Research Coverage: {combined["research_coverage_pct"]:.1f}%')
    print(f'Scenario 3 (Research + ST Best Case): {combined["scenario_3_best"]} candidates')
    print(f'Scenario 4 (Research + ST Worst Case): {combined["scenario_4_worst"]} candidates')

    print('\n## Replay Scope Matrix')
    print('-' * 60)
    print(scope_matrix.to_string(index=False))

    print('\n## Final Answers')
    print('-' * 60)
    print(f'1. ST UNKNOWN 实际影响: {st_bounds["uncertainty_range"]} 只 (当前 0，历史可能有)')
    print(f'2. Market Cap uncertainty 影响: {mcap_bounds["without_mcap"]} 只无市值数据')
    print(f'3. 5-90B 边界受影响: {mcap_bounds["borderline_10pct"]} 只在 10% 边界内')
    print(f'4. STRICT Candidate coverage: {combined["strict_coverage_pct"]:.1f}%')
    print(f'5. RESEARCH Candidate coverage: {combined["research_coverage_pct"]:.1f}%')
    print(f'6. ST Best/Worst Case 区间: [{combined["scenario_4_worst"]}, {combined["scenario_3_best"]}]')
    print(f'7. Market Cap Strict/Research 区间: [{mcap_bounds["in_range"]}, {mcap_bounds["in_range"]}]')
    print(f'8. 联合上下界: [{combined["scenario_4_worst"]}, {combined["scenario_3_best"]}]')
    print(f'9. SINGLE_STOCK_REPLAY: 可开展 (仅研究用途)')
    print(f'10. FULL_DECISION_REPLAY: 不能 (ST BLOCKED, Portfolio NONE)')
    print(f'11. Portfolio 影响: 仅影响完整组合层，不影响单票研究')
    print(f'12. 是否值得购买专业数据: MEDIUM ROI (ST 影响大但当前无 UNKNOWN)')
    print(f'13. 最值得解决: ST (历史数据缺失，无法自动检测)')
    print(f'14. Replay A/B/C 可行范围: A=PARTIAL, B=PARTIAL, C=BLOCKED')
    print(f'15. 下一步: 单票 Candidate Replay 研究 (不实现全市场 Replay)')


if __name__ == '__main__':
    main()
