"""
用 IMAP 抓取最新業績 Excel，解析後更新 performance.json
"""
import imaplib
import email
import os
import json
import io
from datetime import datetime, timezone, timedelta
import openpyxl
import xlrd

GMAIL_USER = os.environ.get("GMAIL_USER", "wangnanshan33@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "performance.json")

REGIONS = ["全國", "台北一區", "台北二區", "桃竹苗區", "中部地區", "南部地區"]


def get_latest_excel():
    """連線 Gmail IMAP，找最新一封含 xlsx 附件的信"""
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(GMAIL_USER, GMAIL_APP_PASSWORD)
    mail.select("inbox")

    # 只搜尋指定寄件者的信
    SENDERS = [
        "Jessica-YC.Lu@nanshan.com.tw",
        "c5268326@gmail.com",
    ]
    search_query = " ".join([f'FROM "{s}"' for s in SENDERS])
    # IMAP OR 語法
    _, data = mail.search(None, f'(OR FROM "{SENDERS[0]}" FROM "{SENDERS[1]}")')
    mail_ids = data[0].split()

    # 從最新往舊找，找到第一封含 xlsx 或 xls 的信
    for mail_id in reversed(mail_ids):
        _, msg_data = mail.fetch(mail_id, "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])

        for part in msg.walk():
            filename = part.get_filename()
            if filename and (filename.endswith(".xlsx") or filename.endswith(".xls")):
                print(f"找到附件：{filename}")
                file_bytes = part.get_payload(decode=True)
                mail.logout()
                return io.BytesIO(file_bytes), filename

    mail.logout()
    return None, None


def parse_xls(file_bytes):
    """解析舊版 .xls 格式"""
    wb = xlrd.open_workbook(file_contents=file_bytes.read())
    ws = wb.sheet_by_index(0)
    results = {}
    for row_idx in range(1, ws.nrows):
        row = ws.row_values(row_idx)
        region = str(row[0]).strip() if row[0] else ""
        if region in REGIONS:
            results[region] = {
                "實收保費": str(row[1]) if row[1] != "" else "－",
                "實收達成率": str(row[2]) if row[2] != "" else "－",
                "加權保費": str(row[3]) if row[3] != "" else "－",
                "加權保費達成率": str(row[4]) if row[4] != "" else "－",
            }
    return results


def parse_excel(file_bytes):
    """
    解析 Excel 取得各地區業績數據
    ⚠️ 請根據實際 Excel 欄位調整（目前為範例格式）
    假設格式：
      A欄 = 地區名稱
      B欄 = 實收保費
      C欄 = 實收達成率
      D欄 = 加權保費
      E欄 = 加權保費達成率
    """
    wb = openpyxl.load_workbook(file_bytes, data_only=True)
    ws = wb.active

    results = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row[0]:
            continue
        region = str(row[0]).strip()
        if region in REGIONS:
            results[region] = {
                "實收保費": str(row[1]) if row[1] is not None else "－",
                "實收達成率": str(row[2]) if row[2] is not None else "－",
                "加權保費": str(row[3]) if row[3] is not None else "－",
                "加權保費達成率": str(row[4]) if row[4] is not None else "－",
            }
    return results


def update_performance(region_data):
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    for region, values in region_data.items():
        data["regions"][region] = values
        print(f"✅ 更新 {region}")

    TW = timezone(timedelta(hours=8))
    data["updated_at"] = datetime.now(TW).strftime("%Y/%m/%d %H:%M")

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("performance.json 已更新")


def main():
    if not GMAIL_APP_PASSWORD:
        print("❌ 未設定 GMAIL_APP_PASSWORD 環境變數")
        return

    file_bytes, filename = get_latest_excel()
    if file_bytes:
        if filename.endswith(".xls"):
            region_data = parse_xls(file_bytes)
        else:
            region_data = parse_excel(file_bytes)
        if region_data:
            update_performance(region_data)
        else:
            print("⚠️ Excel 內找不到對應地區資料，請確認欄位格式")
    else:
        print("⚠️ 收件匣找不到含 xlsx 附件的信件")


if __name__ == "__main__":
    main()
