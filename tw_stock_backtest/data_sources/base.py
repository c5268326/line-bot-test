"""所有資料源共用的抽象介面與資料表 schema 定義。

任何新的資料來源（FinMind / TWSE / yfinance / 自己的 CSV）都應該繼承 DataSource，
並回傳下列三張固定 schema 的 DataFrame，這樣 factors.py / backtest.py 完全不需要
知道資料實際從哪裡來。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

# 價格面板 schema：長格式（long format）
PRICE_COLUMNS = ["date", "ticker", "open", "high", "low", "close", "volume"]

# 基本面面板 schema：長格式，一列代表某檔股票在某個「公告可用日」的最新基本面數值。
# 務必使用「公告日」而非「所屬會計期間」，否則會有 look-ahead bias。
FUNDAMENTAL_COLUMNS = [
    "date", "ticker",
    "per", "pbr", "dividend_yield",
    "roe", "gross_margin", "debt_to_equity",
    "revenue_yoy", "eps_yoy",
]

# 總經面板 schema：寬格式，index 為日期
MACRO_COLUMNS = [
    "sox_index", "usdtwd", "policy_rate", "cpi_yoy",
    "export_orders_yoy", "m1b_yoy", "business_cycle_signal",
]


class DataSource(ABC):
    """資料來源抽象介面。"""

    @abstractmethod
    def get_price_history(self, tickers: list[str], start: str, end: str) -> pd.DataFrame:
        """回傳長格式價格面板，欄位見 PRICE_COLUMNS。"""

    @abstractmethod
    def get_fundamentals(self, tickers: list[str], start: str, end: str) -> pd.DataFrame:
        """回傳長格式基本面面板，欄位見 FUNDAMENTAL_COLUMNS。date 為「公告可用日」。"""

    @abstractmethod
    def get_macro(self, start: str, end: str) -> pd.DataFrame:
        """回傳寬格式總經面板，index 為日期，欄位見 MACRO_COLUMNS（可有缺值，由呼叫端處理）。"""

    def validate_price_df(self, df: pd.DataFrame) -> pd.DataFrame:
        missing = set(PRICE_COLUMNS) - set(df.columns)
        if missing:
            raise ValueError(f"price DataFrame 缺少欄位: {missing}")
        return df[PRICE_COLUMNS].sort_values(["ticker", "date"]).reset_index(drop=True)

    def validate_fundamentals_df(self, df: pd.DataFrame) -> pd.DataFrame:
        missing = set(FUNDAMENTAL_COLUMNS) - set(df.columns)
        if missing:
            raise ValueError(f"fundamentals DataFrame 缺少欄位: {missing}")
        return df[FUNDAMENTAL_COLUMNS].sort_values(["ticker", "date"]).reset_index(drop=True)
