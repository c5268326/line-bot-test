"""
釐清 Goodinfo 403 的成因,並找出可以取代它的資料源。

第一支探測顯示三張報表全部 403。有兩種可能,處置方式完全不同:

  A. Goodinfo 擋資料中心 IP   → 手法沒壞,只是不能在 Actions 上跑。
                                 skill 在本機仍可用,但無法納入我們的自動化管線。
  B. CLIENT_KEY 手法已失效     → 那支 skill 本身壞了,誰都跑不動。

判別方法:不帶任何 cookie 打 Goodinfo 首頁。首頁也 403 就是 A(整個 IP 被擋),
首頁通、報表頁不通才是 B。

同時測 FinMind 有沒有現金流量表 —— 若有,三表分析可以完全不靠 Goodinfo,
改用已經驗證能在 Actions 上跑的資料源。
"""
import json
import time
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def probe(url, headers=None, label=""):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            body = r.read()
            print(f"  {label}: HTTP {r.status},{len(body):,} bytes", flush=True)
            return r.status, body
    except Exception as e:
        print(f"  {label}: HTTP {getattr(e, 'code', None) or type(e).__name__}", flush=True)
        return getattr(e, "code", None), b""


print("=== 一、Goodinfo 是擋 IP 還是手法失效 ===", flush=True)
s_home, _ = probe("https://goodinfo.tw/tw/index.asp", label="首頁(不帶 cookie)")
time.sleep(2)
s_rpt, _ = probe("https://goodinfo.tw/tw/StockFinDetail.asp?RPT_CAT=IS_YEAR&STOCK_ID=2317",
                 label="報表頁(不帶 cookie)")
time.sleep(2)

if s_home == 403 and s_rpt == 403:
    print("\n  → 連首頁都 403:整個資料中心 IP 被擋。")
    print("    那支 skill 的手法沒有壞,但**無法在 GitHub Actions 上執行**,")
    print("    也就無法納入我們的自動化管線。在本機(住宅 IP)應該仍可用。", flush=True)
elif s_home and s_home < 400:
    print("\n  → 首頁通、報表頁不通:是 CLIENT_KEY 這條路失效,不是 IP 問題。", flush=True)
else:
    print(f"\n  → 首頁 {s_home}、報表頁 {s_rpt},結果不明確。", flush=True)

print("\n=== 二、FinMind 能不能取代:三張報表是否都拿得到 ===", flush=True)
FM = "https://api.finmindtrade.com/api/v4/data"
for ds, label in (("TaiwanStockFinancialStatements", "損益表"),
                  ("TaiwanStockBalanceSheet", "資產負債表"),
                  ("TaiwanStockCashFlowsStatement", "現金流量表")):
    url = f"{FM}?dataset={ds}&data_id=2317&start_date=2022-01-01&end_date=2025-12-31"
    status, body = probe(url, label=f"{label} {ds}")
    time.sleep(2)
    if status == 200 and body:
        try:
            j = json.loads(body)
        except Exception:
            continue
        data = j.get("data") or []
        if j.get("status") != 200 or not data:
            print(f"      ✗ status={j.get('status')} msg={j.get('msg')} 筆數={len(data)}", flush=True)
            continue
        types = sorted({r.get("type") for r in data if r.get("type")})
        dates = sorted({r.get("date") for r in data})
        print(f"      ✓ {len(data)} 筆,{len(types)} 個科目,期間 {dates[0]} ~ {dates[-1]}")
        print(f"        科目樣本 {types[:14]}", flush=True)

print("\n=== 三、SKILL.md 需要的關鍵科目,FinMind 有沒有 ===", flush=True)
need = {
    "TaiwanStockFinancialStatements": ["Revenue", "GrossProfit", "OperatingExpenses",
                                       "OperatingIncome", "IncomeAfterTaxes", "EPS"],
    "TaiwanStockBalanceSheet": ["CashAndCashEquivalents", "Inventories", "CurrentAssets",
                                "CurrentLiabilities", "Liabilities", "Equity", "TotalAssets"],
    "TaiwanStockCashFlowsStatement": [],
}
for ds, want in need.items():
    url = f"{FM}?dataset={ds}&data_id=2317&start_date=2024-01-01&end_date=2024-12-31"
    status, body = probe(url, label=ds)
    time.sleep(2)
    if status != 200 or not body:
        continue
    try:
        data = (json.loads(body) or {}).get("data") or []
    except Exception:
        continue
    types = sorted({r.get("type") for r in data if r.get("type")})
    if not want:
        print(f"      全部科目({len(types)} 個):{types}", flush=True)
        continue
    miss = [w for w in want if w not in types]
    print(f"      {'✓ 全部命中' if not miss else '✗ 缺 ' + str(miss)}"
          f"({len(want) - len(miss)}/{len(want)})", flush=True)
