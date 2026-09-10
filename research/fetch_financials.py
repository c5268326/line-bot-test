"""
用 FinMind 抓三張財報,產出個股基本面資料給網頁用。

為什麼不用 Goodinfo
------------------
chengwesley/taiwan-stock-analysis 那支 skill 從 Goodinfo 抓三表,設計得不錯,
但實測 Goodinfo 對 GitHub Actions 的 IP 回 403(連首頁都擋),所以進不了
這個 repo 的自動化管線。FinMind 的三張報表已驗證可用且科目齊全,改用它。

沿用那支 skill 值得留下的設計:資料血緣標注、合理性檢查、附 MOPS 原始
申報連結讓人自己核對。

一個必須先驗證的前提
------------------
FinMind 的財報是「單季」還是「累計」?這決定所有比率的分母。猜錯不會報錯,
只會讓毛利率之類的數字整片偏掉。用月營收交叉驗:12 個月加總應等於年營收,
拿它去比對四個季度的加總,就知道是哪一種。

產出 docs/data/financials.json
"""
import json
import os
import sys
import time
import urllib.request
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEST = os.path.join(ROOT, "docs", "data", "financials.json")
STOCKS = os.path.join(ROOT, "docs", "data", "stocks.json")

FINMIND = "https://api.finmindtrade.com/api/v4/data"
UA = "Mozilla/5.0 (compatible; tw-backtest-research/1.0)"
PACE = float(os.environ.get("FINMIND_PACE", "1.8"))
YEARS_BACK = 4                      # 多抓一年,才算得出最舊那年的年增率
LIMIT = int(os.environ.get("LIMIT", "0"))   # 0 = 全部


class QuotaExhausted(Exception):
    """FinMind 回 402/429:配額用盡。這和『查無資料』完全不同,不能混為一談。"""


def get(url, tries=4, timeout=35):
    """回傳 JSON;配額用盡時拋 QuotaExhausted,其他失敗回 None。

    先前這裡把兩種情況都回 None,呼叫端一律當成「無財報」——
    於是配額用盡的最後十檔被記成「這些公司沒有財報」,那是假的。
    """
    quota = False
    for i in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except Exception as e:
            code = getattr(e, "code", None)
            quota = quota or code in (402, 429)
            wait = (8 if code in (402, 429) else 4) * (i + 1)
            print(f"      {code or type(e).__name__},{wait}s 後重試", flush=True)
            time.sleep(wait)
    if quota:
        raise QuotaExhausted(url)
    return None


def fm(dataset, sid, start, end):
    """配額用盡會往上拋,不會被誤當成空資料"""
    j = get(f"{FINMIND}?dataset={dataset}&data_id={sid}&start_date={start}&end_date={end}")
    time.sleep(PACE)
    if not j or j.get("status") != 200:
        return []
    return j.get("data") or []


def by_date(rows, wanted):
    """長格式 → {date: {科目: 值}},只留需要的科目"""
    out = defaultdict(dict)
    for r in rows:
        t = r.get("type")
        if t in wanted:
            try:
                out[r["date"]][t] = float(r["value"])
            except (TypeError, ValueError, KeyError):
                pass
    return out


IS_FIELDS = {"Revenue", "GrossProfit", "OperatingExpenses", "OperatingIncome",
             "IncomeAfterTaxes", "EPS", "PreTaxIncome", "CostOfGoodsSold"}
BS_FIELDS = {"CashAndCashEquivalents", "Inventories", "AccountsReceivableNet",
             "CurrentAssets", "CurrentLiabilities", "Liabilities", "Equity", "TotalAssets"}
CF_FIELDS = {"NetCashInflowFromOperatingActivities", "CashProvidedByInvestingActivities",
             "CashFlowsProvidedFromFinancingActivities", "PropertyAndPlantAndEquipment",
             "CashBalancesEndOfPeriod", "Depreciation"}
# 期末現金雖然列在現金流量表裡,但它是「某一天的餘額」,不是期間流量。
# 四季相加會得到四倍的假數字 —— 這正是交叉核對抓到的那 215 筆警示。
LEVEL_IN_CF = {"CashBalancesEndOfPeriod", "CashBalancesBeginningOfPeriod"}

# 產出格式版本。改動衍生邏輯時要一併加一,續抓才不會沿用舊格式算出來的值。
SCHEMA = 4


def detect_basis(sid, year):
    """
    判斷財報是單季還是累計。
    月營收 12 個月加總 = 年營收,拿它比對四季加總即可判別 —— 不靠任何寫死的數字。
    """
    mr = fm("TaiwanStockMonthRevenue", sid, f"{year}-01-01", f"{year + 1}-06-30")
    annual = sum(float(r["revenue"]) for r in mr
                 if str(r.get("revenue_year")) == str(year) and r.get("revenue") is not None)
    if not annual:
        return None, "月營收取不到,無法判別"

    fs = by_date(fm("TaiwanStockFinancialStatements", sid, f"{year}-01-01", f"{year}-12-31"),
                 {"Revenue"})
    qs = sorted(fs)
    revs = [fs[d].get("Revenue") for d in qs if fs[d].get("Revenue")]
    if len(revs) < 4:
        return None, f"{year} 只有 {len(revs)} 季,無法判別"

    total, last = sum(revs), revs[-1]
    d_sum, d_last = abs(total - annual) / annual, abs(last - annual) / annual
    print(f"  月營收年度合計 {annual:,.0f}", flush=True)
    print(f"  四季加總       {total:,.0f}  (差 {d_sum * 100:5.1f}%)", flush=True)
    print(f"  第四季單值     {last:,.0f}  (差 {d_last * 100:5.1f}%)", flush=True)
    if d_sum < 0.03:
        return "quarterly", "四季加總吻合年營收 → 單季值,年度數字要自行加總"
    if d_last < 0.03:
        return "cumulative", "第四季即等於年營收 → 累計值,年度數字直接取 Q4"
    return None, f"兩種都對不上(加總差 {d_sum:.1%}、Q4 差 {d_last:.1%})"


def annualize(per_date, basis, flow_fields):
    """
    把季資料整理成 {年: {科目: 年度值}}。

    存量(資產負債表科目、現金流量表裡的期末/期初現金)取年末那一季;
    流量(營收、獲利、營業現金流)在單季基準下要四季齊全才加總。

    當年度通常只有一兩季,流量算不出來 —— 這種年度整年不輸出,
    否則它會佔掉三年視窗的一格,把一個完整的舊年度擠掉。
    """
    out = {}
    for y in sorted({d[:4] for d in per_date}):
        qs = sorted(d for d in per_date if d.startswith(y))
        if not qs:
            continue
        keys = set()
        for d in qs:
            keys |= set(per_date[d])
        is_flow = lambda k: k in flow_fields and k not in LEVEL_IN_CF
        if basis != "cumulative" and len(qs) != 4 and any(is_flow(k) for k in keys):
            continue                                   # 不完整的年度,整年不要
        vals = {}
        for k in keys:
            series = [per_date[d][k] for d in qs if k in per_date[d]]
            if not series:
                continue
            vals[k] = sum(series) if (is_flow(k) and basis != "cumulative") else series[-1]
        if vals:
            out[y] = vals
    return out


def ratios(is_y, bs_y, cf_y):
    """
    由三表算出比率。缺項就留 None,不用別的數字硬湊。

    只走損益表有的年度。annualize() 的守門是逐張報表判斷的,而資產負債表
    沒有任何流量欄位,不完整的當年度會從那裡漏過來 —— 用聯集就會把它撿回,
    產生一個只有現金與負債比率的空殼年度,還佔掉三年視窗一格。
    年報要成立的前提是那一年有營收,所以以損益表為準。
    """
    out = {}
    for y in sorted(is_y):
        i, b, c = is_y.get(y, {}), bs_y.get(y, {}), cf_y.get(y, {})
        rev, eq, ta = i.get("Revenue"), b.get("Equity"), b.get("TotalAssets")
        ni = i.get("IncomeAfterTaxes")
        pct = lambda n, d: round(n / d * 100, 2) if (n is not None and d) else None
        ocf = c.get("NetCashInflowFromOperatingActivities")
        capex = c.get("PropertyAndPlantAndEquipment")
        out[y] = {
            "revenue": rev, "gross_profit": i.get("GrossProfit"),
            "operating_income": i.get("OperatingIncome"), "net_income": ni,
            "eps": i.get("EPS"),
            "gross_margin": pct(i.get("GrossProfit"), rev),
            "opex_ratio": pct(i.get("OperatingExpenses"), rev),
            "op_margin": pct(i.get("OperatingIncome"), rev),
            "net_margin": pct(ni, rev),
            "roe": pct(ni, eq), "roa": pct(ni, ta),
            "current_ratio": pct(b.get("CurrentAssets"), b.get("CurrentLiabilities")),
            "debt_ratio": pct(b.get("Liabilities"), ta),
            "cash": b.get("CashAndCashEquivalents"), "inventories": b.get("Inventories"),
            "equity": eq, "total_assets": ta,
            "operating_cf": ocf, "investing_cf": c.get("CashProvidedByInvestingActivities"),
            "financing_cf": c.get("CashFlowsProvidedFromFinancingActivities"),
            # capex 以「不動產廠房設備」為代理,FinMind 給的是負值(增加)
            "free_cf": (ocf + capex) if (ocf is not None and capex is not None) else None,
            "cf_end_cash": c.get("CashBalancesEndOfPeriod"),
        }
    return out


def sanity(rat, years):
    """沿用那支 skill 的合理性檢查 —— 數字荒謬時要講出來,不是照樣畫圖"""
    w = []
    for y in years:
        m = rat.get(y, {})
        gm, cr, dr, roe = m.get("gross_margin"), m.get("current_ratio"), \
            m.get("debt_ratio"), m.get("roe")
        if gm is not None and gm > 100:
            w.append({"level": "error", "field": f"{y} 毛利率", "msg": f"{gm:.1f}% 超過 100%"})
        if cr is not None and cr < 0:
            w.append({"level": "error", "field": f"{y} 流動比率", "msg": f"{cr:.1f}% 為負值"})
        if dr is not None and dr > 100:
            w.append({"level": "warn", "field": f"{y} 負債比率",
                      "msg": f"{dr:.1f}% 超過 100%,若非金融業為警示"})
        if roe is not None and abs(roe) > 100:
            w.append({"level": "warn", "field": f"{y} ROE",
                      "msg": f"{roe:.1f}% 絕對值超過 100%,請確認股東權益"})
        # 現金流量表期末現金 vs 資產負債表現金 —— 那支 skill 規定卻沒實作的交叉核對
        a, b2 = m.get("cash"), m.get("cf_end_cash")
        if a and b2 and abs(a - b2) > max(1.0, abs(a) * 0.02):
            w.append({"level": "warn", "field": f"{y} 現金交叉核對",
                      "msg": f"資產負債表 {a:,.0f} vs 現金流量表期末 {b2:,.0f},差異超過 2%"})
    nm = [(y, rat[y].get("net_margin")) for y in years if y in rat]
    for k in range(1, len(nm)):
        (y0, a), (y1, b2) = nm[k - 1], nm[k]
        if a is not None and b2 is not None and abs(b2 - a) > 30:
            w.append({"level": "warn", "field": f"{y0}→{y1} 淨利率",
                      "msg": f"波動 {b2 - a:+.1f} 個百分點,確認是否有一次性損益"})
    return w


def load_existing():
    """讀既有產出以支援續抓。360 個請求撞上 FinMind 配額時會拖很久,
    中途被砍不該讓整批重來 —— fetch_pit.py 已經踩過同一個坑。"""
    if not os.path.exists(DEST):
        return {}
    try:
        prev = json.load(open(DEST, encoding="utf-8")) or {}
    except (ValueError, OSError):
        return {}
    if prev.get("schema") != SCHEMA:
        print(f"既有產出是舊格式(schema {prev.get('schema')} ≠ {SCHEMA}),重新計算", flush=True)
        return {}
    return prev.get("stocks") or {}


def save(out):
    """寫暫存再 replace,避免中途失敗把既有產出毀掉"""
    os.makedirs(os.path.dirname(DEST), exist_ok=True)
    tmp = DEST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, DEST)


def main():
    stocks = json.load(open(STOCKS, encoding="utf-8"))["stocks"]
    ids = [(s["id"], s["name"]) for s in stocks]
    if LIMIT:
        ids = ids[:LIMIT]

    this_year = time.gmtime().tm_year
    start = f"{this_year - YEARS_BACK}-01-01"
    end = time.strftime("%Y-%m-%d")

    print("=== 先判別財報是單季還是累計(用月營收交叉驗)===", flush=True)
    try:
        basis, why = detect_basis("2330", this_year - 2)
    except QuotaExhausted:
        # 判別在主迴圈之前,這裡沒接住就會變成 traceback,
        # 看起來像程式壞了,其實只是配額還沒回補。
        print("  FinMind 配額用盡,連基準都判別不了 —— 稍後配額回補再跑",
              flush=True)
        print("  既有產出未被更動", flush=True)
        return 0
    print(f"  → {basis or '無法判別'}:{why}\n", flush=True)
    if not basis:
        raise SystemExit("✗ 無法判別財報基準,停止 —— 猜錯會讓所有比率靜默偏掉")

    done = load_existing()
    if done:
        print(f"續抓:已有 {len(done)} 檔,尚缺 {len(ids) - len(done)} 檔\n", flush=True)

    out = {"updated_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
           "schema": SCHEMA,
           "source": "FinMind", "basis": basis, "basis_note": why,
           "note": "Goodinfo 對資料中心 IP 回 403,故改用 FinMind;科目已逐一實測",
           "stocks": dict(done)}

    ok = len(done)
    no_data, quota_stopped = [], None
    for n, (sid, name) in enumerate(ids, 1):
        if sid in done:
            continue
        try:
            is_r = by_date(fm("TaiwanStockFinancialStatements", sid, start, end), IS_FIELDS)
            bs_r = by_date(fm("TaiwanStockBalanceSheet", sid, start, end), BS_FIELDS)
            cf_r = by_date(fm("TaiwanStockCashFlowsStatement", sid, start, end), CF_FIELDS)
        except QuotaExhausted:
            # 配額用盡後繼續跑只是空轉:上次這樣燒掉四十分鐘,還把十檔
            # 記成「無財報」。直接停下,保留已完成的部分,下次續抓。
            quota_stopped = sid
            print(f"\n  [{n:3}/{len(ids)}] {sid} {name}:FinMind 配額用盡,停止本輪", flush=True)
            print("  已完成的部分會保留,配額回補後重跑即可續抓", flush=True)
            break
        if not is_r:
            no_data.append(f"{sid} {name}")
            print(f"  [{n:3}/{len(ids)}] {sid} {name}:查無財報(API 有回應但無資料)", flush=True)
            continue

        flow = IS_FIELDS | CF_FIELDS          # 損益與現金流是流量,資產負債是存量
        rat = ratios(annualize(is_r, basis, flow),
                     annualize(bs_r, basis, flow),
                     annualize(cf_r, basis, flow))
        years = sorted(rat)[-3:]          # 都是流量完整的年度
        rat = {y: rat[y] for y in years}
        if not rat:
            continue

        out["stocks"][sid] = {
            "name": name, "years": years, "metrics": rat,
            "verification": {"sanity": sanity(rat, years)},
            "mops_url": f"https://mops.twse.com.tw/mops/web/t05st01?step=1&co_id={sid}&TYPEK=sii",
        }
        ok += 1
        if n % 10 == 0 or n == len(ids):
            save(out)                      # 每 10 檔落地一次,被砍也只損失最後幾檔
            print(f"  [{n:3}/{len(ids)}] 已完成 {ok} 檔", flush=True)

    out["no_data"] = no_data
    out["incomplete_from"] = quota_stopped     # 有值代表這輪沒跑完
    save(out)
    if quota_stopped:
        print(f"\n⚠ 本輪未跑完(停在 {quota_stopped}),不是所有個股都沒有財報", flush=True)
    warned = sum(1 for v in out["stocks"].values() if v["verification"]["sanity"])
    print(f"\n完成:{ok} 檔,{os.path.getsize(DEST)/1024:.0f} KB,"
          f"其中 {warned} 檔有合理性警示", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
