"""
證交所當日全市場收盤資料。

只依賴標準函式庫,不牽涉 Flask 或 LINE SDK,所以可以獨立測試
(見 research/test_twse_live.py)。

網頁在瀏覽器裡不能直接抓證交所 —— 對方沒有給跨網域標頭,會被 CORS 擋。
由伺服器代抓就沒有這個限制,而且證交所有「全市場當日收盤」這個端點,
一次請求就能拿到所有個股,不論監測幾檔都只打對方一次。
"""
import csv
import io
import urllib.request

STOCK_DAY_ALL = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL?response=json"
UA = "Mozilla/5.0 (compatible; tw-signal-station/1.0)"


def _num(s):
    try:
        return float(str(s).replace(",", "").strip('"'))
    except (TypeError, ValueError):
        return None


def roc_to_iso(raw):
    """民國年 7 碼(1150904)轉西元 ISO 日期,格式不符回傳 None"""
    raw = str(raw).strip().strip('"')
    if len(raw) != 7 or not raw.isdigit():
        return None
    y, m, d = int(raw[:3]) + 1911, raw[3:5], raw[5:7]
    if not (1 <= int(m) <= 12 and 1 <= int(d) <= 31):
        return None
    return f"{y}-{m}-{d}"


def fetch_today(timeout=20):
    """
    回傳 {股票代號: [日期, 開, 高, 低, 收, 成交量(張)]}。

    只收四碼數字的普通股,排除 ETF、權證、特別股。
    成交量由「股」換算為「張」,與台股看盤習慣一致。
    """
    req = urllib.request.Request(STOCK_DAY_ALL, headers={
        "User-Agent": UA,
        "Accept": "text/csv, application/json, */*",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8-sig")

    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        code = (row.get("證券代號") or "").strip().strip('"')
        if not (len(code) == 4 and code.isdigit()):
            continue

        iso = roc_to_iso(row.get("日期"))
        if not iso:
            continue

        c = _num(row.get("收盤價"))
        if not c or c <= 0:
            continue

        o = _num(row.get("開盤價")) or c
        h = _num(row.get("最高價")) or c
        lo = _num(row.get("最低價")) or c
        shares = _num(row.get("成交股數")) or 0

        # 少數情況(如當日無成交)欄位會是「--」,前面已轉成 None 並以收盤價補上,
        # 這裡再夾一次確保 OHLC 的大小關係成立
        h = max(h, o, c)
        lo = min(lo, o, c)

        out[code] = [iso, o, h, lo, c, int(shares // 1000)]
    return out
