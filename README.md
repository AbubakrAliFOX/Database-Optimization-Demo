# PostgreSQL Database Optimization — Demo Environment

A fully seeded e-commerce database for learning and demonstrating four core PostgreSQL optimization concepts:

- **EXPLAIN & EXPLAIN ANALYZE** — read what the database is actually doing
- **Denormalization** — restructure data to avoid expensive joins
- **Indexes** — skip irrelevant data instead of scanning everything
- **Pre-aggregation** — compute expensive results once, read them many times

The database contains roughly **23 million rows** spread across 6 tables — enough data to make the before/after difference dramatic.

---

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Docker Desktop | Latest | [docker.com/get-started](https://docker.com/get-started) |
| PostgreSQL | 18.4 | Pulled automatically via Docker |
| Python | 3.9+ | For the seed script |

---

## Quick Start

### 1. Clone and enter the project

```bash
git clone <repo-url>
cd database-optimization
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

The defaults work out of the box. Edit `.env` only if port `5432` or `8080` is already in use.

### 3. Start the database

```bash
docker compose up -d
```

This starts PostgreSQL and pgAdmin. The schema is applied automatically on first boot.

### 4. Install Python dependencies

```bash
pip3 install -r requirements.txt
```

### 5. Seed the database

```bash
python3 seed.py
```

Seeding takes **15–30 minutes** depending on your machine. You will see a live progress bar for each table.

> **Quick test run** — seed a smaller dataset to verify the setup:
> ```bash
> NUM_CUSTOMERS=10000 NUM_ORDERS=50000 NUM_REVIEWS=20000 python3 seed.py
> ```

---

## Connecting to the Database

### psql (terminal)

```bash
psql -h localhost -U admin -d ecommerce
```

Password: `password`

### pgAdmin (browser GUI)

Open [http://localhost:8080](http://localhost:8080) and log in with:
- Email: `admin@demo.com`
- Password: `password`

Then add a new server connection:
- Host: `db`
- Port: `5432`
- Database: `ecommerce`
- Username: `admin`
- Password: `password`

### Any SQL client (TablePlus, DBeaver, DataGrip)

```
Host:     localhost
Port:     5432
Database: ecommerce
User:     admin
Password: password
```

---

## Schema Overview

```
categories (60 rows)
    └── products (100K rows)
            └── order_items (≈15M rows)
                    └── orders (5M rows)
                            └── customers (1M rows)

product_reviews (2M rows)  →  products + customers
```

| Table | Rows | Purpose |
|---|---|---|
| `categories` | ~60 | Hierarchical product taxonomy |
| `products` | ~100,000 | Product catalog with price and stock |
| `customers` | ~1,000,000 | Registered users |
| `orders` | ~5,000,000 | Order headers with status and total |
| `order_items` | ~15,000,000 | Line items linking orders to products |
| `product_reviews` | ~2,000,000 | Customer ratings (1–5) with optional text |

---

## Part 1 — EXPLAIN & EXPLAIN ANALYZE

Before any optimization technique, you need the tool that tells you whether it actually worked. `EXPLAIN` shows the **query execution plan** — what the database intends to do. `EXPLAIN ANALYZE` runs the query and shows real timings alongside the estimates.

## Anatomy of a Plan

```sql
EXPLAIN
SELECT product_id, name, description, price
FROM products;
```

```
Seq Scan on products  (cost=0.00..4000.00 rows=100000 width=80)
```

| Field | Meaning |
|---|---|
| **Operation** | What the DB is doing — `Seq Scan`, `Index Scan`, `Hash Join`, etc. |
| **cost=X..Y** | X = startup cost, Y = total cost to return all rows (arbitrary units) |
| **rows** | Estimated rows this operation returns |
| **width** | Average row size in bytes |

`Seq Scan` means the database read **every row** in the table. Cost units are arbitrary — they're not milliseconds, but they're useful as a rough ratio to compare plans.

**`Seq Scan` on a large table is generally what we want to get rid of** — Part 3 covers how.

---

## Case 1 — SELECT *

```sql
EXPLAIN SELECT * FROM orders;
```

```
Seq Scan on orders  (cost=0.00..91345.00 rows=5000000 width=42)
```

Full table scan — every row, every column. Now compare selecting one column:

```sql
EXPLAIN SELECT total_amount FROM orders;
```

```
Seq Scan on orders  (cost=0.00..91345.00 rows=5000000 width=8)
```

Same scan, smaller width. **Cost is identical** — the bottleneck is reading every row, not how many columns you return. `SELECT *` is dangerous because it prevents covering indexes from working and pulls unnecessary data over the network — not because of the columns themselves.

---

## Case 2 — Filtering with WHERE

```sql
EXPLAIN SELECT * FROM orders WHERE customer_id = 42;
```

```
Seq Scan on orders  (cost=0.00..98345.00 rows=5 width=42)
  Filter: (customer_id = 42)
```

A `Seq Scan` with a filter — the DB reads all 5M rows and discards the ones that don't match. We'll fix this in Part 3.

**Range filters** can still produce a `Seq Scan` even with an index:
```sql
EXPLAIN SELECT * FROM orders WHERE total_amount > 50;
```

If the filter matches a large percentage of rows, the planner correctly decides that sequential reads are faster than hopping through the index to thousands of scattered rows.

---

## Case 3 — ORDER BY, GROUP BY, LIMIT

**ORDER BY:**
```sql
EXPLAIN SELECT * FROM orders ORDER BY total_amount DESC;
```

```
Sort  (cost=812345.00..824845.00 rows=5000000 width=42)
  Sort Key: total_amount DESC
  ->  Seq Scan on orders  (cost=0.00..91345.00 rows=5000000 width=42)
```

Two-step plan now — a `Seq Scan` feeding into a `Sort`. Sorting 5M rows is expensive. With an index on `total_amount`, PostgreSQL can return rows already sorted and skip the sort entirely.

**GROUP BY:**
```sql
EXPLAIN SELECT customer_id, SUM(total_amount) FROM orders GROUP BY customer_id;
```

```
HashAggregate  (cost=141345.00..142845.00 rows=1000000 width=40)
  Group Key: customer_id
  ->  Seq Scan on orders  (cost=0.00..91345.00 rows=5000000 width=12)
```

`HashAggregate` builds an in-memory hash table to group rows. If the hash table doesn't fit in `work_mem`, PostgreSQL spills to disk and the cost jumps significantly.

**LIMIT:**
```sql
EXPLAIN SELECT * FROM orders ORDER BY created_at DESC LIMIT 10;
```

```
Limit  (cost=812345.10..812345.13 rows=10 width=42)
  ->  Sort  (cost=812345.00..824845.00 rows=5000000 width=42)
        ->  Seq Scan on orders
```

`LIMIT` reduces returned rows but **does not reduce how many rows are sorted**. All 5M rows are sorted first, then 10 are returned. An index on `created_at` would let the DB read just the top 10 directly with no sort.

---

## Case 4 — JOINs

```sql
EXPLAIN
SELECT o.order_id, c.first_name, c.last_name
FROM orders o
JOIN customers c ON o.customer_id = c.customer_id
WHERE o.status = 'delivered'
LIMIT 100;
```

```
Limit
  ->  Hash Join  (cost=...)
        Hash Cond: (o.customer_id = c.customer_id)
        ->  Seq Scan on orders
              Filter: (status = 'delivered')
        ->  Hash
              ->  Seq Scan on customers
```

The plan is now a **tree** — read it bottom-up. PostgreSQL chose `Hash Join` — it scans the smaller table, builds a hash table from it, then probes it with each row from the larger table.

You may also see:
- **Nested Loop** — small tables or when an index is available on the join column
- **Merge Join** — when both sides are already sorted

**Each join adds a layer.** A 6-table join produces a deep nested plan. This is exactly what denormalization and pre-aggregation are solving.

---

## Case 5 — Subqueries vs JOINs

```sql
-- Subquery
EXPLAIN
SELECT name FROM products
WHERE product_id IN (
  SELECT product_id FROM order_items WHERE order_id = 1000
);
```

```
Hash Semi Join
  ->  Seq Scan on products
  ->  Hash
        ->  Seq Scan on order_items
              Filter: (order_id = 1000)
```

PostgreSQL is often smart enough to rewrite a subquery as a join internally (`Hash Semi Join` here). Not always. Always `EXPLAIN` both forms and pick the plan the planner handles better.

---

## EXPLAIN ANALYZE — actual runtime

`EXPLAIN ANALYZE` runs the query and shows real measurements alongside the estimates:

```sql
EXPLAIN ANALYZE SELECT * FROM orders WHERE customer_id = 42;
```

```
Seq Scan on orders  (cost=0.00..98345.00 rows=5 width=42)
                    (actual time=0.043..891.223 rows=5 loops=1)
  Filter: (customer_id = 42)
  Rows Removed by Filter: 4999995
Planning Time: 0.121 ms
Execution Time: 891.4 ms
```

| New Field | Meaning |
|---|---|
| **actual time=X..Y** | X = ms to first row, Y = ms to last row |
| **rows** | Actual rows returned — compare to estimate |
| **loops** | How many times this node ran |
| **Rows Removed by Filter** | Rows read and discarded — a high number is a red flag |
| **Planning Time** | Time to build the plan |
| **Execution Time** | Total real runtime |

**Comparing estimated rows to actual rows is the most valuable signal.** A large gap means stale statistics — run `ANALYZE orders;` to refresh them.

**Reading tip:** read the tree **bottom-up**, focus on the deepest node first, and look at the **biggest time jump between a child and its parent** to find your bottleneck.

> Use `EXPLAIN` when you want a quick look at the plan. Use `EXPLAIN ANALYZE` when you want to measure actual performance — but it runs the query, so be careful with writes.

---

## Part 2 — Denormalization

Normalization eliminates redundancy — one place for every piece of data. Denormalization is the **deliberate introduction of redundancy** to make reads faster. You consciously trade write complexity for read speed.

## Two Forms of Denormalization

### Form 1 — Duplicating columns

Copy a value into another table to avoid a join. Right now every query that needs a product name has to JOIN `order_items` to `products`.

**Before:**
```sql
EXPLAIN ANALYZE
SELECT
    oi.order_item_id,
    p.name          AS product_name,
    oi.quantity,
    oi.subtotal
FROM order_items oi
JOIN products p ON oi.product_id = p.product_id
WHERE oi.order_id = 1000;
```

**Denormalize:**
```sql
ALTER TABLE order_items
    ADD COLUMN product_name  VARCHAR(255),
    ADD COLUMN product_price NUMERIC(10, 2);

-- Backfill (takes a few minutes on the full dataset)
UPDATE order_items oi
SET
    product_name  = p.name,
    product_price = p.price
FROM products p
WHERE oi.product_id = p.product_id;
```

**After (no JOIN):**
```sql
EXPLAIN ANALYZE
SELECT order_item_id, product_name, quantity, subtotal
FROM order_items
WHERE order_id = 1000;
```

---

### Form 2 — Storing computed / aggregated values

Pre-calculate instead of computing at query time. The product list page wants to show `review_count` and `avg_rating` — both currently require a `GROUP BY` over 2M reviews on every page load.

**Before:**
```sql
EXPLAIN ANALYZE
SELECT
    p.product_id,
    p.name,
    COUNT(r.review_id) AS review_count,
    ROUND(AVG(r.rating), 2) AS avg_rating
FROM products p
LEFT JOIN product_reviews r ON p.product_id = r.product_id
GROUP BY p.product_id, p.name
ORDER BY avg_rating DESC NULLS LAST
LIMIT 20;
```

**Denormalize:**
```sql
ALTER TABLE products
    ADD COLUMN review_count INTEGER  DEFAULT 0,
    ADD COLUMN avg_rating   NUMERIC(3, 2);

-- One-time backfill
UPDATE products p
SET
    review_count = sub.cnt,
    avg_rating   = sub.avg_r
FROM (
    SELECT product_id,
           COUNT(*)            AS cnt,
           ROUND(AVG(rating), 2) AS avg_r
    FROM product_reviews
    GROUP BY product_id
) sub
WHERE p.product_id = sub.product_id;
```

**After (no aggregation):**
```sql
EXPLAIN ANALYZE
SELECT product_id, name, review_count, avg_rating
FROM products
ORDER BY avg_rating DESC NULLS LAST
LIMIT 20;
```

---

## Trade-offs

**1. Write complexity** — every write must now update data in multiple places:
```sql
-- Normalized: one update
UPDATE products SET price = 49.99 WHERE product_id = 42;

-- Denormalized: must also update copies elsewhere
UPDATE order_items SET product_price = 49.99 WHERE product_id = 42;
```

**2. Risk of data inconsistency** — if update logic has a bug or a write partially fails, you get different answers depending on which table you query. Silent and dangerous.

**3. Storage cost** — duplicated data uses more disk space.

**4. Schema rigidity** — changing one column means finding and updating every place it was copied.

**Discussion question for students:** when a product's price changes, should the historical `order_items.product_price` change too? (Usually no — you want to preserve the price at the time of sale. That's denormalization aligning with real business logic.)

---

## Part 3 — Indexes

Without an index, every filtered query does a **full table scan** — the DB reads every row and checks if it matches. An index is a separate data structure that lets the DB jump directly to relevant rows.

> Like the index at the back of a book — instead of reading every page to find "partitioning", you check the index, find the page numbers, and go directly there.

## How Indexes Work — The B-Tree

PostgreSQL uses **B+ Tree** indexes by default. Searching is **O(log n)** instead of **O(n)** — on 5M rows that's ~22 comparisons instead of 5,000,000.

```text
                    [  50  ]
                   /        \
          [ 20 | 35 ]      [ 65 | 80 ]
         /     |    \      /    |     \
      [10]  [25|30] [40] [55] [70]  [90|99]
       ↓      ↓      ↓    ↓    ↓      ↓
     rows   rows   rows rows  rows   rows
```

Other index types in PostgreSQL:
- **Hash** — `=` only, no ranges, rarely the right choice
- **GIN / GiST** — full-text, JSON, geospatial
- **BRIN** — lightweight, for naturally ordered columns (e.g. timestamps on append-only tables)

---

## Single-Column Index

**Before:**
```sql
EXPLAIN ANALYZE
SELECT * FROM orders WHERE customer_id = 12345;
-- Seq Scan on orders, ~hundreds of ms
```

**Add the index:**
```sql
CREATE INDEX idx_orders_customer_id ON orders(customer_id);
```

**After:**
```sql
EXPLAIN ANALYZE
SELECT * FROM orders WHERE customer_id = 12345;
-- Index Scan, single-digit ms
```

---

## Composite Index — left-prefix rule

A composite index indexes multiple columns in one structure. **Column order matters enormously** — the index can only be used if your query starts from the leftmost column.

```sql
CREATE INDEX idx_orders_status_date ON orders(status, created_at);
```

```sql
-- ✅ Uses both columns
EXPLAIN ANALYZE
SELECT * FROM orders WHERE status = 'delivered' AND created_at > '2025-01-01';

-- ✅ Uses first column only
EXPLAIN ANALYZE
SELECT * FROM orders WHERE status = 'delivered';

-- ❌ Skips first column — index unusable
EXPLAIN ANALYZE
SELECT * FROM orders WHERE created_at > '2025-01-01';
```

---

## Unique Index

Enforces uniqueness *and* gives index performance. Created automatically by `PRIMARY KEY` and `UNIQUE` constraints — but you can also create one explicitly:

```sql
-- customers.email already has a UNIQUE constraint from the schema,
-- so the lookup below is already index-backed:
EXPLAIN ANALYZE
SELECT * FROM customers WHERE email = 'user12345@gmail.com';
```

---

## Covering Index — the INCLUDE keyword

Adds extra columns to the index that aren't part of the search key but live in the leaf nodes. The query can be answered entirely from the index without touching the table — an **Index Only Scan**.

```sql
CREATE INDEX idx_orders_covering
ON orders(customer_id)
INCLUDE (total_amount, status, created_at);
```

```sql
EXPLAIN ANALYZE
SELECT total_amount, status, created_at
FROM orders
WHERE customer_id = 12345;
-- Index Only Scan — never touches the orders heap
```

Three conditions must all hold for an Index Only Scan:
1. Every column the query needs is in the index (key or INCLUDE)
2. The visibility map says the heap pages are all-visible (run `VACUUM` to help)
3. The planner decides it's the cheapest plan

---

## When the planner ignores your index

```sql
EXPLAIN ANALYZE SELECT * FROM orders WHERE total_amount > 50;
```

Even with an index on `total_amount`, PostgreSQL may still choose a `Seq Scan` if the filter matches a large percentage of rows. Hopping through the index for millions of scattered rows is slower than reading the table sequentially. **The planner is right.**

---

## Trade-offs

**1. Write cost** — every index must be updated on every `INSERT`, `UPDATE`, `DELETE`. Ten indexes on a hot table turns one write into eleven.

**2. Storage cost** — indexes can be nearly as large as the table itself.

**3. Low-cardinality is a trap** — an index on `status` (5 possible values) is mostly useless. The planner will often ignore it.

**4. Over-indexing** — the most common mistake. Find unused indexes with:
```sql
SELECT schemaname, relname, indexrelname, idx_scan
FROM pg_stat_user_indexes
WHERE idx_scan = 0
  AND schemaname = 'public'
ORDER BY relname;
```
If `idx_scan = 0` and the index has been live in production for a while, drop it.

---

## The Mental Model

```
What does my query filter on?           → candidate for index
What does my query sort on?             → match ORDER BY column order
What does my query return?              → candidate for INCLUDE (covering)
How write-heavy is this table?          → caps how many indexes you can afford
How many distinct values in the column? → caps whether the index will be used
```

---

## Part 4 — Pre-Aggregation

Some queries produce the same expensive answer over and over — joining millions of rows, scanning entire tables, computing sums and counts from scratch — on every single request. Pre-aggregation **computes that answer once and stores it**, so queries just read the result.

> The best aggregation is the one that already happened before the query ran.

There are two main forms: **summary tables** (you manage everything) and **materialized views** (the database manages everything).

---

## Summary Tables

A summary table is a plain table you create and maintain yourself. Full control, full responsibility.

**The slow live query:**
```sql
EXPLAIN ANALYZE
SELECT
    c.category_id,
    c.name                         AS category,
    COUNT(DISTINCT o.order_id)     AS total_orders,
    SUM(oi.subtotal)               AS total_revenue
FROM categories c
JOIN products    p  ON c.category_id = p.category_id
JOIN order_items oi ON p.product_id  = oi.product_id
JOIN orders      o  ON oi.order_id   = o.order_id
WHERE o.status = 'delivered'
GROUP BY c.category_id, c.name;
-- Multiple seq scans, joins, aggregation — slow
```

**Create the summary table:**
```sql
CREATE TABLE category_revenue_summary (
    category_id   INT PRIMARY KEY,
    category_name VARCHAR(100),
    total_orders  INTEGER,
    total_revenue NUMERIC(15, 2),
    last_updated  TIMESTAMP
);

INSERT INTO category_revenue_summary
SELECT
    c.category_id,
    c.name,
    COUNT(DISTINCT o.order_id),
    SUM(oi.subtotal),
    NOW()
FROM categories c
JOIN products    p  ON c.category_id = p.category_id
JOIN order_items oi ON p.product_id  = oi.product_id
JOIN orders      o  ON oi.order_id   = o.order_id
WHERE o.status = 'delivered'
GROUP BY c.category_id, c.name;
```

**Querying it is just a table read:**
```sql
SELECT * FROM category_revenue_summary ORDER BY total_revenue DESC;
```

**How you keep it updated:**

| Method | Benefit | Cost |
|---|---|---|
| **Application code** | Simple, explicit | Logic scattered, easy to miss writes |
| **Triggers** | Nothing slips through | Adds overhead to every write |
| **Scheduled jobs** | Simple to reason about | Data is stale between runs |

---

## Materialized Views

A materialized view is the database's native solution. You define a query, PostgreSQL runs it and **stores the result on disk** like a table. The database handles storage — you control when it refreshes.

```sql
CREATE MATERIALIZED VIEW monthly_category_revenue AS
SELECT
    DATE_TRUNC('month', o.created_at)  AS month,
    c.category_id,
    c.name                              AS category_name,
    SUM(oi.subtotal)                    AS revenue,
    COUNT(DISTINCT o.order_id)          AS orders,
    COUNT(oi.order_item_id)             AS items_sold
FROM orders o
JOIN order_items oi ON o.order_id     = oi.order_id
JOIN products    p  ON oi.product_id  = p.product_id
JOIN categories  c  ON p.category_id  = c.category_id
WHERE o.status = 'delivered'
GROUP BY 1, 2, 3;

-- Index it like any table
CREATE UNIQUE INDEX ON monthly_category_revenue(month, category_id);
```

**Querying it is just a table read:**
```sql
EXPLAIN ANALYZE
SELECT month, category_name, revenue, orders
FROM monthly_category_revenue
ORDER BY month DESC, revenue DESC;
-- Index Scan, <1 ms
```

**Refreshing:**
```sql
-- Full refresh — blocks reads briefly
REFRESH MATERIALIZED VIEW monthly_category_revenue;

-- Non-blocking refresh — requires a UNIQUE index on the view
REFRESH MATERIALIZED VIEW CONCURRENTLY monthly_category_revenue;
```

---

## Summary Tables vs Materialized Views

| | Summary Tables | Materialized Views |
|---|---|---|
| Managed by | You | The database |
| Update mechanism | App code, triggers, scheduled jobs | `REFRESH` command |
| Incremental updates | ✅ Yes | ❌ No — full recompute |
| Indexable | ✅ Yes | ✅ Yes |
| Flexibility | High | Limited to query definition |
| Maintenance burden | High | Low |
| Best for | High write frequency, near real-time | Periodic refresh is acceptable |

---

## Trade-offs

**1. Staleness** — data is only as fresh as the last refresh. Fine for dashboards. Not for anything requiring real-time accuracy.

**2. Refresh cost** — `REFRESH` recomputes the entire underlying query on materialized views. Slow on large datasets.

**3. No automatic updates** — PostgreSQL does not refresh materialized views on its own. Schedule them, or they silently age.

**4. Storage cost** — the result lives on disk; indexes on top add more.

**Discussion questions for students:**
- How stale can the view get before it becomes a problem?
- What is the cost of `REFRESH` on a production system?
- When would a summary table be better than a materialized view?

---

## Session Summary

| Technique | What It Eliminates | Trade-off |
|---|---|---|
| **EXPLAIN ANALYZE** | Guesswork | Doesn't fix anything itself — but you can't fix what you can't measure |
| **Denormalization** | Join cost at query time | Write complexity, consistency risk |
| **Indexes** | Full table scans | Write overhead, storage cost |
| **Pre-Aggregation** | Aggregation + joins at query time | Staleness, refresh cost |

**The throughline:** every technique here moves work *away* from query time — either by organizing data better, navigating it smarter, or computing results in advance.

---

## Resetting the Database

To wipe all data and start fresh:

```bash
docker compose down -v   # removes volumes (all data)
docker compose up -d     # recreates with clean schema
python3 seed.py          # re-seed
```

---

## Troubleshooting

**Port 5432 already in use**
Edit `.env` and change `DB_PORT` to e.g. `5433`, then restart: `docker compose down && docker compose up -d`.

**Seed script fails with "connection refused"**
The database container may still be starting. Wait ~10 seconds and re-run `python3 seed.py` — the script retries automatically.

**Seeding is slow**
This is expected for the full dataset. Reduce row counts for quicker iteration:
```bash
NUM_CUSTOMERS=10000 NUM_ORDERS=50000 NUM_REVIEWS=20000 python3 seed.py
```
