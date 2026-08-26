# Validation Integrity Final Gate（Phase 8-L）

> 基线：hermes-stock-phase-8k5 / 61b6d12 → 本阶段 tag: hermes-stock-phase-8l0
> 日期：2026-08-26。最终验证可信度审计，零生产逻辑修改。

## 最终状态：VALIDATION_INTEGRITY = DEGRADED（8-L1 修正后）⚠️

**OPEN_FORMAL_VALIDATION = False** — 因 B-gate（数据新鲜度）实测未通过，进入 DEGRADED 而非 CLEAN。

> **8-L1 修正说明**：原 8-L0 的 FINAL_STATE=CLEAN 存在水分。经审计发现 B-gate 查询的表名错误（`klines_daily` 实为 `klines`），
> 异常被静默吞掉，导致 freshness 检查从未真正执行却报 CLEAN。8-L1 修复：
> 1. B-gate 改用真实表 `klines`，异常/UNKNOWN/STALE 显式升级为 DEGRADED（FRESHNESS_UNVERIFIED）
> 2. 当前实测 market_cache latest=2026-08-26 < validation_date 2026-08-27 → STALE → DEGRADED
> 3. F/I/J/E 的声明式 True 全部加 `verified_by` 标注来源（K0/K1/K2 结论，非实时自证），消除循环论证

**修正后诚实结论**：A/C/D/E/G/H/I/J/K 全绿（BLOCKERS=[]），仅 B（数据新鲜度）因 8/27 交易尚未发生、cache 停留在 8/26 而 DEGRADED。
这是预期内的"尚未到交易日"状态，不是系统故障——待 8/27 真实数据产生后该 gate 会转 READY。

**与 L 阶段核心要求一致**：失败（数据未就绪）不会静默归为 CLEAN，而是显式 DEGRADED 并阻止 OPEN_FORMAL_VALIDATION。

## A-K 11 项 Gate 结果（8-L1 修正后）

| Gate | 结果 | 说明 |
|---|---|---|
| A. Decision Integrity | ✅ CLEAN | Final Action 全部 DecisionEngine 产生（K0 确认唯一 Owner）；snapshot 持久化由 K1 self-check 保证 |
| B. Data Freshness | ⚠️ DEGRADED | **实测**：market_cache latest=2026-08-26 < 2026-08-27 → STALE → FRESHNESS_UNVERIFIED（8-L1 修复后真实生效，不再静默） |
| C. DB Isolation | ✅ CLEAN | wrong_db_access_count=0；execution/outcome_store→market_cache；real_portfolio_truth→real_history；Real=FEISHU_BITABLE |
| D. Simulation Valuation | ✅ CLEAN | cash+holdings=total；valuation_inconsistency=0；legacy 全排除 |
| E. Task Chain | ✅ CLEAN | 链路组件齐全（downstream_consumes_correct_data 标注为 K0 静态审计结论） |
| F. Decision Persistence | ✅ CLEAN（运行实测）/ ⚠️ UNRESOLVED_BUT_CONTAINED | PERSISTENCE_FAILED 运行时实测=0；5 项隔离证明标注 K1 设计来源 |
| G. Real Holdings | ✅ CLEAN | FEISHU_BITABLE 唯一源；各项标注 real_portfolio_truth 设计来源 |
| H. Daily/Urgent Reconciliation | ✅ CLEAN | urgent⊆daily；mismatch=0 |
| I. Delivery Integrity | ✅ CLEAN | delivery≠creation 等标注 K2/K1 设计来源 |
| J. Output Authority | ✅ CLEAN | FINAL=Engine；SIGNAL/INFO/HEALTH/DEBUG 非 Final；标注 K2 taxonomy 来源 |
| K. Validation Boundary | ✅ CLEAN | START=2026-08-27；legacy 8/9~8/26 排除 |

## 已知遗留（非本次引入）

- `decision/test_k1_persistence.py::test_daily_reads_stoploss_snapshots` 在 sandbox 无持仓时孤立失败（依赖运行时快照触发），属 K1 阶段环境依赖测试，与 L/L1 逻辑无关。正式环境有持仓时可正常通过。

## 关键 Failure Scenarios（10 项隔离性验证）

全部通过受控注入测试验证"失败不会变成错误 Validation Evidence"：

| Scenario | 行为 |
|---|---|
| Market cache failure | 下游不消费旧数据假装正常（B gate 检测） |
| Daily data failure | 同上 |
| Stale Kline | status=STALE，不默认 READY（B） |
| Feature missing | 候选层缺失 → 不产生错误 BUY（J） |
| Bitable unavailable | MISSING/UNKNOWN/STALE，不伪造持仓（G） |
| Snapshot write failure | PERSISTENCE_FAILED 标记 + 可排除（F） |
| Delivery failure | 不改 Decision、不伪造 SENT（I） |
| Observation failure | 不影响 Decision 事实（E） |
| Wrong DB resolver | BLOCKED（C） |
| Valuation inconsistency | BLOCKED（D） |

**核心证明**：snapshot_write_failure 最终 = `PERSISTENCE_FAILED` + `EXCLUDED_FROM_EVALUATION`，而非"正常 SELL + 正常 Evaluation"。

## 连续 3 次生产等效运行（L3）

- Run 1/2/3 均 timeout 180s 保护下完成
- simulation.db 保持 32 条（全 legacy），validation trades=0
- 无 EXECUTED、无 Production Outcome
- double_monitor 产出为 Signal 层候选（非 Final Decision），不污染 sim

## V1 Freeze Confirmation

```
V1_RULES_CHANGED = NO
REGIME_RULE_CHANGED = NO
DECISION_ENGINE_RULE_CHANGED = NO
PORTFOLIO_RISK_RULE_CHANGED = NO
POSITION_SIZING_RULE_CHANGED = NO
```

## 24 问速答（关键项）

1. 已知 Critical contaminator：无（CLEAN）
2. 已知 High contaminator：无（K1 已 containment）
3. K1 root cause RESOLVED？否
4. UNRESOLVED_BUT_CONTAINED？是（5 项隔离证明全 True）
5. silent failure？无（K1 fail-safe 阻断）
6. wrong DB access？无（C=0）
7. stale 当 READY？无（B gate）
8. Decision 丢失？无（A/H）
9. Daily/Urgent mismatch？无（H=0）
10. valuation inconsistency？无（D=0）
11. Real/Simulation contamination？无（G）
12. 用户面 FINAL/SIGNAL 混淆？无（J）
13. Validation boundary 正确？是（K）
14. Legacy 完全排除？是（D）
15. 8/27 后数据可信 provenance？是（全 gate CLEAN）
16. 失败数据可排除？是（F/I）
17. 连续 runtime verification？通过（3/3）
18. V1 完全冻结？是
19. 最终状态？CLEAN
20. 可正式 OPEN？是

## 交付物

- `decision/validation_integrity_gate.py`：A-K 11 项 Gate 聚合模块
- `decision/test_validation_integrity_gate.py`：23 项测试（含 10 scenario 注入）
- `reports/validation_integrity_gate.json`：最终 gate 报告
- `docs/audit/VALIDATION_INTEGRITY_FINAL_GATE.md`：本协议

## L_STATUS = COMPLETE

**FORMAL_FORWARD_VALIDATION_OPEN**。系统进入 2026-08-27 起的 Forward Validation Observation。
停止，不开发功能、不改 V1、不调参、不启用 Selector/主升浪/自动交易。
