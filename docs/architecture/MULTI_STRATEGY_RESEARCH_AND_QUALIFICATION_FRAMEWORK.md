# 多策略研究 & 资格认证框架（Multi-Strategy Research & Qualification Framework）

> Phase 9-A · 2026-08-27
> 文档目标：说明为什么需要多策略、框架如何工作、各模块职责、硬门槛，以及 Phase 9-B 的下一步。

---

## 0. 设计起点：研究的目标不是"找最高收益"

历史收益高 ≠ Qualified。

研究的真正目标：寻找历史上具有 **足够收益、风险控制、跨时期稳定性、跨 Regime 稳定性、执行可行性、数据可信度、统计充分性** 的候选策略。

必须区分三层概念，永远不混用：
- **HISTORICAL PERFORMANCE**：历史回测表现。
- **ROBUSTNESS**：跨时期 / 跨 Regime / 跨市值 / 参数扰动下的稳定性。
- **QUALIFICATION**：通过统一 Gate 后获得的资格状态。

---

## 1. 为什么需要多策略竞技场

当前系统只有 V1（Top3 翻倍潜力）。但 V1 是"一个不断调参的基线"，不是策略生态。

我们想要的体系：
```
Historical Research
       ↓
Strategy Candidate
       ↓
Qualification
       ↓
Shadow / Forward Validation
       ↓
Qualified Strategy Pool
       ↓
Strategy Selector（未来阶段，本阶段 OFF）
```

多策略必须同时满足：
1. 可以并存（V1 / V2 / V3 同台）。
2. 独立记账（互不污染）。
3. 公平比较（同一数据 / 同一 outcome / 同一执行口径）。
4. 通过 Qualification Gate 后进入 Shadow / Forward Validation。
5. 不拥有最终交易权威。

---

## 2. Strategy Lifecycle（策略生命周期）

显式状态（不靠文件夹名判断）：
```
RESEARCH → HISTORICAL_TESTING → QUALIFICATION → SHADOW → FORWARD_VALIDATION → PRODUCTION
                                                                  ↘ REJECTED
                                                                  ↘ RETIRED
```

- **RESEARCH**：研究候选，尚未进入系统测试。
- **HISTORICAL_TESTING**：历史回测 / 稳健性研究。
- **QUALIFICATION**：资格认证中。
- **SHADOW**：通过认证，进入 Shadow（hypothetical，非真实交易）。
- **FORWARD_VALIDATION**：前向验证（独立记账）。
- **PRODUCTION**：进入生产（仅未来 Selector 阶段）。
- **REJECTED / RETIRED**：未通过 / 退役。

每个策略的状态记录在 `StrategyRegistry`（JSON 持久化），不靠目录结构推断。

---

## 3. Research vs Qualification vs Production（三层分离）

| 层 | 职责 | 是否可交易 | 权威 |
|----|------|-----------|------|
| Research | 假设 → 因子 → 回测 → 稳健性 | 否 | 无 |
| Qualification | 通过统一 Gate 判定资格 | 否 | 无 |
| Shadow | 假设的进出场观测 | 否（hypothetical） | 无 |
| Forward Validation | 实时独立记账观测 | 否 | 无 |
| Production | 真实执行 | 是 | DecisionEngine |

**核心架构约束**：
- Strategy Registry **不拥有 Final Decision Authority**。
- Strategy 只是"候选策略定义"。
- 最终交易权威仍是 **DecisionEngine**。
- 未来 Selector 也 **不能直接成为最终交易 Authority**：
  ```
  Strategy → Selector（未来） → DecisionEngine → Final Action
  ```

---

## 4. Dataset Registry（数据登记）

所有策略研究必须绑定 `dataset_id + version`。这样未来 V1 vs V2 可以证明：是不是在同一数据环境里比较。

`DatasetSpec` 必须显式暴露已知缺口（Phase 9-A 三十），不得隐藏：

| 缺口 | 状态 |
|------|------|
| Historical ST | **BLOCKED** |
| Historical Market Cap | PARTIAL（部分 APPROXIMATE） |
| Historical Execution Model | PARTIAL（涨停不可买未建模） |
| Survivorship | LIMITED（退市股未纳入） |
| 指数历史缺口 | 000300 仅至 2026-07-24 |

这些缺口进入资格判断：若关键缺口影响策略核心逻辑 → `QUALIFICATION = BLOCKED / DATA_INSUFFICIENT`，而不是"收益不错，所以先通过"。

---

## 5. PIT（Point-in-Time）Integrity

所有历史策略记录 `PIT_STATUS`（READY / PARTIAL / BLOCKED），检查维度：
- future leakage（未来信息泄漏）
- survivorship（幸存者偏差）
- historical market cap（历史市值）
- historical ST（历史 ST）
- financial effective date（财报生效日）
- signal timestamp / trade timestamp

已知：`Historical ST = BLOCKED`、`Market Cap = APPROXIMATE`。
**禁止**简单输出 `PIT_COMPLETE`。必须精确记录哪些因子完整 / 哪些 APPROXIMATE / 哪些 UNKNOWN / 哪些 BLOCKED。

复用既有 PIT 研究模块（不修改）：
- `research/candidate_pit.py`：V1 候选 PIT 重建。
- `research/regime_pit.py`：Market Regime PIT 重建（000300 缺口显式 UNKNOWN）。

---

## 6. Execution Model（执行模型）

当前 Historical Backtest 已知"涨停不可买"未完整建模——**不能继续假装不存在**。

`ExecutionModelSpec` 声明覆盖/未覆盖的执行约束：
- 涨停不可买 / 跌停不可卖 / 停牌 / 缺失价格 / 一手 100 / T+1 / 滑点 / 手续费 / 流动性 / 开盘收盘语义。

状态：
- **READY**：完整建模，可支撑 QUALIFIED。
- **PARTIAL**：部分建模（如涨停未建模）→ 可研究但 **不得 QUALIFIED** 直到达标。
- **BLOCKED**：关键约束不可用。

默认 `EXEC_PARTIAL`：涨停不可买未建模 → `is_qualified_ready()=False`。

---

## 7. Walk-Forward（主测试方式）

核心策略不能只看 Full History Backtest。必须至少支持 TRAIN / VALIDATION / HOLDOUT，按时间严格推进。
**禁止**用未来 Holdout 选择参数。建议 Rolling / Expanding Walk-Forward。

多轮研究管线（Phase 9-A 十五）：
```
ROUND 1 Discovery → 2 In-Sample → 3 Out-of-Sample → 4 Walk-Forward →
5 Regime → 6 Time Stability → 7 Cost/Slippage → 8 Execution Feasibility →
9 Parameter Perturbation → 10 Universe/Market-Cap → 11 Stress Test → 12 Multiple-Testing Review
```
不能只跑一次 Backtest。

---

## 8. Regime / Robustness / Cost / Statistical Gate

### Regime 稳定性
策略必须回答：在强趋势 / 高波动 / 低量能 / 震荡市 下是否都成立。

### Robustness
至少覆盖：
- 时间稳定性（time stability）
- Regime 稳定性（regime stability）
- 市值稳定性（market-cap stability）
- 参数稳定性（parameter stability）

### Cost / Slippage 敏感性
必须记录：turnover、slippage sensitivity、liquidity failure、limit-up block rate、limit-down block rate。所有分母必须完整。

### Statistical Sufficiency vs Data Sufficiency（Phase 9-A 二十）
- **DATA SUFFICIENCY** ≠ **STATISTICAL SUFFICIENCY**。
- 历史 10000 条候选记录 ≠ 10000 个独立交易样本。
- `StrategyResearchRun` 至少保留：
  `candidate_n / signal_n / trade_n / independent_trade_n / period_n / regime_n`。

---

## 9. Multiple Testing 防护（Phase 9-A 三十三）

若研究 100 因子 × 100 阈值 × 20 组合，不能最后只报告最好的一组。
必须记录 `research_search_space` 与 `multiple_testing_status`。
未完整校正 → 明确为 **DISCOVERY_ONLY**，**不得直接 Qualified**。

---

## 10. Candidate / Signal / Trade 严格分离（Phase 9-A 十一）

所有研究区分：
```
CANDIDATE → SIGNAL → ENTRY → EXECUTION → OUTCOME
```
- Candidate return 好 ≠ Strategy return 好。
- Candidate ≠ Signal ≠ Executed Trade。
- 未成交信号、未覆盖的流动性、交易成本，都不得从分母剔除。

`TradeLedgerRow` 三层标记：`is_signal`（信号层）、`is_executed`（实际进场）。

---

## 11. Comparison（公平比较）

`StrategyComparisonRow` 统一维度：
- **Return**：cumulative / CAGR / median / average trade return
- **Risk**：max drawdown / downside quantiles / volatility / Calmar / Sortino
- **Trade**：win rate / payoff ratio / profit factor / trades / holding period
- **Execution**：turnover / slippage sensitivity / liquidity failure / limit-up/down block rate
- **Robustness**：time / regime / market-cap / parameter stability
- **Data**：PIT / survivorship / missing / approximate

**严禁"冠军策略"思维**：输出 `QUALIFIED_STRATEGIES` 列表，而非单 `BEST_STRATEGY`（除非明确定义 `BEST_UNDER_DEFINED_OBJECTIVE` 并输出 objective/constraints/data_quality/robustness）。

---

## 12. Qualification Gate（资格认证）

结论：`QUALIFIED / CONDITIONALLY_QUALIFIED / REJECTED / DATA_INSUFFICIENT`。

四类 Gate：
1. **Data Gate**：PIT sufficient / Execution Model sufficient / Survivorship acceptable。
2. **Performance Gate**：minimum trade count / return / risk / drawdown。
3. **Robustness Gate**：time / regime / parameter stability。
4. **Statistical Gate**：statistical sufficiency / multiple-testing control。

**阈值策略**（Phase 9-A 十九）：
- 本阶段不擅自固定所有数值阈值。
- 先复用既有项目定义的 Gate；未定义阈值标 **UNDEFINED** 并输出 **QUALIFICATION_THRESHOLD_GAP**。
- 禁止为了让某策略通过而发明阈值。

判定逻辑：
- 数据门槛不达标 → `DATA_INSUFFICIENT`（ST 未 BLOCKED 时）或 `REJECTED`。
- 定义阈值未满足 → `REJECTED`。
- 阈值未定义 / 未校正 → `CONDITIONALLY_QUALIFIED`（不能直接 QUALIFIED）。

---

## 13. Shadow（Phase 9-A 二十四）

QUALIFIED 策略不能直接进入 Production。必须 `QUALIFIED → SHADOW`。
Shadow 至少记录：candidate / signal / hypothetical entry / hypothetical exit / hypothetical trade / MAE-MFE / regime / timestamp。
**shadow ≠ production**（代码层强制 `is_production=False`）。

---

## 14. Forward Validation（Phase 9-A 二十五）

每个策略保留：`strategy_id / strategy_version / validation_start / validation_dataset_version`。
多个策略可同日起跑，但**独立记账**（strategy-specific ledger，partition_key = `id@version`）。

---

## 15. Reproducibility（Phase 9-A 三十二）

任意研究可由 `(strategy_id, strategy_version, dataset_id, dataset_version, run_id)` 重现。
必须记录：code_version / config_version / data_version / execution_version / cost_version / random_seed。

---

## 16. Strategy Selector 的未来位置

本阶段 **Strategy Selector = OFF**。

未来架构：
```
Strategy (定义) → Registry → Qualification → Shadow → Forward Validation
       ↓
Qualified Strategy Pool
       ↓
Strategy Selector（未来阶段启用，仍非最终权威）
       ↓
DecisionEngine → Final Action
```

Selector 只是"从 Qualified Pool 中选择执行哪个"，**不能直接下单**。最终权威永远是 DecisionEngine。

---

## 17. 当前 V1 的特殊约束

V1（自 2026-08-27 起）：
- 继续 **FROZEN**。
- 继续 **Forward Validation**。
- 在框架中定位 = **BENCHMARK_STRATEGY**（比较基准，不参与新资格认证）。
- 不得 reset / modify / add factors / optimize / change thresholds。

V2（第一阶段）：
- 仅 `RESEARCH_ONLY`，不形成 production rule。
- 研究假设 = HYPOTHESIS（非 FACT）："Quality+Growth+Momentum+Regime+Risk 可能比单纯极端成交量过滤更稳定"。
- 第一轮顺序：Quality → Growth → Momentum → Volume → Valuation → correlation → incremental → 构建 → … → Walk-forward → Qualification。
- 禁止一开始 100 分模型 / 手工权重（如 Quality 25% / Momentum 20% / Growth 15%）。

---

## 18. 模块清单（research/）

| 模块 | 职责 |
|------|------|
| `strategy_registry.py` | StrategySpec + Registry（唯一身份，显式状态） |
| `dataset_registry.py` | DatasetSpec（绑定 dataset_id+version + 已知缺口） |
| `strategy_contract.py` | 统一 14 字段研究契约 + 统一 outcome 口径 |
| `strategy_runner.py` | 统一历史 Pipeline（StrategyResearchRun + 独立记账） |
| `execution_models.py` | EXECUTION_MODEL_STATUS（READY/PARTIAL/BLOCKED） |
| `pit_gate.py` | PIT Integrity（READY/PARTIAL/BLOCKED） |
| `survivorship_gate.py` | Survivorship（CLEAN/LIMITED/BLOCKED） |
| `multiple_testing.py` | Multiple Testing（DISCOVERY_ONLY/BONFERRONI/FDR） |
| `factors/factor_contract.py` | 25 因子候选 + 每因子 10 问 / 8 产出 |
| `strategy_comparison.py` | StrategyComparisonRow（六维比较） |
| `qualification_gate.py` | 四类 Gate + 结论 + threshold gap |
| `validation_contracts.py` | Shadow / Forward Validation / Reproducibility |
| `artifacts_layout.py` | run 目录 + FACT/EVIDENCE/HYPOTHESIS 三层 |
| `adapters/v1_adapter.py` | V1 adapter（只读复用，不改 V1） |
| `v2_research_spec.py` | V2 研究假设 + 12 步顺序 + 禁止早期权重 |

---

## 19. 测试与验收

- 新增 `test_phase9a_research_framework.py`：**48 项全过**（Registry/Contract/Dataset/Comparison/Qualification/PIT/Execution/Multiple-Testing/Isolation/集成/Shadow/Forward/Factor/Reproducibility/Artifacts/Persistence）。
- 既有 decision 套件：**516 项全过**（满足 512+ 要求）。
- 无生产代码修改；V1 Forward Validation 不受影响。

---

## 20. 下一阶段（Phase 9-B）

仅允许：**V2 第一轮 Factor Research**（先独立研究因子，再组合）。
继续：**V1 Forward Validation**。

最终目标：建立一个能不断 **发现 / 验证 / 淘汰 / 晋级** 策略的研究体系，而不是只拥有一个不断调参的 V1。
