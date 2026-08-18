# 券商 API 对接方案调研报告

## 当前状态

系统当前已安装：无任何券商SDK（xtquant/ths_trader/easytrader 均未安装）
信号系统：全模拟，无真实成交反馈

## 可用方案对比

### 方案A：QMT（迅投）— 推荐

| 项目 | 详情 |
|:----|:------|
| SDK | `xtquant` Python 包 |
| 安装 | `pip install xtquant` |
| 支持券商 | 中信、国泰君安、华泰、招商、银河等 30+ |
| 开户门槛 | 入金 1-2 万（部分券商免门槛） |
| 功能 | 行情+交易+账户查询，支持限价单/市价单/算法单 |
| 文档 | 迅投官方文档，社区活跃 |
| 费用 | SDK 免费，按券商正常佣金 |
| 异步支持 | 支持 `xtdata` 异步行情 |
| 优点 | 国内量化交易的事实标准，Python 原生态 |
| 缺点 | 需开通券商 QMT 权限，部分券商有资金门槛 |

### 方案B：PTrade（恒生）— 备选

| 项目 | 详情 |
|:----|:------|
| SDK | `ths_trader` 第三方封装 |
| 支持券商 | 华泰、国金、东方财富等 |
| 开户门槛 | 通常 1-5 万 |
| 功能 | 交易+账户，部分支持策略回测 |
| 文档 | 恒生官方文档，社区较小 |
| 优点 | 部分券商免费提供 |
| 缺点 | SDK 非官方，接口不稳定，只支持 Windows |

### 方案C：easytrader（第三方）— 不推荐

| 项目 | 详情 |
|:----|:------|
| SDK | `easytrader` + `easyquotation` |
| 原理 | 模拟客户端操作（GUI自动化） |
| 稳定性 | 低，客户端更新即失效 |
| 速度 | 慢（秒级），不适合高频 |
| 推荐度 | ❌ 仅用于学习调试 |

## 推荐路径

```
第一阶段（当前）：模拟成交回执 + 滑点统计
第二阶段（1-2周）：安装 xtquant，对接 QMT 沙箱环境
第三阶段（2-4周）：真实资金对接，限价单 + 撤单重追
第四阶段（1-2月）：TWAP/VWAP 算法 + 多账户资金管理
```

## 对接方案（QMT）

### 所需步骤

1. 开通券商 QMT 权限（推荐国金/华泰，门槛低）
2. 安装 `xtquant`：`pip install xtquant`
3. 配置账户信息（无需明文密码，使用 token 认证）
4. 对接行情接口 `xtdata`（替代当前 akshare 数据源）
5. 对接交易接口 `xttrade`（下单、撤单、查询持仓）
6. 实现自动交易循环：信号生成 → 校验 → 下单 → 成交回报 → 记录

### 代码示例（QMT 下单）

```python
from xtquant import xtdata, xttrader
from xtquant.xttype import StockAccount

# 初始化
acc = StockAccount('您的资金账号', '券商类型')
trader = xttrader.XtQuantTrader('路径', session_id=1)
trader.start()

# 下单
order_id = trader.order_stock(
    acc, '600519', 'SH', 100, 188.5,  # 限价买入100股
    order_type=23,  # 限价单
    order_remark='Hermes信号'
)

# 查询成交
orders = trader.query_all_orders(acc)
```

### 风险控制（API 级别）

```python
# 每笔检查
if order_amount > max_single_order:
    reject('单笔金额超限')
if total_position > max_position:
    reject('总仓位超限')
if order_count_today > max_daily_orders:
    reject('当日下单次数超限')
```