from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageSendMessage
import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo

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
    "・最新業績 → 查詢各地區業績數字"
)


def load_performance():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def build_performance_text():
    data = load_performance()
    now = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y/%m/%d %H:%M")
    lines = [f"📊 最新業績\n截至 {now}\n"]
    for region, values in data["regions"].items():
        lines.append(
            f"【{region}】\n"
            f"實收保費：{values['實收保費']}\n"
            f"實收達成率：{values['實收達成率']}\n"
            f"加權保費：{values['加權保費']}\n"
            f"加權保費達成率：{values['加權保費達成率']}"
        )
    return "\n\n".join(lines)


@app.route("/", methods=["GET"])
def index():
    return "LINE Bot is running."


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

    if text == "最新業績":
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
