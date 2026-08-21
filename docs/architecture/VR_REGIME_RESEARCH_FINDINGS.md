# Volume Ratio × Regime Deep Research — Findings (Phase 8-G2)

> 本文件是 Phase 8-G2 的 Volume Ratio × Regime 研究结果。
> 严格 **RESEARCH_ONLY**，不修改生产，不输出参数建议。
> 结论标签受控：无预先定义的 Stability / Incremental Gate → 最高只到 PRELIMINARY_*。
> `EXPLORATORY_RESEARCH = TRUE`

---

## 1. Research Objective

研究 Volume Ratio (VR) 与 Forward Outcome 的关系，及该关系是否依赖 Market Regime。
核心：2.7 是高 Edge 过滤器，还是极端稀缺过滤器？

## 2. Production Semantics（继承 G1，已确认）

- Cadence：**weekly**（周日17:20）
- Candidate：每周最后交易日；Entry：T+1 Open
- VR Formula：`vol_ratio = 5日均量 / 前20日均量(kl[-25:-5])`（生产 scan_doubling_potential 与 G1 研究一致）
- **FORMULA_MATCH = TRUE**

## 3. Fixed VR Bands（分析前锁定）

B1 <1.0 / B2 1.0-1.3 / B3 1.3-1.7 / B4 1.7-2.0 / B5 2.0-2.7 / B6 >=2.7
（2.7 是生产阈值，故 2.0-2.7 与 >=2.7 单独保留）

## 4. Research Data

- 33 只股票 × 2015-2024（weekly cadence），16830 条候选级记录
- 来源：历史 K 线 + PIT 特征 + PIT 市值重建（非 double_up_scores）
- Regime 映射：PIT 重建（2015-2024：高波动794/震荡1280/低量能345/强趋势12）
- 全部候选 `final_candidate=0`（所选样本多为中大盘股，不满足市值/流动性等其它 filter）→ **本研究是纯 VR 条件的候选级 Counterfactual，未叠加其它 V1 filter**

## 5. FACT / EVIDENCE / HYPOTHESIS

### FACT（数据直接显示）
1. **VR 分布**：全部样本中位数 0.93，Q90=1.60，Q95=1.95，Q99=3.12，max=13.9
2. **2.7 分位**：约 Q98.5（Q99=3.12），属极尾部
3. **2.7 Coverage Loss**：VR>=1.0 有 7203 样本，VR>=2.7 仅 300 → **2.7 砍掉约 96% 样本**
   （VR>=2.7 / VR>=1.0 相对比 = 24.0x）
4. **VR × median 20D return（全部候选）**：
   - B1(<1.0): +0.23%
   - B2(1.0-1.3): +0.22%
   - B3(1.3-1.7): +0.42%
   - B4(1.7-2.0): +0.87%
   - B5(2.0-2.7): **-0.76%**
   - B6(>=2.7): **-2.70%**
5. **单调性 = NON_MONOTONIC**：VR 1.0-2.0 上升对应收益小幅改善，2.0 后收益转负，>=2.7 最差

### EVIDENCE
- VR 2.0 之后 forward return 明显恶化（2.0-2.7 与 >=2.7 均为负）
- 该模式跨 2015-2019 与 2020-2024 两期均存在（2015-19: B5=-0.42%, B6=-2.90%; 2020-24: B5=-1.71%, B6=-2.64%）
- Regime 条件：HIGH_VOL B5/B6 均负（-1.59%/-1.80%）；SIDEWAYS B5/B6 负（-0.71%/-2.58%）；LOW_VOLUME B6 极差（-4.58%）
- Market Cap 条件：SMALL B6 相对抗跌（-0.46%），UNKNOWN/APPROXIMATE B6 较差

### HYPOTHESIS
- 高 VR（>=2.0）可能代表短期放量后的均值回归 / 追高风险，而非资金确认 Edge
- 2.7 不是"高 Edge 过滤器"，而是"极端稀缺 + 条件更差"的过滤器
- 但本阶段是**候选级 Counterfactual**，未叠加其它 V1 filter，不能外推为完整策略结论

## 6. 2.7 Incremental Value（2.0-2.7 vs >=2.7）

- 2.0-2.7：N=464，med 20D = -0.76%
- >=2.7：N=300，med 20D = **-2.70%**
- **结论：>=2.7 相对 2.0-2.7 无明显增量价值，反而 20D 更差**
- 跨期稳定：两期均如此

## 7. Regime × VR Matrix（median 20D）

| Regime | <1.0 | 1.0-1.3 | 1.3-1.7 | 1.7-2.0 | 2.0-2.7 | >=2.7 |
|---|---|---|---|---|---|---|
| ALL | +0.23 | +0.22 | +0.42 | +0.87 | -0.76 | **-2.70** |
| HIGH_VOL | +0.01 | +0.57 | +0.92 | +1.70 | -1.59 | -1.80 |
| LOW_VOLUME | +0.53 | +0.26 | +1.68 | +1.08 | +0.01 | **-4.58** |
| SIDEWAYS | +0.21 | +0.13 | +0.08 | +0.77 | -0.71 | -2.58 |
| STRONG_TREND | +1.42 | -4.23 | -5.11 | -4.41 | -6.90 | -4.40 |

## 8. Confounders（Market Cap / ATR / Price Position）

- Market Cap：SMALL 在 B6 相对抗跌（-0.46%），UNKNOWN/APPROXIMATE B6 较差（-3.75%/-2.24%）
  → 高 VR 的高收益恶化部分受市值/数据质量影响，但 B5/B6 转负在所有市值层基本一致
- ATR / Price Position：产物已生成（vr_conditional_atr/pricepos），B5/B6 负值在各桶普遍

## 9. Time Stability

- 2015-2019：B5=-0.42%, B6=-2.90%
- 2020-2024：B5=-1.71%, B6=-2.64%
- **模式跨期稳定**：2.0 后收益转负，>=2.7 最差，两期一致
- 非 TIME_LOCALIZED_PATTERN（两期均出现）

## 10. Sensitivity（STRICT/RESEARCH/SENSITIVITY）

- med 20D：STRICT SMALL B6=-0.46%；RESEARCH B6=-2.22%；SENSITIVITY B6=-2.70%
- **B5/B6 为负在所有模式一致** → 结论不依赖 ST/Market Cap 质量假设

## 11. Research Conclusion

### 最终结论标签
- **VR_MONOTONICITY_STATUS = NON_MONOTONIC**
- **VR_2_7_INCREMENTAL_STATUS = NO_INCREMENTAL_EVIDENCE**（2.7 相对 2.0-2.7 无额外价值，且 20D 更差）
- **REGIME_CONDITIONAL_STATUS = PRELIMINARY_PATTERN**（各 Regime 高 VR 均偏弱，但样本/覆盖有限）

### 核心回答
- 2.7 是"**极端稀缺过滤器**"（砍掉 ~96% 样本，位于 Q98.5），而非"高 Edge 过滤器"
- VR 与 forward return **非单调**：1.0-2.0 小幅上升改善，2.0 后恶化
- 2.7 无增量价值（>=2.7 20D median -2.70% < 2.0-2.7 -0.76%）
- 高 VR 收益恶化跨 Regime / 跨时期 / 跨数据质量模式基本一致

### 严格边界
- 本研究是**候选级纯 VR 条件 Counterfactual**，未叠加其它 V1 filter，`final_candidate=0`
- **不代表"V1 失效"**，也不代表"2.7 应修改"
- **不输出任何参数建议**
- 未启用 Strategy Selector，未修改生产

## 12. Data Limitations

1. 候选级纯 VR 条件（未叠加完整 V1 filter 链）
2. Signal 层未重建（需 Entry Signal 重建，G1 未完成）
3. ST 全 UNKNOWN、部分市值 APPROXIMATE
4. STRONG_TREND 仅 12 天（DATA_INSUFFICIENT）
5. 样本为 33 只中大盘股，未覆盖全市场小市值分布

## 13. Research Health

**RESEARCH_PARTIAL**
- production_semantics / VR_formula / cadence / entry_timing / feature / regime / forward_outcome / baseline / time_stability：CONFIRMED
- market_cap：PIT-APPROXIMATE
- ST：UNKNOWN
- survivorship：LIMITED
- signal 层：NOT_REBUILT
- regime_coverage：STRONG_TREND DATA_INSUFFICIENT

---

*Phase 8-G2 · Volume Ratio × Regime Deep Research · 候选级 Counterfactual（NON_MONOTONIC / NO_INCREMENTAL_EVIDENCE / PRELIMINARY_PATTERN）*
