"""以證交所（TWSE）公開資料作為價格資料源，適合只需要台股「大盤／少量個股」歷史股價、
不想申請 FinMind token 的情境。

**限制**：
- TWSE 沒有單一端點能一次拿到多年歷史，經典的 `STOCK_DAY` 端點是「一檔股票、一個月」一次
  請求，回測期間長、股票多時請求數量會很大，本實作已加上請求間隔避免被限流，但仍建議
  優先使用 FinMindDataSource；這裡主要作為備援 / 交叉驗證用。
- TWSE 公開 API 沒有現成、穩定的「歷史基本面（PER/PBR/ROE 等）」端點，因此
  `get_fundamentals` 直接拋出 NotImplementedError，請改用 FinMindDataSource 取得基本面。
- 本檔案同樣是在無法連線 twse.com.tw 驗證的沙盒環境中撰寫，端點網址/欄位若已變更，
  請對照證交所公開資訊觀測站現行文件調整。
"""
from __future__ import annotations

import time

import pandas as pd
import requests

from .base import DataSource

STOCK_DAY_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"


class TWSEDataSource(DataSource):
    def __init__(self, request_interval_sec: float = 3.0):
        self.request_interval_sec = request_interval_sec

    def get_price_history(self, tickers: list[str], start: str, end: str) -> pd.DataFrame:
        months = pd.date_range(start, end, freq="MS")
        rows = []
        for ticker in tickers:
            for month_start in months:
                params = {"response": "json", "date": month_start.strftime("%Y%m01"), "stockNo": ticker}
                resp = requests.get(STOCK_DAY_URL, params=params, timeout=30)
                time.sleep(self.request_interval_sec)
                if resp.status_code != 200:
                    continue
                payload = resp.json()
                if payload.get("stat") != "OK" or "data" not in payload:
                    continue
                for row in payload["data"]:
                    # TWSE 欄位順序：日期, 成交股數, 成交金額, 開盤, 最高, 最低, 收盤, 漲跌價差, 成交筆數
                    roc_date = row[0]  # 民國年格式，例如 113/01/05
                    y, m, d = roc_date.split("/")
                    date = pd.Timestamp(year=int(y) + 1911, month=int(m), day=int(d))

                    def to_f(s: str) -> float:
                        return float(s.replace(",", "")) if s not in ("--", "") else float("nan")

                    rows.append({
                        "date": date, "ticker": ticker,
                        "open": to_f(row[3]), "high": to_f(row[4]),
                        "low": to_f(row[5]), "close": to_f(row[6]),
                        "volume": to_f(row[1]),
                    })
        df = pd.DataFrame(rows) if rows else pd.DataFrame(
            columns=["date", "ticker", "open", "high", "low", "close", "volume"])
        return self.validate_price_df(df)

    def get_fundamentals(self, tickers: list[str], start: str, end: str) -> pd.DataFrame:
        raise NotImplementedError(
            "TWSE 公開 API 沒有穩定的歷史基本面端點，請改用 data_sources.finmind_source.FinMindDataSource。"
        )

    def get_macro(self, start: str, end: str) -> pd.DataFrame:
        raise NotImplementedError(
            "請改用 data_sources.yfinance_source.YFinanceDataSource（SOX/匯率）"
            "並搭配 data/macro_manual_template.csv 手動補上景氣燈號等指標，見 macro.py。"
        )
