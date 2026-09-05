"""
用 point-in-time 股票池重跑回測,並與舊的固定股票池結果並列比較。

差別只在股票池怎麼決定:
  舊  用「今天」的成交金額前 120 名回頭套十年 —— 名單裡有大量公司在
      回測初期還沒上市,已下市的公司則完全不在樣本內
  新  每個換股日各自取當天成交金額前 N 名 —— 只看當時真正買得到的股票

指標計算、訊號判斷、交易成本、停損邏輯全部沿用 backtest.py,
確保兩者的差異只來自股票池。

輸入 research/data/pit/{universe_by_date.csv, price.csv.gz}
產出 research/output/backtest_pit.json
     research/output/compare.md
"""
import csv
import gzip
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest as B  # noqa: E402  沿用同一份指標與回測邏輯

PIT_DIR = os.path.join(B.HERE, "data", "pit")


def load_pit():
    uni_path = os.path.join(PIT_DIR, "universe_by_date.csv")
    price_path = os.path.join(PIT_DIR, "price.csv.gz")
    for p in (uni_path, price_path):
        if not os.path.exists(p):
            raise SystemExit(f"找不到 {p},請先執行 fetch_pit.py")

    # universe[換股日] = [代號…];val[代號][換股日] = 估值
    universe, val = defaultdict(list), defaultdict(dict)
    with open(uni_path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            d, sid = r["date"], r["stock_id"]
            universe[d].append(sid)

            def fnum(key):
                v = r.get(key)
                try:
                    return float(v) if v not in (None, "", "None") else None
                except ValueError:
                    return None

            val[sid][d] = {"PER": fnum("per"), "PBR": fnum("pbr"),
                           "dividend_yield": fnum("yield")}

    price = defaultdict(dict)
    total = 0
    try:
        with gzip.open(price_path, "rt", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    c = float(r["close"])
                except (TypeError, ValueError):
                    continue
                if c <= 0:
                    continue

                def g(k):
                    try:
                        return float(r[k])
                    except (TypeError, ValueError):
                        return None

                price[r["stock_id"]][r["date"]] = {
                    "open": g("open") or c, "max": g("max") or c,
                    "min": g("min") or c, "close": c,
                    "Trading_Volume": g("Trading_Volume") or 0,
                }
                total += 1
    except (EOFError, gzip.BadGzipFile) as e:
        print(f"  ⚠ price.csv.gz 不完整({type(e).__name__}),採用已讀到的 {total:,} 筆")

    all_dates = sorted({d for s in price.values() for d in s})
    sizes = [len(v) for v in universe.values()]
    print(f"  股票池 {len(universe)} 期,每期 {min(sizes)}~{max(sizes)} 檔,"
          f"聯集 {len({s for v in universe.values() for s in v})} 檔")
    print(f"  日線 {total:,} 筆,{len(price)} 檔,{all_dates[0]} ~ {all_dates[-1]}")
    return dict(universe), price, val, all_dates


def main():
    print("讀取 point-in-time 資料 …", flush=True)
    universe, price, val, all_dates = load_pit()

    # 月營收資料只有舊股票池那 120 檔有,PIT 聯集涵蓋不到,
    # 硬跑會變成「在一小撮股票裡選股」—— 那是另一種偏誤,寧可不報。
    revenue = {}
    strategies = [k for k in B.STRATEGY_LABEL if k != "revenue_momentum"]
    print(f"  回測策略:{strategies}")
    print("  (月營收動能需另外抓取聯集個股的營收資料,本輪略過)\n", flush=True)

    results = {"config": {
        "start": B.START, "end": all_dates[-1], "top_n": B.TOP_N,
        "stop_loss": B.STOP_LOSS, "fee": B.FEE, "tax": B.TAX,
        "universe_mode": "point-in-time",
        "universe_periods": len(universe),
        "universe_size": max(len(v) for v in universe.values()),
        "rebalance": "quarterly",
    }, "benchmark": {}, "strategies": {}}

    bench_final, bench_curve, bench_trades, _ = B.run(
        "universe_ew", False, price, val, revenue, all_dates, universe)
    bm = B.metrics(bench_curve, bench_trades, 0)
    results["benchmark"] = {"id": "universe_ew", "label": B.BENCH_LABEL, **bm}
    results["benchmark"]["curve"] = [{"d": d, "v": round(v, 4)} for d, v in bench_curve[::5]]
    print(f"{B.BENCH_LABEL:24} 年化 {bm['cagr']*100:+6.2f}%  "
          f"總報酬 {bm['total_return']*100:+8.1f}%  MDD {bm['max_drawdown']*100:6.1f}%\n", flush=True)

    for strat in strategies:
        results["strategies"][strat] = {"label": B.STRATEGY_LABEL[strat]}
        for use_stop in (False, True):
            key = "with_stop" if use_stop else "no_stop"
            _, curve, trades, hits = B.run(
                strat, use_stop, price, val, revenue, all_dates, universe)
            m = B.metrics(curve, trades, hits)
            results["strategies"][strat][key] = m
            results["strategies"][strat][key + "_curve"] = [
                {"d": d, "v": round(v, 4)} for d, v in curve[::5]]
            print(f"{B.STRATEGY_LABEL[strat]:24} {'含20%停損' if use_stop else '無停損  '}"
                  f"  年化 {m['cagr']*100:+6.2f}%"
                  f"  超額 {(m['cagr']-bm['cagr'])*100:+6.2f}pp"
                  f"  MDD {m['max_drawdown']*100:6.1f}%"
                  f"  夏普 {m.get('sharpe')}", flush=True)
        print("", flush=True)

    os.makedirs(B.OUT_DIR, exist_ok=True)
    out = os.path.join(B.OUT_DIR, "backtest_pit.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, separators=(",", ":"))
    print(f"已寫入 {out}", flush=True)

    write_compare(results)
    return 0


def write_compare(new):
    """把新舊兩種股票池的結果並列,讓偏誤的規模可以直接讀出來"""
    old_path = os.path.join(B.OUT_DIR, "backtest_results.json")
    if not os.path.exists(old_path):
        return
    old = json.load(open(old_path, encoding="utf-8"))

    pct = lambda v, d=2: "—" if v is None else f"{v*100:+.{d}f}%"
    L = ["# 股票池修正前後對照\n",
         "兩份回測的指標、訊號、交易成本、停損邏輯完全相同,",
         "唯一差別是股票池怎麼決定。\n",
         "| | 舊:固定股票池 | 新:point-in-time |",
         "|---|---|---|",
         f"| 選股方式 | 用今天的成交金額前 {old['config']['universe_size']} 名回頭套十年 | "
         f"每個換股日各取當天前 {new['config']['universe_size']} 名 |",
         f"| 期數 | 1 份名單共用 | {new['config']['universe_periods']} 期各自一份 |",
         "", "## 年化報酬\n",
         "| 策略 | 舊 | 新 | 差異 |", "|---|---:|---:|---:|"]

    ob, nb = old["benchmark"]["cagr"], new["benchmark"]["cagr"]
    L.append(f"| **{new['benchmark']['label']}** | {pct(ob)} | {pct(nb)} | {(nb-ob)*100:+.2f}pp |")
    for k, s in new["strategies"].items():
        if k not in old["strategies"]:
            continue
        o, n = old["strategies"][k]["no_stop"]["cagr"], s["no_stop"]["cagr"]
        L.append(f"| {s['label']} | {pct(o)} | {pct(n)} | {(n-o)*100:+.2f}pp |")

    L += ["", "## 對照組超額(扣掉股票池效應後,選股邏輯真正的貢獻)\n",
          "| 策略 | 舊 | 新 |", "|---|---:|---:|"]
    for k, s in new["strategies"].items():
        if k not in old["strategies"]:
            continue
        oe = old["strategies"][k]["no_stop"]["cagr"] - ob
        ne = s["no_stop"]["cagr"] - nb
        L.append(f"| {s['label']} | {oe*100:+.2f}pp | {ne*100:+.2f}pp |")

    L += ["", "## 仍然存在的限制\n",
          "- point-in-time 修正了「用今天的名單回頭套」這一項,但股票池仍以"
          "**成交金額**排序,等於偏向大型股,不是全市場。",
          "- 未計入股利,高股息策略被系統性低估。",
          "- 未計入滑價與流動性衝擊。",
          "- 回測是對歷史的描述,不是對未來的預測,更不是投資建議。"]

    path = os.path.join(B.OUT_DIR, "compare.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print(f"已寫入 {path}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
