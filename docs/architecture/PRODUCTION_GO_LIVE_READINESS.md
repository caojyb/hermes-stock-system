# Production Go-Live Readiness

> 本文件记录 Hermes 股票系统进入 Production Observation Period 前的运行级验收结论。
> 本阶段不评价策略、不调参、不启用自动交易。

---

## 1. Runtime Entry

| 项目 | 值 |
|:---|:---|
| Production Scheduler | `double-monitor-daily` |
| Schedule | `50 16 * * 1-5` |
| Script | `cron/double_monitor.py` |
| Working Directory | `/home/caojy/.hermes/scripts/cron` |
| Python | venv python（cron 自动） |
| Output | `reports/` |
| Cron Output | `/home/caojy/.hermes/cron/output/<job_id>/` |

上下游时序：
- `stock-market-cache-refresh` 16:30
- `stock-daily-data-refresh` 16:40
- `double-monitor-daily` 16:50

## 2. Daily Decision Report（PRIMARY）

- 生成器：`decision/daily_decision_contract.py`
- 保存入口：`save_daily_report(report)`
- 输出：
  - `reports/daily_decision_<date>.json`
  - `reports/daily_decision_<date>.txt`
- 接入点：`double_monitor.py` 末尾调用 `save_daily_report({})`
- 语义：只读取已有 Decision Snapshot / Real Portfolio / Market Context，不重新决策。

## 3. Production Observation Report（SECONDARY）

- 生成器：`decision/observation.py`
- 保存入口：`save_daily_observation_report()`
- 输出：
  - `reports/production_observation_<date>.json`
  - `reports/production_observation_<date>.txt`
- 接入点：`double_monitor.py` 末尾调用 `save_daily_observation_report()`
- 语义：只统计 Decision / Execution / Position / Outcome 事实，不做策略评价。

## 4. Primary / Secondary / DETAIL 关系

- `PRIMARY`：Daily Decision Report → 今天该做什么
- `SECONDARY`：Production Observation Report → 记录有没有断
- `DETAIL`：Decision Snapshot / Replay / Evidence Review → 为什么

Secondary / Detail 不重新生成 Decision。

## 5. Real Account Readiness

- 模式：`MANUAL_CONFIRMATION`
- 未确认状态：`ACCOUNT_READINESS = BLOCKED / MISSING`
- 影响：`BUY / ADD` 被阻止；`SELL / REDUCE` 仍允许。

## 6. Observation Start

- `2026-08-20`
- 更早数据：`PRE_OBSERVATION / LEGACY`

## 7. 自动交易

- 关闭
- 无券商 API 调用
- `PLANNED != EXECUTED`

## 8. 当前状态

| 项目 | 状态 |
|:---|:---|
| Production Outcome | 0 |
| Daily Decision Report | READY |
| Production Observation Report | READY |
| 非交易日报告生成 | READY |
| 零 BUY 日报告生成 | READY |
| 自动交易 | 关闭 |
| 观察窗口 | 2026-08-20 |

---

*文档版本：Phase 8-E.1 · Production Report Wiring Closure*
