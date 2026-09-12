"""
探測「籌碼面」資料拿不拿得到:三大法人買賣超、融資融券、借券、外資持股、月營收。

在 GitHub Actions 上執行(沙箱沒有對外網路)。

重點不是「有沒有這個 API」,而是兩件事:
  1) 欄位實際長什麼樣 —— 憑記憶假設欄位名是之前踩過的坑
  2) 是「全市場一次給完」還是「一檔一個 request」
     —— MI_INDEX 的經驗:全市場快照 1 個 request 抵 674 個。
        FinMind 的配額是以小時計的,能用證交所端點就不要用 FinMind。

分點進出(摩根士丹利買超 X 張)刻意不列:證交所沒有免費的個股分點日資料,
那是付費／爬蟲來源,這裡拿不到就是拿不到,不要假裝有。

    python research/probe_chips.py
"""
import json
import os
import time
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (compatible; stock-research/1.0)"
TIMEOUT = 30
FINMIND = "https://api.finmindtrade.com/api/v4/data"
PACE = float(os.environ.get("FINMIND_PACE", "2.0"))

# 找一個「一定有交易」的日子當樣本。太近的日期可能還沒公布。
SAMPLE_DAY = os.environ.get("SAMPLE_DAY", "2026-09-10")
SID = os.environ.get("SAMPLE_SID", "2409")


def get(url, label):
    print(f"\n{'=' * 74}\n【{label}】\n  {url}")
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json, text/plain, */*"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read()
            print(f"  HTTP {r.status}  {len(raw):,} bytes")
            return raw
    except urllib.error.HTTPError as e:
        body = b""
        try:
            body = e.read()[:200]
        except Exception:
            pass
        print(f"  ✗ HTTP {e.code} {e.reason}  {body!r}")
    except Exception as e:
        print(f"  ✗ {type(e).__name__}: {e}")
    return None


def finmind(dataset, **kw):
    q = "&".join(f"{k}={v}" for k, v in kw.items())
    raw = get(f"{FINMIND}?dataset={dataset}&{q}", f"FinMind {dataset}")
    time.sleep(PACE)
    if not raw:
        return None
    j = json.loads(raw)
    msg, data = j.get("msg"), j.get("data")
    print(f"  msg={msg!r}  筆數={len(data) if isinstance(data, list) else data!r}")
    if isinstance(data, list) and data:
        print(f"  欄位: {sorted(data[0].keys())}")
        for row in data[:3]:
            print(f"    {row}")
    return data


def twse(url, label):
    raw = get(url, label)
    if not raw:
        return None
    try:
        j = json.loads(raw)
    except Exception:
        print(f"  ✗ 不是 JSON,前 200 字:{raw[:200]!r}")
        return None
    print(f"  頂層鍵: {list(j.keys())}")
    for k in ("stat", "date", "title", "total"):
        if k in j:
            print(f"    {k}: {j[k]!r}")
    for k in ("fields", "data", "tables"):
        v = j.get(k)
        if isinstance(v, list) and v:
            if k == "tables":
                for t in v:
                    print(f"    table: {t.get('title')!r}  "
                          f"欄位 {t.get('fields')}  {len(t.get('data') or [])} 列")
                    for row in (t.get("data") or [])[:2]:
                        print(f"      {row}")
            else:
                print(f"    {k}: {len(v)} 筆")
                for row in v[:3]:
                    print(f"      {row}")
    return j


def main():
    d = SAMPLE_DAY
    dnodash = d.replace("-", "")
    print(f"樣本日 {d} ・ 樣本個股 {SID}")

    print("\n\n########## 一、證交所:全市場一次給完(最省) ##########")
    # 三大法人買賣超日報:全市場,1 個 request
    twse(f"https://www.twse.com.tw/rwd/zh/fund/T86?date={dnodash}&selectType=ALL&response=json",
         "TWSE T86 三大法人買賣超(全市場)")
    # 融資融券餘額:全市場,1 個 request
    twse(f"https://www.twse.com.tw/rwd/zh/margin/MI_MARGN?date={dnodash}&selectType=ALL&response=json",
         "TWSE MI_MARGN 融資融券(全市場)")
    # 外資及陸資買賣超彙總
    twse(f"https://www.twse.com.tw/rwd/zh/fund/TWT38U?date={dnodash}&response=json",
         "TWSE TWT38U 外資買賣超前段")
    # 借券賣出餘額
    twse(f"https://www.twse.com.tw/rwd/zh/SBL/TWT93U?date={dnodash}&response=json",
         "TWSE TWT93U 借券賣出")
    # 個股日本益比/殖利率/淨值比(全市場)
    twse(f"https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?date={dnodash}&selectType=ALL&response=json",
         "TWSE BWIBBU_d 本益比殖利率淨值比(全市場)")

    print("\n\n########## 二、櫃買中心(上櫃股票走這裡)##########")
    twse(f"https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?type=Daily&sect=EW&date={d}&response=json",
         "TPEx 上櫃三大法人")

    print("\n\n########## 三、FinMind(一檔一個 request,配額以小時計)##########")
    finmind("TaiwanStockInstitutionalInvestorsBuySell",
            data_id=SID, start_date="2026-09-01", end_date=d)
    finmind("TaiwanStockMarginPurchaseShortSale",
            data_id=SID, start_date="2026-09-01", end_date=d)
    finmind("TaiwanStockShareholding", data_id=SID, start_date="2026-09-01", end_date=d)
    finmind("TaiwanStockSecuritiesLending", data_id=SID, start_date="2026-09-01", end_date=d)
    finmind("TaiwanStockMonthRevenue", data_id=SID, start_date="2025-01-01", end_date=d)
    finmind("TaiwanStockPER", data_id=SID, start_date="2026-09-01", end_date=d)

    print("\n\n########## 結論要看的兩件事 ##########")
    print("  1. 證交所那幾個端點若可用 → 全市場一次抓完,不吃 FinMind 配額")
    print("  2. 上櫃股票證交所端點沒有 → 只能靠 TPEx 或 FinMind")


if __name__ == "__main__":
    main()
