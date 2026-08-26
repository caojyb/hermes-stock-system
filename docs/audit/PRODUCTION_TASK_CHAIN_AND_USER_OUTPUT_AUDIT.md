# Production Task Chain & User Output Audit（Phase 8-K0）

> 日期：2026-08-26。只读审计。基线：hermes-stock-phase-8j0d / ca530e3。
> 未修改任何代码/规则/cron/配置。

## K0_STATUS = **PARTIAL**

（发现 1 项 HIGH 断链 + 若干 MEDIUM，无 CRITICAL 第二决策中心）

---

## 一、Cron Inventory（真实 registry：~/.hermes/cron/jobs.json）

股票相关 ACTIVE cron 共 **24 个**（另有 fortune/sales/cleanup 等 non-stock 任务不计入）：

| # | Job | Schedule | 分类 | 输出层 |
|---|---|---|---|---|
| 1 | stock-pre-market-brief | 平日08:00 | INFORMATION | Feishu(主群) agent模式 |
| 2 | hot-sector-scanner | 平日09:30 | SIGNAL/INFORMATION | origin(local) |
| 3 | position-stop-loss-alert | 平日09:35 | **URGENT/FINAL** | Feishu(主群) no-agent |
| 4 | stock-intraday-minute | 盘中每15分 | DEBUG/数据采集 | local |
| 5 | stock-opportunity-push | 盘中每30分 | **SIGNAL** | Feishu(主群) no-agent |
| 6 | stock-lhb-daily | 平日15:35 | INFORMATION | Feishu(主群) no-agent |
| 7 | stock-news-sentiment-pilot | 平日15:40 | INFORMATION | Feishu(主群) no-agent |
| 8 | daily-sentiment-report | 平日15:30 | INFORMATION | Feishu(主群) no-agent |
| 9 | deep-position-review | 平日16:00 | INFORMATION（含建议措辞⚠️） | Feishu(主群) agent模式 |
| 10 | stock-market-cache-refresh | 平日16:30 | 数据层 | Feishu(主群) no-agent |
| 11 | daily-data-refresh | 平日16:40 | 数据层 | local |
| 12 | double-monitor-daily | 平日16:50 | **PRODUCTION DECISION** | Feishu(主群)+reports |
| 13 | weekly-portfolio-summary | 周五16:45 | HEALTH/账户视图 | Feishu |
| 14 | stock-weekly-analysis | 周五20:00 | RESEARCH | Feishu |
| 15 | us-stock-weekly-update | 周六10:30 | INFORMATION | Feishu |
| 16 | stock-recommendation-pool-weekly | 周六11:30 | RESEARCH | Feishu |
| 17 | stock-financial-weekly-refresh | 周日16:20 | 数据层 | Feishu no-agent |
| 18 | stock-pe-pb-weekly-refresh | 周日16:00 | 数据层 | Feishu no-agent |
| 19 | double-pool-refresh | 周日16:50 | 数据层 | Feishu no-agent |
| 20 | market-env-report | 周日17:00 | INFORMATION(Regime) | local |
| 21 | stock-weekly-screener | 周日17:20 | SIGNAL/数据层 | Feishu no-agent |
| 22 | stock-weekly-pipeline | 周日17:50 | RESEARCH报告 | Feishu no-agent |
| 23 | system-health-check | 周日18:00 | HEALTH | origin |
| 24 | system-health-monitor | 每30分 | HEALTH | Feishu(运维群) |

分类依据 = registry + 脚本代码 + 真实输出样本，非文件名猜测。
LEGACY/DISABLED：double_refresh.py（cron 已停用）；simulation_engine/l5_*/simulated_execution = MANUAL_ONLY 不在 registry。

## 二、Production Task Graph（核心链，pipeline_status 实证 8/26 时序）

```
[16:30] market-cache-refresh (实际16:37 ok, klines→2026-08-26)
   ↓ check_upstream(max_age=180min)
[16:40] daily-data-refresh (实际16:48 ok; indicators/signals/股东筹码两融)
   ↓ pipeline_status
[16:50] double-monitor-daily (实际16:53 ok)
   ├─ 止损/止盈段 → DecisionEngine.decide → save_snapshot + execution/outcome
   ├─ 买入段 → Permission→Portfolio→DecisionEngine(BUY gate)
   ├─ 风控减仓段 → risk_controller_v2 → DecisionEngine(SELL归一)
   └─ 报告段 → daily_decision_contract(Daily Decision Report)
              → feishu_delivery(Priority投递+幂等去重)
              → observation report

[09:35] position-stop-loss-alert（独立URGENT链）
   └─ Bitable→RealSnapshot→DecisionEngine逐只→飞书直推
      ⚠️ snapshot落盘在cron环境缺失（见 HIGH-1）

盘中: opportunity-push(SIGNAL) / intraday-minute(DEBUG数据)
```

## 三、Authority Matrix（Final Action Producer）

| Producer | Action | DecisionEngine? | decision_id | persistence | consumer |
|---|---|---|---|---|---|
| double_monitor 止损/止盈段 | SELL | ✅ decide() L744/778 | ✅ | snapshot+trades+execution+outcome | Daily Report |
| double_monitor 买入段 | BUY/NO_TRADE | ✅ L933 | ✅ | snapshot+trades | Daily Report |
| risk_controller_v2 | SELL(trim) | ✅ L494 | ✅ (923a695修复) | trades UPDATE带id | summary |
| position_stop_loss_alert | HOLD/REDUCE/SELL/ADD | ✅ L186 | ✅ | snapshot(⚠️cron缺)+飞书直推 | URGENT surface |
| track_flow_manager | BUY建仓 | ✅ (Phase3.6 fail-safe) | ✅ | trades | — |
| stock_opportunity_push | 无action（纯SIGNAL） | 不持有engine | N/A | 推荐池db | Feishu SIGNAL |

**结论：不存在第二 Final Decision Owner。** deep-position-review 有"🔴减仓"措辞但无
decision_id、不经 engine —— 属 INFORMATION 层越权措辞（MEDIUM，见 §九）。

## 四、Actionability Matrix（基于真实 Daily Contract 字段）

| Action | symbol | timing | sizing status | reason | decision_id | 可执行性判定 |
|---|---|---|---|---|---|---|
| BUY | ✅ | ✅ planned_entry | ✅ READY/BLOCKED/PARTIAL 显式 | ✅ reason_codes | ✅ | BLOCKED 时转 NO_TRADE 显示 |
| ADD | ✅ | ✅ | ✅ 同上 | ✅ | ✅ | 同上 |
| HOLD | ✅ | n/a | optional | ✅ | ✅ | 信息性 |
| REDUCE | ✅ | ✅ | quantity if known | ✅ | ✅ | PARTIAL 允许 |
| SELL | ✅ | ✅ 当日 | quantity if known | ✅ exit_reason | ✅ | 可执行 |
| NO_TRADE | scope | 当前窗口 | N/A | ✅ blocking_layer reason_codes | ✅ | 明确不可执行原因 |

实测样本（8/25 Daily Report）：
`SELL 003010 | decision_id=2026-08-25T14:41...003010... | reason完整` → **可回答五问中的4问**
（何时卖=当日、为什么=exit_reason、卖多少=sizing、来源=decision_id）。BUY 类当日为 NO_TRADE
时 blocking layer 显式（REAL_TOTAL_ASSET_UNKNOWN / REAL_HOLDINGS_QUALITY_ERROR）。

**Account MISSING 场景**（当前真实状态 total_asset=DATA_UNAVAILABLE）：
HOLD/REDUCE/SELL 正常产出；BUY/ADD 全部 NO_TRADE+BLOCKED——语义正确（§十二验证通过）。

## 五、Effective Window / Supersession

- snapshot 文件名含 UTC 时间戳 + immutable（已存在不覆盖）
- load_today_snapshots 按 `timestamp.startswith(today)` 过滤 → 过期自动排除（测试验证 1999 日期返回空）
- detect_conflicts() 存在 FINAL vs FINAL 重叠检测（user_authority）
- 实测：8/26 早 09:35 stop-loss 8×SELL 与晚 16:50 monitor 无同 symbol FINAL 冲突
  （模拟仓已清仓，两者标的域不同：Bitable 真实仓 vs simulation）

## 六、Symbol Conflict Matrix

| 组合 | 实例 | 分类 |
|---|---|---|
| Signal(opportunity) vs Final(stop-loss) 不同标的域 | 每日 | 非 conflict |
| Final(double-monitor SELL simulation) vs Final(stop-loss SELL bitable) | 8/26 | 不同持仓体系，非 conflict |
| MULTI_ACTION 同symbol BUY+SELL | 尚未发生 | 显示层已处理（J0B） |
| TRUE_FINAL_CONFLICT | **未发现** | — |

## 七、Duplicate Message Analysis

TOP_DUPLICATED_SYMBOLS（8/26）：蓝色光标300058 出现于 stop-loss(URGENT SELL)、
deep-review(INFORMATION 减仓)、portfolio-summary(INFORMATION) —— 三条消息分属不同层级
且内容不同质 → **非 duplicate**（不同证据）。重复投递由 feishu_delivery
is_duplicate_delivery 幂等抑制（8/26 实测 DUPLICATE_SUPPRESSED ✓）。
未发现 30+ 条同等级消息刷屏。

## 八、Timing / Staleness（实际执行时间 vs schedule）

| 链 | scheduled | actual (8/26) | 判定 |
|---|---|---|---|
| cache→daily→monitor | 16:30→16:40→16:50 | 16:37→16:48→16:53 | ✅ 顺序正确，有上游检查 |
| stop-loss 09:35 在 market-cache(前日16:30) 之后 | 09:35 | 09:35 | ⚠️ 使用昨日K线（lag≤1 属正常盘前行为，data_health 会标注） |
| opportunity-push 15:30 run | 收盘后仍运行 | 15:31 | ⚠️ MEDIUM：收盘后盘中任务产生 stale context 推送 |

stale 触发 BUY 的可能性：double_monitor IS_TRADING_DAY 防护 + freshness guard +
check_upstream → stale 不能触发 BUY（Scenario C/E 验证通过）。

## 九、Output Quality Matrix（真实样本评分）

| 输出 | symbol | action | 来源 | decision_id | reason | Final? | 有效期 | DEBUG污染 | traceback | 重复 | 模糊措辞 | 总评 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| stop-loss 9:35 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ URGENT | 部分⚠️ | 无 | 无(0 files全库) | 否 | 否 | **A-** |
| double-monitor Daily | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | [BRANCH]调试行残留⚠️ | 无 | 否 | 否 | A- |
| opportunity | ✅ | 无(✓正确) | n/a | n/a | ✅评分 | SIGNAL✓ | n/a | 无 | 无 | 中(30分钟频率) | 否 | B+ |
| pre-market | n/a | n/a | n/a | n/a | n/a | INFORMATION✓ | n/a | prompt泄漏在md头部⚠️ | 无 | 否 | 否 | B |
| sentiment/LHB/news | ✅ | 无 | n/a | n/a | n/a | INFORMATION✓ | n/a | 无 | 无 | 否 | 否 | A- |
| hot-sector | ✅ | 无 | n/a | n/a | ✅信号 | SIGNAL✓ | n/a | prompt头部可见⚠️ | 无 | 否 | 否 | B |
| deep-position-review | ✅ | ⚠️减仓措辞 | ❌无来源 | ❌ | ✅ | AMBIGUOUS⚠️ | ❌ | 无 | 无 | 否 | 部分 | **C+** |

全库 cron output 无 Python Traceback 泄漏（grep 证实 0 文件）。

## 十、Failure Propagation（只读场景核验）

| Scenario | 上游状态 | 下游行为 | 用户看到 | BUY可能? | 判定 |
|---|---|---|---|---|---|
| A cache failed | pipeline error | monitor check_upstream 告警+降级 | 告警推送 | 否(fail-safe禁新仓) | ✅ |
| B daily failed | error 记录(8/25实例) | monitor 次日检测到并告警 | ⚠️告警 | 否 | ✅（8/25 实际发生过，传播正确） |
| C kline stale | lag>3日 | freshness guard 拒绝写池+飞书告警 | 告警 | 否 | ✅ |
| D Bitable failed | holdings MISSING | Account not READY → BUY/ADD blocked | UNKNOWN状态展示 | 否；SELL保留 | ✅ |
| E feature missing | filters 标记 | 候选被过滤 | 排除清单 | 否 | ✅ |
| F snapshot missing | Daily 读不到该 decision | **HIGH-1 断链（见下）** | URGENT有/Daily无 | — | ⚠️ |
| G delivery failed | delivery_status=FAILED | Decision 不受影响（源码断言） | 投递失败提示 | — | ✅ |
| H observation failed | [REPORT] try 包裹 | Decision 不受影响 | 缺 observation | — | ✅ |

### HIGH-1（本审计最重要发现）：Stop-Loss 快照在 cron 环境丢失

证据链：
1. 8/24、8/25、8/26 三天 09:35 stop-loss cron 正常输出 8-9 个 SELL 决策（用户已在飞书收到，rc=ok）
2. 但 `decision/snapshots/` 目录中没有任何 9:35 的快照文件（三天均如此）
3. 当日 16:50 Daily Report `total_decisions` 只含 double-monitor 的止损，**stop-loss 的 SELL 从未进入 Daily Surface**
4. 手动复现（系统 python3.12 和 hermes venv python3.13、两种 cwd）save_snapshot 均**成功落盘**且 load_today_snapshots 能读回
5. 输出 md 无任何 `[WARN] snapshot save failed`
6. 结论：存在某种 cron 运行环境差异导致快照写入失败或写到别处，**根因未定**（IMPLEMENTATION_REQUIRED，K1 修复阶段需加落盘自校验 + 失败醒目告警）

影响：用户在 URGENT 看到 SELL 后，Daily Decision Report 无法作为统一对账面（违反
"Daily=Primary Decision Surface"完整性）。不产生错误动作（fail-safe 方向安全），故 HIGH 非 CRITICAL。

## 十一、用户视角场景验收（8 场景）

| Scenario | 结果 |
|---|---|
| 1 正常交易日"今天该怎么办" | ✅ Daily Decision 主面 + stop-loss URGENT（但见 HIGH-1 对账缺口） |
| 2 高波动"为什么不建仓" | ✅ 环境标签🔴高波动+缩放0.5x+NO_TRADE reason_codes |
| 3 真实持仓止损 | ✅ action/symbol/reason/decision_id/仅建议不自动交易 全齐 |
| 4 Opportunity 是 Signal | ✅ 措辞无 BUY 指令（源码+输出双验证） |
| 5 上游失败 DATA_NOT_READY | ✅ pipeline error 传播+告警（8/25 实例） |
| 6 Bitable 失败 | ✅ MISSING→Account not READY→BUY blocked，不会误显已卖出 |
| 7 同股多消息哪个是 Final | ⚠️ PARTIAL：分层正确但用户侧无显式"FINAL/SIGNAL"标签（MEDIUM-2） |
| 8 Account Asset 缺失 | ✅ 持仓分析可用+BUY sizing BLOCKED 显式 |

## 十二、发现分级汇总

### CRITICAL
无。（无第二 Final Owner；无 stale→BUY 路径；无数据互相污染）

### HIGH
- **H-1** Stop-Loss cron 快照落盘缺失（§十 HIGH-1）：URGENT 与 Daily 断链，根因未定

### MEDIUM
- **M-1** deep-position-review（agent 模式）输出"🔴减仓/🟢持有"行动性措辞，无 decision_id、非 DecisionEngine 产物 → INFORMATION 层 AMBIGUOUS_CLASSIFICATION，用户可能与 Final 混淆
- **M-2** 用户消息缺少显式 FINAL/SIGNAL/INFORMATION 分层标签，跨消息来源辨识靠用户记忆
- **M-3** opportunity-push schedule 含 15:30，收盘后仍以"盘中推荐"口径推送（stale context）
- **M-4** pre-market-brief / hot-sector 的 output md 头部包含完整 skill prompt（DEBUG 内容进入用户可读文件；Feishu 正文未见，属本地工件卫生问题）
- **M-5** double_monitor stdout 含 [BRANCH]/[RC-REFRESH] 等工程调试标记直达 Feishu（no_agent 直投），轻度 DEBUG 污染

### LOW
- L-1 stop-loss URGENT 消息无显式有效期字段（当日有效隐含）
- L-2 system-health-check deliver=origin（CLI 本地），与其它健康任务的运维群不一致
- L-3 pipeline_status 表位于 skills 目录的 market_cache.db（路径权威性历史遗留）

## 十三、Recommended Fix Phases（不在本阶段执行）

```
K1: critical/high task-chain fixes
    - H-1 stop-loss 快照落盘自校验 + 失败醒目告警（重试→告警，不允许静默）
K2: user output clarification
    - M-1 deep-review 措辞降级为"观察参考"或标注 NON_DECISIONAL
    - M-2 消息头部增加 [FINAL]/[SIGNAL]/[INFO] 层级标签
    - M-5 清理 double_monitor 面向用户的调试标记（保留落盘日志）
K3: message consolidation & scheduling hygiene
    - M-3 opportunity 15:30 run 移除或改口径
    - M-4 prompt 与用户输出分离
    - L-1/L-2/L-3
```

## 十四、30 问速答

1. Active 股票 cron = **24**
2. Production Decision Chain = double-monitor-daily（+其上游 cache/daily-refresh）
3. Signal only = opportunity-push、hot-sector、weekly-screener
4. Information = pre-market、LHB、news、sentiment、us-stock、market-env、deep-review*
5. Health = system-health-check/monitor、weekly-portfolio-summary
6. Debug = intraday-minute（数据采集）、cron-output-cleanup
7. 只有 DecisionEngine 产生 Final Action？**是**（5 个 producer 全部经 engine）
8. 第二 Final Owner？**无**
9. Final Action 都有 decision_id？**是**
10. 用户知道今天该怎么办？**是**（Daily Primary；HIGH-1 造成 URGENT↔Daily 对账缺口）
11. BUY/ADD timing 明确？**是**（planned_entry_time 字段存在）
12. BUY/ADD sizing status？**是**（READY/BLOCKED 显式，ERROR 自动转 NO_TRADE）
13. SELL/REDUCE reason？**是**（exit_reason/reason_codes）
14. NO_TRADE blocking layer？**是**（reason_codes 含 REAL_TOTAL_ASSET_UNKNOWN 等）
15. Real/Sim 分离？**是**
16. Account MISSING 仍有持仓建议？**是**（HOLD/REDUCE/SELL 正常）
17. Opportunity 是 Signal？**是**
18. Intraday 是 Signal/Debug？**是**
19. Stop Loss 是 Final/URGENT？**是**
20. True Final vs Final 冲突？**未发现**
21. 重复 Final Message？**无**（幂等去重工作正常）
22. 30+ 同级消息刷屏？**无**
23. 上游失败 fail-safe？**是**（8/25 实战验证）
24. stale 触发 BUY/ADD？**不可能**（三层护栏）
25. Bitable failure 错误持仓状态？**不会**（MISSING→blocked 语义）
26. Delivery failure 影响 Decision？**否**
27. Observation failure 影响 Decision？**否**
28. 分层遵守？**基本是**（deep-review 措辞模糊为唯一例外 M-1）
29. 最严重任务链 Bug：**H-1 stop-loss 快照 cron 丢失**
30. 最严重用户输出 Bug：**M-1 deep-review 行动性措辞无 authority 背书**

## 十五、声明

NO STRATEGY CHANGES。本阶段零生产代码修改（新增 1 个只读审计测试文件 + 本文档）。
IMPLEMENTATION_REQUIRED 事项全部列入 §十二/K1-K3，等待下一独立 Phase 指令。

只读审计测试：decision/test_task_chain_audit.py（22 项全过）。
