-- Per-customer monetary value, recency and frequency on the cleaned database.
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
    SELECT v.customer_id,
           v.purchase_ts,
           pay.gross - COALESCE(ref.refunded, 0) AS net
    FROM valid_orders v
    JOIN pay ON pay.order_id = v.order_id
    LEFT JOIN ref ON ref.order_id = v.order_id
)
SELECT customer_id,
       MAX(purchase_ts)                     AS last_purchase_ts,
       COUNT(*)                             AS frequency,
       ROUND(SUM(net), 2)                   AS monetary,
       CAST(julianday(:snapshot) - julianday(MAX(purchase_ts)) AS INTEGER) AS recency_days
FROM order_econ
GROUP BY customer_id
ORDER BY monetary DESC;
