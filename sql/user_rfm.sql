-- RFM scoring pushed into SQL.
--
-- Scores are assigned against **global quintile cut points** passed in as
-- parameters instead of NTILE(): frequency is heavily tied (most customers order
-- once) and NTILE would break those ties arbitrarily, making the SQL result
-- non-reproducible and impossible to cross-check against Pandas.
--
--   recency  : lower is better   (<= r1 -> 5 ... > r4 -> 1)
--   frequency: min(orders, 5)    (deterministic business mapping)
--   monetary : higher is better  (>= m4 -> 5 ... < m1 -> 1)
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
),
user_econ AS (
    SELECT customer_id,
           MAX(purchase_ts) AS last_purchase_ts,
           COUNT(*)         AS frequency,
           ROUND(SUM(net), 2) AS monetary
    FROM order_econ
    GROUP BY customer_id
),
scored AS (
    SELECT customer_id,
           last_purchase_ts,
           frequency,
           monetary,
           CAST(julianday(:snapshot) - julianday(last_purchase_ts) AS INTEGER) AS recency_days
    FROM user_econ
)
SELECT customer_id,
       last_purchase_ts,
       recency_days,
       frequency,
       monetary,
       CASE WHEN recency_days <= :r1 THEN 5
            WHEN recency_days <= :r2 THEN 4
            WHEN recency_days <= :r3 THEN 3
            WHEN recency_days <= :r4 THEN 2
            ELSE 1 END                                   AS r_score,
       CASE WHEN frequency >= 5 THEN 5 ELSE frequency END AS f_score,
       CASE WHEN monetary >= :m4 THEN 5
            WHEN monetary >= :m3 THEN 4
            WHEN monetary >= :m2 THEN 3
            WHEN monetary >= :m1 THEN 2
            ELSE 1 END                                   AS m_score
FROM scored
ORDER BY monetary DESC;
