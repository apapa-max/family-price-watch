import re
import sqlite3
from datetime import datetime

import requests

from notifier import notify_low_stock, notify_sale

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

    return {
        "price": price,
        "base_price": base_price,
        "coupon_discount": coupon.get("discountValue"),
        "sale_start_date": coupon.get("localDiscountStartDate"),
        "sale_end_date": coupon.get("localDiscountEndDate"),
        "stock_level": stock.get("stockLevel"),
        "stock_level_status": stock.get("stockLevelStatus"),
        "min_order_quantity": d.get("minOrderQuantity"),
    }


def _extract_item_code(url: str) -> str | None:
    m = re.search(r"/p/(\d+)", url or "")
    return m.group(1) if m else None


def update_all_prices() -> int:
    """アクティブなCostco商品の価格を一括更新。更新件数を返す。"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    products = conn.execute(
        """SELECT id, name, url, target_price, is_sale_notified, is_stock_notified
           FROM products
           WHERE is_active = 1 AND site LIKE '%Costco%'"""
    ).fetchall()

    updated = 0
    now = datetime.now().isoformat()

    for p in products:
        item_code = _extract_item_code(p["url"])
        if not item_code:
            continue
        data = fetch_costco_data(item_code)
        if data is None or data["price"] is None:
            continue

        price = data["price"]
        base_price = data["base_price"]
        is_sale = base_price is not None and price < base_price
        is_sale_notified = p["is_sale_notified"]
        is_stock_notified = p["is_stock_notified"]
        new_target = min(p["target_price"], price) if p["target_price"] else price

        # セール通知
        if is_sale and not is_sale_notified:
            notify_sale(p["name"], data)
            is_sale_notified = 1
        elif not is_sale and is_sale_notified:
            # 通常価格に戻ったのでフラグをリセット
            is_sale_notified = 0

        # 在庫わずか通知
        stock_level = data["stock_level"]
        if stock_level is not None and stock_level <= STOCK_ALERT_THRESHOLD and not is_stock_notified:
            notify_low_stock(p["name"], data)
            is_stock_notified = 1

        conn.execute(
            """UPDATE products
               SET current_price      = ?,
                   target_price       = ?,
                   base_price         = ?,
                   sale_end_date      = ?,
                   is_sale_notified   = ?,
                   is_stock_notified  = ?,
                   last_checked       = ?,
                   updated_at         = ?
               WHERE id = ?""",
            (
                price,
                new_target,
                base_price,
                data["sale_end_date"],
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
        updated += 1

    conn.commit()
    conn.close()
    return updated
