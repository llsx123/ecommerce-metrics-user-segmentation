-- Monthly revenue trend with month-over-month growth (window function LAG).
WITH valid_orders AS (
    SELECT o.order_id, o.customer_id, o.purchase_ts
    FROM orders o
    WHERE o.order_status IN ('approved', 'invoiced', 'processing', 'shipped', 'delivered')
      AND o.purchase_ts <= :snapshot
      AND EXISTS (SELECT 1 FROM payments p WHERE p.order_id = o.order_id)
),
pay AS (
    SELECT p.order_id, SUM(p.payment_value) AS gross
    FROM payments p JOIN valid_orders v ON v.order_id = p.order_id
    GROUP BY p.order_id
),
ref AS (
    SELECT r.order_id, SUM(r.refund_value) AS refunded
    FROM refunds r JOIN valid_orders v ON v.order_id = r.order_id
    GROUP BY r.order_id
),
order_econ AS (
    SELECT v.order_id,
           v.customer_id,
           v.purchase_ts,
           pay.gross AS gross,
           COALESCE(ref.refunded, 0) AS refunded,
           pay.gross - COALESCE(ref.refunded, 0) AS net
    FROM valid_orders v
    JOIN pay ON pay.order_id = v.order_id
    LEFT JOIN ref ON ref.order_id = v.order_id
),
monthly AS (
    SELECT SUBSTR(purchase_ts, 1, 7) AS month,
           COUNT(*) AS paid_orders,
           COUNT(DISTINCT customer_id) AS paid_users,
           SUM(gross) AS gross_gmv,
           SUM(refunded) AS refund_amount,
           SUM(net) AS net_gmv
    FROM order_econ
    GROUP BY SUBSTR(purchase_ts, 1, 7)
)
SELECT month,
       paid_orders,
       paid_users,
       ROUND(gross_gmv, 2)                                   AS gross_gmv,
       ROUND(refund_amount, 2)                               AS refund_amount,
       ROUND(net_gmv, 2)                                     AS net_gmv,
       ROUND(net_gmv / paid_orders, 2)                       AS aov,
       ROUND(net_gmv / paid_users, 2)                        AS arpu,
       ROUND(refund_amount / gross_gmv, 4)                   AS refund_rate,
       ROUND(LAG(net_gmv) OVER (ORDER BY month), 2)           AS prev_net_gmv,
       ROUND((net_gmv - LAG(net_gmv) OVER (ORDER BY month))
             / LAG(net_gmv) OVER (ORDER BY month), 4)         AS mom_growth
FROM monthly
ORDER BY month;
