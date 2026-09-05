"""回測引擎：依因子複合分數選股、週/月/季再平衡、-20% 停損出場。

**已知簡化（誠實列出）**：
- 再平衡只處理「因子排名被淘汰 / 新入選」的股票，既有且仍在名單內的持股不會被強制調整回
  等權重，這是簡化過的實作，不是完整的目標權重（target-weight）再平衡。真正上線使用建議
  補上定期權重再平衡的邏輯。
- 停損判斷用「前一交易日收盤價」是否already跌破成本 -20%，成立後於「當日開盤」出場，
  避免用到出場當下還沒發生的價格資訊（look-ahead bias）。
- 股票以「一張＝1000股」為交易單位，符合台股實務下單規則。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import factors as F
from . import macro as M
from .config import BacktestConfig


@dataclass
class Trade:
    date: pd.Timestamp
    ticker: str
    action: str   # "buy" | "sell"
    reason: str   # "rebalance" | "stop_loss"
    price: float
    shares: float
    amount: float


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    trades: list[Trade] = field(default_factory=list)
    macro_score: pd.Series | None = None


class Backtester:
    def __init__(self, config: BacktestConfig, prices: pd.DataFrame,
                 fundamentals: pd.DataFrame, macro_df: pd.DataFrame):
        self.config = config
        self.prices = prices
        self.fundamentals = fundamentals
        self.macro_df = macro_df

    def run(self, initial_capital: float = 1_000_000.0) -> BacktestResult:
        cfg = self.config
        price_factors = F.build_price_factors(self.prices, cfg.factor_windows)
        fund_factors = F.build_fundamental_factors(self.fundamentals)
        macro_score = M.compute_macro_score(self.macro_df)

        close_pivot = self.prices.pivot(index="date", columns="ticker", values="close")
        open_pivot = self.prices.pivot(index="date", columns="ticker", values="open")
        calendar = close_pivot.index.sort_values()
        calendar = calendar[(calendar >= pd.Timestamp(cfg.start_date)) & (calendar <= pd.Timestamp(cfg.end_date))]
        if len(calendar) == 0:
            raise ValueError("回測期間內沒有任何價格資料，請檢查 start_date/end_date 與資料源回傳結果。")

        period = {"W": "W", "M": "M", "Q": "Q"}.get(cfg.rebalance_freq, "M")
        calendar_series = calendar.to_series()
        decision_dates = set(calendar_series.groupby(calendar.to_period(period)).max().tolist())

        cash = initial_capital
        positions: dict[str, dict] = {}
        pending_targets: list[str] | None = None
        trades: list[Trade] = []
        equity_curve: dict[pd.Timestamp, float] = {}

        for i, date in enumerate(calendar):
            if pending_targets is not None:
                targets, pending_targets = pending_targets, None
                for ticker in list(positions.keys()):
                    if ticker not in targets:
                        px = open_pivot.at[date, ticker] if ticker in open_pivot.columns else np.nan
                        if not np.isnan(px):
                            cash += self._sell(positions, ticker, px, date, trades, "rebalance")
                new_tickers = [t for t in targets if t not in positions]
                if new_tickers and cash > 0:
                    budget_per_stock = cash / len(new_tickers)
                    for ticker in new_tickers:
                        px = open_pivot.at[date, ticker] if ticker in open_pivot.columns else np.nan
                        if np.isnan(px) or px <= 0:
                            continue
                        cost_rate = 1 + cfg.buy_commission_rate
                        lots = np.floor(budget_per_stock / (px * cost_rate * 1000))
                        shares = lots * 1000
                        if shares <= 0:
                            continue
                        amount = shares * px * cost_rate
                        cash -= amount
                        positions[ticker] = {"shares": shares, "entry_price": px, "entry_date": date}
                        trades.append(Trade(date, ticker, "buy", "rebalance", px, shares, amount))

            if i > 0:
                prev_date = calendar[i - 1]
                for ticker in list(positions.keys()):
                    pos = positions[ticker]
                    holding_days = i - calendar.get_indexer([pos["entry_date"]])[0]
                    if holding_days < cfg.min_holding_days_before_stop:
                        continue
                    prev_close = close_pivot.at[prev_date, ticker] if ticker in close_pivot.columns else np.nan
                    if np.isnan(prev_close):
                        continue
                    if prev_close <= pos["entry_price"] * (1 - cfg.stop_loss_pct):
                        px = open_pivot.at[date, ticker] if ticker in open_pivot.columns else np.nan
                        if not np.isnan(px):
                            cash += self._sell(positions, ticker, px, date, trades, "stop_loss")

            if date in decision_dates:
                tickers = list(close_pivot.columns)
                snapshot = F.as_of_snapshot(price_factors, fund_factors, date, tickers)
                if not snapshot.empty:
                    scores = F.composite_score(snapshot, cfg.factor_weights)
                    m_score = macro_score.get(date, 0.0)
                    top_n = cfg.defensive_top_n if m_score < cfg.macro_defensive_threshold else cfg.top_n
                    pending_targets = F.select_targets(snapshot, scores, top_n, cfg.min_avg_daily_turnover)

            market_value = cash
            for ticker, pos in positions.items():
                px = close_pivot.at[date, ticker] if ticker in close_pivot.columns else np.nan
                if np.isnan(px):
                    px = pos["entry_price"]
                market_value += pos["shares"] * px
            equity_curve[date] = market_value

        return BacktestResult(
            equity_curve=pd.Series(equity_curve).sort_index(),
            trades=trades,
            macro_score=macro_score,
        )

    def _sell(self, positions: dict, ticker: str, price: float, date: pd.Timestamp,
              trades: list[Trade], reason: str) -> float:
        pos = positions.pop(ticker)
        proceeds = pos["shares"] * price * (1 - self.config.sell_commission_rate - self.config.sell_tax_rate)
        trades.append(Trade(date, ticker, "sell", reason, price, pos["shares"], proceeds))
        return proceeds
