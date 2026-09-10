"""
把指定的個股加進檢測站的 docs/data/stocks.json。

為什麼要另外寫一支
------------------
既有管線走證交所的 MI_INDEX / STOCK_DAY,那些端點只涵蓋**上市**。
使用者指名的個股可能是上櫃(tpex),證交所查不到,但 FinMind 兩者都有。
所以這支直接用 FinMind 抓,並把市場別一併記下來,讓網頁能標示出來。

代號不從記憶猜 —— 先用 TaiwanStockInfo 反查確認名稱與市場別,對不上就停。

用法(環境變數 ADD_STOCKS,逗號分隔):
    ADD_STOCKS=4939,6735 python research/add_stocks.py
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(ROOT, "docs", "data", "stocks.json")
FINMIND = "https://api.finmindtrade.com/api/v4/data"
UA = "Mozilla/5.0 (compatible; tw-backtest-research/1.0)"
KEEP = int(os.environ.get("KEEP_BARS", "500"))
IDS = [x.strip() for x in (os.environ.get("ADD_STOCKS") or "").split(",") if x.strip()]
TW = timezone(timedelta(hours=8))


def get(url, tries=4, timeout=40):
    for i in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except Exception as e:
            code = getattr(e, "code", None)
            wait = (8 if code in (402, 429) else 4) * (i + 1)
            print(f"      {code or type(e).__name__},{wait}s 後重試", flush=True)
            time.sleep(wait)
    return None


def main():
    if not IDS:
        raise SystemExit("✗ 沒有指定 ADD_STOCKS")
    if not os.path.exists(DEST):
        raise SystemExit(f"✗ 找不到 {DEST}")

    print(f"=== 反查代號:{IDS} ===", flush=True)
    j = get(f"{FINMIND}?dataset=TaiwanStockInfo")
    info = {}
    for r in (j or {}).get("data") or []:
        sid = r.get("stock_id")
        if sid and sid not in info:
            info[sid] = (r.get("stock_name"), r.get("type"), r.get("industry_category"))
    if not info:
        raise SystemExit("✗ 取不到代號對照表,停止 —— 不確認名稱就寫進去會標錯股票")

    for sid in IDS:
        if sid not in info:
            raise SystemExit(f"✗ 代號 {sid} 不在台股清單裡,停止")
        print(f"  {sid}  {info[sid][0]}  市場 {info[sid][1]}  產業 {info[sid][2]}", flush=True)

    doc = json.load(open(DEST, encoding="utf-8"))
    # 既有檔案的日期可能是索引,先還原成字串再處理,最後統一重編
    old_dates = doc.get("dates")
    if old_dates:
        for s in doc["stocks"]:
            s["bars"] = [[old_dates[b[0]]] + list(b[1:]) for b in s["bars"]]
    existing = {s["id"]: s for s in doc["stocks"]}
    start = (datetime.now(TW) - timedelta(days=int(KEEP * 1.8))).strftime("%Y-%m-%d")
    end = datetime.now(TW).strftime("%Y-%m-%d")

    print(f"\n=== 抓日線({start} ~ {end})===", flush=True)
    added, updated = [], []
    for sid in IDS:
        time.sleep(2)
        jj = get(f"{FINMIND}?dataset=TaiwanStockPrice&data_id={sid}"
                 f"&start_date={start}&end_date={end}")
        rows = (jj or {}).get("data") or []
        bars = []
        for r in rows:
            try:
                o, h, l, c = float(r["open"]), float(r["max"]), float(r["min"]), float(r["close"])
                v = int(float(r.get("Trading_Volume") or 0))
            except (TypeError, ValueError, KeyError):
                continue
            if c <= 0:
                continue
            # 成交量由「股」換算為「張」,與台股看盤習慣一致
            bars.append([r["date"], o, h, l, c, v // 1000])
        bars.sort(key=lambda x: x[0])
        bars = bars[-KEEP:]
        if len(bars) < 60:
            print(f"  ✗ {sid} {info[sid][0]}:只有 {len(bars)} 根,算不出季線,不加入", flush=True)
            continue

        name = info[sid][0]
        rec = {"id": sid, "name": name, "market": info[sid][1], "bars": bars}
        (updated if sid in existing else added).append(f"{sid} {name}")
        existing[sid] = rec
        print(f"  ✓ {sid} {name}:{len(bars)} 根,{bars[0][0]} ~ {bars[-1][0]},"
              f"最新收盤 {bars[-1][4]}", flush=True)

    if not added and not updated:
        raise SystemExit("✗ 沒有任何個股成功加入")

    # 依代號排序,讓輸出穩定
    doc["stocks"] = [existing[k] for k in sorted(existing)]
    doc["updated_at"] = datetime.now(TW).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    doc["as_of"] = max(s["bars"][-1][0] for s in doc["stocks"])
    dates = sorted({b[0] for s in doc["stocks"] for b in s["bars"]})
    di = {d: i for i, d in enumerate(dates)}
    for s in doc["stocks"]:
        s["bars"] = [[di[b[0]]] + list(b[1:]) for b in s["bars"]]
    doc["dates"] = dates
    doc["source"] = "證交所日線(經 FinMind);上櫃個股由 FinMind 直接提供"

    tmp = DEST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, DEST)
    print(f"\n新增 {added}、更新 {updated}", flush=True)
    print(f"共 {len(doc['stocks'])} 檔,{os.path.getsize(DEST)/1024/1024:.2f} MB,"
          f"資料截至 {doc['as_of']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
