"""
測 FinMind 有沒有保留「已下市公司」的歷史資料。

這決定了修正倖存者偏誤要用哪種做法:

  A. 每個交易日都抓證交所全市場(約 3000 次請求、7 小時)
     —— 一定包含下市公司,但很慢

  B. 只在換股日抓證交所建立 point-in-time 股票池(47 次請求、幾分鐘),
     再用 FinMind 補這些股票的日線
     —— 快很多,但前提是 FinMind 對下市公司也有資料

做法:拿 2015 年初的全市場清單,比對今天的清單,找出已經消失的代號,
再問 FinMind 要不要得到它們 2015 年的日線。
"""
import json
import time
import urllib.request

UA = "Mozilla/5.0 (compatible; tw-backtest-research/1.0)"
MI = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={d}&type=ALLBUT0999&response=json"
FINMIND = ("https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice"
           "&data_id={sid}&start_date=2015-01-01&end_date=2015-06-30")


def get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json, */*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"    ✗ {type(e).__name__}: {e}")
        return None


def market_codes(datestr):
    """回傳該日全市場四碼普通股的 {代號: 名稱}"""
    j = get(MI.format(d=datestr))
    if not j or j.get("stat") != "OK":
        return {}
    for t in j.get("tables", []):
        f = t.get("fields") or []
        if "證券代號" in f and "收盤價" in f:
            i_code, i_name = f.index("證券代號"), f.index("證券名稱")
            return {
                str(r[i_code]).strip().strip('"'): str(r[i_name]).strip()
                for r in t.get("data", [])
                if len(str(r[i_code]).strip().strip('"')) == 4
                and str(r[i_code]).strip().strip('"').isdigit()
            }
    return {}


def main():
    print("取得 2015-01-05 全市場清單 …")
    old = market_codes("20150105")
    print(f"  {len(old)} 檔")
    time.sleep(3)

    print("取得 2026-09-04 全市場清單 …")
    new = market_codes("20260904")
    print(f"  {len(new)} 檔")

    if not old or not new:
        raise SystemExit("✗ 取不到清單,無法比較")

    gone = sorted(set(old) - set(new))
    added = sorted(set(new) - set(old))
    print(f"\n2015 有、2026 沒有(已下市或改代號):{len(gone)} 檔")
    print(f"  {[(c, old[c]) for c in gone[:12]]}")
    print(f"2026 有、2015 沒有(期間新上市):{len(added)} 檔")

    print(f"\n這 {len(gone)} 檔就是先前回測完全看不到的公司 —— 倖存者偏誤的來源。")

    print("\n=== 測 FinMind 對這些已消失代號有沒有資料 ===")
    hit = miss = 0
    for sid in gone[:10]:
        j = get(FINMIND.format(sid=sid))
        time.sleep(2)
        n = len(j.get("data") or []) if j and j.get("status") == 200 else 0
        if n:
            hit += 1
            print(f"  ✓ {sid} {old[sid]}: {n} 筆(2015 上半年)")
        else:
            miss += 1
            print(f"  ✗ {sid} {old[sid]}: 無資料")

    print(f"\n抽測 10 檔:有資料 {hit},無資料 {miss}")
    if hit >= 7:
        print("→ FinMind 保留下市公司資料,可採用做法 B(快很多)")
    elif hit == 0:
        print("→ FinMind 沒有下市公司資料,必須採用做法 A(每日全市場,較慢)")
    else:
        print("→ FinMind 覆蓋不完整,採用做法 A 較穩妥")


if __name__ == "__main__":
    main()
