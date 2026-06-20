-- =============================================================
-- E-Commerce Demo Database
-- Purpose: Demonstrate indexes, denormalization, and aggregation
-- Note: Indexes intentionally omitted (beyond PKs) for demo purposes
-- =============================================================

-- -------------------------------------------------------------
-- CATEGORIES
-- ~50 rows | Used in: index demo (filter products by category)
-- -------------------------------------------------------------
CREATE TABLE categories (
    category_id   SERIAL PRIMARY KEY,
    name          VARCHAR(100) NOT NULL,
    parent_id     INT REFERENCES categories(category_id)
);

-- -------------------------------------------------------------
-- PRODUCTS
-- ~100,000 rows | Used in: index demo, denormalization demo
-- -------------------------------------------------------------
CREATE TABLE products (
    product_id      SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    price           NUMERIC(10, 2) NOT NULL,
    stock_quantity  INT NOT NULL DEFAULT 0,
    category_id     INT NOT NULL REFERENCES categories(category_id),
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- -------------------------------------------------------------
-- CUSTOMERS
-- ~1,000,000 rows | Used in: index demo, aggregation demo
-- -------------------------------------------------------------
CREATE TABLE customers (
    customer_id  SERIAL PRIMARY KEY,
    first_name   VARCHAR(100) NOT NULL,
    last_name    VARCHAR(100) NOT NULL,
    email        VARCHAR(255) NOT NULL UNIQUE,
    phone        VARCHAR(20),
    city         VARCHAR(100),
    country      VARCHAR(100),
    created_at   TIMESTAMP NOT NULL DEFAULT NOW()
);

-- -------------------------------------------------------------
-- ORDERS
-- ~5,000,000 rows | Used in: index demo, aggregation demo
-- Intentionally normalized: no customer info embedded here
-- (denormalization demo will add city/country columns later)
-- -------------------------------------------------------------
CREATE TABLE orders (
    order_id      SERIAL PRIMARY KEY,
    customer_id   INT NOT NULL REFERENCES customers(customer_id),
    status        VARCHAR(20) NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'processing', 'shipped', 'delivered', 'cancelled')),
    total_amount  NUMERIC(12, 2),
    created_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

-- -------------------------------------------------------------
-- ORDER ITEMS
-- ~15,000,000 rows | Main fact table
-- Intentionally normalized: no product name/price embedded here
-- (denormalization demo will add product_name, product_price columns later)
-- -------------------------------------------------------------
CREATE TABLE order_items (
    order_item_id  SERIAL PRIMARY KEY,
    order_id       INT NOT NULL REFERENCES orders(order_id),
    product_id     INT NOT NULL REFERENCES products(product_id),
    quantity       INT NOT NULL,
    unit_price     NUMERIC(10, 2) NOT NULL,
    subtotal       NUMERIC(12, 2) NOT NULL
);

-- -------------------------------------------------------------
-- PRODUCT REVIEWS
-- ~2,000,000 rows | Used in: aggregation demo (avg rating per product)
-- -------------------------------------------------------------
CREATE TABLE product_reviews (
    review_id   SERIAL PRIMARY KEY,
    product_id  INT NOT NULL REFERENCES products(product_id),
    customer_id INT NOT NULL REFERENCES customers(customer_id),
    rating      SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    title       VARCHAR(255),
    body        TEXT,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);
