"""
增量更新檢測站的行情:只補上缺的那幾個交易日。

為什麼不逐檔抓
--------------
674 檔逐檔向 FinMind 要日線 = 674 次請求,撞配額要跑二十幾分鐘。
證交所的 MI_INDEX 是**全市場單日快照**,一天只要 1 次請求 ——
補四個交易日只要 4 次。上櫃個股證交所沒有,那幾檔才用 FinMind 補。

輸出格式與 make_station_from_pit.py 一致:日期存共用表的索引。
"""
import json
import os
import re
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(ROOT, "docs", "data", "stocks.json")
MI = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={d}&type=ALLBUT0999&response=json"
FINMIND = "https://api.finmindtrade.com/api/v4/data"
UA = "Mozilla/5.0 (compatible; tw-backtest-research/1.0)"
TWSE_PACE = 2.5
TW = timezone(timedelta(hours=8))
KEEP = int(os.environ.get("KEEP_BARS", "300"))
MAX_DAYS = int(os.environ.get("MAX_DAYS", "10"))     # 最多往回補幾個日曆日


def get_json(url, tries=3, timeout=35):
    for i in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json, */*"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except Exception as e:
            print(f"      {getattr(e, 'code', None) or type(e).__name__},重試", flush=True)
            time.sleep(5 * (i + 1))
    return None


def num(s):
    t = re.sub(r"[,\s]", "", str(s)).strip('"')
    if t in ("", "--", "-", "X", "N/A"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def snapshot(d):
    """回傳 {代號: [開, 高, 低, 收, 張]};非交易日回 None。欄位一律用欄名對應。"""
    j = get_json(MI.format(d=d.strftime("%Y%m%d")))
    if not j or j.get("stat") != "OK":
        return None
    need = ("證券代號", "開盤價", "最高價", "最低價", "收盤價", "成交股數")
    for t in j.get("tables", []):
        f = t.get("fields") or []
        if not all(k in f for k in need):
            continue
        ic, io, ih, il, ic2, iv = (f.index(k) for k in need)
        out = {}
        for r in t.get("data", []):
            code = str(r[ic]).strip().strip('"')
            if not (len(code) == 4 and code.isdigit()):
                continue
            o, h, l, c, v = (num(r[i]) for i in (io, ih, il, ic2, iv))
            if not c or c <= 0:
                continue
            # 開高低偶爾是 "--"(無成交),用收盤價補,不要留 None 讓指標算錯
            out[code] = [o or c, h or c, l or c, c, int((v or 0) // 1000)]
        return out
    return None


def main():
    doc = json.load(open(DEST, encoding="utf-8"))
    dates = doc.get("dates") or []
    # 還原成日期字串再處理,最後統一重編
    for s in doc["stocks"]:
        s["bars"] = [[dates[b[0]]] + list(b[1:]) for b in s["bars"]] if dates else \
                    [list(b) for b in s["bars"]]

    have = {s["id"]: {b[0] for b in s["bars"]} for s in doc["stocks"]}
    latest = max(b[0] for s in doc["stocks"] for b in s["bars"])
    today = datetime.now(TW).date()
    print(f"現有資料最新到 {latest},今天 {today}", flush=True)

    start = datetime.strptime(latest, "%Y-%m-%d").date() + timedelta(days=1)
    days = [start + timedelta(days=i) for i in range((today - start).days + 1)][-MAX_DAYS:]
    days = [d for d in days if d.weekday() < 5]          # 週末直接跳過
    if not days:
        print("沒有需要補的交易日", flush=True)
        return 0

    print(f"要嘗試的日期:{[d.isoformat() for d in days]}", flush=True)
    listed = {s["id"] for s in doc["stocks"]}
    added = 0
    for d in days:
        snap = snapshot(d)
        time.sleep(TWSE_PACE)
        if not snap:
            print(f"  {d} 非交易日或無資料", flush=True)
            continue
        n = 0
        ds = d.isoformat()
        for s in doc["stocks"]:
            row = snap.get(s["id"])
            if not row or ds in have[s["id"]]:
                continue
            s["bars"].append([ds] + row)
            have[s["id"]].add(ds)
            n += 1
        added += n
        print(f"  {d} 全市場 {len(snap)} 檔 → 更新 {n} 檔", flush=True)

    # 上櫃個股證交所沒有,用 FinMind 補
    otc = [s for s in doc["stocks"] if s.get("market") == "tpex"]
    for s in otc:
        time.sleep(2)
        last = max(b[0] for b in s["bars"])
        j = get_json(f"{FINMIND}?dataset=TaiwanStockPrice&data_id={s['id']}"
                     f"&start_date={last}&end_date={today.isoformat()}")
        rows = (j or {}).get("data") or []
        n = 0
        for r in rows:
            if r["date"] in have[s["id"]]:
                continue
            try:
                o, h, l, c = float(r["open"]), float(r["max"]), float(r["min"]), float(r["close"])
                v = int(float(r.get("Trading_Volume") or 0))
            except (TypeError, ValueError, KeyError):
                continue
            if c <= 0:
                continue
            s["bars"].append([r["date"], o, h, l, c, v // 1000])
            have[s["id"]].add(r["date"])
            n += 1
        added += n
        print(f"  上櫃 {s['id']} {s['name']}:補 {n} 筆", flush=True)

    if not added:
        print("\n沒有任何新資料,檔案不變", flush=True)
        return 0

    for s in doc["stocks"]:
        s["bars"].sort(key=lambda x: x[0])
        s["bars"] = s["bars"][-KEEP:]

    new_dates = sorted({b[0] for s in doc["stocks"] for b in s["bars"]})
    di = {d: i for i, d in enumerate(new_dates)}
    for s in doc["stocks"]:
        s["bars"] = [[di[b[0]]] + list(b[1:]) for b in s["bars"]]
    doc["dates"] = new_dates
    doc["as_of"] = new_dates[-1]
    doc["updated_at"] = datetime.now(TW).strftime("%Y-%m-%dT%H:%M:%S+08:00")

    tmp = DEST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, DEST)
    print(f"\n新增 {added} 筆日線,共 {len(doc['stocks'])} 檔,"
          f"{os.path.getsize(DEST)/1024/1024:.2f} MB,資料截至 {doc['as_of']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
