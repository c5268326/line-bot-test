"""
用 IMAP 抓取最新業績 Excel，解析後更新 performance.json，並廣播推播最新業績
"""
import imaplib
import email
from email.header import decode_header
import os
import json
import io
import requests
from datetime import datetime, timezone, timedelta
import openpyxl
import xlrd

GMAIL_USER = os.environ.get("GMAIL_USER", "wangnanshan33@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get(
    "LINE_CHANNEL_ACCESS_TOKEN",
    "SFqZWlkhtiRJXJNHgjO6PEqeHbmgIq3Ww2fO5kiq/25W+8CjFF9bApG9e9/VzuAJSZlPsSs/VUEFWAos4nyKOzAihgrzfkjCz8kxcb7w7ogiw01htnA65RIziuKn/hlaVCjwZCu8orjs0IH0hxY1ZQdB04t89/1O/w1cDnyilFU="
)

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


# 新格式：Excel 地區名稱 → 系統地區名稱
REGION_NAME_MAP = {
    "北一業發部": "台北一區",
    "北二業發部": "台北二區",
    "桃竹苗業發部": "桃竹苗區",
    "中區業發部": "中部地區",
    "南區業發部": "南部地區",
    "合計": "全國",
}

# 新格式：各地區業展處在 all_rows 中的起始列索引與數量（0-based）
# 地區列：rows 2-7（0-based），業展處：rows 11-39（0-based）
DEPT_ROW_MAP = {
    "台北一區":  (11, 7),
    "台北二區":  (18, 7),
    "桃竹苗區":  (25, 4),
    "中部地區":  (29, 7),
    "南部地區":  (36, 4),
}


def _extract_new_format(row, today=False):
    """從新格式列擷取業績欄位"""
    def v(i):
        val = row[i] if len(row) > i else None
        return str(val) if val not in (None, "") else "－"

    if today:
        # col 8=當日實收, 9=當日實收率, 10=當日A&H, 11=當日A&H率, 12=當日RP, 13=當日RP率
        return {"實收保費": v(8), "實收達成率": v(9), "A&H保費": v(10), "A&H達成率": v(11), "RP保費": v(12), "RP達成率": v(13)}
    else:
        # col 17=本月實收, 18=本月實收率, 23=A&H, 24=A&H率, 27=期繳, 28=期繳率
        return {"實收保費": v(17), "實收達成率": v(18), "A&H保費": v(23), "A&H達成率": v(24), "RP保費": v(27), "RP達成率": v(28)}


def _parse_new_format(all_rows):
    """解析新版單工作表格式（業發部_業展處_三時段整點）"""
    monthly = {}
    today = {}

    # 地區列 rows 2-7（含合計）
    for row in all_rows[2:8]:
        raw = str(row[0]).strip() if row[0] else ""
        sys_name = REGION_NAME_MAP.get(raw)
        if sys_name:
            monthly[sys_name] = _extract_new_format(row, today=False)
            today[sys_name] = _extract_new_format(row, today=True)
            print(f"✅ 地區：{raw} → {sys_name}")

    # 業展處列（依位置對應部門名稱）
    for region, (start_idx, count) in DEPT_ROW_MAP.items():
        dept_names = DEPARTMENTS[region]
        for i, row in enumerate(all_rows[start_idx:start_idx + count]):
            if i >= len(dept_names):
                break
            dept_name = dept_names[i]
            monthly[dept_name] = _extract_new_format(row, today=False)
            today[dept_name] = _extract_new_format(row, today=True)
            print(f"✅ 業展處：{region}[{i+1}] → {dept_name}")

    return monthly, today


def parse_xls(file_bytes):
    wb = xlrd.open_workbook(file_contents=file_bytes.read())
    all_rows = [wb.sheet_by_index(0).row_values(i) for i in range(wb.sheet_by_index(0).nrows)]
    return _parse_new_format(all_rows)


def parse_excel(file_bytes):
    wb = openpyxl.load_workbook(file_bytes, data_only=True)
    all_rows = list(wb.worksheets[0].iter_rows(values_only=True))
    print(f"工作表：{wb.worksheets[0].title}，共 {len(all_rows)} 列")
    return _parse_new_format(all_rows)


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
        # 更新前保留昨日資料
        if data.get("today"):
            data["yesterday"] = data["today"]
        if data.get("today_departments"):
            data["yesterday_departments"] = data["today_departments"]
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


def fmt_amount(val):
    try:
        n = float(str(val).replace(",", ""))
        return f"{n:,.0f}"
    except (ValueError, TypeError):
        return val


def fmt_rate(val):
    s = str(val).strip()
    if s in ("－", "", "None"):
        return "－"
    if "%" in s:
        try:
            return f"{float(s.replace('%', '')):.1f}%"
        except ValueError:
            return s
    try:
        n = float(s)
        if n <= 1.5:
            return f"{n * 100:.1f}%"
        return f"{n:.1f}%"
    except ValueError:
        return s


def parse_rate_float(val):
    s = str(val).strip().replace("%", "")
    try:
        n = float(s)
        return n / 100 if n > 1.5 else n
    except ValueError:
        return None


def broadcast_performance():
    """廣播最新業績 Flex Message 給所有使用者"""
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    regions = data.get("regions", {})
    updated = data.get("updated_at", "－")
    national = regions.get("全國", {})

    def rate_color(val, nat_key):
        f = parse_rate_float(val)
        nf = parse_rate_float(national.get(nat_key, "0"))
        if f is not None and nf is not None and f < nf:
            return "#e74c3c"
        return "#111111"

    def make_row(label, amount, rate_val, nat_key, is_national=False):
        color = "#111111" if is_national else rate_color(rate_val, nat_key)
        return {
            "type": "box", "layout": "horizontal",
            "contents": [
                {"type": "text", "text": label, "size": "sm", "color": "#666666", "flex": 2},
                {"type": "text", "text": fmt_amount(amount), "size": "sm", "color": "#222222", "flex": 4, "align": "end", "weight": "bold"},
                {"type": "text", "text": fmt_rate(rate_val), "size": "sm", "color": color, "flex": 3, "align": "end", "weight": "bold"},
            ],
            "margin": "xs",
        }

    blocks = []
    for region, vals in regions.items():
        is_nat = (region == "全國")
        blocks.append({"type": "text", "text": f"【{region}】", "weight": "bold", "size": "md", "color": "#1a5276", "margin": "md"})
        blocks.append(make_row("實收", vals.get("實收保費", "－"), vals.get("實收達成率", "－"), "實收達成率", is_nat))
        blocks.append(make_row("A&H", vals.get("A&H保費", "－"), vals.get("A&H達成率", "－"), "A&H達成率", is_nat))
        blocks.append(make_row("RP", vals.get("RP保費", "－"), vals.get("RP達成率", "－"), "RP達成率", is_nat))
        blocks.append({"type": "separator", "margin": "md"})

    flex_message = {
        "type": "flex",
        "altText": "📊 最新業績更新通知",
        "contents": {
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box", "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "📊 最新業績更新通知", "weight": "bold", "size": "lg", "color": "#1a5276"},
                    {"type": "text", "text": f"截至 {updated}", "size": "xs", "color": "#888888", "margin": "xs"},
                ],
                "backgroundColor": "#EBF5FB",
                "paddingAll": "16px",
            },
            "body": {
                "type": "box", "layout": "vertical",
                "contents": blocks,
                "paddingAll": "12px",
                "spacing": "none",
            },
        },
    }

    resp = requests.post(
        "https://api.line.me/v2/bot/message/broadcast",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        },
        json={"messages": [flex_message]},
    )
    if resp.status_code == 200:
        print("✅ 廣播推播成功")
    else:
        print(f"⚠️ 廣播推播失敗：{resp.status_code} {resp.text}")


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
            broadcast_performance()
        else:
            print("⚠️ Excel 內找不到對應地區資料，請確認欄位格式")
    else:
        print("⚠️ 收件匣找不到含 xlsx 附件的信件")


if __name__ == "__main__":
    main()
