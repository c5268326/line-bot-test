"""
台股量化策略回測:五個策略 × 有無 20% 停損 × 與 0050 買進持有對照。

輸入:research/data/{universe.csv, price.csv.gz, valuation.csv.gz, revenue.csv.gz}
產出:research/output/backtest_results.json
      research/output/report.md

回測設計(所有假設都寫在這裡,報告會一併輸出)
--------------------------------------------------------------------
期間      2015-01-01 ~ 資料最後一日
universe  證交所當日成交金額前 N 檔上市普通股(見 fetch_data.py)
換股頻率  每季第一個交易日
持股      等權重,每次選分數最高的 20 檔
進場價    換股日收盤價
出場      (a) 下次換股日收盤價,或
          (b) 觸發 20% 停損 —— 當日最低價 <= 進場價 × 0.8 時,
              以 min(當日開盤價, 停損價) 成交(反映跳空缺口),
              出場後持有現金至下次換股
交易成本  買進手續費 0.1425%;賣出手續費 0.1425% + 證交稅 0.3%
          (未給券商折扣,屬保守估計)
--------------------------------------------------------------------

前視偏誤的處理
  PER / PBR / 殖利率  FinMind 提供的是每日當下值,直接取換股日當天,無前視
  ROE                 由 PBR / PER 推導(PB/PE = E/B = ROE),同樣是當日值
  月營收              台股規定次月 10 日前公布,故只採用「換股日之前
                      至少 45 天已公布」的營收月份,避免用到未公布資料
  動能                只用換股日之前的價格
"""
import csv
import gzip
import json
import math
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
OUT_DIR = os.path.join(HERE, "output")

START = "2015-01-01"
TOP_N = 20                 # 每期持股檔數
STOP_LOSS = 0.20           # 停損幅度
FEE = 0.001425             # 手續費(單邊)
TAX = 0.003                # 證交稅(賣出)
BENCHMARK = "0050"


# =====================================================================
# 讀資料
# =====================================================================
def read_gz(name, numeric):
    """
    讀壓縮 CSV。抓取工作被中斷時 gzip 串流可能沒有正常收尾,
    此時保留已讀到的部分並警告,而不是整份資料丟掉。
    """
    rows = []
    path = os.path.join(DATA_DIR, name)
    if not os.path.exists(path):
        print(f"  ⚠ 找不到 {name},相關策略將被略過", flush=True)
        return rows
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out = dict(r)
                ok = True
                for k in numeric:
                    v = out.get(k)
                    if v in (None, "", "None", "nan"):
                        out[k] = None
                        continue
                    try:
                        out[k] = float(v)
                    except ValueError:
                        ok = False
                        break
                if ok:
                    rows.append(out)
    except (EOFError, gzip.BadGzipFile) as e:
        print(f"  ⚠ {name} 檔案不完整({type(e).__name__}),"
              f"採用已讀到的 {len(rows):,} 筆", flush=True)
    return rows


def load():
    print("讀取資料 …", flush=True)

    price_rows = read_gz("price.csv.gz", ["open", "max", "min", "close", "Trading_Volume", "Trading_money"])
    val_rows = read_gz("valuation.csv.gz", ["PER", "PBR", "dividend_yield"])
    rev_rows = read_gz("revenue.csv.gz", ["revenue", "revenue_year", "revenue_month"])

    # price[stock][date] = bar
    price = defaultdict(dict)
    for r in price_rows:
        if r["close"] and r["close"] > 0:
            price[r["stock_id"]][r["date"]] = r

    val = defaultdict(dict)
    for r in val_rows:
        val[r["stock_id"]][r["date"]] = r

    # revenue[stock] = [(YYYY-MM 營收所屬月, 營收, 公布日下限)]
    revenue = defaultdict(dict)
    for r in rev_rows:
        y, m = r.get("revenue_year"), r.get("revenue_month")
        if not y or not m or not r.get("revenue"):
            continue
        revenue[r["stock_id"]][(int(y), int(m))] = r["revenue"]

    all_dates = sorted({d for s in price.values() for d in s})
    print(f"  個股 {len(price)} 檔,交易日 {len(all_dates)} 天"
          f"({all_dates[0]} ~ {all_dates[-1]})", flush=True)
    return price, val, revenue, all_dates


# =====================================================================
# 換股日
# =====================================================================
def rebalance_dates(all_dates, start=START):
    """每季第一個交易日"""
    seen, out = set(), []
    for d in all_dates:
        if d < start:
            continue
        y, m = int(d[:4]), int(d[5:7])
        q = (y, (m - 1) // 3)
        if q not in seen:
            seen.add(q)
            out.append(d)
    return out


# =====================================================================
# 因子
# =====================================================================
def latest_on_or_before(series, when, max_back_days=15):
    """取 when 當日或之前最近一筆(容忍停牌/假日)"""
    if when in series:
        return series[when]
    d = datetime.strptime(when, "%Y-%m-%d").date()
    for back in range(1, max_back_days + 1):
        k = (d - timedelta(days=back)).isoformat()
        if k in series:
            return series[k]
    return None


def trailing_return(bars_dates, series, when, lookback_days, skip_days=0):
    """(when - skip) 相對 (when - lookback) 的報酬"""
    d = datetime.strptime(when, "%Y-%m-%d").date()
    end_key = None
    for back in range(skip_days, skip_days + 15):
        k = (d - timedelta(days=back)).isoformat()
        if k in series:
            end_key = k
            break
    start_key = None
    for back in range(lookback_days, lookback_days + 20):
        k = (d - timedelta(days=back)).isoformat()
        if k in series:
            start_key = k
            break
    if not end_key or not start_key:
        return None
    p0, p1 = series[start_key]["close"], series[end_key]["close"]
    if not p0 or p0 <= 0:
        return None
    return p1 / p0 - 1


def revenue_yoy(rev, when):
    """
    月營收年增率(近三個月平均,平滑出貨節奏)。
    台股規定次月 10 日前公布,保守起見只採用換股日 45 天前所屬的月份,
    確保回測當下該筆營收確實已經公布。
    """
    d = datetime.strptime(when, "%Y-%m-%d").date()
    cutoff = d - timedelta(days=45)
    y, m = cutoff.year, cutoff.month

    ratios = []
    for back in range(3):
        mm = m - back
        yy = y
        while mm <= 0:
            mm += 12
            yy -= 1
        cur = rev.get((yy, mm))
        prev = rev.get((yy - 1, mm))
        if cur and prev and prev > 0:
            ratios.append(cur / prev - 1)
    if not ratios:
        return None
    return sum(ratios) / len(ratios)


def rank_composite(items):
    """
    雙因子排名合成。items = [(sid, 值A, 值B)],兩者皆為越大越好。
    分別轉成百分位排名再相加,避免量綱差異讓其中一個因子主導。
    """
    n = len(items)
    if n < 2:
        return [(sid, 0.0) for sid, _, _ in items]
    ranks = {}
    for idx in (1, 2):
        order = sorted(range(n), key=lambda i: items[i][idx])
        for pos, i in enumerate(order):
            sid = items[i][0]
            ranks[sid] = ranks.get(sid, 0.0) + pos / (n - 1)
    return [(sid, ranks[sid]) for sid, _, _ in items]


def build_scores(strategy, when, universe, price, val, revenue):
    """回傳 [(stock_id, 分數)],分數越高越優先"""

    if strategy == "quality_value":
        # 品質與價值各自獨立排名後相加。
        # 先前寫成 roe/PBR,代入 roe=PBR/PER 後恰好等於 1/PER,
        # 等於退化成純低本益比,品質完全沒有參與排序 —— 那是實作錯誤。
        cand = []
        for sid in universe:
            pser = price.get(sid)
            if not pser or when not in pser:
                continue
            v = latest_on_or_before(val.get(sid, {}), when)
            if not v:
                continue
            per, pbr = v.get("PER"), v.get("PBR")
            if not per or not pbr or per <= 0 or pbr <= 0:
                continue
            roe = pbr / per
            if roe <= 0.08:                      # 品質門檻:年化 ROE 需高於 8%
                continue
            cand.append((sid, roe, -pbr))        # 高 ROE 好、低 PBR 好
        scored = rank_composite(cand)
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    out = []
    for sid in universe:
        pser = price.get(sid)
        if not pser or when not in pser:
            continue                      # 當日沒交易(未上市/停牌)就跳過
        v = latest_on_or_before(val.get(sid, {}), when)

        score = None
        if strategy == "value_pb":
            if v and v.get("PBR") and v["PBR"] > 0:
                score = -v["PBR"]                       # 低股價淨值比優先

        elif strategy == "dividend":
            if v and v.get("dividend_yield") and v["dividend_yield"] > 0:
                if v.get("PER") and 0 < v["PER"] < 30:  # 排除虧損與本益比異常高者
                    score = v["dividend_yield"]

        elif strategy == "momentum":
            score = trailing_return(None, pser, when, lookback_days=365, skip_days=21)

        elif strategy == "revenue_momentum":
            score = revenue_yoy(revenue.get(sid, {}), when)

        elif strategy == "universe_ew":
            # 對照組:同一個 universe 等權全持。
            # 它和各策略吃同一份倖存者偏誤,兩者相減才是策略真正的貢獻。
            score = 0.0

        if score is not None and math.isfinite(score):
            out.append((sid, score))

    out.sort(key=lambda x: x[1], reverse=True)
    return out


# =====================================================================
# 回測
# =====================================================================
def run(strategy, use_stop, price, val, revenue, all_dates, universe):
    """
    逐日計算權益曲線。只在換股日取樣的話,季中的回檔會完全看不見,
    最大回撤與夏普都會嚴重失真 —— 對停損研究來說那等於白做。
    """
    rebals = rebalance_dates(all_dates)
    date_idx = {d: i for i, d in enumerate(all_dates)}

    equity = 1.0
    curve = [(rebals[0], equity)]
    trades = []
    stop_hits = 0

    for i, rb in enumerate(rebals):
        end_date = rebals[i + 1] if i + 1 < len(rebals) else all_dates[-1]
        span = all_dates[date_idx[rb]: date_idx[end_date] + 1]
        n_hold = len(universe) if strategy == "universe_ew" else TOP_N
        picks = [s for s, _ in build_scores(strategy, rb, universe, price, val, revenue)[:n_hold]]

        if not picks:
            for d in span[1:]:
                curve.append((d, equity))
            continue

        weight = 1.0 / len(picks)
        base = equity

        # 每檔的持倉狀態;exit_value 為已實現的每元淨值(含賣出成本)
        pos = {}
        for sid in picks:
            entry = price[sid][rb]["close"]
            pos[sid] = {
                "entry": entry if entry and entry > 0 else None,
                "stop": (entry * (1 - STOP_LOSS)) if entry and entry > 0 else None,
                "exit_value": None, "exit_price": None, "exit_date": None, "stopped": False,
            }

        for d in span[1:]:
            port = 0.0
            for sid, p in pos.items():
                if p["entry"] is None:
                    port += weight               # 沒有有效進場價,當作持平
                    continue
                if p["exit_value"] is not None:
                    port += weight * p["exit_value"]   # 已停損,轉持現金
                    continue

                bar = price[sid].get(d)

                if use_stop and bar:
                    low = bar.get("min") if bar.get("min") else bar.get("close")
                    if low is not None and low <= p["stop"]:
                        # 跳空開低時不可能在停損價成交,取開盤價與停損價的較低者
                        op = bar.get("open") or bar.get("close")
                        fill = min(op, p["stop"]) if op else p["stop"]
                        p["exit_value"] = (fill / p["entry"]) * (1 - FEE) * (1 - FEE - TAX)
                        p["exit_price"], p["exit_date"], p["stopped"] = fill, d, True
                        stop_hits += 1
                        port += weight * p["exit_value"]
                        continue

                if bar:
                    px = bar["close"]
                else:
                    last = latest_on_or_before(price[sid], d)   # 停牌沿用最後價格
                    px = last["close"] if last else p["entry"]
                port += weight * (px / p["entry"]) * (1 - FEE)  # 未實現,只扣買進成本

            curve.append((d, base * port))

        # 期末結算尚未停損的部位
        final = 0.0
        for sid, p in pos.items():
            if p["entry"] is None:
                final += weight
                continue
            if p["exit_value"] is None:
                last = latest_on_or_before(price[sid], end_date)
                exit_price = last["close"] if last else p["entry"]
                p["exit_value"] = (exit_price / p["entry"]) * (1 - FEE) * (1 - FEE - TAX)
                p["exit_price"], p["exit_date"] = exit_price, end_date
            final += weight * p["exit_value"]

            trades.append({
                "strategy": strategy, "stop": use_stop, "stock": sid,
                "entry_date": rb, "exit_date": p["exit_date"],
                "entry": round(p["entry"], 2), "exit": round(p["exit_price"], 2),
                "ret": round(p["exit_value"] - 1, 4), "stopped": p["stopped"],
            })

        equity = base * final
        curve[-1] = (end_date, equity)

    return equity, curve, trades, stop_hits


def buy_and_hold(sid, price, all_dates):
    pser = price.get(sid)
    if not pser:
        return None, []
    days = sorted(d for d in pser if d >= START)
    if len(days) < 2:
        return None, []
    entry = pser[days[0]]["close"]
    curve = [(d, pser[d]["close"] / entry) for d in days]
    final = curve[-1][1] * (1 - FEE) * (1 - FEE - TAX)
    return final, curve


# =====================================================================
# 績效指標
# =====================================================================
def metrics(curve, trades=None, stop_hits=0):
    if len(curve) < 2:
        return {}
    d0 = datetime.strptime(curve[0][0], "%Y-%m-%d").date()
    d1 = datetime.strptime(curve[-1][0], "%Y-%m-%d").date()
    years = max((d1 - d0).days / 365.25, 1e-9)
    total = curve[-1][1] - 1
    cagr = curve[-1][1] ** (1 / years) - 1 if curve[-1][1] > 0 else -1

    peak, mdd = -1e9, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1)

    rets = []
    for a, b in zip(curve, curve[1:]):
        if a[1] > 0:
            rets.append(b[1] / a[1] - 1)
    if len(rets) > 1:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        sd = math.sqrt(var)
        periods_per_year = len(rets) / years
        vol = sd * math.sqrt(periods_per_year)
        sharpe = (cagr - 0.015) / vol if vol > 0 else None   # 無風險利率概估 1.5%
    else:
        vol, sharpe = None, None

    m = {
        "total_return": round(total, 4),
        "cagr": round(cagr, 4),
        "max_drawdown": round(mdd, 4),
        "volatility": round(vol, 4) if vol else None,
        "sharpe": round(sharpe, 3) if sharpe else None,
        "periods": len(curve) - 1,
    }
    if trades is not None:
        wins = [t for t in trades if t["ret"] > 0]
        m["trades"] = len(trades)
        m["win_rate"] = round(len(wins) / len(trades), 4) if trades else None
        m["avg_trade"] = round(sum(t["ret"] for t in trades) / len(trades), 4) if trades else None
        m["stop_hits"] = stop_hits
        m["stop_rate"] = round(stop_hits / len(trades), 4) if trades else None
    return m


BENCH_LABEL = "對照:universe 等權全持"

STRATEGY_LABEL = {
    "value_pb": "價值:低股價淨值比",
    "quality_value": "品質×價值:ROE 與 PBR 雙因子排名",
    "dividend": "高現金殖利率",
    "momentum": "動能:12-1 相對強弱",
    "revenue_momentum": "月營收年增動能",
}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    price, val, revenue, all_dates = load()

    with open(os.path.join(DATA_DIR, "universe.csv"), encoding="utf-8") as f:
        universe = [r["stock_id"] for r in csv.DictReader(f)]
    print(f"  universe {len(universe)} 檔\n", flush=True)

    results = {"config": {
        "start": START, "end": all_dates[-1], "top_n": TOP_N,
        "stop_loss": STOP_LOSS, "fee": FEE, "tax": TAX,
        "universe_size": len(universe), "rebalance": "quarterly",
    }, "strategies": {}, "benchmark": {}}

    # 對照組:同 universe 等權全持,不含停損。
    # 各策略與它相減,才是扣掉倖存者偏誤後策略真正的貢獻。
    bench_final, bench_curve, bench_trades, _ = run(
        "universe_ew", False, price, val, revenue, all_dates, universe)
    bm = metrics(bench_curve, bench_trades, 0)
    results["benchmark"] = {"id": "universe_ew", "label": BENCH_LABEL, **bm}
    results["benchmark"]["curve"] = [{"d": d, "v": round(v, 4)} for d, v in bench_curve[::5]]
    print(f"{BENCH_LABEL:24} {'無停損  '}"
          f"  總報酬 {bm['total_return'] * 100:+8.1f}%"
          f"  年化 {bm['cagr'] * 100:+6.2f}%"
          f"  MDD {bm['max_drawdown'] * 100:6.1f}%\n", flush=True)

    bh_final, bh_curve = buy_and_hold(BENCHMARK, price, all_dates)
    if bh_final:
        results["benchmark_etf"] = {"id": BENCHMARK, "total_return": round(bh_final - 1, 4)}
        print(f"對照組 {BENCHMARK} 買進持有:總報酬 {(bh_final - 1) * 100:+.1f}%\n", flush=True)
    else:
        print(f"(找不到 {BENCHMARK} 的價格資料,以 universe 等權作為唯一對照)\n", flush=True)

    for strat in STRATEGY_LABEL:
        results["strategies"][strat] = {"label": STRATEGY_LABEL[strat]}
        for use_stop in (False, True):
            key = "with_stop" if use_stop else "no_stop"
            final, curve, trades, hits = run(
                strat, use_stop, price, val, revenue, all_dates, universe)
            m = metrics(curve, trades, hits)
            results["strategies"][strat][key] = m
            # 曲線改存每週一點,檔案才不會爆掉(指標仍以逐日資料計算)
            results["strategies"][strat][key + "_curve"] = [
                {"d": d, "v": round(v, 4)} for d, v in curve[::5]]
            print(f"{STRATEGY_LABEL[strat]:24} {'含20%停損' if use_stop else '無停損  '}"
                  f"  總報酬 {m['total_return'] * 100:+8.1f}%"
                  f"  年化 {m['cagr'] * 100:+6.2f}%"
                  f"  MDD {m['max_drawdown'] * 100:6.1f}%"
                  f"  勝率 {(m.get('win_rate') or 0) * 100:5.1f}%"
                  f"  停損率 {(m.get('stop_rate') or 0) * 100:5.1f}%", flush=True)
        print("", flush=True)

    out = os.path.join(OUT_DIR, "backtest_results.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, separators=(",", ":"))
    print(f"已寫入 {out}({os.path.getsize(out) / 1024:.0f} KB)", flush=True)

    write_report(results)
    return 0


def pct(v, digits=1):
    return "—" if v is None else f"{v * 100:+.{digits}f}%"


def write_report(res):
    """輸出人可讀的 markdown 報告"""
    c = res["config"]
    L = []
    L.append("# 台股五策略回測結果\n")
    L.append(f"回測期間 **{c['start']} ~ {c['end']}**,"
             f"universe {c['universe_size']} 檔,每季換股,等權持有 {c['top_n']} 檔。\n")

    b = res.get("benchmark") or {}
    if b:
        L.append(f"對照組 **{b['id']} 買進持有**:總報酬 {pct(b.get('total_return'))}、"
                 f"年化 {pct(b.get('cagr'), 2)}、最大回撤 {pct(b.get('max_drawdown'))}\n")

    L.append("\n## 總覽\n")
    L.append("| 策略 | 停損 | 總報酬 | 年化 | 最大回撤 | 夏普 | 勝率 | 停損觸發率 |")
    L.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for _, s in res["strategies"].items():
        for key, label in (("no_stop", "無"), ("with_stop", "20%")):
            m = s.get(key) or {}
            L.append(
                f"| {s['label']} | {label} | {pct(m.get('total_return'))} | "
                f"{pct(m.get('cagr'), 2)} | {pct(m.get('max_drawdown'))} | "
                f"{m.get('sharpe') if m.get('sharpe') is not None else '—'} | "
                f"{pct(m.get('win_rate')) if m.get('win_rate') is not None else '—'} | "
                f"{pct(m.get('stop_rate')) if m.get('stop_rate') is not None else '—'} |")

    L.append("\n## 扣掉 universe 偏誤後的超額報酬\n")
    bench_cagr = (res.get("benchmark") or {}).get("cagr")
    if bench_cagr is not None:
        L.append(f"對照組(同 universe 等權全持)年化 **{pct(bench_cagr, 2)}**。"
                 "策略與它的差額,才是選股邏輯真正的貢獻;"
                 "兩者吃同一份倖存者偏誤,相減可大致抵銷。\n")
        L.append("| 策略 | 年化(無停損) | 對照組 | 超額 |")
        L.append("|---|---:|---:|---:|")
        for _, s2 in res["strategies"].items():
            m = s2.get("no_stop") or {}
            if m.get("cagr") is None:
                continue
            L.append(f"| {s2['label']} | {pct(m['cagr'], 2)} | {pct(bench_cagr, 2)} | "
                     f"{(m['cagr'] - bench_cagr) * 100:+.2f}pp |")

    L.append("\n## 停損的影響\n")
    L.append("| 策略 | 無停損年化 | 含停損年化 | 差異 | 回撤改善 |")
    L.append("|---|---:|---:|---:|---:|")
    for _, s in res["strategies"].items():
        a, bb = s.get("no_stop") or {}, s.get("with_stop") or {}
        if a.get("cagr") is None or bb.get("cagr") is None:
            continue
        d = bb["cagr"] - a["cagr"]
        dd = (bb.get("max_drawdown") or 0) - (a.get("max_drawdown") or 0)
        L.append(f"| {s['label']} | {pct(a['cagr'], 2)} | {pct(bb['cagr'], 2)} | "
                 f"{d * 100:+.2f}pp | {dd * 100:+.1f}pp |")

    L.append("\n## 必須知道的限制\n")
    L.append("- **倖存者偏誤**:universe 以「今天」的成交金額前 N 檔回頭選股,"
             "下市與長期萎縮的公司完全不在樣本中,所有報酬數字都因此偏高。\n")
    L.append("- **交易成本**已計入手續費 0.1425% 雙邊與賣出證交稅 0.3%,未給券商折扣;"
             "但**未計入滑價與流動性衝擊**,高週轉策略的實際報酬會再低一些。\n")
    L.append("- **未計入股利**:報酬僅為價格報酬,高股息策略因此被系統性低估。\n")
    L.append("- 回測是對歷史的描述,不是對未來的預測,更不是投資建議。\n")

    path = os.path.join(OUT_DIR, "report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print(f"已寫入 {path}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
