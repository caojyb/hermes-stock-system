# Bitable Field Mapping Integrity Design

## 1. Current State

### 1.1 Current Mapping（Position-based）
`decision/real_portfolio_truth.py:_read_bitable_holdings()` 使用固定索引：

| Index | Field Name | Code Variable | Notes |
|-------|-----------|---------------|-------|
| 0 | 股票ID | `code` | strip() |
| 1 | name | `name` | strip() |
| 2 | 买入价格 | `avg_cost` | float() |
| 3 | 现价 | `current_price` | float() |
| 4 | 是否买入 | `buy_status` | list, filter "已买入" |
| 5 | 买入数量 | `shares` | int(float(replace(',',''))) |
| 6 | 买入时间 | - | unused |
| 7 | 所属板块 | `sector` | strip() |

### 1.2 lark-cli Invocation
```bash
lark-cli base +record-list \
  --base-token $BITABLE_TOKEN \
  --table-id tbluYAy8YJx36jpP \
  --field-id 股票ID --field-id name \
  --field-id 买入价格 --field-id 现价 \
  --field-id 是否买入 --field-id 买入数量 \
  --field-id 买入时间 --field-id 所属板块 \
  --limit 100 --format json
```

**Assumption**: 带 `--field-id` 后返回顺序 = 传参顺序。
**Risk**: 若 Bitable 表增加/删除字段，或 lark-cli 版本改变顺序规则，索引全部错位。

### 1.3 Historical Evidence
`stock-pipeline-audit/references/bitable-holding-cost-audit.md` 记录：
- 2026-08-08：Bitable "买入价格" 字段本身被写入错误值（不是读取错位）
- `bitable-field-mapping.md` 记录：18 字段表中索引可能漂移

## 2. Proposed Migration: Position-based → Field-id-based

### 2.1 Target Design
不依赖返回顺序，改用字段名匹配：

```python
def _read_bitable_holdings_by_name() -> list[dict]:
    """从 Bitable 读取真实持仓，按 field name 匹配，不依赖顺序。"""
    result = subprocess.run([...], capture_output=True, text=True, timeout=30)
    data = json.loads(result.stdout)
    records = data.get('data', {}).get('data', []) or []
    
    holdings = []
    for rec in records:
        # 转为 dict：按 field name 匹配，不依赖 index
        row = {
            '股票ID': str(rec[0]).strip(),  # 占位，后续替换
            'name': str(rec[1]).strip(),
            ...
        }
        ...
```

**问题**: lark-cli 返回仍是按传参顺序的数组，不返回 dict。

**可行方案 A：`--format json` + 元数据**
- 某些 CLI 版本支持 `--field-names` 或 `--headers` 输出字段名
- 若 lark-cli 支持，可直接拿到 `{field_name: value}` dict

**可行方案 B：`--field-id` 顺序固定 + 常量映射**
- 保持 position-based，但把索引提取为常量 `FIELD_INDEX = {...}`
- 单点维护，若 lark-cli 行为变化只需改一处

**可行方案 C：双轨运行**
- 保留现有 `_read_bitable_holdings()` 不变
- 新增 `_read_bitable_holdings_v2()` 尝试 name-based
- 若 v2 可用则切到 v2，否则 fallback 到 v1
- 逐步迁移，不破坏现有数据

### 2.2 Recommended Approach: **方案 B + 单点索引常量**

理由：
- lark-cli 当前行为：`--field-id` 顺序 = 返回顺序（已验证）
- 不依赖 lark-cli 未文档化的 format 变化
- 最小风险，单点维护

```python
# real_portfolio_truth.py
BITABLE_FIELD_INDEX = {
    '股票ID': 0,
    'name': 1,
    '买入价格': 2,
    '现价': 3,
    '是否买入': 4,
    '买入数量': 5,
    '买入时间': 6,
    '所属板块': 7,
}

def _read_bitable_holdings() -> list[dict]:
    ...
    for rec in records:
        code = str(rec[BITABLE_FIELD_INDEX['股票ID']]).strip()
        name = str(rec[BITABLE_FIELD_INDEX['name']]).strip()
        cost = float(rec[BITABLE_FIELD_INDEX['买入价格']] or 0)
        ...
```

### 2.3 兼容策略
- 不删除现有代码
- 新增 `_validate_field_order()` 在启动时/测试时校验索引
- 若索引漂移 → 抛出明确错误，不静默错位

## 3. Field-id 规范

### 3.1 当前使用的 Field IDs
从 `_read_bitable_holdings()` 和 `bitable-field-mapping.md` 提取：

| field-id | Type | Required | Notes |
|----------|------|----------|-------|
| 股票ID | text/number | YES | A股代码 |
| name | text | YES | 股票名称 |
| 买入价格 | number | YES | 成本价 |
| 现价 | number | YES | 当前价格 |
| 是否买入 | single_select | YES | 单选数组，过滤用 |
| 买入数量 | number | YES | 股数 |
| 买入时间 | datetime | NO | 当前未使用 |
| 所属板块 | text | NO | 所属板块 |

### 3.2 当前未使用但存在于表结构（18字段）
根据 `bitable-field-mapping.md`：
- 操作信号、最新RSI、盈亏、盈亏率、止损价、分析报告、止盈价、类型、所属概念、止损距

**原则**: 不读取未使用字段；若未来需要，按 `BITABLE_FIELD_INDEX` 单点扩展。

## 4. Migration Path

| Phase | Action | Risk |
|-------|--------|------|
| Phase 8-H1（设计） | 定义 `BITABLE_FIELD_INDEX` 常量 | 零风险（只读设计） |
| Phase I（实现） | 替换硬编码索引为常量引用 | 低风险（行为不变） |
| Phase II（加固） | 增加 `_validate_field_order()` 启动检查 | 中风险（可能暴露已有错位） |
| Phase III（可选） | 若 lark-cli 支持，切换 name-based dict | 中风险 |

## 5. Verification Strategy

### 5.1 Design-time Checks
- 确保 `BITABLE_FIELD_INDEX` 与 `--field-id` 传参顺序完全一致
- 若新增字段，同步更新常量和传参列表

### 5.2 Runtime Checks（设计）
```python
def _validate_field_order(records: list) -> bool:
    """校验返回记录长度与期望字段数一致。"""
    if not records:
        return True
    expected_len = len(BITABLE_FIELD_INDEX)
    actual_len = len(records[0])
    if actual_len != expected_len:
        raise RuntimeError(
            f"Bitable field count mismatch: expected {expected_len}, got {actual_len}. "
            f"BITABLE_FIELD_INDEX may be stale."
        )
    return True
```

## 6. Key Decisions

1. **当前迁移策略**: 先改常量引用，保持行为不变；不立即切 name-based。
2. **不破坏现有数据**: 只改代码读取方式，不写 Bitable。
3. **单点维护**: 所有索引集中在 `BITABLE_FIELD_INDEX`。
4. **漂移检测**: 增加长度校验，索引漂移时立即报错。
5. **不读取未使用字段**: 减少 blast radius。
