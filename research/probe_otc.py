"""
查明 4939 亞電、6735 美達科技為什麼沒有籌碼資料。

觀察到的事實:chips.json 涵蓋 674 檔裡的 672 檔,而且**沒有任何一檔**的
籌碼是從櫃買日報來的(全部都有外資分項,代表全部來自證交所 T86)。

這個現象有兩種解釋,必須分開:
  A) 櫃買的解析壞了,一直回空 —— 那是我的 bug
  B) 櫃買解析正常,只是我的 674 檔裡本來就沒有上櫃股票,
     而這兩檔連櫃買日報也沒有(例如它們其實是興櫃)

兩種都會產生「0 檔來自櫃買」,所以不能從結果反推。直接去看:
櫃買日報到底回幾列、這兩檔在不在裡面。

順帶確認一個在探測階段就看到、但當時沒追的疑點:
櫃買的 API 帶 date=2026-09-10 卻回 date='20260911'。
如果它根本不看 date 參數、永遠回最新的一天,那我抓 30 天等於
把同一天的資料貼到 30 個不同日期上 —— 那比沒有資料更糟。

    python research/probe_otc.py
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fetch_chips as F   # noqa: E402  用同一份解析程式,才測得到真正的行為

TARGETS = ["4939", "6735"]
FINMIND = "https://api.finmindtrade.com/api/v4/data"


def raw(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": F.UA, "Accept": "application/json, */*"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"    ✗ HTTP {e.code}")
    except Exception as e:
        print(f"    ✗ {type(e).__name__}: {e}")
    return None


def main():
    days = ["2026-09-08", "2026-09-09", "2026-09-10"]

    print("########## 一、櫃買日報實際回了什麼 ##########")
    for d in days:
        inst = F.tpex_inst(d)
        time.sleep(1.2)
        marg = F.tpex_margin(d)
        time.sleep(1.2)
        print(f"\n  {d}")
        print(f"    tpex_inst   回 {len(inst):>4} 檔"
              f"{'  ← 空的,解析有問題' if not inst else ''}")
        print(f"    tpex_margin 回 {len(marg):>4} 檔"
              f"{'  ← 空的,解析有問題' if not marg else ''}")
        for t in TARGETS:
            print(f"    {t}: 法人 {'有' if t in inst else '不在清單'}"
                  f" / 融資 {'有' if t in marg else '不在清單'}")

    print("\n\n########## 二、櫃買到底看不看 date 參數 ##########")
    print("  (探測時帶 09-10 卻回 09-11,要確認不是把同一天貼到 30 個日期上)")
    for d in ["2026-08-14", "2026-09-01", "2026-09-10"]:
        j = raw(f"https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade"
                f"?type=Daily&sect=EW&date={d}&response=json")
        if not j:
            continue
        tb = next((t for t in (j.get("tables") or [])
                   if "三大法人" in (t.get("title") or "")), None)
        n = len(tb.get("data") or []) if tb else 0
        # 取同一檔的數字,若三個日期都一樣就是完全沒在看 date
        sample = None
        for r in (tb.get("data") or []) if tb else []:
            if str(r[0]).strip() == "5483":
                sample = r[-1]
                break
        print(f"    要求 {d} → 回應 date={j.get('date')!r}  {n} 列"
              f"  5483 三大法人合計={sample}")

    print("\n\n########## 三、這兩檔在 FinMind 眼中是什麼 ##########")
    j = raw(f"{FINMIND}?dataset=TaiwanStockInfo")
    rows = (j or {}).get("data") or []
    idx = {}
    for r in rows:
        idx.setdefault(r.get("stock_id"), r)
    for t in TARGETS:
        r = idx.get(t)
        print(f"    {t}: {r.get('stock_name') if r else '查無'}"
              f"  type={r.get('type') if r else '—'}"
              f"  industry={r.get('industry_category') if r else '—'}"
              f"  date={r.get('date') if r else '—'}")
    time.sleep(2)

    print("\n\n########## 四、FinMind 有沒有這兩檔的法人買賣超 ##########")
    for t in TARGETS:
        j = raw(f"{FINMIND}?dataset=TaiwanStockInstitutionalInvestorsBuySell"
                f"&data_id={t}&start_date=2026-09-01&end_date=2026-09-10")
        d = (j or {}).get("data") or []
        print(f"    {t}: {len(d)} 筆  msg={(j or {}).get('msg')!r}")
        for r in d[:3]:
            print(f"      {r}")
        time.sleep(2)


if __name__ == "__main__":
    sys.exit(main())
