import json
import re
import sqlite3
import subprocess
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from notifier import notify_low_stock, notify_sale, notify_stock_restocked, notify_target_price

DB_PATH = "family_price_watch.db"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja-JP,ja;q=0.9",
}

STOCK_ALERT_THRESHOLD = 50

UNAVAILABLE_STOCK_KEYWORDS = (
    "予定数の販売を終了しました",
    "販売を終了しました",
    "販売休止中です",
    "お取り扱いを終了しました",
    "在庫なし",
    "品切れ",
    "完売",
)

AVAILABLE_STOCK_KEYWORDS = (
    "在庫あり",
    "在庫残少",
    "ご注文はお早めに",
    "お取り寄せ",
    "予約受付中",
)

YODOBASHI_API_TIMEOUT = 25


def fetch_costco_data(item_code: str) -> dict | None:
    """Costco APIから価格・在庫・クーポン情報を取得。失敗時はNoneを返す。"""
    url = (
        f"https://www.costco.co.jp/rest/v2/japan/products/{item_code}/"
        f"?fields=FULL&lang=ja&curr=JPY"
    )
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        d = resp.json()
    except Exception:
        return None

    price = (d.get("price") or {}).get("value")
    base_price = (d.get("basePrice") or {}).get("value")
    coupon = d.get("couponDiscount") or {}
    stock = d.get("stock") or {}
    name = _clean_text(d.get("name") or d.get("productName") or d.get("displayName") or "")

    return {
        "price": price,
        "base_price": base_price,
        "coupon_discount": coupon.get("discountValue"),
        "sale_start_date": coupon.get("localDiscountStartDate"),
        "sale_end_date": coupon.get("localDiscountEndDate"),
        "stock_level": stock.get("stockLevel"),
        "stock_level_status": stock.get("stockLevelStatus"),
        "min_order_quantity": d.get("minOrderQuantity"),
        "name": name or None,
    }


def _parse_yen(text: str) -> int | None:
    m = re.search(r"[￥¥]\s*([0-9,]+)", text or "")
    return int(m.group(1).replace(",", "")) if m else None


def _parse_jsonp(text: str) -> dict | None:
    m = re.search(r"^[^(]*\((.*)\)\s*;?\s*$", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _first_text(soup: BeautifulSoup, selectors: list[str]) -> str | None:
    for selector in selectors:
        el = soup.select_one(selector)
        if el:
            text = _clean_text(el.get_text(" ", strip=True))
            if text:
                return text
    return None


def _extract_yodobashi_stock_status(text: str) -> str | None:
    for keyword in UNAVAILABLE_STOCK_KEYWORDS + AVAILABLE_STOCK_KEYWORDS:
        if keyword in text:
            return keyword
    return None


def is_yodobashi_available(status: str | None) -> bool:
    return bool(status) and any(keyword in status for keyword in AVAILABLE_STOCK_KEYWORDS)


def _extract_yodobashi_item_code(url: str) -> str | None:
    m = re.search(r"/product/(\d+)", url or "")
    return m.group(1) if m else None


def _fetch_yodobashi_api_text(item_code: str) -> str | None:
    url = f"https://www.yodobashi.com/ws/api/ec/products-noukikaitou?sku={item_code}"
    script = """
const url = process.argv[1];
const ac = new AbortController();
const timer = setTimeout(() => ac.abort(), 20000);
fetch(url, {
  headers: {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ja-JP,ja;q=0.9"
  },
  signal: ac.signal
}).then(async response => {
  clearTimeout(timer);
  if (!response.ok) {
    console.error(`HTTP ${response.status}`);
    process.exit(2);
  }
  process.stdout.write(await response.text());
}).catch(error => {
  clearTimeout(timer);
  console.error(`${error.name}: ${error.message}`);
  process.exit(1);
});
"""
    try:
        result = subprocess.run(
            ["node", "-e", script, url],
            capture_output=True,
            text=True,
            timeout=YODOBASHI_API_TIMEOUT,
            check=False,
        )
    except Exception as e:
        print(
            f"[family-price-watch] Yodobashi API node failed: {url} "
            f"({type(e).__name__}: {e})",
            flush=True,
        )
        return None
    if result.returncode != 0:
        print(
            f"[family-price-watch] Yodobashi API failed: {url} "
            f"({result.stderr.strip()})",
            flush=True,
        )
        return None
    return result.stdout


def fetch_yodobashi_api_data(item_code: str) -> dict | None:
    text = _fetch_yodobashi_api_text(item_code)
    payload = _parse_jsonp(text or "")
    if not payload or payload.get("status") != "0":
        return None
    items = payload.get("item") or []
    if not items:
        return None
    item = items[0]
    price = _parse_yen(item.get("salesPrice") or "")
    if price is None:
        return None
    brand_name = _clean_text(item.get("brandName") or "")
    product_name = _clean_text(item.get("productName") or "")
    name = " ".join(part for part in [brand_name, product_name] if part)
    return {
        "price": price,
        "base_price": None,
        "coupon_discount": None,
        "sale_start_date": None,
        "sale_end_date": None,
        "stock_level": None,
        "stock_level_status": item.get("stockMessage"),
        "min_order_quantity": None,
        "name": name or None,
        "url": f"https://www.yodobashi.com/product/{item_code}/",
    }


def fetch_yodobashi_data(url: str) -> dict | None:
    """ヨドバシの商品ページから価格・在庫文言を取得。失敗時はNoneを返す。"""
    item_code = _extract_yodobashi_item_code(url)
    if item_code:
        api_data = fetch_yodobashi_api_data(item_code)
        if api_data is not None:
            return api_data

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=(5, 20))
        resp.raise_for_status()
    except Exception as e:
        print(
            f"[family-price-watch] Yodobashi fetch failed: {url} "
            f"({type(e).__name__}: {e})",
            flush=True,
        )
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    page_text = _clean_text(soup.get_text(" ", strip=True))

    price_text = _first_text(
        soup,
        [
            "#js_scl_unitPrice",
            ".productPrice",
            ".price",
            ".js_productPrice",
            "[class*=price]",
        ],
    )
    price = _parse_yen(price_text or "") or _parse_yen(page_text)
    if price is None:
        print(
            f"[family-price-watch] Yodobashi price not found: {url}",
            flush=True,
        )
        return None

    name = _first_text(
        soup,
        [
            "h1",
            ".productName",
            "#products_maintitle",
            "title",
        ],
    )
    stock_status = _extract_yodobashi_stock_status(page_text)

    return {
        "price": price,
        "base_price": None,
        "coupon_discount": None,
        "sale_start_date": None,
        "sale_end_date": None,
        "stock_level": None,
        "stock_level_status": stock_status,
        "min_order_quantity": None,
        "name": name,
        "url": url,
    }


def _extract_item_code(url: str) -> str | None:
    m = re.search(r"/p/(\d+)", url or "")
    return m.group(1) if m else None


def _fetch_product_data(p: sqlite3.Row) -> dict | None:
    site = (p["site"] or "").lower()
    if "costco" in site:
        item_code = _extract_item_code(p["url"])
        if not item_code:
            return None
        return fetch_costco_data(item_code)
    if "ヨドバシ" in p["site"] or "yodobashi" in site:
        return fetch_yodobashi_data(p["url"])
    return None


def _get_history_max_price(conn, product_id: int, fallback_price) -> float | None:
    row = conn.execute(
        "SELECT MAX(price) AS max_price FROM price_history WHERE product_id = ?",
        (product_id,),
    ).fetchone()
    values = [fallback_price]
    if row and row["max_price"] is not None:
        values.append(row["max_price"])
    return max(values) if values else None


def _update_product(conn, p: sqlite3.Row, now: str) -> bool:
    old_stock_status = p["stock_level_status"]
    data = _fetch_product_data(p)
    if data is None or data["price"] is None:
        return False

    site = (p["site"] or "").lower()
    price = data["price"]
    base_price = data["base_price"]
    product_name = data.get("name") or p["name"]
    is_costco = "costco" in site
    if not is_costco:
        history_base = _get_history_max_price(conn, p["id"], price)
        if p["current_price"] is not None:
            history_base = max(history_base or price, p["current_price"])
        base_price = max(history_base or price, price)
        data["base_price"] = base_price
        data["coupon_discount"] = max(base_price - price, 0)
    is_sale = (
        base_price is not None and price < base_price
        if is_costco
        else p["target_price"] is not None and price <= p["target_price"]
    )
    is_sale_notified = p["is_sale_notified"]
    is_stock_notified = p["is_stock_notified"]
    new_target = min(p["target_price"], price) if p["target_price"] else None

    # セール通知
    if is_sale and not is_sale_notified:
        if is_costco:
            notify_sale(product_name, data)
        else:
            notify_target_price(product_name, data, p["target_price"])
        is_sale_notified = 1
    elif not is_sale and is_sale_notified:
        # 通常価格に戻ったのでフラグをリセット
        is_sale_notified = 0

    # 在庫わずか通知
    stock_level = data["stock_level"]
    if stock_level is not None and stock_level <= STOCK_ALERT_THRESHOLD and not is_stock_notified:
        notify_low_stock(product_name, data)
        is_stock_notified = 1
    elif stock_level is None:
        was_unavailable = old_stock_status and not is_yodobashi_available(old_stock_status)
        is_available = is_yodobashi_available(data["stock_level_status"])
        if was_unavailable and is_available and not is_stock_notified:
            notify_stock_restocked(product_name, data)
            is_stock_notified = 1
        elif not is_available:
            is_stock_notified = 0

    conn.execute(
        """UPDATE products
           SET name               = ?,
               current_price      = ?,
               target_price       = ?,
               base_price         = ?,
               coupon_discount    = ?,
               sale_end_date      = ?,
               stock_level        = ?,
               stock_level_status = ?,
               min_order_quantity = ?,
               is_sale_notified   = ?,
               is_stock_notified  = ?,
               last_checked       = ?,
               updated_at         = ?
           WHERE id = ?""",
        (
            product_name,
            price,
            new_target,
            base_price,
            data["coupon_discount"],
            data["sale_end_date"],
            data["stock_level"],
            data["stock_level_status"],
            data["min_order_quantity"],
            is_sale_notified,
            is_stock_notified,
            now,
            now,
            p["id"],
        ),
    )
    conn.execute(
        "INSERT INTO price_history (product_id, price, checked_at) VALUES (?, ?, ?)",
        (p["id"], price, now),
    )
    return True


def update_product_price(product_id: int) -> bool:
    """指定したアクティブ商品の価格を更新。成功時はTrue。"""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    product = conn.execute(
        """SELECT id, site, name, url, current_price, target_price,
                  is_sale_notified, is_stock_notified,
                  stock_level_status
           FROM products
           WHERE id = ? AND is_active = 1
             AND (site LIKE '%Costco%' OR site LIKE '%ヨドバシ%' OR site LIKE '%Yodobashi%')""",
        (product_id,),
    ).fetchone()
    updated = False
    if product:
        updated = _update_product(conn, product, datetime.now().isoformat())
    conn.commit()
    conn.close()
    return updated


def update_all_prices() -> int:
    """アクティブ商品の価格を一括更新。更新件数を返す。"""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    products = conn.execute(
        """SELECT id, site, name, url, current_price, target_price,
                  is_sale_notified, is_stock_notified,
                  stock_level_status
           FROM products
           WHERE is_active = 1
             AND (site LIKE '%Costco%' OR site LIKE '%ヨドバシ%' OR site LIKE '%Yodobashi%')"""
    ).fetchall()

    updated = 0
    now = datetime.now().isoformat()

    for p in products:
        if _update_product(conn, p, now):
            updated += 1

    conn.commit()
    conn.close()
    return updated
