"""
探測證交所「全市場某一日」的歷史端點是否可用。

FinMind 匿名配額已耗盡,改走證交所路線:一次請求拿當日全市場所有個股,
約 2750 次請求即可覆蓋 11 年。這條路沒有硬性配額,只需禮貌性間隔,
而且能建立逐日的 point-in-time universe,大幅修正倖存者偏誤。

發動 2750 次請求之前,先確認這些端點吃不吃 date 參數、欄位長什麼樣。
"""
import json
import time
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (compatible; tw-backtest-research/1.0)"


def probe(url, label, show=3):
    print(f"\n{'=' * 74}\n【{label}】\n{url}")
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json, text/plain, */*"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        print(f"  ✗ HTTP {e.code} {e.reason}")
        return None
    except Exception as e:
        print(f"  ✗ {type(e).__name__}: {e}")
        return None

    print(f"  HTTP 200  {len(raw):,} bytes")
    try:
        j = json.loads(raw)
    except Exception:
        print(f"  ✗ 非 JSON,前 160 字元:{raw[:160]!r}")
        return None

    print(f"  頂層鍵:{list(j.keys())}")
    for k in ("stat", "date", "title"):
        if k in j:
            print(f"    {k}: {j[k]!r}")

    # MI_INDEX 會回傳多個表格(tables),BWIBBU_d 則是 fields/data
    if "tables" in j:
        print(f"    tables: {len(j['tables'])} 個")
        for i, t in enumerate(j["tables"]):
            n = len(t.get("data") or [])
            print(f"      [{i}] {t.get('title', '')[:40]!r} 欄位{len(t.get('fields') or [])} 筆數{n}")
            if n and t.get("fields") and len(t["fields"]) > 10:
                print(f"          fields: {t['fields']}")
                for row in t["data"][:show]:
                    print(f"          {row}")
    for k in ("fields", "data"):
        if k in j and isinstance(j[k], list):
            print(f"    {k}: {len(j[k])} 筆")
            if k == "fields":
                print(f"      {j[k]}")
            else:
                for row in j[k][:show]:
                    print(f"      {row}")
    return j


def main():
    print("證交所歷史端點探測")

    # 全市場某日收盤(ALLBUT0999 = 全部,不含權證)
    probe("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
          "?date=20240102&type=ALLBUT0999&response=json",
          "MI_INDEX 全市場日收盤(2024-01-02)")
    time.sleep(3)

    # 全市場某日本益比/殖利率/淨值比
    probe("https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d"
          "?date=20240102&response=json",
          "BWIBBU_d 全市場日估值(帶 date)")
    time.sleep(3)

    # 較早年份,確認歷史深度
    probe("https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d"
          "?date=20150105&response=json",
          "BWIBBU_d 全市場日估值(2015-01-05,測歷史深度)")
    time.sleep(3)

    probe("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
          "?date=20150105&type=ALLBUT0999&response=json",
          "MI_INDEX 全市場日收盤(2015-01-05,測歷史深度)")
    time.sleep(3)

    # 非交易日的行為(元旦)
    probe("https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d"
          "?date=20240101&response=json",
          "BWIBBU_d 非交易日(2024-01-01,確認回傳形式)")

    print(f"\n{'=' * 74}\n探測結束")


if __name__ == "__main__":
    main()
