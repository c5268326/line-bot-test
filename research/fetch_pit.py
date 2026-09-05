"""
建立 point-in-time 股票池,並抓取池內個股(含已下市者)的日線與估值。

為什麼這樣做
------------
先前回測用「今天」的成交金額前 120 名回頭選股。探測發現這造成兩種偏誤:

  2015-01-05 全市場 873 檔、2026-09-04 全市場 1093 檔
  2015 有而 2026 沒有(已下市/改代號)  71 檔  ← 回測完全看不到
  2026 有而 2015 沒有(期間才上市)    291 檔  ← 回測假裝當時就能買

第二種的規模是第一種的四倍。用今天的名單回頭套十年,等於預先知道誰
會活下來、誰會長大。

做法
----
1. 只在「換股日」抓證交所全市場快照 —— 每季一次,約 47 天,94 次請求。
   每個換股日取當天成交金額前 N 名,那就是**當時真正買得到**的池子。
2. 取所有換股日池子的聯集,用 FinMind 抓這些個股的完整日線。
   已驗證 FinMind 保有下市公司的歷史資料(抽測 10/10 有)。

產出
    research/data/pit/universe_by_date.csv   每個換股日的池子與當日估值
    research/data/pit/price.csv.gz           聯集個股的日線
"""
import csv
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "data", "pit")

UA = "Mozilla/5.0 (compatible; tw-backtest-research/1.0)"
TWSE_PACE = float(os.environ.get("TWSE_PACE", "2.5"))
FINMIND_PACE = float(os.environ.get("FINMIND_PACE", "1.5"))
TOP_N = int(os.environ.get("PIT_TOP_N", "150"))     # 每個換股日的池子大小
START, END = "2015-01-01", date.today().isoformat()
PRICE_START = "2014-01-01"                          # 多抓一年供動能因子回看

MI_INDEX = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={d}&type=ALLBUT0999&response=json"
BWIBBU = "https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?date={d}&response=json"
FINMIND = "https://api.finmindtrade.com/api/v4/data"


def get_json(url, tries=4, timeout=35):
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json, */*"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            wait = (8 if e.code in (402, 429) else 4) * (attempt + 1)
            print(f"      HTTP {e.code},{wait}s 後重試", flush=True)
            time.sleep(wait)
        except Exception as e:
            wait = 4 * (attempt + 1)
            print(f"      {type(e).__name__},{wait}s 後重試", flush=True)
            time.sleep(wait)
    return None


def num(s):
    if s is None:
        return None
    t = re.sub(r"[,\s]", "", str(s)).strip('"')
    if t in ("", "--", "-", "X", "N/A"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def quarter_starts(start, end):
    """每季第一天,實際交易日由 API 回應決定"""
    y, m = int(start[:4]), int(start[5:7])
    m = ((m - 1) // 3) * 3 + 1
    out = []
    while True:
        d = date(y, m, 1)
        if d.isoformat() > end:
            break
        out.append(d)
        m += 3
        if m > 12:
            m, y = 1, y + 1
    return out


def market_snapshot(d):
    """回傳當日 [(代號, 成交金額)];非交易日回 None"""
    j = get_json(MI_INDEX.format(d=d.strftime("%Y%m%d")))
    if not j or j.get("stat") != "OK":
        return None
    for t in j.get("tables", []):
        f = t.get("fields") or []
        if "證券代號" in f and "成交金額" in f and "收盤價" in f:
            ic, im, ip = f.index("證券代號"), f.index("成交金額"), f.index("收盤價")
            rows = []
            for r in t.get("data", []):
                code = str(r[ic]).strip().strip('"')
                if not (len(code) == 4 and code.isdigit()):
                    continue
                money, close = num(r[im]), num(r[ip])
                if not close or close <= 0 or not money:
                    continue
                rows.append((code, money))
            return rows
    return None


def valuation_snapshot(d):
    """回傳 {代號: (per, yield, pbr)};欄位結構這十年改過,依欄名對應"""
    j = get_json(BWIBBU.format(d=d.strftime("%Y%m%d")))
    if not j or j.get("stat") != "OK":
        return {}
    f = j.get("fields") or []
    need = ("證券代號", "本益比", "殖利率(%)", "股價淨值比")
    if not all(k in f for k in need):
        return {}
    ic, ie, iy, ib = (f.index(k) for k in need)
    out = {}
    for r in j.get("data", []):
        code = str(r[ic]).strip().strip('"')
        if len(code) == 4 and code.isdigit():
            per, pbr = num(r[ie]), num(r[ib])
            out[code] = (per or None, num(r[iy]), pbr or None)
    return out


def build_universes():
    """逐季建立 point-in-time 股票池"""
    print(f"=== 建立 point-in-time 股票池(每季前 {TOP_N} 名)===", flush=True)
    path = os.path.join(OUT_DIR, "universe_by_date.csv")
    members = set()
    rows_written = 0

    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "stock_id", "rank", "turnover", "per", "yield", "pbr"])

        for q in quarter_starts(START, END):
            snap, used = None, None
            # 季初可能連續放假,往後找最多 10 天直到遇到交易日
            for off in range(10):
                d = q + timedelta(days=off)
                if d.isoformat() > END:
                    break
                snap = market_snapshot(d)
                time.sleep(TWSE_PACE)
                if snap:
                    used = d
                    break
            if not snap:
                print(f"  {q} 找不到交易日,略過", flush=True)
                continue

            vals = valuation_snapshot(used)
            time.sleep(TWSE_PACE)

            snap.sort(key=lambda x: x[1], reverse=True)
            for rank, (code, money) in enumerate(snap[:TOP_N], 1):
                per, yld, pbr = vals.get(code, (None, None, None))
                w.writerow([used.isoformat(), code, rank, int(money),
                            per if per is not None else "",
                            yld if yld is not None else "",
                            pbr if pbr is not None else ""])
                members.add(code)
                rows_written += 1
            print(f"  {used}  當日全市場 {len(snap)} 檔 → 取前 {min(TOP_N, len(snap))},"
                  f"估值 {len(vals)} 檔,聯集累計 {len(members)}", flush=True)

    print(f"\n股票池完成:{rows_written} 筆,聯集 {len(members)} 檔個股", flush=True)
    return sorted(members)


FIELDS = ["date", "stock_id", "open", "max", "min", "close", "Trading_Volume"]


def existing_prices(path):
    """
    讀出已抓到的日線,回傳 (每檔的資料列, 已完成的代號集合)。
    抓取被中斷時 gzip 串流不會正常收尾,此時保留讀得到的部分並丟掉
    最後一檔(它可能只寫到一半),下次續抓時重抓那一檔即可。
    """
    if not os.path.exists(path):
        return {}, set()
    per, last_sid = {}, None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                sid = r["stock_id"]
                per.setdefault(sid, []).append([r.get(k) for k in FIELDS])
                last_sid = sid
    except (EOFError, gzip.BadGzipFile):
        if last_sid:
            per.pop(last_sid, None)          # 最後一檔可能不完整,丟掉重抓
    return per, set(per)


def fetch_prices(ids):
    """用 FinMind 抓聯集個股的日線(含已下市者),支援續抓"""
    path = os.path.join(OUT_DIR, "price.csv.gz")
    kept, done = existing_prices(path)
    todo = [s for s in ids if s not in done]

    if done:
        print(f"\n=== 續抓:已有 {len(done)} 檔,尚缺 {len(todo)} 檔 ===", flush=True)
    else:
        print(f"\n=== 抓取 {len(ids)} 檔日線({PRICE_START} ~ {END})===", flush=True)
    if not todo:
        print("  全部已完成,不需重抓", flush=True)
        return

    fields = FIELDS
    total, missing = sum(len(v) for v in kept.values()), []

    tmp = path + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8", newline="") as gz:
        w = csv.writer(gz)
        w.writerow(fields)
        for sid in ids:                       # 先寫回已完成的部分,維持代號順序
            for row in kept.get(sid, []):
                w.writerow(row)
        for i, sid in enumerate(todo, 1):
            url = (f"{FINMIND}?dataset=TaiwanStockPrice&data_id={sid}"
                   f"&start_date={PRICE_START}&end_date={END}")
            j = get_json(url)
            time.sleep(FINMIND_PACE)
            data = (j or {}).get("data") if (j or {}).get("status") == 200 else None
            if not data:
                missing.append(sid)
                continue
            for r in data:
                w.writerow([r.get(k) for k in fields])
            total += len(data)
            if i % 20 == 0 or i == len(todo):
                print(f"  [{i:4}/{len(todo)}] 累計 {total:,} 筆,缺 {len(missing)}", flush=True)

    os.replace(tmp, path)
    print(f"\n日線完成:{total:,} 筆,{os.path.getsize(path)/1024/1024:.1f} MB,"
          f"缺漏 {len(missing)} 檔 {missing[:10]}", flush=True)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    uni_path = os.path.join(OUT_DIR, "universe_by_date.csv")
    if os.path.exists(uni_path) and os.path.getsize(uni_path) > 10_000:
        with open(uni_path, encoding="utf-8") as f:
            ids = sorted({r["stock_id"] for r in csv.DictReader(f)})
        print(f"沿用既有股票池:{len(ids)} 檔(如需重建請先刪除 {uni_path})", flush=True)
    else:
        ids = build_universes()
    if not ids:
        raise SystemExit("✗ 沒有建立出任何股票池")
    fetch_prices(ids)
    print("\n全部完成", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
