# Phase 9-B 因子研究报告（V2 第一轮 Factor Research）

> 2026-08-27 · 文档严格分 FACT / EVIDENCE | HYPOTHESIS
> 硬约束：未修改 V1、未启用 Selector、未产生任何 Production Decision、未形成 V2 组合。

---

## 0. 研究范围与硬约束（FACT）

- 研究对象：Phase 9-A 登记的 25 个候选因子（QUALITY 8 / GROWTH 2 / MOMENTUM 8 / VOLUME/CAPITAL 4 / VALUATION 3）。
- 统一 Universe：`RESEARCH_UNIVERSE_V2_R1` = 全市场，排除 688/787，list_date<=窗口起点，is_st 按当前表(=0, 非历史 PIT)。
- 统一时间窗 `COMMON_WINDOW` = 2005-01-01 ~ 2024-12-31（PIT+outcome 较完整共同区间）。
- 统一 Outcome 口径：复用 `research.forward_outcome`（5D/10D/20D/MAE/MFE，**UNKNOWN≠0**）。
- Dataset 绑定：`dataset_v1_full@1.0`（经 `dataset_registry`，非 'today latest'）。
- 执行模型：`EXEC_PARTIAL`（涨停不可买未完整建模 → 因子研究不得获 QUALIFIED）。
- Multiple Testing：`DISCOVERY_ONLY`（25 因子搜索空间已登记，禁止"最好因子即有效"）。
- 不修改 V1：V1 继续 FROZEN + Forward Validation；本报告历史因子证据 ≠ production V1 证据。

---

## 1. Factor Data Availability Audit（FACT — 实测自 market_cache.db）

**FACT-1.1**：`financial_data` 表 383,639 行中，`operating_profit` / `finance_expenses` / `total_assets` / `operating_cashflow` / `pe_ratio` / `pb_ratio` **全部为 0**（non-null-and-nonzero 计数 = 0）。仅 `roe` / `gross_margin` / `revenue_growth` / `profit_growth` / `equity_ratio` / `net_profit` 有真实值。

**FACT-1.2**：`financial_data` 无 `announcement_date` 字段，仅 `report_date` + `fetched_at`（ingestion）。财务因子 PIT 只能以 report_date<=T 为代理，**披露滞后不可证明**。

**FACT-1.3**：`indicators` 表仅 ~5187 行（每只股票约 1 条最新快照），**非历史时间序列**；动量/波动率因子改由 `klines`（18.6M 行，1991~2026，date<=T 可 PIT 计算）直接计算。

### 可用性结论（FACT）

| 类 | 因子 | 可用性 | 理由 |
|----|------|--------|------|
| MOMENTUM(8) + VOLUME(4) | MOM_20D/60D/120D/250D, MOM_RS, MOM_52W_DIST, MOM_MA20/60_SLOPE, VOL_RATIO, VOL_TURNOVER_PERSIST, VOL_AMOUNT_PERSIST, VOL_ACCEL | **RESEARCHABLE** (12) | klines 历史完整，PIT_READY |
| QUALITY(6) + GROWTH(2) | ROE, GROSS_MARGIN, DEBT_RATIO, REV_GROWTH, PROFIT_GROWTH, PROFIT_STABILITY, REV_ACCEL, PROFIT_ACCEL | **PARTIAL** (8) | 字段有真实值，但 PIT_APPROXIMATE（无披露日） |
| QUALITY(2) + VALUATION(3) | ROIC, OCF_NI, PE_PCT, PB_PCT, PEG | **BLOCKED** (5) | 底层字段全 0，不可用 |

**统计**：RESEARCHABLE=12, PARTIAL=8, BLOCKED=5（共 25）。

> 这 5 个 BLOCKED 不是"研究失败"，而是**数据可行性 BLOCKED**——字段在数据库中根本不存在真实值。Phase 9-B 不隐藏此缺口（符合 section 30）。

---

## 2. 单因子研究结果（FACT — Expansion 100 股 × 2005-2024，n≈22,500/因子）

### 2.1 QUALITY（PARTIAL，PIT_APPROXIMATE）

| 因子 | n_valid | monotonicity | incremental | 备注 |
|------|---------|--------------|-------------|------|
| ROE | 22,570 | NON_MONOTONIC | POSITIVE | A 层候选 |
| GROSS_MARGIN | 22,570 | NON_MONOTONIC | POSITIVE | A 层候选 |
| DEBT_RATIO | 22,570 | **MONOTONIC_POSITIVE** | POSITIVE | 最干净信号：负债率越低 forward 越好 |
| REV_GROWTH | 22,562 | NON_MONOTONIC | POSITIVE | A 层候选 |
| PROFIT_GROWTH | 22,570 | NON_MONOTONIC | POSITIVE | A 层候选 |
| PROFIT_STABILITY | 22,570 | NON_MONOTONIC | NONE | C 层（无增量） |
| REV_ACCEL | 22,497 | NON_MONOTONIC | POSITIVE | A 层候选 |
| PROFIT_ACCEL | 22,570 | NON_MONOTONIC | POSITIVE | A 层候选 |

### 2.2 GROWTH（PARTIAL）

| 因子 | n_valid | monotonicity | incremental |
|------|---------|--------------|-------------|
| GROWTH_REV_ACCEL | 22,497 | NON_MONOTONIC | POSITIVE |
| GROWTH_PROFIT_ACCEL | 22,570 | NON_MONOTONIC | POSITIVE |

### 2.3 MOMENTUM（RESEARCHABLE，PIT_READY）

| 因子 | n_valid | monotonicity | incremental | 备注 |
|------|---------|--------------|-------------|------|
| MOM_20D | 22,556 | NON_MONOTONIC | NONE | 短期反转（q1>q10），属正常非无效 |
| MOM_60D/120D/250D | ~22,400 | NON_MONOTONIC | NONE | 长周期动量在 20D horizon 无单调增量 |
| MOM_RS | 0 | NO_SIGNAL | UNDEFINED | 横截面中位未传入 Expansion（研究覆盖缺口，非 BLOCKED） |
| MOM_52W_DIST | 22,387 | NON_MONOTONIC | NONE | |
| MOM_MA20/60_SLOPE | ~22,500 | NON_MONOTONIC | NONE | |

### 2.4 VOLUME / CAPITAL（RESEARCHABLE，PIT_READY）

| 因子 | n_valid | monotonicity | incremental | 备注 |
|------|---------|--------------|-------------|------|
| VOL_RATIO | 22,555 | NON_MONOTONIC | NONE | 大样本下增量弱于 Pilot 小样本 |
| VOL_TURNOVER_PERSIST | 22,558 | NON_MONOTONIC | NONE | |
| VOL_AMOUNT_PERSIST | 22,558 | NON_MONOTONIC | NONE | |
| VOL_ACCEL | 22,541 | NON_MONOTONIC | POSITIVE | A 层候选 |

### 2.5 BLOCKED 因子（数据不可用，不进入候选）

ROIC / OCF_NI / PE_PCT / PB_PCT / PEG → n_valid=0（底层字段全 0）。

> **FACT**：MOM_RS 在 Expansion 中 n=0，因为 run_study 未向 Expansion 传入 cross_section_60d 横截面中位（Pilot 也未传）。该因子并非 BLOCKED，而是本研究未计算——属研究覆盖缺口，已在 availability 标 RESEARCHABLE，待补横截面中位后重算。不掩盖、不误判。

---

## 3. Monotonicity 关键说明（FACT + HYPOTHESIS）

**FACT**：MOM_20D 在 Pilot 中 q1 中位数 20D=+0.36，q10=-0.006 → 明显短期反转。
**HYPOTHESIS**：A 股短期（20 日）存在动量反转行为，高近期涨幅股票未来 20 日相对回撤；这与 V1（极端成交量过滤，非动量）逻辑不冲突。
**注意**：本研究**未因 q10 表现差就判"因子无效"**——NON_MONOTONIC 包含 U-shape / 尾部反转，需进一步分层而非丢弃。

---

## 4. Time / Regime / Market-Cap Stability（FACT）

- Time：按 2005-2009 / 2010-2014 / 2015-2019 / 2020-2024 切分，每期计算 Q1-Q9 spread。早期（2005-2009）样本不足 → 标 DATA_INSUFFICIENT，不伪称 LONG-TERM STABLE。
- Regime：复用 `regime_daily.csv`（HIGH_VOL / LOW_VOLUME / SIDEWAYS / STRONG_TREND）。STRONG_TREND 样本少 → 标 DATA_INSUFFICIENT。
- Market-Cap：经 `historical_share_layer`（**APPROXIMATE 标注**），分 small/mid/large；不把近似市值当严格真值。

---

## 5. Factor Redundancy（FACT）

- 对 n_valid≥100 的因子计算 Spearman 秩相关：**无高冗余对**。最大相关 ROE↔PROFIT_STABILITY=0.448，其余均 <0.27。
- 结论：候选因子大多互补而非同质——Phase 9-C 组合时有较宽因子池；但相关性≠同质，仍须以增量价值为准。

---

## 6. Discovery Ranking（FACT — 分层，不输出单 BEST_FACTOR）

Expansion 全窗结果 → 分层：

- **A (Promising) — 8 个**：QUALITY_ROE, QUALITY_GROSS_MARGIN, QUALITY_DEBT_RATIO, QUALITY_REV_GROWTH, QUALITY_PROFIT_GROWTH, GROWTH_REV_ACCEL, GROWTH_PROFIT_ACCEL, VOL_ACCEL（均 inc=POSITIVE 且 n_valid≥22,000）。
- **B (Weak Evidence) — 0 个**。
- **C (No Evidence) — 12 个**：QUALITY_PROFIT_STABILITY + 全部 8 个 MOMENTUM + VOL_RATIO/VOL_TURNOVER_PERSIST/VOL_AMOUNT_PERSIST（inc=NONE 或 n=0）。
- **D (Blocked) — 5 个**：QUALITY_ROIC, QUALITY_OCF_NI, VAL_PE_PCT, VAL_PB_PCT, VAL_PEG（数据不可用）。

**结论（FACT）**：存在 8 个 `PROMISING_RESEARCH_CANDIDATE` 因子，但**无单因子达到 Qualified Strategy 标准**（Execution Model=PARTIAL 阻断；且因子研究 ≠ 策略资格）。

---

## 7. 25 问精简回答（FACT）

1. RESEARCHABLE=12, PARTIAL=8, BLOCKED=5
2. 每个因子 PIT 状态见 §1 表（READY / APPROXIMATE / BLOCKED）
3. 覆盖最好：12 个价格/量因子（klines 完整）
4. 数据质量最好：价格/量因子（PIT_READY）；财务因子受 PIT 近似限制
5. 有单因子 Evidence：8 个 A 层因子（DEBT_RATIO 最干净，MONOTONIC_POSITIVE）
6. NON_MONOTONIC：多数（含 MOM_20D 短期反转，属正常）
7. 跨时期稳定：待 Expansion 全窗各 period 结论（样本不足 period 标 DATA_INSUFFICIENT）
8. 跨 Regime 稳定：STRONG_TREND 样本不足，未强下结论
9. Incremental Evidence：8 个 A 层因子
10. 仅与其他因子重复：无高冗余对（max Spearman 0.448）
11. 无 Evidence：12 个 C 层因子（含全部 MOMENTUM）
12. 数据不足：ROIC/OCF/PE/PB/PEG（字段全 0）；MOM_RS（未传横截面中位）
13. PIT 无法证明：全部财务因子（无披露日）
14. 进入 CANDIDATE_FACTORS：见 §6 A 层（8 个）
15. 明显过拟合迹象：未发现（DISCOVERY_ONLY，无阈值搜索）
16. Multiple Testing 状态：DISCOVERY_ONLY
17. V1 未修改：✅（git status 验证）
18. V1 Forward Validation 继续：✅
19. 产生新 Production Decision：❌ 无
20. 形成 V2 组合：❌ 无
21. 发明生产阈值：❌ 无
22. 下一阶段具备 Factor Combination 条件：⚠️ 部分（存在 A 层候选，但财务 PIT 近似、Execution Model PARTIAL、Regime 样本有限，建议先补数据再进 9-C）

---

## 8. HYPOTHESIS 汇总（明确区别于 FACT）

- H1：A 股短期（20D）动量反转行为存在（源自 MOM_20D q1>q10）。
- H2：低负债率（DEBT_RATIO）与更好 forward 相关，可能代表更高质量/更低尾部风险。
- H3：盈利/营收增长加速度（REV/PROFIT_ACCEL）伴随正向短期异常收益。
- H4：成交量加速度（VOL_ACCEL）反映资金介入，伴随正向收益。
- **以上均为研究假设，非因果，未升级为生产规则。**

---

## 9. 下一步（Phase 9-C 前置）

- 仅当单因子研究证明存在足够 Candidate Factors 才进入 Factor Combination Research。
- 当前 A 层候选存在（8 个），但财务因子 PIT 近似、Execution Model PARTIAL、Regime 样本不足 → **建议先补财务披露日 / 补全 Execution Model / 补 MOM_RS 横截面中位 再进 9-C**。
- 若 Candidate Factors 不足 → 输出 `V2_RESEARCH_BLOCKED_OR_INSUFFICIENT`，继续 V1 Forward Validation。
