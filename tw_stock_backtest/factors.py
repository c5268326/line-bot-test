"""因子計算：把價格面板 + 基本面面板轉成「橫斷面可比較」的因子分數，並合成複合分數。

所有因子在這裡都先轉成「數值越大越好」的方向（debt_to_equity 例外，見下方註解），
再由 config.FactorWeights 的正負號決定最終加權方向，這樣 config.py 一個檔案就能完整
表達「這個因子權重多少、方向要不要反轉」，不用到處翻程式碼。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import FactorWeights, FactorWindows

RAW_FACTOR_COLUMNS = [
    "earnings_yield", "book_to_price", "dividend_yield",
    "roe", "gross_margin", "debt_to_equity",
    "revenue_growth_yoy", "eps_growth_yoy",
    "momentum_12_1", "low_volatility", "institutional_net_buy",
]


def build_price_factors(prices: pd.DataFrame, windows: FactorWindows | None = None) -> pd.DataFrame:
    """由日頻價格面板算出動能、波動度因子，回傳長格式 (date, ticker, momentum_12_1, low_volatility)。

    `momentum_12_1` 這個欄位名稱沿用長期策略的預設窗口（12-1個月）命名，但實際回看天數由
    `windows` 決定——短期策略（見 config.short_term_config）會把它縮短成約「3個月-1週」，
    欄位名稱不變是為了讓 FactorWeights 的設定不必因為策略換了回看窗口而跟著改名。
    """
    windows = windows or FactorWindows()
    df = prices.sort_values(["ticker", "date"]).copy()
    df["ret"] = df.groupby("ticker")["close"].pct_change()
    df["momentum_12_1"] = df.groupby("ticker")["close"].transform(
        lambda s: s.shift(windows.momentum_skip_days) / s.shift(windows.momentum_lookback_days) - 1
    )
    vol = df.groupby("ticker")["ret"].transform(
        lambda s: s.rolling(windows.volatility_window_days,
                             min_periods=max(5, windows.volatility_window_days // 2)).std() * np.sqrt(252)
    )
    df["low_volatility"] = -vol  # 取負號，讓「數值越大 = 波動度越低 = 越好」
    df["avg_turnover_20d"] = df.groupby("ticker").apply(
        lambda g: (g["close"] * g["volume"]).rolling(20, min_periods=10).mean()
    ).reset_index(level=0, drop=True)
    return df[["date", "ticker", "momentum_12_1", "low_volatility", "avg_turnover_20d", "close"]]


def build_fundamental_factors(fundamentals: pd.DataFrame) -> pd.DataFrame:
    """由基本面面板算出價值 / 品質 / 成長因子。輸入的 date 必須是「公告可用日」。"""
    df = fundamentals.sort_values(["ticker", "date"]).copy()
    df["earnings_yield"] = 1.0 / df["per"].replace(0, np.nan)
    df["book_to_price"] = 1.0 / df["pbr"].replace(0, np.nan)
    df["revenue_growth_yoy"] = df["revenue_yoy"]
    df["eps_growth_yoy"] = df["eps_yoy"]
    return df[["date", "ticker", "earnings_yield", "book_to_price", "dividend_yield",
               "roe", "gross_margin", "debt_to_equity",
               "revenue_growth_yoy", "eps_growth_yoy"]]


def as_of_snapshot(price_factors: pd.DataFrame, fund_factors: pd.DataFrame,
                    as_of_date: pd.Timestamp, tickers: list[str]) -> pd.DataFrame:
    """組出某個決策日當下，每檔股票「當時已知」的最新因子值（不可用到未來資料）。"""
    rows = []
    pf = price_factors[price_factors["date"] <= as_of_date]
    ff = fund_factors[fund_factors["date"] <= as_of_date]
    for ticker in tickers:
        p = pf[pf["ticker"] == ticker].tail(1)
        f = ff[ff["ticker"] == ticker].tail(1)
        if p.empty:
            continue
        row = {"ticker": ticker,
               "momentum_12_1": p["momentum_12_1"].iloc[0],
               "low_volatility": p["low_volatility"].iloc[0],
               "avg_turnover_20d": p["avg_turnover_20d"].iloc[0],
               "institutional_net_buy": np.nan}
        if not f.empty:
            for col in ["earnings_yield", "book_to_price", "dividend_yield",
                        "roe", "gross_margin", "debt_to_equity",
                        "revenue_growth_yoy", "eps_growth_yoy"]:
                row[col] = f[col].iloc[0]
        else:
            for col in ["earnings_yield", "book_to_price", "dividend_yield",
                        "roe", "gross_margin", "debt_to_equity",
                        "revenue_growth_yoy", "eps_growth_yoy"]:
                row[col] = np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def zscore(series: pd.Series) -> pd.Series:
    std = series.std(ddof=0)
    if not np.isfinite(std) or std == 0:
        return pd.Series(0.0, index=series.index)
    return (series - series.mean()) / std


def composite_score(snapshot: pd.DataFrame, weights: FactorWeights) -> pd.Series:
    """對每個因子做橫斷面 z-score，再依權重加總；缺值因子視為中性（貢獻 0），不會讓整檔股票被排除。"""
    weight_map = weights.__dict__
    total_abs_weight = sum(abs(w) for w in weight_map.values()) or 1.0
    score = pd.Series(0.0, index=snapshot.index)
    for factor, weight in weight_map.items():
        if weight == 0 or factor not in snapshot.columns:
            continue
        z = zscore(snapshot[factor]).fillna(0.0)
        score = score + weight * z
    return score / total_abs_weight


def select_targets(snapshot: pd.DataFrame, scores: pd.Series, top_n: int,
                    min_avg_daily_turnover: float) -> list[str]:
    df = snapshot.copy()
    df["score"] = scores
    df = df[df["avg_turnover_20d"].fillna(0) >= min_avg_daily_turnover]
    df = df.dropna(subset=["momentum_12_1"])
    df = df.sort_values("score", ascending=False)
    return df["ticker"].head(top_n).tolist()
