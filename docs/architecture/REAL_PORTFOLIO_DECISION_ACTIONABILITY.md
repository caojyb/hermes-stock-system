# REAL_PORTFOLIO_DECISION_ACTIONABILITY.md（Phase 7.5）

## 1. Real Portfolio Source

| 字段 | 来源 | 状态 |
|---|---|---|
| symbol | 飞书 Bitable | ✅ |
| quantity | 飞书 Bitable（“买入数量”字段） | ✅ |
| avg_cost | 飞书 Bitable（“买入价格”字段） | ✅ |
| current_price | 飞书 Bitable（“现价”字段） | ✅ |
| sector | 飞书 Bitable（“所属板块”字段） | ✅ |
| cash | 无自动来源 | ❌ DATA_UNAVAILABLE |
| total_asset | 无自动来源 | ❌ DATA_UNAVAILABLE |
| available_cash | 无自动来源 | ❌ DATA_UNAVAILABLE |
| historical_asset | 无自动来源 | ❌ 从快照序列积累 |

## 2. Asset Snapshot

`build_real_snapshot()` 支持两种模式：

### 自动模式（source=bitable）
- 从 Bitable 读取持仓明细
- cash/total_asset 为 None
- data_quality = PARTIAL
- 只能计算持仓市值相对占比

### 手动确认模式（source=MANUAL_CONFIRMATION）
- 显式注入 cash/total_asset
- 保存 provenance（entered_by, confirmation_note）
- 历史快照序列记录在 `real_portfolio_history.db`
- 支持 peak_asset / drawdown 计算

## 3. Cash

| 属性 | 值 |
|---|---|
| 来源 | MANUAL_CONFIRMATION（用户从平安证券输入） |
| 精度 | 元级别 |
| 新鲜度 | 人工提供，有 stale_after_hours 检查 |
| 失败行为 | 无 cash → BUY/ADD BLOCKED |

## 4. Total Asset

| 属性 | 值 |
|---|---|
| 公式 | total_asset = cash + holdings_value |
| 当 cash 未知时 | total_asset = UNKNOWN |
| 当 total_asset 未知时 | BUY/ADD BLOCKED，SELL/REDUCE 允许 |

## 5. Peak Asset

| 属性 | 值 |
|---|---|
| 定义 | peak_asset(T) = max(total_asset <= T) |
| 来源 | 从 `real_portfolio_history.db` 历史快照序列计算 |
| 无历史时 | peak_asset = None，status = UNKNOWN |
| 不使用 simulation peak | ✅ |

## 6. Drawdown

| 属性 | 值 |
|---|---|
| 公式 | drawdown = (peak_asset - total_asset) / peak_asset |
| 无历史峰值时 | drawdown = UNKNOWN |
| 不使用 simulation drawdown | ✅ |
| 不伪造成 0 | ✅ |

## 7. Freshness

| 状态 | 含义 |
|---|---|
| FRESH | 数据在 stale_after_hours 内 |
| EXPIRED | 数据过期，data_quality 降级为 STALE |
| UNKNOWN | 无时间戳 |

## 8. Manual Confirmation

| 字段 | 含义 |
|---|---|
| entered_by | 谁输入的（如 'caojy'） |
| confirmation_note | 确认来源说明（如 "平安证券截图"） |
| snapshot_id | 唯一快照 ID |
| confirmation_status | 确认状态 |
| source | MANUAL_CONFIRMATION |

## 9. Real Position Sizing

输入：
- total_asset
- current_market_value
- cash
- target_position_pct
- reference_price
- lot_size（默认 100）

输出：
- current_position_pct
- target_position_pct
- target_value
- target_quantity
- delta_value
- delta_quantity
- sizing_status：READY / PARTIAL / BLOCKED

## 10. Target Value

| 场景 | 公式 |
|---|---|
| 正常 | target_value = total_asset × target_position_pct |
| total_asset 未知 | target_value = None（BLOCKED） |

## 11. Target Quantity

| 场景 | 公式 |
|---|---|
| 正常 | target_quantity = floor(target_value / reference_price / lot_size) × lot_size |
| price 未知 | target_quantity = 0 |
| total_asset 未知 | target_quantity = None（BLOCKED） |

## 12. Delta

| 字段 | 含义 |
|---|---|
| delta_value | target_value - current_market_value |
| delta_quantity | floor(delta_value / reference_price / lot_size) × lot_size |
| delta > 0 | ADD / BUY |
| delta < 0 | REDUCE / SELL |

## 13. Permission

| Action | total_asset 未知 | 行为 |
|---|---|---|
| BUY | UNKNOWN | BLOCKED |
| ADD | UNKNOWN | BLOCKED |
| SELL | UNKNOWN | 允许 |
| REDUCE | UNKNOWN | 允许 |
| HOLD | UNKNOWN | 允许 |

## 14. Portfolio

Real Mode Portfolio Assessment 优先读取：
- Real Portfolio Snapshot（total_asset, cash, holdings, drawdown, position_count, sector_exposure）

禁止：
- Real Mode fallback → simulation portfolio_snapshots
- 如果真实数据缺失 → fail-safe（BUY/ADD BLOCKED）

## 15. Real/Simulation Isolation

| 维度 | Simulation | Real | 状态 |
|---|---|---|---|
| 数据源 | simulation.db | Bitable / MANUAL_CONFIRMATION | ✅ 隔离 |
| 持仓 | simulation.trades | Bitable records | ✅ 隔离 |
| 现金/总资产 | TOTAL_CAPITAL 固定 | cash/total_asset（真实或手动） | ✅ 隔离 |
| 交易执行 | record_simulation_execution | confirm_manual_execution | ✅ 隔离 |
| 输出文件 | simulation.db / decision/execution | decision/execution (source=MANUAL) | ✅ 隔离 |
| drawdown | portfolio_snapshots 历史峰值 | real_portfolio_history.db | ✅ 隔离 |

## 16. Data Gaps

| 数据 | 状态 | 影响 |
|---|---|---|
| cash | DATA_UNAVAILABLE（自动） | BUY/ADD 需手动输入 |
| total_asset | DATA_UNAVAILABLE（自动） | 绝对仓位% 需手动输入 |
| drawdown | UNKNOWN（无历史） | 组合回撤控制受限 |
| peak_asset | UNKNOWN（无历史） | drawdown 无法计算 |

## 17. Test Cases

| Case | 覆盖 |
|---|---|
| 1 | real portfolio asset snapshot |
| 2 | cash + holdings = total asset |
| 3 | total asset missing |
| 4 | peak calculation |
| 5 | real drawdown calculation |
| 6 | drawdown unknown |
| 7 | real position percentage |
| 8 | target value |
| 9 | target quantity |
| 10 | delta quantity |
| 11 | lot size |
| 12 | insufficient cash |
| 13 | total asset unknown blocks BUY |
| 14 | total asset unknown does not block SELL |
| 15 | real/simulation isolation |
| 16 | stale real portfolio |
| 17 | manual confirmation provenance |
| 18 | real portfolio replay context |
| 19 | drawdown permission integration |
| 20 | real sizing deterministic |

## 18. Known Limitations

1. **cash/total_asset 仍需人工输入**：当前 Bitable 不提供账户级现金/总资产，系统不猜测。
2. **drawdown 历史需积累**：从第一笔有效快照开始，历史不足时 = UNKNOWN。
3. **Real Position Sizing 依赖 reference_price**：若价格缺失，target_quantity = 0。
4. **SELL 数量在 total_asset 未知时不够精确**：系统仍允许卖出，但无法计算精确数量。
5. **lark-cli 404**：当前环境 BITABLE_APP_TOKEN 可能失效，生产环境需验证。
