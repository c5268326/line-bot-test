from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, ImageSendMessage,
    FlexSendMessage, StickerSendMessage,
    QuickReply, QuickReplyButton, MessageAction
)
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
    "全國": f"{GITHUB_RAW_BASE}/national.png",
}

DEPARTMENT_MANAGERS = {
    "北一業展一處": "蔡信宏", "北一業展二處": "陳俊廷", "北一業展三處": "許哲維",
    "北一業展四處": "黃琮暉", "北一業展五處": "黃啟源", "北一業展六處": "阮玉蘭", "北一業展七處": "林正佳",
    "北二業展一處": "李易修", "北二業展二處": "謝至偉", "北二業展三處": "陳勝隆",
    "北二業展四處": "張雪熙", "北二業展五處": "黃怡叡", "北二業展六處": "徐嘉龍", "北二業展七處": "林慶文",
    "桃竹苗業展一處": "陳來樹", "桃竹苗業展二處": "李嘉慶", "桃竹苗業展三處": "吳玉真", "桃竹苗業展四處": "黃柱珍",
    "中區業展一處": "雷承恩", "中區業展二處": "蔡博清", "中區業展三處": "馮祖浩",
    "中區業展四處": "李應良", "中區業展五處": "林建孜", "中區業展六處": "賴俊男", "中區業展七處": "廖俊傑",
    "南區業展一處": "楊緒民", "南區業展二處": "邱淑珍", "南區業展三處": "王婉蕙", "南區業展四處": "鄭裕昌",
}

REGION_DEPARTMENTS = {
    "台北一區": ["北一業展一處", "北一業展二處", "北一業展三處", "北一業展四處", "北一業展五處", "北一業展六處", "北一業展七處"],
    "台北二區": ["北二業展一處", "北二業展二處", "北二業展三處", "北二業展四處", "北二業展五處", "北二業展六處", "北二業展七處"],
    "桃竹苗區": ["桃竹苗業展一處", "桃竹苗業展二處", "桃竹苗業展三處", "桃竹苗業展四處"],
    "中部地區": ["中區業展一處", "中區業展二處", "中區業展三處", "中區業展四處", "中區業展五處", "中區業展六處", "中區業展七處"],
    "南部地區": ["南區業展一處", "南區業展二處", "南區業展三處", "南區業展四處"],
}

DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "performance.json")

HELP_TEXT = (
    "可用指令：\n"
    "・台北一區 / 桃竹苗區 / 中部地區 / 南部地區 / 台北二區\n"
    "　→ 地區+業展處業績卡片\n"
    "・全國 → 全國報表圖片\n"
    "・最新業績 → 查詢各地區業績數字\n"
    "・本月業績速報 → 業績卡片總覽\n"
    "・本月業展處速報 → 所有業展處本月業績卡片（含全國排名）\n"
    "・本日業展處速報 → 所有業展處本日業績卡片（含全國排名）\n"
    "・達成率排名 → 選擇本月或本日達成率地區排名\n"
    "・業展處排名 → 選擇本月或本日業展處達成率排名（三項各一張）\n"
    "・本日業績速報 → 本日新增保費速報\n"
    "・達標 → 業展處達標狀況 + 動態慶祝\n"
    "・趨勢比較 → 業展處今日 vs 昨日全國排名升降（▲▼）\n"
    "・各地區 → 點選地區快速查詢"
)


def build_region_quickreply():
    """回傳地區選擇 Quick Reply 訊息"""
    regions = ["台北一區", "台北二區", "桃竹苗區", "中部地區", "南部地區"]
    items = [
        QuickReplyButton(action=MessageAction(label=r, text=r))
        for r in regions
    ]
    return TextSendMessage(
        text="請選擇地區 👇",
        quick_reply=QuickReply(items=items)
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


def make_bubble_header(title, updated):
    return {
        "type": "box",
        "layout": "vertical",
        "contents": [
            {"type": "text", "text": title, "weight": "bold", "size": "lg", "color": "#1a5276"},
            {"type": "text", "text": f"截至 {updated}", "size": "xs", "color": "#888888", "margin": "xs"},
        ],
        "backgroundColor": "#EBF5FB",
        "paddingAll": "16px",
    }


def calc_dept_rankings(data):
    """計算各業展處三項達成率的全國排名，回傳 {dept: {key: rank}}"""
    all_depts = {}
    for region_depts in data.get("departments", {}).values():
        for dept, vals in region_depts.items():
            all_depts[dept] = vals
    rankings = {}
    for key in ("實收達成率", "A&H達成率", "RP達成率"):
        scored = [(d, parse_rate_float(v.get(key, "0"))) for d, v in all_depts.items()]
        scored = [(d, f) for d, f in scored if f is not None]
        scored.sort(key=lambda x: x[1], reverse=True)
        for rank, (dept, _) in enumerate(scored, 1):
            rankings.setdefault(dept, {})[key] = rank
    return rankings


def build_region_row(region, values, national=None, subtitle=None, rankings=None):
    """產生單一地區的 Flex 區塊。rankings 傳入時在達成率後顯示全國排名。"""
    def rate_color(val, nat_key):
        if region == "全國" or national is None:
            return "#111111"
        f = parse_rate_float(val)
        nf = parse_rate_float(national.get(nat_key, "0"))
        if f is not None and nf is not None and f < nf:
            return "#e74c3c"
        return "#111111"

    def row(label, amount, rate_val, nat_key):
        rank_text = ""
        if rankings:
            r = rankings.get(nat_key)
            CIRCLE_NUMS = ["①","②","③","④","⑤","⑥","⑦","⑧","⑨","⑩","⑪","⑫","⑬","⑭","⑮","⑯","⑰","⑱","⑲","⑳","㉑","㉒","㉓","㉔","㉕","㉖","㉗","㉘","㉙","㉚"]
            if r: rank_text = f" {CIRCLE_NUMS[r-1]}" if r <= len(CIRCLE_NUMS) else f" {r}"
        return {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {"type": "text", "text": label, "size": "sm", "color": "#666666", "flex": 2},
                {"type": "text", "text": amount, "size": "sm", "color": "#222222", "flex": 4, "align": "end", "weight": "bold"},
                {"type": "text", "text": fmt_rate(rate_val) + rank_text, "size": "sm", "color": rate_color(rate_val, nat_key), "flex": 3, "align": "end", "weight": "bold"},
            ],
            "margin": "xs",
        }

    header = [{"type": "text", "text": f"【{region}】", "weight": "bold", "size": "md", "color": "#1a5276", "margin": "md"}]
    if subtitle:
        header.append({"type": "text", "text": subtitle, "size": "xs", "color": "#888888", "margin": "xs"})

    contents = header + [
        row("實收", fmt_amount(values.get("實收保費", "－")), values.get("實收達成率", "－"), "實收達成率"),
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
                    {"type": "text", "text": f"🔥 {section_title}", "weight": "bold", "size": "sm", "color": "#2471a3", "flex": 5},
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
                {"type": "text", "text": title, "weight": "bold", "size": "lg", "color": "#1a5276"},
                {"type": "text", "text": f"截至 {updated}", "size": "xs", "color": "#888888", "margin": "xs"},
            ],
            "backgroundColor": "#EBF5FB",
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


def build_ranking_bubble(source_key="regions", title="📊 本月達成率排名"):
    """回傳單一 bubble dict（供組 carousel 用）"""
    msg = build_ranking_flex(source_key, title)
    return msg.contents


def build_dept_ranking_flex(source_key="departments", title_prefix="本月"):
    """業展處三項達成率排名，各指標一張 Bubble，共 3 張 Carousel"""
    data = load_performance()
    dept_source = data.get(source_key, {})
    national_source = data["regions"] if source_key == "departments" else data.get("today", data["regions"])
    updated = data.get("updated_at", "－")

    # 收集所有業展處資料
    all_depts = {}
    for region, dept_names in REGION_DEPARTMENTS.items():
        dept_data = dept_source.get(region, {})
        for dept in dept_names:
            all_depts[dept] = dept_data.get(dept, {})

    CIRCLE_NUMS = ["①","②","③","④","⑤","⑥","⑦","⑧","⑨","⑩",
                   "⑪","⑫","⑬","⑭","⑮","⑯","⑰","⑱","⑲","⑳",
                   "㉑","㉒","㉓","㉔","㉕","㉖","㉗","㉘","㉙","㉚"]

    def make_bubble(metric_title, key):
        nat_val = national_source.get("全國", {}).get(key, "0")
        nat_f = parse_rate_float(nat_val)
        nat_str = fmt_rate(nat_val)

        scored = [(d, parse_rate_float(v.get(key, "0"))) for d, v in all_depts.items()]
        scored = [(d, f) for d, f in scored if f is not None]
        scored.sort(key=lambda x: x[1], reverse=True)

        rows = [{
            "type": "box", "layout": "horizontal",
            "contents": [
                {"type": "text", "text": "業展處", "size": "xs", "color": "#888888", "flex": 5},
                {"type": "text", "text": f"全國 {nat_str}", "size": "xs", "color": "#2471a3", "flex": 4, "align": "end", "weight": "bold"},
            ],
            "margin": "sm",
        }]

        for i, (dept, f) in enumerate(scored):
            rank = i + 1
            circle = CIRCLE_NUMS[rank - 1] if rank <= len(CIRCLE_NUMS) else str(rank)
            manager = DEPARTMENT_MANAGERS.get(dept, "")
            label = f"{dept} {manager}" if manager else dept
            rate_color = "#e74c3c" if (nat_f is not None and f < nat_f) else "#222222"
            rows.append({
                "type": "box", "layout": "horizontal",
                "contents": [
                    {"type": "text", "text": circle, "size": "sm", "color": "#2471a3", "flex": 1, "weight": "bold"},
                    {"type": "text", "text": label, "size": "xs", "color": "#333333", "flex": 6, "wrap": True},
                    {"type": "text", "text": fmt_rate(f), "size": "sm", "color": rate_color, "flex": 3, "align": "end", "weight": "bold"},
                ],
                "margin": "xs",
            })

        return {
            "type": "bubble", "size": "mega",
            "header": {
                "type": "box", "layout": "vertical",
                "contents": [
                    {"type": "text", "text": f"📊 {title_prefix} {metric_title} 排名", "weight": "bold", "size": "lg", "color": "#1a5276"},
                    {"type": "text", "text": f"全29業展處 ｜ 截至 {updated}", "size": "xs", "color": "#888888", "margin": "xs"},
                ],
                "backgroundColor": "#EBF5FB", "paddingAll": "16px",
            },
            "body": {
                "type": "box", "layout": "vertical",
                "contents": rows, "paddingAll": "12px", "spacing": "none",
            },
        }

    bubbles = [
        make_bubble("實收達成率", "實收達成率"),
        make_bubble("A&H達成率", "A&H達成率"),
        make_bubble("RP達成率", "RP達成率"),
    ]
    return FlexSendMessage(
        alt_text=f"{title_prefix}業展處達成率排名",
        contents={"type": "carousel", "contents": bubbles}
    )


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


def build_region_detail_flex(region):
    data = load_performance()
    dept_data = data.get("departments", {}).get(region, {})
    national = data["regions"].get("全國", {})
    region_vals = data["regions"].get(region, {})
    updated = data.get("updated_at", "－")
    dept_names = REGION_DEPARTMENTS.get(region, [])

    def make_bubble(title, blocks):
        return {
            "type": "bubble",
            "size": "mega",
            "header": make_bubble_header(title, updated),
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": blocks,
                "paddingAll": "12px",
                "spacing": "none",
            },
        }

    all_rankings = calc_dept_rankings(data)
    today_dept_data = data.get("today_departments", {}).get(region, {})
    today_national = data.get("today", {}).get("全國", {})
    today_rankings = calc_dept_rankings_from(data.get("today_departments", {}))

    bubble1 = make_bubble(f"📊 {region} 業績總覽", [
        build_region_row("全國", national),
        build_region_row(region, region_vals, national=national),
    ])

    dept_blocks = []
    for dept in dept_names:
        manager = DEPARTMENT_MANAGERS.get(dept, "")
        values = dept_data.get(dept, {})
        label = f"{dept}　{manager}" if manager else dept
        dept_blocks.append(build_region_row(label, values, national=national, rankings=all_rankings.get(dept)))
    bubble2 = make_bubble(f"📊 {region} 本月業展處", dept_blocks)

    today_blocks = []
    for dept in dept_names:
        manager = DEPARTMENT_MANAGERS.get(dept, "")
        values = today_dept_data.get(dept, {})
        label = f"{dept}　{manager}" if manager else dept
        today_blocks.append(build_region_row(label, values, national=today_national, rankings=today_rankings.get(dept)))
    bubble3 = make_bubble(f"📊 {region} 本日業展處", today_blocks)

    return FlexSendMessage(alt_text=f"{region}業績詳情", contents={"type": "carousel", "contents": [bubble1, bubble2, bubble3]})


def build_all_depts_flex(source_key="departments", title_prefix="本月", alt_text="本月業展處速報"):
    data = load_performance()
    national_key = "regions" if source_key == "departments" else "today"
    national = data.get(national_key, data["regions"]).get("全國", {})
    updated = data.get("updated_at", "－")
    all_rankings = calc_dept_rankings_from(data.get(source_key, {}))

    bubbles = []
    for region, dept_names in REGION_DEPARTMENTS.items():
        dept_data = data.get(source_key, {}).get(region, {})
        blocks = []
        for dept in dept_names:
            manager = DEPARTMENT_MANAGERS.get(dept, "")
            values = dept_data.get(dept, {})
            label = f"{dept}　{manager}" if manager else dept
            blocks.append(build_region_row(label, values, national=national, rankings=all_rankings.get(dept)))
        bubbles.append({
            "type": "bubble",
            "size": "mega",
            "header": make_bubble_header(f"📊 {region} {title_prefix}業展處", updated),
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": blocks,
                "paddingAll": "12px",
                "spacing": "none",
            },
        })

    return FlexSendMessage(alt_text=alt_text, contents={"type": "carousel", "contents": bubbles})


def calc_region_rankings(source_regions):
    """計算各地區三項達成率排名（排除全國），回傳 {region: {key: rank}}"""
    regions = {r: v for r, v in source_regions.items() if r != "全國"}
    rankings = {}
    for key in ("實收達成率", "A&H達成率", "RP達成率"):
        scored = [(r, parse_rate_float(v.get(key, "0"))) for r, v in regions.items()]
        scored = [(r, f) for r, f in scored if f is not None]
        scored.sort(key=lambda x: x[1], reverse=True)
        for rank, (r, _) in enumerate(scored, 1):
            rankings.setdefault(r, {})[key] = rank
    return rankings


def build_flex_from_source(source_regions, title, alt_text):
    data = load_performance()
    updated = data.get("updated_at", "－")
    national = source_regions.get("全國", {})
    region_rankings = calc_region_rankings(source_regions)
    region_blocks = [
        build_region_row(r, v, national=national, rankings=region_rankings.get(r) if r != "全國" else None)
        for r, v in source_regions.items()
    ]
    bubble = {
        "type": "bubble",
        "size": "mega",
        "header": make_bubble_header(title, updated),
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
    return build_flex_from_source(data["regions"], "📊 本月業績速報", "本月業績速報")


def calc_dept_rankings_from(dept_source):
    """從指定的 today_departments/yesterday_departments 計算排名"""
    all_depts = {}
    for region_depts in dept_source.values():
        for dept, vals in region_depts.items():
            all_depts[dept] = vals
    rankings = {}
    for key in ("實收達成率", "A&H達成率", "RP達成率"):
        scored = [(d, parse_rate_float(v.get(key, "0"))) for d, v in all_depts.items()]
        scored = [(d, f) for d, f in scored if f is not None]
        scored.sort(key=lambda x: x[1], reverse=True)
        for rank, (dept, _) in enumerate(scored, 1):
            rankings.setdefault(dept, {})[key] = rank
    return rankings


def build_trend_flex():
    """今日 vs 昨日全國排名變化（業展處）"""
    data = load_performance()
    today_depts   = data.get("today_departments", {})
    yest_depts    = data.get("yesterday_departments", {})
    updated = data.get("updated_at", "－")

    # 需要今日和昨日都有資料才能比較
    has_today = any(today_depts.get(r) for r in REGION_DEPARTMENTS)
    has_yest  = any(yest_depts.get(r) for r in REGION_DEPARTMENTS)
    if not has_today:
        return None

    today_ranks = calc_dept_rankings_from(today_depts)
    yest_ranks  = calc_dept_rankings_from(yest_depts) if has_yest else {}

    CIRCLE_NUMS = ["①","②","③","④","⑤","⑥","⑦","⑧","⑨","⑩",
                   "⑪","⑫","⑬","⑭","⑮","⑯","⑰","⑱","⑲","⑳",
                   "㉑","㉒","㉓","㉔","㉕","㉖","㉗","㉘","㉙","㉚"]

    def circle(r):
        return CIRCLE_NUMS[r-1] if r and r <= len(CIRCLE_NUMS) else str(r)

    def rank_change(dept, key):
        t = today_ranks.get(dept, {}).get(key)
        y = yest_ranks.get(dept, {}).get(key)
        if t is None:
            return "－", "#888888"
        today_str = circle(t)
        if y is None or not has_yest:
            return today_str, "#222222"
        diff = y - t  # 排名數字變小 = 名次上升 → ▲
        if diff > 0:
            return f"{today_str} ▲{diff}", "#27ae60"
        elif diff < 0:
            return f"{today_str} ▼{abs(diff)}", "#e74c3c"
        return f"{today_str} →", "#888888"

    bubbles = []
    for region, dept_names in REGION_DEPARTMENTS.items():
        blocks = []
        for dept in dept_names:
            manager = DEPARTMENT_MANAGERS.get(dept, "")
            label = f"{dept} {manager}" if manager else dept
            blocks.append({
                "type": "text", "text": label,
                "weight": "bold", "size": "xs", "color": "#1a5276", "margin": "md"
            })
            row_items = []
            for short, key in [("實收", "實收達成率"), ("A&H", "A&H達成率"), ("RP", "RP達成率")]:
                text, color = rank_change(dept, key)
                row_items.append({
                    "type": "box", "layout": "horizontal",
                    "contents": [
                        {"type": "text", "text": short, "size": "xs", "color": "#666666", "flex": 2},
                        {"type": "text", "text": text, "size": "xs", "color": color, "flex": 5, "align": "end", "weight": "bold"},
                    ],
                    "margin": "xs",
                })
            blocks.extend(row_items)
            blocks.append({"type": "separator", "margin": "xs"})

        bubbles.append({
            "type": "bubble", "size": "mega",
            "header": {
                "type": "box", "layout": "vertical",
                "contents": [
                    {"type": "text", "text": f"📈 {region} 排名變化", "weight": "bold", "size": "lg", "color": "#1a5276"},
                    {"type": "text", "text": f"今日排名 ▲上升 ▼下降 ｜ 截至 {updated}", "size": "xs", "color": "#888888", "margin": "xs"},
                ],
                "backgroundColor": "#EBF5FB", "paddingAll": "16px",
            },
            "body": {
                "type": "box", "layout": "vertical",
                "contents": blocks, "paddingAll": "12px", "spacing": "none",
            },
        })

    return FlexSendMessage(
        alt_text="業展處排名趨勢比較",
        contents={"type": "carousel", "contents": bubbles}
    )




def build_achieved_flex():
    """達標業展處（實收達成率 ≥ 100%）"""
    data = load_performance()
    all_rankings = calc_dept_rankings(data)
    updated = data.get("updated_at", "－")
    national = data["regions"].get("全國", {})
    nat_rate = parse_rate_float(national.get("實收達成率", "0")) or 0

    achieved = []
    not_achieved = []
    for region, depts in REGION_DEPARTMENTS.items():
        dept_data = data.get("departments", {}).get(region, {})
        for dept in depts:
            vals = dept_data.get(dept, {})
            f = parse_rate_float(vals.get("實收達成率", "0"))
            manager = DEPARTMENT_MANAGERS.get(dept, "")
            label = f"{dept}　{manager}" if manager else dept
            rank = all_rankings.get(dept, {}).get("實收達成率")
            CIRCLE_NUMS = ["①","②","③","④","⑤","⑥","⑦","⑧","⑨","⑩","⑪","⑫","⑬","⑭","⑮","⑯","⑰","⑱","⑲","⑳","㉑","㉒","㉓","㉔","㉕","㉖","㉗","㉘","㉙","㉚"]
            rank_text = f" {CIRCLE_NUMS[rank-1]}" if rank and rank <= len(CIRCLE_NUMS) else ""
            rate_text = fmt_rate(vals.get("實收達成率", "－")) + rank_text
            if f is not None and f >= 1.0:
                achieved.append((label, rate_text, "#27ae60"))
            else:
                not_achieved.append((label, rate_text, "#e74c3c" if f is not None and f < nat_rate else "#555555"))

    def make_rows(items):
        rows = []
        for label, rate, color in items:
            rows.append({
                "type": "box", "layout": "horizontal",
                "contents": [
                    {"type": "text", "text": label, "size": "sm", "color": "#333333", "flex": 6},
                    {"type": "text", "text": rate, "size": "sm", "color": color, "flex": 3, "align": "end", "weight": "bold"},
                ],
                "margin": "xs",
            })
        return rows

    body = []
    if achieved:
        body.append({"type": "text", "text": "🏆 已達標", "weight": "bold", "size": "sm", "color": "#27ae60", "margin": "md"})
        body.extend(make_rows(achieved))
        body.append({"type": "separator", "margin": "md"})
    if not_achieved:
        body.append({"type": "text", "text": "⚡ 未達標", "weight": "bold", "size": "sm", "color": "#e74c3c", "margin": "md"})
        body.extend(make_rows(not_achieved))

    bubble = {
        "type": "bubble", "size": "mega",
        "header": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": "🎯 實收達成率 達標狀況", "weight": "bold", "size": "lg", "color": "#1a5276"},
                {"type": "text", "text": f"達標基準：100% ｜ 截至 {updated}", "size": "xs", "color": "#888888", "margin": "xs"},
            ],
            "backgroundColor": "#EBF5FB", "paddingAll": "16px",
        },
        "body": {
            "type": "box", "layout": "vertical",
            "contents": body, "paddingAll": "12px", "spacing": "none",
        },
    }
    return FlexSendMessage(alt_text="達標狀況一覽", contents=bubble)


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

    if text == "各地區":
        line_bot_api.reply_message(event.reply_token, build_region_quickreply())
    elif text == "達標":
        flex_msg = build_achieved_flex()
        # LINE 官方動態貼圖（Lottie 渲染）：package 11537 Brown & Friends 慶祝動態
        sticker = StickerSendMessage(package_id="11537", sticker_id="52002740")
        line_bot_api.reply_message(event.reply_token, [sticker, flex_msg])
    elif text == "趨勢比較":
        msg = build_trend_flex()
        if msg:
            line_bot_api.reply_message(event.reply_token, msg)
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 尚無今日資料，請等待今日速報更新後再查詢"))
    elif text == "群組ID":
        source = event.source
        gid = getattr(source, "group_id", None) or getattr(source, "room_id", None) or source.user_id
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"ID：{gid}"))
    elif text == "本月業展處速報":
        line_bot_api.reply_message(
            event.reply_token,
            build_all_depts_flex("departments", "本月", "本月業展處速報")
        )
    elif text == "本日業展處速報":
        line_bot_api.reply_message(
            event.reply_token,
            build_all_depts_flex("today_departments", "本日", "本日業展處速報")
        )
    elif text == "業展處排名":
        items = [
            QuickReplyButton(action=MessageAction(label="本月業展處排名", text="本月業展處排名")),
            QuickReplyButton(action=MessageAction(label="本日業展處排名", text="本日業展處排名")),
        ]
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="請選擇查詢期間 👇", quick_reply=QuickReply(items=items))
        )
    elif text == "本月業展處排名":
        line_bot_api.reply_message(
            event.reply_token,
            build_dept_ranking_flex("departments", "本月")
        )
    elif text == "本日業展處排名":
        line_bot_api.reply_message(
            event.reply_token,
            build_dept_ranking_flex("today_departments", "本日")
        )
    elif text == "達成率排名":
        b1 = build_ranking_bubble("regions", "📊 本月達成率排名")
        b2 = build_ranking_bubble("today", "📊 本日達成率排名")
        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(alt_text="達成率排名", contents={"type": "carousel", "contents": [b1, b2]})
        )
    elif text == "本月達成率排名":
        line_bot_api.reply_message(
            event.reply_token,
            build_ranking_flex("regions", "📊 本月達成率排名")
        )
    elif text == "本日達成率排名":
        line_bot_api.reply_message(
            event.reply_token,
            build_ranking_flex("today", "📊 本日達成率排名")
        )
    elif text == "本日業績速報":
        data = load_performance()
        line_bot_api.reply_message(
            event.reply_token,
            build_flex_from_source(data.get("today", data["regions"]), "📊 本日業績速報", "本日業績速報")
        )
    elif text == "本月業績速報":
        line_bot_api.reply_message(
            event.reply_token,
            build_flex_message()
        )
    elif text in REGION_DEPARTMENTS:
        line_bot_api.reply_message(
            event.reply_token,
            build_region_detail_flex(text)
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
