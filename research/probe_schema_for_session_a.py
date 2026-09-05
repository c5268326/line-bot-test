"""
逐條驗證 tw_stock_backtest/ 對資料源的假設(那份程式是在無法連網的環境寫的)。

只做「假設 vs 實際」的比對,不改對方任何檔案。每一條都印出實際回傳的欄位/科目名稱,
對不上時直接指出要改哪一個常數。

重點在那些「猜錯不會報錯」的地方 —— 例如 pick() 找不到科目時回傳空 Series,
ROE 會整欄變成 NaN,因子照樣參與排序,只是完全沒有訊號。這種錯不會拋例外。
"""
import json
import time
import urllib.request

UA = "Mozilla/5.0 (compatible; tw-backtest-research/1.0)"
FINMIND = "https://api.finmindtrade.com/api/v4/data"
PASS, FAIL, WARN = [], [], []


def get(url, timeout=35, tries=3):
    for i in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json, */*"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read()
        except Exception as e:
            code = getattr(e, "code", None)
            if code and code not in (402, 429):
                return code, b""
            time.sleep(6 * (i + 1))
    return None, b""


def fm(dataset, data_id=None, start="2023-01-01", end="2023-12-31"):
    url = f"{FINMIND}?dataset={dataset}&start_date={start}&end_date={end}"
    if data_id:
        url += f"&data_id={data_id}"
    status, body = get(url)
    time.sleep(2.0)
    if status != 200 or not body:
        return None, f"HTTP {status}"
    try:
        j = json.loads(body)
    except Exception as e:
        return None, f"JSON 解析失敗 {e}"
    if j.get("status") != 200:
        return None, f"status={j.get('status')} msg={j.get('msg')}"
    return j.get("data") or [], None


def check(label, ok, detail):
    (PASS if ok else FAIL).append(label)
    print(f"  {'✓' if ok else '✗'} {label}\n      {detail}", flush=True)


print("=" * 72)
print("1. STOCK_DAY 舊端點是否還活著(twse_source.py 用位置索引取值)")
print("=" * 72)
OLD = "https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date=20230103&stockNo=2330"
NEW = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?response=json&date=20230103&stockNo=2330"
for name, url in (("舊 /exchangeReport/", OLD), ("新 /rwd/zh/afterTrading/", NEW)):
    status, body = get(url)
    time.sleep(2.5)
    fields = None
    if status == 200 and body:
        try:
            j = json.loads(body)
            fields = j.get("fields")
        except Exception:
            pass
    print(f"  {name}: HTTP {status},fields={fields}", flush=True)
    if name.startswith("舊") :
        if fields:
            want = ["日期", "成交股數", "成交金額", "開盤價", "最高價", "最低價", "收盤價"]
            got = fields[:7]
            check("STOCK_DAY 欄位順序與 twse_source.py 的位置索引一致",
                  got == want, f"實際前七欄 {got}")
        else:
            check("STOCK_DAY 舊端點可用", False,
                  f"HTTP {status} —— twse_source.py 的 STOCK_DAY_URL 需要改成 /rwd/zh/afterTrading/STOCK_DAY")

print()
print("=" * 72)
print("2. FinMind dataset 名稱是否存在")
print("=" * 72)
for ds, did in (("TaiwanStockPrice", "2330"), ("TaiwanStockPER", "2330"),
                ("TaiwanStockMonthRevenue", "2330"),
                ("TaiwanStockFinancialStatements", "2330"),
                ("TaiwanStockBalanceSheet", "2330"),
                ("TaiwanExchangeRate", "USD")):
    data, err = fm(ds, did)
    if data is None:
        check(f"dataset {ds}", False, err)
    elif not data:
        check(f"dataset {ds}", False, "回傳 0 筆(名稱可能對,但這個 data_id 沒資料)")
    else:
        check(f"dataset {ds}", True, f"{len(data)} 筆,欄位 {sorted(data[0].keys())}")

print()
print("=" * 72)
print("3. 財報長格式的 type 值 —— pick() 猜錯會靜默變成整欄 NaN")
print("=" * 72)
for ds, cands in (
    ("TaiwanStockFinancialStatements",
     {"revenue": ["Revenue", "OperatingRevenue"], "gross_profit": ["GrossProfit"],
      "net_income": ["IncomeAfterTaxes", "ProfitLoss", "NetIncome"],
      "eps": ["EPS", "BasicEarningsPerShare"]}),
    ("TaiwanStockBalanceSheet",
     {"equity": ["Equity", "EquityAttributableToOwnersOfParent"],
      "liabilities": ["Liabilities", "TotalLiabilities"]}),
):
    data, err = fm(ds, "2330")
    if not data:
        print(f"  ⚠ {ds} 取不到資料({err}),無法核對科目", flush=True)
        WARN.append(ds)
        continue
    types = sorted({r.get("type") for r in data if r.get("type")})
    print(f"  {ds} 實際科目 {len(types)} 個:")
    print(f"      {types}", flush=True)
    for field, cand in cands.items():
        hit = [c for c in cand if c in types]
        check(f"{ds}.{field} 候選 {cand}", bool(hit),
              f"命中 {hit}" if hit else "全部沒命中 → 這個因子會整欄 NaN,而且不會報錯")

print()
print("=" * 72)
print("4. 月營收的 date 是「營收月份」還是「公告日」—— 差別是前視偏誤")
print("=" * 72)
data, err = fm("TaiwanStockMonthRevenue", "2330", "2023-01-01", "2023-06-30")
if data:
    for r in data[:5]:
        print(f"      date={r.get('date')}  revenue_year={r.get('revenue_year')}"
              f"  revenue_month={r.get('revenue_month')}", flush=True)

    def next_month(y, m):
        return (y + 1, 1) if m == 12 else (y, m + 1)

    shifted = 0
    for r in data:
        try:
            y, m = int(r["revenue_year"]), int(r["revenue_month"])
            dy, dm = int(str(r["date"])[:4]), int(str(r["date"])[5:7])
        except (KeyError, TypeError, ValueError):
            continue
        if (dy, dm) == next_month(y, m):
            shifted += 1
    # 台股規定次月 10 日前公布。FinMind 的 date 是「次月 1 日」,
    # 比真正可用的日子早了最多 9 天 —— 拿它當公告日就是這麼多天的前視偏誤。
    check("date 欄 = 營收月份的次月 1 日(既不是營收月,也不是公告日)",
          shifted == len(data),
          f"{shifted}/{len(data)} 筆符合。finmind_source._get_revenue_yoy 直接把 date "
          "當公告日,會早於法定的次月 10 日,最多 9 天前視;"
          "它自己的 fallback(次月 +10 天)反而是對的")
else:
    print(f"  ⚠ 取不到月營收({err})", flush=True)
    WARN.append("MonthRevenue")

print()
print("=" * 72)
print("5. TaiwanExchangeRate 的欄位是否有 cash_sell / spot_sell")
print("=" * 72)
data, err = fm("TaiwanExchangeRate", "USD", "2023-01-01", "2023-01-31")
if data:
    cols = sorted(data[0].keys())
    check("cash_sell 或 spot_sell 存在", any(c in cols for c in ("cash_sell", "spot_sell")),
          f"實際欄位 {cols}")
else:
    print(f"  ⚠ 取不到匯率({err})", flush=True)
    WARN.append("ExchangeRate")

print()
print("=" * 72)
print(f"通過 {len(PASS)}、不符 {len(FAIL)}、無法判定 {len(WARN)}")
if FAIL:
    print("\n需要修正:")
    for f in FAIL:
        print(f"  ✗ {f}")
print("=" * 72)
