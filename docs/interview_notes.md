# 项目一：面试复核笔记

> 用法：先自己口述答案，再对照"代码位置"。凡是答不出来的，回到对应文件读一遍并跑一次测试。

## Q1. 你的 GMV 口径是什么？为什么不用"所有订单金额总和"？

**答题要点**：有效订单 = 状态属于 5 个已支付状态 + 下单时间 ≤ 快照 + 至少一条支付流水；GMV 取
`SUM(payment_value)`；净 GMV 扣退款。

- 排除取消/不可用订单：这些不会形成收入。
- 排除无支付订单：状态可能滞后，没有流水无法确认收入。
- 用支付金额而不是订单行金额：支付流水才是资金视角，订单行价格可能与实际支付不一致（运费、优惠）。
- 价格与支付对不平的订单在清洗时被隔离，不会"带病"进入指标。

**代码位置**：`sql/overall_metrics.sql:9`（valid_orders CTE）、`src/ecom/pandas_metrics.py:30`（order_econ）。

**追问**：如果业务只认"妥投收入"怎么办？→ 把状态改成只保留 `delivered`，所有数字需要重跑，
口径文档 `docs/metric_definitions.md` §6 已声明这个开关。

## Q2. 退款怎么处理？为什么 AOV 用净 GMV？

**答题要点**：毛 GMV 与净 GMV 分开报告；AOV/ARPU 的分子用净 GMV，避免退款把客单价抬高；
退款只统计快照日前已发生的记录；部分退款只扣金额，不剔除整单；退款大于支付的订单是数据缺陷，整单隔离。

**代码位置**：`sql/overall_metrics.sql:24`（ref CTE）、`sql/overall_metrics.sql:40`（net 计算）、
`src/ecom/clean.py:63`（退款超额规则在 `QUARANTINE_RULES`）。

**边界**：如果做财务对账，应改为"退款按发生月份归属"，两种口径的月度曲线不同。

## Q3. 复购率的分母是什么？为什么这是最容易错的地方？

**答题要点**：分母是"观察窗口内有 ≥1 笔有效订单的用户数"，不是注册用户数；分子是"有效订单 ≥ 2 的单用户"；
订单按 `order_id` 去重，拆单支付不会重复计数。文档明确这是**窗口复购率**。

**代码位置**：`sql/overall_metrics.sql:44`（repeat CTE）、`tests/test_metrics_tiny.py:28`（手算 25%）。

**追问**：用 `customer_unique_id` 还是 `customer_id`？→ 本项目用账号粒度；合并自然人需要额外的身份映射表。

## Q4. 为什么 `COUNT(DISTINCT order_id)` 而不是 `COUNT(*)` 做订单数？

**答题要点**：`payments` 一个订单可能有多条流水（拆单支付），`COUNT(*)` 会按流水的行数计数，
导致订单数虚高、客单价虚低。测试数据里 o5 就有两条支付记录（50 + 15）。

**代码位置**：`sql/overall_metrics.sql:50`、`tests/test_metrics_tiny.py`（o5 拆单支付）。

## Q5. 你的 SQL 里用了哪些窗口函数？分别解决什么问题？

**答题要点**：

- `LAG(net_gmv)`：月度环比（`sql/monthly_metrics.sql:49`）；
- `RANK() OVER (ORDER BY item_gmv DESC)`：品类排名，并列同名次（`sql/category_metrics.sql:30`）；
- `SUM(...) OVER (ORDER BY ... ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)`：帕累托累计占比；
- `ROW_NUMBER() + LAG()` 分区：用户内订单序列与复购间隔（`sql/repeat_intervals.sql:8`）。

**追问**：`RANK` / `DENSE_RANK` / `ROW_NUMBER` 的区别？→ 并列时 RANK 跳号、DENSE_RANK 不跳号、
ROW_NUMBER 强制唯一。

## Q6. 复用 SQL 的 CTE 有什么好处？

**答题要点**：把"有效订单"定义收敛到一处（`valid_orders`），支付、退款、订单金额三层逐级聚合，
避免在 5 个指标里各写一遍过滤条件导致口径漂移；同时比嵌套子查询可读。

**代码位置**：`sql/overall_metrics.sql:9-46`。

## Q7. 数据质量做了哪些规则？怎么证明规则真的有效？

**答题要点**：10 条规则（重复主键、空用户、孤儿外键、负价格、支付对不平、退款超额、未来日期、
无支付订单等）；生成器**故意注入**每类缺陷并输出 manifest，测试断言"检测数量 == 注入数量"，
所以规则失效会直接让测试变红，而不是静默通过。

**代码位置**：`src/ecom/quality.py:19`（CHECKS 定义）、`src/ecom/generate.py:226`（注入）、
`tests/test_quality.py:18`（逐项比对）。

**边界**：检测"支付对不平"时排除了含负价格/重复行的订单，否则会重复计数；这条排除逻辑是测试保持稳定的关键。

## Q8. 为什么清洗要"整单隔离"而不是"删掉坏行"？

**答题要点**：坏行（负价格、重复行）会改变订单总额；删掉坏行后，订单行合计与支付金额仍然对不平，
指标会带着一个"看起来没问题"的错误数字。整单隔离保证每个进入指标层的订单都满足
`SUM(payment) ≈ SUM(price + freight)`，并且隔离清单可审计。

**代码位置**：`src/ecom/clean.py` 模块 docstring、`tests/test_cleaning.py:38`（清洗后 100% 对平）。

## Q9. SQL 和 Pandas 怎么交叉校验？容差怎么定？

**答题要点**：两个实现读同一份清洗库、共用同一份口径定义；金额容差 0.011（一分钱），
比率 1e-4，天数 0.02。比对器还会把"键只出现在一侧"标记为失败；另有一个测试故意篡改数值，
证明比对器不会假阳性通过。

**代码位置**：`src/ecom/reconcile.py:17`（容差）、`tests/test_sql_vs_pandas.py:60`（防假阳性测试）。

**追问**：为什么不做严格相等？→ 浮点求和顺序不同会产生 1e-10 级差异，用"一分钱"容差既覆盖精度问题，
又不会放过真实的口径偏差。

## Q10. RFM 为什么不用 NTILE？分层规则是什么？

**答题要点**：频率字段有大量并列（55% 用户只有 1 单），`NTILE(5)` 会任意切开并列值，导致结果不可复现、
SQL 与 Pandas 无法逐行对齐。改为"先算全局分位切点，再用确定性比较规则打分"；F 直接映射
`min(订单数, 5)`；分层是 R/F 的固定业务规则（champions / loyal / new_promising / ...）。

**代码位置**：`src/ecom/rfm.py:39`（cutpoints）、`src/ecom/rfm.py:70`（assign_segment）、
`sql/user_rfm.sql:52`（SQL 版 CASE）。

**局限**：分位切点是相对的，跨期比较要固定切点；分层不是聚类最优解，需要时可用 K-Means 对照。

---

## 自测清单（能答上来才算过关）

- [ ] 不看代码写出净 GMV、AOV、复购率的完整公式（含分母）
- [ ] 解释 `(order_id, order_item_id)` 为什么是订单行主键
- [ ] 手写一个 `LAG` 计算环比 + 一个 `RANK` 排名的 SQL
- [ ] 解释为什么"整单隔离"优于"删坏行"
- [ ] 说明注入缺陷 manifest 如何保证数据质量测试有效
- [ ] 解释 SQL/Pandas 校验的容差来源与防假阳性测试
- [ ] 说出 RFM 打分方向（R 越小分越高）与分层规则
