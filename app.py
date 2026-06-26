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
    "・最新業績圖 → 業績卡片總覽\n"
    "・本月達成率排名 → 本月三項達成率地區排名\n"
    "・今日達成率排名 → 今日三項達成率地區排名\n"
    "・今日速報 → 今日新增保費速報\n"
    "・本月速報 → 本月累積保費速報"
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


def progress_bar(rate_float, national_rate=None):
    """產生進度條區塊，rate_float 為 0.0~1.0+"""
    pct = max(0.0, min(rate_float, 1.5))  # 上限 150%
    filled = int(pct * 100)
    empty = 100 - filled

    if national_rate is not None:
        color = "#e74c3c" if rate_float < national_rate else "#27ae60"
    else:
        color = "#333333"

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


def build_region_row(region, values, national=None):
    """產生單一地區的 Flex 區塊，national 傳入全國數值用於達成率比較"""
    def rate_color(val, nat_key):
        if region == "全國" or national is None:
            return "#111111"
        f = parse_rate_float(val)
        nf = parse_rate_float(national.get(nat_key, "0"))
        if f is not None and nf is not None and f < nf:
            return "#e74c3c"
        return "#111111"

    def row(label, amount, rate_val, nat_key):
        return {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {"type": "text", "text": label, "size": "sm", "color": "#555555", "flex": 2},
                {"type": "text", "text": amount, "size": "sm", "color": "#111111", "flex": 4, "align": "end", "weight": "bold"},
                {"type": "text", "text": fmt_rate(rate_val), "size": "sm", "color": rate_color(rate_val, nat_key), "flex": 3, "align": "end", "weight": "bold"},
            ],
            "margin": "xs",
        }

    contents = [
        {"type": "text", "text": f"【{region}】", "weight": "bold", "size": "md", "color": "#1a5276", "margin": "md"},
        row("實收", fmt_amount(values["實收保費"]), values["實收達成率"], "實收達成率"),
        row("A&H", fmt_amount(values.get("A&H保費", "－")), values.get("A&H達成率", "－"), "A&H達成率"),
        row("RP", fmt_amount(values.get("RP保費", "－")), values.get("RP達成率", "－"), "RP達成率"),
        {"type": "separator", "margin": "md"},
    ]

    return {"type": "box", "layout": "vertical", "contents": contents}


RANK_EMOJI = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]

REGION_SHORT = {
    "全國": "全國",
    "台北一區": "北一",
    "台北二區": "北二",
    "桃竹苗區": "桃竹苗",
    "中部地區": "中區",
    "南部地區": "南區",
}


def to_yi(val):
    """數字轉億（保留兩位小數）"""
    try:
        n = float(str(val).replace(",", ""))
        return f"{n / 1e8:.2f}億"
    except (ValueError, TypeError):
        return val


def build_ranking_flex(source_key="regions", title="📊 本月達成率排名"):
    data = load_performance()
    source = data.get(source_key, data["regions"])
    regions = {r: v for r, v in source.items() if r != "全國"}
    updated = data.get("updated_at", "－")

    def rank_section_block(section_title, key):
        scored = []
        for r, v in regions.items():
            f = parse_rate_float(v.get(key, "0"))
            if f is not None:
                scored.append((r, f))
        scored.sort(key=lambda x: x[1], reverse=True)
        national_rate = fmt_rate(source.get("全國", {}).get(key, "0"))
        national_f = parse_rate_float(source.get("全國", {}).get(key, "0"))

        rows = [
            {
                "type": "box",
                "layout": "horizontal",
                "contents": [
                    {"type": "text", "text": f"🔥 {section_title}", "weight": "bold", "size": "sm", "color": "#1a5276", "flex": 5},
                    {"type": "text", "text": f"全國 {national_rate}", "size": "sm", "color": "#555555", "flex": 3, "align": "end"},
                ],
                "margin": "md",
            }
        ]
        for i, (r, f) in enumerate(scored):
            emoji = RANK_EMOJI[i] if i < len(RANK_EMOJI) else f"{i+1}."
            short = REGION_SHORT.get(r, r)
            rate_color = "#e74c3c" if (national_f is not None and f < national_f) else "#111111"
            rows.append({
                "type": "box",
                "layout": "horizontal",
                "contents": [
                    {"type": "text", "text": emoji, "size": "sm", "flex": 1},
                    {"type": "text", "text": short, "size": "sm", "color": "#333333", "flex": 3},
                    {"type": "text", "text": fmt_rate(f), "size": "sm", "color": rate_color, "flex": 3, "align": "end", "weight": "bold"},
                ],
                "margin": "xs",
            })
        rows.append({"type": "separator", "margin": "md"})
        return rows

    body_contents = []
    for section_title, key in [("A&H達成率", "A&H達成率"), ("RP達成率", "RP達成率"), ("實收達成率", "實收達成率")]:
        body_contents.extend(rank_section_block(section_title, key))

    bubble = {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": title, "weight": "bold", "size": "lg", "color": "#ffffff"},
                {"type": "text", "text": f"截至 {updated}", "size": "xs", "color": "#dddddd", "margin": "xs"},
            ],
            "backgroundColor": "#1a5276",
            "paddingAll": "16px",
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": body_contents,
            "paddingAll": "12px",
            "spacing": "none",
        },
    }
    return FlexSendMessage(alt_text=title, contents=bubble)


def build_speed_report(source_key, label):
    data = load_performance()
    source = data.get(source_key, data.get("regions", {}))
    national = source.get("全國", {})
    updated = data.get("updated_at", "－")

    ah = to_yi(national.get("A&H保費", "0"))
    rp = to_yi(national.get("RP保費", "0"))
    total = to_yi(national.get("實收保費", "0"))
    ah_rate = fmt_rate(national.get("A&H達成率", "0"))
    rp_rate = fmt_rate(national.get("RP達成率", "0"))
    total_rate = fmt_rate(national.get("實收達成率", "0"))

    return (
        f"📊 {label}\n截至 {updated}\n\n"
        f"🌐 全國\n"
        f"A&H　{ah}　({ah_rate})\n"
        f"RP　　{rp}　({rp_rate})\n"
        f"實收　{total}　({total_rate})"
    )


def build_flex_from_source(source_regions, title, alt_text):
    data = load_performance()
    updated = data.get("updated_at", "－")
    national = source_regions.get("全國", {})
    region_blocks = [build_region_row(r, v, national=national) for r, v in source_regions.items()]
    bubble = {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": title, "weight": "bold", "size": "lg", "color": "#ffffff"},
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
    return FlexSendMessage(alt_text=alt_text, contents=bubble)


def build_flex_message():
    data = load_performance()
    return build_flex_from_source(data["regions"], "📊 今日最新業績速報", "最新業績總覽")


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
            f"A&H保費：{fmt_amount(values.get('A&H保費', '－'))}\n"
            f"A&H達成率：{fmt_rate(values.get('A&H達成率', '－'))}\n"
            f"RP保費：{fmt_amount(values.get('RP保費', '－'))}\n"
            f"RP達成率：{fmt_rate(values.get('RP達成率', '－'))}"
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

    if text == "本月達成率排名":
        line_bot_api.reply_message(
            event.reply_token,
            build_ranking_flex("regions", "📊 本月達成率排名")
        )
    elif text == "今日達成率排名":
        line_bot_api.reply_message(
            event.reply_token,
            build_ranking_flex("today", "📊 今日達成率排名")
        )
    elif text == "今日速報":
        data = load_performance()
        line_bot_api.reply_message(
            event.reply_token,
            build_flex_from_source(data.get("today", data["regions"]), "📊 今日速報", "今日速報")
        )
    elif text == "本月速報":
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=build_speed_report("regions", "本月累積速報"))
        )
    elif text == "最新業績圖":
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
