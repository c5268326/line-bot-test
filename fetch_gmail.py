"""
執行此腳本一次，完成 Gmail 授權並取得 token.json
之後伺服器會自動用 token.json 抓取信件
"""
import os
import json
import base64
import io
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import openpyxl

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"
DATA_FILE = os.path.join("data", "performance.json")

# Excel 欄位對應（之後根據實際欄位調整）
REGION_MAP = {
    "台北一區": "台北一區",
    "台北二區": "台北二區",
    "桃竹苗區": "桃竹苗區",
    "中部地區": "中部地區",
    "南部地區": "南部地區",
}


def get_gmail_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def get_latest_excel(service):
    """找最新一封含 Excel 附件的信"""
    results = service.users().messages().list(
        userId="me",
        q="has:attachment filename:xlsx",
        maxResults=1
    ).execute()

    messages = results.get("messages", [])
    if not messages:
        print("找不到含 Excel 附件的信件")
        return None

    msg = service.users().messages().get(
        userId="me", id=messages[0]["id"]
    ).execute()

    for part in msg["payload"].get("parts", []):
        filename = part.get("filename", "")
        if filename.endswith(".xlsx"):
            attachment_id = part["body"]["attachmentId"]
            attachment = service.users().messages().attachments().get(
                userId="me", messageId=messages[0]["id"], id=attachment_id
            ).execute()
            data = base64.urlsafe_b64decode(attachment["data"])
            print(f"找到附件：{filename}")
            return io.BytesIO(data)

    return None


def parse_excel(file_bytes):
    """
    解析 Excel，回傳各地區數據
    ⚠️ 請根據實際 Excel 格式調整欄位位置
    目前假設格式：
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
        region = str(row[0]).strip() if row[0] else ""
        if region in REGION_MAP:
            results[REGION_MAP[region]] = {
                "實收保費": str(row[1]) if row[1] is not None else "0",
                "實收達成率": str(row[2]) if row[2] is not None else "0%",
                "加權保費": str(row[3]) if row[3] is not None else "0",
                "加權保費達成率": str(row[4]) if row[4] is not None else "0%",
            }
    return results


def update_performance(region_data):
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    for region, values in region_data.items():
        if region in data["regions"]:
            data["regions"][region] = values
            print(f"✅ 更新 {region}：{values}")

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("performance.json 已更新")


def main():
    service = get_gmail_service()
    file_bytes = get_latest_excel(service)
    if file_bytes:
        region_data = parse_excel(file_bytes)
        if region_data:
            update_performance(region_data)
        else:
            print("Excel 內找不到對應地區資料，請確認欄位格式")
    else:
        print("未找到 Excel 附件")


if __name__ == "__main__":
    main()
