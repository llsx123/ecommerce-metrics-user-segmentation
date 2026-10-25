-- Strict schema for the *cleaned* database.
-- Enforces the business keys used by the metric layer, so any cleaning bug that
-- lets a duplicate or orphan row through fails loudly instead of silently
-- inflating revenue.

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS payments;
DROP TABLE IF EXISTS refunds;

CREATE TABLE users (
    customer_id        TEXT PRIMARY KEY,
    customer_unique_id TEXT NOT NULL,
    zip_code_prefix    TEXT,
    city               TEXT,
    state              TEXT,
    signup_date        TEXT
);

CREATE TABLE products (
    product_id TEXT PRIMARY KEY,
    category   TEXT NOT NULL,
    price      REAL NOT NULL CHECK (price >= 0),
    weight_g   INTEGER
);

CREATE TABLE orders (
    order_id     TEXT PRIMARY KEY,
    customer_id  TEXT NOT NULL REFERENCES users (customer_id),
    order_status TEXT NOT NULL,
    purchase_ts  TEXT NOT NULL,
    delivered_ts TEXT,
    estimated_ts TEXT
);

CREATE TABLE order_items (
    order_id      TEXT NOT NULL REFERENCES orders (order_id),
    order_item_id INTEGER NOT NULL,
    product_id    TEXT NOT NULL REFERENCES products (product_id),
    price         REAL NOT NULL CHECK (price >= 0),
    freight_value REAL NOT NULL CHECK (freight_value >= 0),
    PRIMARY KEY (order_id, order_item_id)
);

CREATE TABLE payments (
    order_id      TEXT NOT NULL REFERENCES orders (order_id),
    payment_seq   INTEGER NOT NULL,
    payment_type  TEXT NOT NULL,
    payment_value REAL NOT NULL CHECK (payment_value >= 0),
    PRIMARY KEY (order_id, payment_seq)
);

CREATE TABLE refunds (
    order_id     TEXT NOT NULL REFERENCES orders (order_id),
    refund_ts    TEXT NOT NULL,
    refund_value REAL NOT NULL CHECK (refund_value >= 0),
    reason       TEXT
);

CREATE INDEX idx_orders_purchase_ts ON orders (purchase_ts);
CREATE INDEX idx_orders_customer ON orders (customer_id);
CREATE INDEX idx_items_product ON order_items (product_id);
