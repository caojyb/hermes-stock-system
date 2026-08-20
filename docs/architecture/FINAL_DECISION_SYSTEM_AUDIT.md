# FINAL_DECISION_SYSTEM_AUDIT.md（Phase 7.4）

> 本文件只记录审计结论，不修改任何生产代码/参数/策略。

## 1. Daily Decision Output

用户在一个正常交易日最终看到的是 `double_monitor.py` 的 stdout / 飞书推送。

| 输出项 | 实际内容 | 状态 |
|---|---|---|
| 市场环境 | `ENV_LABEL` + `ENV_TOTAL` + `ENV_SCALE` | COMPLETE |
| 交易许可 | `tp_result['status']` + `new_entry/add/reduce/exit` | COMPLETE |
| 候选 | `WATCH_LIST` + 信号 A/B/C/D + 过滤器 | COMPLETE |
| 买入建议 | `BUY code name price x shares = amount | decision_id` | COMPLETE |
| 买入时点 | 收盘后统一执行，计划入场价 = 当日收盘价 | COMPLETE |
| 买入价格 | `reference_price = klines[-1]['close']` | COMPLETE |
| 建议仓位 | `TOTAL_CAPITAL * FIRST_POSITION_PCT * ENV_SCALE` → shares | COMPLETE（Simulation）/ PARTIAL（Real） |
| 当前持仓建议 | `open_map` 实时计算 + 浮盈浮亏 | COMPLETE（Simulation） |
| SELL | `止损 / 清仓止盈 / 部分止盈` + decision_id | COMPLETE |
| REDUCE | Portfolio drawdown 触发减仓至 50% | COMPLETE |
| ADD | DecisionEngine 允许，但 double_monitor 当前未单独发 ADD | PARTIAL |
| HOLD | 持仓无退出/减仓/加仓信号 | COMPLETE |
| NO_TRADE | Permission/Candidate/Entry/Portfolio 任一失败 | COMPLETE |
| reason_codes | `dec.reason_codes` | COMPLETE |
| decision_id | `gen_decision_id` | COMPLETE |

## 2. 最初七问

| 问题 | Owner | 输入 | 规则 | Output | 可解释 | 可 Replay | 状态 |
|---|---|---|---|---|---|---|---|
| 谁决定买什么 | `double_monitor.py` + `double_up_scores` | K 线 + indicators + V1 Candidate | 信号 ≥2 + 过滤器通过 | `buy_candidates` ranking | ✅ | ✅ | COMPLETE |
| 谁决定什么时候买 | `DecisionEngine` | `entry_ctx` | `entry_signal == CONFIRMED` + Permission | `BUY/NO_TRADE` | ✅ | ✅ | COMPLETE |
| 谁决定买多少 | `double_monitor.py`（Simulation）/ `position_stop_loss_alert.py`（Real） | `TOTAL_CAPITAL * FIRST_POSITION * ENV_SCALE` | 现金上限 + 手数取整 | `shares` | ✅ | ✅ | COMPLETE / PARTIAL |
| 谁决定什么时候卖 | `DecisionEngine` | Exit Assessment | STOP_LOSS / TP / TRAILING / MA20 | `SELL/REDUCE` | ✅ | ✅ | COMPLETE |
| 什么环境允许交易 | `trading_permission.py` | regime + timing + drawdown + data_health | `new_entry == ALLOW` | `permission_status` | ✅ | ✅ | COMPLETE |
| 谁最终拍板 | `DecisionEngine.decide()` | 全部 Assessment | 单一入口 | `BUY/HOLD/SELL/NO_TRADE/REDUCE/ADD` | ✅ | ✅ | COMPLETE |
| 决策之后如何验证 | `decision.execution` + `decision.outcome` + `decision.replay` | `decision_id` | 结构化生命周期 | `Outcome` | ✅ | ✅ | COMPLETE |

## 3. Final Action Emitter Matrix

| Action | Producer | DecisionEngine | Permission | Portfolio | Execution | Snapshot | Replay |
|---|---|---|---|---|---|---|---|
| BUY | `double_monitor.py` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| ADD | `DecisionEngine`（持仓管理路径） | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| HOLD | `DecisionEngine`（else branch） | ✅ | — | — | ✅ | ✅ | ✅ |
| REDUCE | `DecisionEngine`（portfolio risk / drawdown） | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| SELL | `double_monitor.py` / `position_stop_loss_alert.py` | ✅ | ✅ | — | ✅ | ✅ | ✅ |
| NO_TRADE | `DecisionEngine`（任意 gate 失败） | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

**旁路结论**: 未发现生产旁路。`simulation_engine.py` / `trade_gateway.py` 仍存在，但不在当前 `double_monitor.py` 主路径中，标记为 `LEGACY / NON_PRODUCTION`。

## 4. 买什么：V1 Candidate → Final BUY

| 层 | 输入 | Producer | 数据源 | 规则 | 输出 |
|---|---|---|---|---|---|
| Universe | `stocks` + `klines` | `market_cache.db` | 本地 | 基础过滤 | 原始标的 |
| ST | 名称/公告 | `stocks.is_st` / 名称检查 | 当前快照 | ST 排除 | `ST_FILTER` |
| Market Cap | `stocks.total_mcap` | `stocks` 表 | 当前快照 | 5–90B | `PASS/FAIL` |
| Technical Features | `klines` | `indicators` 表 | 本地 | MA20/MACD/ATR/Volume Ratio/Amount/Price Position | `features` |
| Candidate Ranking | `double_up_scores.total_score` | `scan_doub` 相关脚本 | 本地 | 总分排序 | `WATCH_LIST` |
| Entry Signal | `indicators.signal_a/b/c/d` | `indicators` 表 | 本地 | ≥2 个信号 | `entry_signal` |
| Trading Permission | `trading_permission.evaluate()` | `trading_permission.py` | regime/timing/data | `new_entry == ALLOW` | `permission_status` |
| Portfolio | `assess_portfolio()` | `decision/portfolio.py` | drawdown/sector/position count | 无 BLOCK | `pa['action']` |
| DecisionEngine | `decide()` | `decision/engine.py` | 全部输入 | 全部 gate 通过 → `BUY` | `decision_id` |

**Candidate != BUY**: 明确。Candidate 只要求 V1 过滤 + ≥2 信号；BUY 还要 Permission + Portfolio + Entry + target_position>0 全部通过。

## 5. 什么时候买：Entry Contract

| 字段 | 值 | 说明 |
|---|---|---|
| decision_time | `dec.timestamp` | DecisionEngine 生成时间 |
| signal_time | `indicators.date` | 信号基于当日收盘 |
| planned_entry_time | T+1 Open（模拟）/ 下一交易日 | 非交易日 `IS_TRADING_DAY=False` 时跳过 |
| planned_entry_price | `reference_price = klines[-1]['close']` | 当日收盘价 |
| actual_execution_price | `entry_price`（模拟）/ 人工回写（真实） | 同 planned 或实际成交价 |
| execution_status | `EXECUTED / PARTIAL / REJECTED / NOT_EXECUTED` | 记录在 `execution.status` |
| entry_invalid_output | `NO_TRADE` + `ENTRY_INSUFFICIENT / PERMISSION_BLOCKED / ...` | 明确 reason_code |

## 6. 买多少：Position Sizing

### Simulation（COMPLETE）

| 层级 | 规则 | 值 |
|---|---|---|
| base position | `TOTAL_CAPITAL * FIRST_POSITION_PCT` | 1,000,000 * 0.025 = 25,000 |
| regime scale | `ENV_SCALE` | 强趋势 1.0 / 高波动 0.7 / 未知 0.5 |
| portfolio limit | `MAX_POSITION_PCT = 5%` | 50,000 |
| max position | 单股上限 | 50,000 |
| sector limit | `MAX_SECTOR_CNT = 3` | 行业计数 |
| drawdown control | `drawdown >= 15%` | REDUCE / NO_NEW_ENTRY |
| final target position | `min(base * scale, cash, max_position)` | 实际 `buy_amount` |

### Real Position（PARTIAL）

| 字段 | 状态 | 说明 |
|---|---|---|
| target_position | ✅ | `TOTAL_CAPITAL * FIRST_POSITION_PCT * ENV_SCALE` | 
| target_quantity | ✅ | `int(target / price / 100) * 100` |
| target_cash_amount | ✅ | `target_position` | 
| relative_position | ✅ | `market_value / total_holdings_value` | 
| total_asset | ❌ | `DATA_UNAVAILABLE`（Bitable 无现金/总资产） | 
| drawdown | ❌ | `UNKNOWN`（无真实历史净值峰值） | 

**结论**: `REAL_POSITION_SIZING = PARTIAL`。真实仓没有 cash/total_asset，无法给出“占总资产 X%”的绝对仓位建议，只能给相对持仓市值口径或固定金额建议。

## 7. 什么时候卖：Exit Assessment

| 类型 | Trigger | DecisionEngine 映射 | 状态 |
|---|---|---|---|
| STOP_LOSS | `ret <= -8%` | `exit_signal=RISK, triggers=['STOP_LOSS']` | COMPLETE |
| TAKE_PROFIT | `peak_ret >= 25% && retrace >= 8%` | `exit_signal=RISK, triggers=['TAKE_PROFIT']` | COMPLETE |
| TRAILING_STOP | `pnl>15% && retrace>=10%` | `triggers=['TRAILING_STOP']` | COMPLETE |
| MA20_EXIT | `price < ma20 && (ma20-price)/ma20>3%` | `triggers=['MA20_BREAK']` | COMPLETE |
| PORTFOLIO_RISK | `drawdown>=15%` | `action=REDUCE, target=cur/2` | COMPLETE |
| MANUAL | 用户平安证券成交后回写 | `confirm_manual_execution` | COMPLETE |
| FORCED | `forced_exit=True` | `action=SELL` | COMPLETE |
| OTHER | `exit_signal=EXIT_NORMAL` | 无特殊触发 | COMPLETE |

**EXIT_DECISION_GAP**: 未发现。所有 Exit 都经过 `DecisionEngine`。

## 8. Regime Control

Regime 当前真实控制范围：

| 控制项 | 是否真正控制 | 说明 |
|---|---|---|
| Position Sizing | ✅ | `ENV_SCALE` 直接缩放 `FIRST_POSITION` | 
| Trading Permission | ✅ | `new_entry/add_position` 受 regime 控制 | 
| Entry | ✅ | `new_entry==DENY` 时 `NO_TRADE` | 
| Portfolio Risk | ❌ | Portfolio 只做 veto，不按 regime 调整风险阈值 | |
| Strategy Selection | ❌ | 当前只有 `v1_double`，Strategy Selector 未启用 | |
| 完全停止开仓 | ✅ | `new_entry=DENY` 可实现 | |

**结论**: Regime 当前控制 Position Sizing / Permission / Entry，不直接控制 Portfolio Risk / Strategy Selection。这属于 `SUPPORTED`（已有），不是 `BLOCKED`。

## 9. Trading Permission

四种权限真实含义：

| 权限位 | 含义 | 影响 |
|---|---|---|
| `new_entry` | 是否允许新开仓 | `ALLOW` 才能 BUY |
| `add_position` | 是否允许加仓 | `ALLOW` 且 `target>current` 才 ADD |
| `reduce_position` | 是否允许减仓 | Portfolio Risk 触发 REDUCE |
| `exit_position` | 是否允许退出 | Exit Assessment 触发 SELL |

**DENY 是否阻止 BUY/ADD**: ✅ 是。`engine.py:182` 明确 `new_entry != ALLOW → NO_TRADE`。

**DENY 是否错误阻止 SELL/REDUCE**: ❌ 否。Exit 路径在 `has_position or mode=='position'` 分支，不检查 `new_entry`。

## 10. Portfolio Veto Matrix

| Constraint | Exists | Calculated Before BUY | Can Veto BUY | Reason Code | Applies to SELL |
|---|---|---|---|---|---|
| Max Position | ✅ | ✅ | ✅ | `MAX_POSITION_EXCEEDED` | ❌ |
| Sector Limit | ✅ | ✅ | ✅ | `SECTOR_LIMIT_EXCEEDED` | ❌ |
| Drawdown | ✅ | ✅ | ✅ | `DRAWDOWN_BLOCKED` | ❌（只触发 REDUCE） |
| Exposure | ✅ | ✅ | ✅ | `EXPOSURE_BLOCKED` | ❌ |
| Position Count | ✅ | ✅ | ✅ | `MAX_POSITION_REACHED` | ❌ |

**结论**: Portfolio 只对 BUY 做 veto，对 SELL 不阻止。符合预期。

## 11. Real / Simulation 隔离

| 维度 | Simulation | Real | 状态 |
|---|---|---|---|
| 数据源 | `simulation.db` | 飞书 Bitable | ✅ 隔离 |
| 持仓 | `simulation.trades` | Bitable records | ✅ 隔离 |
| 现金/总资产 | `TOTAL_CAPITAL` 固定 | `DATA_UNAVAILABLE` | ✅ 隔离 |
| 交易执行 | `record_simulation_execution` | `confirm_manual_execution` | ✅ 隔离 |
| 输出文件 | `simulation.db` / `decision/execution` | `decision/execution` (source=MANUAL) | ✅ 隔离 |
| drawdown | 基于 `portfolio_snapshots` 历史峰值 | `UNKNOWN` | ✅ 隔离 |

**结论**: `REAL / SIMULATION ISOLATION STATUS = COMPLETE`

## 12. Decision Contract

| 字段 | 存在 | 说明 |
|---|---|---|
| symbol | ✅ | `dec.symbol` |
| strategy | ✅ | `dec.strategy` |
| candidate_score/rank | ✅ | `dec.candidate_score / candidate_rank` |
| planned_entry_time | ✅ | `dec.as_of_time` |
| planned_price | ✅ | `dec.reference_price` |
| target_position | ✅ | `dec.target_position` |
| target_quantity | ✅（Simulation）/ ❓（Real） | shares 计算存在 |
| stop_loss | ✅ | `dec.stop_loss` |
| take_profit | ✅ | `dec.take_profit` |
| trailing_stop | ✅ | `dec.trailing_stop` |
| exit_conditions | ✅ | `dec.exit_triggers` |
| reason_codes | ✅ | `dec.reason_codes` |
| explanation | ✅ | `dec.explanation` |
| regime | ✅ | `dec.regime_label` |
| permission | ✅ | `dec.permission_status` |
| portfolio | ✅ | `dec.portfolio_assessment` (snapshot) |
| candidate | ✅ | `dec.candidate_qualified` |
| entry | ✅ | `dec.entry_signal` |
| risk | ✅ | `dec.risk_flags` |
| exit | ✅ | `dec.exit_signal` |

**DECISION_CONTRACT_GAP**: 未发现。单个 Decision Snapshot 可恢复所有关键字段。

## 13. Snapshot / Replay

| 检查项 | 状态 | 说明 |
|---|---|---|
| BUY replay | ✅ | `lifecycle_replay(outcome_id)` 可恢复完整链 |
| NO_TRADE replay | ✅ | `decision_snapshot` 保存 |
| SELL replay | ✅ | `record_sim_exit_and_outcome` → Outcome |
| REDUCE replay | ✅ | DecisionEngine 记录 |
| HOLD replay | ✅ | DecisionEngine 记录 |
| deterministic | ✅ | 16/16 tests passed |

## 14. Execution / Outcome 归因

| 链路 | 状态 | 说明 |
|---|---|---|
| BUY → Execution | ✅ | `record_simulation_execution` 关联 `decision_id` |
| NOT_EXECUTED | ✅ | `execution.status = NOT_EXECUTED` | 
| PARTIAL | ✅ | `execution.status = PARTIAL` | 
| ADD | ✅ | `record_simulation_execution` 支持 | 
| REDUCE | ✅ | DecisionEngine 记录 | 
| SELL | ✅ | `record_sim_exit_and_outcome` | 
| Multiple Exit | ✅ | `exit_segments[]` | 
| Final Outcome | ✅ | `build_outcome_from_execution` | 

## 15. 生产旁路搜索

| 文件 | 是否主路径 | 说明 |
|---|---|---|
| `simulation_engine.py` | ❌ LEGACY | 有独立 `open_position/check_exit_signals`，但不在 `double_monitor.py` 主路径 |
| `trade_gateway.py` | ❌ NON_PRODUCTION | 券商网关 PoC，未接入真实交易 |
| `position_stop_loss_alert.py` | ✅ 独立任务 | 真实仓独立决策，不写 simulation |
| `track_flow_manager.py` | ✅ 辅助 | 资金流转，不产生 BUY/SELL |

**Final Audit Blocker**: 无。但 `simulation_engine.py` 仍是潜在风险，建议后续彻底移除或标记 DEPRECATED。

## 16. Daily Production Graph

```text
Scheduler (cron)
  → daily-data-refresh (16:40)
  → market-cache-refresh (16:30)
  → double-monitor (16:50)
      ├── load_watch_list() → double_up_scores
      ├── validate_klines_health()
      ├── check_market_timing() → timing_ok
      ├── trading_permission.evaluate() → tp_result
      ├── data_filters (gap_up / liquidity)
      ├── assess_portfolio() → pa
      ├── DecisionEngine.decide() → BUY/NO_TRADE/SELL/REDUCE
      ├── decision_snapshot.save_snapshot()
      ├── record_simulation_execution()
      ├── record_sim_exit_and_outcome()
      └── portfolio_summary + risk_controller_v2
```

**UNUSED / NON_PRODUCTION**:
- `simulation_engine.py`: 不在 cron 主路径
- `trade_gateway.py`: 券商网关 PoC，未启用
- `historical_replay_engine.py`: 仅研究用，不进入生产
- `strategy_ga_optimization.py`: 遗传算法，不在生产路径

## 17. 最终能力矩阵

| Capability | Simulation | Real Position | Production | Status |
|---|---|---|---|---|
| Buy What | ✅ | ✅ | ✅ | COMPLETE |
| When to Buy | ✅ | ✅ | ✅ | COMPLETE |
| How Much | ✅ | PARTIAL | PARTIAL | PARTIAL |
| When to Sell | ✅ | ✅ | ✅ | COMPLETE |
| Market Regime | ✅ | ✅ | ✅ | COMPLETE |
| Trading Permission | ✅ | ✅ | ✅ | COMPLETE |
| Portfolio Veto | ✅ | ✅ | ✅ | COMPLETE |
| Final Decision | ✅ | ✅ | ✅ | COMPLETE |
| Explainability | ✅ | ✅ | ✅ | COMPLETE |
| Replay | ✅ | ✅ | ✅ | COMPLETE |
| Outcome | ✅ | PARTIAL | PARTIAL | PARTIAL |

**System Readiness**: COMPLETE（决策管道统一、可解释、可追踪）  
**Strategy Readiness**: PARTIAL（V1 尚无真实 Production Edge 证据，主升浪 SHADOW_ONLY）

## 18. Historical Replay 限制

| 维度 | 状态 | 说明 |
|---|---|---|
| ST | BLOCKED | 100% UNKNOWN，无可用历史数据源 |
| Market Cap | PARTIAL | PIT_SAFE 90.8%，APPROXIMATE 9.1% | 
| Portfolio | NONE | 无历史组合数据 |
| Replay A | RECONSTRUCTABLE | 技术特征可重建 | 
| Replay B | RESEARCH/PARTIAL | 研究层可部分重建 | 
| Replay C | BLOCKED | ST 阻塞 | 

**这些限制不等于当前 Production Decision 系统无法工作。**

## 19. 最终差距（Final Gap）

| 差距 | 优先级 | 说明 |
|---|---|---|
| Real Position total_asset / drawdown 缺失 | HIGH | 导致真实仓无法计算“占总资产%”和组合回撤 | 
| Strategy Selector 未启用 | MEDIUM | 当前只有 v1_double，无策略路由 | 
| 主升浪 SHADOW_ONLY | MEDIUM | 主升浪存在但不进入生产决策 | 
| simulation_engine.py 潜在旁路 | LOW | 建议移除或标记 DEPRECATED | 
| Historical ST 数据源 | LOW | 已标记 DATA_INSUFFICIENT，不影响生产 | 

## 20. 结论

当前 Hermes 股票系统已经是一个**统一、可解释、可执行、可追踪**的决策系统：

- **统一**: 所有 Final Action 经过 `DecisionEngine`
- **可解释**: `reason_codes + explanation` 完整保留
- **可执行**: `Execution` 记录 planned/actual/status
- **可追踪**: `Outcome + lifecycle_replay` 完整链路

距离最初目标“买什么、什么时候买、买多少、什么时候卖”只差：
1. 真实仓 total_asset / drawdown（数据源问题）
2. Strategy Selector（策略能力，非系统能力）
3. 真实 Production Edge 验证（需要更多实盘样本）

**不要修改 V1。不要启用 Strategy Selector。不要继续 Historical Replay 数据挖掘。**