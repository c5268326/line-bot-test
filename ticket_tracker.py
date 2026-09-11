"""追蹤票資料存取與寬宏售票網址解析共用邏輯"""
import json
import os
from urllib.parse import parse_qs, urlparse

DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "ticket_tracking.json")

ALLOWED_HOSTS = {"kham.com.tw", "www.kham.com.tw"}

STATUS_LABELS = {
    "not_released": "⚪ 尚未開賣",
    "on_sale": "🟢 已開賣",
    "sold_out": "🔴 已售完",
    "unknown": "❓ 狀態未知",
}


def load_tickets():
    if not os.path.exists(DATA_FILE):
        return {"tickets": []}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_tickets(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def extract_ticket_params(url):
    """從寬宏售票網址取出 PERFORMANCE_ID / PRODUCT_ID，非寬宏網址回傳 None"""
    parsed = urlparse(url.strip())
    if parsed.netloc.lower() not in ALLOWED_HOSTS:
        return None
    qs = parse_qs(parsed.query)
    performance_id = qs.get("PERFORMANCE_ID", [None])[0]
    product_id = qs.get("PRODUCT_ID", [None])[0]
    if not performance_id or not product_id:
        return None
    return performance_id, product_id


def find_ticket(data, performance_id, product_id):
    for ticket in data["tickets"]:
        if ticket["performance_id"] == performance_id and ticket["product_id"] == product_id:
            return ticket
    return None


def add_tracking(url, user_id):
    """加入追蹤，回傳 (錯誤訊息或 None, ticket 或 None)"""
    params = extract_ticket_params(url)
    if not params:
        return "❌ 請提供正確的寬宏售票（kham.com.tw）票券網址", None

    performance_id, product_id = params
    data = load_tickets()
    ticket = find_ticket(data, performance_id, product_id)
    if ticket is None:
        ticket = {
            "performance_id": performance_id,
            "product_id": product_id,
            "url": url.strip(),
            "status": "unknown",
            "last_checked": None,
            "user_ids": [],
        }
        data["tickets"].append(ticket)

    if user_id and user_id not in ticket["user_ids"]:
        ticket["user_ids"].append(user_id)

    save_tickets(data)
    return None, ticket


def remove_tracking(url, user_id):
    params = extract_ticket_params(url)
    if not params:
        return "❌ 請提供正確的寬宏售票（kham.com.tw）票券網址"

    performance_id, product_id = params
    data = load_tickets()
    ticket = find_ticket(data, performance_id, product_id)
    if ticket is None or user_id not in ticket.get("user_ids", []):
        return "⚠️ 你尚未追蹤這張票券"

    ticket["user_ids"].remove(user_id)
    save_tickets(data)
    return "✅ 已取消追蹤"


def list_tracking_for_user(user_id):
    data = load_tickets()
    return [t for t in data["tickets"] if user_id in t.get("user_ids", [])]
