import sqlite3

DB_PATH = "family_price_watch.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site TEXT NOT NULL,
            name TEXT NOT NULL,
            url TEXT,
            current_price INTEGER,
            target_price INTEGER,
            created_by TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()
    print("DB initialized")


if __name__ == "__main__":
    init_db()
