-- Category performance with ranking, revenue share and a Pareto (cumulative) share.
-- Category GMV uses line-item price only; freight is reported separately so that
-- product revenue and logistics revenue are never mixed.
WITH valid_orders AS (
    SELECT o.order_id
    FROM orders o
    WHERE o.order_status IN ('approved', 'invoiced', 'processing', 'shipped', 'delivered')
      AND o.purchase_ts <= :snapshot
      AND EXISTS (SELECT 1 FROM payments p WHERE p.order_id = o.order_id)
),
category_econ AS (
    SELECT p.category,
           SUM(i.price)                    AS item_gmv,
           SUM(i.freight_value)            AS freight_revenue,
           COUNT(DISTINCT i.order_id)      AS paid_orders,
           SUM(i.price + i.freight_value)  AS gross_revenue
    FROM order_items i
    JOIN valid_orders v ON v.order_id = i.order_id
    JOIN products p ON p.product_id = i.product_id
    GROUP BY p.category
)
SELECT category,
       ROUND(item_gmv, 2)            AS item_gmv,
       ROUND(freight_revenue, 2)     AS freight_revenue,
       paid_orders,
       ROUND(item_gmv / paid_orders, 2) AS category_aov,
       RANK() OVER (ORDER BY item_gmv DESC) AS gmv_rank,
       ROUND(item_gmv / SUM(item_gmv) OVER (), 4) AS gmv_share,
       ROUND(SUM(item_gmv) OVER (ORDER BY item_gmv DESC
                                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
             / SUM(item_gmv) OVER (), 4) AS cumulative_share
FROM category_econ
ORDER BY item_gmv DESC;
