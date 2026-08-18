# Git Repository Baseline（Phase G0）

> 建立于：2026-08-19
> 对应 Phase：0 ~ 6.6
> Branch：master
> Commit：e802ed8（baseline 495bb95 + fix real_portfolio os import）

---

## Repository

| 字段 | 值 |
|:--|:--|
| Path | `/home/caojy/.hermes/scripts/cron` |
| Baseline Date | 2026-08-19 |
| Current Phase | 6.6（Production Lifecycle Closure 完成） |
| Branch | master |
| Commit (baseline) | `495bb95` chore: establish Hermes stock system baseline (Phase 0~6.6) |
| Commit (latest) | `e802ed8` fix: add missing os import in real_portfolio.py |
| Tag | `hermes-stock-baseline-20260819` |

## Managed Source
- `decision/`（contract / engine / adapters / execution / outcome / portfolio / real_portfolio / replay / snapshot）
- `double_monitor.py`、`position_stop_loss_alert.py`
- `confirm_execution.py`
- `main_up_backtest_valid.py`、`main_up_light_backtest.py`、`main_up_qualification.py`
- 其他生产脚本（`fetch_*`、`daily_data_refresh.py`、`health_check.py` 等）

## Managed Tests
- `decision/test_*.py`（11 个测试文件）
- `test_trading_permission.py`

## Managed Docs
- `/home/caojy/.hermes/skills/stock/stock-expert/docs/architecture/*.md`
- `PROJECT.md`

## Ignored Runtime Data
- `decision/snapshots/`、`decision/executions/`、`decision/outcomes/`
- `*.log`、`logs/`

## Ignored Databases
- `*.db`（`market_cache.db`、`simulation.db`、`simulation_test.db`、`intraday_cache.db`、`lhb_cache.db`、`news_cache.db`）
- `*.sqlite`、`*.sqlite3`

## Ignored Logs / Cache / Snapshots / Artifacts
- `__pycache__/`、`*.pyc`、`.pytest_cache/`
- `cache/`、`tmp/`、`runtime/`、`artifacts/`、`snapshots/`、`backups/`
- `*.png`、`*.jpg`、`*.pdf`

## Sensitive Files Excluded
| 文件 | 处理方式 |
|:--|:--|
| `emquant_config.json` | 硬编码账号密码 → **.gitignore 排除** |
| `news_sentiment.py` | 硬编码 LLM_API_KEY → **改为环境变量读取** |
| `trade_gateway.py` | 硬编码 api_key → **改为环境变量读取** |
| `decision/real_portfolio.py` | 硬编码 Bitable token → **改为环境变量读取** |
| `position_stop_loss_alert.py` | 硬编码 Bitable token → **改为环境变量读取** |
| `fetch_holdings_westock.py` | 硬编码 Bitable token → **改为环境变量读取** |
| `stock_opportunity_scan.py` | 已用环境变量（FEISHU_BOT_TOKEN），无需改 |
| `scan_doubling_potential.py` | 已用环境变量（FEISHU_WEBHOOK_TOKEN），无需改 |

**敏感内容原文未进入 Git 仓库**（硬编码值已替换为 `os.environ.get(...)`）。

## Current Test Baseline
- **102 passed**（94 + 8 lifecycle tests）
- 无失败 / 无错误

## Rollback
```bash
# 从当前 Phase 6.6 状态回退到 baseline（重置工作区）
git reset --hard hermes-stock-baseline-20260819

# 或查看 baseline 内容（不修改工作区）
git show hermes-stock-baseline-20260819 --stat
```

## Known Limitations
1. Git 纳管范围 = `cron/` 目录代码；架构文档在 `skills/stock/stock-expert/docs/`（未纳入同一仓库，未来可考虑 submodule 或统一仓库）。
2. `.env` 机制尚未建立（敏感信息改为环境变量读取，但未提供 `.env.example` template）。
3. `emquant_config.json` 仍存在本地（运行时需要），仅 .gitignore 排除；若换机器需手动迁移。
