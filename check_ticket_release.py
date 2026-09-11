"""定期檢查寬宏售票（kham.com.tw）票券是否開賣，開賣後推播 LINE 提醒給有追蹤的使用者"""
from datetime import datetime, timedelta, timezone

import requests
from linebot.models import TextSendMessage

from app import line_bot_api
from ticket_tracker import load_tickets, save_tickets

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

# 寬宏售票頁面常見文案關鍵字，用來判斷開賣狀態；若對方網站文案調整需同步更新
NOT_RELEASED_KEYWORDS = ["尚未開賣", "尚未上市", "敬請期待", "即將開賣", "尚未販售"]
SOLD_OUT_KEYWORDS = ["已售完", "完售", "售罄"]
ON_SALE_KEYWORDS = ["立即購票", "選購座位", "選位購票", "馬上購票", "加入購物車", "選擇張數"]
RELEASED_STATUSES = {"on_sale", "sold_out"}

TW = timezone(timedelta(hours=8))


def detect_status(html: str) -> str:
    if any(k in html for k in NOT_RELEASED_KEYWORDS):
        return "not_released"
    if any(k in html for k in ON_SALE_KEYWORDS):
        return "on_sale"
    if any(k in html for k in SOLD_OUT_KEYWORDS):
        return "sold_out"
    return "unknown"


def check_ticket(ticket):
    try:
        resp = requests.get(ticket["url"], headers=HEADERS, timeout=15)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
    except requests.RequestException as e:
        print(f"⚠️ 查詢失敗 {ticket['url']}：{e}")
        return

    old_status = ticket.get("status", "unknown")
    new_status = detect_status(resp.text)
    ticket["status"] = new_status
    ticket["last_checked"] = datetime.now(TW).strftime("%Y/%m/%d %H:%M")

    just_released = new_status in RELEASED_STATUSES and old_status not in RELEASED_STATUSES
    if just_released and ticket.get("user_ids"):
        status_text = "已售完，請盡快確認" if new_status == "sold_out" else "開放購票中"
        message = f"🎫 票券開賣通知！\n狀態：{status_text}\n{ticket['url']}"
        for user_id in ticket["user_ids"]:
            try:
                line_bot_api.push_message(user_id, TextSendMessage(text=message))
            except Exception as e:
                print(f"⚠️ 推播失敗 {user_id}：{e}")


def main():
    data = load_tickets()
    for ticket in data.get("tickets", []):
        check_ticket(ticket)
    save_tickets(data)


if __name__ == "__main__":
    main()
