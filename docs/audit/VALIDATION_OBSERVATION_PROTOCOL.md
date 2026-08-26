# V1 Forward Validation Observation Protocol（Phase 8-K5）

> 基线：hermes-stock-phase-8k4 / 2eab9e3 → 本阶段 tag: hermes-stock-phase-8k5
> 日期：2026-08-26。只读协议，零生产逻辑修改。

## 一、目标

把 2026-08-27 起的 V1 Forward Validation 变成严格、可持续、不可被随意污染的证据收集流程。
系统进入 **FORWARD VALIDATION OBSERVATION ONLY**，直到 2026-09-05 Checkpoint 或后续明确指令。

## 二、Validation Boundary

- VALIDATION_START = `2026-08-27`（J0D 修复生效时间戳 2026-08-26 16:53:39 之后）
- VALIDATION_END_TARGET = `2026-09-05`（仅 checkpoint，非自动 evaluation day）
- 只统计 `trade_date >= 2026-08-27` 的 validation trades；legacy（<8/27）完全排除
- 当前 simulation.db 全部 32 条 trades 均为 legacy → validation_trades = 0

## 三、每日 Readback 字段

模块：`decision/validation_readback.py`（只读聚合，写 `reports/validation_readback_<date>.json|txt`）

- VALIDATION_IDENTITY：start / date / trading_day / trade_day_number / state / status
- SYSTEM：calendar / market_data / daily_data / double_monitor / runtime_error / integrity
- V1_RULE_FREEZE：VR 2.7 / MC 5-90亿 / Amount 0.8亿 / 20D 0.4亿 / ATR≥3% / PP≤40% / Sig≥3 → V1_RULES_CHANGED=NO
- DECISION：candidate / final / BUY/ADD/HOLD/REDUCE/SELL/NO_TRADE / decision_ids
- SIMULATION：opening/closing cash/holdings/total / pnl / drawdown / validation_trades / legacy_trades
- REAL_HOLDINGS：source=FEISHU_BITABLE / readonly（不触发网络刷新）
- DELIVERY：persistence_failed_count / urgent_daily_gap / duplicate_suppressed
- EXECUTION：planned/executed/partial/rejected（Simulation 与 Production 完全分离）
- OUTCOME：SIMULATION(pending/closed) / PRODUCTION(count=0)
- GATE：trading_days / validation_trades / min / status / early_evaluation=BLOCKED
- CONTAMINATION：detected[] / VALIDATION_CONTAMINATION / 仅记录不重置
- RECONCILIATION：decision⊆daily / urgent⊆daily / sim_eq_canonical / real_eq_daily / delivery_eq_send
- CHECKPOINT：target_date / is_checkpoint_only / formal_evaluation_prerequisites

## 四、Validation Gate

复用 `decision/validation_baseline.py`：

| 条件 | 状态 |
|---|---|
| trading_days < 20 OR validation_trades < 10 | `DATA_INSUFFICIENT`（不判失败） |
| 满足样本量 | `EVALUABLE`（允许评价，不提前判 PASS/FAIL） |

前置条件（9/5 才检查）：trading_days≥20 / validation_trades≥10 / win_rate≥0.50 / max_drawdown≤0.15

**禁止提前强评**：early_evaluation 字段恒为 BLOCKED。

## 五、Contamination Rules

检测项（仅标记，不删数据、不重置）：

- valuation formula changed → VALUATION_CONTAMINATION
- DB isolation violated / wrong DB / stale input / corrupted state → VALIDATION_CONTAMINATION
- decision persistence failure → PERSISTENCE_FAILED（K1 root cause 未解，专项监控）

分级：
- VALIDATION_CLEAN：数据可信，样本足够
- VALIDATION_DEGRADED：局部完整性问题（如 PERSISTENCE_FAILED>0），不阻止观察
- VALIDATION_BLOCKED：关键链错误（如 urgent/daily reconciliation gap>0）

**只有证据完整性问题才能 BLOCK，不能因收益不好进 BLOCKED。**

## 六、K1 Persistence Anomaly 监控

每日 readback 记录：
- `DELIVERY.persistence_failed_count`
- `DELIVERY.urgent_daily_reconciliation_gap`

PERSISTENCE_FAILED > 0 → VALIDATION_DEGRADED + 🚨 VALIDATION_INTEGRITY_ALERT
urgent/daily gap > 0 → VALIDATION_BLOCKED

## 七、Reconciliation（每日）

- Final decision IDs ⊆ Daily decision IDs
- Urgent decision IDs ⊆ Daily decision IDs（除非 EXPIRED/SUPERSEDED）
- Simulation trade count = canonical trade records
- Bitable snapshot = Daily Contract holdings source
- delivery record = application send result（不伪造 USER_RECEIVED）

## 八、9/5 Checkpoint

非自动 Evaluation Day。到 9/5：
- <20 交易日 OR <10 validation trades → DATA_INSUFFICIENT → 继续 Observation
- 满足 → 进入 FORMAL_V1_EVALUATION（本阶段不自动执行）

## 九、每日人工检查项

只需看：1) Daily Decision 2) Production Evidence Dashboard 3) Validation Readback（仅当状态≠ACTIVE）
不需要阅读全量 cron stdout / DEBUG log / 每个 signal / 每个 info task，除非异常。

## 十、约束遵守（本阶段）

| 项 | 状态 |
|---|---|
| V1 未修改 | ✅ |
| 生产逻辑未修改 | ✅ |
| 无新 Decision/Execution/Outcome | ✅ |
| simulation.db 未被 readback 写入 | ✅（测试验证 mtime 不变） |
| Cron schedule 未改 | ✅ |
| Feishu 未新增消息 | ✅（readback 仅 LOCAL/AUDIT） |
| Production Outcome 仍 0 | ✅ |

## 十一、新增文件

- `decision/validation_readback.py`：只读聚合模块
- `decision/test_k5_validation_readback.py`：24 项只读测试
- `reports/validation_readback_2026-08-27.json|txt`：首份 readback 样本
- `docs/audit/VALIDATION_OBSERVATION_PROTOCOL.md`：本协议

## 十二、K5_STATUS = COMPLETE

系统进入 FORWARD VALIDATION OBSERVATION ONLY。停止，不开发新功能、不改策略、不调参、不启用 Selector/主升浪/自动交易。
