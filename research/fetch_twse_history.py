"""
抓取證交所全市場歷史日資料,建立「逐日 point-in-time 股票池」。

要解決的問題
------------
先前的回測用「今天」的成交金額前 120 名回頭選股,等於預先知道誰活下來
且變大。結果是等權對照組年化 25%,而台股同期實際約 10~13% —— 那個落差
全部是倖存者偏誤。

這支程式改抓每一個交易日的全市場快照,於是每個換股日看到的都是「當天
實際掛牌且有成交」的股票,已下市的公司在它還存在的期間也會出現在池子裡。

資料來源(公開、免金鑰,無硬性配額)
  MI_INDEX?date=&type=ALLBUT0999  每日收盤行情,一次拿當日全市場
  BWIBBU_d?date=                  個股本益比/殖利率/股價淨值比

用法(以年份分段,避免單一 workflow 跑太久;已抓過的年份會自動略過)
    YEARS=2015,2016 python research/fetch_twse_history.py

產出
    research/data/pit/price_<year>.csv.gz    當日成交金額前 N 名
    research/data/pit/val_<year>.csv.gz      換股日的估值資料
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
PACE = float(os.environ.get("TWSE_PACE", "2.0"))     # 對公開服務的禮貌間隔
TOP_N = int(os.environ.get("PIT_TOP_N", "400"))      # 每日保留成交金額前 N 名
START_YEAR, END_YEAR = 2014, date.today().year

MI_INDEX = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={d}&type=ALLBUT0999&response=json"
BWIBBU = "https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?date={d}&response=json"


def get_json(url, tries=3):
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Accept": "application/json, */*"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            wait = 5 * (attempt + 1)
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


def weekdays(year):
    d = date(year, 1, 1)
    end = min(date(year, 12, 31), date.today())
    while d <= end:
        if d.weekday() < 5:          # 假日與颱風停市由 API 回傳「無資料」自然過濾
            yield d
        d += timedelta(days=1)


def parse_mi_index(j):
    """從 MI_INDEX 取出『每日收盤行情』那張表,回傳 [(代號, 開,高,低,收, 量張, 成交金額)]"""
    if not j or j.get("stat") != "OK":
        return []
    table = None
    for t in j.get("tables", []):
        f = t.get("fields") or []
        if "證券代號" in f and "收盤價" in f and "成交金額" in f:
            table = t
            break
    if not table:
        return []

    idx = {name: i for i, name in enumerate(table["fields"])}
    out = []
    for row in table.get("data", []):
        code = str(row[idx["證券代號"]]).strip().strip('"')
        if not (len(code) == 4 and code.isdigit()):     # 只要普通股
            continue
        c = num(row[idx["收盤價"]])
        if not c or c <= 0:
            continue
        o = num(row[idx["開盤價"]]) or c
        h = num(row[idx["最高價"]]) or c
        lo = num(row[idx["最低價"]]) or c
        shares = num(row[idx["成交股數"]]) or 0
        money = num(row[idx["成交金額"]]) or 0
        h = max(h, o, c)
        lo = min(lo, o, c)
        out.append((code, o, h, lo, c, int(shares // 1000), money))
    return out


def parse_bwibbu(j):
    """
    回傳 [(代號, PER, 殖利率, PBR)]。
    欄位結構在這十年間改過(2015 是 5 欄、2024 是 8 欄),
    所以一律依欄名對應,不能用位置。
    """
    if not j or j.get("stat") != "OK":
        return []
    fields = j.get("fields") or []
    idx = {name: i for i, name in enumerate(fields)}
    need = ("證券代號", "本益比", "殖利率(%)", "股價淨值比")
    if not all(k in idx for k in need):
        return []

    out = []
    for row in j.get("data", []):
        code = str(row[idx["證券代號"]]).strip().strip('"')
        if not (len(code) == 4 and code.isdigit()):
            continue
        per, yld, pbr = (num(row[idx["本益比"]]), num(row[idx["殖利率(%)"]]), num(row[idx["股價淨值比"]]))
        # 0 代表沒有資料(例如虧損公司沒有本益比),不是真的等於零
        out.append((code, per or None, yld, pbr or None))
    return out


def is_rebalance_day(d, seen_quarters):
    q = (d.year, (d.month - 1) // 3)
    if q in seen_quarters:
        return False
    seen_quarters.add(q)
    return True


def fetch_year(year):
    price_path = os.path.join(OUT_DIR, f"price_{year}.csv.gz")
    val_path = os.path.join(OUT_DIR, f"val_{year}.csv.gz")
    if os.path.exists(price_path) and os.path.getsize(price_path) > 10_000:
        print(f"=== {year} 已存在,略過 ===", flush=True)
        return

    print(f"\n=== {year} ===", flush=True)
    seen_q, trading_days, price_rows, val_rows = set(), 0, 0, 0

    with gzip.open(price_path, "wt", encoding="utf-8", newline="") as pf, \
         gzip.open(val_path, "wt", encoding="utf-8", newline="") as vf:
        pw, vw = csv.writer(pf), csv.writer(vf)
        pw.writerow(["date", "stock_id", "open", "high", "low", "close", "volume", "turnover"])
        vw.writerow(["date", "stock_id", "per", "yield", "pbr"])

        for d in weekdays(year):
            ds = d.strftime("%Y%m%d")
            iso = d.isoformat()

            rows = parse_mi_index(get_json(MI_INDEX.format(d=ds)))
            time.sleep(PACE)
            if not rows:
                continue                       # 非交易日
            trading_days += 1

            # 每日只留成交金額前 N 名 —— 這就是當天的 point-in-time 池子,
            # 同時把檔案控制在合理大小
            rows.sort(key=lambda r: r[6], reverse=True)
            for code, o, h, lo, c, vol, money in rows[:TOP_N]:
                pw.writerow([iso, code, o, h, lo, c, vol, int(money)])
                price_rows += 1

            # 估值只在每季第一個交易日抓,回測是每季換股,不需要每天
            if is_rebalance_day(d, seen_q):
                for code, per, yld, pbr in parse_bwibbu(get_json(BWIBBU.format(d=ds))):
                    vw.writerow([iso, code, per, yld, pbr])
                    val_rows += 1
                time.sleep(PACE)
                print(f"  {iso} 換股日:估值 {val_rows} 筆(累計)", flush=True)

            if trading_days % 40 == 0:
                print(f"  {iso}  交易日 {trading_days},價格 {price_rows:,} 筆", flush=True)

    print(f"  {year} 完成:{trading_days} 個交易日,價格 {price_rows:,} 筆,估值 {val_rows:,} 筆,"
          f"{os.path.getsize(price_path)/1024/1024:.1f} MB", flush=True)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    raw = os.environ.get("YEARS", "").strip()
    years = ([int(y) for y in raw.split(",") if y.strip()]
             if raw else list(range(START_YEAR, END_YEAR + 1)))
    print(f"預定抓取年份:{years}(每日保留前 {TOP_N} 名,間隔 {PACE}s)", flush=True)
    for y in years:
        fetch_year(y)
    print("\n全部完成", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
