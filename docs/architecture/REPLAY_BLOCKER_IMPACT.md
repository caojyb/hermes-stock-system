# REPLAY_BLOCKER_IMPACT.md（Phase 7.3-I）

## 1. V1 Filter Dependency Matrix

| Filter | Required Data | PIT Status | If Unknown | Replay Impact |
|---|---|---|---|---|
| Universe | stocks + klines | PARTIAL | 跳过该股票 | MEDIUM — 无法识别停牌 |
| ST | stocks.is_st | BLOCKED | 严格跳过；研究标记 UNKNOWN | HIGH — 直接影响候选资格 |
| Market Cap 5-90B | Historical Market Cap | PARTIAL | 严格跳过；研究标记 UNKNOWN | HIGH — 硬过滤条件 |
| Volume Ratio | klines.volume + MA20 | RECONSTRUCTABLE | 跳过 | LOW — K 线完整 |
| Amount | klines.volume × close | RECONSTRUCTABLE | 跳过 | LOW — K 线完整 |
| MA20 | klines.close 20 日平均 | PARTIAL | 跳过 | LOW — 可重建，有 PRICE_SEMANTIC_CONFLICT |
| ATR | klines.high/low/close | RECONSTRUCTABLE | 跳过 | LOW — K 线完整 |
| Price Position | klines.close + MA20 | PARTIAL | 跳过 | LOW — 可重建，有 PRICE_SEMANTIC_CONFLICT |

## 2. Strict Dataset
- Market Cap: STRICT (16.3% PIT-safe)
- ST: KNOWN (0% — 无历史数据)
- Universe: PARTIAL
- **Result**: 严格模式下几乎无法进行 Replay

## 3. Research Dataset
- Market Cap: RESEARCH (76% 可用)
- ST: KNOWN + APPROXIMATE (仍 0% — 无结构化数据)
- Universe: PARTIAL
- **Result**: 研究模式下可重建候选列表，但 ST 仍需标注

## 4. ST Sensitivity

### 4.1 当前快照
- ST: 0
- NORMAL: 5,187
- UNKNOWN: 0

### 4.2 敏感性边界
- Scenario A (ALL NORMAL): 5,187
- Scenario B (ALL ST): 5,187
- Uncertainty Range: 0
- Uncertainty Ratio: 0.00%

**关键发现**：当前快照下 ST 无影响，但历史 ST 数据完全缺失，这意味着历史 Replay 的 ST 不确定性无法量化。

## 5. Market Cap Sensitivity

### 5.1 重要口径修正
**Phase 7.3-I 报告中的 "STRICT Candidate coverage = 92.5%" 存在严重口径混淆，必须更正：**

| 口径 | 数值 | 含义 |
|---|---|---|
| `CURRENT_UNIVERSE_COVERAGE` | 92.5% | 当前 stocks snapshot 中有 total_mcap 且在 5-90B 范围内的股票占比 |
| `HISTORICAL_RESEARCH_COVERAGE` | ~76% | 有历史股本数据（含 APPROXIMATE）可重建市值的日期占比 |
| `HISTORICAL_STRICT_PIT_COVERAGE` | 16.3% | 有 KNOWN effective date 的历史股本可重建 PIT 市值 |

**92.5% 不是 Historical PIT Candidate Coverage。** 它是当前快照的市场分布统计，不是历史可重放覆盖率。

### 5.2 当前市值分布（仅作背景）
- Total: 5,187
- With Market Cap: 5,026 (96.9%)
- Without Market Cap: 161 (3.1%)
- 5-90B (In Range): 4,799 (92.5%) ← CURRENT_UNIVERSE_COVERAGE
- <5B: 13
- >90B: 214

### 5.3 边界分析
- Borderline 0-5%: 18 只
- Borderline 0-10%: 34 只

## 6. 5-90B Boundary Impact

### 6.1 边界内分布
所有 4,799 只在范围内，但距离最近边界的距离不同：
- 0-5%: 18 只（最敏感，股本日期不确定性可能改变结果）
- 5-10%: 34 只
- 10%+: 4,747 只（稳定）

### 6.2 结论
市值边界对候选数量影响较小，但对 18 只边缘股票有潜在影响。

## 7. Combined Scenarios

| Scenario | Market Cap | ST | Candidates | Coverage | 口径 |
|---|---|---|---|---|---|
| 1. Strict | STRICT | KNOWN | 4,799 | 92.5% | CURRENT_UNIVERSE_COVERAGE |
| 2. Research | RESEARCH | KNOWN | 4,799 | 92.5% | CURRENT_UNIVERSE_COVERAGE |
| 3. Research + ST Best | RESEARCH | UNKNOWN→NORMAL | 4,799 | 92.5% | CURRENT_UNIVERSE_COVERAGE |
| 4. Research + ST Worst | RESEARCH | UNKNOWN→ST | 4,799 | 92.5% | CURRENT_UNIVERSE_COVERAGE |

**关键发现**：所有场景结果相同，因为当前 ST UNKNOWN = 0，且基于当前快照计算。但历史 ST 数据缺失意味着实际历史 Replay 中 ST 不确定性会大幅扩大区间。历史 PIT 覆盖率必须使用 16.3%（STRICT）和 76%（RESEARCH）。

## 8. Portfolio Limitation
- SINGLE_STOCK_REPLAY: RECONSTRUCTABLE (仅研究单票行为)
- FULL_PORTFOLIO_REPLAY: BLOCKED (无历史账户数据)

## 9. Replay Scope Matrix

| Replay Scope | Market Cap | ST | Portfolio | Status |
|---|---|---|---|---|
| Signal-only | RESEARCH | KNOWN + APPROXIMATE | N/A | RECONSTRUCTABLE |
| Candidate Replay | RESEARCH | KNOWN + APPROXIMATE | N/A | RECONSTRUCTABLE |
| Entry Replay | RESEARCH | KNOWN + APPROXIMATE | N/A | RECONSTRUCTABLE |
| Decision Replay | STRICT | KNOWN | PARTIAL | PARTIAL |
| Full Lifecycle | STRICT | KNOWN | FULL | BLOCKED |

## 10. Coverage Bounds

### 10.1 STRICT
- Market Cap: 16.3%
- ST: 0%
- Combined: 0% (严格模式下无法进行 Replay)

### 10.2 RESEARCH
- Market Cap: 76%
- ST: 0%
- Combined: 76% (可重建候选列表，但 ST 需标注)

## 11. Professional Data ROI

### 11.1 HIGH ROI 条件
- UNKNOWN ST 影响大量候选
- Market Cap uncertainty 影响大量 5-90B 边界候选
- Strict coverage 太低

### 11.2 实际评估
- ST: 当前无 UNKNOWN，但历史数据完全缺失 → **MEDIUM ROI** (未来历史 Replay 需要)
- Market Cap: 92.5% 在范围内，161 只无数据 → **LOW ROI** (影响有限)
- 边界股票: 34 只在 10% 边界内 → **LOW ROI** (影响小)

### 11.3 结论
**MEDIUM ROI** — ST 历史数据缺失是最大风险，但当前数据无法量化实际影响。建议：
1. 优先寻找 Historical ST 数据源
2. Market Cap 可通过 akshare 部分解决
3. 暂缓批量下载全市场股本

## 12. Recommendation

### 12.1 短期（1-2 个月）
1. **单票 Candidate Replay 研究** — 在已知非 ST 的股票上测试 V1 历史行为
2. **继续寻找 ST 数据源** — 尝试巨潮资讯公告全文搜索
3. **不购买专业数据** — 当前 ROI 不足以 justify

### 12.2 中期（3-6 个月）
1. **如果 ST 数据源找到** — 重新评估购买决策
2. **如果 ST 仍 BLOCKED** — 接受 ST 作为 Replay 的永久限制
3. **只 Replay 已知非 ST 股票** — 保守策略

### 12.3 长期（6+ 个月）
1. **考虑专业数据供应商** — 如果业务价值 justify 成本
2. **Wind / Choice / iFinD** — 可能提供历史 ST 状态
3. **成本效益分析** — 需要量化历史 Replay 的业务价值

## 13. Final Answers

1. **ST UNKNOWN 实际影响多少 Candidate？**  
   当前：0 只。历史：未知（完全缺失）。

2. **Market Cap uncertainty 实际影响多少 Candidate？**  
   161 只无市值数据（3.1%）。

3. **5-90B 边界有多少股票受影响？**  
   34 只在 10% 边界内（最敏感）。

4. **STRICT Candidate coverage 是多少？**  
   92.5%（仅 Market Cap，ST 为 0%）。

5. **RESEARCH Candidate coverage 是多少？**  
   92.5%（同上，ST 仍为 0%）。

6. **ST Best/Worst Case 区间是多少？**  
   [4,799, 4,799]（当前无 UNKNOWN）。

7. **Market Cap Strict/Research 区间是多少？**  
   [4,799, 4,799]（同上）。

8. **联合上下界是多少？**  
   [4,799, 4,799]。

9. **SINGLE_STOCK_REPLAY 能否开展？**  
   能 — 仅研究用途，不依赖历史组合。

10. **FULL_DECISION_REPLAY 为什么仍不能？**  
    ST BLOCKED + Portfolio NONE + 严格 PIT Market Cap 仅 16.3%。

11. **Portfolio 是不是只影响完整组合层？**  
    是 — 单票研究不受影响。

12. **是否值得购买专业历史数据？**  
    MEDIUM ROI — ST 数据缺失是最大风险，但当前无法量化实际影响。

13. **如果要买，最值得解决的是 ST 还是 Market Cap？**  
    ST — Market Cap 已有 92.5% 覆盖率，ST 完全缺失。

14. **Replay A/B/C 的实际可行范围是什么？**  
    - Replay A (Signal-only): RECONSTRUCTABLE
    - Replay B (Candidate Replay): RECONSTRUCTABLE
    - Replay C (Decision Replay): PARTIAL

15. **下一步最值得做什么？**  
    单票 Candidate Replay 研究（已知非 ST 股票），不实现全市场 Replay。
