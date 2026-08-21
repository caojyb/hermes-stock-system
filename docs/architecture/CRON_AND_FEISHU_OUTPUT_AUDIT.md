# Cron & Feishu Output Reality Audit (Phase 8-F0)

> 本文件是 Hermes 股票系统 **Cron / Scheduler / Feishu 输出**的只读事实审计。
> 本阶段不改代码、不改交易规则、不改消息格式、不新增 Primary Decision Output。
> 目标：还原「用户现在到底每天看到什么」。

---

## 1. Scope

审计范围：
- Hermes Scheduler / Cron registry：`~/.hermes/cron/jobs.json`（31 个任务）
- 股票系统相关任务（约 21 个，含周任务）
- 每个任务真实 stdout / stderr / 输出文件 / Feishu 目标
- 用户实际看到的 Feishu 消息类型、频率、重复与冲突

审计日期：2026-08-21
审计基线：git `hermes-stock-phase-8e1`（commit 6e9ab20）

---

## 2. Scheduler Inventory（Hermes Cron 全量）

总任务数：**31**（来自 `~/.hermes/cron/jobs.json`）
调度机制：Hermes 自身 Scheduler（非 crontab / systemd；crontab 仅含 openclaw/hindsight/系统维护，非股票决策）

| EN | ID | Name | Schedule | Script | Deliver | Status |
|---|---|---|---|---|---|---|
| Y | a4f800130622 | cron-health-monitor | 每小时 | health_check_cron.sh | feishu:oc_6825 | ok |
| Y | b03e1e08ada6 | cron-output-cleanup | 03:00 每日 | cron_output_cleanup.sh | feishu:oc_6825 | ok |
| Y | d65cb2d7d744 | daily-data-refresh | 16:40 周一-五 | daily_data_refresh.py | **local** | ok |
| Y | eea9a4d7674e | daily-sentiment-report | 15:30 周一-五 | sentiment_thermo.sh | feishu:oc_88d1 | ok |
| Y | 5a1e590e3c54 | db-auto-backup | 03:00 周日 | db_backup.sh | origin | ok |
| Y | e4a2c0461481 | deep-position-review | 16:00 周一-五 | (agent) | feishu:oc_88d1 | **error** |
| Y | db39df50d53e | double-monitor-daily | 16:50 周一-五 | double_monitor.py | feishu:oc_88d1 | ok |
| Y | e3b3f39c1441 | fortune-daily-push | 08:30 周一-五 | (agent) | feishu:oc_6825 | ok |
| Y | 49dfda6bdef7 | hot-sector-scanner | 09:30 周一-五 | (agent) | origin | **error** |
| Y | 0165f2380e3c | market-env-report | 17:00 周日 | market_env_report.sh | origin | ok |
| Y | 21540a83af1b | position-stop-loss-alert | 09:35 周一-五 | position_stop_loss_alert.py | feishu:oc_88d1 | ok |
| Y | f48759590dc1 | stock-financial-weekly-refresh | 16:20 周日 | fetch_financial_refresh.sh | feishu:oc_88d1 | ok |
| Y | c0c0ac20dc4d | stock-intraday-minute | */15 9-14 周一-五 | intraday_cache.py | feishu:oc_88d1 | ok |
| Y | 348badc42c93 | stock-lhb-daily | 15:35 周一-五 | lhb_monitor.py | feishu:oc_88d1 | ok |
| Y | a6a60497fbb6 | stock-market-cache-refresh | 16:30 周一-五 | market_cache_refresh.sh | feishu:oc_88d1 | ok |
| Y | bcc03e4d1ff7 | stock-news-sentiment-pilot | 15:40 周一-五 | news_sentiment.py | feishu:oc_88d1 | ok |
| Y | 1aa2fd36bdef | stock-opportunity-push | */30 9-11,13-15 | stock_opportunity_scan.py | feishu:oc_88d1 | ok |
| Y | 9ea449d76786 | stock-pe-pb-weekly-refresh | 16:00 周日 | fetch_pe_pb_refresh.sh | feishu:oc_88d1 | ok |
| Y | 354bafa5fb8a | stock-pre-market-brief | 08:00 周一-五 | (agent) | feishu:oc_88d1 | ok |
| Y | 7cbd0f64a31c | stock-recommendation-pool-weekly | 11:30 周六 | weekly_pool_report.sh | feishu:oc_88d1 | ok |
| Y | stock-weekly-analysis | stock-weekly-analysis | 20:00 周五 | (agent) | feishu:oc_88d1 | ok |
| Y | dbfe3b22a18f | stock-weekly-pipeline | 17:50 周日 | stock_pipeline_wrapper.sh | feishu:oc_88d1 | ok |
| Y | df7937dac885 | stock-weekly-screener | 17:20 周日 | stock_screener_wrapper.sh | feishu:oc_88d1 | ok |
| Y | 72a04795e6ce | system-health-check | 18:00 周日 | (agent) | origin | ok |
| Y | 75784417a2b2 | system-health-monitor | 每30分钟 | health_check_system.sh | feishu:oc_6825 | ok |
| Y | 858f5a256a4c | us-stock-weekly-update | 10:30 周六 | us_stock_weekly.sh | feishu:oc_88d1 | ok |
| Y | fd17884dd911 | weekly-portfolio-summary | 16:45 周五 | (agent) | feishu:oc_88d1 | ok |
| Y | 7622c389e379 | 客户动态监控 | 09:00 周二四 | (agent) | feishu:oc_6825 | ok |
| Y | a527bc58b466 | 竞品动态监控 | 09:00 周一三五 | (agent) | feishu:oc_6825 | ok |
| Y | c9d4b0f0def8 | 系统心跳监控 | 09:00/15:00 周一-五 | heartbeat.py | feishu:oc_6825 | ok |
| N | a7b68cb6d6a3 | double-pool-refresh | 16:50 周日 | double_refresh.py | feishu:oc_6825 | **DISABLED** |

Feishu 目标区分：
- `oc_88d1817efbb9f328f4376314ab7c8b05` = **股票主群**（所有股票任务）
- `oc_6825e1438c41d1b7251b1698ea3be4fe` = **平台/通用群**（健康/竞品/命理/清理）

---

## 3. Stock Cron Inventory（股票系统相关，PRODUCTION_ACTIVE）

日频股票任务（周一至五）：
1. `stock-pre-market-brief` 08:00 — 晨间简报（agent）
2. `position-stop-loss-alert` 09:35 — 真实持仓止损（script）
3. `stock-intraday-minute` */15 09-14 — 分钟级信号（script）
4. `stock-opportunity-push` */30 09-11,13-15 — 盘中三档推荐（script）
5. `daily-sentiment-report` 15:30 — 情绪温度计（script）
6. `stock-lhb-daily` 15:35 — 龙虎榜（script）
7. `stock-news-sentiment-pilot` 15:40 — 新闻情绪（script）
8. `stock-market-cache-refresh` 16:30 — 全市场K线（script）
9. `daily-data-refresh` 16:40 — 信号重算（script, **deliver=local 不推 Feishu**）
10. `deep-position-review` 16:00 — 持仓深度诊断（agent, **error 跳过**）
11. `double-monitor-daily` 16:50 — 翻倍信号+模拟交易（script）

周频股票任务：
12. `weekly-portfolio-summary` 周五 16:45
13. `stock-weekly-analysis` 周五 20:00
14. `us-stock-weekly-update` 周六 10:30
15. `stock-recommendation-pool-weekly` 周六 11:30
16. `stock-pe-pb-weekly-refresh` 周日 16:00
17. `stock-financial-weekly-refresh` 周日 16:20
18. `market-env-report` 周日 17:00
19. `stock-weekly-screener` 周日 17:20
20. `stock-weekly-pipeline` 周日 17:50

非股票 Hermes 平台任务（NOT_PART_OF_STOCK_DECISION_SYSTEM）：
- `cron-health-monitor`、`cron-output-cleanup`、`db-auto-backup`、`system-health-check`、`system-health-monitor`、`fortune-daily-push`、`客户动态监控`、`竞品动态监控`、`系统心跳监控`、`double-pool-refresh`(disabled)

---

## 4. PRODUCTION_CRON_TIMELINE（真实顺序）

依据：jobs.json `schedule` + `last_run_at` 确认

```
周一至五（交易日）：
08:00  stock-pre-market-brief        → Feishu 股票群（晨间简报）
09:30  hot-sector-scanner            → (agent, 当前 error 跳过)
09:35  position-stop-loss-alert      → Feishu 股票群（真实持仓止损）
09-15  stock-intraday-minute */15    → Feishu 股票群（盘中信号）
09-15  stock-opportunity-push */30   → Feishu 股票群（三档推荐）
15:30  daily-sentiment-report        → Feishu 股票群（情绪）
15:35  stock-lhb-daily               → Feishu 股票群（龙虎榜）
15:40  stock-news-sentiment-pilot    → Feishu 股票群（新闻情绪）
16:00  deep-position-review          → Feishu 股票群（agent, 当前 error 跳过）
16:30  stock-market-cache-refresh    → Feishu 股票群（缓存成功）
16:40  daily-data-refresh            → local（不推 Feishu）
16:50  double-monitor-daily          → Feishu 股票群（翻倍信号+模拟仓）
```

依赖链：`16:30 market-cache → 16:40 daily-data-refresh → 16:50 double-monitor`
- 前序成功要求：double-monitor 读 market_cache.db 的 K 线，依赖 market-cache 先更新。

---

## 5. 各股票 Cron 真实输出

| Job | stdout 目标 | stderr | 输出文件 | Feishu 推送 |
|---|---|---|---|---|
| stock-pre-market-brief | Hermes agent 响应 | agent log | cron/output | ✅ 股票群 |
| position-stop-loss-alert | script stdout | cron log | cron/output | ✅ 股票群 |
| stock-intraday-minute | script stdout | cron log | cron/output | ✅ 股票群 |
| stock-opportunity-push | script stdout | cron log | cron/output + opportunity_track_latest.json | ✅ 股票群 |
| daily-sentiment-report | script stdout | cron log | cron/output | ✅ 股票群 |
| stock-lhb-daily | script stdout | cron log | cron/output | ✅ 股票群 |
| stock-news-sentiment-pilot | script stdout | cron log | cron/output | ✅ 股票群 |
| stock-market-cache-refresh | script stdout | cron log | cron/output | ✅ 股票群 |
| daily-data-refresh | script stdout | cron log | cron/output | ❌ (deliver=local) |
| double-monitor-daily | script stdout | cron log | cron/output + **reports/daily_decision + reports/production_observation** | ✅ 股票群 |

`REAL_RUN`（真实 cron 输出已采样）：见 `docs/audit/feishu_samples/`

---

## 6. FEISHU_MESSAGE_INVENTORY（用户实际收到的消息）

股票主群（oc_88d1）真实消息（基于 cron output 采样）：

| Job | 时间 | 标题/类型 | 长度 | 含决策 | 含调试 | 类型 |
|---|---|---|---|---|---|---|
| stock-pre-market-brief | 08:00 | 📊 晨间简报 | 27KB | 部分(持仓建议) | 少 | Informational |
| position-stop-loss-alert | 09:35 | 📊 真实持仓统一决策 | 437B | ✅(SELL/HOLD/REDUCE) | 少 | **Decision-like** |
| stock-opportunity-push | 每30min | 【盘中推荐】三档推荐 | ~1KB | ✅(BUY档位/止损/目标) | 少 | **Decision-like** |
| stock-intraday-minute | 每15min | 📊 分钟级信号 | 1.6KB | ✅(A信号) | 中 | Decision-like |
| daily-sentiment-report | 15:30 | 🟡 市场情绪温度计 | 1.5KB | ❌ | 少 | Informational |
| stock-lhb-daily | 15:35 | 📊 龙虎榜数据 | 1.2KB | ❌ | 少 | Informational |
| stock-news-sentiment-pilot | 15:40 | 📰 新闻情绪分析 | 20KB | 部分(利好/利空) | 中 | Informational |
| stock-market-cache-refresh | 16:30 | ✅ 增量更新完成 | 339B | ❌ | 少 | Debug/Runtime |
| double-monitor-daily | 16:50 | 📊 翻倍策略监控 | 19-21KB | ✅(买入信号/推荐等级) | **大量** | **Decision-like** |

结论：股票主群每天消息量 = **8 条固定 + 盘中高频（intraday 每15min + opportunity 每30min）**，一个交易日约 **30+ 条**。

---

## 7. 用户看到的「股票决策消息」识别

Decision-like（真正涉及 BUY/SELL/HOLD/Position/Risk）：
- `position-stop-loss-alert`：SELL/HOLD/REDUCE + 仓位建议（DecisionEngine 归一）
- `stock-opportunity-push`：三档推荐（激进/稳健/价值）+ 止损/目标（**独立逻辑，非 DecisionEngine**）
- `stock-intraday-minute`：A/B/C/D 盘中信号（**独立信号，非 DecisionEngine**）
- `double-monitor-daily`：买入信号 + ⭐推荐等级 + 模拟仓摘要（含 DecisionEngine 归一，但含大量 stdout 调试）

Informational：
- `pre-market-brief`（晨间环境）、`daily-sentiment-report`（情绪）、`stock-lhb-daily`（龙虎榜）、`stock-news-sentiment-pilot`（新闻）

Debug/Runtime：
- `stock-market-cache-refresh`（缓存完成）、`daily-data-refresh`（local）

---

## 8. USER-FACING DECISION OUTPUT MATRIX

| Output | Producer | Final Decision? | DecisionEngine-backed? | Feishu? | User-facing? | Status |
|---|---|---|---|---|---|---|
| 买入信号 + ⭐推荐等级 | double-monitor-daily | 部分 | ✅ | ✅ | ✅ | 多决策出口之一 |
| 模拟仓摘要/净值 | double-monitor-daily | ❌ | 部分 | ✅ | ✅ | 信息 |
| 三档推荐(激进/稳健/价值) | stock-opportunity-push | 部分(仅提示) | ❌ | ✅ | ✅ | **独立出口** |
| 盘中 A 信号 | stock-intraday-minute | ❌ | ❌ | ✅ | ✅ | 独立信号 |
| 真实持仓 SELL/HOLD/REDUCE | position-stop-loss-alert | ✅ | ✅ | ✅ | ✅ | DecisionEngine |
| 晨间持仓建议 | pre-market-brief | 部分 | ❌ | ✅ | ✅ | agent 输出 |
| 龙虎榜 | stock-lhb-daily | ❌ | ❌ | ✅ | ✅ | 信息 |
| 新闻利好/利空 | news-sentiment | ❌ | ❌ | ✅ | ✅ | 信息 |

---

## 9. 当前 PRIMARY 到底是谁（基于事实）

> `CURRENT_PRIMARY_USER_OUTPUT` = **double-monitor-daily 的 Feishu 消息**（16:50，翻倍信号+模拟仓摘要）
> 它同时携带：市场环境、买入信号、推荐等级、模拟仓净值、候选池。
> 但不是唯一决策出口 —— 用户一天会看到 **至少 4 个独立 Decision-like 出口**。

---

## 10. Daily Decision Report 与 Feishu 关系

- `reports/daily_decision_<date>.json/.txt`：**由 double-monitor-daily 生成并落盘**
- Feishu 使用情况：**NOT_CONNECTED**
  - 证据：double-monitor 的 Feishu 消息正文 = 脚本 stdout（不含 daily_decision 内容）
  - daily_decision 只写文件，未接入任何 Feishu 推送

## 11. Production Observation Report 与 Feishu 关系

- `reports/production_observation_<date>.json/.txt`：由 double-monitor-daily 生成并落盘
- 是否被 Scheduler 调用：**是**（double-monitor 末尾）
- 是否被 Feishu 使用：**NOT_CONNECTED**
- 当前状态：**仅保存**（无其他系统消费）

---

## 12. 消息重复 / 冲突

### DUPLICATE_USER_DECISION_OUTPUT
同一 symbol 一天内可能被多个任务重复提示：
- 武汉凡谷(002194)：intraday 盘中信号 + opportunity 推荐 + double-monitor 买入信号，可能同日多条
- 同一条 002194 在 double-monitor 显示「买入信号 A+D」但北向连续流出降级

### CONFLICTING_USER_OUTPUT
存在潜在冲突（本阶段只记录，不修）：
- `opportunity-push` 推荐激进档（独立逻辑） vs `double-monitor` NO_NEW_ENTRY（高波动禁新仓）
- 高波动环境下 double-monitor 可能 NO_TRADE，但 opportunity-push 仍推荐买入
- 不同出口对同一 symbol 的建议可能不一致（因各用各的过滤逻辑）

---

## 13. stdout 是否 = Feishu 消息

- 对 **no_agent 脚本任务**（double-monitor、opportunity-push、intraday、lhb、sentiment、news-sentiment、market-cache）：**stdout 即 Feishu 消息正文**（cron 捕获 stdout 投递）
- 因此 double-monitor 的**大量 stdout 调试**（进度、数据源失败、WARN）也会一并出现在 Feishu 股票群
- 对 **agent 任务**（pre-market-brief、deep-position-review、weekly-*）：Hermes agent 响应投递，非原始 stdout

---

## 14. 真实用户体验图

```text
Hermes Scheduler
   │
   ├─ 08:00 pre-market-brief ──────────────┐
   ├─ 09:30 hot-sector(ERROR)               │
   ├─ 09:35 stop-loss-alert ────────────────┤
   ├─ 09-15 intraday */15 ──────────────────┤→ Feishu 股票群 (oc_88d1)
   ├─ 09-15 opportunity */30 ───────────────┤   每天 30+ 条
   ├─ 15:30 sentiment ─────────────────────┤
   ├─ 15:35 lhb ───────────────────────────┤
   ├─ 15:40 news-sentiment ─────────────────┤
   ├─ 16:00 deep-position(ERROR)            │
   ├─ 16:30 market-cache ───────────────────┤
   ├─ 16:40 daily-data(local,不推)           │
   └─ 16:50 double-monitor ─────────────────┘   ← PRIMARY（含大量stdout调试）
                                            ↓
                                         User（每天看 30+ 条股票消息）
```

---

## 15. PRIMARY OUTPUT GAP

`FEISHU_PRIMARY_GAP`：
1. **无单一 Primary Decision 消息** —— 用户看 4+ 个独立 Decision-like 出口（double-monitor / opportunity / intraday / stop-loss）
2. **double-monitor 消息混入大量 stdout 调试**（进度、数据源失败、WARN），非纯决策
3. **Daily Decision Report 未接入 Feishu**（只落盘 NOT_CONNECTED）
4. **多个出口规则不一致**（opportunity 激进档 vs double-monitor 高波动禁新仓 → 潜在冲突）
5. 重复 symbol 提示（武汉凡谷等）
6. agent 任务（deep-position-review、hot-sector）因模型漂移 **error 跳过**，当前不产出

---

## 16. Known Limitations

- 本次采样为最近真实 cron 输出（2026-08-20/21），部分 agent 任务因 drift error 无最新输出
- Feishu 群内实际渲染格式（富文本/纯文本）未直接从群读取，依据 cron output 文件推断
- daily-data-refresh deliver=local，其 stdout 不进 Feishu

---

## 17. 关键结论（最终回答 20 问）

1. **Hermes 总 Cron 任务**：31
2. **股票 Active Cron**：20（日频 11 + 周频 9）
3. **真实执行顺序**：08:00 晨间简报 → 09:35 止损 → 盘中 intraday/opportunity → 15:30-15:40 情绪/龙虎/新闻 → 16:30 market-cache → 16:40 daily-data → 16:50 double-monitor
4. **每个股票 Cron 命令**：见 §2/§3 表（script 或 agent prompt）
5. **输出到**：cron/output/ + 部分落盘 reports/（仅 double-monitor 写 daily_decision 与 observation）
6. **真正推送 Feishu**：18 个股票任务推 `oc_88d1` 股票群；daily-data-refresh 不推
7. **Feishu 每天股票消息**：约 **30+ 条**（固定 8 条 + 盘中高频）
8. **每条消息内容**：见 §6 FEISHU_MESSAGE_INVENTORY
9. **当前 PRIMARY Decision Message**：**double-monitor-daily Feishu**（但混 stdout 调试，且非唯一）
10. **是否存在多个 Decision-like**：**是**（至少 4 个：double-monitor / opportunity / intraday / stop-loss）
11. **是否存在重复提示**：**是**（同一 symbol 多任务重复）
12. **是否存在消息冲突**：**潜在是**（opportunity 激进 vs double-monitor 高波动禁新仓）
13. **double-monitor stdout 是否就是 Feishu**：**是**（no_agent 任务 stdout 即消息正文）
14. **Daily Decision JSON 是否接入 Feishu**：**NOT_CONNECTED**
15. **Observation JSON 是否接入 Feishu**：**NOT_CONNECTED**
16. **哪个最该成为 Primary**：**Daily Decision Report**（结构化、DecisionEngine 归一、非调试）
17. **当前 Primary Gap**：见 §15（无单一出口 + 调试混入 + 报告未接入 Feishu）
18. **三者关系**：Daily Decision / Observation 落盘 NOT_CONNECTED；Feishu 走独立脚本 stdout
19. **当前用户体验**：一天收 30+ 条多来源股票消息，决策出口分散、含调试噪音
20. **下一步最值得改**：把 Daily Decision Report 作为唯一 Primary 接入 Feishu（单独 Phase，本阶段不改）

---

*审计日期：2026-08-21 · Phase 8-F0 · 只读审计，未修改任何生产逻辑*
