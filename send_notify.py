"""執行完成後寄送通知信給管理員"""
import smtplib
import os
import json
from email.mime.text import MIMEText
from datetime import datetime, timezone, timedelta

GMAIL_USER = os.environ.get("GMAIL_USER", "wangnanshan33@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
NOTIFY_TO = "c5268326@gmail.com"
DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "performance.json")

TW = timezone(timedelta(hours=8))
now = datetime.now(TW).strftime("%Y/%m/%d %H:%M")

try:
    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)
    updated = data.get("updated_at", "－")
    today_str = datetime.now(TW).strftime("%Y/%m/%d")
    broadcast = "✅ 已廣播" if data.get("last_broadcast_date") == today_str else "⏭️ 略過廣播"
except Exception:
    updated = "－"
    broadcast = "不明"

body = f"""南山業績 LINE Bot 執行完成

執行時間：{now}
資料時間：{updated}
廣播狀態：{broadcast}

查看執行記錄：
https://github.com/c5268326/line-bot-test/actions
"""

msg = MIMEText(body, "plain", "utf-8")
msg["Subject"] = f"✅ 業績更新完成 {now}"
msg["From"] = GMAIL_USER
msg["To"] = NOTIFY_TO

try:
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        smtp.send_message(msg)
    print("✅ 通知信已寄出")
except Exception as e:
    print(f"⚠️ 通知信寄送失敗：{e}")
