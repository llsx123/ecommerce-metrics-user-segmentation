"""Assemble the Markdown analysis report from real pipeline artefacts."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import FIG_DIR, REPORT_DIR

METRIC_DEFINITIONS = [
    ("有效订单 (valid order)", "状态属于 approved/invoiced/processing/shipped/delivered，下单时间不晚于快照日，且至少有一条支付记录。"),
    ("GMV(毛)", "有效订单 payment_value 之和；反映支付流水口径。"),
    ("退款金额", "有效订单在快照前发生的 refund_value 之和。"),
    ("GMV(净)", "毛 GMV − 退款金额；AOV、ARPU 均使用净 GMV，避免退款虚增收入。"),
    ("支付订单数", "有效订单的订单号去重计数。"),
    ("支付用户数", "有效订单的 customer_id 去重计数（customer_id 为用户账号粒度，非 customer_unique_id）。"),
    ("客单价 AOV", "净 GMV ÷ 支付订单数；分母不含取消/未支付订单。"),
    ("ARPU", "净 GMV ÷ 支付用户数；分母只含当期有支付行为的用户。"),
    ("复购率", "有效订单数 ≥ 2 的用户数 ÷ 有效订单数 ≥ 1 的用户数；观察窗口内口径，非生命周期复购。"),
    ("退款率", "退款金额 ÷ 毛 GMV。"),
    ("品类 GMV", "订单行 price 之和（不含运费），只统计有效订单；运费单列。"),
]


def _md_table(frame: pd.DataFrame, columns: list[str], formats: dict[str, str] | None = None) -> str:
    formats = formats or {}
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    lines = [header, separator]
    for idx in range(len(frame)):
        row = frame.iloc[idx]
        cells = []
        for column in columns:
            value = row[column]
            if value is None or (isinstance(value, float) and pd.isna(value)):
                cells.append("—")
                continue
            if pd.api.types.is_integer_dtype(frame[column].dtype) and pd.notna(value):
                cells.append(str(int(value)))
                continue
            spec = formats.get(column)
            if spec and isinstance(value, (int, float)) and pd.notna(value):
                cells.append(format(value, spec))
            else:
                cells.append(str(value))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def build_report(
    overall: dict,
    monthly: pd.DataFrame,
    category: pd.DataFrame,
    rfm_summary: pd.DataFrame,
    dq_findings: pd.DataFrame,
    stats: dict,
    reconcile_summary: dict,
    sample_users: int,
    seed: int,
) -> Path:
    figures = {
        "monthly": FIG_DIR / "monthly_trend.png",
        "category": FIG_DIR / "category_pareto.png",
        "rfm": FIG_DIR / "rfm_segments.png",
        "payment": FIG_DIR / "payment_mix.png",
    }

    metric_table = pd.DataFrame(METRIC_DEFINITIONS, columns=["指标", "定义"])
    dq_table = dq_findings[["check", "table", "severity", "rows", "description"]].copy()

    top_categories = category.head(10).copy()
    top_categories["item_gmv"] = top_categories["item_gmv"].round(2)
    top_categories["gmv_share"] = (top_categories["gmv_share"] * 100).round(2)
    top_categories["cumulative_share"] = (top_categories["cumulative_share"] * 100).round(2)

    recent_months = monthly.tail(12).copy()
    recent_months["mom_growth"] = (recent_months["mom_growth"] * 100).round(2)

    rfm_table = rfm_summary.copy()
    rfm_table["user_share"] = (rfm_table["user_share"] * 100).round(2)
    rfm_table["monetary_share"] = (rfm_table["monetary_share"] * 100).round(2)

    report = f"""# 电商经营指标体系与用户画像分析

> **数据声明**：本项目使用**完全合成**的电商交易数据（Olist 风格表结构，随机种子 `{seed}`），
> 由 `src/ecom/generate.py` 生成，包含 {sample_users:,} 个用户。所有金额、用户、订单均为程序模拟，
> **不代表任何真实企业或平台的经营数据**。项目目的是演示指标口径设计、SQL 实现、数据质量治理与
> SQL/Pandas 交叉校验方法。

## 1. 核心经营指标

| 指标 | 数值 |
| --- | --- |
| 毛 GMV | {overall['gross_gmv']:,.2f} |
| 退款金额 | {overall['refund_amount']:,.2f} |
| 净 GMV | {overall['net_gmv']:,.2f} |
| 支付订单数 | {int(overall['paid_orders']):,} |
| 支付用户数 | {int(overall['paid_users']):,} |
| 复购用户数 | {int(overall['repeat_users']):,} |
| 复购率 | {overall['repeat_rate'] * 100:.2f}% |
| 客单价 AOV | {overall['aov']:,.2f} |
| ARPU | {overall['arpu']:,.2f} |
| 退款率 | {overall['refund_rate'] * 100:.2f}% |

## 2. 指标口径

{_md_table(metric_table, ["指标", "定义"])}

口径要点：

- **退款处理**：毛 GMV 与净 GMV 分开统计，AOV/ARPU 使用净 GMV；退款只统计快照日之前发生的记录。
- **重复订单**：订单行主键 `(order_id, order_item_id)` 去重；清洗阶段直接隔离含重复行的订单（见第 6 节）。
- **空值**：`customer_id` 为空的订单无法归属用户，直接隔离，不进入任何用户指标。
- **复购率分母**：只含观察窗口内有 ≥1 笔有效订单的用户，属于"窗口复购率"，不是生命周期复购率。

## 3. 月度趋势

![月度净 GMV 与客单价](figures/monthly_trend.png)

{_md_table(recent_months, ["month", "paid_orders", "paid_users", "gross_gmv", "refund_amount", "net_gmv", "aov", "mom_growth"], {"gross_gmv": ",.2f", "refund_amount": ",.2f", "net_gmv": ",.2f", "aov": ",.2f", "mom_growth": ".2f"})}

> `mom_growth` 为环比增速（%），由窗口函数 `LAG(net_gmv)` 计算；首月为空。

## 4. 品类结构

![品类 GMV 排名](figures/category_pareto.png)

{_md_table(top_categories, ["category", "item_gmv", "paid_orders", "category_aov", "gmv_share", "cumulative_share"], {"item_gmv": ",.2f", "category_aov": ",.2f", "gmv_share": ".2f", "cumulative_share": ".2f"})}

> `gmv_share` 与 `cumulative_share` 由 `RANK()` 与累计窗口求和计算，单位为百分比。

## 5. 用户画像（RFM）

![RFM 分层](figures/rfm_segments.png)

{_md_table(rfm_table, ["segment", "users", "user_share", "avg_recency_days", "avg_frequency", "avg_monetary", "monetary_share"], {"avg_recency_days": ".1f", "avg_frequency": ".2f", "avg_monetary": ",.2f", "user_share": ".2f", "monetary_share": ".2f"})}

RFM 打分规则（详见 `docs/rfm_segments.md`）：

- R：距今未购买天数，取全量用户 20/40/60/80 分位切点，天数越少分越高（5→1）。
- F：订单数直接映射，`min(订单数, 5)`，避免大量"仅 1 单"用户被 `NTILE` 任意切分。
- M：净 GMV，取 20/40/60/80 分位切点，金额越高分越高（1–5）。
- 分层：基于 R、F 两个维度的确定性业务规则（`src/ecom/rfm.py::assign_segment`）。

## 6. 数据质量

原始层注入并检测到的问题：

{_md_table(dq_table, ["check", "table", "severity", "rows", "description"])}

清洗策略：**整单隔离**（`src/ecom/clean.py`）。含空 `customer_id`、孤儿外键、未来日期、无支付、
支付对不平、退款大于支付、异常订单行（负价格 / 未知商品 / 重复行）的订单全部进入隔离清单，
不进入指标层。隔离后：原始订单 {stats['raw_orders']:,} 单，隔离 {stats['quarantined_orders']:,} 单，
保留 {stats['clean_orders']:,} 单。

## 7. SQL 与 Pandas 交叉校验

同一份清洗后数据分别用 SQL 与 Pandas 计算，逐项比对：

| 校验对象 | 结果 |
| --- | --- |
| 核心指标 | {reconcile_summary['overall']} |
| 月度指标 | {reconcile_summary['monthly']} |
| 品类指标 | {reconcile_summary['category']} |
| 用户级指标 | {reconcile_summary['users']} |
| 复购间隔 | {reconcile_summary['repeat']} |
| RFM 打分数值 | {reconcile_summary['rfm']} |

（"PASS" 表示差异在容差内：金额 0.011，比率 1e-4，天数 0.02。）

## 8. 可视化

![支付方式构成](figures/payment_mix.png)

## 9. 局限与后续

1. **合成数据**：订单分布、退款率、季节性均为人为设定，结论不可外推到真实业务。
2. **窗口复购率**：只观察 2024 年内行为，长周期复购需更长的历史数据。
3. **RFM 分层规则**：业务规则而非聚类结果，段位边界需要结合业务目标调整。
4. **用户口径**：以 `customer_id`（账号）为粒度，未合并同一自然人的多账号。
5. **后续**：可接入真实数仓（分区表 + 调度）、增加 cohort 留存与 LTV、对退款原因做细分归因。
"""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / "analysis_report.md"
    path.write_text(report, encoding="utf-8")
    return path
