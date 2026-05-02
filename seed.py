import sqlite3

DB_PATH = "family_price_watch.db"

conn = sqlite3.connect(DB_PATH)

conn.execute("""
    INSERT INTO products (site, name, url, current_price, target_price, created_by)
    VALUES (?, ?, ?, ?, ?, ?)
""", (
    "costco",
    "オイコス ストロベリー 12個",
    "https://www.costco.co.jp/",
    1248,
    1100,
    "papa"
))

conn.commit()
conn.close()

print("Seed inserted")
