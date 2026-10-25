# 数据字典（合成电商数据集）

> 全部数据由 `src/ecom/generate.py` 以固定随机种子生成，**不含任何真实用户或交易信息**。
> 表结构参考公开的 Olist 巴西电商数据集形状，字段名与语义为本项目自定义。

## 1. 表结构

### users（用户主数据）

| 字段 | 类型 | 说明 | 质量约束 |
| --- | --- | --- | --- |
| customer_id | TEXT | 用户账号 ID（主键，分析粒度） | 唯一、非空 |
| customer_unique_id | TEXT | 自然人标识（本项目与账号 1:1，仅作扩展位） | 非空 |
| zip_code_prefix | TEXT | 邮编前 5 位 | 允许空 |
| city | TEXT | 城市（脱敏占位值） | 允许空 |
| state | TEXT | 州缩写 | 允许空 |
| signup_date | TEXT | 注册日期 `YYYY-MM-DD` | 允许空 |

### products（商品主数据）

| 字段 | 类型 | 说明 | 质量约束 |
| --- | --- | --- | --- |
| product_id | TEXT | 商品 ID（主键） | 唯一、非空 |
| category | TEXT | 品类（20 个类目，长尾分布） | 非空 |
| price | REAL | 标价（元，保留 2 位） | ≥ 0 |
| weight_g | INTEGER | 重量（克） | 允许空 |

### orders（订单头）

| 字段 | 类型 | 说明 | 质量约束 |
| --- | --- | --- | --- |
| order_id | TEXT | 订单号（主键） | 唯一、非空 |
| customer_id | TEXT | 下单用户，外键 → users | 非空、必须存在 |
| order_status | TEXT | `delivered / shipped / approved / invoiced / processing / canceled / unavailable` | 枚举 |
| purchase_ts | TEXT | 下单时间 `YYYY-MM-DD HH:MM:SS` | ≤ 快照时间 |
| delivered_ts | TEXT | 妥投时间，仅 delivered 有值 | ≥ purchase_ts |
| estimated_ts | TEXT | 承诺送达时间 | 允许空 |

### order_items（订单行）

| 字段 | 类型 | 说明 | 质量约束 |
| --- | --- | --- | --- |
| order_id | TEXT | 外键 → orders | 必须存在 |
| order_item_id | INTEGER | 订单内行号，从 1 开始 | `(order_id, order_item_id)` 唯一 |
| product_id | TEXT | 外键 → products | 必须存在 |
| price | REAL | 成交单价 | ≥ 0 |
| freight_value | REAL | 该行分摊运费 | ≥ 0 |

### payments（支付流水）

| 字段 | 类型 | 说明 | 质量约束 |
| --- | --- | --- | --- |
| order_id | TEXT | 外键 → orders | 必须存在 |
| payment_seq | INTEGER | 同一订单的支付序号（支持拆单支付） | `(order_id, payment_seq)` 唯一 |
| payment_type | TEXT | `credit_card / boleto / voucher / debit_card` | 枚举 |
| payment_value | REAL | 支付金额 | ≥ 0 |

### refunds（退款流水）

| 字段 | 类型 | 说明 | 质量约束 |
| --- | --- | --- | --- |
| order_id | TEXT | 外键 → orders | 必须存在 |
| refund_ts | TEXT | 退款时间 | 允许空 |
| refund_value | REAL | 退款金额 | ≥ 0，且该订单累计退款 ≤ 累计支付 |
| reason | TEXT | `return / damaged / late_delivery / goodwill / chargeback` | 允许空 |

## 2. 关系

```
users 1 ── n orders 1 ── n order_items n ── 1 products
                    │
                    ├── n payments
                    └── n refunds
```

## 3. 数据量（默认配置，seed=20240101）

| 表 | 行数（原始层） | 行数（清洗后） |
| --- | --- | --- |
| users | 12,005（含 5 条重复） | 12,000 |
| products | 1,200 | 1,200 |
| orders | 23,098 | 23,057 |
| order_items | 约 3.0 万（含注入缺陷） | 见 `outputs/pipeline_summary.json` |
| payments | 约 2.7 万 | 见 `outputs/pipeline_summary.json` |
| refunds | 约 900 | 见 `outputs/pipeline_summary.json` |

> 精确行数以 `outputs/pipeline_summary.json` 的 `cleaning` 字段为准（每次运行重新生成）。

## 4. 数据质量问题与处理

| 问题 | 检测方式 | 处理 |
| --- | --- | --- |
| 用户主键重复 | `GROUP BY customer_id HAVING COUNT(*) > 1` | 保留首行，其余丢弃 |
| 订单行重复 | `GROUP BY order_id, order_item_id` | 整单隔离（口径不可信） |
| 订单缺少用户 | `customer_id IS NULL` | 整单隔离 |
| 孤儿外键（用户/商品） | `LEFT JOIN ... IS NULL` | 整单隔离 |
| 负价格 / 负运费 | `price < 0 OR freight_value < 0` | 整单隔离 |
| 支付与订单行不平 | `ABS(SUM(payment) - SUM(price+freight)) > 0.01` | 整单隔离 |
| 退款大于支付 | `SUM(refund) > SUM(payment) + 0.01` | 整单隔离 |
| 未来日期 | `purchase_ts > snapshot` | 整单隔离 |
| 无支付的"有效状态"订单 | `NOT EXISTS payments` | 整单隔离 |

隔离清单由 `src/ecom/clean.py::quarantine_reasons` 生成，每单记录一条原因（可多原因拼接）。
