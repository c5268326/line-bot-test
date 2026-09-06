"""
實測 chengwesley/taiwan-stock-analysis 的抓取層現在還能不能用。

那支 skill 的解析有兩個「壞掉不會報錯」的地方,只有連上去才知道:

  tables[6]        表格位置寫死。版面一變就抓到別張表,或 len(tables)<7 直接
                   回傳空字典 —— 呼叫端拿到的是空資料,不是例外。
  years 偵測       第一列必須含 2020~2025 其中之一才會被認成年度列,
                   寫死的年份清單會隨時間失效。

另外驗 SKILL.md 自己規定的交叉核對:
  現金流量表期末現金 == 資產負債表現金及約當現金

只打 3 個請求,間隔 2 秒。
"""
import re
import sys
import time
import urllib.request

STOCK = sys.argv[1] if len(sys.argv) > 1 else "2317"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def client_key():
    tz = -480
    days = time.time() * 1000 / 86400000 - tz / 1440
    return f"2.8|38057.1435627105|46946.0324515993|{tz}|{days}|{days}", days


def fetch(rpt, days, ck):
    url = (f"https://goodinfo.tw/tw/StockFinDetail.asp?RPT_CAT={rpt}"
           f"&STOCK_ID={STOCK}&REINIT={days:.10f}")
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Referer": "https://goodinfo.tw/", "Cookie": f"CLIENT_KEY={ck}"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", None) or type(e).__name__, ""


def tables(html):
    """粗略切出 <table> 區塊,只為了數數量與看內容,不做完整解析"""
    return re.findall(r"<table[^>]*>.*?</table>", html, re.S | re.I)


def cells(table_html):
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.S | re.I)
    out = []
    for r in rows:
        cs = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S | re.I)
        out.append([re.sub(r"<[^>]+>", "", c).replace("&nbsp;", " ").strip() for c in cs])
    return out


ck, days = client_key()
print(f"=== 實測 Goodinfo 抓取層(股票 {STOCK})===\n", flush=True)

parsed = {}
for rpt, label in (("IS_YEAR", "損益表"), ("BS_YEAR", "資產負債表"), ("CF_YEAR", "現金流量表")):
    status, html = fetch(rpt, days, ck)
    time.sleep(2)
    ts = tables(html) if html else []
    print(f"{label}({rpt}):HTTP {status},HTML {len(html):,} bytes,table {len(ts)} 個", flush=True)

    if not html:
        print("   ✗ 取不到內容\n", flush=True)
        continue
    if len(ts) < 7:
        print(f"   ✗ table 只有 {len(ts)} 個 —— parse_table() 會靜默回傳空字典,"
              "呼叫端拿到空資料而不是例外\n", flush=True)
        continue

    rows = cells(ts[6])
    head = rows[0] if rows else []
    years = [v for v in head[1:] if len(v) == 4 and v.isdigit()]
    hard = [y for y in ("2025", "2024", "2023", "2022", "2021", "2020") if y in head]
    print(f"   tables[6] 第一列:{head[:9]}")
    print(f"   偵測到年度 {years[:8]}")
    print(f"   {'✓' if hard else '✗'} 寫死的年份清單命中 {hard}"
          f"{'' if hard else ' —— 年度列不會被認出,整張表解析失敗'}")

    if years:
        data = {}
        for r in rows[1:]:
            if len(r) >= 3 and r[0] and r[1:] and r[1] not in years:
                stride = max(1, round(len(r[1:]) / len(years)))
                vals = {}
                for j, y in enumerate(years):
                    if j * stride < len(r) - 1:
                        try:
                            vals[y] = float(r[1 + j * stride].replace(",", ""))
                        except ValueError:
                            vals[y] = None
                if vals:
                    data[r[0]] = vals
        print(f"   解析出 {len(data)} 個欄位")
        parsed[rpt] = (data, years)

        want = {"IS_YEAR": "營業收入合計", "BS_YEAR": "現金及約當現金",
                "CF_YEAR": "營業活動之淨現金流入"}[rpt]
        hit = [k for k in data if want[:4] in k]
        print(f"   {'✓' if hit else '✗'} SKILL.md 指名的欄位「{want}」"
              f"{'命中 ' + str(hit[:2]) if hit else '沒找到'}")
        if hit:
            print(f"      {hit[0]} = {data[hit[0]]}")
    print(flush=True)

print("=== SKILL.md 自己規定的交叉核對:期末現金 == 資產負債表現金 ===", flush=True)
if "BS_YEAR" in parsed and "CF_YEAR" in parsed:
    bs, bsy = parsed["BS_YEAR"]
    cf, _ = parsed["CF_YEAR"]
    bs_cash = next((v for k, v in bs.items() if "現金及約當現金" in k), None)
    cf_cash = next((v for k, v in cf.items() if "期末" in k and "現金" in k), None)
    if bs_cash and cf_cash:
        for y in bsy[:3]:
            a, b = bs_cash.get(y), cf_cash.get(y)
            if a is None or b is None:
                print(f"  {y}: 缺值 BS={a} CF={b}")
            else:
                d = abs(a - b)
                print(f"  {y}: BS={a:,.1f}  CF={b:,.1f}  差 {d:,.1f} "
                      f"{'✓ 一致' if d < max(1, abs(a) * 0.01) else '✗ 不一致 → 年度可能錯位'}")
    else:
        print(f"  無法核對(BS 現金 {'有' if bs_cash else '無'}、"
              f"CF 期末現金 {'有' if cf_cash else '無'})")
else:
    print("  兩張表沒有都解析成功,無法核對")
