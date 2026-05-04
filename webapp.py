import os
import sqlite3
from datetime import datetime

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from bs4 import BeautifulSoup
from flask import Flask, jsonify, redirect, render_template, request, url_for

from scraper import update_all_prices

app = Flask(__name__)
DB_PATH = "family_price_watch.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            site         TEXT    NOT NULL,
            name         TEXT    NOT NULL,
            url          TEXT,
            current_price REAL,
            target_price  REAL,
            last_checked  TEXT,
            created_by   TEXT,
            is_active    INTEGER DEFAULT 1,
            created_at   TEXT,
            updated_at   TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            price      REAL    NOT NULL,
            checked_at TEXT    NOT NULL
        )
    """)
    # 既存DBへの追加カラム（初回のみ実行される）
    for col_def in [
        "ALTER TABLE products ADD COLUMN last_checked TEXT",
        "ALTER TABLE products ADD COLUMN current_price REAL",
        "ALTER TABLE products ADD COLUMN target_price REAL",
        "ALTER TABLE products ADD COLUMN base_price REAL",
        "ALTER TABLE products ADD COLUMN sale_end_date TEXT",
        "ALTER TABLE products ADD COLUMN is_sale_notified INTEGER DEFAULT 0",
        "ALTER TABLE products ADD COLUMN is_stock_notified INTEGER DEFAULT 0",
    ]:
        try:
            conn.execute(col_def)
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.route("/")
def index():
    conn = get_db()
    products = conn.execute(
        "SELECT * FROM products WHERE is_active = 1 ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return render_template("index.html", products=products)


@app.route("/add", methods=["GET", "POST"])
def add():
    errors = {}

    if request.method == "POST":
        site         = request.form.get("site", "").strip()
        name         = request.form.get("name", "").strip()
        url          = request.form.get("url", "").strip()
        item_code    = request.form.get("item_code", "").strip()
        target_price = request.form.get("target_price", "").strip()
        created_by   = request.form.get("created_by", "").strip()

        costco_with_code = site == "Costco" and item_code.isdigit() and len(item_code) >= 5

        if not site:
            errors["site"] = "サイトを選択してください"
        if not name and not costco_with_code:
            errors["name"] = "商品名を入力してください"
        if not url:
            if costco_with_code:
                url = f"https://www.costco.co.jp/p/{item_code}"
            else:
                errors["url"] = "URLを入力してください"
        if not target_price:
            errors["target_price"] = "目標価格を入力してください"
        else:
            try:
                target_price = int(target_price)
                if target_price <= 0:
                    errors["target_price"] = "1以上の金額を入力してください"
            except ValueError:
                errors["target_price"] = "数字で入力してください"
        if not created_by:
            errors["created_by"] = "追加者を入力してください"

        if not errors:
            if costco_with_code and not name:
                name = fetch_costco_product_name(item_code)
            now = datetime.now().isoformat()
            conn = get_db()
            conn.execute(
                """
                INSERT INTO products
                    (site, name, url, current_price, target_price,
                     created_by, is_active, created_at, updated_at)
                VALUES (?, ?, ?, NULL, ?, ?, 1, ?, ?)
                """,
                (site, name, url, target_price, created_by, now, now),
            )
            conn.commit()
            conn.close()
            return redirect(url_for("index"))

        form_data = request.form
        return render_template("add.html", errors=errors, form_data=form_data)

    return render_template("add.html", errors={}, form_data={})


_COSTCO_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja-JP,ja;q=0.9",
}


def fetch_costco_product_name(item_code):
    url = f"https://www.costco.co.jp/p/{item_code}"
    try:
        resp = requests.get(url, headers=_COSTCO_HEADERS, timeout=6)
        soup = BeautifulSoup(resp.text, "html.parser")
        for sel in ["h1.page-title span", "h1.product-name", "h1", "title"]:
            el = soup.select_one(sel)
            if el:
                text = el.get_text(strip=True)
                if text and "costco" not in text.lower():
                    return text
    except Exception:
        pass
    return f"Costco商品（商品番号：{item_code}）"


@app.route("/edit/<int:product_id>", methods=["GET", "POST"])
def edit(product_id):
    conn = get_db()
    product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if not product:
        conn.close()
        return redirect(url_for("index"))

    if request.method == "POST":
        site         = request.form.get("site", "").strip()
        name         = request.form.get("name", "").strip()
        url          = request.form.get("url", "").strip()
        target_price = request.form.get("target_price", "").strip()
        created_by   = request.form.get("created_by", "").strip()

        errors = {}
        if not site:
            errors["site"] = "サイトを選択してください"
        if not name:
            errors["name"] = "商品名を入力してください"
        if not url:
            errors["url"] = "URLを入力してください"
        if not target_price:
            errors["target_price"] = "目標価格を入力してください"
        else:
            try:
                target_price = int(target_price)
                if target_price <= 0:
                    errors["target_price"] = "1以上の金額を入力してください"
            except ValueError:
                errors["target_price"] = "数字で入力してください"

        if not errors:
            now = datetime.now().isoformat()
            conn.execute(
                """UPDATE products
                   SET site=?, name=?, url=?, target_price=?, created_by=?, updated_at=?
                   WHERE id=?""",
                (site, name, url, target_price, created_by, now, product_id),
            )
            conn.commit()
            conn.close()
            return redirect(url_for("index"))

        conn.close()
        return render_template("edit.html", product=product, errors=errors, form_data=request.form)

    conn.close()
    return render_template("edit.html", product=product, errors={}, form_data=dict(product))


@app.route("/delete/<int:product_id>", methods=["POST"])
def delete(product_id):
    conn = get_db()
    conn.execute(
        "UPDATE products SET is_active = 0, updated_at = ? WHERE id = ?",
        (datetime.now().isoformat(), product_id),
    )
    conn.commit()
    conn.close()
    return redirect(url_for("index"))


@app.route("/api/costco-search")
def api_costco_search():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])
    try:
        resp = requests.get(
            "https://www.costco.co.jp/catalogsearch/result/",
            params={"q": q},
            headers=_COSTCO_HEADERS,
            timeout=6,
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for item in soup.select(".product-item")[:8]:
            name_el = item.select_one(".product-item-name a")
            if name_el:
                results.append({
                    "name": name_el.get_text(strip=True),
                    "url": name_el.get("href", ""),
                })
        return jsonify(results)
    except Exception:
        return jsonify([])


@app.route("/api/costco-item")
def api_costco_item():
    code = request.args.get("code", "").strip()
    if not code or not code.isdigit():
        return jsonify({})
    url = f"https://www.costco.co.jp/p/{code}"
    name = fetch_costco_product_name(code)
    if name == f"Costco商品（商品番号：{code}）":
        name = None
    return jsonify({"name": name, "url": url})


@app.route("/api/update-prices", methods=["POST"])
def api_update_prices():
    count = update_all_prices()
    return jsonify({"updated": count})


init_db()

# Werkzeugのリローダーが2プロセス起動するのを防ぐ
if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    _scheduler = BackgroundScheduler(timezone="Asia/Tokyo")
    _scheduler.add_job(update_all_prices, "cron", hour=9, minute=0)
    _scheduler.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
