# Production Scheduling & Message Surface Audit（Phase 8-K3）

> 日期：2026-08-26。只读审计。基线：hermes-stock-phase-8k2 / e69525a。
> 未修改任何生产代码/配置。建议修复集列于 §十一，待下一 Phase 执行。

## K3_STATUS = PARTIAL（审计完成，发现 2 个需修复项 + 若干 LOW）

---

## 一、Cron Inventory（真实 registry，24 active stock crons）

| Job | Schedule | Surface | Category | 产生 Final? |
|---|---|---|---|---|
| pre-market-brief | 08:00 | Feishu主群 | INFORMATION | ❌ |
| hot-sector-scanner | 09:30 | origin(local) | SIGNAL/INFO | ❌ |
| position-stop-loss-alert | 09:35 | Feishu主群 | **URGENT/FINAL** | ✅ |
| stock-intraday-minute | */15 9-14 | Feishu主群 | SIGNAL(静默) | ❌ |
| stock-opportunity-push | */30 9-11,13-15 | Feishu主群 | **SIGNAL** | ❌ |
| stock-lhb-daily | 15:35 | Feishu主群 | INFORMATION | ❌ |
| stock-news-sentiment-pilot | 15:40 | Feishu主群 | INFORMATION | ❌ |
| daily-sentiment-report | 15:30 | Feishu主群 | INFORMATION | ❌ |
| deep-position-review | 16:00 | Feishu主群 | INFORMATION(降级后) | ❌ |
| stock-market-cache-refresh | 16:30 | Feishu主群 | 数据层 | ❌ |
| daily-data-refresh | 16:40 | local | 数据层 | ❌ |
| double-monitor-daily | 16:50 | Feishu主群 | **PRODUCTION DECISION** | ✅ |
| weekly-portfolio-summary | Fri16:45 | Feishu主群 | HEALTH | ❌ |
| stock-weekly-analysis | Fri20:00 | Feishu主群 | RESEARCH | ❌ |
| us-stock-weekly-update | Sat10:30 | Feishu主群 | INFORMATION | ❌ |
| stock-recommendation-pool-weekly | Sat11:30 | Feishu主群 | RESEARCH | ❌ |
| stock-financial/weekly-refresh | Sun16:00/16:20 | Feishu主群 | 数据层 | ❌ |
| double-pool-refresh | Sun16:50 | 运维群 | 数据层 | ❌ |
| market-env-report | Sun17:00 | origin | INFORMATION(Regime) | ❌ |
| stock-weekly-screener | Sun17:20 | Feishu主群 | SIGNAL/数据 | ❌ |
| stock-weekly-pipeline | Sun17:50 | Feishu主群 | RESEARCH | ❌ |
| system-health-check | Sun18:00 | origin | HEALTH | ❌ |
| system-health-monitor | */30 | 运维群 | HEALTH | ❌ |
| stock-intraday (DEBUG data) | — | — | DEBUG | ❌ |

---

## 二、M-3：盘后 Opportunity Push 语义审计

**证据**（8/26 15:31:33 run，收盘后 31 分钟）：
- 输出标题：`【盘中推荐 · 15:31】`
- 实时价字段显示 `现价29.37(-1.28%)`，但当日 15:00 已收盘 → 实为 stale 兜底价
- schedule `*/30 9-11,13-15` 含 **15:00 与 15:30** 两个盘后 slot（收盘 15:00）

**OPPORTUNITY_SESSION_SEMANTICS**：
- INTRADAY_VALID_WINDOW：09:30–11:30, 13:00–15:00（交易时段）
- EOD_VALID_WINDOW：15:00 之后不应使用“盘中”口径
- OUT_OF_WINDOW_BEHAVIOR（建议，非本阶段执行）：
  - 15:00/15:30 两次 run 应改为 **EOD Research Summary** 或停止推送
  - 文案从“盘中推荐”改为“盘后扫描/候选更新”
  - 或 schedule 收窄为 `9-11,13-14` 避免盘后 slot

**POST_CLOSE_INTRADAY_SEMANTIC_ERROR = CONFIRMED**（根因：schedule 含盘后 slot + 文案硬编码"盘中"）。

---

## 三、M-4：Prompt-in-MD 泄漏审计

**PROMPT_LEAK_MATRIX**：

| source | task | file | leak_type | user_visible | severity |
|---|---|---|---|---|---|
| 本地 cron output | 所有 no_agent 任务 | `cron/output/<id>/*.md` | job metadata（# Cron Job/Job ID/Run Time/Mode） | local md（非飞书正文） | LOW |
| 本地 cron output | 所有 agent 任务 | `cron/output/<id>/*.md` | 完整 skill system prompt（`## Prompt` + `IMPORTANT: user invoked...`） | local md（飞书正文不含） | MEDIUM |
| 飞书主群正文 | 所有任务 | Feishu message | 无 prompt 泄漏 | — | ✅ clean |

**secret 扫描**：0 命中（api_key/token/password/secret 均无）。

**结论**：飞书用户面干净（K2 已隔离 DEBUG）；M-4 泄漏仅发生在**本地工件文件**，不进入用户聊天。严重性低于 K0 预期，但仍是内部上下文暴露，建议 K3-fix 将 job metadata/prompt 与用户可读内容分离（写入独立 debug 工件或抑制回显）。

---

## 四、10 日消息频率（8/13–8/26 聚合）

| 指标 | 估算值 |
|---|---|
| 主群日消息总量 | ~21–25 条 |
| FINAL（Daily） | 1/日 |
| URGENT（stop-loss） | 0–1/日 |
| SIGNAL（opportunity+intraday+hot-sector） | ~14/日 |
| INFORMATION（pre-market/sentiment/lhb/news/deep-review） | ~5/日 |
| HEALTH（非运维群） | <1/日 |
| DEBUG（intraday 数据落地） | 24 run/日（静默为主，运维群另计） |

**核心结论**：hierarchy 遵守良好——FINAL/URGENT 仅 2 条，Signal 占多数但属预期（盘中监控）。无同等级互相抢 Primary 现象（Daily 16:50 为当日唯一 FINAL 汇总）。

---

## 五、Message Value Matrix（节选）

| task | freq | unique_info | already_in_daily | recommend |
|---|---|---|---|---|
| opportunity-push | 11×/日 | 候选评分 | 否（独立 Signal） | **SCHEDULE_FIX**（去盘后2次） |
| intraday-minute | 20×/日 | 盘中信号 | 否 | KEEP（静默，仅触发输出） |
| deep-position-review | 1×/日 | 持仓诊断 | 部分 | KEEP（已降级） |
| pre-market | 1×/日 | 盘前全景 | 否 | KEEP |
| sentiment/lhb/news | 各1×/日 | 独立资讯 | 否 | KEEP |
| system-health-monitor | 48×/日 | 运维健康 | 否 | **LOCAL_ONLY 候选**（运维群已隔离，主群无） |

---

## 六、Task→Surface Matrix（节选）

| task | current | desired | dup_risk |
|---|---|---|---|
| opportunity-push | SIGNAL主群 | SIGNAL主群（去盘后） | 中（盘后冗余） |
| intraday-minute | SIGNAL主群 | SIGNAL主群（静默） | 低 |
| system-health-monitor | HEALTH运维群 | HEALTH运维群 | 低 |
| deep-position-review | INFO主群 | INFO主群 | 低（已降级） |

---

## 七、User Scenario 验收

| # | 场景 | 结果 |
|---|---|---|
| 1 正常交易日"怎么办" | Daily(FINAL) + stop-loss(URGENT) 两条主面 | ✅ 2 条核心 |
| 2 止损 | URGENT·FINAL 标签清晰 | ✅ |
| 3 机会信号 | 【SIGNAL·非最终决策】 | ✅ |
| 4 盘后 15:30 | **仍见"【盘中推荐】"** | ❌ M-3（审计确认） |
| 5 系统异常 | Health/Daily 内嵌 data_health | ✅ |
| 6 Debug | 飞书无 [BRANCH]/prompt | ✅（本地 md 有，非飞书） |

---

## 八、24 问速答（节选关键项）

1. Active stock cron = **24**
2. 真实 Surface 见 §一
3. 直接发 Feishu：pre-market/stop-loss/intraday/opportunity/lhb/news/sentiment/deep-review/cache/double-monitor/weekly*/us-stock/screener/pipeline/portfolio
4. 产生 Final：position-stop-loss-alert + double-monitor-daily
5. 只 Signal：opportunity/intraday/hot-sector
6. 只 Information：pre-market/sentiment/lhb/news/deep-review
7. 只 Health：system-health-*
8. M-3 根因：schedule 含 15:00/15:30 盘后 slot + 文案硬编码"盘中"
9. 盘后正确语义：EOD Research/停止/收窄 schedule
10. M-4 泄漏任务：所有 agent 任务（本地 md 含 skill prompt）
11. secret 风险：**无**（0 命中）
12. 日均主群消息 ~21–25
13. FINAL/URGENT=2, SIGNAL~14, INFO~5
14. 真重复：opportunity 盘后 2 次冗余
15. 有效不同证据：各 Signal/Info 数据源独立
16. 被 Daily 覆盖：stop-loss 的 SELL 已并入 Daily（K1 修复后）
17. 最适合 local-only：system-health-monitor 详细日志（已在运维群）
18. 最适合合并：opportunity 盘后 slot → 并入 EOD
19. 同等级抢 Primary？**否**
20. 回答"怎么办"需看 1–2 个源（Daily+Urgent）
21. 最严重调度卫生：M-3 盘后盘中语义错位
22. 最严重用户输出：M-3（用户盘后误以为盘中信号）
23. 最小修复集：见 §十一
24. 暂不改：intraday 静默机制、weekly 系列、health 运维群
25. 可改策略外实施 K3 修复？**是**（仅 schedule/文案/local 工件分离）

---

## 九、RECOMMENDED_MESSAGE_POLICY（证据驱动，不在本阶段执行）

```
SCHEDULE_CHANGE_CANDIDATE (M-3):
  stock-opportunity-push: */30 9-11,13-15 → */30 9-11,13-14
  理由: 15:00/15:30 为盘后，输出"盘中推荐"语义错误
  或: 盘后 run 改文案为【盘后候选更新】且不推送实时价

WIRING_FIX (M-4):
  cron output 本地工件: 将 # Cron Job/## Prompt 元数据与用户正文分离
  理由: 本地 md 泄漏 skill prompt，虽不进飞书但属内部上下文暴露
  飞书面已 clean，不需改

KEEP:
  stop-loss / double-monitor (FINAL/URGENT 唯一来源)
  intraday (SIGNAL 静默，仅触发输出)
  pre-market/sentiment/lhb/news/deep-review (INFO 独立价值)

LOCAL_ONLY_CANDIDATE:
  system-health-monitor 详细日志（已在运维群，主群无影响）
```

## 十、声明

NO STRATEGY CHANGES。本阶段零生产代码修改（新增只读审计测试 + 文档 + JSON）。
IMPLEMENTATION_REQUIRED 列入 §九，等待下一独立 Phase 指令。

只读测试：decision/test_k3_audit.py（12 项全过）。
