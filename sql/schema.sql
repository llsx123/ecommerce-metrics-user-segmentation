-- Staging schema for the *raw* synthetic extract.
-- Deliberately permissive: no primary keys or foreign keys, because the raw layer
-- must be able to hold duplicate business keys and orphan references so that the
-- data-quality layer has something to detect. The strict schema lives in
-- schema_clean.sql and is applied to the cleaned database only.

CREATE TABLE IF NOT EXISTS users (
    customer_id        TEXT,
    customer_unique_id TEXT,
    zip_code_prefix    TEXT,
    city               TEXT,
    state              TEXT,
    signup_date        TEXT
);

CREATE TABLE IF NOT EXISTS products (
    product_id TEXT,
    category   TEXT,
    price      REAL,
    weight_g   INTEGER
);

CREATE TABLE IF NOT EXISTS orders (
    order_id     TEXT,
    customer_id  TEXT,
    order_status TEXT,
    purchase_ts  TEXT,
    delivered_ts TEXT,
    estimated_ts TEXT
);

CREATE TABLE IF NOT EXISTS order_items (
    order_id      TEXT,
    order_item_id INTEGER,
    product_id    TEXT,
    price         REAL,
    freight_value REAL
);

CREATE TABLE IF NOT EXISTS payments (
    order_id      TEXT,
    payment_seq   INTEGER,
    payment_type  TEXT,
    payment_value REAL
);

CREATE TABLE IF NOT EXISTS refunds (
    order_id     TEXT,
    refund_ts    TEXT,
    refund_value REAL,
    reason       TEXT
);

CREATE INDEX IF NOT EXISTS idx_orders_purchase_ts ON orders (purchase_ts);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders (customer_id);
CREATE INDEX IF NOT EXISTS idx_items_order ON order_items (order_id);
CREATE INDEX IF NOT EXISTS idx_items_product ON order_items (product_id);
CREATE INDEX IF NOT EXISTS idx_payments_order ON payments (order_id);
CREATE INDEX IF NOT EXISTS idx_refunds_order ON refunds (order_id);
