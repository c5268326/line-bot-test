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
import ssl
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
# 證交所會對短時間內的密集請求回 307 轉址。一輪 150 個請求,
# 間隔拉長比重跑便宜。
PACE = float(os.environ.get("TWSE_PACE", "2.5"))
DAYS = int(os.environ.get("CHIP_DAYS", "30"))

FINMIND = "https://api.finmindtrade.com/api/v4/data"

# MI_MARGN 曾經在 /margin/ 底下,現在不是。與其猜一條寫死,
# 不如依序試、取第一個回得出 JSON 的 —— 下次證交所再搬家也還能活。
MARGIN_PATHS = ["afterTrading/MI_MARGN", "marginTrading/MI_MARGN", "margin/MI_MARGN"]


class QuotaExhausted(Exception):
    """FinMind 回 402/429:配額用盡。這和『查無資料』完全不同。"""


class FetchFailed(Exception):
    """請求失敗。和『查無資料』完全不同 —— 混為一談會讓整條資料源靜靜地死掉。"""


# 櫃買的伺服器沒有送出中介憑證,客戶端湊不出信任鏈。
# 實測 certifi 的 bundle 也救不了:缺的是「伺服器沒送的那一張」,
# 不是「我這邊信任庫不夠完整」—— 再換憑證庫都一樣。
# 絕不關掉驗證,那是把一個資料問題換成一個安全問題。
# 目前的作法是讓上櫃個股走 FinMind 後援(見下方 main)。
def _ssl_ctx():
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(cafile=certifi.where())
    except Exception:
        pass
    return ctx


_CTX = _ssl_ctx()
FAILURES = []          # (網址, 原因),最後一次講清楚


def get(url, quiet=False):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json, text/plain, */*"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_CTX) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code in (402, 429):
            raise QuotaExhausted(f"HTTP {e.code}")
        FAILURES.append((url, f"HTTP {e.code}"))
        if not quiet:
            print(f"    ✗ HTTP {e.code} {url[:90]}")
        raise FetchFailed(f"HTTP {e.code}")
    except FetchFailed:
        raise
    except Exception as e:
        FAILURES.append((url, f"{type(e).__name__}: {e}"))
        if not quiet:
            print(f"    ✗ {type(e).__name__} {url[:90]}")
        raise FetchFailed(str(e))


def as_json(raw):
    """回 None 只代表『這個回應不是 JSON』(證交所查無資料時會回 HTML 404 頁)。
    請求失敗是 FetchFailed,由呼叫端另外處理,兩者不要混在同一個 None 裡。"""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


FAILED = object()      # 「請求失敗」的哨符,和「查無資料」的 None 分開


def try_json(url, quiet=False):
    """請求失敗回 FAILED,查無資料回 None,成功回解析後的物件。"""
    try:
        return as_json(get(url, quiet=quiet))
    except FetchFailed:
        return FAILED


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
    j = try_json(f"https://www.twse.com.tw/rwd/zh/fund/T86"
                 f"?date={day}&selectType=ALL&response=json")
    if j is FAILED:
        return FAILED
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
        j = try_json(f"https://www.twse.com.tw/rwd/zh/{p}"
                     f"?date={day}&selectType=ALL&response=json", quiet=True)
        if j is FAILED or not j:
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
    j = try_json(f"https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d"
                 f"?date={day}&selectType=ALL&response=json")
    if j is FAILED:
        return FAILED
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
    """回 FAILED 代表連不上;回 None 代表連上了但沒有這張表。"""
    j = try_json(url)
    if j is FAILED:
        return FAILED
    if not j or j.get("stat") not in ("ok", "OK"):
        return None
    for t in (j.get("tables") or []):
        if t.get("fields") and t.get("data") and want in (t.get("title") or ""):
            return by_name(t["fields"], t["data"])
    return None


def tpex_inst(day):
    rows = tpex_table(f"https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade"
                      f"?type=Daily&sect=EW&date={day}&response=json", "三大法人")
    if rows is FAILED:
        return FAILED
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
    if rows is FAILED:
        return FAILED
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
    except FetchFailed as e:
        return None, f"FinMind 連不上({e}),這一輪沒驗證到"
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

    tpex_dead = twse_dead = 0
    for d in days:
        dn = d.replace("-", "")
        inst = twse_inst(dn); time.sleep(PACE)
        marg, p = twse_margin(dn, margin_path); time.sleep(PACE)
        if p:
            margin_path = p
        val = twse_value(dn); time.sleep(PACE)
        ti = tpex_inst(d); time.sleep(PACE)
        tm = tpex_margin(d); time.sleep(PACE)

        # 上櫃與上市要分開數。先前把兩邊合併後只印一個總數,
        # 櫃買整整 30 天都連不上(SSL 憑證鏈不完整)也看不出來 ——
        # 上市的一千多檔把那個 0 蓋掉了。
        # 證交所那三個也可能失敗(例如被 307 擋掉),失敗時是 FAILED 哨符,
        # 不是 dict。先前直接對它呼叫 .update() 就炸了 ——
        # 我把「分辨失敗」做對了,卻忘了在使用端把哨符換回空 dict。
        if inst is FAILED:
            twse_dead += 1
            inst = {}
        if marg is FAILED:
            marg = {}
        if val is FAILED:
            val = {}

        n_tpex = 0
        if ti is FAILED or tm is FAILED:
            tpex_dead += 1
        else:
            inst.update(ti); marg.update(tm)
            n_tpex = len(ti)

        for sid, v in inst.items():
            chips[sid]["inst"][d] = v
        for sid, v in marg.items():
            chips[sid]["margin"][d] = v.get("margin")
            chips[sid]["short"][d] = v.get("short")
        for sid, v in val.items():
            chips[sid]["value"][d] = v
        print(f"  {d}  上市法人 {len(inst) - n_tpex:>5}  上櫃法人 "
              f"{'連不上' if ti is FAILED else n_tpex:>5}"
              f"  融資 {len(marg):>5}  評價 {len(val):>5}", flush=True)

    if tpex_dead:
        print(f"\n⚠ 櫃買日報有 {tpex_dead}/{len(days)} 天連不上", flush=True)
    if twse_dead:
        print(f"\n⚠ 證交所有 {twse_dead}/{len(days)} 天連不上", flush=True)
        # 證交所會用 307 轉址擋掉短時間內的密集請求。這種時候硬寫檔會用
        # 半套資料蓋掉上一輪完整的結果 —— 那比不更新還糟。
        if twse_dead > len(days) * 0.2:
            print("  超過兩成,判定為被限流,不寫檔。"
                  "請隔一段時間再跑,或調高 TWSE_PACE。", flush=True)
            return 1

    # 後援:補「實際上缺的」,不是補「哪個來源掛掉」。
    #
    # 先前寫成 if tpex_dead 才啟動,結果櫃買恢復之後後援就不跑了,
    # 上櫃個股的本益比又變成 0 天 —— 因為證交所的 BWIBBU_d 只涵蓋上市,
    # 而櫃買那邊我沒有對應的估值端點。條件掛在「誰失敗」上,
    # 就會漏掉「沒有人負責」的那一塊。改成看每一檔到底缺什麼。
    universe_ids = [s_["id"] for s_ in json.load(
        open(os.path.join(ROOT, "docs", "data", "stocks.json"), encoding="utf-8"))["stocks"]]
    # chips 是 defaultdict:用 chips[i] 檢查會把 674 檔全部建成空紀錄,
    # 於是頁面看到「有這檔但每欄都空」,會畫出一整排破折號,
    # 而不是「這檔沒有籌碼資料」那句說明。用 .get 讀,不要碰到就生。
    def lacks(sid, field):
        return not (chips.get(sid, {}) or {}).get(field)

    need_inst = [i for i in universe_ids if lacks(i, "inst")]
    need_marg = [i for i in universe_ids if lacks(i, "margin")]
    need_val = [i for i in universe_ids if lacks(i, "value")]
    todo = sorted(set(need_inst) | set(need_marg) | set(need_val))
    if todo:
        print(f"\n後援(FinMind 逐檔):法人缺 {len(need_inst)} 檔、"
              f"融資缺 {len(need_marg)} 檔、評價缺 {len(need_val)} 檔"
              f",共 {len(todo)} 檔要補", flush=True)
        if len(todo) > 40:
            # 檔數一多就不是「補缺」而是「整批重抓」,那會打爆配額。
            # 寧可少補一些並講清楚,也不要跑到一半被擋然後留下半套資料。
            print(f"  ⚠ 超過 40 檔,只補前 40 檔,其餘下一輪再補", flush=True)
            todo = todo[:40]
        for sid in todo:
            rows = []
            if sid in need_inst:
                try:
                    j = as_json(get(f"{FINMIND}?dataset=TaiwanStockInstitutionalInvestorsBuySell"
                                    f"&data_id={sid}&start_date={days[0]}&end_date={days[-1]}"))
                    rows = (j or {}).get("data") or []
                except QuotaExhausted:
                    print("  FinMind 配額用盡,後援中止", flush=True)
                    break
                except FetchFailed:
                    print(f"  {sid} FinMind 法人連不上", flush=True)
            # FinMind 是每個法人別一列,要自己合併成當日淨額
            per_day = defaultdict(lambda: {"foreign": 0.0, "trust": 0.0,
                                           "dealer": 0.0, "total": 0.0})
            KEY = {"Foreign_Investor": "foreign", "Investment_Trust": "trust",
                   "Dealer_self": "dealer", "Dealer_Hedging": "dealer",
                   "Foreign_Dealer_Self": "foreign"}
            for r in rows:
                k = KEY.get(r.get("name"))
                if not k:
                    continue
                net = (r.get("buy") or 0) - (r.get("sell") or 0)
                per_day[r["date"]][k] += net
                per_day[r["date"]]["total"] += net
            for dd, v in per_day.items():
                chips[sid]["inst"][dd] = v
            time.sleep(2)

            # 法人補完還不夠:融資餘額與本益比也要補,否則這幾檔的面板
            # 會少兩塊,而使用者看不出是「這檔沒有」還是「我沒抓到」。
            n_m = n_v = 0
            try:
                if sid not in need_marg:
                    raise StopIteration
                j = as_json(get(f"{FINMIND}?dataset=TaiwanStockMarginPurchaseShortSale"
                                f"&data_id={sid}&start_date={days[0]}&end_date={days[-1]}"))
                for r in (j or {}).get("data") or []:
                    chips[sid]["margin"][r["date"]] = num(r.get("MarginPurchaseTodayBalance"))
                    chips[sid]["short"][r["date"]] = num(r.get("ShortSaleTodayBalance"))
                    n_m += 1
                time.sleep(2)
            except StopIteration:
                pass
            except (QuotaExhausted, FetchFailed) as e:
                print(f"  {sid} 融資補不到:{e}", flush=True)
            try:
                if sid not in need_val:
                    raise StopIteration
                j = as_json(get(f"{FINMIND}?dataset=TaiwanStockPER"
                                f"&data_id={sid}&start_date={days[0]}&end_date={days[-1]}"))
                for r in (j or {}).get("data") or []:
                    chips[sid]["value"][r["date"]] = {
                        "per": num(r.get("PER")), "pbr": num(r.get("PBR")),
                        "yield": num(r.get("dividend_yield"))}
                    n_v += 1
                time.sleep(2)
            except StopIteration:
                pass
            except (QuotaExhausted, FetchFailed) as e:
                print(f"  {sid} 評價補不到:{e}", flush=True)
            print(f"  {sid} FinMind 補上 法人 {len(per_day)} 天、"
                  f"融資 {n_m} 天、評價 {n_v} 天", flush=True)

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

    if FAILURES:
        kinds = defaultdict(int)
        for _, why in FAILURES:
            kinds[why.split(":")[0]] += 1
        print(f"\n⚠ 這一輪有 {len(FAILURES)} 個請求失敗:", flush=True)
        for k, n in sorted(kinds.items(), key=lambda x: -x[1]):
            print(f"    {n:>4}  {k}", flush=True)
        print(f"    例:{FAILURES[0][1][:120]}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
