from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageSendMessage, FlexSendMessage
import os
import json
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

CHANNEL_ACCESS_TOKEN = os.environ.get(
    "LINE_CHANNEL_ACCESS_TOKEN",
    "SFqZWlkhtiRJXJNHgjO6PEqeHbmgIq3Ww2fO5kiq/25W+8CjFF9bApG9e9/VzuAJSZlPsSs/VUEFWAos4nyKOzAihgrzfkjCz8kxcb7w7ogiw01htnA65RIziuKn/hlaVCjwZCu8orjs0IH0hxY1ZQdB04t89/1O/w1cDnyilFU="
)
CHANNEL_SECRET = os.environ.get(
    "LINE_CHANNEL_SECRET",
    "4a8fa39b484f6ef050fb4c9eb729b4ae"
)

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

GITHUB_RAW_BASE = "https://raw.githubusercontent.com/c5268326/line-bot-test/main/images"

REGION_IMAGES = {
    "全國":    f"{GITHUB_RAW_BASE}/national.png",
    "台北一區": f"{GITHUB_RAW_BASE}/taipei1.png",
    "台北二區": f"{GITHUB_RAW_BASE}/taipei2.png",
    "桃竹苗區": f"{GITHUB_RAW_BASE}/taoyuan.png",
    "中部地區": f"{GITHUB_RAW_BASE}/central.png",
    "南部地區": f"{GITHUB_RAW_BASE}/south.png",
}

DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "performance.json")

HELP_TEXT = (
    "可用指令：\n"
    "・台北一區 / 桃竹苗區 / 中部地區 / 南部地區 / 台北二區 → 業績報表圖片\n"
    "・最新業績 → 查詢各地區業績數字\n"
    "・最新業績圖 → 業績卡片總覽"
)


def load_performance():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def fmt_amount(val):
    """數字加千分位，非數字原樣回傳"""
    try:
        n = float(str(val).replace(",", ""))
        return f"{n:,.0f}"
    except (ValueError, TypeError):
        return val


def fmt_rate(val):
    """確保達成率顯示為百分比格式"""
    s = str(val).strip()
    if s in ("－", "", "None"):
        return "－"
    # 已含 % 直接回傳
    if "%" in s:
        try:
            return f"{float(s.replace('%', '')):.1f}%"
        except ValueError:
            return s
    # 小數格式（如 0.85 → 85.0%）
    try:
        n = float(s)
        if n <= 1.5:
            return f"{n * 100:.1f}%"
        return f"{n:.1f}%"
    except ValueError:
        return s


def parse_rate_float(val):
    """達成率字串轉 float（0~1），失敗回傳 None"""
    s = str(val).strip().replace("%", "")
    try:
        n = float(s)
        return n / 100 if n > 1.5 else n
    except ValueError:
        return None


def progress_bar(rate_float):
    """產生進度條區塊，rate_float 為 0.0~1.0+"""
    pct = max(0.0, min(rate_float, 1.5))  # 上限 150%
    filled = int(pct * 100)
    empty = 100 - filled

    if rate_float >= 1.0:
        color = "#27ae60"   # 綠：達標
    elif rate_float >= 0.8:
        color = "#f39c12"   # 橘：接近
    else:
        color = "#e74c3c"   # 紅：未達

    bar_contents = [{"type": "box", "layout": "vertical", "contents": [], "backgroundColor": color, "flex": filled, "height": "8px", "cornerRadius": "4px"}]
    if empty > 0:
        bar_contents.append({"type": "box", "layout": "vertical", "contents": [], "backgroundColor": "#e0e0e0", "flex": empty, "height": "8px", "cornerRadius": "4px"})

    return {
        "type": "box",
        "layout": "horizontal",
        "contents": bar_contents,
        "margin": "xs",
        "spacing": "xs",
    }


def build_region_row(region, values):
    """產生單一地區的 Flex 區塊"""
    def row(label, val):
        return {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {"type": "text", "text": label, "size": "sm", "color": "#555555", "flex": 3},
                {"type": "text", "text": val, "size": "sm", "color": "#111111", "flex": 4, "align": "end", "weight": "bold"},
            ],
            "margin": "xs",
        }

    收達成率_str = fmt_rate(values["實收達成率"])
    加權達成率_str = fmt_rate(values["加權保費達成率"])
    收達成率_f = parse_rate_float(values["實收達成率"])
    加權達成率_f = parse_rate_float(values["加權保費達成率"])

    contents = [
        {"type": "text", "text": f"【{region}】", "weight": "bold", "size": "md", "color": "#1a5276", "margin": "md"},
        row("實收保費", fmt_amount(values["實收保費"])),
        row("實收達成率", 收達成率_str),
    ]
    if 收達成率_f is not None:
        contents.append(progress_bar(收達成率_f))

    contents += [
        row("加權保費", fmt_amount(values["加權保費"])),
        row("加權達成率", 加權達成率_str),
    ]
    if 加權達成率_f is not None:
        contents.append(progress_bar(加權達成率_f))

    contents.append({"type": "separator", "margin": "md"})

    return {"type": "box", "layout": "vertical", "contents": contents}


def build_flex_message():
    data = load_performance()
    TW = timezone(timedelta(hours=8))
    updated = data.get("updated_at", "－")

    region_blocks = [build_region_row(r, v) for r, v in data["regions"].items()]

    bubble = {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "📊 最新業績總覽", "weight": "bold", "size": "lg", "color": "#ffffff"},
                {"type": "text", "text": f"截至 {updated}", "size": "xs", "color": "#dddddd", "margin": "xs"},
            ],
            "backgroundColor": "#1a5276",
            "paddingAll": "16px",
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": region_blocks,
            "paddingAll": "12px",
            "spacing": "none",
        },
    }

    return FlexSendMessage(alt_text="最新業績總覽", contents=bubble)


def build_performance_text():
    data = load_performance()
    TW = timezone(timedelta(hours=8))
    now = datetime.now(TW).strftime("%Y/%m/%d %H:%M")
    lines = [f"📊 最新業績\n截至 {now}\n"]
    for region, values in data["regions"].items():
        lines.append(
            f"【{region}】\n"
            f"實收保費：{fmt_amount(values['實收保費'])}\n"
            f"實收達成率：{fmt_rate(values['實收達成率'])}\n"
            f"加權保費：{fmt_amount(values['加權保費'])}\n"
            f"加權保費達成率：{fmt_rate(values['加權保費達成率'])}"
        )
    return "\n\n".join(lines)


@app.route("/", methods=["GET"])
def index():
    return "LINE Bot is running."


@app.route("/update", methods=["GET"])
def update():
    """手動觸發抓取最新 Excel 更新業績資料"""
    try:
        from fetch_gmail import main as fetch_main
        fetch_main()
        return "✅ 業績資料已更新", 200
    except Exception as e:
        return f"❌ 更新失敗：{str(e)}", 500


@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()

    if text == "最新業績圖":
        line_bot_api.reply_message(
            event.reply_token,
            build_flex_message()
        )
    elif text == "最新業績":
        reply = build_performance_text()
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply)
        )
    elif text in REGION_IMAGES:
        url = REGION_IMAGES[text]
        line_bot_api.reply_message(
            event.reply_token,
            ImageSendMessage(
                original_content_url=url,
                preview_image_url=url
            )
        )
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=HELP_TEXT)
        )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
