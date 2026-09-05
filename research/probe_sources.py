"""
探測各個台股公開資料源目前是否可用,以及回傳的實際欄位長什麼樣。

在 GitHub Actions 上執行(本地沙箱沒有對外網路)。
目的是在動手寫回測之前,先確認資料拿得到、格式是什麼,
而不是憑記憶假設某個 API 還活著。

    python research/probe_sources.py
"""
import json
import time
import urllib.request
import urllib.error

UA = "Mozilla/5.0 (compatible; backtest-research/1.0)"
TIMEOUT = 25


def get(url, label):
    print(f"\n{'=' * 72}\n【{label}】\n{url}")
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read()
            print(f"  HTTP {r.status}  {len(raw)} bytes  {r.headers.get('Content-Type', '')}")
            return raw
    except urllib.error.HTTPError as e:
        print(f"  ✗ HTTP {e.code} {e.reason}")
    except Exception as e:
        print(f"  ✗ {type(e).__name__}: {e}")
    return None


def show_json(raw, keys_only=False, sample=2):
    if not raw:
        return None
    try:
        j = json.loads(raw)
    except Exception as e:
        print(f"  ✗ 不是合法 JSON: {e}")
        print(f"  前 200 字元: {raw[:200]!r}")
        return None

    if isinstance(j, dict):
        print(f"  頂層鍵: {list(j.keys())}")
        for k in ("stat", "msg", "status", "date", "title"):
            if k in j:
                print(f"    {k}: {j[k]!r}")
        for k in ("fields", "data", "msgArray"):
            if k in j and isinstance(j[k], list):
                print(f"    {k}: {len(j[k])} 筆")
                if not keys_only:
                    for row in j[k][:sample]:
                        print(f"      {row}")
    elif isinstance(j, list):
        print(f"  陣列 {len(j)} 筆")
        for row in j[:sample]:
            print(f"    {row}")
    return j


def main():
    print("台股公開資料源探測")
    print(f"時間: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    # ---- 1. 證交所 個股日成交資訊(價格 OHLCV,一次一個月) ----
    show_json(get(
        "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
        "?date=20240102&stockNo=2330&response=json",
        "TWSE 個股日成交 STOCK_DAY(2330 / 2024-01)"))
    time.sleep(3)

    # ---- 2. 證交所 個股本益比、殖利率、股價淨值比(估值,一次一個月) ----
    show_json(get(
        "https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU"
        "?date=20240102&stockNo=2330&response=json",
        "TWSE 個股估值 BWIBBU(2330 / 2024-01)"))
    time.sleep(3)

    # ---- 3. 證交所 全市場當日估值(一次拿全部個股) ----
    show_json(get(
        "https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?response=json",
        "TWSE 全市場當日估值 BWIBBU_d"), sample=3)
    time.sleep(3)

    # ---- 4. 證交所 全市場當日收盤(一次拿全部個股) ----
    show_json(get(
        "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL?response=json",
        "TWSE 全市場當日收盤 STOCK_DAY_ALL"), sample=3)
    time.sleep(3)

    # ---- 5. 上櫃 OTC 日收盤 ----
    show_json(get(
        "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
        "TPEx 上櫃當日收盤 OpenAPI"), sample=2)
    time.sleep(2)

    # ---- 6. FinMind 股價(免 token,一次可拿多年) ----
    show_json(get(
        "https://api.finmindtrade.com/api/v4/data"
        "?dataset=TaiwanStockPrice&data_id=2330&start_date=2024-01-01&end_date=2024-03-31",
        "FinMind TaiwanStockPrice(匿名)"))
    time.sleep(2)

    # ---- 7. FinMind 本益比/淨值比 ----
    show_json(get(
        "https://api.finmindtrade.com/api/v4/data"
        "?dataset=TaiwanStockPER&data_id=2330&start_date=2024-01-01&end_date=2024-03-31",
        "FinMind TaiwanStockPER(匿名)"))
    time.sleep(2)

    # ---- 8. FinMind 月營收 ----
    show_json(get(
        "https://api.finmindtrade.com/api/v4/data"
        "?dataset=TaiwanStockMonthRevenue&data_id=2330&start_date=2023-01-01&end_date=2024-06-30",
        "FinMind 月營收(匿名)"))
    time.sleep(2)

    # ---- 9. FinMind 綜合損益表(算 ROE 用) ----
    show_json(get(
        "https://api.finmindtrade.com/api/v4/data"
        "?dataset=TaiwanStockFinancialStatements&data_id=2330&start_date=2023-01-01&end_date=2024-06-30",
        "FinMind 財報(匿名)"))
    time.sleep(2)

    # ---- 10. FinMind 三大法人買賣超 ----
    show_json(get(
        "https://api.finmindtrade.com/api/v4/data"
        "?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id=2330"
        "&start_date=2024-01-01&end_date=2024-01-31",
        "FinMind 三大法人(匿名)"))
    time.sleep(2)

    # ---- 11. Yahoo Finance(備援價格來源) ----
    show_json(get(
        "https://query1.finance.yahoo.com/v8/finance/chart/2330.TW"
        "?range=1y&interval=1d",
        "Yahoo Finance chart(2330.TW)"), keys_only=True)

    print(f"\n{'=' * 72}\n探測結束")


if __name__ == "__main__":
    main()
