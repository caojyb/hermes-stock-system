# Cron 脚本深度代码扫描报告

> 扫描日期: 2026-08-05
> 扫描路径: /home/caojy/.hermes/scripts/cron/
> 扫描脚本数: 54 个 .py 文件

---

## 数据库概览

| 数据库别名 | 物理路径 | 使用脚本数 |
|---|---|---|
| market_cache | /home/caojy/.hermes/skills/stock/stock-expert/market_cache.db | 41 |
| westock_cache | /home/caojy/.openclaw/workspace-stockexpert/data/westock_cache.db | 1 |
| lhb_cache | /home/caojy/.hermes/scripts/cron/lhb_cache.db | 2 |
| simulation | /home/caojy/.hermes/scripts/cron/simulation.db | 2 |
| news_cache | /home/caojy/.hermes/scripts/cron/news_cache.db | 1 |
| pipeline_status | (由 pipeline_status 模块管理) | 1 |

---

## 数据库读取

### market_cache.db 读取的表和字段

| 表名 | 读取字段 | 使用脚本 |
|---|---|---|
| **stocks** | code, name, market, sector, is_st, list_date, total_shares_real, circulating_shares_real, total_mcap | daily_data_refresh, double_refresh, doubling_gene, scan_doubling_potential, param_optimizer, backtest_liquidity, param_comparison_scan, param_verify_full, v1_diagnose_scan, long_term_backtest, long_term_backtest_v2, long_term_holding, alternative_data, northbound_stock, track_diagnosis, track_loose_channel, ps_pcf_update, full_diagnosis, hot_sector_scanner, double_monitor |
| **klines** | code, date, close, open, high, low, volume, turnover, change_pct | 几乎所有脚本 |
| **indicators** | turnover_rate, ps_ttm, pcf_ttm, atr_14, ma20, north_flow, signal_a/b/c/d, close, volume | double_refresh, doubling_gene, data_upgrade, data_filters, double_monitor, north_flow_monitor, northbound_stock, ps_pcf_update, param_optimizer, position_stop_loss_alert, system_health_check |
| **financial_data** | roe, profit_growth, revenue_growth, debt_ratio, gross_margin, net_margin, report_date | doubling_gene, full_diagnosis, l4_1_signal_conflict, system_health_check, health_check, long_term_backtest, long_term_backtest_v2, track_loose_channel |
| **pe_pb_data** | code, pe_ttm, pe_pct | double_refresh, long_term_backtest, long_term_backtest_v2, system_health_check |
| **double_up_scores** | code, name, sector, scan_date | double_monitor, scan_doubling_potential, l4_1_signal_conflict, system_health_check, alternative_data |
| **trades** | code, name, buy_date, buy_price, buy_shares, buy_amount, status, profit_amount, profit_pct, hold_mode, id | double_monitor, double_refresh, full_diagnosis, simulation_engine, simulation_weekly, simulation_chart, health_check, system_health_check, boundary_verify |
| **main_fund_flow** | COUNT(*) | daily_data_refresh |
| **portfolio_snapshots** | date, total_value, total_return_pct | simulation_chart, simulation_weekly |
| **ipo_blocks** | *, affected_stocks | full_diagnosis, health_check, simulation_engine, double_monitor |
| **track_fund_pool** | SUM(amount) | track_flow_manager |
| **signals** | signal_type, triggered_at, details | double_monitor |

### lhb_cache.db

| 表名 | 读取字段 | 使用脚本 |
|---|---|---|
| **lhb_data** | COUNT(*) | daily_data_refresh |

### westock_cache.db

| 表名 | 读取字段 | 使用脚本 |
|---|---|---|
| **board_cache** | COUNT(*), MAX(date) | daily_data_refresh |

### simulation.db

| 表名 | 读取字段 | 使用脚本 |
|---|---|---|
| **trades** | *, COUNT, SUM, AVG | simulation_engine, simulation_weekly |
| **portfolio_snapshots** | date, total_value, total_return_pct | simulation_weekly |

### news_cache.db

| 表名 | 读取字段 | 使用脚本 |
|---|---|---|
| (未在 SQL 语句中明确提取字段) | | news_sentiment |

### pipeline_status 表 (独立DB)

| 列 | 使用脚本 |
|---|---|
| task_name, status, data_date, row_count, message, created_at | pipeline_status |

---

## 数据库写入

| 脚本 | 表名 | 写入字段/方式 | SQL 类型 | 所在函数 |
|---|---|---|---|---|
| **daily_data_refresh** | main_fund_flow | (全部字段) | INSERT OR REPLACE | refresh_main_fund_flow |
| **daily_data_refresh** | main_fund_flow | (全部字段) | INSERT OR REPLACE | _refresh_westock_main_fund_flow |
| **double_monitor** | ipo_blocks | (全部字段) | INSERT | ema |
| **double_monitor** | ipo_blocks | (特定字段) | UPDATE | ema |
| **north_flow_monitor** | indicators | north_flow 等 | UPDATE | update_north_flow_db |
| **northbound_stock** | indicators | north_net_buy 等 | UPDATE | update_db |
| **ps_pcf_update** | indicators | ps_ttm, pcf_ttm | UPDATE | update_db |
| **data_upgrade** | indicators | (特定字段) | UPDATE | update_valuation |
| **fix_total_shares_real** | stocks | total_shares_real | UPDATE | main |
| **simulation_engine** | trades | status, profit_amount, exit_price, exit_date | UPDATE | check_exit_signals |
| **simulation_engine** | trades | buy_price, buy_shares, buy_amount | UPDATE | ema |
| **simulation_engine** | ipo_blocks | status, affected_stocks | UPDATE | check_ipo_suction |
| **simulation_weekly** | portfolio_snapshots | (全部字段) | INSERT | <module> |
| **double_refresh** | (JSON文件) | double_pool.json | (写入 JSON) | get_trend_label |
| **scan_doubling_potential** | double_up_scores | (全部行) | DELETE | write_to_db |
| **pipeline_status** | pipeline_status | task_name, status, data_date, row_count, message | INSERT | record_status |
| **backtest_liquidity** | (DB读) | 读取 stocks + klines | SELECT | _strategy |
| **param_comparison_scan** | (DB读) | 读取 stocks + klines | SELECT | scan_stocks |
| **param_verify_full** | (DB读) | 读取 stocks + klines | SELECT | _strategy |
| **l5_2_consecutive_stop_loss** | trades | (全部) | DELETE | init_portfolio |
| **l5_2_consecutive_stop_loss** | trades | status, exit_price, exit_date | UPDATE | run_simulation |
| **l5_2_consecutive_stop_loss** | portfolio_snapshots | (全部) | DELETE | run_simulation |
| **l5_3_full_position_drawdown** | trades | (全部) | DELETE | init_portfolio |
| **l5_3_full_position_drawdown** | trades | status, exit_price, exit_date | UPDATE | run_simulation |
| **l5_3_full_position_drawdown** | portfolio_snapshots | (全部) | DELETE | run_simulation |
| **risk_controller_v2** | portfolio_snapshots | (全部) | DELETE | check_portfolio_drawdown_v2 |

---

## 外部 API

### 东方财富 API (eastmoney.com HTTP 直连)

| 脚本 | API 域名/端点 | 方法 | 所在函数 |
|---|---|---|---|
| **daily_data_refresh** | push2delay.eastmoney.com/api/qt/clist/get | GET | fetch_northbound_batch |
| **daily_data_refresh** | push2.eastmoney.com/api/qt/clist/get | GET | fetch_main_fund_rank |
| **daily_data_refresh** | datacenter.eastmoney.com/securities/api/data/v1/get | GET | fetch_lhb |
| **data_filters** | push2delay.eastmoney.com/api/qt/stock/get | GET | check_liquidity_accurate, check_market_timing |
| **data_filters** | datacenter.eastmoney.com/securities/api/data/v1/get | GET | fetch_performance_warnings |
| **data_upgrade** | push2delay.eastmoney.com/api/qt/stock/get | GET | fetch_main_fund_flow, estimate_ps_pcf, update_valuation |
| **double_monitor** | push2delay.eastmoney.com/api/qt/clist/get | GET | ema |
| **double_refresh** | push2delay.eastmoney.com/api/qt/stock/get | GET | estimate_mcap |
| **hot_sector_scanner** | push2delay.eastmoney.com (indirect) | GET | (URL拼接) |
| **intraday_cache** | push2delay.eastmoney.com/api/qt/stock/trends2/get | GET | fetch_minute_data |
| **lhb_monitor** | datacenter.eastmoney.com/securities/api/data/v1/get | GET | fetch_lhb |
| **news_sentiment** | search-api-web.eastmoney.com/search/jsonp | GET | fetch_news_via_api |
| **north_flow_monitor** | push2delay.eastmoney.com/api/qt/clist/get | GET | fetch_north_top |
| **northbound_stock** | push2delay.eastmoney.com/api/qt/clist/get | GET | fetch_all_northbound |
| **ps_pcf_update** | push2delay.eastmoney.com/api/qt/clist/get | GET | get_pcf_batch |
| **ps_pcf_update** | push2delay.eastmoney.com/api/qt/stock/get | GET | get_ps_single |
| **simulation_engine** | push2delay.eastmoney.com/api/qt/clist/get | GET | scan_upcoming_ipos |
| **simulation_engine** | push2delay.eastmoney.com/api/qt/stock/get | GET | scan_upcoming_ipos |
| **long_term_backtest** | push2delay.eastmoney.com (indirect) | GET | fetch_klines_hist |

### westock 调用 (腾讯自选股数据)

| 脚本 | 调用方式 | 所在函数 |
|---|---|---|
| **daily_data_refresh** | client.westock_asfund(code, date) | _refresh_westock_main_fund_flow |
| **daily_data_refresh** | client.westock_lhb(code, date) | _refresh_westock_lhb |
| **daily_data_refresh** | subprocess.run([python, westock_batch.py, ...]) | _run_westock_batch |
| **stock_opportunity_scan** | subprocess.run → fetch_westock_technical | fetch_westock_technical |

### 飞书 (Feishu/Lark)

| 脚本 | 调用方式 | 所在函数 |
|---|---|---|
| **double_monitor** | feishu_send_message(chat_id, text) | calc_sector_strength, ema |
| **portfolio_summary** | feishu_send_message(chat_id, text) | send_feishu, main |
| **position_stop_loss_alert** | feishu_send_message(chat_id, text) | send_feishu, main |
| **stock_opportunity_scan** | requests.post → open.feishu.cn/open-apis/bot/v2/hook/ | send_feishu |
| **heartbeat** | requests.post → open.feishu.cn/open-apis/bot/v2/hook/ | check_webhook |
| **factor_ic** | _send_feishu(report) | analyze_factor_ic |
| **system_health_check** | (feishu integration) | check_strategy_layer |
| **verify_westock** | subprocess.run(shell) | <module> |

### EMQuantAPI (东方财富量化)

| 脚本 | 调用方式 | 所在函数 |
|---|---|---|
| **emquant_trader** | from EmQuantAPI import c | login, get_quote, place_order |
| **trade_gateway** | subprocess.run(emquant_trader.py ...) | generate_signals_from_recommendations |

### subprocess 调用

| 脚本 | 命令 | 所在函数 |
|---|---|---|
| **daily_data_refresh** | python westock_batch.py {mode} | _run_westock_batch |
| **stock_opportunity_scan** | python westock_batch.py technical | fetch_westock_technical |
| **position_stop_loss_alert** | python trade_gateway.py --get-positions | get_real_positions |
| **l4_1_signal_conflict** | (subprocess run) | run_score_upgrade |
| **trade_gateway** | python emquant_trader.py ... | generate_signals_from_recommendations |
| **verify_westock** | shell commands | <module> |

---

## 文件操作

### JSON 文件读写（数据库之外的主要持久化方式）

| 脚本 | 文件路径 | 操作 | 所在函数 |
|---|---|---|---|
| **double_refresh** | /home/caojy/.hermes/scripts/cron/double_pool.json | 写 | get_trend_label |
| **heartbeat** | heartbeat.log, heartbeat_state.json, heartbeat_alert.log | 读/写 | log, load_state, save_state, send_backup_alert |
| **northbound_stock** | north_cache_*.json | 读/写 | update_north_cache, check_consecutive_sell/buy |
| **north_flow_monitor** | north_flow_log.json | 读/写 | load_north_log, save_north_log |
| **trade_gateway** | config.json, signals/*.json, receipts/*.json | 读/写 | load_config, save_config, generate_signal, get_pending_signals, mark_signal, do_POST |
| **data_filters** | performance_log.json | 读/写 | save_performance_log |
| **data_upgrade** | sector_ratings.json, candidate_pool.json | 读 | load_sector_ratings, run_all |
| **full_diagnosis** | double_pool.json, candidate_pool.json | 读 | fail |
| **health_check** | pool config + history.json | 读/写 | run_health_check |
| **long_term_holding** | sector_rating.json, candidate_pool.json | 读 | load_sector_rating, scan_long_term_seeds |
| **track_flow_manager** | track_pool.json, pending_buys.json | 读/写 | load_track_pool, load_pending_buys, save_pending_buys |
| **track_diagnosis** | candidate_pool.json | 读 | load_candidate_pool |
| **track_loose_channel** | (结果 JSON) | 写 | run |
| **simulated_execution** | execution_history.json | 读/写 | collect_historical_executions, main |
| **simulation_engine** | candidate_pool.json | 读 | main |
| **hot_sector_scanner** | (结果 JSON) | 写 | main |
| **intraday_cache** | pool JSON | 读 | load_pool |
| **lhb_monitor** | pool JSON | 读 | load_pool |
| **news_sentiment** | pool JSON | 读 | get_pool_names |
| **emquant_trader** | emquant_config.json | 读/写 | load_config, save_config |
| **ga_main_up_optimizer** | (报告 JSON) | 写 | main |
| **param_ga_optimizer** | (报告 JSON) | 写 | main |
| **log_replay** | (日志文件) | 读 | replay_log |
| **stock_opportunity_scan** | (结果 JSON) | 写 | track_to_pool |
| **system_health_check** | (扫描文件) | 读(Path.read_text) | check_strategy_layer |

---

## 环境变量

| 脚本 | 变量名 | 所在位置 |
|---|---|---|
| **double_monitor** | SIM_MODE (os.getenv) | 模块级 |
| **stock_opportunity_scan** | FEISHU_BOT_TOKEN (os.environ.get) | 模块级 |
| **emquant_trader** | (EMQuantAPI 账号密码从配置文件读取) | load_config |

---

## 各脚本依赖图谱总结

### 数据库操作密集型脚本（15+ SQL ops）
- **daily_data_refresh** (14+ SQL, 20+ API calls) — 核心数据刷新，综合使用 eastmoney API + westock + subprocess
- **double_monitor** (20 SQL ops) — 翻倍策略监控，飞书通知
- **simulation_engine** (19 SQL ops) — 回测引擎核心，交易模拟
- **simulation_weekly** (11 SQL ops) — 周度回测汇总
- **double_refresh** (11 SQL ops) — 翻倍池刷新
- **full_diagnosis** (12 SQL ops) — 综合诊断
- **boundary_verify** (8 SQL ops) — 边界验证
- **doubling_gene** (8 SQL ops) — 翻倍基因筛选

### API 调用密集型脚本
- **daily_data_refresh** (20 API calls) — eastmoney + westock + subprocess
- **stock_opportunity_scan** (13 API calls) — westock + feishu + subprocess
- **emquant_trader** (11 API calls) — EMQuantAPI
- **trade_gateway** (4 API calls) — EMQuantAPI + subprocess

### 文件操作密集型脚本
- **trade_gateway** (22 file ops) — HTTP 服务器模式，配置/信号/回执管理
- **northbound_stock** (12 file ops) — 北向资金 JSON 缓存
- **heartbeat** (8 file ops) — 心跳状态 JSON
- **north_flow_monitor** (6 file ops) — 北向资金日志
- **track_flow_manager** (6 file ops) — 追踪资金池 JSON
- **data_filters** (6 file ops) — 性能日志
- **health_check** (6 file ops) — 健康检查历史

### 无外部依赖（纯计算）
- **stress_test.py** — 纯压力测试数学计算
- **stress_test_2024_detail.py** — 纯数学计算

---

## 关键发现

1. **数据库统一性**: 41/54 个脚本使用 market_cache.db，以 `get_db_path('market_cache')` 为标准入口
2. **API 调用模式**: 所有 HTTP 调用直接使用 `requests.get()` 直连 eastmoney.com API，未使用 MCP 工具封装
3. **westock 调用**: 通过 `data_client` 库的 `westock_asfund`/`westock_lhb` 方法，或 subprocess 调用 `westock_batch.py`
4. **飞书通知**: 两种模式并存 — (a) 通过 `feishu_sender.feishu_send_message` SDK 发到 chat_id，(b) 直接 POST webhook URL
5. **JSON 文件持久化**: 大量使用 JSON 文件作为 SQLite 的补充/缓存层，路径分散在 cron 目录下
6. **环境变量极少**: 仅 2 个脚本使用环境变量（SIM_MODE 和 FEISHU_BOT_TOKEN），配置多为硬编码路径
7. **无 MCP 工具调用**: 所有脚本均未使用 `mcp__eastmoney__*`/`mcp__tdx__*`/`mcp__cn_financial__*` 等 MCP 工具
