# Validation Baseline Reset — 2026-08-27

> Phase 8-J0D。本 reset 是**逻辑边界 reset**（metadata/date boundary），
> 不是 data reset。Historical data was NOT deleted or modified.

## 1. Reset Provenance

| 项 | 值 |
|---|---|
| old_validation_start | 2026-08-09 |
| old_validation_end | 2026-08-26 |
| new_validation_start | **2026-08-27** |
| new_planned_end | 2026-09-05（若交易日不足20 → DATA_INSUFFICIENT，不强评） |
| reset_reason | RESET_REQUIRED（Phase 8-J0C 审计：验证期内全部 11 条 NAV 记录受估值层污染） |
| contamination_type | VALUATION_LAYER_CONTAMINATION_ONLY |
| contamination_evidence | docs/audit/VALIDATION_BASELINE_INTEGRITY_AUDIT.md（逐日新旧公式数值重放，误差<1元；周备份交叉证实无篡改） |
| affected_metrics | cash / total_asset / return / drawdown |
| unaffected_metrics | decision count / trade count / entry-exit facts / win-loss 分类 / holding period |
| initial_cash | 781,471.12（2026-08-26 收盘 simulation.db 真实值，非估算） |
| initial_holdings | 0 |
| initial_total_asset | 781,471.12 |
| initial_drawdown | 0（新期间从零起算；旧 65.53% 属 PRE_FIX_LEGACY_RESULT） |
| reset_timestamp | 2026-08-26（执行时刻见 git commit） |
| source_commit | 223d9f1 (hermes-stock-phase-8j0c) |
| operator | Hermes Agent (ox-alpha)，经用户 Phase 8-J0D 指令授权 |

**Statement: Historical data was NOT deleted or modified.**

## 2. 三层结果边界（互不覆盖）

```
PRE_FIX_LEGACY_RESULT   = 2026-07-29 ~ 2026-08-26 全部历史（含旧验证区间 8/9–8/26）
RAW_VALIDATION_RESULT   = 数据库实际记录（保留，仅供历史审计）
CLEAN_POST_FIX_RESULT   = 2026-08-27 起 V1 Forward Validation 产出
```

旧区间允许用途：历史行为审计、交易事实查询、bug 影响分析。
禁止用途：新 V1 win rate / return / drawdown / Strategy Readiness 评价。

## 3. VALIDATION_PERIOD_FILTER（实现方式）

单一权威定义落在 `decision/validation_baseline.py`：
`VALIDATION_START_DATE = '2026-08-27'`。
所有新 V1 Performance Evaluation 查询必须带
`WHERE trade_date >= VALIDATION_START_DATE`。
不复制 simulation.db、不建第二账户、不删历史。

## 4. 第一笔 Validation Trade 定义

自 2026-08-27 起，只有当前 V1 Candidate → 当前 V1 Decision → 当前 Simulation state
产生的交易属于 VALIDATION_TRADE。旧仓位（PRE_FIX_LEGACY）即使在 8/27 后产生动作，
仍归 PRE_FIX_LEGACY_RESULT，不自动计入 validation。

## 5. 新 Validation Gate

- Observation Start: 2026-08-27；Planned End: 2026-09-05
- ≥20 trading days 且 ≥10 valid V1 validation trades
- 8/27→9/5 自然日不足20交易日 → 输出 DATA_INSUFFICIENT，不得提前评价
- Gate 数值本身未修改

## 6. 未修改项核对

V1 参数（VR 2.7/市值5-90亿/成交额8000万等）、Regime、DecisionEngine、
Portfolio Risk、Position Sizing、Entry/Exit、Strategy Selector(OFF)、
主升浪(SHADOW_ONLY)、Historical Replay(OFF)、AUTO_TRADING(OFF)、
Production Outcome(0) —— 全部零改动。
