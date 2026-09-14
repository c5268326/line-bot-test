"""以 yfinance 作為資料源。需要在有網路權限的環境安裝 `yfinance` 套件。

限制（誠實列出，不要假裝沒有）：
- 台股代號要加 `.TW`（上市）或 `.TWO`（上櫃），本模組預設全部嘗試 `.TW`，上櫃股票
  請自行在 tickers 帶入時加上正確後綴，例如 "6488.TWO"。
- yfinance 對台股的財報欄位（quarterly_financials / balance_sheet）覆蓋率不完整、
  部分小型股甚至完全沒有資料，PER/PBR/股息殖利率的歷史序列品質也不穩定。
  **建議基本面請改用 FinMindDataSource**，這裡的 get_fundamentals 僅供 demo / 備援。
"""
from __future__ import annotations

import pandas as pd

from .base import DataSource


def _to_tw_ticker(ticker: str) -> str:
    return ticker if "." in ticker else f"{ticker}.TW"


class YFinanceDataSource(DataSource):
    def __init__(self):
        try:
            import yfinance as yf  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "請先安裝 yfinance： pip install yfinance"
            ) from e

    def get_price_history(self, tickers: list[str], start: str, end: str) -> pd.DataFrame:
        import yfinance as yf

        tw_tickers = [_to_tw_ticker(t) for t in tickers]
        raw = yf.download(
            tw_tickers, start=start, end=end, group_by="ticker",
            auto_adjust=False, progress=False, threads=True,
        )
        rows = []
        for orig, tw in zip(tickers, tw_tickers):
            try:
                sub = raw[tw] if len(tw_tickers) > 1 else raw
            except KeyError:
                continue
            sub = sub.dropna(how="all").reset_index()
            if sub.empty:
                continue
            rows.append(pd.DataFrame({
                "date": sub["Date"], "ticker": orig,
                "open": sub["Open"], "high": sub["High"],
                "low": sub["Low"], "close": sub["Close"],
                "volume": sub["Volume"],
            }))
        df = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(
            columns=["date", "ticker", "open", "high", "low", "close", "volume"])
        return self.validate_price_df(df)

    def get_fundamentals(self, tickers: list[str], start: str, end: str) -> pd.DataFrame:
        import yfinance as yf

        rows = []
        for ticker in tickers:
            tw = _to_tw_ticker(ticker)
            info = {}
            try:
                info = yf.Ticker(tw).info or {}
            except Exception:
                info = {}
            # yfinance 的 .info 只給「目前」的快照，沒有歷史序列，這裡簡化成整段期間套用同一組
            # 快照值（有明顯偏誤，僅供快速 demo；正式回測請改用 FinMindDataSource）。
            rows.append({
                "date": pd.Timestamp(start), "ticker": ticker,
                "per": info.get("trailingPE", float("nan")),
                "pbr": info.get("priceToBook", float("nan")),
                "dividend_yield": info.get("dividendYield", float("nan")),
                "roe": info.get("returnOnEquity", float("nan")),
                "gross_margin": info.get("grossMargins", float("nan")),
                "debt_to_equity": info.get("debtToEquity", float("nan")),
                "revenue_yoy": info.get("revenueGrowth", float("nan")),
                "eps_yoy": info.get("earningsGrowth", float("nan")),
            })
        df = pd.DataFrame(rows)
        return self.validate_fundamentals_df(df)

    def get_macro(self, start: str, end: str) -> pd.DataFrame:
        import yfinance as yf

        sox = yf.download("^SOX", start=start, end=end, progress=False)["Close"]
        fx = yf.download("TWD=X", start=start, end=end, progress=False)["Close"]
        df = pd.DataFrame(index=pd.bdate_range(start, end))
        df["sox_index"] = sox.reindex(df.index)
        df["usdtwd"] = fx.reindex(df.index)
        for col in ["policy_rate", "cpi_yoy", "export_orders_yoy", "m1b_yoy", "business_cycle_signal"]:
            df[col] = float("nan")  # 這些指標 yfinance 沒有，見 macro.py 的手動 CSV 合併機制
        return df
