# HISTORICAL_ST_RECONSTRUCTION.md（Phase 7.3-H）

## 1. V1 ST Semantics

### 1.1 过滤字段
- **字段**：`stocks.is_st`
- **过滤条件**：`is_st IS NULL OR is_st = 0`
- **代码位置**：`scan_doubling_potential.py:53`
- **语义**：排除 ST 股票和 is_st 为 NULL 的股票

### 1.2 当前状态
- `is_st = 1`：0 条（当前无 ST 股票）
- `is_st = 0`：5,187 条（正常股票）
- `is_st IS NULL`：0 条

### 1.3 V1 ST_FILTER_SEMANTICS
```python
V1_ST_FILTER_SEMANTICS = {
    'field': 'is_st',
    'exclude': ['ST', '*ST', 'is_st = 1', 'is_st IS NULL'],
    'include': 'NORMAL (is_st = 0)',
}
```

## 2. Source Inventory

### 2.1 已安装 Python 包
- **akshare** 1.18.81（免费，开源）

### 2.2 可用接口
| 接口 | 类型 | ST 历史 | 生效日期 | 状态 |
|---|---|---|---|---|
| `stock_zh_a_st_em` | 当前 ST 板 | ❌ | ❌ | CURRENT_ONLY |
| `stock_info_change_name` | 曾用名 | ⚠️ 间接 | ❌ | PARTIAL |
| `stock_notice_report` | 当日公告 | ⚠️ 需搜索 | ❌ | PARTIAL |
| `stock_zh_a_stop_em` | 暂停上市 | ❌ | ❌ | UNRELIABLE |
| cn_financial MCP | 不稳定 | ❌ | ❌ | UNRELIABLE |
| market_cache.db:stocks.is_st | 当前快照 | ❌ | ❌ | CURRENT_ONLY |

## 3. ST Event Model

### 3.1 HistoricalSTEvent（理想模型）
```python
@dataclass
class HistoricalSTEvent:
    symbol: str
    old_status: str  # NORMAL / ST / *ST
    new_status: str  # NORMAL / ST / *ST
    effective_date: date | None
    announcement_date: date | None
    event_date: date | None
    source: str
    source_query_time: str
    confidence: float
    date_quality: str  # KNOWN / APPROXIMATE / UNKNOWN
    limitation_codes: list[str]
```

### 3.2 实际可用数据
**无法建立 HistoricalSTEvent** — 无结构化历史 ST 状态变更事件。

## 4. Effective Date

### 4.1 stock_info_change_name
- **字段**：只有 `name`（曾用名列表）
- **无**：effective_date、announcement_date、event_date
- **标记**：`ST_EFFECTIVE_DATE_UNKNOWN`

### 4.2 stock_notice_report
- **字段**：公告标题、公告日期
- **可搜索**：ST、风险警示、退市等关键词
- **但**：需逐日查询，无结构化状态变更事件
- **标记**：`ST_EFFECTIVE_DATE_UNKNOWN`

## 5. Announcement Date

### 5.1 stock_notice_report 提供公告日期
- 格式：YYYY-MM-DD
- 但：仅提供当日公告列表，无结构化 ST 状态变更事件
- 无法自动识别哪些公告导致 ST 状态变更

## 6. Timeline Reconstruction

### 6.1 当前能力
**无法重建 Historical ST Timeline。**

### 6.2 原因
1. 无历史 ST 状态时间序列接口
2. 曾用名接口无生效日期
3. 公告接口需逐日查询且无结构化状态变更

## 7. Initial State

### 7.1 问题
如果某股票在历史最早记录时已经是 ST：
- 无法获得初始状态
- 标记：`ST_INITIAL_STATE_UNKNOWN`

## 8. ST / Un-ST

### 8.1 正向变化（NORMAL → ST）
- 无法自动检测
- 需人工分析公告

### 8.2 反向变化（ST → NORMAL）
- 无法自动检测
- 需人工分析公告

## 9. Name Evidence

### 9.1 可用性
`stock_info_change_name` 提供曾用名，包含 ST 标记：
- 000668：S武石油 → 荣丰控股 → *ST荣控 → 荣丰控股
- 000587：*ST光明 → ST光明 → SST光明 → ... → 金叶珠宝 → *ST金洲 → 金洲3
- 600255：鑫科材料 → 梦舟股份 → *ST梦舟 → *ST鑫科 → 鑫科材料

### 9.2 限制
- **无生效日期** — 无法确定何时变为 ST
- **无退市日期** — 无法确定何时解除 ST
- **只能作为 NAME_STATUS_EVIDENCE** — 不能作为 PIT_SAFE_ST

## 10. PIT Rules

### 10.1 严格 PIT
- 仅允许 `KNOWN` 状态参与严格 Replay
- **当前 KNOWN = 0%** — 无历史 ST 数据

### 10.2 研究 Replay
- 允许 `KNOWN + APPROXIMATE`
- **当前 APPROXIMATE = 0%** — 无结构化状态变更事件

### 10.3 禁止
- 禁止使用当前 `stocks.is_st` 回填历史
- 禁止使用曾用名作为 PIT_SAFE_ST（无生效日期）

## 11. Coverage

### 11.1 股票覆盖
- **0%** — 无历史 ST 数据
- 当前 `stocks.is_st = 1` 的股票：0 只

### 11.2 时间覆盖
- **N/A** — 无历史 ST 数据

### 11.3 状态覆盖
- ST：N/A
- *ST：N/A
- NORMAL：N/A
- 解除 ST：N/A

## 12. Quality Model

| Quality | 定义 | 当前状态 |
|---|---|---|
| KNOWN | 有明确生效时间 | 0% |
| APPROXIMATE | 有时间窗口 | 0% |
| UNKNOWN | 无法判断 | 100% |

## 13. Adapter

### 13.1 无法建立 Historical ST Adapter
- 无结构化历史 ST 数据源
- 无生效日期
- 无法做 PIT 查询

## 14. Replay Impact

### 14.1 Historical ST 状态
**BLOCKED** — 无历史 ST 数据源

### 14.2 Replay A/B/C 影响
- **Replay A**：BLOCKED（ST 未解锁）
- **Replay B**：BLOCKED（ST 未解锁）
- **Replay C**：BLOCKED（ST 未解锁）

### 14.3 核心 Blocker
Historical ST = BLOCKED 是 Replay A/B/C 的核心硬 Blocker 之一。

## 15. Known Limitations

1. **无历史 ST 状态时间序列** — 无法做严格 PIT 查询
2. **曾用名无生效日期** — 只能作为间接证据，不能作为 PIT Truth
3. **公告需逐日查询** — 无法批量获取历史 ST 状态变更
4. **初始状态未知** — 无法确定股票最早历史时的 ST 状态
5. **ST → NORMAL 无法自动检测** — 只能通过人工分析公告
6. **2025-2026 覆盖未知** — 无历史 ST 接口

## 16. Recommendation

### 16.1 下一阶段
**继续寻找 Historical ST 数据源。**

可选方向：
1. **巨潮资讯公告全文搜索** — 批量下载历史公告，人工标注 ST 状态变更
2. **东方财富公告接口** — 类似巨潮，但需逐日查询
3. **专业数据供应商** — Wind、Choice、同花顺 iFinD（付费）

### 16.2 不做
- 不要用曾用名自动推断 ST 状态（无生效日期）
- 不要用当前 is_st 回填历史
- 不要实现不完整的 Historical ST Adapter

### 16.3 短期替代方案
如果必须进行 Replay：
- **方案 A**：只 Replay 已知非 ST 的股票（保守，漏掉 ST 股票）
- **方案 B**：人工标注关键 ST 时点（不 scalable）
- **方案 C**：等待专业数据源接入

## 17. Final Answers

### 17.1 哪些外部数据源真实提供 Historical ST？
**无。** 仅找到：
- `stock_zh_a_st_em` — 当前 ST 板（非历史）
- `stock_info_change_name` — 曾用名（间接证据，无生效日期）
- `stock_notice_report` — 当日公告（需逐日查询，无结构化事件）

### 17.2 V1 实际 ST 过滤语义？
`stocks.is_st`，排除 `is_st = 1` 和 `is_st IS NULL`。

### 17.3 是否存在 historical status event？
**否** — 无结构化历史 ST 状态变更事件接口。

### 17.4 是否有 effective_date？
**否** — 所有接口均无 ST 生效日期字段。

### 17.5 是否有 announcement_date？
- `stock_notice_report` 有公告日期，但仅当日公告，无结构化 ST 状态变更
- `stock_info_change_name` 无公告日期

### 17.6 PIT Safe 吗？
**否** — 无 PIT 安全的历史 ST 数据源。

### 17.7 时间覆盖多少年？
**N/A** — 无历史 ST 数据。

### 17.8 股票覆盖多少？
**0%** — 无历史 ST 数据。

### 17.9 ST → NORMAL 能否恢复？
**否** — 无法自动检测反向变化。

### 17.10 NORMAL → ST 能否恢复？
**否** — 无法自动检测正向变化。

### 17.11 多次 ST 能否恢复？
**否** — 无法追踪 ST 状态变化。

### 17.12 初始状态能否确定？
**否** — 标记为 `ST_INITIAL_STATE_UNKNOWN`。

### 17.13 2025-2026 是否覆盖？
**否** — 无历史 ST 接口。

### 17.14 数据稳定性如何？
**不适用** — 无历史 ST 数据源。

### 17.15 是否存在 revision risk？
**不适用** — 无历史 ST 数据源。

### 17.16 Historical ST 是否可以从 BLOCKED 提升？
**否** — 保持 **BLOCKED**。

### 17.17 Replay A/B/C 是否发生变化？
**否** — 仍全部 **BLOCKED**。

### 17.18 Portfolio 是否仍 NONE？
**是** — 保持 `PORTFOLIO_REPLAY_MODE = NONE`。

### 17.19 下一阶段最值得做什么？
1. **继续寻找 Historical ST 数据源**（最高优先级）
2. **考虑专业数据供应商**（Wind、Choice、同花顺 iFinD）
3. **或接受 ST 作为 Replay 的永久 Blocker**（仅 Replay 非 ST 股票）
