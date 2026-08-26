# J0A — Production Integrity Delta Audit（8h2 → 923a695）

> 审计日期：2026-08-26。只审计，不修复。
> 原任务书基线 hermes-stock-phase-8i0 / commit 4350522 **不存在于本仓库**，
> 经用户确认正式接受：BASELINE_TAG = hermes-stock-phase-8h2 (876cee8)，CURRENT_HEAD = 923a695。

## 1. 真实 Git Baseline

| 项 | 值 |
|---|---|
| BASELINE_TAG | hermes-stock-phase-8h2 → 876cee8 |
| CURRENT_HEAD | 923a695 (master, origin/master) |
| Working tree | M heartbeat_state.json；?? hot_sector_2026-08-26.md（均为 runtime artifact） |
| Full decision suite | **320 passed / 0 failed** (~180s) |

## 2. Runtime Artifact Status

| 文件 | tracked | gitignore 规则 | 判定 |
|---|---|---|---|
| heartbeat_state.json | YES（且被 0179a2b 提交过） | 无 | RUNTIME_ONLY=TRUE，心跳自动写状态。建议加入 .gitignore 并 git rm --cached（待批准） |
| hot_sector_2026-08-26.md | NO | 无 | 每日板块扫描输出文件，RUNTIME_ONLY=TRUE。建议 `hot_sector_*.md` 入 .gitignore（待批准） |

本阶段未修改 .gitignore。

## 3. Commit Timeline (8h2..HEAD, 共5个)

| Commit | Message | Files | 关联审计项 | 生产影响 |
|---|---|---|---|---|
| 273c8df | health_check port 18080→9177; heartbeat websocket-aware | health_check_system.sh, heartbeat.py | 非J0 | 监控修正 |
| e11cc18 | health check bugfix v2 | heartbeat.py 等 | 非J0 | 监控修正 |
| 0179a2b | chore: heartbeat state update | heartbeat_state.json | 非J0 | runtime state |
| **763c181** | trades linkage + cash formula + sim_trades SQL | double_monitor.py, decision/daily_decision_contract.py | **J0-B 核心 + 部分 J0-C trace** | cash 公式修复、trades 写 decision_id/exit_reason |
| c5d1624 | ensure decision snapshots exist for daily report linkage | decision/* | J0-C/D 链路 | snapshot-daily 报告关联 |
| **9d7a57f** | branch tracing + risk controller decision freeze | double_monitor.py, risk_controller_v2.py | J0-C/F 相关 | [BRANCH] 追踪 + risk 决策冻结 |
| **923a695** | risk controller writes decision_id/exit_reason on trim | risk_controller_v2.py | J0-C trace fix | 减仓 UPDATE 带 decision_id/exit_reason |

（注：763c181 diff 显示 cash 公式在 8h2 后被改了两次——先到中间态再到最终态，最终态见 §5。）

## 4. J0-A：SIM/PROD DB Isolation

DB_ISOLATION_STATUS = **PARTIAL**（接近完成）

14 个脚本现状（全部已接 simulation_db_helper.get_active_sim_db() 或 stock_db_paths）：

| script | db 解析 | runtime_reachability | remaining_issue |
|---|---|---|---|
| simulation_weekly | SIM_DB helper | cron 辅助 | 无 |
| track_flow_manager | SIM_DB helper | **PRODUCTION（double_monitor 调用）** | 无 |
| data_upgrade | SIM_DB helper | production 辅助 | 无 |
| north_flow_monitor | SIM_DB helper | production 辅助 | 无 |
| l5_2_consecutive_stop_loss | SIM_DB helper | MANUAL_ONLY | 无 |
| simulated_execution | SIM_DB helper | LEGACY/手动 | 注释仍写 "simulation.db"，无实际影响 |
| track_diagnosis | SIM_DB helper | MANUAL_ONLY | 无 |
| portfolio_summary | SIM_DB helper + stock_db_paths | 手动/cron 辅助 | 无 |
| full_diagnosis | SIM_DB helper | MANUAL_ONLY | 无 |
| long_term_holding | SIM_DB helper | MANUAL_ONLY | 无 |
| double_refresh | stock_db_paths + SIM_DB helper | cron 已停用 | 无 |
| system_health_check | SIM_DB helper | cron（周日18:00） | 文案硬编码 "simulation.db" 字样，仅显示 |
| l5_3_full_position_drawdown | SIM_DB helper | MANUAL_ONLY | 无 |
| simulation_engine | SIM_DB helper + stock_db_paths | LEGACY（不在 cron） | 无 |

**残留问题（1个真实风险点）**：
- `stock_opportunity_scan.py:152` fallback 分支：get_active_sim_db() import 失败时回退到
  `skills/stock/stock-expert/simulation.db`（另一份 DB！）。该脚本是生产 cron
  （stock-opportunity-push，盘中每30分钟）。import 失败概率低但存在 →
  属 IMPLEMENTATION_REQUIRED（J0-A 缺口）。

SIM_MODE=test vs production 解析验证（实测）：
- SIM_MODE=test → simulation_test.db ✅
- 默认/production → simulation.db ✅
- double_monitor 自带 ACTIVE_SIM_DB 同语义切换 ✅

## 5. J0-B：Simulation Valuation

J0_B_STATUS = **ALREADY_FIXED**（763c181），但语义审计发现 1 个口径缺口。

当前公式（double_monitor.py:1023-1026）：
```
realized_pnl = SUM(sell_amount - buy_amount) WHERE sell_date IS NOT NULL
open_cost    = Σ buy_shares × buy_price WHERE status IN ('持有','部分止盈')
cash         = TOTAL_CAPITAL + realized_pnl − open_cost
total_asset  = cash + holdings_value（现价×股数实时结算）
```

数学验证：cash + holdings_value = TOTAL_CAPITAL + realized_pnl + unrealized_pnl ✅
（holdings_value = open_cost + unrealized_pnl）。恒等式成立，旧公式
`TOTAL_CAPITAL - all_bought + all_sold` 的重复扣减已消除。

- realized/unrealized 分离：✅（realized_pnl SQL 独立；浮盈分布 win/loss 计数）
- drawdown：按历史峰值真实计算 ✅（快照 DELETE+INSERT 幂等）
- restart recovery：无持久 cash 余额表，cash 每次由流水推导——确定性可重算，restart 安全 ✅
- fees/slippage：**不存在**（模拟语义一直不含费用，属既有约定非 bug）
- partial sell / multiple lifecycle：UPDATE 单行按 status 处理，sell_amount 全额记录；
  "部分止盈"状态下 open_cost 仍按全部剩余股数×买价计——与"部分止盈"行保留原 buy_shares 的存储方式自洽

**缺口**：realized_pnl 用 `sell_amount - buy_amount`，依赖 sell_amount 正确写入。
历史数据中曾有 sell_amount=0 的造假行（2026-08-17 已修复重算）。若未来再出现
sell_amount 缺失，cash 会被高估。建议后续加 sanity guard（IMPLEMENTATION_OPTIONAL，非本阶段必改）。

**-34% 是否被污染**：旧公式在"持仓成本 > 已实现卖出回款"时会系统性低估 cash。
7/29 批次止损后 realized_pnl 为大负数，新旧公式在该情形下数值差异 =
`(all_bought - all_sold) - (open_cost - realized_pnl)` = 已清仓部分的买入额 − 其亏损额 > 0，
即**旧公式低估净值，-34% 中含 valuation bug 成分**。量化需重放历史流水，
标记为 PRE_FIX_LEGACY_RESULT（不覆盖），POST_FIX 重算留待 J0 实现/验证阶段。

## 6. J0-C：Stop Loss Unified Decision Chain

STOP_LOSS_CHAIN_STATUS = **COMPLETE（authority 层）/ TRACE 层近期补齐**

证据：
- position_stop_loss_alert.py:168 起：构建 DecisionEngine('v1_double')，Exit Assessment 归一 HOLD/REDUCE/SELL/ADD；dec.decision_id 存在
- :241/:283 save_snapshot(dec) → decision/snapshots/
- daily_decision_contract.load_today_snapshots() glob snapshots/*.json → classify_actions 进入 Daily Report ✅（链路已通）
- record_sim_exit_and_outcome 接 Outcome 闭环
- 9d7a57f/923a695 是 TRACE FIX（risk trim 补 decision_id/exit_reason），不是 authority fix；
  authority fix 早在 Phase 5/5.5 完成
- 无第二 Final Decision Owner（stop-loss 不自行拍板 SELL，只出 Assessment）

残余小项：Urgent Surface 表现层对 stop_loss decision 的 presentation 标记未见显式
URGENT 分类（Daily 可见性已满足）。列 IMPLEMENTATION_REQUIRED(low) 待确认语义。

## 7. J0-D：Quality Report

J0_D_STATUS = **PARTIAL**

- real_portfolio_truth.build_real_snapshot 内调 check_portfolio_quality → quality_report 存入快照 + real_asset_snapshots.quality_report_json ✅
- daily_decision_contract.build_real_portfolio_section:191 输出 quality_report 进 Daily Report JSON ✅
- 三级语义存在：OK/WARNING/ERROR（real_portfolio_quality.py:53-57），avg_cost/current_price/quantity 各有 MISSING(W)/NON_POSITIVE(E) 规则 ✅
- ERROR→VALID 静默升级：未发现 ✅
- **缺口**：quality overall 未接入 BUY/ADD fail-safe gate（Account readiness 只看 holdings_status，
  不看 quality ERROR）；Dashboard/Observation 是否展示 quality warning/error 未验证。
  → IMPLEMENTATION_REQUIRED（fail-safe wiring + dashboard visibility）

## 8. J0-E：Trade Summary buys/sells

FIXED_STATUS = **OPEN（低危）**

double_monitor.py:1089-1092 按 buy_date=? / sell_date=? 分别查询后独立打印。
同一 symbol 当日既买又卖会同时出现在两个列表——但此处是 Summary-only 打印，
不影响 Decision/Portfolio/统计落库。按互斥集合假设处理确实存在，建议引入
MULTI_ACTION 标注。属显示分类问题。

## 9. J0-F：Risk Summary Refresh

FIXED_STATUS = **PARTIAL**

- 风控减仓后 **cash 已刷新**（RC-REFRESH 段，1121 行重算）✅
- **但摘要的 open_pos / win_cnt / loss_cnt / len(open_pos) 仍是风控前读取的列表**
  （1024 行读一次，风控后未重读；"当前持仓 N 只"打印用旧 len(open_pos)）。
  快照 INSERT 在风控段之前执行，portfolio_snapshots 也写的是减仓前市值。
- → IMPLEMENTATION_REQUIRED（canonical positions 重读 + 快照写入时机后移或二次刷新）

## 10. J0-G/J0-H：Bitable Reader

BITABLE_READER_STATUS = **两个 parser 并存**
- real_portfolio_truth.py：BITABLE_FIELD_INDEX + _validate_field_order + 类型转换（权威）
- fetch_holdings_westock.py:22-40：自己 lark-cli + 表头猜 CODE 列（独立 parser，无字段校验，
  仅取代码列所以风险有限，但违反 SINGLE AUTHORITY 原则）
→ IMPLEMENTATION_REQUIRED：让 fetch_holdings_westock.read_holdings_codes 复用
real_portfolio_truth 的读取层（注意避免重复 lark-cli 启动，可传 holdings 参数复用）。

SNAPSHOT_REUSE_STATUS = **无当日缓存**
build_real_snapshot() 调用点 ≥6 处（daily_decision_contract、observation ×3、
real_portfolio、position_stop_loss_alert、real_portfolio_truth 内部），每次都触发
lark-cli 子进程。同一天多次读取 → 多次 Bitable 访问 + 时间点不一致风险。
→ IMPLEMENTATION_REQUIRED（daily snapshot cache，MISSING 时不得静默复用旧缓存）

## 11. Fourth Round Finding Matrix

| # | Finding | Status | Fixed By | Remaining Gap | Severity |
|---|---|---|---|---|---|
| 1 | quality_report not effective | PARTIAL | 8-H2 + c5d1624 | BUY/ADD fail-safe + dashboard | High |
| 2 | SIM/PROD isolation | PARTIAL | df936bf(SIM_DB helper)+各脚本迁移 | stock_opportunity_scan.py:152 fallback 错误路径 | Critical(条件触发) |
| 3 | cash formula | FIXED | 763c181 | sell_amount sanity guard(optional) | ~~Critical~~→Closed |
| 4 | flat P&L classification | FIXED | 2026-08-17 重算 | 无 | Closed |
| 5 | BUY+SELL duplicate | OPEN | — | summary-only MULTI_ACTION | Low |
| 6 | trade_gateway no auth | FIXED | api_key 改 env（前轮核实） | SECURITY_DEBT 备注 | Closed(debt) |
| 7 | trade_gateway 0.0.0.0 | FIXED | 绑定改 192.168.1.100（前轮核实）；实测 9527 未监听、无进程 | — | Closed(debt) |
| 8 | emquant plaintext password | OPEN(DEBT) | — | emquant_config.json 644 明文；Broker API 禁改 | Security Debt |
| 9 | backup real portfolio db | FIXED | real_asset_snapshots 表 + 周日备份链 | 无 | Closed |
| 10 | position stoploss chain gap | FIXED | Phase5/5.5 + c5d1624 + 923a695 | URGENT presentation 标记(低) | Closed(minor) |
| 11 | daily report missing quality | PARTIAL | quality_report 已进 daily JSON | WARNING/ERROR 显著展示 | Medium |
| 12 | hardcoded 1M total asset | FIXED | TOTAL_CAPITAL 常量集中(double_monitor:50)；真实仓 total_asset=DATA_UNAVAILABLE 不伪造 | 模拟仓语义即 100万基准，符合设计 | Closed |
| 13 | fetch_holdings_westock duplicate reader | OPEN | — | parser 未统一 | Medium |
| 14 | duplicate Bitable reads | OPEN | — | 无当日 snapshot reuse | Medium |
| 15 | double risk-controller entry | VERIFIED OK | 9d7a57f freeze + 单一调用点 | 无 | Closed |
| 16 | stale post-risk summary | PARTIAL | RC-REFRESH 修了 cash | positions/win-loss/快照仍旧值 | High |

## 12. trade_gateway / emquant 依赖确认

- 无任何生产脚本 import trade_gateway / emquant_trader（grep 证实）
- hermes cron 注册表中无相关任务
- 9527 端口未监听、无进程
→ CURRENTLY_NOT_RUNNING，SECURITY_DEBT 记录，无阻塞。

## 13. 结论

J0_BASELINE_STATUS = **CONSISTENT**（基线重新定义为 8h2 后一致）

REMAINING_J0_WORK_ITEMS（供下阶段决策，均 IMPLEMENTATION_REQUIRED 除注明外）：
1. [Critical] stock_opportunity_scan.py:152 错误 DB fallback 移除/改 SIM_DB helper
2. [High] J0-F 补全：风控后重读 canonical positions + 快照写入时序
3. [High] J0-D 补全：quality ERROR 对 BUY/ADD fail-safe + Dashboard/WARNING 可见性
4. [Medium] J0-G：fetch_holdings_westock 复用统一 Bitable reader
5. [Medium] J0-H：当日 Real Holdings snapshot reuse（失败→MISSING，不静默用旧缓存）
6. [Low] J0-E：buys/sells MULTI_ACTION 标注（summary-only）
7. [Low] stop-loss URGENT presentation 语义确认
8. [Optional] sell_amount sanity guard；heartbeat_state.json / hot_sector_*.md 入 .gitignore
9. PRE_FIX_LEGACY_RESULT vs POST_FIX 重算（依赖 1-2 完成后跑安全运行取数）

Baseline regression：decision/ 全套 **320 passed**，无失败。
