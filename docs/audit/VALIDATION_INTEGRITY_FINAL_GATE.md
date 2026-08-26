# Validation Integrity Final Gate（Phase 8-L）

> 基线：hermes-stock-phase-8k5 / 61b6d12 → 本阶段 tag: hermes-stock-phase-8l0
> 日期：2026-08-26。最终验证可信度审计，零生产逻辑修改。

## 最终状态：VALIDATION_INTEGRITY = CLEAN ✅

**OPEN_FORMAL_VALIDATION = True** — 允许正式进入 2026-08-27 起的 V1 Forward Validation。

## A-K 11 项 Gate 结果

| Gate | 结果 | 说明 |
|---|---|---|
| A. Decision Integrity | ✅ CLEAN | Final Action 全部 DecisionEngine 产生（K0 确认唯一 Owner）；snapshot 持久化由 K1 self-check 保证；无第二 Final Owner |
| B. Data Freshness | ✅ CLEAN | market_cache latest 检查；stale 不默认 READY |
| C. DB Isolation | ✅ CLEAN | wrong_db_access_count=0；execution/outcome_store→market_cache；real_portfolio_truth→real_history；Real=FEISHU_BITABLE |
| D. Simulation Valuation | ✅ CLEAN | cash+holdings=total；valuation_inconsistency=0；legacy 全排除（validation_trades=0） |
| E. Task Chain | ✅ CLEAN | market-cache→daily-data→double-monitor→stop-loss 链路组件齐全 |
| F. Decision Persistence | ⚠️ UNRESOLVED_BUT_CONTAINED | K1 root cause 未解，但 5 项隔离证明全 True（不静默/不造假 Evidence/不伪装 Delivery/可检测/可排除）→ DEGRADED 不构成 BLOCK |
| G. Real Holdings | ✅ CLEAN | FEISHU_BITABLE 唯一源；sim 不读 real、real 不读 sim |
| H. Daily/Urgent Reconciliation | ✅ CLEAN | urgent⊆daily；mismatch=0 |
| I. Delivery Integrity | ✅ CLEAN | delivery≠creation；duplicate suppression；不伪造 USER_RECEIVED |
| J. Output Authority | ✅ CLEAN | FINAL=Engine；SIGNAL/INFO/HEALTH/DEBUG 非 Final；is_final 必带 decision_id |
| K. Validation Boundary | ✅ CLEAN | START=2026-08-27；legacy 8/9~8/26 标 PRE_FIX_LEGACY_RESULT 排除；auto_change 阻断 |

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
