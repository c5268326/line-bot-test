"""
把 research/data/ 的真實台股資料轉成檢測站網頁讀取的 docs/data/stocks.json。

資料來源是 fetch_stocks.py / fetch_data.py 經 GitHub Actions 抓下來的
證交所日線(透過 FinMind),不是模擬資料。

用法:
    python tools/make_station_data.py [每檔保留幾根日K]

預設保留最近 500 根,足夠算出季線與所有指標,同時讓檔案小到可以直接
內嵌進 Artifact(Artifact 受 CSP 限制無法 fetch 外部檔案)。
"""
import csv
import gzip
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(ROOT, "research", "data")
OUT = os.path.join(ROOT, "docs", "data", "stocks.json")

KEEP = int(sys.argv[1]) if len(sys.argv) > 1 else 500
TW = timezone(timedelta(hours=8))


def main():
    uni_path = os.path.join(SRC_DIR, "universe.csv")
    price_path = os.path.join(SRC_DIR, "price.csv.gz")
    for p in (uni_path, price_path):
        if not os.path.exists(p):
            raise SystemExit(f"找不到 {p},請先執行資料抓取")

    names = {}
    with open(uni_path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            names[r["stock_id"]] = r["name"]

    bars = defaultdict(list)
    with gzip.open(price_path, "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                o, h, l, c = float(r["open"]), float(r["max"]), float(r["min"]), float(r["close"])
                v = int(float(r["Trading_Volume"] or 0))
            except (TypeError, ValueError):
                continue
            if c <= 0:
                continue
            # 成交量由「股」換算為「張」,與台股看盤習慣一致
            bars[r["stock_id"]].append([r["date"], o, h, l, c, v // 1000])

    stocks, skipped = [], []
    for sid, rows in bars.items():
        rows.sort(key=lambda x: x[0])
        rows = rows[-KEEP:]
        if len(rows) < 60:            # 算不出季線的就不放進去
            skipped.append(sid)
            continue
        stocks.append({"id": sid, "name": names.get(sid, ""), "bars": rows})

    # 依代號排序,讓輸出穩定、diff 好讀
    stocks.sort(key=lambda s: s["id"])

    latest = max(s["bars"][-1][0] for s in stocks)
    payload = {
        "updated_at": datetime.now(TW).isoformat(timespec="seconds"),
        "source": "證交所日線(經 FinMind)",
        "as_of": latest,
        "failures": skipped,
        "stocks": stocks,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    size = os.path.getsize(OUT) / 1024 / 1024
    print(f"已寫入 {OUT}")
    print(f"  {len(stocks)} 檔,每檔最多 {KEEP} 根,資料截止 {latest},{size:.2f} MB")
    if skipped:
        print(f"  略過資料不足的 {len(skipped)} 檔:{skipped[:10]}")


if __name__ == "__main__":
    main()
