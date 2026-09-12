"""
抓籌碼面資料:三大法人買賣超、外資買賣超、融資融券餘額、本益比/淨值比/殖利率。

省配額的原則
------------
能走「全市場一次給完」的端點就不要走 FinMind。
證交所與櫃買的日報每天各 1 個 request 就涵蓋全部個股;
FinMind 是一檔一個 request、配額以小時計 —— 674 檔要跑好幾輪。
所以這裡只有月營收走 FinMind(證交所沒有對應的全市場端點)。

欄位一律用名稱查,不用索引
--------------------------
證交所改版時會插欄位。寫死 row[5] 的程式那天就會安靜地讀到錯的數字,
而且不會報錯 —— 那比直接壞掉更糟。

融資餘額要交叉驗證
------------------
MI_MARGN 的回應裡有好幾張表,欄位名稱相近(前日餘額/資餘額/限額…)。
挑錯欄位一樣不會報錯,只會給出錯的數字。所以抓完先拿一檔去對
FinMind 的同日數值,對不上就不要寫檔。

    python research/fetch_chips.py
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "docs", "data", "chips.json")

UA = "Mozilla/5.0 (compatible; stock-research/1.0)"
TIMEOUT = 30
PACE = float(os.environ.get("TWSE_PACE", "1.2"))
DAYS = int(os.environ.get("CHIP_DAYS", "30"))

FINMIND = "https://api.finmindtrade.com/api/v4/data"

# MI_MARGN 曾經在 /margin/ 底下,現在不是。與其猜一條寫死,
# 不如依序試、取第一個回得出 JSON 的 —— 下次證交所再搬家也還能活。
MARGIN_PATHS = ["afterTrading/MI_MARGN", "marginTrading/MI_MARGN", "margin/MI_MARGN"]


class QuotaExhausted(Exception):
    """FinMind 回 402/429:配額用盡。這和『查無資料』完全不同。"""


def get(url, quiet=False):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json, text/plain, */*"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code in (402, 429):
            raise QuotaExhausted(f"HTTP {e.code}")
        if not quiet:
            print(f"    ✗ HTTP {e.code} {url[:90]}")
    except Exception as e:
        if not quiet:
            print(f"    ✗ {type(e).__name__} {url[:90]}")
    return None


def as_json(raw):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None      # 證交所查無資料時會回 HTML 404 頁


def num(s):
    """'1,234' → 1234;'--'、'-'、'' → None。不要把破折號當成 0。"""
    if s is None:
        return None
    t = str(s).strip().replace(",", "").replace("+", "")
    if t in ("", "-", "--", "---", "N/A"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def by_name(fields, data):
    """把 [欄位名] + [列] 轉成 [{欄位名: 值}]。重複欄位名加序號區隔。"""
    names, seen = [], defaultdict(int)
    for f in fields:
        f = (f or "").strip()
        seen[f] += 1
        names.append(f if seen[f] == 1 else f"{f}#{seen[f]}")
    return [dict(zip(names, row)) for row in data]


def pick(row, *candidates):
    """依序找第一個存在的欄位名。找不到回 None —— 不要猜索引。"""
    for c in candidates:
        if c in row:
            return num(row[c])
    return None


# =====================================================================
# 證交所(上市)
# =====================================================================
def twse_inst(day):
    """三大法人買賣超日報。回傳 {代號: {foreign, trust, dealer, total}},單位:股"""
    j = as_json(get(f"https://www.twse.com.tw/rwd/zh/fund/T86"
                    f"?date={day}&selectType=ALL&response=json"))
    if not j or j.get("stat") != "OK":
        return {}
    out = {}
    for r in by_name(j.get("fields") or [], j.get("data") or []):
        sid = (r.get("證券代號") or "").strip()
        if not sid:
            continue
        out[sid] = {
            "foreign": pick(r, "外陸資買賣超股數(不含外資自營商)", "外資買賣超股數"),
            "trust": pick(r, "投信買賣超股數"),
            "dealer": pick(r, "自營商買賣超股數"),
            "total": pick(r, "三大法人買賣超股數"),
        }
    return out


def twse_margin(day, path_hint=None):
    """
    融資融券餘額。回傳 {代號: {margin, margin_prev, short, short_prev}},單位:張。

    MI_MARGN 的回應可能是 fields/data,也可能是 tables —— 兩種都處理,
    並且只認「有代號欄位」的那張表。
    """
    paths = ([path_hint] if path_hint else []) + MARGIN_PATHS
    for p in paths:
        j = as_json(get(f"https://www.twse.com.tw/rwd/zh/{p}"
                        f"?date={day}&selectType=ALL&response=json", quiet=True))
        if not j:
            continue
        blocks = []
        if j.get("fields") and j.get("data"):
            blocks.append((j["fields"], j["data"]))
        for t in (j.get("tables") or []):
            if t.get("fields") and t.get("data"):
                blocks.append((t["fields"], t["data"]))
        for fields, data in blocks:
            rows = by_name(fields, data)
            if not rows or not any(k in rows[0] for k in ("代號", "證券代號", "股票代號")):
                continue
            out = {}
            for r in rows:
                sid = (r.get("代號") or r.get("證券代號") or r.get("股票代號") or "").strip()
                if not sid:
                    continue
                out[sid] = {
                    "margin": pick(r, "融資今日餘額", "資餘額", "今日餘額"),
                    "margin_prev": pick(r, "融資前日餘額", "前資餘額(張)", "前日餘額"),
                    "short": pick(r, "融券今日餘額", "券餘額"),
                    "short_prev": pick(r, "融券前日餘額", "前券餘額(張)"),
                }
            if out and any(v["margin"] is not None for v in out.values()):
                return out, p
    return {}, None


def twse_value(day):
    """本益比、殖利率、股價淨值比。"""
    j = as_json(get(f"https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d"
                    f"?date={day}&selectType=ALL&response=json"))
    if not j or j.get("stat") != "OK":
        return {}
    out = {}
    for r in by_name(j.get("fields") or [], j.get("data") or []):
        sid = (r.get("證券代號") or "").strip()
        if not sid:
            continue
        out[sid] = {"per": pick(r, "本益比"), "pbr": pick(r, "股價淨值比"),
                    "yield": pick(r, "殖利率(%)", "殖利率")}
    return out


# =====================================================================
# 櫃買(上櫃)
# =====================================================================
def tpex_table(url, want):
    j = as_json(get(url))
    if not j or j.get("stat") not in ("ok", "OK"):
        return None
    for t in (j.get("tables") or []):
        if t.get("fields") and t.get("data") and want in (t.get("title") or ""):
            return by_name(t["fields"], t["data"])
    return None


def tpex_inst(day):
    rows = tpex_table(f"https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade"
                      f"?type=Daily&sect=EW&date={day}&response=json", "三大法人")
    out = {}
    for r in rows or []:
        sid = (r.get("代號") or "").strip()
        if sid:
            out[sid] = {"foreign": None, "trust": None, "dealer": None,
                        "total": pick(r, "三大法人買賣超股數合計")}
    return out


def tpex_margin(day):
    rows = tpex_table(f"https://www.tpex.org.tw/www/zh-tw/margin/balance"
                      f"?date={day}&response=json", "融資融券")
    out = {}
    for r in rows or []:
        sid = (r.get("代號") or "").strip()
        if sid:
            out[sid] = {"margin": pick(r, "資餘額"), "margin_prev": pick(r, "前資餘額(張)"),
                        "short": pick(r, "券餘額"), "short_prev": pick(r, "前券餘額(張)")}
    return out


# =====================================================================
def trading_days(n):
    """從 docs/data/stocks.json 借用交易日清單 —— 不必自己算休市日。"""
    path = os.path.join(ROOT, "docs", "data", "stocks.json")
    d = json.load(open(path, encoding="utf-8"))
    return d["dates"][-n:]


def verify_margin(chips, day):
    """
    拿一檔去對 FinMind 的同日融資餘額。欄位挑錯不會報錯,只會給出錯的數字,
    所以寧可多花一個 request 確認。對不上就讓呼叫端決定要不要寫檔。
    """
    sid = "2409"
    mine = (chips.get(sid, {}).get("margin") or {}).get(day)
    if mine is None:
        return None, "樣本個股當日沒有融資資料,無法驗證"
    try:
        raw = get(f"{FINMIND}?dataset=TaiwanStockMarginPurchaseShortSale"
                  f"&data_id={sid}&start_date={day}&end_date={day}")
    except QuotaExhausted:
        return None, "FinMind 配額用盡,這一輪沒驗證到"
    j = as_json(raw)
    rows = (j or {}).get("data") or []
    if not rows:
        return None, "FinMind 查無同日資料,這一輪沒驗證到"
    theirs = rows[0].get("MarginPurchaseTodayBalance")
    if theirs is None:
        return None, "FinMind 沒有該欄位"
    ok = abs(mine - theirs) <= max(1.0, theirs * 0.001)
    return ok, f"證交所 {mine:,.0f} 張 vs FinMind {theirs:,.0f} 張"


def main():
    days = trading_days(DAYS)
    print(f"抓籌碼資料:{days[0]} ~ {days[-1]},共 {len(days)} 個交易日", flush=True)
    print("  來源:證交所 T86 / MI_MARGN / BWIBBU_d、櫃買 dailyTrade / margin"
          "(皆為全市場日報,每天各 1 個 request)\n", flush=True)

    chips = defaultdict(lambda: defaultdict(dict))
    margin_path = None
    hit = defaultdict(int)

    for d in days:
        dn = d.replace("-", "")
        inst = twse_inst(dn); time.sleep(PACE)
        marg, p = twse_margin(dn, margin_path); time.sleep(PACE)
        if p:
            margin_path = p
        val = twse_value(dn); time.sleep(PACE)
        inst.update(tpex_inst(d)); time.sleep(PACE)
        marg.update(tpex_margin(d)); time.sleep(PACE)

        for sid, v in inst.items():
            chips[sid]["inst"][d] = v
        for sid, v in marg.items():
            chips[sid]["margin"][d] = v.get("margin")
            chips[sid]["short"][d] = v.get("short")
        for sid, v in val.items():
            chips[sid]["value"][d] = v
        hit["inst"] += len(inst); hit["margin"] += len(marg); hit["value"] += len(val)
        print(f"  {d}  法人 {len(inst):>5}  融資 {len(marg):>5}  評價 {len(val):>5}",
              flush=True)

    print(f"\n融資融券端點:{margin_path or '找不到'}", flush=True)
    ok, detail = verify_margin(chips, days[-1])
    print(f"融資餘額交叉驗證:{'✓ 相符' if ok else '✗ 不符' if ok is False else '⚠ 未驗證'}"
          f"  {detail}", flush=True)
    if ok is False:
        print("\n欄位對不上,不寫檔 —— 寧可沒有資料,也不要寫進錯的數字。", flush=True)
        return 1

    # 只留檢測站裡有的個股,檔案才不會被 1,300 檔 ETF 灌爆
    universe = {s["id"] for s in json.load(
        open(os.path.join(ROOT, "docs", "data", "stocks.json"), encoding="utf-8"))["stocks"]}
    out = {"updated_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
           "source": "TWSE T86/MI_MARGN/BWIBBU_d + TPEx dailyTrade/margin",
           "margin_endpoint": margin_path,
           "margin_verified": ok, "margin_verify_detail": detail,
           "dates": days, "stocks": {}}
    for sid in sorted(universe & set(chips)):
        c = chips[sid]
        out["stocks"][sid] = {
            "inst": {d: v for d, v in c["inst"].items()},
            "margin": {d: v for d, v in c["margin"].items() if v is not None},
            "short": {d: v for d, v in c["short"].items() if v is not None},
            "value": {d: v for d, v in c["value"].items()},
        }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    size = os.path.getsize(OUT) / 1024
    print(f"\n已寫入 {OUT}({size:,.0f} KB,{len(out['stocks'])} 檔)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
