"""以 FinMind API 作為資料源（建議的主力資料源，台股基本面資料最完整）。

本檔案最初是在網路出口被封鎖、無法連線 https://finmind.github.io/ 查證文件的沙盒環境中
撰寫的，欄位映射當時純粹依訓練資料裡的既有知識所寫。後來另一個有網路權限的 Claude
session（在同一個 repo 的 `research/` 目錄工作）實際打過這些端點做了交叉驗證
（見 repo 根目錄 `RESEARCH_HANDOFF.md` 第五之二節），結果：

- **STOCK_DAY 舊端點欄位順序、六個 `_DATASET_*` 名稱、損益表/資產負債表科目候選字串、
  `TaiwanExchangeRate` 的 `cash_sell`/`spot_sell` 欄位 —— 全部驗證通過，不用改。**
- 唯一驗證出的問題（已修正）：`TaiwanStockMonthRevenue` 的 `date` 欄實測是「營收所屬月份
  的次月 1 日」，不是公告日（台股規定次月 10 日前公布，`date` 可能早最多 9 天），原本的
  fallback 邏輯因為 `date` 恆有值而永遠不會被觸發。現在改成不信任 `date` 欄，一律用
  「營收所屬月份 + 1 個月 + 10 天」估計公告可用日；YoY 計算也從 `pct_change(12)`（假設無
  缺漏月）改成用 `(revenue_year, revenue_month)` 顯式對齊。

即便如此，FinMind API 仍可能持續改版，建議正式使用前仍對照
https://finmind.github.io/ 抽查一次；若欄位對不上，只需要修改 `_DATASET_*` 常數與對應的
欄位映射，不用動其他模組。

免費額度：每小時 600 次 API 呼叫，且實測額度偏緊（同一個交叉驗證來源曾用不夠保守的間隔
連續打 360 次請求，跑了 110 分鐘才被迫取消）——預設請求間隔與重試退避已依實測結果調整，
不建議調快。需要環境變數 `FINMIND_TOKEN`（可留空以匿名方式呼叫，額度較低）。
"""
from __future__ import annotations

import os
import time

import pandas as pd
import requests

from .base import DataSource

FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"

# 依訓練資料所知的 FinMind dataset 名稱，使用前請對照官方文件確認。
_DATASET_PRICE = "TaiwanStockPrice"
_DATASET_PER = "TaiwanStockPER"                       # 欄位含 PER, PBR, dividend_yield
_DATASET_MONTH_REVENUE = "TaiwanStockMonthRevenue"    # 月營收，用來算 revenue_yoy
_DATASET_FINANCIAL_STATEMENTS = "TaiwanStockFinancialStatements"  # 損益表項目（type/value 長格式）
_DATASET_BALANCE_SHEET = "TaiwanStockBalanceSheet"    # 資產負債表項目（type/value 長格式）
_DATASET_EXCHANGE_RATE = "TaiwanExchangeRate"


class FinMindDataSource(DataSource):
    def __init__(self, token: str | None = None, request_interval_sec: float = 1.5,
                 max_retries: int = 5):
        self.token = token or os.environ.get("FINMIND_TOKEN", "")
        # 跨 session 實測：匿名額度很緊，360 次請求以過快的間隔呼叫曾跑了 110 分鐘才被迫取消，
        # 1.5~2 秒間隔加上下面的指數退避是實測後建議的保守設定，不要調快。
        self.request_interval_sec = request_interval_sec
        self.max_retries = max_retries

    def _request(self, dataset: str, data_id: str | None, start: str, end: str) -> pd.DataFrame:
        params = {"dataset": dataset, "start_date": start, "end_date": end}
        if data_id:
            params["data_id"] = data_id
        if self.token:
            params["token"] = self.token

        backoff = self.request_interval_sec
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            resp = requests.get(FINMIND_URL, params=params, timeout=30)
            if resp.status_code == 429:
                time.sleep(backoff)
                backoff *= 2
                continue
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("status") != 200:
                last_error = RuntimeError(f"FinMind 回傳錯誤：{payload.get('msg')}")
                # 額度用盡時 FinMind 常在 status/msg 裡回傳文字錯誤而非 HTTP 429，同樣視為
                # 可重試的情況，而不是直接視為資料集本身有問題。
                time.sleep(backoff)
                backoff *= 2
                continue
            time.sleep(self.request_interval_sec)  # 每次成功請求後固定間隔，避免累積超過額度
            return pd.DataFrame(payload["data"])

        raise last_error or RuntimeError(f"FinMind 請求重試 {self.max_retries} 次後仍失敗：{dataset}")

    def get_price_history(self, tickers: list[str], start: str, end: str) -> pd.DataFrame:
        rows = []
        for ticker in tickers:
            raw = self._request(_DATASET_PRICE, ticker, start, end)
            if raw.empty:
                continue
            rows.append(pd.DataFrame({
                "date": pd.to_datetime(raw["date"]), "ticker": ticker,
                "open": raw["open"], "high": raw["max"], "low": raw["min"],
                "close": raw["close"], "volume": raw["Trading_Volume"],
            }))
        df = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(
            columns=["date", "ticker", "open", "high", "low", "close", "volume"])
        return self.validate_price_df(df)

    def _get_per_pbr(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        raw = self._request(_DATASET_PER, ticker, start, end)
        if raw.empty:
            return pd.DataFrame(columns=["date", "ticker", "per", "pbr", "dividend_yield"])
        return pd.DataFrame({
            "date": pd.to_datetime(raw["date"]), "ticker": ticker,
            "per": raw.get("PER"), "pbr": raw.get("PBR"),
            "dividend_yield": raw.get("dividend_yield"),
        })

    def _get_revenue_yoy(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        # 多抓一年份，才能算出期初幾個月的 YoY
        buffer_start = (pd.Timestamp(start) - pd.DateOffset(years=1)).strftime("%Y-%m-%d")
        raw = self._request(_DATASET_MONTH_REVENUE, ticker, buffer_start, end)
        if raw.empty:
            return pd.DataFrame(columns=["date", "ticker", "revenue_yoy"])
        raw = raw.dropna(subset=["revenue_year", "revenue_month", "revenue"]).copy()
        raw["revenue_year"] = raw["revenue_year"].astype(int)
        raw["revenue_month"] = raw["revenue_month"].astype(int)
        raw = raw.sort_values(["revenue_year", "revenue_month"])

        # 用 (年,月) 對齊算 YoY，而非 pct_change(12)：後者假設每年剛好 12 列無缺漏，
        # 中間若有月份沒回傳資料，pct_change(12) 會用位置對齊，YoY 會錯位到別的月份。
        revenue_by_period = raw.set_index(["revenue_year", "revenue_month"])["revenue"]

        def _yoy(row) -> float:
            prev = revenue_by_period.get((row["revenue_year"] - 1, row["revenue_month"]))
            if prev is None or prev == 0:
                return float("nan")
            return row["revenue"] / prev - 1

        raw["revenue_yoy"] = raw.apply(_yoy, axis=1)

        # 公告可用日：跨 session 實測（見 RESEARCH_HANDOFF.md）發現 FinMind 的 date 欄實際上是
        # 「營收所屬月份的次月 1 日」（例如 2330 的 date=2023-01-01 對應
        # revenue_year=2022, revenue_month=12），比台股規定「次月 10 日前公布」最多早 9 天，
        # 直接拿來當公告可用日會有前視偏誤風險。因此不信任 date 欄，一律用
        # 「營收所屬月份 + 1 個月 + 10 天」估計最保守的公告可用日。
        announce_date = pd.to_datetime(
            raw["revenue_year"].astype(str) + "-" + raw["revenue_month"].astype(str) + "-01"
        ) + pd.DateOffset(months=1, days=10)
        out = pd.DataFrame({"date": announce_date, "ticker": ticker, "revenue_yoy": raw["revenue_yoy"]})
        return out[out["date"] >= start]

    def _get_financials(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        """從損益表 + 資產負債表算 ROE / 毛利率 / 負債權益比 / EPS YoY。

        FinMind 的財報資料集是「type/value」長格式（一列一個科目），科目名稱請對照官方文件，
        以下 candidate 名稱是常見寫法，對不上時請調整這裡的字串即可，不用動其他程式。
        """
        buffer_start = (pd.Timestamp(start) - pd.DateOffset(years=1, months=6)).strftime("%Y-%m-%d")
        income = self._request(_DATASET_FINANCIAL_STATEMENTS, ticker, buffer_start, end)
        balance = self._request(_DATASET_BALANCE_SHEET, ticker, buffer_start, end)
        if income.empty or balance.empty:
            return pd.DataFrame(columns=["date", "ticker", "roe", "gross_margin", "debt_to_equity", "eps_yoy"])

        def pivot(df: pd.DataFrame) -> pd.DataFrame:
            return df.pivot_table(index="date", columns="type", values="value", aggfunc="last")

        inc_p = pivot(income)
        bal_p = pivot(balance)

        def pick(df: pd.DataFrame, candidates: list[str]) -> pd.Series:
            for c in candidates:
                if c in df.columns:
                    return df[c]
            return pd.Series(index=df.index, dtype=float)

        revenue = pick(inc_p, ["Revenue", "OperatingRevenue"])
        gross_profit = pick(inc_p, ["GrossProfit"])
        net_income = pick(inc_p, ["IncomeAfterTaxes", "ProfitLoss", "NetIncome"])
        eps = pick(inc_p, ["EPS", "BasicEarningsPerShare"])
        equity = pick(bal_p, ["Equity", "EquityAttributableToOwnersOfParent"])
        liabilities = pick(bal_p, ["Liabilities", "TotalLiabilities"])

        merged_dates = sorted(set(inc_p.index) | set(bal_p.index))
        out = pd.DataFrame(index=pd.to_datetime(merged_dates))
        out["gross_margin"] = (gross_profit / revenue).reindex(out.index)
        out["roe"] = (net_income / equity).reindex(out.index)
        out["debt_to_equity"] = (liabilities / equity).reindex(out.index)
        out["eps_yoy"] = eps.reindex(out.index).pct_change(4)  # 假設季報，YoY = 前 4 期
        out["ticker"] = ticker
        out = out.reset_index().rename(columns={"index": "date"})
        # 公告日概估：財報公告通常落後會計期間結束 45 天左右
        out["date"] = out["date"] + pd.DateOffset(days=45)
        return out[out["date"] >= start]

    def get_fundamentals(self, tickers: list[str], start: str, end: str) -> pd.DataFrame:
        frames = []
        for ticker in tickers:
            per_pbr = self._get_per_pbr(ticker, start, end)
            rev_yoy = self._get_revenue_yoy(ticker, start, end)
            fin = self._get_financials(ticker, start, end)
            merged = per_pbr.merge(rev_yoy, on=["date", "ticker"], how="outer")
            merged = merged.merge(fin, on=["date", "ticker"], how="outer")
            frames.append(merged)
        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        for col in ["per", "pbr", "dividend_yield", "roe", "gross_margin",
                    "debt_to_equity", "revenue_yoy", "eps_yoy"]:
            if col not in df.columns:
                df[col] = float("nan")
        return self.validate_fundamentals_df(df)

    def get_macro(self, start: str, end: str) -> pd.DataFrame:
        raw = self._request(_DATASET_EXCHANGE_RATE, "USD", start, end)
        df = pd.DataFrame(index=pd.bdate_range(start, end))
        if not raw.empty:
            fx = pd.Series(
                raw.get("cash_sell", raw.get("spot_sell")).values,
                index=pd.to_datetime(raw["date"]),
            )
            df["usdtwd"] = fx.reindex(df.index).ffill()
        else:
            df["usdtwd"] = float("nan")
        for col in ["sox_index", "policy_rate", "cpi_yoy", "export_orders_yoy",
                    "m1b_yoy", "business_cycle_signal"]:
            df[col] = float("nan")  # FinMind 免費層沒有這些，交給 macro.py 的手動 CSV 合併
        return df
