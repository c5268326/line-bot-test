"""合成資料來源：純粹用來在「沒有網路權限」的環境下驗證整個回測管線的程式邏輯正確、
不會中途崩潰。產生的數字沒有任何真實市場意義，絕對不能拿來當作真實投資績效的依據。

用法：把 run_backtest.py 的 --source 參數設為 "synthetic" 即可。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import DataSource


class SyntheticDataSource(DataSource):
    def __init__(self, seed: int = 42):
        self.rng = np.random.default_rng(seed)

    def get_price_history(self, tickers: list[str], start: str, end: str) -> pd.DataFrame:
        dates = pd.bdate_range(start, end)
        rows = []
        for ticker in tickers:
            price = 50 + self.rng.uniform(0, 150)
            drift = self.rng.uniform(-0.0002, 0.0006)
            vol = self.rng.uniform(0.012, 0.028)
            # 每檔股票隨機安排 0~2 次劇烈下殺，確保停損邏輯有機會被觸發並可被驗證。
            crash_days = self.rng.choice(len(dates), size=self.rng.integers(0, 3), replace=False)
            prices = []
            for i, _ in enumerate(dates):
                shock = self.rng.normal(drift, vol)
                if i in crash_days:
                    shock -= self.rng.uniform(0.15, 0.30)
                price *= max(0.01, 1 + shock)
                prices.append(price)
            close = np.array(prices)
            open_ = close * (1 + self.rng.normal(0, 0.003, size=len(close)))
            high = np.maximum(open_, close) * (1 + np.abs(self.rng.normal(0, 0.004, size=len(close))))
            low = np.minimum(open_, close) * (1 - np.abs(self.rng.normal(0, 0.004, size=len(close))))
            volume = self.rng.integers(500_000, 20_000_000, size=len(close))
            rows.append(pd.DataFrame({
                "date": dates, "ticker": ticker,
                "open": open_, "high": high, "low": low, "close": close, "volume": volume,
            }))
        df = pd.concat(rows, ignore_index=True)
        return self.validate_price_df(df)

    def get_fundamentals(self, tickers: list[str], start: str, end: str) -> pd.DataFrame:
        # 季頻公告，公告日設在季末後 45 天（模擬財報公告延遲），符合「可用日」原則。
        quarter_ends = pd.date_range(start, end, freq="QE")
        rows = []
        for ticker in tickers:
            base_roe = self.rng.uniform(0.03, 0.25)
            base_per = self.rng.uniform(8, 30)
            base_pbr = self.rng.uniform(0.8, 6)
            base_div = self.rng.uniform(0.0, 0.07)
            base_margin = self.rng.uniform(0.1, 0.5)
            base_de = self.rng.uniform(0.2, 1.5)
            for q_end in quarter_ends:
                announce_date = q_end + pd.Timedelta(days=45)
                rows.append({
                    "date": announce_date, "ticker": ticker,
                    "per": max(1.0, base_per + self.rng.normal(0, 3)),
                    "pbr": max(0.2, base_pbr + self.rng.normal(0, 0.5)),
                    "dividend_yield": max(0.0, base_div + self.rng.normal(0, 0.01)),
                    "roe": base_roe + self.rng.normal(0, 0.02),
                    "gross_margin": min(0.9, max(0.02, base_margin + self.rng.normal(0, 0.03))),
                    "debt_to_equity": max(0.05, base_de + self.rng.normal(0, 0.1)),
                    "revenue_yoy": self.rng.normal(0.05, 0.20),
                    "eps_yoy": self.rng.normal(0.05, 0.30),
                })
        df = pd.DataFrame(rows)
        return self.validate_fundamentals_df(df)

    def get_macro(self, start: str, end: str) -> pd.DataFrame:
        dates = pd.bdate_range(start, end)
        n = len(dates)
        sox = 2000 * np.cumprod(1 + self.rng.normal(0.0003, 0.02, n))
        usdtwd = 30 + np.cumsum(self.rng.normal(0, 0.02, n))
        policy_rate = np.full(n, 1.5) + np.cumsum(self.rng.normal(0, 0.001, n))
        cpi_yoy = self.rng.normal(0.02, 0.01, n)
        export_orders_yoy = self.rng.normal(0.03, 0.15, n)
        m1b_yoy = self.rng.normal(0.05, 0.08, n)
        business_cycle_signal = np.clip(self.rng.normal(25, 6, n), 9, 45)
        return pd.DataFrame({
            "sox_index": sox, "usdtwd": usdtwd, "policy_rate": policy_rate,
            "cpi_yoy": cpi_yoy, "export_orders_yoy": export_orders_yoy,
            "m1b_yoy": m1b_yoy, "business_cycle_signal": business_cycle_signal,
        }, index=dates)
