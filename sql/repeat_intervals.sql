-- Purchase cadence for repeat customers (window functions: LAG + ROW_NUMBER).
WITH valid_orders AS (
    SELECT o.order_id, o.customer_id, o.purchase_ts
    FROM orders o
    WHERE o.order_status IN ('approved', 'invoiced', 'processing', 'shipped', 'delivered')
      AND o.purchase_ts <= :snapshot
      AND EXISTS (SELECT 1 FROM payments p WHERE p.order_id = o.order_id)
),
sequenced AS (
    SELECT customer_id,
           purchase_ts,
           ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY purchase_ts, order_id) AS order_seq,
           LAG(purchase_ts) OVER (PARTITION BY customer_id ORDER BY purchase_ts, order_id) AS prev_purchase_ts
    FROM valid_orders
),
intervals AS (
    SELECT customer_id,
           order_seq,
           CAST(julianday(purchase_ts) - julianday(prev_purchase_ts) AS REAL) AS days_since_previous
    FROM sequenced
    WHERE prev_purchase_ts IS NOT NULL
)
SELECT ROUND(AVG(days_since_previous), 3)                       AS avg_days_between_orders,
       CAST(COUNT(*) AS INTEGER)                                AS repeat_intervals,
       CAST(COUNT(DISTINCT customer_id) AS INTEGER)             AS repeat_customers,
       ROUND(MIN(days_since_previous), 3)                       AS min_days,
       ROUND(MAX(days_since_previous), 3)                       AS max_days
FROM intervals;
