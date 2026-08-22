# Real Holdings Data Quality Guard Design

## 1. Background
历史事件：`bitable-holding-cost-audit.md` 记录 2026-08-08 发现 Bitable "买入价格"字段被写入错误值（市值/盈亏金额误写为成本价）。

当前现状：
- `_read_bitable_holdings()` 不做任何数据质量校验
- `avg_cost/current_price/quantity` 异常值会直接进入 Decision 计算
- 异常成本导致 `position_stop_loss_alert.py` 误触发止损告警

## 2. Design Principles
- **只读检查**：不修改 Bitable 数据
- **不自动修正**：只产生 WARNING，不自动修正值
- **不阻断读取**：质量问题只标记，不阻止 holdings 继续使用
- **可审计**：所有告警记录可追溯

## 3. Quality Guard Schema

```yaml
holding_quality:
  symbol: "600588"
  name: "用友网络"
  checks:
    - field: "avg_cost"
      status: "OK" | "WARNING" | "ERROR"
      reason: "NONE" | "NON_POSITIVE" | "OUTLIER" | "MISSING"
      detail: "具体描述"
    - field: "current_price"
      status: "OK" | "WARNING" | "ERROR"
      reason: "NON_POSITIVE" | "OUTLIER" | "MISSING"
      detail: "具体描述"
    - field: "quantity"
      status: "OK" | "WARNING" | "ERROR"
      reason: "NON_POSITIVE" | "NON_INTEGER" | "MISSING"
      detail: "具体描述"
    - field: "cost_price_ratio"
      status: "OK" | "WARNING" | "ERROR"
      reason: "EXTREME_DEVIATION" | "MISSING"
      detail: "avg_cost/current_price ratio 异常"
  overall: "OK" | "WARNING" | "ERROR"
```

## 4. Check Rules

### 4.1 avg_cost
| Condition | Status | Reason |
|-----------|--------|--------|
| `avg_cost <= 0` | ERROR | NON_POSITIVE |
| `avg_cost is None` | WARNING | MISSING |
| `avg_cost > current_price * 10` | WARNING | OUTLIER（成本超现价10倍） |
| `avg_cost < current_price / 10` | WARNING | OUTLIER（成本不足现价1/10） |

**理由**：A股单日涨跌幅限制 20%，极端情况下成本与现价偏离 10 倍以上几乎不可能（除非除权除息未调整）。

### 4.2 current_price
| Condition | Status | Reason |
|-----------|--------|--------|
| `current_price <= 0` | ERROR | NON_POSITIVE |
| `current_price is None` | WARNING | MISSING |

### 4.3 quantity
| Condition | Status | Reason |
|-----------|--------|--------|
| `quantity <= 0` | ERROR | NON_POSITIVE |
| `quantity is None` | WARNING | MISSING |
| `quantity % 100 != 0` | WARNING | NON_INTEGER（A股最小单位100） |

### 4.4 cost/price ratio
| Condition | Status | Reason |
|-----------|--------|--------|
| `avg_cost / current_price > 10` | WARNING | EXTREME_DEVIATION |
| `avg_cost / current_price < 0.1` | WARNING | EXTREME_DEVIATION |
| `current_price / avg_cost > 10` | WARNING | EXTREME_DEVIATION |
| `current_price / avg_cost < 0.1` | WARNING | EXTREME_DEVIATION |

**排除场景**：
- `avg_cost == 0` 或 `current_price == 0` 时跳过 ratio 检查

### 4.5 sector（可选）
| Condition | Status | Reason |
|-----------|--------|--------|
| `sector is None or sector == ''` | WARNING | MISSING |
| `sector 不在已知板块列表` | WARNING | UNKNOWN_SECTOR |

**已知板块来源**：从 market_cache 或板块强度脚本动态收集，不硬编码。

## 5. Integration Points

### 5.1 _read_bitable_holdings() 返回增强
```python
def _read_bitable_holdings() -> list[dict]:
    ...
    holdings = []
    for rec in records:
        ...
        quality_checks = _check_holding_quality(code, name, cost, cur, shares, sector)
        holdings.append({
            'code': code,
            'name': name,
            'quantity': shares,
            'avg_cost': cost,
            'current_price': cur,
            'sector': sector,
            'quality': quality_checks,  # 新增
        })
    return holdings
```

### 5.2 build_real_snapshot() 聚合
```python
def build_real_snapshot(...):
    ...
    warning_count = sum(1 for h in holdings if any(c['status'] == 'WARNING' for c in h.get('quality', {}).get('checks', [])))
    error_count = sum(1 for h in holdings if any(c['status'] == 'ERROR' for c in h.get('quality', {}).get('checks', [])))
    
    if error_count > 0:
        data_quality = 'ERROR'
    elif warning_count > 0:
        data_quality = 'WARNING'
    ...
```

### 5.3 Daily Contract / Feishu / Observation
- 只展示 quality summary，不阻断数据流
- Feishu Primary 增加 `Data Quality: WARNING/ERROR` 标记
- Observation 若 `error_count > 0` → DEGRADED

## 6. Alerting Strategy

| Level | Count | Action |
|-------|-------|--------|
| WARNING | >0 | 标记 holdings quality，Feishu 显示 WARNING |
| ERROR | >0 | 标记 data_quality=ERROR，Observation DEGRADED，Feishu 显示 ERROR |
| ERROR | 全部持仓 | 标记 data_quality=MISSING，禁止 SELL/REDUCE |

## 7. Non-Goals
- 不自动修正 avg_cost（即使明显异常）
- 不自动删除/跳过异常持仓
- 不写回 Bitable
- 不触发自动交易
- 不修改 DecisionEngine

## 8. Future Enhancements
- 增加 `avg_cost vs 北向资金/主力资金` 交叉校验（需额外数据源）
- 增加 `current_price vs TDX 实时价` 交叉校验（需 westock/tdx）
- 增加 `quantity vs 历史最大持仓` 合理性检查
