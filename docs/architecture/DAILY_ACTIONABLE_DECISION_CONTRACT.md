# DAILY_ACTIONABLE_DECISION_CONTRACT.md（Phase 7.6）

## 1. Purpose

把当前已经存在的 Decision / Regime / Permission / Portfolio / Real Sizing / Position / Exit 能力，统一收敛成一个最终的、用户可直接执行的 Daily Decision Output。

用户每天不需要阅读多个脚本，不需要自己拼接候选、信号、仓位、风控和持仓状态；系统直接给出最终答案。

## 2. User Question

- 买什么
- 什么时候买
- 买多少
- 什么时候卖

## 3. Daily Decision Contract

统一输出对象：`DailyDecisionReport`

### 3.1 Market Context
- as_of_time
- market_regime
- regime_score
- regime_version
- position_scale

### 3.2 Trading Permission
- new_entry
- add_position
- reduce
- exit
- permission_reason_codes

### 3.3 BUY（每个 BUY）
- symbol
- strategy
- candidate_score
- candidate_rank
- entry_signals
- planned_entry_time
- planned_entry_price
- target_position_pct
- target_value
- target_quantity
- risk
- reason_codes
- decision_id

### 3.4 NO_TRADE（每个未通过的候选）
- symbol
- candidate_score
- blocked_at
- blocking_layer
- reason_codes

### 3.5 REAL POSITION（每个真实持仓）
- symbol
- current_qty
- current_value
- current_position_pct
- action
- target_position_pct
- target_value
- target_quantity
- delta_value
- delta_quantity
- exit_reason
- decision_id

支持：
- HOLD
- ADD
- REDUCE
- SELL

### 3.6 DATA HEALTH
- VALID
- STALE
- PARTIAL
- MISSING
- DATA_GAP

至少包括：
- Regime
- Permission
- Portfolio
- Real Asset Snapshot
- Candidate
- Price

## 4. Action 语义

Daily Decision Output 中 Action 只能使用：
- BUY
- ADD
- HOLD
- REDUCE
- SELL
- NO_TRADE

不再出现：
- “建议关注”
- “可以考虑”
- “信号较强”
- “值得观察”

如果系统只是提供研究信息：
必须标记：
RESEARCH_ONLY

## 5. Candidate vs Final Decision

Candidate ≠ BUY

Candidate 只是进入候选池。

Final BUY 必须满足：
Candidate + Entry + Permission + Portfolio + Risk + Target Position + DecisionEngine

否则：
NO_TRADE

## 6. Entry Contract

最终 BUY 必须能够回答：
- decision_time
- signal_time
- planned_entry_time
- planned_entry_price
- actual_execution_price
- execution_status

当前 V1：
planned_entry_time = T+1 Open
planned_entry_price = 次日开盘价（参考收盘价）

## 7. Real Position Sizing

如果 total_asset = READY：
- 总资产
- 当前持仓
- 当前仓位 %
- 目标仓位 %
- 目标金额
- 目标数量
- Delta 金额
- Delta 数量

如果无法计算：
明确：
TARGET_VALUE = UNKNOWN
TARGET_QUANTITY = UNKNOWN
ACTION = BLOCKED / HOLD

## 8. Real Portfolio Freshness

如果 Real Portfolio Snapshot = STALE / EXPIRED：
- 新 BUY / ADD：BLOCKED
- SELL / REDUCE：不得因为账户快照过旧而被错误阻止

## 9. Market Regime 输出

必须显示：
- Market Regime label
- Trading Permission
- Position Scale

并明确 Regime 当前到底影响了什么：
- Position Sizing
- New Entry Permission
- Entry

不暗示控制了 Strategy Selector（当前未启用）。

## 10. Daily Decision 优先级

1. Market Regime
2. Trading Permission
3. Final Action（BUY / HOLD / REDUCE / SELL / ADD / NO_TRADE）
4. Reason Codes / Explanation

## 11. Decision Summary

至少生成：
### 今日结论
- Market
- Permission
- New BUY
- ADD
- HOLD
- REDUCE
- SELL

### 今日 BUY
如果没有：
BUY = NONE

### 今日 SELL / REDUCE
逐票列出。

### 今日 HOLD
逐票列出。

## 12. 为什么不买

对于 NO_TRADE：
必须明确否决层：
- Permission
- Portfolio
- Candidate
- Entry
- Risk

不能只输出“未通过”。

## 13. 为什么卖

对于 SELL / REDUCE：
必须明确：
- Stop Loss
- Take Profit
- Trailing Stop
- MA20
- Portfolio Risk
- Manual
- Forced

不能只输出：
SELL

## 14. Decision ID

所有最终 Action 必须带：
decision_id

用户看到一个动作，就能够反查：
Decision → Snapshot → Execution → Outcome

## 15. Report 不做第二次决策

Daily Report 只展示 DecisionEngine 已经做出的 Decision。

禁止：
Report 层重新计算：
- BUY / SELL
- Position size
- Permission
- Regime

正确：
DecisionEngine → DailyDecisionReport

## 16. Daily Decision Replay Preview

用户看到 decision_id 之后，可以查：
replay(decision_id)

输出：
- 当时 Regime
- Permission
- Candidate
- Entry
- Portfolio
- Risk
- Final Action
- Explanation
- Versions

## 17. Decision Completeness

每个 Production Final Decision 必须计算：
DECISION_COMPLETE

至少要求：
- action
- symbol（NO_TRADE 可以无 symbol，但必须有 context）
- timestamp
- reason_codes
- regime
- permission
- portfolio context
- strategy
- decision_id

对于 BUY 额外：
- planned_entry
- target_position
- target_value
- target_quantity

如果缺失：
DECISION_PARTIAL

## 18. Primary Output

PRIMARY_DECISION_OUTPUT：
`reports/daily_decision_<date>.json`
`reports/daily_decision_<date>.txt`

Secondary：
`double_monitor.py` stdout（ DETAIL / DEBUG ）

## 19. Known Limitations

- Historical ST = BLOCKED
- Historical Market Cap = PARTIAL
- Historical Portfolio = NONE
- Real cash/total_asset 可能只能通过 MANUAL_CONFIRMATION 获得
- 真实仓 Position Sizing 在 total_asset 未知时 = PARTIAL/BLOCKED

## 20. File Locations

- `decision/daily_decision_contract.py` — 只读聚合层
- `decision/snapshots/` — 每日 Decision Snapshot
- `reports/daily_decision_<date>.json` — 结构化日报
- `reports/daily_decision_<date>.txt` — 可读日报
