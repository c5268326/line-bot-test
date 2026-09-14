"""一次性研究腳本：波浪理論(ABC修正/五浪完成) + momentum_12_1 動能確認，能不能把勝率推到60%以上。

**這個檔案是研究用的暫時腳本，跑完會被移除，不進 pipeline.py。** 只透過 GitHub Actions
（有網路權限的 runner）執行一次、把結果印進 job summary，供 Claude session 讀回去寫進
RESEARCH.md，本機沙盒（網路出口被政策封鎖，見 RESEARCH.md「已知限制」）無法直接跑。

方法論延續 RESEARCH.md 第九、十一節：
- ZigZag 轉折點用因果版演算法（只用當下與過去價格，threshold% 反轉才確認），且訊號時間戳記
  用「確認日」而非「發生日」（第九節抓到的前視偏誤教訓）。
- ABC_DONE：轉折點序列最近4個是 [高,低,高,低]（對應A下、B上、C下三段修正腳），在最後一個
  低點的確認日觸發，代表修正完成、預期反彈。
- IMPULSE_DONE：轉折點序列最近6個是 [低,高,低,高,低,高]（對應五浪1-2-3-4-5），且套用三條
  客觀鐵律（浪2不跌破浪1起點、浪3不是三浪中最短、浪4不與浪1價格區間重疊），在最後一個高點
  的確認日觸發，代表五浪完成、預期修正。
- momentum_12_1：跟 factors.py 相同定義（skip 21、lookback 252 個交易日），在訊號確認日
  當天取值（因果、不偷看未來）。
- volume_ratio：訊號確認日當天成交量 / 過去20個交易日均量（不含當天），當作「帶量確認」
  的門檻，三種都測：只看動能、只看成交量、動能+成交量雙重確認。
- 確認門檻只用訓練期(confirm date <= 2019-12-31)挑選（避免用測試期結果回頭選門檻），
  再誠實報驗證期(2020-01-01~2022-12-31)、測試期(>2022-12-31)的樣本外表現。
- 公平基準：同一個「訊號可能出現的股票池 + 日期範圍」內，隨機 (股票,日期) 進場的勝率，
  按同樣的訓練/驗證/測試切法分開算，不是拿全市場或未過濾的基準來比。
"""
from __future__ import annotations

import argparse
import json
import os
import random
import time
from dataclasses import dataclass

import pandas as pd
import requests

FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"

MOMENTUM_SKIP = 21
MOMENTUM_LOOKBACK = 252
FORWARD_DAYS = 63
VOLUME_WINDOW = 20  # 成交量確認：當天量 / 過去20個交易日均量（不含當天，避免自己污染基準）
MIN_HISTORY = MOMENTUM_SKIP + MOMENTUM_LOOKBACK + FORWARD_DAYS + 10

TRAIN_END = pd.Timestamp("2019-12-31")
VAL_END = pd.Timestamp("2022-12-31")


def _finmind_request(dataset: str, data_id: str | None, start: str, end: str,
                      token: str, interval: float = 1.6, max_retries: int = 5) -> pd.DataFrame:
    params = {"dataset": dataset, "start_date": start, "end_date": end}
    if data_id:
        params["data_id"] = data_id
    if token:
        params["token"] = token
    backoff = interval
    for _ in range(max_retries):
        resp = requests.get(FINMIND_URL, params=params, timeout=30)
        if resp.status_code == 429:
            time.sleep(backoff)
            backoff *= 2
            continue
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("status") != 200:
            time.sleep(backoff)
            backoff *= 2
            continue
        time.sleep(interval)
        return pd.DataFrame(payload["data"])
    return pd.DataFrame()


def fetch_universe(token: str, max_tickers: int) -> list[str]:
    """抓 TWSE 全上市普通股清單（4碼數字代號，排除ETF/存託憑證/特別股等）。

    TaiwanStockInfo 是快照型資料集，start_date/end_date 若給同一天，FinMind可能因為內部
    用date欄位做區間篩選而回傳空集合；改用寬區間確保抓到完整清單。
    """
    info = _finmind_request("TaiwanStockInfo", None, "2000-01-01",
                             pd.Timestamp.today().strftime("%Y-%m-%d"), token, interval=0.5)
    if info.empty:
        raise RuntimeError("TaiwanStockInfo 回傳空資料，無法建立股票池")
    print(f"  TaiwanStockInfo 原始筆數: {len(info)}, 欄位: {list(info.columns)}")
    if "type" not in info.columns or "stock_id" not in info.columns:
        raise RuntimeError(f"TaiwanStockInfo 欄位跟預期不符: {list(info.columns)}")
    info = info[info["type"] == "twse"]
    info = info[info["stock_id"].str.fullmatch(r"\d{4}")]
    exclude_kw = ("ETF", "存託憑證", "特別股", "ETN")
    if "industry_category" in info.columns:
        info = info[~info["industry_category"].fillna("").str.contains("|".join(exclude_kw))]
    tickers = sorted(info["stock_id"].unique().tolist())
    print(f"  篩選後股票池大小: {len(tickers)}")
    if not tickers:
        raise RuntimeError("篩選後股票池為空，請檢查 type/stock_id/industry_category 篩選條件")
    return tickers[:max_tickers]


def fetch_prices(tickers: list[str], start: str, end: str, token: str) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for i, ticker in enumerate(tickers):
        try:
            raw = _finmind_request("TaiwanStockPrice", ticker, start, end, token)
        except Exception as exc:  # noqa: BLE001 - 單檔失敗不該中斷整批
            print(f"  [{i+1}/{len(tickers)}] {ticker} 抓取失敗: {exc}")
            continue
        if raw.empty or len(raw) < MIN_HISTORY:
            continue
        df = pd.DataFrame({
            "date": pd.to_datetime(raw["date"]),
            "close": pd.to_numeric(raw["close"], errors="coerce"),
            "volume": pd.to_numeric(raw.get("Trading_Volume"), errors="coerce"),
        }).dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
        df["volume"] = df["volume"].fillna(0.0)
        # 停牌/資料異常時 FinMind 偶爾會回傳 close=0，會讓ZigZag除以零；直接剔除這種列，
        # 不試著補值(補值等於臆測停牌期間真實價格，不誠實)。
        df = df[df["close"] > 0].reset_index(drop=True)
        if len(df) < MIN_HISTORY:
            continue
        out[ticker] = df
        if (i + 1) % 50 == 0:
            print(f"  已抓取 {i+1}/{len(tickers)} 檔（目前有效 {len(out)} 檔）")
    return out


@dataclass
class Pivot:
    kind: str          # 'H' or 'L'
    occ_idx: int        # 轉折點「發生日」的 index
    confirm_idx: int    # 轉折點「確認日」的 index（threshold% 反轉當天）
    price: float         # 發生日當天的收盤價


def zigzag_pivots(closes: list[float], threshold: float) -> list[Pivot]:
    """因果版 ZigZag：只用當下與過去的價格，反轉幅度 >= threshold 才確認一個轉折點。
    回傳的每個 Pivot 同時記錄「發生日」(occ_idx，事後看才知道是極值) 與「確認日」
    (confirm_idx，反轉幅度達標的那一天，訊號時間戳記必須用這個，不能用occ_idx)。
    """
    n = len(closes)
    if n < 2:
        return []

    cand_high_price, cand_high_idx = closes[0], 0
    cand_low_price, cand_low_idx = closes[0], 0
    first: Pivot | None = None
    for i in range(1, n):
        p = closes[i]
        if p > cand_high_price:
            cand_high_price, cand_high_idx = p, i
        if p < cand_low_price:
            cand_low_price, cand_low_idx = p, i
        if cand_high_price > closes[0] and cand_high_price > 0 and \
                (cand_high_price - p) / cand_high_price >= threshold:
            first = Pivot("H", cand_high_idx, i, cand_high_price)
            break
        if cand_low_price < closes[0] and cand_low_price > 0 and \
                (p - cand_low_price) / cand_low_price >= threshold:
            first = Pivot("L", cand_low_idx, i, cand_low_price)
            break
    if first is None:
        return []

    pivots = [first]
    trend = 1 if first.kind == "L" else -1  # 1: 現在在找高點, -1: 現在在找低點
    extreme_price, extreme_idx = closes[first.confirm_idx], first.confirm_idx

    for i in range(first.confirm_idx + 1, n):
        p = closes[i]
        if trend == 1:
            if p > extreme_price:
                extreme_price, extreme_idx = p, i
            elif extreme_price > 0 and (extreme_price - p) / extreme_price >= threshold:
                pivots.append(Pivot("H", extreme_idx, i, extreme_price))
                trend = -1
                extreme_price, extreme_idx = p, i
        else:
            if p < extreme_price:
                extreme_price, extreme_idx = p, i
            elif extreme_price > 0 and (p - extreme_price) / extreme_price >= threshold:
                pivots.append(Pivot("L", extreme_idx, i, extreme_price))
                trend = 1
                extreme_price, extreme_idx = p, i
    return pivots


def abc_done_signals(pivots: list[Pivot]) -> list[Pivot]:
    """回傳觸發 ABC_DONE(買進)的那些低點 Pivot：最近4個轉折點是 [高,低,高,低]。"""
    sigs = []
    for i in range(3, len(pivots)):
        window = pivots[i - 3:i + 1]
        if [p.kind for p in window] == ["H", "L", "H", "L"]:
            sigs.append(window[-1])
    return sigs


def impulse_done_signals(pivots: list[Pivot]) -> list[Pivot]:
    """回傳觸發 IMPULSE_DONE(避開/賣出)的那些高點 Pivot：最近6個轉折點是[低,高,低,高,低,高]，
    且套用三條客觀鐵律。"""
    sigs = []
    for i in range(5, len(pivots)):
        window = pivots[i - 5:i + 1]
        if [p.kind for p in window] != ["L", "H", "L", "H", "L", "H"]:
            continue
        w1_start, w1_end = window[0].price, window[1].price   # 浪1: L0 -> H1
        w2_end = window[2].price                              # 浪2低點
        w3_end = window[3].price                               # 浪3高點
        w4_end = window[4].price                                # 浪4低點
        w5_end = window[5].price                                 # 浪5高點
        wave1 = w1_end - w1_start
        wave2 = w1_end - w2_end
        wave3 = w3_end - w2_end
        wave4 = w3_end - w4_end
        wave5 = w5_end - w4_end
        if wave1 <= 0 or wave3 <= 0 or wave5 <= 0:
            continue
        if wave2 >= wave1:  # 鐵律1：浪2不可回撤超過浪1起點
            continue
        if wave3 <= min(wave1, wave5):  # 鐵律2：浪3不可是三浪中最短
            continue
        if w4_end <= w1_end:  # 鐵律3：浪4低點不可跟浪1價格區間重疊
            continue
        sigs.append(window[-1])
    return sigs


def momentum_at(closes: list[float], idx: int) -> float | None:
    j = idx - MOMENTUM_SKIP
    k = idx - MOMENTUM_SKIP - MOMENTUM_LOOKBACK
    if k < 0 or j < 0:
        return None
    if closes[k] == 0:
        return None
    return closes[j] / closes[k] - 1


def volume_ratio_at(volumes: list[float], idx: int, window: int = VOLUME_WINDOW) -> float | None:
    """當天成交量 / 過去window個交易日均量（不含當天）。用來當「帶量確認」的門檻。"""
    if idx - window < 0:
        return None
    baseline = volumes[idx - window:idx]
    avg = sum(baseline) / len(baseline) if baseline else 0.0
    if avg <= 0:
        return None
    return volumes[idx] / avg


def forward_return(closes: list[float], idx: int) -> float | None:
    if idx + FORWARD_DAYS >= len(closes):
        return None
    if closes[idx] == 0:
        return None
    return closes[idx + FORWARD_DAYS] / closes[idx] - 1


def split_label(date: pd.Timestamp) -> str:
    if date <= TRAIN_END:
        return "train"
    if date <= VAL_END:
        return "val"
    return "test"


def win_rate(rows: list[float]) -> tuple[float, int]:
    if not rows:
        return float("nan"), 0
    wins = sum(1 for r in rows if r > 0)
    return wins / len(rows), len(rows)


def evaluate_cutoffs(rows: list[tuple], predicate, cutoffs: list[float],
                      baseline_summary: dict, cutoff_field_name: str,
                      min_n: int = 30) -> tuple[list[dict], dict | None]:
    """rows: (split, *keys, fwd_ret) 的 list；predicate(row_keys, cutoff) -> bool 決定該筆
    是否通過門檻。回傳每個門檻的三段勝率/超額，以及「只用訓練期表現挑出的最佳門檻」。
    """
    results = []
    for cutoff in cutoffs:
        by_split: dict[str, list[float]] = {"train": [], "val": [], "test": []}
        for row in rows:
            split, fwd = row[0], row[-1]
            keys = row[1:-1]
            if predicate(keys, cutoff):
                by_split[split].append(fwd)
        per_split = {}
        for split in ("train", "val", "test"):
            wr, n = win_rate(by_split[split])
            base_wr = baseline_summary[split]["win_rate"]
            excess = (wr - base_wr) if n and base_wr == base_wr else float("nan")
            per_split[split] = {"win_rate": wr, "n": n, "baseline_win_rate": base_wr,
                                 "excess_pp": excess * 100 if excess == excess else None}
        results.append({cutoff_field_name: cutoff, "splits": per_split})
        p = per_split
        print(f"  {cutoff_field_name}>{cutoff:>7.2f}: train {p['train']['win_rate']:.1%}"
              f"(n={p['train']['n']}) | val {p['val']['win_rate']:.1%}(n={p['val']['n']}) | "
              f"test {p['test']['win_rate']:.1%}(n={p['test']['n']})")

    eligible = [c for c in results if c["splits"]["train"]["n"] >= min_n]
    best = max(eligible, key=lambda c: c["splits"]["train"]["win_rate"]) if eligible else None
    return results, best


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", default=os.environ.get("FINMIND_TOKEN", ""))
    parser.add_argument("--start", default="2014-01-01")
    parser.add_argument("--end", default=pd.Timestamp.today().strftime("%Y-%m-%d"))
    parser.add_argument("--max-tickers", type=int, default=500)
    parser.add_argument("--thresholds", default="0.05,0.08,0.12")
    parser.add_argument("--momentum-cutoffs", default="-999,0.0,0.10,0.20,0.30")
    parser.add_argument("--volume-cutoffs", default="-999,1.0,1.5,2.0,3.0")
    parser.add_argument("--out", default="wave_momentum_report.json")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)
    thresholds = [float(x) for x in args.thresholds.split(",")]
    mom_cutoffs = [float(x) for x in args.momentum_cutoffs.split(",")]
    vol_cutoffs = [float(x) for x in args.volume_cutoffs.split(",")]

    print(f"抓股票池（上限 {args.max_tickers} 檔）...")
    tickers = fetch_universe(args.token, args.max_tickers)
    print(f"股票池大小: {len(tickers)}")

    print("抓價格資料（每檔一次請求，含間隔避免429）...")
    price_data = fetch_prices(tickers, args.start, args.end, args.token)
    print(f"有效資料檔數: {len(price_data)} / {len(tickers)}")

    report: dict = {"n_tickers_fetched": len(price_data), "thresholds": {}}

    for threshold in thresholds:
        print(f"\n=== ZigZag threshold={threshold:.0%} ===")
        abc_rows = []   # (split, momentum, volume_ratio, fwd_ret)
        baseline_rows = []  # (split, fwd_ret) —— 隨機(股票,日期)基準，同一股票池/期間

        for ticker, df in price_data.items():
            dates = df["date"].tolist()
            closes = df["close"].tolist()
            volumes = df["volume"].tolist()
            pivots = zigzag_pivots(closes, threshold)

            for sig in abc_done_signals(pivots):
                idx = sig.confirm_idx
                mom = momentum_at(closes, idx)
                vol = volume_ratio_at(volumes, idx)
                fwd = forward_return(closes, idx)
                if mom is None or vol is None or fwd is None:
                    continue
                split = split_label(dates[idx])
                abc_rows.append((split, mom, vol, fwd))

            # 基準母體：這檔股票所有「momentum/前瞻報酬都算得出來」的日期，
            # 每 5 個交易日抽一個當候選，避免母體過度膨脹又維持覆蓋率。
            lo = MOMENTUM_SKIP + MOMENTUM_LOOKBACK
            hi = len(closes) - FORWARD_DAYS
            for idx in range(lo, hi, 5):
                fwd = forward_return(closes, idx)
                if fwd is None:
                    continue
                baseline_rows.append((split_label(dates[idx]), fwd))

        # 基準：每個 split 隨機抽最多 5000 筆，避免記憶體/print膨脹，抽樣不影響勝率估計
        baseline_by_split: dict[str, list[float]] = {"train": [], "val": [], "test": []}
        for split, fwd in baseline_rows:
            baseline_by_split[split].append(fwd)
        baseline_summary = {}
        for split, rows in baseline_by_split.items():
            sample = random.sample(rows, min(5000, len(rows))) if rows else []
            wr, n = win_rate(sample)
            baseline_summary[split] = {"win_rate": wr, "n": n}

        print(" -- 只看動能確認 --")
        mom_rows = [(split, mom, fwd) for split, mom, vol, fwd in abc_rows]
        mom_results, mom_best = evaluate_cutoffs(
            mom_rows, lambda keys, c: keys[0] > c, mom_cutoffs, baseline_summary, "momentum_cutoff")

        print(" -- 只看成交量確認(當天量/20日均量) --")
        vol_rows = [(split, vol, fwd) for split, mom, vol, fwd in abc_rows]
        vol_results, vol_best = evaluate_cutoffs(
            vol_rows, lambda keys, c: keys[0] > c, vol_cutoffs, baseline_summary, "volume_cutoff")

        combined_results = None
        combined_best = None
        if mom_best is not None:
            best_mom_cutoff = mom_best["momentum_cutoff"]
            print(f" -- 動能({best_mom_cutoff:.2f}，訓練期選出) + 成交量雙重確認 --")
            combined_rows = [(split, mom, vol, fwd) for split, mom, vol, fwd in abc_rows
                              if mom > best_mom_cutoff]
            combined_results, combined_best = evaluate_cutoffs(
                combined_rows, lambda keys, c: keys[1] > c, vol_cutoffs, baseline_summary,
                "volume_cutoff")

        report["thresholds"][f"{threshold:.2f}"] = {
            "baseline": baseline_summary,
            "momentum_only": {"cutoff_results": mom_results, "selected_by_train": mom_best},
            "volume_only": {"cutoff_results": vol_results, "selected_by_train": vol_best},
            "momentum_and_volume": {
                "momentum_cutoff": mom_best["momentum_cutoff"] if mom_best else None,
                "cutoff_results": combined_results, "selected_by_train": combined_best,
            },
        }
        if mom_best:
            print(f"  → 動能單獨最佳門檻 momentum>{mom_best['momentum_cutoff']:.2f}，"
                  f"樣本外 val={mom_best['splits']['val']['win_rate']:.1%} "
                  f"test={mom_best['splits']['test']['win_rate']:.1%}")
        if vol_best:
            print(f"  → 成交量單獨最佳門檻 volume>{vol_best['volume_cutoff']:.2f}倍，"
                  f"樣本外 val={vol_best['splits']['val']['win_rate']:.1%} "
                  f"test={vol_best['splits']['test']['win_rate']:.1%}")
        if combined_best:
            print(f"  → 動能+成交量雙重確認最佳門檻 volume>{combined_best['volume_cutoff']:.2f}倍，"
                  f"樣本外 val={combined_best['splits']['val']['win_rate']:.1%} "
                  f"test={combined_best['splits']['test']['win_rate']:.1%}")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n完整報告已寫入 {args.out}")


if __name__ == "__main__":
    main()
