"""
抓取回測所需的台股歷史資料,存成壓縮 CSV 供 backtest.py 使用。

在 GitHub Actions 上執行。資料會 commit 回 repo,之後調整回測邏輯就不必重抓。

資料源(皆為公開、免金鑰):
  - 證交所 STOCK_DAY_ALL / BWIBBU_d  → 決定universe(當日流動性前 N 檔)
  - FinMind TaiwanStockPrice          → 日 OHLCV
  - FinMind TaiwanStockPER            → 日 PER / PBR / 殖利率
  - FinMind TaiwanStockMonthRevenue   → 月營收

產出:
  research/data/universe.csv
  research/data/price.csv.gz
  research/data/valuation.csv.gz
  research/data/revenue.csv.gz
"""
import csv
import gzip
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")

START_DATE = "2014-01-01"          # 多抓一年,讓 2015 起的回測有足夠的回看期
END_DATE = date.today().isoformat()
UNIVERSE_SIZE = int(os.environ.get("UNIVERSE_SIZE", "120"))
PACE = float(os.environ.get("FINMIND_PACE", "1.1"))   # 每次請求間隔秒數

UA = "Mozilla/5.0 (compatible; tw-backtest-research/1.0)"
FINMIND = "https://api.finmindtrade.com/api/v4/data"


# ------------------------------------------------------------------ HTTP

def http_get(url, timeout=40, tries=4):
    """帶退避重試的 GET。回傳 bytes,失敗回 None。"""
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "application/json, text/csv, */*",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            # 402/429 都代表被限流,等久一點再試
            wait = (6 if e.code in (402, 429) else 2) * (attempt + 1) ** 2
            print(f"      HTTP {e.code},{wait}s 後重試({attempt + 1}/{tries})", flush=True)
            time.sleep(wait)
        except Exception as e:
            wait = 2 * (attempt + 1) ** 2
            print(f"      {type(e).__name__},{wait}s 後重試({attempt + 1}/{tries})", flush=True)
            time.sleep(wait)
    return None


def finmind(dataset, stock_id, start=START_DATE, end=END_DATE):
    url = FINMIND + "?" + urllib.parse.urlencode({
        "dataset": dataset, "data_id": stock_id,
        "start_date": start, "end_date": end,
    })
    raw = http_get(url)
    if not raw:
        return None
    try:
        j = json.loads(raw)
    except Exception:
        return None
    if j.get("status") != 200:
        print(f"      FinMind 回應 status={j.get('status')} msg={j.get('msg')!r}", flush=True)
        return None
    return j.get("data") or []


# ------------------------------------------------------------------ universe

def build_universe(n):
    """
    以證交所當日資料決定 universe:
    取「有本益比/淨值比資料」且「成交金額最大」的前 n 檔上市普通股。

    ⚠ 這是用『今天』的流動性回頭選股,存在倖存者偏誤與前視偏誤。
      回測報告中會標示此限制。
    """
    print("決定 universe …", flush=True)

    raw = http_get("https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?response=json")
    if not raw:
        sys.exit("✗ 無法取得 BWIBBU_d")
    bw = json.loads(raw)
    have_fundamentals = {row[0].strip() for row in bw.get("data", [])}
    print(f"  有估值資料的個股:{len(have_fundamentals)} 檔", flush=True)
    time.sleep(3)

    raw = http_get("https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL?response=json")
    if not raw:
        sys.exit("✗ 無法取得 STOCK_DAY_ALL")
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    print(f"  當日成交資料:{len(rows)} 檔", flush=True)

    cand = []
    for r in rows:
        code = (r.get("證券代號") or "").strip().strip('"')
        name = (r.get("證券名稱") or "").strip().strip('"')
        # 只要四碼數字的普通股,排除 ETF、權證、特別股、存託憑證
        if not (len(code) == 4 and code.isdigit()):
            continue
        if code not in have_fundamentals:
            continue
        try:
            turnover = float((r.get("成交金額") or "0").replace(",", "").strip('"'))
        except ValueError:
            continue
        cand.append((turnover, code, name))

    cand.sort(reverse=True)
    picked = cand[:n]
    print(f"  篩出普通股 {len(cand)} 檔,取成交金額前 {len(picked)} 檔", flush=True)

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "universe.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["stock_id", "name", "turnover_at_selection"])
        for turnover, code, name in picked:
            w.writerow([code, name, int(turnover)])

    return [(code, name) for _, code, name in picked]


# ------------------------------------------------------------------ 主流程

DATASETS = [
    # (檔名, FinMind dataset, 要保留的欄位)
    ("price.csv.gz", "TaiwanStockPrice",
     ["date", "stock_id", "open", "max", "min", "close", "Trading_Volume", "Trading_money"]),
    ("valuation.csv.gz", "TaiwanStockPER",
     ["date", "stock_id", "PER", "PBR", "dividend_yield"]),
    ("revenue.csv.gz", "TaiwanStockMonthRevenue",
     ["date", "stock_id", "revenue", "revenue_year", "revenue_month"]),
]


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    # 只跑指定的資料集(逗號分隔),讓抓取可以分段進行。
    # 一次跑完三個資料集需要 360 次請求,很容易撞上 FinMind 的匿名額度;
    # 分段跑則每段結束就 commit,中斷不會讓先前的進度歸零。
    only = {s.strip() for s in os.environ.get("ONLY_DATASETS", "").split(",") if s.strip()}

    universe_path = os.path.join(DATA_DIR, "universe.csv")
    if os.path.exists(universe_path) and only:
        # 分段跑時沿用既有 universe,否則每段選到的股票會不一致
        with open(universe_path, encoding="utf-8") as f:
            ids = [r["stock_id"] for r in csv.DictReader(f)]
        print(f"沿用既有 universe:{len(ids)} 檔", flush=True)
    else:
        ids = [c for c, _ in build_universe(UNIVERSE_SIZE)]

    print(f"\n抓取區間 {START_DATE} ~ {END_DATE},共 {len(ids)} 檔", flush=True)

    for filename, dataset, fields in DATASETS:
        if only and dataset not in only:
            print(f"\n=== 略過 {dataset}(不在 ONLY_DATASETS 內)===", flush=True)
            continue

        path = os.path.join(DATA_DIR, filename)
        if os.path.exists(path) and os.path.getsize(path) > 50_000 and not only:
            print(f"\n=== {filename} 已存在且有內容,略過 ===", flush=True)
            continue

        print(f"\n=== {dataset} → {filename} ===", flush=True)
        total, missing = 0, []

        with gzip.open(path, "wt", encoding="utf-8", newline="") as gz:
            w = csv.writer(gz)
            w.writerow(fields)
            for i, sid in enumerate(ids, 1):
                data = finmind(dataset, sid)
                time.sleep(PACE)
                if not data:
                    missing.append(sid)
                    print(f"  [{i:3}/{len(ids)}] {sid} ✗", flush=True)
                    continue
                for row in data:
                    w.writerow([row.get(k) for k in fields])
                total += len(data)
                if i % 20 == 0 or i == len(ids):
                    print(f"  [{i:3}/{len(ids)}] 累計 {total:,} 筆", flush=True)

        size_mb = os.path.getsize(path) / 1024 / 1024
        print(f"  完成:{total:,} 筆,{size_mb:.1f} MB,缺漏 {len(missing)} 檔 {missing[:10]}", flush=True)

    print("\n全部完成", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
