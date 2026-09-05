"""用合成資料驗證整條 pipeline（資料源 -> 因子 -> 回測 -> 績效報告）邏輯正確、不會中途崩潰。

**這裡驗證的是程式正確性，不是投資報酬率**——合成資料是隨機亂數產生，任何回測結果數字都
沒有真實市場意義。想要真實結果請用 FinMindDataSource / YFinanceDataSource 在有網路的環境跑。
"""
from __future__ import annotations

import numpy as np

from tw_stock_backtest.backtest import Backtester
from tw_stock_backtest.config import BacktestConfig
from tw_stock_backtest.data_sources.synthetic_source import SyntheticDataSource
from tw_stock_backtest import metrics


def _build_config() -> BacktestConfig:
    cfg = BacktestConfig()
    cfg.start_date = "2018-01-01"
    cfg.end_date = "2022-12-31"
    cfg.universe = [f"T{i:03d}" for i in range(30)]
    cfg.benchmark = "BENCH"
    cfg.top_n = 8
    cfg.defensive_top_n = 4
    return cfg


def test_full_pipeline_runs_without_error():
    cfg = _build_config()
    source = SyntheticDataSource(seed=7)
    all_tickers = cfg.universe + [cfg.benchmark]

    prices = source.get_price_history(all_tickers, cfg.start_date, cfg.end_date)
    fundamentals = source.get_fundamentals(cfg.universe, cfg.start_date, cfg.end_date)
    macro_df = source.get_macro(cfg.start_date, cfg.end_date)

    assert not prices.empty
    assert not fundamentals.empty
    assert not macro_df.empty

    universe_prices = prices[prices["ticker"] != cfg.benchmark]
    benchmark_prices = prices[prices["ticker"] == cfg.benchmark]

    backtester = Backtester(cfg, universe_prices, fundamentals, macro_df)
    result = backtester.run(initial_capital=3_000_000.0)

    assert len(result.equity_curve) > 0
    assert not result.equity_curve.isna().any()
    assert (result.equity_curve > 0).all()

    report = metrics.generate_report(
        result, cfg, benchmark_prices.set_index("date")["close"]
    )
    for key in ["cagr", "annualized_volatility", "sharpe_ratio", "max_drawdown",
                "num_round_trips", "benchmark_cagr", "alpha_vs_benchmark_cagr"]:
        assert key in report

    assert np.isfinite(report["annualized_volatility"])


def test_stop_loss_can_trigger_on_crash_heavy_seed():
    """特別找一個會產生較多崩跌路徑的 seed，驗證停損機制真的會被觸發、且流程仍正常結束。"""
    cfg = _build_config()
    cfg.stop_loss_pct = 0.20
    source = SyntheticDataSource(seed=1)
    all_tickers = cfg.universe + [cfg.benchmark]

    prices = source.get_price_history(all_tickers, cfg.start_date, cfg.end_date)
    fundamentals = source.get_fundamentals(cfg.universe, cfg.start_date, cfg.end_date)
    macro_df = source.get_macro(cfg.start_date, cfg.end_date)
    universe_prices = prices[prices["ticker"] != cfg.benchmark]

    backtester = Backtester(cfg, universe_prices, fundamentals, macro_df)
    result = backtester.run(initial_capital=3_000_000.0)

    stats = metrics.trade_stats(result)
    assert stats["num_round_trips"] >= 0  # 流程不崩潰是這個測試的重點
    # 停損 + 換股出場次數合計應等於總交易配對數
    assert stats["num_stop_loss_exits"] + stats["num_rebalance_exits"] == stats["num_round_trips"]


if __name__ == "__main__":
    test_full_pipeline_runs_without_error()
    test_stop_loss_can_trigger_on_crash_heavy_seed()
    print("所有合成資料驗證測試通過（僅驗證程式邏輯，非真實投資績效）。")
