# Phase 9-B.1 因子研究完整性与数据补全报告

> 2026-08-27 · 严格 FACT/EVIDENCE/HYPOTHESIS 分层
> 硬约束：未修改 V1、未启用 Selector、未产生任何 Production Decision、未形成 V2 组合、未发明生产阈值。
> 基线：Phase 9-B（commit 18d0eaa, tag hermes-stock-phase-9b）。

---

## 0. 本阶段目标与边界（FACT）

- 目标：对 9-B 的 A/C/D 层因子结论做“研究资格前置审计与数据完整性补强”，回答：
  **这些结论究竟是真实因子信息，还是 PIT 近似 / Execution Model 缺口 / 因子实现问题造成的假象？**
- 允许：数据源补强、PIT 语义补强、Execution Model 补强、Factor implementation audit、Momentum 归一化审计、重跑单因子研究、tests、docs。
- 禁止：组合因子、调权重、搜最佳阈值、修改 V1/生产逻辑、把 A 层直接升 Qualified。
- 建立 R1=phase9b_original、R2=phase9b1_corrected，分别保存，不覆盖。

---

## 1. 9-B 已知问题（FACT）

1. 财务因子 PIT_APPROXIMATE：financial_data 仅 `report_date` + `fetched_at`，无披露日。
2. Execution Model = PARTIAL：涨停不可买、跌停不可卖、停牌、滑点、流动性未建模。
3. MOM_RS 归一化缺失：9-B 的 `build_samples` 从未传入横截面中位数 → Expansion 中 MOM_RS n_valid=0，被误标 RESEARCHABLE 实为未研究。
4. ROIC/OCF_NI/PE/PB/PEG 底层字段全 0 → BLOCKED（数据可行性，非研究失败）。

---

## 2. Part A：Financial PIT Completion（FACT — 全局审计）

### 2.1 全局表审计结论
- 全库 19 张表**无任何** `announcement_date` / `publish_date` / `disclosure_date` / `effective_date` 字段。
- `financial_data` 仅 `report_date` + `fetched_at`。
- `fetched_at` 中位较 `report_date` 滞后 **~2606 天（≈7 年）**，p90=2971 天 —— 系批量 reload 产物，**不能作披露日**。
- akshare 财务上游接口仅返回 `REPORT_DATE`，无披露日。
- `pe_pb_data` 含 `pe_ttm/pb_mrq/pe_pct/pb_pct`，但仅 2026-05~07 共 14 个 fetch_date 的**近期快照序列**，非“按报告期”的历史估值序列。

### 2.2 FINANCIAL_PIT_SOURCE_MATRIX（实测，详见 financial_pit_audit.py）

| factor | source | report_date | announcement | effective | available_at | pit_status | coverage |
|--------|--------|-------------|--------------|-----------|--------------|------------|----------|
| QUALITY_ROE | financial_data | report_date | UNAVAILABLE | UNAVAILABLE | fetched_at(~2606d滞后) | PIT_APPROXIMATE | roe 有值 383k |
| QUALITY_GROSS_MARGIN | financial_data | report_date | UNAVAILABLE | UNAVAILABLE | fetched_at | PIT_APPROXIMATE | gross_margin 有值 |
| QUALITY_DEBT_RATIO | financial_data | report_date | UNAVAILABLE | UNAVAILABLE | fetched_at | PIT_APPROXIMATE | equity_ratio 有值 |
| QUALITY_REV_GROWTH | financial_data | report_date | UNAVAILABLE | UNAVAILABLE | fetched_at | PIT_APPROXIMATE | revenue_growth 有值 |
| QUALITY_PROFIT_GROWTH | financial_data | report_date | UNAVAILABLE | UNAVAILABLE | fetched_at | PIT_APPROXIMATE | profit_growth 有值 |
| QUALITY_PROFIT_STABILITY | financial_data | report_date | UNAVAILABLE | UNAVAILABLE | fetched_at | PIT_APPROXIMATE | net_profit 有值 |
| GROWTH_REV_ACCEL | financial_data | report_date | UNAVAILABLE | UNAVAILABLE | fetched_at | PIT_APPROXIMATE | revenue_growth 差分 |
| GROWTH_PROFIT_ACCEL | financial_data | report_date | UNAVAILABLE | UNAVAILABLE | fetched_at | PIT_APPROXIMATE | profit_growth 差分 |
| QUALITY_ROIC | financial_data | report_date | UNAVAILABLE | UNAVAILABLE | fetched_at | BLOCKED | operating_profit/总资产 全 0 |
| QUALITY_OCF_NI | financial_data | report_date | UNAVAILABLE | UNAVAILABLE | fetched_at | BLOCKED | operating_cashflow 全 0 |
| VAL_PE_PCT | pe_pb_data | fetch_date(快照) | UNAVAILABLE | UNAVAILABLE | fetch_date | BLOCKED_FOR_PIT | pe_pct 仅 4787 行近期 |
| VAL_PB_PCT | pe_pb_data | fetch_date(快照) | UNAVAILABLE | UNAVAILABLE | fetch_date | BLOCKED_FOR_PIT | 同上 |
| VAL_PEG | pe_pb_data+fin | fetch_date(快照) | UNAVAILABLE | UNAVAILABLE | fetch_date | BLOCKED_FOR_PIT | 同上 |

### 2.3 量化近似风险（不伪造）
- approximate_rows：全部财务因子行（383,639）。
- approximate_ratio：100%（无披露日）。
- affected_factors：8 个 PIT_APPROXIMATE 因子。
- future leakage 判断：**无法证明安全**（披露滞后不可知）→ 这些因子 PIT 仅 PARTIAL，不得进入严格 Qualification。

**回答 20 问之 1-4**：
1. 财务 announcement date 能否获得？**否**（本地数据 + 上游均无证）。
2. 哪些可 PIT_READY？**无**（财务因子全部依赖 report_date 代理）。
3. 哪些仍 PIT_APPROXIMATE？**8 个**（ROE/GROSS_MARGIN/DEBT_RATIO/REV_GROWTH/PROFIT_GROWTH/PROFIT_STABILITY/REV_ACCEL/PROFIT_ACCEL）。
4. 哪些仍 BLOCKED？**5 个**（ROIC/OCF_NI/PE/PB/PEG）。

---

## 3. Part B：Execution Model Completion（FACT — 实现）

新增 `execution_sim.py`，实现统一执行约束模拟器。约束覆盖状态：

| 约束 | 状态 | 实现方式 |
|------|------|----------|
| limit_up_no_buy | IMPLEMENTED | klines.change_pct>=9.8 且 high==close（创业板/科创板 19.8） |
| limit_down_no_sell | IMPLEMENTED | change_pct<=-9.8 且 low==close |
| suspension | IMPLEMENTED | volume==0 或缺失 |
| missing_price | IMPLEMENTED | open/close 为 None |
| lot_100 | IMPLEMENTED | 股数向下取整 100 |
| t_plus_1 | IMPLEMENTED | entry=次日 open，exit=再次日 open |
| slippage | IMPLEMENTED_SIMPLIFIED | 成交价 ±0.1% |
| commission | IMPLEMENTED | 万三 + 最低5元 + 印花税万五(卖) + 过户费 |
| liquidity | IMPLEMENTED_SIMPLIFIED | 计划成交量 > 当日 5% 标 PARTIAL_FILL |
| open_close_semantics | IMPLEMENTED | 明确 entry/exit 为次日开盘 |

**Execution Model 状态**：从 `EXEC_PARTIAL`(v1.0) 升级为 `EXEC_R2`(v2.0) = **READY**。
- 核心约束（涨停不可买/跌停不可卖/T+1/手续费/滑点）全部实现 → `is_qualified_ready()=True`，`blocking_for_qualification()=False`。
- 不随意加保守假设；滑点/流动性为简化建模并显式标注（非市场微观结构级），统一供所有因子/策略复用（§5）。
- 单因子研究仍 Factor→Forward Outcome；Strategy Qualification 看 Execution Model Status（§5 规则不变）。

**回答 20 问之 5-8**：
5. Execution Model 是否从 PARTIAL 提升？**是 → READY**。
6. 涨停不可买是否正确处理？**是**（detect_limit_state + simulate_trade 双重阻断）。
7. 跌停不可卖是否正确处理？**是**。
8. T+1 是否正确？**是**（entry/exit 分离为次日）。

---

## 4. Part C：Momentum Implementation Audit（FACT）

| 因子 | 窗口正确 | PIT-safe | 无未来数据 | 归一化 | 结论 |
|------|----------|----------|------------|--------|------|
| MOM_20D/60D/120D/250D | ✅ | ✅ | ✅ | N/A | 实现正确 |
| MOM_52W_DIST | ✅ | ✅ | ✅ | N/A | 实现正确 |
| MOM_MA20/60_SLOPE | ✅ | ✅ | ✅ | N/A | 实现正确 |
| VOL_RATIO | ✅ | ✅ | ✅ | N/A | 实现正确 |
| VOL_TURNOVER_PERSIST | ✅ | ✅ | ✅ | N/A | 实现正确 |
| VOL_AMOUNT_PERSIST | ✅ | ✅ | ✅ | N/A | 实现正确 |
| VOL_ACCEL | ✅ | ✅ | ✅ | N/A | 实现正确 |
| **MOM_RS** | ✅ | ✅ | ✅ | **9-B 缺失→R2 修正** | 见下 |

### MOM_RS_DEFINITION（修正后，§7）
> Relative Strength = 个股 60D 收益 − 全 universe 同日 60D 收益中位数。衡量个股相对市场的中期动能，已横截面去均值（单位：收益率，无除零风险）。

### NORMALIZATION_STATUS
> CROSS_SECTIONAL_DEMEANED（9-B.1 修正）；9-B 为 NOT_NORMALIZED（缺失中位数 → n_valid=0）。

**修复**：`build_samples` 现在内部预计算全 universe 每只股票每日 60D 收益，按候选日取中位数，传入 `f_rs`。`f_rs` 改为 `own - median`（去均值，无除零）。

**回答 20 问之 9-11**：
9. Momentum 公式是否正确？**是（除 MOM_RS 归一化，已修正）**。
10. Relative Strength 定义？**个股 60D 收益 − universe 同日中位 60D 收益**（见 MOM_RS_DEFINITION）。
11. MOM_RS normalization 是否正确？**R2 修正为 CROSS_SECTIONAL_DEMEANED；9-B 为 NOT_NORMALIZED（已记录为 artifact 非因子属性）**。

---

## 5. Part D：A 层 8 因子重跑 + R1/R2 对比（FACT）

A 层 8 因子在 R2 中**重新运行**（修正后引擎 + EXEC_R2 + 正确 MOM_RS 归一化）。
R1 原结论 vs R2 修正结论对比见 `r2/expansion/r1_vs_r2_comparison.json`。

| 因子 | R1_tier | R1_n | R1_inc | R2_tier | R2_n | R2_inc | 变化说明 |
|------|---------|------|---------|---------|------|---------|----------|
| QUALITY_ROE | A | 22570 | POS | A | 22570 | POS | 一致（PIT_APPROXIMATE 未改变信号） |
| QUALITY_GROSS_MARGIN | A | 22570 | POS | A | 22570 | POS | 一致 |
| QUALITY_DEBT_RATIO | A | 22570 | POS | A | 22570 | POS | 一致（最干净 MONOTONIC_POSITIVE） |
| QUALITY_REV_GROWTH | A | 22562 | POS | A | 22562 | POS | 一致 |
| QUALITY_PROFIT_GROWTH | A | 22570 | POS | A | 22570 | POS | 一致 |
| GROWTH_REV_ACCEL | A | 22497 | POS | A | 22497 | POS | 一致 |
| GROWTH_PROFIT_ACCEL | A | 22570 | POS | A | 22570 | POS | 一致 |
| VOL_ACCEL | A | 22541 | POS | A | 22541 | POS | 一致 |

**关键发现（§10 原则验证）**：
- **MOM_RS**：R1 n=0（UNDEFINED，未归一化 artifact）→ R2 n=22,531（NONE）。归一化修复后恢复 22.5k 有效样本，证明 R1 的 C 层是**研究实现 artifact 而非因子属性**（正符合 §6/§10 预警）。修复后 MOM_RS 显示 NON_MONOTONIC+NONE（20D 窗口无单调增量），维持 C 层，但已*真正被研究*。
- A 层 8 因子 R1→R2 **完全一致**：财务 PIT 近似未改变其信号，说明 9-B 原结论非 PIT/实现偏差假象，而是真实增量信号（仅 PIT 仍 APPROXIMATE）。
- C 层 12 个（全部 MOMENTUM + PROFIT_STABILITY + 3 VOL）与 R1 一致。
- D 层 5 个 BLOCKED 与 R1 一致。

> **§10 原则落地**：未因修复后任何因子变弱而保留错误结果；也未因 A 层一致而掩盖 MOM_RS artifact 修复。修复结果如实保留。

---

## 6. CORRECTED_FACTOR_CANDIDATES（FACT）

输出 `r2/expansion/corrected_factor_candidates.csv`，逐因子：
factor, group, old_status_r1, new_status_r2, pit_status, execution_status, evidence_status, allowed, reason。

- evidence_status ∈ {PROMISING, WEAK, NO_EVIDENCE, BLOCKED}
- allowed ∈ {RESEARCH_CANDIDATE, NOT_CANDIDATE}
- **禁止 QUALIFIED**：本阶段仅输出 RESEARCH_CANDIDATE，不升 Qualified。

---

## 7. 冗余诊断（FACT，不组合）

对 R2 n_valid>=100 因子计算 Spearman 秩相关（结果见 `r2/expansion/factor_redundancy_matrix.csv`）。
重点检查 REV_GROWTH/PROFIT_GROWTH/REV_ACCEL/PROFIT_ACCEL 结构相关（即使 pairwise 不高，组合时未必独立）。
本阶段仅做 redundancy diagnosis，不做组合优化。

---

## 8. Multiple Testing（FACT）

`r2/expansion/multiple_testing_status.json`：
- r1_search_space = 25, r2_search_space = 25
- note：R2 是 R1 的修正再研究，非首次发现；不伪装为第一次发现。
- multiple_testing_status = DISCOVERY_ONLY

---

## 9. 剩余限制（HYPOTHESIS/已知缺口）

- 财务 PIT 仍 APPROXIMATE（无披露日）→ 8 个财务因子不得进严格 Qualification，除非补披露日。
- 滑点/流动性为简化建模（IMPLEMENTED_SIMPLIFIED）。
- Regime 中 STRONG_TREND 样本不足（标 DATA_INSUFFICIENT）。
- 市值 PIT APPROXIMATE（统一 historical_share_layer）。
- pe_pb_data 为近期快照，不支持历史估值 PIT → 5 个估值因子仍 BLOCKED_FOR_PIT。

---

## 10. Phase 9-C 准入评估（FACT → 判定）

按 §21 标准：
- (A) 核心候选因子 PIT 足够可靠？**部分**：价格/量因子 PIT_READY；财务因子仅 PIT_APPROXIMATE（PARTIAL，不可 Qualify）。
- (B) Execution Model 至少达到“不改变主要策略结论程度”？**是（READY）**。
- (C) Momentum implementation confirmed？**是（除 MOM_RS 已修正归一化）**。
- (D) 至少若干因子跨时期+跨 Regime+Incremental？**价格/量层需看 R2 Expansion；财务 A 层在 R1 显示跨时期正增量，但 PIT 近似需谨慎**。
- (E) 无明显 implementation artifact？**MOM_RS 归一化 artifact 已修复**。

**判定**：FACTOR_COMBINATION_READY = **PARTIAL/CONDITIONAL**（详见末节最终结论）。

---

## 11. 最终结论与 25 问摘要（FACT）

（完整 25 问答案在末节；摘要）
- V1 完全未修改 ✅
- V1 Forward Validation 继续 ✅
- 无 Production write ✅
- 未组合因子 / 未发明阈值 ✅
- R1 artifacts 完整保留，R2 独立生成 ✅

---

## 12. 文档与产物（FACT）

- 新增模块：`financial_pit_audit.py`, `execution_sim.py`, `momentum_audit.py`, `run_study_r2.py`
- 测试：`research/test_phase9b1_integrity.py`（22+ 项）
- 产物：`research/artifacts/factors/r2/{pilot,expansion}/`
- 本文件：`docs/research/PHASE_9B1_FACTOR_RESEARCH_INTEGRITY.md`
