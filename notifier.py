import os

import requests
from dotenv import load_dotenv

load_dotenv()

APP_URL = "http://192.168.1.79:5000"


def _send(message: str) -> None:
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not webhook_url or webhook_url.startswith("https://hooks.slack.com/services/XXX"):
        return
    try:
        requests.post(webhook_url, json={"text": message}, timeout=5)
    except Exception:
        pass


def _format_price(value) -> str:
    if value is None:
        return "不明"
    return f"¥{int(value):,}"


def notify_sale(product_name: str, data: dict) -> None:
    lines = [
        f"*セール開始: {product_name}*",
        f"現在価格: {_format_price(data.get('price'))}",
        f"通常価格: {_format_price(data.get('base_price'))}",
    ]
    if data.get("coupon_discount"):
        lines.append(f"割引額: ¥{int(data['coupon_discount']):,}")
    start = data.get("sale_start_date") or ""
    end = data.get("sale_end_date") or ""
    if start or end:
        lines.append(f"セール期間: {start} 〜 {end}")
    if data.get("stock_level") is not None:
        lines.append(f"在庫数: {data['stock_level']}")
    if data.get("stock_level_status"):
        lines.append(f"在庫状況: {data['stock_level_status']}")
    if data.get("min_order_quantity") is not None:
        lines.append(f"最小注文数: {data['min_order_quantity']}")
    lines.append(f"一覧: {APP_URL}")
    _send("\n".join(lines))


def notify_low_stock(product_name: str, data: dict) -> None:
    lines = [
        f"*在庫わずか: {product_name}*",
        f"現在価格: {_format_price(data.get('price'))}",
        f"通常価格: {_format_price(data.get('base_price'))}",
    ]
    if data.get("stock_level") is not None:
        lines.append(f"在庫数: {data['stock_level']}")
    if data.get("stock_level_status"):
        lines.append(f"在庫状況: {data['stock_level_status']}")
    if data.get("min_order_quantity") is not None:
        lines.append(f"最小注文数: {data['min_order_quantity']}")
    lines.append(f"一覧: {APP_URL}")
    _send("\n".join(lines))
