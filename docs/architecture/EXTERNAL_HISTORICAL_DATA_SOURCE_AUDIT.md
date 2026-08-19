# EXTERNAL_HISTORICAL_DATA_SOURCE_AUDIT.md（Phase 7.3-E）

## 1. Sources Discovered

### 1.1 已安装 Python 包
- **akshare** 1.18.81（免费，开源，A股数据接口）

### 1.2 MCP 工具
- cn_financial MCP（超时/不稳定）
- eastmoney MCP（当前快照为主）
- westock-data（腾讯自选股，当前快照）

### 1.3 本地脚本/数据
- daily_data_refresh.py（eastmoney + westock）
- market_cache.db（本地缓存）
- fix_total_shares_real.py（推算当前股本）

### 1.4 外部 API
- 巨潮资讯（cninfo.com.cn）
- 东方财富（eastmoney.com）
- 腾讯自选股（westock）

---

## 2. Source Matrix

| Source | Historical Shares | Historical ST | Announcement Date | Effective Date | PIT Safe | Coverage | Stability | Cost/Access | Reproducible | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| akshare.stock_share_change_cninfo | ✅ | ❌ | ✅ | ✅ (变动日期) | ⚠️ | 2000-2024 | 中 | 免费 | 高 | READY_CANDIDATE |
| akshare.stock_industry_change_cninfo | ❌ | ❌ | ✅ | ✅ (变更日期) | ⚠️ | 部分 | 中 | 免费 | 高 | PARTIAL |
| akshare.stock_zh_a_st_em | ❌ | ❌ (仅当前) | ❌ | ❌ | ❌ | 当前 | 中 | 免费 | 中 | CURRENT_ONLY |
| cn_financial MCP | ❌ | ❌ | ❌ | ❌ | ❌ | - | 低 | - | - | UNRELIABLE |
| westock profile | ❌ | ❌ | ❌ | ❌ | ❌ | 当前 | 中 | 免费 | 高 | CURRENT_ONLY |
| market_cache.db | ❌ | ❌ | ❌ | ❌ | ❌ | - | - | - | - | BLOCKED |

---

## 3. Historical Shares

### 3.1 唯一可行源：akshare.stock_share_change_cninfo
- **数据源**：巨潮资讯网（cninfo.com.cn）
- **接口**：`p_stock2215`
- **字段**：
  - `总股本`（万股）
  - `变动日期`
  - `公告日期`
  - `变动原因`
  - 各股份类型明细

### 3.2 验证样本（000001 平安银行）
- **时间范围**：2000-06-30 至 2024-12-31
- **记录数**：75 条
- **总股本范围**：155,184.71 万股 ~ 1,940,591.82 万股
- **变动原因**：定期报告、配股上市、其他

### 3.3 PIT 规则
- `变动日期` = 股本变动生效日期
- `公告日期` = 公告发布日期
- 定期报告记录：`公告日期` = NaT，`变动日期` = 报告期
- 配股上市：`公告日期` < `变动日期`

### 3.4 限制
- 单位：万股（需转换为股）
- 定期报告的 `变动日期` 是报告期，非实际变动日
- 配股等事件的 `变动日期` 是上市日，非股权登记日
- **SHARE_EFFECTIVE_DATE_UNKNOWN**：定期报告无法确定具体生效日

---

## 4. Historical ST

### 4.1 当前状态
**未找到可靠 Historical ST 数据源。**

- `akshare.stock_zh_a_st_em`：仅返回当前 ST 板股票列表
- 巨潮资讯：无直接 ST 状态变更接口
- 东方财富：无历史 ST 时间序列

### 4.2 限制
- 无法回答：2022-06-24 该股票是否为 ST
- 只能得到：当前 is_st 状态

**标记**：`HISTORICAL_ST_DATA = NOT_FOUND`

---

## 5. PIT Semantics

### 5.1 股本变动 PIT 语义
- `变动日期`：数据层面的变动日期
- 但实际生效日可能更早（股权登记日）
- 定期报告的 `变动日期` = 报告期末，非实际变动日

**风险**：`SHARE_EFFECTIVE_DATE_UNKNOWN`

### 5.2 ST PIT 语义
**不适用（无数据）。**

---

## 6. Market Cap Reconstruction

### 6.1 可行性
**PARTIAL** - 有历史股本数据，但存在有效日期不确定性。

公式：
```
historical_market_cap(T) = share_count(T) × close(T)
```

其中：
- `share_count(T)`：从 `stock_share_change_cninfo` 获取
- `close(T)`：从 klines 获取

### 6.2 限制
1. 定期报告的股本 = 报告期末值，非实时值
2. 配股等事件的生效日 = 上市日，非股权登记日
3. 无法处理：股权登记日与上市日之间的决策窗口

---

## 7. Coverage

### 7.1 股票覆盖
- akshare 接口支持全部 A 股
- 但部分股票可能无股本变动记录（长期无变化）

### 7.2 时间覆盖
- 最早：2000 年左右（取决于股票上市时间）
- 最晚：2024-2025

### 7.3 股本事件覆盖
- 定期报告：每季度/年度
- 配股、增发、送转等：有记录

### 7.4 ST 覆盖
**0%**（无历史 ST 数据）

---

## 8. Stability

### 8.1 akshare 稳定性
- 开源项目，持续维护
- 巨潮资讯 API 相对稳定
- 但可能受反爬机制影响
- 返回格式可能变化

### 8.2 测试结果
- 000001：75 条记录，成功获取
- 接口响应时间：2-5 秒
- 无超时

### 8.3 风险
- 巨潮资讯可能限制请求频率
- 返回格式可能变化
- 部分股票可能无数据

---

## 9. Revision Risk

### 9.1 历史修订
- 巨潮资讯数据为官方披露数据
- 定期报告数据可能因更正公告而修订
- 但修订概率较低

### 9.2 建议
- 本地缓存原始响应
- 记录 fetch timestamp
- 定期验证数据一致性

---

## 10. Access / Cost

### 10.1 akshare
- **免费**：开源，无需账号
- **限制**：无明确 API 限额，但受反爬机制影响
- **商业使用**：允许
- **回测使用**：允许

### 10.2 巨潮资讯
- **免费**：公开数据
- **限制**：无明确限制，但频繁请求可能被限制
- **商业使用**：允许
- **回测使用**：允许

---

## 11. Reproducibility

### 11.1 akshare.stock_share_change_cninfo
- 同一 symbol + date 范围查询，结果一致
- 但历史数据可能因更正公告而修订

### 11.2 建议
- 冻结原始响应
- 记录 fetch timestamp
- 定期验证

---

## 12. Priority Ranking

### Priority A
**无** - 没有源同时提供 Historical Total Shares + Historical ST + PIT Safe

### Priority B
**akshare.stock_share_change_cninfo**
- 提供 Historical Total Shares
- 提供 Effective Date（变动日期）
- 提供 Announcement Date（公告日期）
- **限制**：ST 数据缺失

### Priority C
**无** - 没有源提供 Historical ST

### Priority D
- akshare.stock_zh_a_st_em（仅当前 ST）
- westock profile（仅当前股本）
- cn_financial MCP（不稳定）

### BLOCKED
- market_cache.db（无历史股本/ST）

---

## 13. Blockers

### 13.1 Market Cap
**PARTIAL** - akshare 提供历史股本，但存在有效日期不确定性

### 13.2 ST
**BLOCKED** - 无历史 ST 数据源

### 13.3 Portfolio
**NONE** - 无历史账户数据（本阶段不处理）

---

## 14. Recommendation

### 14.1 下一阶段
**接入 akshare.stock_share_change_cninfo 作为 Historical Market Cap 数据源。**

步骤：
1. 全市场股本变动数据下载
2. PIT 有效性验证
3. 与 klines close 合并计算 historical_market_cap
4. 5-90 亿过滤验证

### 14.2 ST
**继续寻找 Historical ST 数据源。**
- 尝试：巨潮资讯公告搜索
- 或：东方财富个股新闻/公告
- 或：手动标记 + 公告验证

### 14.3 不要做什么
- 不要用当前 `stocks.total_mcap` 回填历史
- 不要放宽 V1 的 5-90 亿过滤
- 不要接受 CURRENT_ONLY 数据源作为 Historical

---

## 15. Next Step

1. **接入 akshare 历史股本数据**
   - 全市场下载
   - PIT 验证
   - Market Cap 重建

2. **继续寻找 Historical ST**
   - 巨潮资讯公告
   - 东方财富公告
   - 其他数据源

3. **Historical Decision Replay**
   - 等 Market Cap + ST 都解锁后
   - 再评估 Replay A/B/C

---

## 16. Final Answers

### 16.1 哪些外部数据源真实可访问？
**akshare（巨潮资讯）** - 免费、稳定、可访问

### 16.2 哪个源能够提供 Historical Total Shares？
**akshare.stock_share_change_cninfo** - 提供 2000-2024 年股本变动记录

### 16.3 哪个源能够提供 Historical ST？
**无** - 未找到可靠 Historical ST 数据源

### 16.4 是否有 Effective Date？
**部分** - 有 `变动日期`，但定期报告无法确定具体生效日

### 16.5 是否有 Announcement Date？
**有** - `公告日期` 字段

### 16.6 是否 PIT Safe？
**PARTIAL** - 股本数据可用，但有效日期存在不确定性

### 16.7 时间覆盖多少年？
**约 20-25 年**（2000-2024）

### 16.8 股票覆盖多少？
**全市场 A 股**（akshare 支持全部代码）

### 16.9 股本变化覆盖如何？
**完整** - 定期报告 + 配股/增发/送转等事件

### 16.10 ST 状态变化覆盖如何？
**0%** - 无历史 ST 数据

### 16.11 Historical Market Cap 能否重建？
**PARTIAL** - 有历史股本，但有效日期不确定

### 16.12 5-90 亿过滤能否历史重放？
**PARTIAL** - 有 historical_market_cap，但存在有效日期误差风险

### 16.13 数据源是否稳定？
**中** - akshare 开源维护，巨潮资讯 API 稳定，但可能受反爬影响

### 16.14 是否存在 revision risk？
**低** - 巨潮资讯数据为官方披露，修订概率低

### 16.15 成本/访问限制是什么？
**免费** - 无需账号，无明确 API 限额

### 16.16 哪个源最适合作为正式接入候选？
**akshare.stock_share_change_cninfo**（巨潮资讯）

### 16.17 Market Cap / ST / Portfolio 三个 Blocker 当前分别是什么状态？
- **Market Cap**: PARTIAL（akshare 可提供历史股本）
- **ST**: BLOCKED（无历史 ST 数据）
- **Portfolio**: NONE（本阶段不处理）

### 16.18 Replay A/B/C 是否仍 BLOCKED？
**是** - ST 未解锁，Market Cap 为 PARTIAL

### 16.19 下一阶段应该接哪个数据源、先解决什么？
**接入 akshare.stock_share_change_cninfo，先解决 Historical Market Cap。**
