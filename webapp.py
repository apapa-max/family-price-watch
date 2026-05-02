from flask import Flask, render_template, request, redirect, url_for, jsonify
import sqlite3
from datetime import datetime
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)
DB_PATH = "family_price_watch.db"


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
        site        = request.form.get("site", "").strip()
        name        = request.form.get("name", "").strip()
        url         = request.form.get("url", "").strip()
        target_price = request.form.get("target_price", "").strip()
        created_by  = request.form.get("created_by", "").strip()

        # --- バリデーション ---
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
        if not created_by:
            errors["created_by"] = "追加者を入力してください"

        if not errors:
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

        # エラー時は入力値を保持して再表示
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
    url = f"https://www.costco.co.jp/ProductPage/{code}"
    try:
        resp = requests.get(url, headers=_COSTCO_HEADERS, timeout=6)
        soup = BeautifulSoup(resp.text, "html.parser")
        name = None
        for sel in ["h1.page-title span", "h1.product-name", "h1", "title"]:
            el = soup.select_one(sel)
            if el:
                text = el.get_text(strip=True)
                if text and "costco" not in text.lower():
                    name = text
                    break
        return jsonify({"name": name, "url": url})
    except Exception:
        return jsonify({"name": None, "url": url})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
