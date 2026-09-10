"""
補上檢測站個股的中文名稱。

擴到 674 檔之後,只有原本 120 檔在 universe.csv 裡有名稱,其餘只能用代號
充當名稱,於是網頁顯示成「0050 0050」「1101 1101」—— 674 檔裡有 554 檔如此。

FinMind 的 TaiwanStockInfo 一次就能拿到全台股的代號與名稱(含上市與上櫃),
只要 1 個請求。
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
TW = timezone(timedelta(hours=8))


def get(url, tries=4, timeout=45):
    for i in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except Exception as e:
            code = getattr(e, "code", None)
            wait = (10 if code in (402, 429) else 4) * (i + 1)
            print(f"  {code or type(e).__name__},{wait}s 後重試", flush=True)
            time.sleep(wait)
    return None


def main():
    doc = json.load(open(DEST, encoding="utf-8"))
    print(f"讀入 {len(doc['stocks'])} 檔", flush=True)

    j = get(f"{FINMIND}?dataset=TaiwanStockInfo")
    rows = (j or {}).get("data") or []
    if not rows:
        print("✗ 取不到 TaiwanStockInfo,不動任何資料", flush=True)
        return 1

    info, market = {}, {}
    for r in rows:
        sid, nm = r.get("stock_id"), r.get("stock_name")
        if sid and nm and sid not in info:
            info[sid] = nm.strip()
            market[sid] = r.get("type")
    print(f"對照表 {len(info)} 檔", flush=True)

    fixed, still = 0, []
    for s in doc["stocks"]:
        sid = s["id"]
        nm = info.get(sid)
        # 現況可能是「1101 1101」(代號充當名稱)或「1101 台泥」
        cur = s["name"].split(" ", 1)[-1] if " " in s["name"] else s["name"]
        if nm and cur != nm:
            s["name"] = f"{sid} {nm}"
            fixed += 1
        elif not nm:
            still.append(sid)
        # 順帶補上市場別,上櫃個股的資料來源與上市不同,值得標示
        if market.get(sid) and not s.get("market"):
            s["market"] = market[sid]

    doc["updated_at"] = datetime.now(TW).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    tmp = DEST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, DEST)

    otc = sum(1 for s in doc["stocks"] if s.get("market") == "tpex")
    print(f"\n更正名稱 {fixed} 檔,對照表查無 {len(still)} 檔 {still[:8]}")
    print(f"標記為上櫃 {otc} 檔,檔案 {os.path.getsize(DEST)/1048576:.2f} MB", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
