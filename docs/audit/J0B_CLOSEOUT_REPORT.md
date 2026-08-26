# Phase 8-J0B Closeout — Production Integrity Fixes

> Baseline: hermes-stock-phase-8j0a / f6ae869 → 本阶段 tag: hermes-stock-phase-8j0b
> 日期：2026-08-26

## 一、修复清单（OLD / FIX / UNCHANGED / TEST）

### STEP 1 [Critical] stock_opportunity_scan.py DB fallback
- **OLD**: get_holdings() 在 simulation_db_helper import/resolve 失败时静默 fallback 到
  `skills/stock/stock-expert/simulation.db`（另一份数据库），盘中每30分钟生产 cron 可读错仓。
- **FIX**: FAIL CLOSED——resolver 失败打印 `[ERROR]` 并跳过模拟仓读取，绝不猜测路径。
- **UNCHANGED**: 正常路径仍用 get_active_sim_db()（test→simulation_test.db，prod→simulation.db）；
  候选扫描、Bitable 持仓合并逻辑不变。
- **TEST**: test_j0b_integrity.py TestDBFallback（5项：无 fallback 源码断言/test/prod 解析/
  FAIL CLOSED 结构/test-prod 路径互斥）。

### STEP 2 [High] J0-F Risk post-action refresh（double_monitor.py）
- **OLD**: 风控减仓后只刷新 cash；open_pos/win-loss 计数/portfolio_snapshots 快照仍是风控前状态。
- **FIX**: RC-REFRESH 段全量重读 canonical positions → 重算 cash/holdings_value/win_cnt/loss_cnt/tv/trp/drawdown
  → DELETE+INSERT 重写当日快照 → commit。
- **UNCHANGED**: Portfolio Risk Rule 阈值（15%回撤/减至50%）零改动；check_portfolio_drawdown_v2 未动。
- **TEST**: TestRiskRefresh（5项：无动作/全减/部分减快照一致性/多次幂等/源码 canonical 断言）。

### STEP 3 [High] J0-D Quality ERROR fail-safe（daily_decision_contract.py）
- **OLD**: quality_report 只展示不拦截；QUALITY_ERROR 不影响 BUY/ADD。
- **FIX**:
  - build_data_health_section 增加 `real_holdings_quality / quality_warning_count / quality_error_count / quality_flags`
  - 新增 get_real_holdings_quality_status() → QUALITY_VALID/WARNING/ERROR/UNKNOWN（局部语义）
  - classify_actions：ERROR → BUY/ADD 转 NO_TRADE（reason=REAL_HOLDINGS_QUALITY_ERROR, sizing BLOCKED）；
    WARNING 仅标注 quality_warning=True 不阻断；SELL/REDUCE/HOLD 完全不受影响。
- **UNCHANGED**: DecisionEngine 优先级/权限/组合规则零改动；quality ERROR 不等于全局 BROKEN
  （market_regime/portfolio 键保持 VALID）。
- **TEST**: TestQualityGate（11项：VALID/WARNING/ERROR/missing/BUY blocked/ADD blocked/SELL allowed/
  REDUCE allowed/WARNING 不阻断/data_health 字段/局部语义）。

### STEP 4 [Medium] J0-G Bitable 单一 reader（fetch_holdings_westock.py）
- **OLD**: 自行 lark-cli + split('|') 猜表头解析 schema —— 第二个 parser。
- **FIX**: read_holdings_codes() 复用 decision.real_portfolio_truth.get_daily_real_holdings()；
  reader 不可用时 RuntimeError(FAIL CLOSED)。westock enrichment 业务职责保留。
- **UNCHANGED**: to_westock/run_westock/market_cache 写入链路不变。
- **TEST**: TestBitableSingleReader（3项：无本地解析源码断言/统一 reader 复用/FAIL CLOSED）。

### STEP 5 [Medium] J0-H 当日 snapshot reuse（real_portfolio_truth.py）
- **OLD**: build_real_snapshot ≥6 个调用点每次触发 lark-cli；无缓存；时间点不一致风险。
- **FIX**: 进程内 DAILY_REAL_HOLDINGS_SNAPSHOT 缓存：
  - 当日首次真实读取（lark-cli ×1），后续 cached=True 复用
  - meta 含 captured_at/schema_version/source_hash(crypto hash)
  - 读取失败不缓存（不伪装 READY）；refresh=True 强制刷新；跨日自动失效
  - provenance.holdings_cache 写入 snapshot
- **UNCHANGED**: 显式注入 holdings 的 MANUAL_CONFIRMATION 路径不经过缓存；Real/Sim 隔离不变。
- **TEST**: TestDailySnapshotReuse（7项：首读一次/二次命中/多 caller 同快照/失败不缓存/
  meta 完整性/强制刷新/build_real_snapshot 记录 provenance）。

### STEP 6 [Low] MULTI_ACTION（double_monitor.py 今日交易 summary）
- **FIX**: 同 symbol 当日 BUY+SELL → 打印 `MULTI_ACTION:<codes>`；不改交易状态，纯显示分类。
- **TEST**: TestMultiAction（7项纯函数覆盖 BUY only/SELL only/同 symbol/多 symbol 排序/部分重叠/源码断言/不可变）。

### STEP 7 URGENT presentation 核对（只读，未改代码）
结论：Decision contract 无 presentation 字段（authority 在 engine）；presentation 是 delivery 层概念，
classify_message 已正确路由 FINAL_DECISION+URGENT→URGENT_MSG surface；stop-loss 决策经 save_snapshot
进 Daily 链 + actionable 独立推送，无第二 Final Owner。语义自洽，无需修改。

## 二、测试与运行证据

| 项 | 结果 |
|---|---|
| 新增回归测试 | 42 个（decision/test_j0b_integrity.py） |
| h2 测试适配 | _fake_bitable 增加 J0-H 缓存失效 + autouse 清理 fixture |
| 全量 decision suite | **362 passed / 0 failed**（baseline 320 + 42） |
| Production-equivalent run | SIM_MODE=test double_monitor.py exit=0 |
| Run 证据 | 模式=test ✅；Daily/Observation 报告生成 ✅；data_health.real_holdings_quality=WARNING(4 warnings, 0 errors) 实际生效 ✅；holdings_cache.provenance 写入且 cached=True ✅；Primary Delivery DUPLICATE_SUPPRESSED（幂等）✅；test db 当日交易 0 笔，无 EXECUTED ✅ |

## 三、Runtime Readback（2026-08-26 safe run）

```
DB ISOLATION: sim=simulation_test.db prod=simulation.db fallback_path_used=N/A wrong_db_access_count=0
VALUATION(test): cash=1,000,000 holdings_value=0 total_asset=1,000,000 drawdown=0.00%
QUALITY: status=WARNING warnings=4 errors=0 (Bitable 成本离群告警，如实透出)
HOLDINGS: source=FEISHU_BITABLE snapshot_id=real_20260826_27b21290 read_count=1(进程内) holdings_count=10
RISK: before=post_risk=summary_position_count=0 (无风控触发)
DECISION: total=0 (NO_SIGNAL 日) multi_action=0 urgent=0
DELIVERY: primary_status=DUPLICATE_SUPPRESSED duplicate_suppressed=True
EXECUTION: planned=0 executed=0 partial=0 rejected=0
OUTCOME: production_outcome_count=0
SYSTEM: runtime_status=OK
```

## 四、冻结核对

```
V1_RULES_CHANGED = NO        （stock_strategy_config.py / scan_doubling_potential.py 零 diff；
                              vol_ratio_min=2.7 / turnover_min=8000万 等参数原样）
REGIME_RULE_CHANGED = NO     （market_env_classifier 未触碰）
DECISION_RULE_CHANGED = NO   （decision/engine.py contract.py adapters.py portfolio.py real_sizing.py 零 diff）
RISK_RULE_CHANGED = NO       （risk_controller_v2.py 零 diff）
POSITION_SIZING_RULE_CHANGED = NO
AUTO_TRADING = OFF           （run 无 EXECUTED，executions 目录无新记录）
```

本阶段 git diff 范围（6 文件）：stock_opportunity_scan.py / double_monitor.py /
decision/daily_decision_contract.py / decision/real_portfolio_truth.py /
fetch_holdings_westock.py / decision/test_real_holdings_h2.py（适配）+ 新增 test_j0b_integrity.py。

## 五、Simulation Validation 基线说明

- PRE_FIX_LEGACY_RESULT：PROJECT.md 中 -34%（2026-08-11 口径）保留为 legacy 结果，不覆盖。
- J0A 已确认旧公式系统性低估净值；763c181 修复后公式恒等式成立。
- RECALCULATION_LIMITED：历史逐笔精确重算需完整流水审计（部分历史 sell_amount 曾被修正过），
  本阶段不做自动重算，不做 VALIDATION_BASELINE_RESET。
- POST_FIX_VALIDATION_PERIOD：以 2026-08-09 为 validation start 继续观察，
  是否重新定义由用户决定（VALIDATION_BASELINE_RESET_REQUIRED 仅在此报告为可选项）。

## 六、最终回答（22 问）

1. Critical DB fallback 彻底消失 ✅（FAIL CLOSED + 源码级回归测试锁定）
2. 生产 cron 仍可能访问错误 simulation.db？**否**
3. risk action 后 summary 读 canonical 最新状态？**是**（positions/cash/win-loss/快照全量重算）
4. portfolio snapshot 与 summary 一致？**是**（同一循环内同源计算 + 幂等验证）
5. quality ERROR fail-safe？**是**（BUY/ADD→NO_TRADE，reason=REAL_HOLDINGS_QUALITY_ERROR）
6. WARNING 可见不过度阻断？**是**（quality_warning 标注 + data_health 计数，不转 NO_TRADE）
7. Bitable 只剩一个 parser？**是**（fetch_holdings_westock 复用统一 reader）
8. 每日只读取一次真实持仓？**是**（当日缓存实测 read_count=1，cached=True 传播到报告）
9. 读取失败拒绝静默旧数据？**是**（失败不缓存 + 测试证明恢复后重读）
10. MULTI_ACTION 正确分类？**是**（summary-only 标注，不改交易状态）
11. URGENT presentation 正确？**是**（delivery 层路由验证通过，无需改动）
12. Real/Simulation 隔离？**是**（路径互斥测试 + safe run test db 零污染）
13. V1 参数 100% 未改？**是**（2.7/8000万等 grep + git diff 证实）
14. Regime 未改？**是**
15. DecisionEngine 规则未改？**是**（engine/contract/adapters 零 diff）
16. Portfolio Risk 规则未改？**是**（risk_controller_v2.py 零 diff）
17. 320 baseline tests 全部通过？**是**（362 全绿含 baseline）
18. 新增回归测试 42 个
19. Production-equivalent run 通过？**是**（exit=0 + 报告四件套 + 幂等投递）
20. 还有 Critical/High integrity issue？**无已知残留**；遗留 SECURITY_DEBT（emquant 明文密码，Broker API 禁改范围）
21. 可以正式冻结 V1？**可以**
22. 可以继续 Forward Validation？**可以**（PRODUCTION_INTEGRITY = READY，Validation = CONTINUE）

## 七、状态

```
PRODUCTION_INTEGRITY = READY
V1 = FROZEN
Validation = CONTINUE (2026-08-09 → 2026-09-05)
AUTO_TRADING = OFF
Production Outcome = 0
```

Phase 8-J0B 完成，立即停止。不进入策略开发阶段。
