# 指标口径定义（Metric Definitions）

本文是**指标契约**：SQL（`sql/*.sql`）与 Pandas（`src/ecom/pandas_metrics.py`）都必须遵守这里的定义。
任何口径变更先改本文，再改代码，最后跑 `pytest` 与 `scripts/run_pipeline.py` 的交叉校验。

---

## 1. 基础概念

### 1.1 分析快照（snapshot）

`snapshot = YYYY-12-31 23:59:59`（默认 `2024-12-31 23:59:59`，见 `config.DataConfig.snapshot`）。

- 所有"截至当前"的口径（GMV、用户数、R 值）都以快照为准。
- `purchase_ts > snapshot` 的订单视为未来数据，直接隔离，不进入任何指标。

### 1.2 有效订单（valid order）

同时满足以下三条：

1. `order_status ∈ {approved, invoiced, processing, shipped, delivered}`
2. `purchase_ts ≤ snapshot`
3. 至少存在一条 `payments` 记录

**为什么这样定义：**

- 排除 `canceled` / `unavailable`：这些订单没有产生可确认的收入。
- 排除无支付订单：状态字段可能滞后于支付系统，缺少支付流水时无法确认收入。
- 未纳入 `delivered` 单一状态：履约中的已支付订单也应计入经营金额（口径可切换，见 §6 局限）。

### 1.3 金额口径

| 字段 | 含义 |
| --- | --- |
| `gross_gmv` | 有效订单的 `SUM(payment_value)`，即实际支付流水（含运费） |
| `refund_amount` | 有效订单在快照前发生的 `SUM(refund_value)` |
| `net_gmv` | `gross_gmv − refund_amount` |

**退款处理规则：**

- 只扣减**快照日前已发生**的退款，避免把未来退款算进当期。
- 退款按订单归属，不按退款发生月份归属（本项目选择"订单归属法"，更适合衡量订单质量）。
- 部分退款只扣减退款金额，不把订单整单剔除。
- `refund_amount > gross_gmv` 属于数据缺陷，该订单在清洗阶段被隔离（不会出现负净额订单）。

---

## 2. 核心指标

| 指标 | 公式 | 粒度 | 分母/过滤 |
| --- | --- | --- | --- |
| 支付订单数 `paid_orders` | `COUNT(DISTINCT order_id)` | 订单 | 有效订单 |
| 支付用户数 `paid_users` | `COUNT(DISTINCT customer_id)` | 用户 | 有效订单的下单用户 |
| 毛 GMV `gross_gmv` | `SUM(payment_value)` | 订单→汇总 | 有效订单 |
| 退款金额 `refund_amount` | `SUM(refund_value)` | 订单→汇总 | 有效订单，`refund_ts ≤ snapshot` |
| 净 GMV `net_gmv` | `gross_gmv − refund_amount` | 汇总 | 有效订单 |
| 客单价 `aov` | `net_gmv ÷ paid_orders` | 汇总 | 分母为非零有效订单数 |
| ARPU | `net_gmv ÷ paid_users` | 汇总 | 分母为有支付行为的用户数 |
| 退款率 `refund_rate` | `refund_amount ÷ gross_gmv` | 汇总 | 毛 GMV 为 0 时返回 NULL |
| 复购用户数 | 有效订单数 ≥ 2 的用户数 | 用户 | 有效订单 |
| 复购率 `repeat_rate` | `复购用户数 ÷ paid_users` | 汇总 | 分母只含有 ≥1 有效订单的用户 |

### 2.1 复购率的分母陷阱

- ❌ 常见错误：`复购用户数 ÷ 全部注册用户数` —— 会把从未下单的用户算进分母，严重低估复购。
- ✅ 本项目：`复购用户数 ÷ 有过有效订单的用户数`，并在文档中明确这是**观察窗口复购率**。
- 订单数按 `order_id` 去重：同一订单拆成多条支付流水不会重复计数。

### 2.2 客单价的分母陷阱

- ❌ `SUM(payment_value) ÷ COUNT(*)`（`COUNT(*)` 是支付流水行数，拆单支付会虚低客单价）。
- ✅ `net_gmv ÷ COUNT(DISTINCT order_id)`，且分母只含有效订单。

### 2.3 重复订单

- 订单行主键为 `(order_id, order_item_id)`；重复行会让 `SUM(price)` 重复计算。
- 清洗阶段对**含重复订单行的订单整单隔离**，而不是去重后继续计算 —— 去重会改变订单总额，导致支付对不平。

---

## 3. 品类指标

| 指标 | 公式 | 说明 |
| --- | --- | --- |
| 品类 GMV `item_gmv` | `SUM(order_items.price)` | **不含运费**，只统计有效订单 |
| 品类运费 `freight_revenue` | `SUM(order_items.freight_value)` | 与商品收入分列，避免混淆 |
| 品类订单数 `paid_orders` | `COUNT(DISTINCT order_id)` | 有效订单 |
| 品类客单价 `category_aov` | `item_gmv ÷ paid_orders` | 品类内订单均价 |
| 排名 `gmv_rank` | `RANK() OVER (ORDER BY item_gmv DESC)` | 并列时同名次 |
| 占比 `gmv_share` | `item_gmv ÷ SUM(item_gmv) OVER ()` | 分母为全部品类合计 |
| 累计占比 `cumulative_share` | 按 GMV 降序的累计窗口求和 ÷ 总 GMV | 用于帕累托分析 |

> 订单跨品类时，每个品类各计一次订单数（订单数不可跨品类相加）。

---

## 4. 用户指标（RFM 输入）

| 指标 | 公式 | 说明 |
| --- | --- | --- |
| `recency_days` | `snapshot_date − MAX(purchase_ts)` 的自然日差（向下取整） | 只用有效订单 |
| `frequency` | 有效订单数 | 按 `order_id` |
| `monetary` | `SUM(net)` | 净 GMV，与整体口径一致 |

---

## 5. 复购间隔

- 对每个用户按 `purchase_ts` 排序，`LAG` 取上一单时间；
- 相邻订单天数差（含小数）只在同用户内计算，首单无间隔；
- `avg_days_between_orders` 为所有间隔的算术平均；
- 同一天多单会产生 0 天间隔，属于正常现象（不剔除）。

---

## 6. 已知局限

1. **窗口复购率**：只统计观察窗口内的订单，无法反映跨年复购与生命周期价值。
2. **退款归属**：按订单归属月份扣减，不按退款发生月份；做财务对账时需切换到后者。
3. **状态口径**：`approved/invoiced/processing/shipped/delivered` 全部计入收入；若业务只认妥投收入，需改为 `delivered` 单一状态并重跑全部数字。
4. **多账号**：以 `customer_id` 为用户粒度，未做自然人合并。
5. **品类 GMV 不含运费**，与 GMV 口径不同，不能直接相加。
