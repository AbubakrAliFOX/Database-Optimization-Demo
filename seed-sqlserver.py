#!/usr/bin/env python3
"""
Seed script for the e-commerce demo database.
Inserts ~23M rows across 6 tables to support demos on
indexes, denormalization, and materialized views.

Requires Python 3.9+ and the packages in requirements.txt.
"""
import pyodbc as mssql
import random
import time
from datetime import datetime, timedelta

import psycopg2
from psycopg2.extras import execute_values
from faker import Faker

fake = Faker()
Faker.seed(42)
random.seed(42)

# Connection parameters
server = 'localhost'          # or 'hostname\instance' or 'hostname:port'
database = 'TestDb'

conn_str = (
    r'DRIVER={ODBC Driver 17 for SQL Server};'
    f'SERVER={server};'
    f'DATABASE={database};'
    r'Trusted_Connection=yes;'
)

# ── Row counts ────────────────────────────────────────────────────────────────
# Override via env vars for quick smoke tests, e.g.:
#   NUM_ORDERS=10000 python seed.py
NUM_CUSTOMERS = 1_000_000
NUM_PRODUCTS  = 100_000
NUM_ORDERS    = 5_000_000
NUM_REVIEWS   = 2_000_000
BATCH_SIZE    = 50_000

# ── Pre-generated lookup pools (avoids calling Faker in hot loops) ────────────
STATUSES      = ["pending", "processing", "shipped", "delivered", "cancelled"]
WEIGHTS       = [0.05, 0.10, 0.15, 0.60, 0.10]
EMAIL_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com"]

FIRST_NAMES = [fake.first_name()   for _ in range(2000)]
LAST_NAMES  = [fake.last_name()    for _ in range(2000)]
CITIES      = [fake.city()         for _ in range(500)]
COUNTRIES   = [fake.country()      for _ in range(100)]
PHRASES     = [fake.catch_phrase() for _ in range(5000)]
SENTENCES   = [fake.sentence(nb_words=6) for _ in range(500)]


def rand_dt(days: int = 3 * 365) -> datetime:
    return datetime.now() - timedelta(seconds=random.randint(0, days * 86_400))


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def progress(done: int, total: int):
    pct    = done / total * 100
    filled = int(30 * done / total)
    bar    = "█" * filled + "░" * (30 - filled)
    print(f"\r  [{bar}] {done:>10,} / {total:,}  {pct:5.1f}%", end="", flush=True)


def wait_for_db(retries: int = 15, delay: int = 3):
    for attempt in range(retries):
        try:
            sql = mssql.connect(conn_str)
            sql.close()

            log("Database is ready.")
            return
        except psycopg2.OperationalError:
            log(f"Waiting for database... ({attempt + 1}/{retries})")
            time.sleep(delay)
    raise RuntimeError("Could not connect to the database after multiple retries.")


# ── Seeders ───────────────────────────────────────────────────────────────────

def seed_categories(cur) -> list:
    top = [
        "Electronics", "Clothing", "Home & Garden", "Sports & Outdoors",
        "Books", "Toys & Games", "Beauty", "Food & Grocery",
        "Automotive", "Health & Wellness",
    ]
    subs = [
        ["Phones", "Laptops", "Tablets", "Cameras", "Audio"],
        ["Men's", "Women's", "Kids'", "Shoes", "Accessories"],
        ["Furniture", "Kitchen", "Bedding", "Garden Tools", "Lighting"],
        ["Fitness", "Camping", "Cycling", "Swimming", "Team Sports"],
        ["Fiction", "Non-Fiction", "Science", "History", "Children's"],
        ["Action Figures", "Board Games", "Puzzles", "LEGO", "Outdoor"],
        ["Skincare", "Haircare", "Makeup", "Fragrance", "Grooming"],
        ["Snacks", "Beverages", "Organic", "Frozen", "Condiments"],
        ["Car Parts", "Car Accessories", "Tools", "Car Care", "Tires"],
        ["Vitamins", "Supplements", "Medical", "First Aid", "Gear"],
    ]

    all_ids = []
    cur.execute(f"USE {database}")
    
    for i, name in enumerate(top):
        cur.execute("INSERT INTO categories (name) OUTPUT inserted.category_id VALUES (?)", (name))
        parent_id = cur.fetchone()[0]
        all_ids.append(parent_id)
        for sub in subs[i]:
            cur.execute("INSERT INTO categories (name, parent_id) OUTPUT inserted.category_id VALUES (?, ?)",(sub, parent_id))
            all_ids.append(cur.fetchone()[0])

    log(f"categories: {len(all_ids)} rows inserted")
    return all_ids


def seed_products(cur, category_ids: list):
    log(f"products: seeding {NUM_PRODUCTS:,} rows...")
    batch = []
    sql = f"INSERT INTO products (name, description, price, stock_quantity, category_id, created_at) VALUES (?, ?, ?, ?, ?, ?)"
    for i in range(1, NUM_PRODUCTS + 1):
        batch.append((
            random.choice(PHRASES),
            fake.text(max_nb_chars=200) if i % 4 == 0 else None,
            round(random.uniform(2.99, 1_499.99), 2),
            random.randint(0, 500),
            random.choice(category_ids),
            rand_dt(3 * 365),
        ))

        if len(batch) == BATCH_SIZE:
            cur.executemany(sql, batch)
            progress(i, NUM_PRODUCTS)
            batch = []
    if batch:
        cur.executemany(sql, batch)
    print()


def seed_customers(cur):
    log(f"customers: seeding {NUM_CUSTOMERS:,} rows...")
    batch = []
    stmt = " INSERT INTO customers (first_name, last_name, email, phone, city, country, created_at) VALUES (?, ?, ?, ?, ?, ?,?)"
    for i in range(1, NUM_CUSTOMERS + 1):
        batch.append((
            random.choice(FIRST_NAMES),random.choice(LAST_NAMES),f"user{i}@{random.choice(EMAIL_DOMAINS)}",
            f"+1{random.randint(2_000_000_000, 9_999_999_999)}",
            random.choice(CITIES),random.choice(COUNTRIES),rand_dt(5 * 365)))
     
        if len(batch) == BATCH_SIZE:
            cur.executemany(stmt, batch)
            batch = []
            progress(i, NUM_CUSTOMERS)
    if batch:
        cur.executemany(stmt, batch)
    print()


def seed_orders(cur):
    log(f"orders: seeding {NUM_ORDERS:,} rows...")
    batch = []
    stmt = "INSERT INTO orders (customer_id, status, total_amount, created_at, updated_at) VALUES (?, ?, ?, ?, ?)"
    for i in range(1, NUM_ORDERS + 1):
        ts = rand_dt(3 * 365)
        batch.append((
            random.randint(1, NUM_CUSTOMERS),
            random.choices(STATUSES, weights=WEIGHTS)[0],
            round(random.uniform(10, 1_500), 2),
            ts, ts,
        ))
        if len(batch) == BATCH_SIZE:
            cur.executemany(stmt, batch)
            batch = []
            progress(i, NUM_ORDERS)
    if batch:
        cur.executemany(stmt, batch)
    print()


def seed_order_items(cur):
    cur.execute("SELECT MIN(order_id), MAX(order_id) FROM orders")
    min_id, max_id = cur.fetchone()
    total_orders   = max_id - min_id + 1

    log(f"order_items: generating items for {total_orders:,} orders (avg 3 items each)...")
    batch      = []
    items_done = 0
    stmt = "  INSERT INTO order_items (order_id, product_id, quantity, unit_price, subtotal) VALUES (?, ?, ?, ?, ?)"
       
    for order_id in range(min_id, max_id + 1):
        for _ in range(random.randint(1, 5)):
            qty   = random.randint(1, 5)
            price = round(random.uniform(2.99, 999.99), 2)
            batch.append((
                order_id,
                random.randint(1, NUM_PRODUCTS),
                qty,
                price,
                round(qty * price, 2),
            ))

        if len(batch) >= BATCH_SIZE:
            cur.executemany(stmt, batch)           
            items_done += len(batch)
            batch = []
            progress(order_id - min_id + 1, total_orders)

    if batch:
        cur.executemany(stmt, batch)
        items_done += len(batch)

    print()
    log(f"order_items: {items_done:,} rows inserted")


def seed_reviews(cur):
    log(f"reviews: seeding {NUM_REVIEWS:,} rows...")
    batch = []
    stmt = "INSERT INTO product_reviews (product_id, customer_id, rating, title, body, created_at) VALUES (?, ?, ?, ?, ?, ?)"
       
    for i in range(1, NUM_REVIEWS + 1):
        batch.append((
            random.randint(1, NUM_PRODUCTS),
            random.randint(1, NUM_CUSTOMERS),
            random.randint(1, 5),
            random.choice(SENTENCES) if i % 2 == 0 else None,
            fake.text(max_nb_chars=300) if i % 4 == 0 else None,
            rand_dt(3 * 365),
        ))
        if len(batch) == BATCH_SIZE:
            cur.executemany(stmt, batch)
            batch = []
            progress(i, NUM_REVIEWS)
    if batch:
        cur.executemany(stmt, batch)
    print()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    wait_for_db()

    cnn = mssql.connect(conn_str)
    cnn.autocommit = False
    cur = cnn.cursor()

    try:
        t0 = time.time()

        log("── Step 1/6: Categories ─────────────────────────────────────")
        category_ids = seed_categories(cur)
        cnn.commit()

        log("── Step 2/6: Products ───────────────────────────────────────")
        seed_products(cur, category_ids)
        cnn.commit()

        log("── Step 3/6: Customers ──────────────────────────────────────")
        seed_customers(cur)
        cnn.commit()

        log("── Step 4/6: Orders ─────────────────────────────────────────")
        seed_orders(cur)
        cnn.commit()

        log("── Step 5/6: Order Items ────────────────────────────────────")
        seed_order_items(cur)
        cnn.commit()

        log("── Step 6/6: Product Reviews ────────────────────────────────")
        seed_reviews(cur)
        cnn.commit()

        elapsed = time.time() - t0
        log(f"All done! Total time: {elapsed / 60:.1f} minutes")

    except Exception:
        cnn.rollback()
        raise
    finally:
        cur.close()
        cnn.close()


if __name__ == "__main__":
    main()
