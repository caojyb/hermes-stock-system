# Phase 8-K2 Closeout — User Output Clarification

> Baseline: hermes-stock-phase-8k1 / cd41a42 → 本阶段 tag: hermes-stock-phase-8k2
> 日期：2026-08-26

## 修改清单（仅 Presentation / Classification，零业务规则改动）

| 文件 | 改动 |
|---|---|
| `decision/presentation.py`（新增） | 六类层级标签常量 + `is_debug_line` + `sanitize_user_surface`（DEBUG 过滤，工程日志保留） |
| `decision/daily_decision_contract.py` | `format_human_readable`：每个 Action 段加 `【FINAL】` 标签（M-2） |
| `position_stop_loss_alert.py` | `format_decisions`：头部加 `【URGENT · FINAL】` 标签、Decision ID 字段规范化、输出经 sanitize（M-2/M-5） |
| `_k2_debug_shunt.py`（新增） | `print` 分流器：`[BRANCH]/[REPORT]/[PERSIST]/[DEBUG]` 写 `logs/double_monitor_debug.log`，stdout 用户面静默（M-5） |
| `double_monitor.py` | 头部 import `_k2_debug_shunt`（M-5，无逻辑改动） |
| `jobs.json`（deep-position-review prompt） | 输出格式指令改为分析性措辞，禁止命令式「减仓/买入」等（M-1） |

**未改动**：DecisionEngine / V1 / Regime / Permission / Portfolio / Stop-loss 规则 / Signal 生成 / Cron / Feishu channel。

## OUTPUT_CLARITY_MATRIX

| task | presentation | is_final | decision_id_req | actionable | timing | sizing | reason | debug_leak | ambiguity |
|---|---|---|---|---|---|---|---|---|---|
| Daily Decision | FINAL | ✅ | ✅ | ✅(with BLOCKED) | ✅ | ✅显式 | ✅ | 无 | 无 |
| Stop-loss/Urgent | URGENT·FINAL | ✅ | ✅ | ✅ | 当日 | 持仓可 | ✅ | 无 | 无 |
| Opportunity Push | SIGNAL | ❌ | ❌ | INFORMATIONAL | 盘中 | n/a | 评分 | 无 | 无 |
| Intraday | SIGNAL | ❌ | ❌ | INFORMATIONAL | 盘中 | n/a | n/a | 无 | 无 |
| Hot Sector | SIGNAL/INFO | ❌ | ❌ | INFORMATIONAL | 盘后 | n/a | n/a | 无 | 无 |
| News | INFO | ❌ | ❌ | INFORMATIONAL | 不定 | n/a | n/a | 无 | 无 |
| Sentiment/LHB | INFO | ❌ | ❌ | INFORMATIONAL | 盘后 | n/a | n/a | 无 | 无 |
| Deep Position Review | INFO（改后） | ❌ | ❌ | INFORMATIONAL | 日终 | n/a | 风险等级 | 无 | **已消除**（原 M-1） |
| Observation/Health | HEALTH | ❌ | ❌ | 非交易 | n/a | n/a | 数据状态 | 无 | 无 |
| double_monitor stdout | — | — | — | — | — | — | — | **已消除**（原 M-5 的 BRANCH） | — |

## 用户视角示例（合规校验）

- **场景1 正常持仓**：`【FINAL】HOLD 600001 T | Reason: HOLD_SIGNAL | Decision ID: ...`
- **场景2 高波动**：`Regime: 🔴 高波动 | Position Scale: 0.5 | NO_TRADE 原因: PERMISSION_HIGH_VOLATILITY`
- **场景3 止损**：`【URGENT · FINAL】🔴 600001 T → **SELL** | 原因: STOP_LOSS | Decision ID: ...`
- **场景4 机会信号**：`【SIGNAL · 非最终决策】301262 量比放大...`
- **场景5 Deep Review（无 Final）**：`风险等级: HIGH（减仓条件触发候选，建议进入 Decision Review）` —— 无「立即减仓」
- **场景6 数据异常**：`【HEALTH】real_asset_snapshot: PARTIAL | 数据缺失` —— 不输出 BUY
- **场景7 Debug**：`[BRANCH]` 仅落 `logs/double_monitor_debug.log`，不在 Feishu 正文

## 17 问速答

1. Deep Review Final-like 措辞？**已降级为分析性表述**
2. 无 Final Decision 仍有命令式？**否**
3. 所有 Final 标 FINAL？**是**
4. Urgent Final 标 URGENT？**是**
5. Signal 明确非 Final？**是（【SIGNAL · 非最终决策】）**
6. Information 明确非 Final？**是**
7. Health 明确非交易？**是**
8. Debug 完全隐藏于用户面？**是（stdout 0 个 BRANCH，完整落工程日志）**
9. 所有 Final 有 decision_id？**是**
10. Presentation 层新建 Decision？**否**
11. Account MISSING 时 BUY/ADD BLOCKED？**是（沿用 Daily Contract 既有语义，标签不变）**
12. 同 symbol FINAL/SIGNAL 区分？**是（标签显式）**
13. JSON/Feishu 一致？**是（同函数渲染）**
14. 仍会误解为交易指令？**否**
15. TRACEBACK/[BRANCH]/prompt 泄漏？**无（M-5 隔离）**
16. Delivery failure 不伪装成功？**未改（沿用 K0 验证的 no-fake-SENT 语义）**
17. Persistence failure 醒目？**是（继承 K1 的 🚨 FAILED 告警）**

K2_STATUS = COMPLETE。不进入 K3。

## 测试

- 新增 `decision/test_k2_presentation.py`：11 项（标签/DEBUG过滤/降级/无第二Owner等）
- 全量 decision suite：**432 passed / 0 failed**
