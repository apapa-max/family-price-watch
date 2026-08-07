import os
import sqlite3
from datetime import datetime

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from bs4 import BeautifulSoup
from flask import Flask, jsonify, redirect, render_template, request, url_for

from scraper import update_all_prices, update_product_price

app = Flask(__name__)
DB_PATH = "family_price_watch.db"
SUPPORTED_SITES = ("Costco", "ヨドバシ.com")


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
        "ALTER TABLE products ADD COLUMN coupon_discount REAL",
        "ALTER TABLE products ADD COLUMN sale_end_date TEXT",
        "ALTER TABLE products ADD COLUMN is_sale_notified INTEGER DEFAULT 0",
        "ALTER TABLE products ADD COLUMN is_stock_notified INTEGER DEFAULT 0",
        "ALTER TABLE products ADD COLUMN stock_level INTEGER",
        "ALTER TABLE products ADD COLUMN stock_level_status TEXT",
        "ALTER TABLE products ADD COLUMN min_order_quantity INTEGER",
    ]:
        try:
            conn.execute(col_def)
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


@app.route("/")
def index():
    notice = request.args.get("notice", "")
    notice_type = request.args.get("notice_type", "info")
    conn = get_db()
    products = conn.execute(
        """SELECT * FROM products
           WHERE is_active = 1
             AND (site LIKE '%Costco%' OR site LIKE '%ヨドバシ%' OR site LIKE '%Yodobashi%')
           ORDER BY created_at DESC"""
    ).fetchall()
    conn.close()
    return render_template(
        "index.html",
        products=products,
        notice=notice,
        notice_type=notice_type,
    )


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

        is_costco = site == "Costco"
        is_yodobashi = site == "ヨドバシ.com"
        costco_with_code = is_costco and item_code.isdigit() and len(item_code) >= 5
        yodobashi_with_code = is_yodobashi and item_code.isdigit()

        if not site:
            errors["site"] = "サイトを選択してください"
        elif site not in SUPPORTED_SITES:
            errors["site"] = "現在取り込めるサイトを選択してください"
        if is_costco and not costco_with_code:
            errors["item_code"] = "Costcoの商品番号を数字5桁以上で入力してください"
        if is_yodobashi and not (yodobashi_with_code or url):
            errors["item_code"] = "ヨドバシの商品番号か商品URLを入力してください"
        if not name and not (is_costco or is_yodobashi):
            errors["name"] = "商品名を入力してください"
        if not url:
            if costco_with_code:
                url = f"https://www.costco.co.jp/p/{item_code}"
            elif yodobashi_with_code:
                url = f"https://www.yodobashi.com/product/{item_code}/"
            elif not (is_costco or is_yodobashi):
                errors["url"] = "URLを入力してください"
        if target_price:
            try:
                target_price = int(target_price)
                if target_price <= 0:
                    errors["target_price"] = "1以上の金額を入力してください"
            except ValueError:
                errors["target_price"] = "数字で入力してください"
        else:
            target_price = None

        if not errors:
            if costco_with_code and not name:
                name = fetch_costco_product_name(item_code)
            if yodobashi_with_code and not name:
                name = fetch_yodobashi_product_name(item_code)
            elif is_yodobashi and url and not name:
                name = fetch_yodobashi_product_name_from_url(url)
            created_by = created_by or None
            now = datetime.now().isoformat()
            conn = get_db()
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                """SELECT id FROM products
                   WHERE is_active = 1 AND site = ? AND url = ?
                   LIMIT 1""",
                (site, url),
            ).fetchone()
            if existing:
                conn.rollback()
                conn.close()
                return redirect(
                    url_for(
                        "index",
                        notice="同じ商品はすでに登録されています",
                        notice_type="warning",
                    )
                )
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


def fetch_yodobashi_product_name(item_code):
    url = f"https://www.yodobashi.com/product/{item_code}/"
    return fetch_yodobashi_product_name_from_url(
        url,
        fallback=f"ヨドバシ商品（商品番号：{item_code}）",
    )


def fetch_yodobashi_product_name_from_url(url, fallback="ヨドバシ商品"):
    try:
        resp = requests.get(url, headers=_COSTCO_HEADERS, timeout=6)
        soup = BeautifulSoup(resp.text, "html.parser")
        for sel in ["h1", ".productName", "#products_maintitle", "title"]:
            el = soup.select_one(sel)
            if el:
                text = el.get_text(" ", strip=True)
                if text and "ヨドバシ.com" not in text:
                    return text
    except Exception:
        pass
    return fallback


@app.route("/edit/<int:product_id>", methods=["GET", "POST"])
def edit(product_id):
    conn = get_db()
    product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if not product:
        conn.close()
        return redirect(url_for("index"))

    if request.method == "POST":
        name         = request.form.get("name", "").strip()
        target_price = request.form.get("target_price", "").strip()

        errors = {}
        if not name:
            errors["name"] = "商品名を入力してください"
        if target_price:
            try:
                target_price = int(target_price)
                if target_price <= 0:
                    errors["target_price"] = "1以上の金額を入力してください"
            except ValueError:
                errors["target_price"] = "数字で入力してください"
        else:
            target_price = None

        if not errors:
            now = datetime.now().isoformat()
            conn.execute(
                "UPDATE products SET name=?, target_price=?, updated_at=? WHERE id=?",
                (name, target_price, now, product_id),
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


@app.route("/update/<int:product_id>", methods=["POST"])
def update_price(product_id):
    updated = update_product_price(product_id)
    if updated:
        return redirect(
            url_for(
                "index",
                notice="価格と在庫を更新しました",
                notice_type="success",
            )
        )
    return redirect(
        url_for(
            "index",
            notice="更新できませんでした。商品ページから価格情報を取得できなかった可能性があります",
            notice_type="error",
        )
    )


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


@app.route("/api/yodobashi-item")
def api_yodobashi_item():
    code = request.args.get("code", "").strip()
    if not code or not code.isdigit():
        return jsonify({})
    url = f"https://www.yodobashi.com/product/{code}/"
    name = fetch_yodobashi_product_name(code)
    if name == f"ヨドバシ商品（商品番号：{code}）":
        name = None
    return jsonify({"name": name, "url": url})


@app.route("/api/update-prices", methods=["POST"])
def api_update_prices():
    count = update_all_prices()
    return jsonify({"updated": count})


init_db()

_scheduler = BackgroundScheduler(timezone="Asia/Tokyo")
_scheduler.add_job(update_all_prices, "cron", hour=9, minute=0, misfire_grace_time=600)
_scheduler.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
