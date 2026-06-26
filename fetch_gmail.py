"""
用 IMAP 抓取最新業績 Excel，解析後更新 performance.json
"""
import imaplib
import email
from email.header import decode_header
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

DEPARTMENTS = {
    "台北一區": ["北一業展一處", "北一業展二處", "北一業展三處", "北一業展四處", "北一業展五處", "北一業展六處", "北一業展七處"],
    "台北二區": ["北二業展一處", "北二業展二處", "北二業展三處", "北二業展四處", "北二業展五處", "北二業展六處", "北二業展七處"],
    "桃竹苗區": ["桃竹苗業展一處", "桃竹苗業展二處", "桃竹苗業展三處", "桃竹苗業展四處"],
    "中部地區": ["中區業展一處", "中區業展二處", "中區業展三處", "中區業展四處", "中區業展五處", "中區業展六處", "中區業展七處"],
    "南部地區": ["南區業展一處", "南區業展二處", "南區業展三處", "南區業展四處"],
}
ALL_DEPTS = [d for depts in DEPARTMENTS.values() for d in depts]
ALL_NAMES = set(REGIONS) | set(ALL_DEPTS)


def get_latest_excel():
    """連線 Gmail IMAP，找最新一封含 xlsx 附件的信"""
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(GMAIL_USER, GMAIL_APP_PASSWORD)
    mail.select("inbox")

    SENDERS = [
        "Jessica-YC.Lu@nanshan.com.tw",
        "c5268326@gmail.com",
    ]

    # 先嘗試指定寄件者搜尋
    _, data = mail.search(None, f'(OR FROM "{SENDERS[0]}" FROM "{SENDERS[1]}")')
    mail_ids = data[0].split()
    print(f"指定寄件者搜尋結果：{len(mail_ids)} 封")

    # 若找不到，改搜尋全部信件
    if not mail_ids:
        print("改為搜尋全部信件...")
        _, data = mail.search(None, "ALL")
        mail_ids = data[0].split()
        print(f"全部信件數量：{len(mail_ids)} 封")

    # 從最新往舊找，找到第一封含 xlsx 或 xls 的信
    for mail_id in reversed(mail_ids):
        _, msg_data = mail.fetch(mail_id, "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])
        sender = msg.get("From", "")
        subject = msg.get("Subject", "")

        has_attachment = False
        for part in msg.walk():
            raw_filename = part.get_filename()
            if raw_filename:
                # 解碼 MIME 編碼的檔名（如 =?UTF-8?B?...?=）
                decoded_parts = decode_header(raw_filename)
                filename = ""
                for part_bytes, charset in decoded_parts:
                    if isinstance(part_bytes, bytes):
                        filename += part_bytes.decode(charset or "utf-8", errors="replace")
                    else:
                        filename += part_bytes
                print(f"信件寄件者：{sender}，附件：{filename}")
                if filename.endswith(".xlsx") or filename.endswith(".xls"):
                    print(f"找到目標附件：{filename}")
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
                "A&H保費": str(row[3]) if len(row) > 3 and row[3] != "" else "－",
                "A&H達成率": str(row[4]) if len(row) > 4 and row[4] != "" else "－",
                "RP保費": str(row[5]) if len(row) > 5 and row[5] != "" else "－",
                "RP達成率": str(row[6]) if len(row) > 6 and row[6] != "" else "－",
            }
    return results


def parse_excel(file_bytes):
    """
    解析 Excel 取得各地區業績數據
    格式：
      A欄 = 地區名稱
      B欄 = 實收保費
      C欄 = 實收達成率
      D欄 = A&H保費
      E欄 = A&H達成率
      F欄 = RP保費
      G欄 = RP達成率
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
                "A&H保費": str(row[3]) if len(row) > 3 and row[3] is not None else "－",
                "A&H達成率": str(row[4]) if len(row) > 4 and row[4] is not None else "－",
                "RP保費": str(row[5]) if len(row) > 5 and row[5] is not None else "－",
                "RP達成率": str(row[6]) if len(row) > 6 and row[6] is not None else "－",
            }
    return results


def parse_sheet(ws_or_rows, is_xlrd=False):
    """通用解析：7欄格式 A=地區/業展處 B=實收 C=實收達成率 D=A&H E=A&H達成率 F=RP G=RP達成率"""
    results = {}
    rows = ws_or_rows if is_xlrd else list(ws_or_rows)
    for row in rows:
        vals = row if is_xlrd else list(row)
        name = str(vals[0]).strip() if vals[0] else ""
        if name not in ALL_NAMES:
            continue
        def v(i): return str(vals[i]) if len(vals) > i and vals[i] not in (None, "") else "－"
        results[name] = {
            "實收保費": v(1), "實收達成率": v(2),
            "A&H保費": v(3), "A&H達成率": v(4),
            "RP保費": v(5), "RP達成率": v(6),
        }
    return results


def parse_xls(file_bytes):
    wb = xlrd.open_workbook(file_contents=file_bytes.read())
    monthly = parse_sheet([wb.sheet_by_index(0).row_values(i) for i in range(1, wb.sheet_by_index(0).nrows)], is_xlrd=True)
    today = {}
    if wb.nsheets >= 2:
        ws2 = wb.sheet_by_index(1)
        today = parse_sheet([ws2.row_values(i) for i in range(1, ws2.nrows)], is_xlrd=True)
    return monthly, today


def parse_excel(file_bytes):
    wb = openpyxl.load_workbook(file_bytes, data_only=True)
    monthly = parse_sheet(wb.worksheets[0].iter_rows(min_row=2, values_only=True))
    today = {}
    if len(wb.worksheets) >= 2:
        today = parse_sheet(wb.worksheets[1].iter_rows(min_row=2, values_only=True))
    return monthly, today


def update_performance(monthly, today):
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    if "departments" not in data:
        data["departments"] = {r: {} for r in DEPARTMENTS}

    for name, values in monthly.items():
        if name in REGIONS:
            data["regions"][name] = values
            print(f"✅ 本月更新 {name}")
        else:
            for region, depts in DEPARTMENTS.items():
                if name in depts:
                    data["departments"].setdefault(region, {})[name] = values
                    print(f"✅ 本月更新 {name}")
                    break

    if today:
        if "today" not in data:
            data["today"] = {}
        if "today_departments" not in data:
            data["today_departments"] = {r: {} for r in DEPARTMENTS}
        for name, values in today.items():
            if name in REGIONS:
                data["today"][name] = values
                print(f"✅ 今日更新 {name}")
            else:
                for region, depts in DEPARTMENTS.items():
                    if name in depts:
                        data["today_departments"].setdefault(region, {})[name] = values
                        print(f"✅ 今日更新 {name}")
                        break

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
            monthly, today = parse_xls(file_bytes)
        else:
            monthly, today = parse_excel(file_bytes)
        if monthly:
            update_performance(monthly, today)
        else:
            print("⚠️ Excel 內找不到對應地區資料，請確認欄位格式")
    else:
        print("⚠️ 收件匣找不到含 xlsx 附件的信件")


if __name__ == "__main__":
    main()
