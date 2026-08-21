# Trading Calendar Integrity Audit (Phase 8-G0 / Phase A)

> 本文件审计 Hermes 股票系统对「交易日」的判断是否正确，并修复 2026-08-21
> 误判为非交易日的基础设施缺陷。
> 本修复为 **CALENDAR_INFRA_FIX**，不修改任何交易规则 / V1 / 参数 / 策略。

---

## 1. 当前 Calendar Authority

- 修复前：`double_monitor.py` 用 `IS_TRADING_DAY = today_kline_count > 0`
  （用「当天有无 K 线」反推「是否交易日」）
- Authority：**无独立交易日历**；以 K 线存在性作为唯一判据
- Timezone：系统 `Asia/Shanghai`，`date.today()` 本地日期

## 2. 2026-08-21 Incident

- 2026-08-21 是**周五**，为 A 股正常交易日（非周末、非 2026 官方节假日）
- 系统输出：`⚠️ 今日 2026-08-21 非交易日（无当日 K 线），跳过买入信号扫描`
- 根因：2026-08-21 盘中触发时，`market-cache`（16:30）尚未刷新当日 K 线
  → `today_kline_count = 0` → 误判 NON_TRADING_DAY

## 3. Root Cause

`CALENDAR_SEMANTIC_CONFLICT`：
- 系统把「当天行情未刷新（MARKET_DATA_NOT_READY）」误当成「非交易日（NON_TRADING_DAY）」
- 两个不同概念被 `today_kline_count > 0` 一个布尔量混为一谈

诊断证据（2026-08-21 12:41 实测）：
- `date.today() = 2026-08-21 星期五`
- `klines MAX(date) = 2026-08-20`（market-cache 16:30 才刷新，盘中无当日）
- `2026-08-21 kline count = 0`、`2026-08-20 = 5004`
- → TRADING_DAY=YES，但 MARKET_DATA_READY=NO

## 4. Data Readiness Semantics（修复后）

三个独立状态（`trading_calendar.py`）：
- `TRADING_DAY`：日历工作日（weekday 判断）→ YES / NO / UNKNOWN
- `MARKET_DATA_READY`：当日 K 线是否刷新 → YES / NO / UNKNOWN
- `LATEST_KLINE_AVAILABLE`：数据库最新 K 线日期

修复后 2026-08-21：
- `trading_day = YES`
- `market_data_ready = NO`
- `semantic = DATA_NOT_READY`（不是 NON_TRADING_DAY）

## 5. Calendar / Data Separation

- **Authority Layer**：交易日 = 日历工作日（周一至五）
- **Market Data Layer**：行情是否刷新是另一回事
- **Decision Layer**：仅当 Trading Day=YES AND Data Ready=YES 才完整交易决策；
  否则进入 `DATA_NOT_READY`，不是 `NON_TRADING_DAY`

## 6. Multiple Authorities

| Source | Used By | Authority | Timezone | Failure Behavior |
|---|---|---|---|---|
| `today_kline_count>0`（修复前） | double_monitor | K线存在性 | local | fail 误判非交易日 |
| `trading_calendar.classify_trading_day`（修复后） | double_monitor | weekday 日历 | local | 区分交易日/数据就绪 |
| `pre_market_brief.is_trading_day` | pre_market_brief | 新浪加密日历+weekday | local | 接口失败→非周末视为交易日 |

→ 修复前存在 `MULTIPLE_CALENDAR_AUTHORITIES`（double_monitor 用 K 线，pre_market_brief 用新浪日历）。
本阶段只修复 double_monitor 生产路径。

## 7. Failure Behavior

- 修复前：交易日但数据未刷新 → 误标 NON_TRADING_DAY（误导，且隐藏真实状态）
- 修复后：交易日但数据未刷新 → `DATA_NOT_READY`（准确，buy 仍被抑制，fail-safe 保持）
- 日历模块异常 → 兜底回退到原 `today_kline_count>0`，不改变买入行为

## 8. Production Impact

- **行为**：`is_buy_eligible = weekday AND today_kline_count>0`，与原 `today_kline_count>0`
  在周末/节假日/数据未刷新时行为一致（buy 均被抑制）→ **不产生虚假今日买入信号**（fail-safe 保持）
- **语义**：消息不再误报「非交易日」，准确报告「交易日但数据未就绪」
- **风险降低**：消除了把数据延迟掩盖为「休市」的误导

## 9. Minimal Fix（CALENDAR_INFRA_FIX）

- 新建 `trading_calendar.py`：`classify_trading_day` / `is_buy_eligible`
- 修改 `double_monitor.py`：接入新语义，保留兜底
- **未改**：V1 / 参数 / Permission / Entry / Exit / Strategy / DecisionEngine / 交易规则

## 10. Regression Tests

`test_trading_calendar.py`（8 项）：
- 2026-08-21 expected OPEN（交易日）
- weekend CLOSED
- holiday CLOSED（weekday 兜底）
- calendar source failure UNKNOWN
- **market data missing != non-trading day（核心）**
- timezone
- date boundary
- buy eligibility 等价性

## 11. Final Status

**FIXED**（2026-08-21 交易日误判为基础设施缺陷，已完成最小修复）
- 修复后 `double_monitor.py` 在交易日+数据未就绪时输出 `DATA_NOT_READY`，不再误报非交易日
- 买入行为与修复前等价（fail-safe 保持），未改变任何交易规则
- 下一合法生产运行（收盘后 16:50）将自然验证：当日 K 线已刷新 → TRADING_DAY_READY

---

*Phase 8-G0 · Phase A · CALENDAR_INFRA_FIX · 审计+最小基础设施修复*
