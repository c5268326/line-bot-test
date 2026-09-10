"""
用 point-in-time 抓下來的 711 檔日線,產生檢測站的 docs/data/stocks.json。

為什麼換這份輸入
----------------
原本的檢測站吃 research/data/price.csv.gz,只有 120 檔 —— 那是早期為了
確認管線跑得動而挑的保守值。做倖存者偏誤修正時已經抓了 711 檔十年日線
(research/data/pit/),那份資料檢測站一直沒用上。

兩個必要的過濾
--------------
1. 已下市的個股要排除。它們對回測是必要的(不排除才沒有倖存者偏誤),
   但放進「今日訊號檢測站」是錯的 —— 那些公司已經沒有現在的價格了。
2. 日線太短的排除,算不出季線。

保留幾根的取捨
--------------
Artifact 受 CSP 限制無法 fetch,行情必須內嵌,上限 16MB。
671 檔 × 500 根約 14MB,逼近上限;× 400 根約 11MB,仍算得出年線(MA240)。

用法:python tools/make_station_from_pit.py [每檔保留幾根] [最後一筆的最早日期]
"""
import csv
import gzip
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRICE = os.path.join(ROOT, "research", "data", "pit", "price.csv.gz")
UNIVERSE = os.path.join(ROOT, "research", "data", "pit", "universe_by_date.csv")
NAMES_SRC = os.path.join(ROOT, "research", "data", "universe.csv")
DEST = os.path.join(ROOT, "docs", "data", "stocks.json")

KEEP = int(sys.argv[1]) if len(sys.argv) > 1 else 400
ALIVE_SINCE = sys.argv[2] if len(sys.argv) > 2 else None
TW = timezone(timedelta(hours=8))
MIN_BARS = 60          # 算不出季線的不放


def main():
    for p in (PRICE, UNIVERSE):
        if not os.path.exists(p):
            raise SystemExit(f"✗ 找不到 {p}")

    # 名稱:先用既有的 universe.csv,缺的再用現有 stocks.json 補
    names = {}
    if os.path.exists(NAMES_SRC):
        with open(NAMES_SRC, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                names[r["stock_id"]] = r["name"]
    keep_extra = {}
    if os.path.exists(DEST):
        cur = json.load(open(DEST, encoding="utf-8"))
        # 既有檔案的日期可能已是共用表的索引,先還原成字串,
        # 否則會和 PIT 來的字串日期混在一起,排序與比較都會炸開
        cur_dates = cur.get("dates")
        if cur_dates:
            for s in cur["stocks"]:
                s["bars"] = [[cur_dates[b[0]]] + list(b[1:]) for b in s["bars"]]
        for s in cur["stocks"]:
            nm = s["name"].split(" ", 1)[-1] if " " in s["name"] else s["name"]
            names.setdefault(s["id"], nm)
            # 使用者手動加入的個股(帶 market 欄位)一律保留,不受 PIT 名單限制
            if s.get("market"):
                keep_extra[s["id"]] = s

    bars = defaultdict(list)
    with gzip.open(PRICE, "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                o, h, l, c = float(r["open"]), float(r["max"]), float(r["min"]), float(r["close"])
                v = int(float(r.get("Trading_Volume") or 0))
            except (TypeError, ValueError, KeyError):
                continue
            if c <= 0:
                continue
            bars[r["stock_id"]].append([r["date"], o, h, l, c, v // 1000])

    last_dates = {sid: max(x[0] for x in rows) for sid, rows in bars.items()}
    newest = max(last_dates.values())
    cutoff = ALIVE_SINCE or (datetime.strptime(newest, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d")

    stocks, dead, short = [], [], []
    for sid, rows in bars.items():
        if last_dates[sid] < cutoff:
            dead.append(sid)                 # 已下市或停止更新
            continue
        rows.sort(key=lambda x: x[0])
        rows = rows[-KEEP:]
        if len(rows) < MIN_BARS:
            short.append(sid)
            continue
        # name 只放公司名,代號由網頁自己加在前面 —— 存成「1101 台泥」
        # 會被再加一次前綴,變成「1101 1101 台泥」
        stocks.append({"id": sid, "name": names.get(sid, ""), "bars": rows})

    # 併回使用者手動加入的個股
    have = {s["id"] for s in stocks}
    for sid, rec in keep_extra.items():
        if sid not in have:
            rec = dict(rec)
            rec["bars"] = rec["bars"][-KEEP:]
            stocks.append(rec)

    stocks.sort(key=lambda s: s["id"])
    as_of = max(s["bars"][-1][0] for s in stocks)

    # 日期改存索引:全站只有幾百個交易日,每根 K 重複存一次日期字串
    # 會佔掉將近三成的檔案大小,而檔案大小正是網頁載入的主要成本。
    dates = sorted({b[0] for s in stocks for b in s["bars"]})
    di = {d: i for i, d in enumerate(dates)}
    for s in stocks:
        s["bars"] = [[di[b[0]]] + b[1:] for b in s["bars"]]

    doc = {
        "updated_at": datetime.now(TW).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "source": "證交所 point-in-time 日線(經 FinMind);上櫃個股由 FinMind 直接提供",
        "as_of": as_of,
        "failures": [],
        "dates": dates,
        "stocks": stocks,
    }
    tmp = DEST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, DEST)

    mb = os.path.getsize(DEST) / 1024 / 1024
    print(f"最新交易日 {newest},存活門檻 {cutoff}")
    print(f"排除:已下市 {len(dead)} 檔、日線不足 {len(short)} 檔")
    print(f"產出:{len(stocks)} 檔 × 最多 {KEEP} 根 = {mb:.2f} MB,資料截至 {doc['as_of']}")
    if mb > 13:
        print("⚠ 逼近 Artifact 的 16MB 上限,建議減少保留根數")
    return 0


if __name__ == "__main__":
    sys.exit(main())
